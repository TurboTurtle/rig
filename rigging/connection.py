# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import json
import os

from multiprocessing.connection import Client
from rigging.exceptions import SendError, ResponseError, DeadRigError

RIG_SOCK_DIR = '/var/run/rig'


class RigConnection():
    """
    Used to abstract communication with an existing rig over the socket created
    at /var/run/rig for that particular rig.
    """

    def __init__(self, rig_name):
        """
        :param rig_name: The name of the rig, which correlates to the name of
        the socket
        """
        self.name = rig_name
        self.sock_path = os.path.join(RIG_SOCK_DIR, self.name)
        if not os.path.exists(self.sock_path):
            raise OSError(f"No socket found for rig {self.name}")
        try:
            # if the rig has died but left its socket behind, this will fail
            Client(self.sock_path)
        except Exception:
            raise DeadRigError(rig_name)

    def _communicate(self, command):
        """
        Send a rig an instruction and then return the result directly to the
        calling command (after json loading) for further handling

        :param command: The command to have the rig perform
        :return: The result of the command
        """
        with Client(self.sock_path) as client:
            try:
                client.send_bytes(json.dumps(command).encode())
            except Exception as err:
                raise SendError(self.name, err)

            try:
                return json.loads(client.recv_bytes(4096).decode())
            except Exception as err:
                raise ResponseError(self.name, err)

    def _create_instruction(self, instruction):
        """
        Create an instruction to send via _communicate() that can be serialized
        via json

        :param instruction: What to instruct the rig to do
        :return: A dict formatted in the way a rig expects socket communication
                 to look like
        """
        return {
            'command': instruction,
            'rig_name': self.name,
        }

    def destroy_rig(self):
        """
        Instruct the rig to self-terminate without triggering any configured
        actions or generating an archive.
        """
        return self._communicate(self._create_instruction('destroy'))
