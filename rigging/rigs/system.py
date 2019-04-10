# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.rigs import BaseRig

import psutil
import time


class System(BaseRig):
    '''
    Monitor overall system utilization metrics.

    These metrics may cover CPU, memory, and/or disk usage.
    '''

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
        return parser

    @property
    def watching(self):
        # TODO: properly define what we're watching
        return 'system utilization'

    @property
    def trigger(self):
        ret = ''
        for conf in self.conf:
            ret += "%s above %s " % conf, self.conf[conf]
        return ret

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
        if self.args['memperc']:
            mem['percent'] = self.args['memperc']
        if cpu:
            self.add_watcher_thread(self.watch_util_metrics,
                                    args=(cpu, psutil.cpu_times_percent,
                                          'cpu')
                                    )
        if self.args['cpuperc']:
            self.add_watcher_thread(self.watch_cpu_utilization,
                                    args=(self.args['cpuperc'],))
        if mem:
            self.add_watcher_thread(self.watch_util_metrics,
                                    args=(mem, psutil.virtual_memory,
                                          'memory')
                                    )

    def watch_cpu_utilization(self, perc):
        '''
        Watch the given poller for a threshold above perc.

        Positional arguments:
            perc        percentage value (float) to use as threshold
        '''
        # First iteration returns meaningless data
        psutil.cpu_percent()
        while True:
            _val = psutil.cpu_percent(interval=1)
            if _val > perc:
                self.log_info("CPU usage at %s%%, exceeding threshold of %s"
                              % (_val, perc))
                return True

    def watch_util_metrics(self, metrics, poller, resource):
        '''
        Watch the given metric from psutil to see if it exceeds the given
        thresold.

        This is passed a dict where the keys are the metrics returned by
        psutil, and the value is the threshold for triggering the rig

        Positional arguments:
            metrics     dict of keys as the metric to watch and the value
                        being our trigger threshold
            poller      method to call to gain stats to compare against
            resource    what kind of resource we're watching
        '''
        _watching = ', '.join("{!s}={!r}".format(key, val)
                              for (key, val) in metrics.items())
        self.log_debug("Beginning watch of %s utilization of: %s"
                       % (resource, _watching))
        # some psutil methods are relative to the previous call, so make the
        # first call before looping to set the right context and not trigger
        # on the first poll.
        _poll = poller()
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
            time.sleep(1)

    def _check_memory(self, metric, val, threshold):
        '''
        Helper method to check if the rig should trigger for memory metrics
        based on how that specific metric needs to be compared to current
        stats
        '''
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
