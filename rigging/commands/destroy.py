# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.commands import RigCmd


class DestroyCmd(RigCmd):
    """
    Forcibly destroys a rig.
    """

    parser_description = 'Terminate a rig without triggering its actions'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('-i', '--id', help='The ID of the rig to destroy')