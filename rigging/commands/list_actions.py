# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>
# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.commands import RigCmd
from rigging.utilities import load_rig_actions
from subprocess import Popen


class ListActionssCmd(RigCmd):
    """
    Used to list locally supported actions, and optionally provide detailed
    information on individual actions.

    If given a value for the --show option, this command will instead wrap to
    the man page for the given action, which will take the format of
    `rig-actions-$name`. This redirection allows us to maintain the formatting
    flexibility of man pages, without relying on users to trawl through all
    available pages.
    """

    parser_description = 'Show information about locally supported actions'
    name = 'list-actions'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('-s', '--show',
                            help='Get detailed information on an action')

    def execute(self):
        actions = load_rig_actions()
        if not self.options['show']:
            self.ui_logger.info(
                'The following actions are supported by your system:\n'
            )
            for act in actions:
                self.ui_logger.info(
                    f"\t{actions[act].action_name:<15}\t\t"
                    f"{actions[act].description}")
            self.ui_logger.info(
                "\nFor more detailed information, please see "
                "'rig list-actions -s <name>'"
            )
        else:
            try:
                _act = actions[self.options['show']]
            except KeyError:
                raise Exception(
                    f"Invalid monitor specified: {self.options['show']}"
                )

            p = Popen(
                ['man', f'rig-actions-{_act.action_name}'],
                shell=False
            )
            p.communicate()
