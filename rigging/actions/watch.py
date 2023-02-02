# Copyright (C) 2022 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from datetime import datetime, timedelta
from rigging.actions import BaseAction, check_exists
from subprocess import Popen, PIPE, STDOUT
from threading import Thread

import shlex
import time
import os


class BackgroundCollector(Thread):
    """Used by this action to run a thread in the background that will
    periodically run a command or collect a file's content.
    """

    def __init__(self, interval):
        self.interval = interval
        self._running = False
        self.stopped = False
        super(BackgroundCollector, self).__init__(daemon=True)

    def start(self):
        self._running = True
        super(BackgroundCollector, self).start()

    def stop(self):
        self._running = False

    def _continue(self):
        """Block for up to rig-configured-interval seconds, before returning
        True to allow the run() loop to continue on to the next iteration.
        If during this time self._running is set to False
        (e.g. via self.stop()), immediately return False to break out of the
        run loop without having to wait for the entire interval to pass

        We need to use this approach instead of a threading.Event() pill
        because we double fork the rig's main process in order to run in the
        background.

        :returns:   True if run() should continue executing, else false
        :rtype:     ``bool``
        """
        _max = datetime.now() + timedelta(seconds=self.interval)
        while datetime.now() < _max:
            if not self._running:
                return False
            time.sleep(1)
        return True

    def run(self):
        # get the first set of data when the rig starts, not after the first
        # interval has passed
        self._run_and_write()
        while self._continue():
            self._run_and_write()

        self.stopped = True

    @staticmethod
    def _write_with_header(fobj, content):
        """
        Write our timestamped header to the output file followed by whatever
        has been collected by the background thread.

        :param fobj:    The open file object to write the header to
        :param content: The content to write to the file
        """
        try:
            fobj.write(f"==== {datetime.now()} ====\n")
            fobj.write(f"{content}\n")
        except Exception as err:
            fobj.write(f"Rig error: Unable to write content: {err}")

    def _run_and_write(self):
        """
        What is actually executed in the background while the thread is
        running.

        Will be overridden by the actual collector being implemented.
        """
        raise NotImplementedError


class FileCollector(BackgroundCollector):
    """
    Used to collect the contents of a particular file as defined by this rig.
    """

    def __init__(self, to_copy, fname, interval):
        """
        :param to_copy:     The name of the file to capture
        :type to_copy:      ``str``

        :param fname:       Path to save the file contents to, including tmpdir
        :type fname:        ``str``

        :param interval:    Time to wait between subsequent collections
        :type interval:     ``int``
        """
        self.to_copy = to_copy
        self.fname = fname
        super(FileCollector, self).__init__(interval=interval)

    def _run_and_write(self):
        with open(self.fname, 'a') as out_file:
            try:
                with open(self.to_copy, 'r') as _to_copy:
                    self._write_with_header(out_file, _to_copy.read())
            except Exception as err:
                msg = f"Unable to copy contents of {self.to_copy}: {err}"
                self._write_with_header(out_file, msg)


class CmdCollector(BackgroundCollector):
    """
    This class is used to control the execution and output storing of a command
    used by this rig. Each command that we'll need to repeatedly capture will
    be instantiated via a CmdMonitor() and run in a background thread.
    """

    def __init__(self, cmd, fname, interval):
        """
        :param cmd:     The command to execute and collect the output of
        :type cmd:      ``str``

        :param fname:   Where to save the output to, including rig's tmpdir
        :type fname:    ``str``

        :param interval:    Time to wait between subsequent ``cmd`` executions
        :type interval:     ``int``
        """
        self.cmd = shlex.split(cmd)
        self.fname = fname
        super(CmdCollector, self).__init__(interval=interval)

    def _run_and_write(self):
        """
        Run the monitor's command and write the output to requested file
        """
        with open(self.fname, 'a') as ofile:
            _proc = Popen(self.cmd, shell=False, stdout=PIPE,
                          stderr=STDOUT, encoding='utf-8')
            try:
                timeout = max(1, self.interval / 2)
                msg, serr = _proc.communicate(timeout=timeout)
            except Exception as err:
                _proc.terminate()
                msg = f"Could not collect command output: {err}"
            self._write_with_header(ofile, msg)


