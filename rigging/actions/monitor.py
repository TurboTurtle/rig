# Copyright (C) 2022 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from datetime import datetime, timedelta
from rigging.actions import BaseAction
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
        """Block for up to self.interval seconds, before returning True to
        allow the run() loop to continue on to the next iteration. If during
        this time self._running is set to False (e.g. via self.stop()), then
        immediately return False to break out of the run loop without having
        to wait for the entire interval to pass

        We need to use this approach instead of a threading.Event() pill
        because of the fact that we double fork the rig's main process in order
        to run in the background.

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

    def _write_with_header(self, fobj, content):
        """
        Write our timestamped header to the output file followed by whatever
        has been collected by the background thread.

        :param fobj:    The open file object to write the header to
        """
        try:
            now = datetime.now()
            fobj.write("==== %s ====\n" % now)
            fobj.write(content + '\n')
        except Exception as err:
            fobj.write("Rig error: Unable to write content: %s" % err)

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
        with open(self.to_copy, 'r') as _to_copy:
            with open(self.fname, 'a') as out_file:
                self._write_with_header(out_file, _to_copy.read())


class CmdCollector(BackgroundCollector):
    """
    This class is used to control the execution and output storing of a command
    used by this rig. Each command that we'll need to repeatedly capture will
    be instantiated via a CmdMonitor() and run in a background thread.
    """

    def __init__(self, cmd, fname, interval):
        """
        :param cmd:     The command the execute and collect the output of
        :type cmd:      ``str``

        :param fname:   Where to save the output to, including rig's tmpdir
        :type fname:    ``str``

        :param stopper: An event to watch for when the thread should exit
        :type stopper:  ``threading.Event``

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
                msg = "Could not collect command output: %s" % err
            self._write_with_header(ofile, msg)


class SysMonitor(BaseAction):
    """
    Record various system stats over the course of the rig's lifetime until
    the rig triggers or is destroyed.

    This is inspired by the `monitor.sh` script used by Red Hat Support
    engineers typically in conjunction with networking related issues.

    See https://access.redhat.com/articles/1311173#monitorsh-script-notes-3
    for context.

    The --disable-monitor-defaults option toggles a standard set of monitors
    that are largely based on the script above.
    """

    action_name = 'monitor'
    enabling_opt = 'monitor'
    enabling_opt_desc = ('record various system statistics over the lifetime '
                         'of the rig')

    @classmethod
    def add_action_options(cls, parser):
        parser.add_argument('--monitor', action='store_true',
                            help=cls.enabling_opt_desc)
        parser.add_argument('--monitor-files', default=[], action='rigextend',
                            help='List of files to periodically monitor')
        parser.add_argument('--monitor-commands', default=[],
                            action='rigextend',
                            help='List of commands to periodically execute')
        parser.add_argument('--disable-monitor-defaults', action='store_true',
                            help='Disable the default resource monitors')

    def pre_action(self):
        """
        Launch the background threads to perform monitoring
        """
        self.procs = {}
        _cmdmons = []
        _filemons = []

        for cmd in self.get_option('monitor_commands'):
            _cmd = cmd.split()
            # tuples used to create the CmdCollectors.
            # Form of (executable, options)
            _cmdmons.append((_cmd[0], ' '.join(_cmd[1:])))

        for _fname in self.get_option('monitor_files'):
            _filemons.append(_fname)

        if not self.get_option('disable_monitor_defaults'):
            _cmdmons.extend([
                ('netstat', '-s'),
                ('nstat', '-az'),
                ('ss', '-noemitaup'),
                ('ps', '-alfe'),
                ('top', '-c -b -n 1'),
                ('numastat', ''),
                ('ip', 'neigh show'),
                ('tc', '-s qdisc')
            ])

            mdevs = self.exec_cmd('tc qdisc show')
            if mdevs['status'] == 0:
                for mdevln in mdevs['stdout'].splitlines():
                    if 'qdisc mq' in mdevln:
                        mdev = mdevln.split('dev')[1].strip().split()[0]
                        opts = "-s class show dev %s" % mdev
                        _cmdmons.append(('tc', opts))

            _filemons.extend([
                '/proc/interrupts',
                '/proc/vmstat',
                '/proc/net/softnet_stat',
                '/proc/softirqs',
                '/proc/net/sockstat',
                '/proc/net/sockstat6',
                ('/proc/net/dev', 'netdev'),
                ('/proc/net/sctp/assocs', 'sctp_assocs'),
                ('/proc/net/sctp/snmp', 'sctp_snmp')
            ])

        for cmd in _cmdmons:
            if self._check_exists(cmd[0]):
                cmdfn = "%s_%s" % (cmd[0],
                                   cmd[1].replace(' ', '_').replace('/', '.'))
                _out = os.path.join(self.tmp_dir, cmdfn)
                _cmdstr = ' '.join(c for c in cmd)
                self.procs[cmdfn] = CmdCollector(_cmdstr, _out,
                                                 self.get_option('interval'))
            else:
                fullcmd = "%s %s" % (cmd[0], cmd[1])
                self.log_info(
                    "Unable to create command monitor for '%s': '%s' not found"
                    % (fullcmd, cmd[0])
                )

        for _file in _filemons:
            if isinstance(_file, tuple):
                _src = _file[0]
                _fname = _file[1]
            else:
                _src = _file
                _fname = _file.split('/')[-1]
            if os.path.exists(_src):
                _dest = os.path.join(self.tmp_dir, _fname)
                self.procs[_fname] = FileCollector(_src, _dest,
                                                   self.get_option('interval'))
            else:
                self.log_info(
                    "Unable to create file monitor for '%s': no such file"
                    % _src
                )

        for proc in self.procs:
            self.log_debug("Starting '%s' periodic collector" % proc)
            self.procs[proc].start()
        return True

    def trigger_action(self):
        # send the stop signal to all monitors
        for proc in self.procs:
            self.procs[proc].stop()
            self.add_report_file(self.procs[proc].fname)
        while not all([p.stopped for p in self.procs.values()]):
            self.log_info(
                "Waiting for collectors %s to stop"
                % (', '.join(p for p in self.procs if not
                             self.procs[p].stopped))
            )
            time.sleep(1)

    def action_info(self):
        return "A collection of file and/or command outputs taken periodically"
