# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import psutil

from rigging.monitors import BaseMonitor


class CpuMonitor(BaseMonitor):
    """
    Monitors for various CPU utilization metrics such as overall use, time
    spent in iowait/steal, etc...

    Users may specify any or all of the metrics reported by psutil, aside from
    idle, or may monitor the overall CPU usage.
    """

    monitor_name = 'cpu'

    def configure(self, percent=None, iowait=None, steal=None, system=None,
                  nice=None, guest=None, guest_nice=None, user=None):
        """
        :param percent: CPU usage threshold expressed as a percentage
        :param iowait: Threshold for percent of time spent in iowait
        :param steal: Threshold for percent of time spent in steal
        :param system: Threshold for percent of time spent in system
        :param nice: Threshold for the percent of time spent in nice
        :param guest: Threshold for the percent of time spent in guest
        :param guest_nice: Threshold for the percent of time spent in
                           guest_nice
        :param user: Threshold for percent of time spent in user
        """
        _metrics = {
            'percent': percent,
            'iowait': iowait,
            'steal': steal,
            'system': system,
            'nice': nice,
            'guest': guest,
            'guest_nice': guest_nice,
            'user': user
        }

        if not any(m is not None for m in _metrics):
            raise Exception(
                f"Must specify at least one of "
                f"{', '.join(m for m in _metrics.keys())}"
            )

        for _m in _metrics:
            if _metrics[_m] is not None:
                try:
                    if float(_metrics[_m]) > 100:
                        raise Exception(f"'{_m}' cannot exceed 100.")
                except (TypeError, ValueError):
                    raise Exception(
                        f"'{_m}' must be integer or float. Not {_m.__class__}."
                    )

        if percent is not None:
            self.add_monitor_thread(
                self.watch_cpu_utilization,
                (float(percent), )
            )

        # save this to the instance so that self.monitoring can report on it
        self.metrics = _metrics.copy()

        _metrics.pop('percent')

        if any(m is not None for m in _metrics.values()):
            self.add_monitor_thread(self.watch_cpu_metrics, (_metrics, ))

    def watch_cpu_utilization(self, perc):
        """
        Monitor the overall CPU utilization expressed as a percentage.

        :param perc: Utilization rate to trigger on when met or exceeded
        """
        # First iteration returns meaningless data
        psutil.cpu_percent()
        while True:
            _val = psutil.cpu_percent(interval=self.config['interval'])
            if _val > perc:
                self.logger.info(
                    f"CPU usage at {_val}%, exceeding threshold of {perc}%"
                )
                return True

    def watch_cpu_metrics(self, metrics):
        """
        Monitor specific aspects of CPU usage, such as iowait time, as a
        percentage of overall CPU time.

        Note that with this method, we monitor _all_ CPU metrics in a single
        thread and with a single polling interval.

        :param metrics: A dict of metrics and their respective thresholds
        """
        _monitor = {}
        for metric in metrics:
            if metrics[metric] is not None:
                _monitor[metric] = float(metrics[metric])
        # first return is usually garbage data
        psutil.cpu_times_percent()
        while True:
            _poll = psutil.cpu_times_percent(self.config['interval'])
            for _mon in _monitor:
                _val = float(getattr(_poll, _mon))
                if _val >= _monitor[_mon]:
                    self.logger.info(
                        f"CPU metric {_mon} is at {_val}%, exceeding threshold"
                        f" of {_monitor[_mon]}%"
                    )
                    return True

    @property
    def monitoring(self):
        _info = {}
        for metric in self.metrics:
            if self.metrics[metric] is not None:
                _info[metric] = f">= {self.metrics[metric]}%"
        return _info
