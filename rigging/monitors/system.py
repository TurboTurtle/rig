# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import os
import psutil

from rigging.monitors import BaseMonitor


class SystemMonitor(BaseMonitor):
    """
    Monitor overall system utilization metrics for areas such as CPU, memory,
    disk usage, temperature, etc..
    """

    monitor_name = 'system'

    def configure(self, temperature=None, loadavg=None, loadavg_interval=1):
        """
        :param temperature: Threshold temperature in Celsius of the CPU
        :param loadavg: Threshold for relative system load reported by loadavg
        :param loadavg_interval: Which loadavg minute interval to track
        """
        if not any([temperature, loadavg]):
            raise Exception(
                'Must specify at least one of \'temperature\', or \'loadavg\''
            )

        self.stats = {}

        if temperature is not None:
            self._configure_temp_monitor(temperature)

        if loadavg is not None:
            self._configure_loadavg_monitor(loadavg, loadavg_interval)

    def _configure_temp_monitor(self, temperature):
        _t = psutil.sensors_temperatures()
        if not any(_i.endswith('temp') for _i in _t.keys()):
            raise Exception(
                'local hardware does not appear to report CPU temperatures'
            )
        try:
            temp = int(temperature)
        except Exception:
            raise Exception(
                f"'temperature' must be integer. Not "
                f"{temperature.__class__}."
            )
        self.add_monitor_thread(self.watch_temperature, (temp,))
        self.stats['temperature'] = f"{temp}C"

    def _configure_loadavg_monitor(self, loadavg, loadavg_interval):
        try:
            float(loadavg)
        except Exception:
            raise Exception(f"'loadavg' must be integer or float. "
                            f"Not {loadavg.__class__}.")
        if int(loadavg_interval) not in [1, 5, 15]:
            raise Exception(f"'loadavg_interval' must be 1, 5, or 15. "
                            f"Not {loadavg_interval}.")
        self.add_monitor_thread(self.watch_loadavg,
                                (loadavg, loadavg_interval))
        self.stats['loadavg'] = f">= {loadavg} (interval: {loadavg_interval})"

    def watch_temperature(self, temp):
        """
        Monitor the system temperature and if it meets or exceeds the specified
        temperature, trigger.

        :param temp: Temperature in Celsius to trigger when met or exceeded
        """
        # get the key for the temperature reading
        _t = psutil.sensors_temperatures()
        _key = [k for k in _t.keys() if k.endswith('temp')][0]
        while True:
            cur_temp = psutil.sensors_temperatures()[_key][0].current
            if cur_temp >= temp:
                self.logger.info(
                    f"System temperature is {cur_temp} C, exceeding threshold "
                    f"of {temp} C"
                )
                return True
            self.wait_loop()

    def watch_loadavg(self, threshold, interval):
        """
        Monitor the ongoing system loadavg as reported by the OS.

        :param threshold: loadavg value to trigger on if met or exceeded
        :param interval: Which reporting interval to use - 1, 5, or 15 minutes
        """
        idx = (1, 5, 15).index(interval)
        if isinstance(threshold, str):
            threshold = float(threshold)
        while True:
            _val = round(os.getloadavg()[idx], 2)
            if _val >= threshold:
                self.logger.info(
                    f"System {interval}-minute loadavg at {_val}, exceeding "
                    f"threshold of {threshold}"
                )
                return True
            self.wait_loop()

    @property
    def monitoring(self):
        return self.stats
