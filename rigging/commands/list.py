# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import dbus

from rigging.commands import RigCmd
from rigging.connection import RigDBusConnection


class ListCmd(RigCmd):
    """
    List all known rigs currently deployed on the system. This will provide an
    at-a-glance overview of existing rigs. For more detailed information, such
    as the full configuration of a given rig, users would want to use the
    `rig info` command.
    """

    def execute(self):
        bus = dbus.SessionBus()
        rigs = {}
        for service_name in bus.list_names():
            if service_name.startswith("com.redhat.Rig."):
                rig_id = service_name.split(".")[-1]
                conn = RigDBusConnection(rig_id)
                ret = conn.describe()
                if ret.success:
                    rigs[rig_id] = ret.result

        nameln = max(max([len(rigs[r]['name']) for r in rigs], default=0), 14)
        monln = max(
            max([len(rigs[r]['monitors']) for r in rigs], default=0),
            19
        )
        actln = max(
            max([len(rigs[r]['actions']) for r in rigs], default=0),
            19
        )

        self.ui_logger.info(
            f"{'NAME':<{nameln+1}}{'STARTED':<21}{'MONITORS':<{monln+1}}"
            f"{'ACTIONS':<{actln+1}}{'STATUS':<10}"
        )

        for rig in rigs:
            _rig = rigs[rig]
            self.ui_logger.info(
                f"{_rig['name'][:nameln]:<{nameln+1}}"
                f"{_rig['start_time'].split('.')[0].replace('T', ' '):<21}"
                f"{_rig['monitors'][:monln]:<{monln+1}}"
                f"{_rig['actions'][:actln]:<{actln+1}}"
                f"{_rig['status']:<10}"
            )
