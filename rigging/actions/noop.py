# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.actions import BaseAction


class Noop(BaseAction):
    '''
    Do nothing. Used for testing rig configurations.
    '''

    action_name = 'noop'
    enabling_opt = 'noop'
    enabling_opt_desc = 'Do nothing. Use for testing rig configurations'

    def add_action_options(self, parser):
        parser.add_argument('--noop', action='store_true',
                            help=self.enabling_opt_desc)
        return parser

    def trigger_action(self):
        self.log_info('No-op action triggered. Doing nothing.')
        return True
