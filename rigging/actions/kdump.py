# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.actions import BaseAction


class Kdump(BaseAction):
    """
    Generate a vmcore via kdump

    Note that this action does NOT perform any verification of kdump settings
    or configuration. It is assumed that kdump has been properly tested on the
    node prior to a rig being deployed with this action.
    """

    action_name = 'kdump'
    enabling_opt = 'kdump'
    enabling_opt_desc = 'Generate a vmcore when rig is triggered'
    priority = 10000  # this MUST run last in all cases

    def add_action_options(self, parser):
        parser.add_argument('--kdump', action='store_true',
                            help=self.enabling_opt_desc)
        parser.add_argument('--sysrq', default=None,
                            help='set /proc/sys/kernel/sysrq to this value')
        return parser

    def pre_action(self):
        sysrq = self.get_option('sysrq')
        if sysrq is not None:
            if sysrq == 0:
                self.log_error('Setting /proc/sys/kernel/sysrq to 0 will '
                               'disable kdump, cannot continue.')
                return False
            self.log_info("Setting /proc/sys/kernel/sysrq to %s" % sysrq)
            with open('/proc/sys/kernel/sysrq', 'w') as kern_sysrq:
                try:
                    kern_sysrq.write(sysrq)
                except Exception as err:
                    self.log_error("Failed to set /proc/sys/kernel/sysrq: %s"
                                   % err)
                return False
        return True

    def trigger_action(self):
        self.log_info('Writing \'c\' to /proc/sysrq-trigger - look in your '
                      'configured crash location for a vmcore after reboot')
        with open('/proc/sysrq-trigger', 'w') as sysrq:
            sysrq.write('c')

    def action_info(self):
        return 'A vmcore saved in your configured crash dump location'
