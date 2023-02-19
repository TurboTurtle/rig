# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import sys
import os

from rigging.commands import RigCmd
from rigging.dbus_connection import RigDBusConnection
from rigging.exceptions import DBusServiceDoesntExistError


class DestroyCmd(RigCmd):
    """
    Terminate a rig without triggering its actions, or generating an archive
    containing any compiled data until now.

    This command may be called for a single rig, like so:

    rig destroy my-test-rig

    Or for multiple rigs:

    rig destroy my-test-rig my-other-rig anotherrig
    """

    parser_description = 'Terminate a rig without triggering its actions'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('rig_id', nargs='+',
                            help='The ID or name of the rig(s) to destroy')
        parser.add_argument('--force', action='store_true', default=False,
                            help='Force remove a dead rig')

    def execute(self):
        for target in self.options['rig_id']:
            try:
                self._run_destroy(target)
                sys.stdout.write(f"Rig '{target}' destroyed\n")
            except Exception as err:
                # don't stop iteration due to one bad attempt
                sys.stdout.write(f"{err}\n")

    def _run_destroy(self, target):
        try:
            conn = RigDBusConnection(target)
            ret = conn.destroy_rig()
            if not ret.success:
                raise Exception(f"Failed to destroy rig: {ret.result}")
        except DBusServiceDoesntExistError as exc:
            raise Exception(f"No such rig: {target}")