class WatchAction(BaseAction):
    """
    This action will record specified files or command output over the life of
    the rig. This is inspired by the `monitor.sh` script used by Red Hat
    Support engineers typically in conjunction with networking related issues.

    See https://access.redhat.com/articles/1311173#monitorsh-script-notes-3
    for context.

    The `use_standard_set` parameter, if true, will automatically add a set of
    files and commands to watch that is sourced from the script above.

    'files' should be provided as a dictionary, with a mandatory 'path' key
    that should reference the source file to record. If the 'dest' key is
    provided, this will serve as the destination filename to which the source
    file is continually recorded to. If this key is omitted, the destination
    filename is automatically generated as the basename of the path.

    'commands' should be provided as a list of strings that serve as the
    command to execute (use a list even if only providing a single command).
    Note that environment variables and in-line scripts will NOT survive the
    parsing of the rigfile. If these are necessary, write a new script file and
    then specify that scripts as a member of 'commands'.
    """

    action_name = 'watch'

    def configure(self, files=None, commands=None, use_standard_set=False):
        """
        :param files: A list of files to watch and routinely copy
        :type files: list of dicts with at minimum a 'path' key. An optional
                     'dest' key determines the filename within the archive
                     to write to

        :param commands: A list of commands to routinely execute and capture
                         the output of
        :type commands: list of strings

        :param use_standard_set: Toggle the use of the standard set of files
                                 and commands watched by Red Hat support's
                                 monitor.sh script
        :type use_standard_set: bool
        """
        self.files = []
        self.commands = []
        if files is not None:
            for _file in files:
                if not isinstance(_file, dict):
                    raise Exception(
                        f"Files must be provided as dictionaries, not "
                        f"{_file.__class__}"
                    )
                if 'path' not in _file:
                    raise Exception("file watchers requires the 'path' key")
                if 'dest' in _file:
                    dest = _file['dest'].replace('/', '_')
                else:
                    dest = _file['path'].split('/')[-1]

                self.files.append({'path': _file['path'], 'dest': dest})

        if commands is not None:
            for _cmd in commands:
                if not isinstance(_cmd, str):
                    raise Exception(
                        f"Commands must be provided as strings, not "
                        f"{_cmd.__class__}"
                    )
                _cmdfn = _cmd.split()[0]
                if not check_exists(_cmdfn) and not os.path.exists(_cmdfn):
                    raise Exception(
                        f"Cannot watch command '{_cmd.split()[0]}': "
                        f"command not found"
                    )
                _outfn = _cmd.replace(' ', '_').replace('/', '.').lstrip('.')
                self.commands.append({
                    'command': _cmd,
                    'filename': _outfn
                })

        if use_standard_set:
            self.logger.debug(
                'Standard set requested, adding items sourced from monitor.sh'
            )
            self.files.extend([
                {'path': '/proc/interrupts', 'dest': 'interrupts'},
                {'path': '/proc/vmstat', 'dest': 'vmstat'},
                {'path': '/proc/net/softnet_stat', 'dest': 'softnet_stat'},
                {'path': '/proc/softirqs', 'dest': 'softirqs'},
                {'path': '/proc/net/sockstat', 'dest': 'sockstat'},
                {'path': '/proc/net/sockstat6', 'dest': 'sockstat6'},
                {'path': '/proc/net/dev', 'dest': 'netdev'},
                {'path': '/proc/net/sctp/assocs', 'dest': 'sctp_assocs'},
                {'path': '/proc/net/sctp/snmp', 'dest': 'sctp_snmp'}
            ])

            for cmd in ['netstat -s', 'nstat -az', 'ss -noemitaup', 'ps -alfe',
                        'top -c -b -n 1', 'numastat', 'ip neigh show',
                        'tc -s qdisc']:
                if not check_exists((cmd.split()[0])):
                    self.logger.debug(
                        f"Command '{cmd.split()[0]}' not found locally, "
                        f"skipping from standard set"
                    )
                    continue
                self.commands.append({
                    'command': cmd,
                    'filename': cmd.replace(' ', '_')
                })

            mdevs = self.exec_cmd('tc qdisc show')
            if mdevs['status'] == 0:
                for mdevln in mdevs['stdout'].splitlines():
                    if 'qdisc mq' in mdevln:
                        mdev = mdevln.split('dev')[1].strip().split()[0]
                        tccmd = f"tc -s class show dev {mdev}"
                        self.commands.append({
                            'command': tccmd,
                            'filename': tccmd.replace(' ', '_')
                        })
        if not self.files and not self.commands:
            raise Exception('No valid files or commands to watch provided')

    def pre_action(self):
        """
        Launch the background threads to perform monitoring
        """
        self.procs = {}

        for cmd in self.commands:
            _outfn = os.path.join(self.tmpdir, cmd['filename'])
            self.procs[cmd['filename']] = CmdCollector(
                cmd['command'], _outfn, self.config['interval']
            )

        for _file in self.files:
            _outfn = os.path.join(self.tmpdir, _file['dest'])
            self.procs[_file['dest']] = FileCollector(
                _file['path'], _outfn, self.config['interval']
            )

        for proc in self.procs:
            self.logger.debug(f"Starting '{proc}' periodic collector")
            self.procs[proc].start()
        return True

    def trigger(self):
        # send the stop signal to all monitors
        for proc in self.procs:
            self.procs[proc].stop()
            self.add_archive_file(self.procs[proc].fname)
        while not all([p.stopped for p in self.procs.values()]):
            stopped = ', '.join(
                p for p in self.procs if not self.procs[p].stopped
            )
            self.logger.info(f"Waiting for collectors {stopped} to stop")
            time.sleep(self.config['interval'])
