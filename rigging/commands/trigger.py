# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

from rigging.commands import RigCmd
from rigging.connection import RigDBusConnection


class TriggerCmd(RigCmd):
    """
    Used to manually trigger a deployed rig, instead of waiting for any of the
    defined monitors to trigger normally.

    This will immediately cause all monitors to stop, and all defined actions
    to be taken as if the rig was triggered by one of the monitors.

    If multiple rigs are specified, they will be triggered one at a time, but
    will not wait for the preceding rig to finish triggering its actions.
    """

    parser_description = 'Manually trigger a rig right now'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('rig_id', nargs='+',
                            help='The ID or name of the rig(s) to trigger')

    def execute(self):
        for target in self.options['rig_id']:
            try:
                _rig = RigDBusConnection(target)
                _rig.trigger()
                self.ui_logger.info(f"Rig '{target}' triggered")
            except Exception as err:
                self.ui_logger.error(f"Failed triggering '{target}': {err}")
