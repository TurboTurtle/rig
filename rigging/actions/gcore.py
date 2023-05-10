# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import psutil
import signal
import os

from rigging.actions import BaseAction
from rigging.utilities import get_proc_pids


class GcoreAction(BaseAction):
    """
    This action will attempt to collect a coredump of a process, or multiple
    processes, via the gcore utility provided by GDB.

    Users may provide a single process or a list of processes, as either PIDs
    or process names. Names will attempt to be converted to PIDs during rig
    setup.

    If the 'freeze' parameter is set to true, this action will send a SIGSTOP
    to each process before attempting to generate the coredump, and then send a
    SIGCONT after the attempt is complete.

    This action is repeatable, so multiple coredumps can be generated for the
    same process if desired.
    """

    action_name = 'gcore'
    description = 'Generate an application coredump via gcore'
    priority = 1
    required_binaries = ('gcore',)
    repeatable = True

    def configure(self, procs, freeze=False):
        """
        :param procs: A process or list of processes to collect a core dump of
        :param freeze: Freeze the process before core dumping, then thaw after
                       a core has been collected
        """
        self.procs = {}
        if isinstance(procs, str | int):
            procs = [procs]

        if isinstance(procs, list):
            for pid in procs:
                try:
                    int(pid)
                    self.procs[pid] = [pid]
                except Exception:
                    self.procs[pid] = get_proc_pids([pid])
        else:
            raise Exception(f"'procs' must be given as string, integer, or "
                            f"list, not {procs.__class__}")

        if not self.procs:
            raise Exception(
                f"No PIDs found matching procs '{', '.join(p for p in procs)}'"
            )

        _pids = []
        for _procs in self.procs.values():
            _pids.extend(_procs)

        self.logger.debug(
            f"PID list for generating core dumps determined to be: "
            f"{', '.join(str(p) for p in _pids)}"
        )
        self.freeze = freeze

    def freeze_pid(self, pid):
        """
        Send a SIGSTOP to the specified pid
        """
        self.logger.info(f"Freezing pid {pid}")
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except Exception as err:
            self.logger.error(f"Could not send SIGSTOP to {pid}: {err}")
        return False

    def thaw_pid(self, pid):
        """
        Send a SIGCONT to the specified pid
        """
        self.logger.info(f"Thawing pid {pid}")
        try:
            os.kill(pid, signal.SIGCONT)
            return True
        except Exception as err:
            self.logger.error(f"Could not send SIGCONT to {pid}: {err}")
        return False

    def trigger(self):
        for proc in self.procs:
            for pid in self.procs[proc]:
                if not psutil.pid_exists(int(pid)):
                    self.logger.error(
                        f"Cannot collect coredump for pid {pid} - process no "
                        f"longer exists"
                    )
                    continue

                if str(proc) == str(pid):
                    _name = os.path.join(self.tmpdir,
                                         f"core-{self.repeat_count}")
                else:
                    _name = os.path.join(self.tmpdir,
                                         f"core-{self.repeat_count}.{proc}")

                self._collect_coredump(pid, _name)

    def _collect_coredump(self, pid, filename):
        """
        Perform the gcore command execution to generate a coredump for the
        given pid.

        :param pid: The PID or name of the process to coredump, if given a name
                    action will match _all_ PIDs with that command name
        :param filename: The filename to write the coredump to, which will be
                         suffixed with '.$pid'
        :return: True
        """

        fname = f"{filename}.{pid}"

        _frozen = False
        if self.freeze:
            _frozen = self.freeze_pid(pid)

        self.logger.debug(f"Collecting coredump of {pid} at {fname}")
        ret = self.exec_cmd(f"gcore -o {filename} {pid}")
        if ret['status'] == 0:
            if os.path.isfile(fname):
                self.add_archive_file(fname)
            else:
                self.logger.info(
                    "Coredump not generated at expected location, attempting "
                    "to determine core filename"
                )
                _fname = ret['stdout'].splitlines()[-2].split()[-1]
                if os.path.isfile(_fname):
                    self.logger.info(
                        f"Coredump {_fname} found. Adding to archive"
                    )
                    self.add_archive_file(_fname)
                else:
                    self.logger.error(
                        "Coredump not generated at expected location, and "
                        "could not determine an alternative location"
                    )
        else:
            self.logger.error(
                "Error collecting coredump via gcore. See debug logs "
                "for details"
            )
            self.logger.debug(f"gcore output: {ret['stdout']}")

        if _frozen:
            self.thaw_pid(pid)

    @property
    def produces(self):
        return [
          f"core-{count}.{proc}" for count in range(self.config['repeat'] + 1)
          for proc in self.procs
        ]
