# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import os
import time

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from rigging.exceptions import DestroyRig


class BaseMonitor():
    """
    This class serves as the building block for any monitors that rig supports.

    A monitor...monitors the system for a specific condition, and when that
    condition is met will inform the rig it is deployed with that the condition
    has been met, at which point the rig will trigger any configured actions
    it needs to take.
    """
    monitor_name = 'Undefined'

    def __init__(self, config, logger):
        """
        The initializer for any monitor will set the base configuration of the
        rig (so, global config options) and then pass the monitor-specific
        configuration from the rigfile to `configure()`.
        """
        self._monitor_threads = []
        self.config = config
        self.logger = logger

    def configure(self, **kwargs):
        """
        Monitors will need to override this method, and any options or tunables
        that the monitor supports or requires will need to be defined as
        parameters in the override.

        Required options are easily set this way by simply making those
        parameters required in the call to `configure()`. If there is any
        default value set for a parameter, it is considered optional.

        Any validation that the monitor needs to do should also be performed
        here, and raise an Exception if there is a problem.

        Finally, this method should be used to define the monitoring logic,
        by leveraging `add_monitor_thread()`. The typical design is that a
        monitor will use `configure()` to do any prep work, while implementing
        the monitoring logic in other methods, which will be referenced in
        calls to `add_monitor_thread()`.
        """
        raise NotImplementedError(
            f"Monitor {self.monitor_name} does not self-configure"
        )

    def start_monitor(self):
        """
        Start the monitor's thread pool that will control the monitoring of
        whatever resource the monitor is designed to watch.

        This method will block until *ANY* of the methods added via
        `add_monitor_thread()` return, at which point this method will return
        which will then cause the rig to be triggered.
        """
        try:
            futures = []
            self.pool = ThreadPoolExecutor()
            for wthread in self._monitor_threads:
                futures.append(self.pool.submit(wthread[0], *wthread[1]))
            results = wait(futures, return_when=FIRST_COMPLETED)
            result = list(results[0])[0].result()
            return result
        except DestroyRig as err:
            self.logger.info(
                f"Destroying rig without triggering actions due to: {err}"
            )
            raise
        except Exception as err:
            self.logger.error(
                f"Exception caught for monitor {self.monitor_name}: {err}"
            )
            self.logger.error(
                "Terminating without triggering due to previous error"
            )
            os._exit(1)

    def add_monitor_thread(self, method, args=()):
        """
        Define a new thread that this monitor should create and watch for the
        purposes of triggering a rig. Any distinct resource that should be
        monitored should be given a separate thread via this method, unless
        it is sufficiently beneficial to have a single thread monitoring
        multiple resources or conditions.

        :param method: A callable method to run in a thread
        :param args: Any args, passed as a tuple, to pass to `method`
        """
        if not callable(method):
            raise Exception(
                f"Unable to add watcher thread. Target must be a callable "
                f"method, received {method.__class__}"
            )
        if not isinstance(args, tuple):
            args = (args, )
        self._monitor_threads.append((method, args))

    def wait_loop(self):
        """
        Helper function to ensure that if a monitor needs to pause, it is able
        to do so consistently and according to the set value of `interval`.
        """
        time.sleep(self.config['interval'])

    def get_info(self):
        """
        Used to return information about this monitor for the `rig info`
        command. This will in turn call the monitor's `monitoring` property.

        :return: dict containing the monitor type and what it is configured to
                 monitor
        """
        return {
            'type': self.monitor_name,
            'monitoring': self.monitoring
        }

    @property
    def monitoring(self):
        """
        This SHOULD BE overridden by specific monitors.
        This method should describe in human-friendly terms what the monitor
        is watching for in order to trigger the rig.
        """
        return 'undefined'
