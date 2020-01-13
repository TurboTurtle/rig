# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.rigs import BaseRig
from warnings import catch_warnings, simplefilter

import os
import psutil


class System(BaseRig):
    """
    Monitor overall system utilization metrics.

    These metrics may cover CPU, memory, and/or disk usage.
    """

    parser_description = 'Monitor overall system utilization metrics'
    _cpu_metrics = ['iowait', 'steal', 'nice', 'guest', 'user']
    _memory_metrics = ['available', 'used', 'free', 'slab']

    def set_parser_options(self, parser):
        for metric in self._cpu_metrics:
            _opt = "--%s" % metric
            parser.add_argument(_opt, type=float,
                                help="Threshold for %s" % metric)
        for mem in self._memory_metrics:
            _option = "--%s" % mem
            parser.add_argument(_option, type=int,
                                help="Threshold for %s memory in MiB" % mem)
        parser.add_argument('--cpuperc', type=float,
                            help="Total CPU usage as a percentage")
        parser.add_argument('--memperc', type=float,
                            help="Total memory usage as a percentage")
        parser.add_argument('--loadavg', type=float,
                            help='Single interval load average threshold')
        parser.add_argument('--loadavg-interval', type=int, default=1,
                            choices=[1, 5, 15],
                            help='Which minute interval to watch. Default: 1')
        parser.add_argument('--temp', type=int,
                            help="CPU temperature in degrees Celsius")
        parser.add_argument('--cpu-id', default=0, type=int,
                            help="Physical CPU package ID to monitor temp for")
        return parser

    @property
    def watching(self):
        # TODO: properly define what we're watching
        return 'system utilization'

    @property
    def trigger(self):
        ret = []
        for conf in self.conf:
            if self.conf[conf]:
                ret.append("%s above %s" % (conf, self.conf[conf]))
        if self.get_option('cpuperc'):
            ret.append("CPU usage above %s%%" % self.get_option('cpuperc'))
        if self.get_option('memperc'):
            ret.append("Memory usage above %s%%" % self.get_option('memperc'))
        if self.get_option('loadavg'):
            ret.append("System loadavg above %s" % self.get_option('loadavg'))
        if self.get_option('temp'):
            ret.append("CPU temperature above %S" % self.get_option('temp'))
        return ', '.join(r for r in ret)

    def _compile_opts_as_dict(self):
        self.conf = {}
        for arg in self.args:
            if arg in self._cpu_metrics or arg in self._memory_metrics:
                self.conf[arg] = self.args[arg]

    def setup(self):
        self._compile_opts_as_dict()
        # CPU metrics
        cpu = {}
        for _met in self._cpu_metrics:
            if _met in self.conf.keys() and self.conf[_met]:
                cpu[_met] = self.conf[_met]
        mem = {}
        for _mem in self._memory_metrics:
            if _mem in self.conf.keys() and self.conf[_mem]:
                mem[_mem] = self.conf[_mem]
        if self.get_option('memperc'):
            mem['percent'] = self.get_option('memperc')
        if cpu:
            self.add_watcher_thread(self.watch_util_metrics,
                                    args=(cpu, psutil.cpu_times_percent,
                                          'cpu')
                                    )
        if self.get_option('cpuperc'):
            self.add_watcher_thread(self.watch_cpu_utilization,
                                    args=(self.get_option('cpuperc'),))
        if mem:
            self.add_watcher_thread(self.watch_util_metrics,
                                    args=(mem, psutil.virtual_memory,
                                          'memory')
                                    )
        if self.get_option('loadavg'):
            self.add_watcher_thread(self.watch_loadavg,
                                    args=(self.get_option('loadavg')))
        if self.get_option('temp'):
            cpu_id = self._get_package_index(self.get_option('cpu_id'))
            self.add_watcher_thread(self.watch_temp,
                                    args=(self.get_option('temp'),
                                          cpu_id))

    def watch_temp(self, temp, phys_id=0):
        """
        Watch CPU temperature for meeting or exceeding the temperature given.

        By default this will watch CPU Package 0, meaning the first physically
        installed CPU. This may be overridden by the --cpu-id option. Please
        note this refers _only_ to physical CPU packages, and does not support
        individual core monitoring.

        If the given phys_id does not exist, default back to CPU Package 0.

        Positional arguments:
            :param temp:        Degrees celsius to trigger on when met

        Optional arguments:
            :param phys_id:     ID of the physical CPU package to monitor as
                                defined by --cpu-id
        """
        while True:
            cur_temp = psutil.sensors_temperatures()['coretemp'][phys_id]
            if cur_temp.current >= temp:
                self.log_info("CPU temperature is %s C, exceeding threshold "
                              "of %s C" % (cur_temp.current, temp))
                return True
            self.wait_loop()

    def _get_package_index(self, phys_id):
        """
        Find the index in psutil's returned list of temperatures for the given
        physical CPU package ID.
        """
        # squelch runtimewarnings from psutil, which are not important to
        # our purposes here with temperature data
        with catch_warnings():
            simplefilter("ignore", RuntimeWarning)
            _temps = psutil.sensors_temperatures()
        for _temp in _temps['coretemp']:
            # Only consider physical CPUs, not cores
            if 'Package id' not in _temp.label:
                continue
            if _temp.label.split()[-1] == str(phys_id):
                return _temps['coretemp'].index(_temp)
        # If the physical ID does not exist, fallback to package 0, and log
        self.log_warn("Requested CPU package ID %s does not exist. Using CPU "
                      "package 0 instead" % phys_id)
        return 0

    def watch_loadavg(self, threshold):
        """
        Watch overall system loadavg for exceeding value given to the
        --loadavg option.

        Will watch the 1/5/15 minute interval value based on the value of
        --loadavg-interval
        """
        idx = (1, 5, 15).index(self.get_option('loadavg_interval'))
        while True:
            _val = os.getloadavg()[idx]
            if _val >= threshold:
                self.log_info(
                    "System %s-minute loadavg at %s, exceeding threshold of %s"
                    % (self.get_option('loadavg_interval'), _val, threshold)
                )
                return True
            self.wait_loop()

    def watch_cpu_utilization(self, perc):
        """
        Watch the given poller for a threshold above perc.

        Positional arguments:
            perc        percentage value (float) to use as threshold
        """
        # First iteration returns meaningless data
        psutil.cpu_percent()
        while True:
            _val = psutil.cpu_percent(interval=1)
            if _val > perc:
                self.log_info("CPU usage at %s%%, exceeding threshold of %s"
                              % (_val, perc))
                return True

    def watch_util_metrics(self, metrics, poller, resource):
        """
        Watch the given metric from psutil to see if it exceeds the given
        thresold.

        This is passed a dict where the keys are the metrics returned by
        psutil, and the value is the threshold for triggering the rig

        Positional arguments:
            metrics     dict of keys as the metric to watch and the value
                        being our trigger threshold
            poller      method to call to gain stats to compare against
            resource    what kind of resource we're watching
        """
        _watching = ', '.join("{!s}={!r}".format(key, val)
                              for (key, val) in metrics.items())
        self.log_debug("Beginning watch of %s utilization of: %s"
                       % (resource, _watching))
        # some psutil methods are relative to the previous call, so make the
        # first call before looping to set the right context and not trigger
        # on the first poll.
        poller()
        while True:
            _poll = poller()
            for metric in metrics:
                _val = float(getattr(_poll, metric))
                if resource == 'cpu':
                    if _val > metrics[metric]:
                        self.log_info("CPU utilization of %s is %s, exceeding "
                                      "threshold of %s"
                                      % (metric, _val, metrics[metric]))
                        return True
                elif resource == 'memory':
                    if self._check_memory(metric, _val, metrics[metric]):
                        return True
            self.wait_loop()

    def _check_memory(self, metric, val, threshold):
        """
        Helper method to check if the rig should trigger for memory metrics
        based on how that specific metric needs to be compared to current
        stats
        """
        if metric == 'percent':
            if val > threshold:
                self.log_info("Total memory usage is %s%%, exceeding theshold "
                              "of %s" % (val, threshold))
                return True
        elif metric in ['available', 'free']:
            val = int(val / 1024 / 1024)
            if val < threshold:
                self.log_info("%s memory is %s MiB, below threshold of %s MiB"
                              % (metric, val, threshold))
                return True
        elif metric in ['used', 'slab']:
            val = int(val / 1024 / 1024)
            if val > threshold:
                self.log_info("%s memory is %s MiB, exceeding theshold of %s"
                              % (metric, val, threshold))
                return True
        return False
