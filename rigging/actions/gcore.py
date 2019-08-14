# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.actions import BaseAction
from os.path import basename, isfile
import psutil


class Gcore(BaseAction):
    '''
    Capture a coredump of a running process with gcore (GDB)
    '''

    action_name = 'gcore'
    enabling_opt = 'gcore'
    enabling_opt_desc = 'Capture a coredump of a running process'
    priority = 1
    required_binaries = ('gcore',)

    def add_action_options(self, parser):
        parser.add_argument('--gcore', nargs='?', action='append', default=[],
                            help=self.enabling_opt_desc)
        parser.add_argument('--all-pids', action='store_true',
                            help=('Execute over all pids found when using '
                                  'process names')
                            )
        return parser

    def _get_pid_from_name(self, pname):
        '''
        Find the PID(s) associated with the given process name
        '''
        _procs = []
        filt = ['name', 'exe', 'cmdline', 'pid']
        for proc in psutil.process_iter(attrs=filt):
            if (proc.info['name'] == pname or
                    proc.info['exe'] and basename(proc.info['exe']) == pname or
                    proc.info['cmdline'] and proc.info['cmdline'][0] == pname):
                _procs.append(proc.info['pid'])
        if len(_procs) > 1 and not (self.get_option('all') or
                                    self.get_option('all_pids')):
            msg = ("Multiple PIDs found for process '%s', use --all to watch "
                   "all PIDs" % pname)
            self.log_error(msg)
            raise Exception
        return _procs

    def pre_action(self):
        '''
        Handle both process names and specific pids in command line args.

        If a PID is supplied, the core name will be core.$pid. If a process
        name is provided, the core name will be core.$name.$pid
        '''
        self.pid_list = []
        # the collected list of requested pids, to be filled later
        procs = []
        # the raw commandline value(s) for --gcore
        _pid = self.get_option('gcore')
        for _p in _pid:
            if _p is None:
                if not self.get_option('process'):
                    msg = ('gcore action must be given a pid or process name, '
                           'or be used with the \'process\' rig type for no'
                           'value')
                    self.log_error(msg)
                    return False
                procs.extend(self.get_option('process'))
            else:
                procs.extend(_p.split(','))
        # actually verify the pids derived from the command line options
        for pid in procs:
            try:
                self.pid_list.append((int(pid), ''))
            except ValueError:
                # we were handed a process name, get the pid of it
                proc_pids = self._get_pid_from_name(pid)
                for proc in proc_pids:
                    self.pid_list.append((int(proc), pid))
        msg = ("Determined pid list to collect coredumps for to be: %s"
               % ','.join(str(p[0]) for p in self.pid_list))
        self.log_debug(msg)
        return True

    def trigger_action(self):
        for pid in self.pid_list:
            loc = self.tmp_dir + 'core'
            if pid[1]:
                loc += ".%s" % pid[1]
            if not psutil.pid_exists(int(pid[0])):
                self.log_error("Cannot collect core for pid %s - pid no "
                               "longer exists" % pid[0])
                continue
            _loc = loc + ".%s" % pid[0]
            self.log_debug("Collecting gcore of %s at %s" % (pid[0], _loc))
            try:
                ret = self.exec_cmd("gcore -o %s %s" % (loc, pid[0]))
                if ret['status'] == 0:
                    if isfile(_loc):
                        fname = _loc
                    else:
                        fname = ret['stdout'].splitlines()[-2].split()[-1]
                    self.add_report_file(fname)
            except Exception as err:
                self.log_error("Error collecting coredump of %s: %s"
                               % (pid[0], err))
        return True

    def action_info(self,):
        return ("A coredump for each of the following PIDs: %s"
                % ', '.join(str(p[0]) for p in self.pid_list))
