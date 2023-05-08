# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>
# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.commands import RigCmd
from rigging.utilities import load_rig_monitors
from subprocess import Popen


class ListMonitorsCmd(RigCmd):
    """
    Used to list locally supported monitors, and optionally provide detailed
    information on individual monitors.

    If given a value for the --show option, this command will instead wrap to
    the man page for the given monitor, which will take the format of
    `rig-monitors-$name`. This redirection allows us to maintain the formatting
    flexibility of man pages, without relying on users to trawl through all
    available pages.
    """

    parser_description = 'Show information about locally supported monitors'
    name = 'list-monitors'

    @classmethod
    def add_parser_options(cls, parser):
        parser.add_argument('-s', '--show',
                            help='Get detailed information on a monitor')

    def execute(self):
        monitors = load_rig_monitors()
        if not self.options['show']:
            self.ui_logger.info(
                'The following rigs are supported by your system:\n'
            )
            for mon in monitors:
                self.ui_logger.info(
                    f"\t{monitors[mon].monitor_name:<15}\t\t"
                    f"{monitors[mon].description}")
            self.ui_logger.info(
                "\nFor more detailed information, please see "
                "'rig list-monitors -s <name>'"
            )
        else:
            try:
                _mon = monitors[self.options['show']]
            except KeyError:
                raise Exception(
                    f"Invalid monitor specified: {self.options['show']}"
                )

            p = Popen(
                ['man', f'rig-monitors-{_mon.monitor_name}'],
                shell=False
            )
            p.communicate()
