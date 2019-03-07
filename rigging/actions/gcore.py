# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

from rigging.actions import BaseAction


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
        parser.add_argument('--gcore', action='append',
                            help=self.enabling_opt_desc)
        parser.add_argument('--all-pids', action='store_true',
                            help=('Execute over all pids found when using '
                                  'process names')
                            )
        return parser

    def pre_action(self):
        '''
        Handle both process names and specific pids in command line args.

        If a PID is supplied, the core name will be core.$pid. If a process
        name is provided, the core name will be core.$name.$pid
        '''
        self.pid_list = []
        for pid in self.args['gcore']:
            try:
                self.pid_list.append((int(pid), ''))
            except ValueError:
                # we were handed a process name, get the pid of it
                ret = self.exec_cmd("pidof %s" % pid)
                if ret['status'] == 0:
                    pids = ret['stdout'].split()
                    if len(pids) > 1 and not self.args['all_pids']:
                        err = ("Multiple pids found for process %s. Use "
                               "--all-pids or specify a pid manually")
                        self.log_error(err % pid)
                        return False
                    for proc in pids:
                        self.pid_list.append((int(proc), pid))
                    return True
                else:
                    self.log_error("Could not find PID(s) for '%s'" % pid)
                    return False
        return True

    def trigger_action(self):
        for pid in self.pid_list:
            loc = self.tmp_dir + 'core'
            if pid[1]:
                loc += ".%s" % pid[1]
            self.log_debug("Collecting gcore of %s at %s" % (pid[0], loc))
            try:
                ret = self.exec_cmd("gcore -o %s %s" % (loc, pid[0]))
                if ret['status'] == 0:
                    fname = ret['stdout'].splitlines()[-1].split()[-1]
                    self.add_report_file(fname)
            except Exception as err:
                self.log_error("Error collecting coredump of %s: %s"
                               % (pid[0], err))
        return True
