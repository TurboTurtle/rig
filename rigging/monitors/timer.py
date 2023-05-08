# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import re
import time

from datetime import timedelta, datetime
from rigging.monitors import BaseMonitor
from rigging.exceptions import DestroyRig

UNITS = {
    's': 'seconds',
    'm': 'minutes',
    'h': 'hours',
    'd': 'days',
    'w': 'weeks'
}


def convert_to_seconds(timestr):
    _times = {}
    for m in re.finditer(r'(?P<val>\d+(\.\d+)?)(?P<unit>[smhdw]?)',
                         timestr, re.I):
        unit = UNITS.get(m.group('unit').lower(), 'seconds')
        _times[unit] = float(m.group('val'))
    return int(timedelta(**_times).total_seconds())


class TimerMonitor(BaseMonitor):
    """
    This monitor is used to set an upper bound for how long a given rig will
    run for before terminating. The default behavior is to trigger the rig when
    the timer expires, but this can be controlled via the `trigger_on_expiry`
    parameter within the rigfile - setting the value to False will cause the
    rig to simply terminate without triggering.

    The `timeout` parameter accepts either a raw value in seconds, or a string
    representation using standard signifiers such as `s` for seconds, `m` for
    minutes, `h` for hours, `d` for days, and `w` for weeks. You can use
    multiple of these signifiers in a single string passed to this parameter,
    e.g. `1d 2h 30m` for 1 day, 2 hours, and 30 minutes from the time the rig
    starts.
    """

    monitor_name = 'timer'
    description = 'Trigger after a set amount of time has elapsed'

    def configure(self, timeout, trigger_on_expiry=True):
        """
        :param timeout: How long to allow the rig to run for
        :type timeout: `int` or `str` representation of time value

        :param trigger_on_expiry: Should the rig trigger actions after timeout?
        :type trigger_on_expiry: `bool`
        """
        self.trigger_on_expiry = trigger_on_expiry
        try:
            seconds = convert_to_seconds(str(timeout))
        except Exception as err:
            raise Exception(f"Unable to parse timeout string: {err}")
        self.add_monitor_thread(self.monitor_timeout, (seconds, ))

    def monitor_timeout(self, seconds):
        """
        This method just sleeps until the timeout is up. If trigger_on_expiry
        was configured (default: True), the rig will be triggered and actions
        will be fired off as expected. If set to False, the rig will terminate
        without triggering actions.

        :param seconds: The timeout given to the rig, converted to seconds
        """
        when = datetime.now() + timedelta(seconds=seconds)
        self.logger.info(
            f"Beginning timer monitor. Timeout will expire at "
            f"{when.strftime('%Y/%m/%d %I:%M %p')}"
        )

        while True:
            diff = (when - datetime.now()).total_seconds()
            if diff < 1:
                break
            time.sleep(diff / 2)

        self.logger.info("Timer monitor timeout expired.")
        if self.trigger_on_expiry:
            return True
        raise DestroyRig(
            'timeout expired in timer monitor with trigger_on_expiry = False'
        )
