# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import datetime as dt
import glob
import os
import shlex
import subprocess

from pipes import quote
from rigging.actions import BaseAction

TCPDUMP_BIN = '/usr/sbin/tcpdump'
# -Z is needed to avoid the privilege drop that happens before opening the
# first savefile, which would result in an ENOPERM and a failed rig
TCPDUMP_OPTS = '-Z root -n'


class TcpdumpAction(BaseAction):
    """
    This action will start a packet capture via tcpdump in the background when
    the rig is created. The packet capture will run until the rig is triggered,
    at which point the capture will end and the resulting pcap file(s) will be
    added to the archive created for the rig.

    Users must specify the interface on which to listen. This needs to be an
    existing interface, or 'any' which tcpdump supports to listen to all
    interfaces at once.

    This action also supports passing a tcpdump expression/filter to the
    packet capture. See pcap-filter(7) for expression syntax.
    """

    action_name = 'tcpdump'
    description = 'Collect a packet capture during the life of the rig'
    required_binaries = ('tcpdump',)
    priority = 2

    def configure(self, interface, capture_count=1, capture_size=10,
                  snapshot_length=0, expression=None):
        """
        :param interface: The interface to capture packets on
        :param capture_count: The number of capture files to keep
        :param capture_size: The maximum size of individual capture files
        :param snapshot_length: Snapshot length of packets captured
        :param expression: A filter to pass to tcpdump to only record packets
                           matching the given criteria
        """
        try:
            self.capture_count = int(capture_count)
        except Exception:
            raise Exception(f"'capture_count' must be integer, not "
                            f"{capture_count.__class__}")

        try:
            self.capture_size = int(capture_size)
        except Exception:
            raise Exception(f"'capture_size' must be integer, not "
                            f"{capture_size.__class__}")

        try:
            self.snapshot_length = int(snapshot_length)
        except Exception:
            raise Exception(f"'snapshot_length' must be integer, not"
                            f"{snapshot_length.__class__}")

        self.interface = interface

        _date = dt.datetime.today().strftime("%d-%m-%Y-%H:%M:%S")
        hostname = self.exec_cmd('hostname')['stdout'].strip()
        name = f"{hostname}-{_date}-{self.interface}"

        self.tcpdump_cmd = (
            f"{TCPDUMP_BIN} {TCPDUMP_OPTS} -i {self.interface} "
            f"-s {self.snapshot_length} -C {self.capture_size} "
            f"-W {self.capture_count}"
        )

        if expression:
            self.tcpdump_cmd += f" {quote(expression)}"

        if self._validate_tcpdump_cmd():
            self.outfn = f"{self.tmpdir}/{name}.pcap"
            self.tcpdump_cmd += f" -w {self.outfn}"

    def _validate_tcpdump_cmd(self):
        """
        Perform an initial execution of the command to verify it will actually
        run. This allows expressions to be vetted directly by tcpdump.

        :return: True if successful, else raise Exception
        """
        proc, devnull = self.start_tcpdump()
        try:
            # if we hit an error in the first second of execution, it means
            # tcpdump was configured incorrectly
            stdout, stderr = proc.communicate(timeout=1)
            if stderr:
                raise Exception(
                    stderr.decode('utf-8', 'ignore').strip()
                )
            self.logger.debug(
                "tcpdump command validated with no errors returned"
            )
        except subprocess.TimeoutExpired:
            pass
        except Exception as err:
            raise Exception(
                f"Error during validation of tcpdump command: {err}"
            )
        finally:
            proc.terminate()
            devnull.close()

        return True

    def pre_action(self):
        """
        Launch the actual tcpdump packet capture in the background, so that
        we have meaningful data throughout the life of the rig.
        """
        try:
            self.proc, self.devnull = self.start_tcpdump()
        except Exception as err:
            raise Exception(
                f"Error while starting background packet capture: {err}"
            )

    def start_tcpdump(self):
        """
        Launch a tcpdump command in the background
        """

        self.logger.debug(f"Running tcpdump as '{self.tcpdump_cmd}'")
        devnull = open(os.devnull, 'w')
        proc = subprocess.Popen(shlex.split(self.tcpdump_cmd), shell=False,
                                stdout=devnull, stderr=subprocess.PIPE)
        return proc, devnull

    def trigger(self):
        self.logger.debug("Stopping tcpdump")
        try:
            self.proc.terminate()
            _files = glob.glob(self.outfn + '*')
            for _file in _files:
                self.add_archive_file(_file)
            self.devnull.close()
        except Exception as err:
            self.logger.error(f"Could not stop tcpdump: {err}")
        return True

    def cleanup(self):
        try:
            self.proc.terminate()
            self.devnull.close()
        except Exception as err:
            self.logger.error(f"Error during tcpdump cleanup: {err}")

    @property
    def produces(self):
        basename = self.outfn.split('/')[-1]
        return [f"{basename}{x}" for x in range(self.capture_count)]
