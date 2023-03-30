# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import json

from rigging.commands import RigCmd
from rigging.connection import RigDBusConnection
from rigging.exceptions import DBusServiceDoesntExistError


class InfoCmd(RigCmd):
    """
    Used to display info about a specific rig that has already been deployed.
    """

    parser_description = 'Display info about a particular rig'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('rig_id', help='The ID of the rig')

    def execute(self):
        try:
            conn = RigDBusConnection(self.options['rig_id'])
            _i = conn.info().result
            self.ui_logger.info(json.dumps(_i, indent=4))
        except DBusServiceDoesntExistError:
            raise Exception(f"No such rig: {self.options['rig_id']}")
