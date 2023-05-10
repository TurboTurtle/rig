# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.actions import BaseAction


class KdumpAction(BaseAction):
    """
    This action will trigger the use of the kdump service, which will create a
    vmcore on the system. Kdump creates these vmcores when a system encounters
    a kernel panic, and this action will artificially generate a panic by use
    of the /proc/sysrq-trigger facility.

    Note that this action does NOT perform any verification of kdump settings
    or configuration. It is assumed that kdump has been properly tested on the
    node prior to a rig being deployed with this action.

    This action has special handling within rig to ensure it runs _after_ the
    rig's archive has been created due to the nature of kdump causing system
    resets. As such, the vmcore will not be included in the rig's archive.
    """

    action_name = 'kdump'
    description = 'Generate a system vmcore via kdump'
    priority = 10000

    def configure(self, enabled, sysrq=None):
        """
        :param enabled: Used as a fail-safe to ensure this action is actually
                        desired by a configuration
        :param sysrq: Set /proc/sys/kernel/sysrq to this value
        """
        if enabled is not True:
            raise Exception(
                f"'enabled' parameter must be set to true, not '{enabled}'"
            )

        try:
            if sysrq and not int(sysrq) == 0:
                raise Exception(
                    "Setting 'sysrq' to 0 will disable kdump, cannot continue"
                    " configuring this action"
                )
        except Exception:
            raise Exception(f"'sysrq' must be integer, not {sysrq.__class__}")

        self.sysrq = sysrq

    def pre_action(self):
        if self.sysrq is not None:
            self.logger.info(f"Setting /proc/sys/kernel/sysrq to {self.sysrq}")
            with open('/proc/sys/kernel/sysrq', 'w') as kern_sysrq:
                try:
                    kern_sysrq.write(self.sysrq)
                except Exception as err:
                    self.logger.error(
                        f"Failed to set /proc/sys/kernel/sysrq: {err}"
                    )
                return False
        return True

    def trigger(self):
        self.logger.info(
            'Writing \'c\' to /proc/sysrq-trigger - look in your '
            'configured crash location for a vmcore after reboot'
        )
        with open('/proc/sysrq-trigger', 'w') as sysrq:
            sysrq.write('c')

    @property
    def produces(self):
        return "A vmcore at your configured crash location following restart"
