# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.


from rigging.rigs import BaseRig
from rigging.exceptions import CannotConfigureRigError
from os.path import basename

import psutil
import time


class Process(BaseRig):
    '''
    Watch a process for state changes and trigger when user-provided definition
    is met.

    This definition may be a process state (such as D-state) or process
    resource consumption such as CPU or memory.

    The following parameters are available as rig options:
        :opt proc:    The PID or name of the process to monitor
        :opt state:   The status of a given process on which to trigger
        :opt rss:     The resident set size threshold on which to trigger
        :opt vms:     The virtual memory size threshold on which to trigger
        :opt memperc: The percentage of memory usage on which to trigger
        :opt cpuperc: The percentage of CPU usage on which to trigger

    '''

    parser_description = ('Monitor a process for state or resource consumption'
                          ' thresholds.')

    def set_parser_options(self, subparser):
        subparser.add_argument('--proc', action='append',
                               help='PID or name of process to watch')
        subparser.add_argument('--all', action='store_true',
                               help='Watch all PIDs for a process name')
        subparser.add_argument('--state',
                               help='What process status to trigger on')
        subparser.add_argument('--rss',
                               help='Memory RSS threshold to trigger on')
        subparser.add_argument('--vms',
                               help=('Virtual Memory Size threshold to '
                                     'trigger on'))
        subparser.add_argument('--memperc',
                               help=('Percentage of system memory usage to '
                                     'trigger on'))
        subparser.add_argument('--cpuperc',
                               help='Percentage of CPU usage to trigger on')
        return subparser

    @property
    def watching(self):
        return ', '.join(str(p) for p in self.proc_list)

    @property
    def trigger(self):
        triggers = ''
        if self.args['state']:
            triggers += 'State: %s ' % self.args['state']
        if self.args['rss']:
            triggers += "RSS usage above %s " % self.args['rss']
        if self.args['vms']:
            triggers += "VMS usage above %s " % self.args['vms']
        if self.args['memperc']:
            triggers += "%Mem usage above %s%% " % self.args['memperc']
        if self.args['cpuperc']:
            triggers += "%CPU usage above %s%%" % self.args['cpuperc']
        return triggers

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
        if len(_procs) > 1 and not self.args['all']:
            msg = ("Multiple PIDs found for process '%s', use --all to watch "
                   "all PIDs" % pname)
            raise CannotConfigureRigError(msg)
        return _procs

    def _get_bytes(self, val):
        '''
        Converts the user provided string to an integer representing the
        memory threshold specified in bytes.
        '''
        suffixes = [('K', 10), ('M', 20), ('G', 30)]
        for suff in suffixes:
            if suff[0].lower() in val.lower():
                _suf = suff
        return int(val.split(_suf[0])[0]) << _suf[1]

    def _validate(self):
        '''
        This will do several tasks that ensure the rig is properly defined:

        First, it will validate the given PID, or convert a process name
        to a PID or list of PIDS

        Second, it will validate that all given or discovered PIDs exist

        Third, it will validate the provided status is one we can match with
        psutil. Or it will determine the memory size in bytes to use as our
        threshold.
        '''
        self.proc_list = []
        for process in self.args['proc']:
            try:
                _proc = int(process)
                self.proc_list.append(_proc)
            except ValueError:
                _proc = self._get_pid_from_name(process)
                if not _proc:
                    raise CannotConfigureRigError("No processes found for '%s'"
                                                  % process)
                self.proc_list.extend(_proc)
        if not self.proc_list:
            raise CannotConfigureRigError('No valid PIDs provided. Aborting.')
        for proc in self.proc_list:
            if psutil.pid_exists(int(proc)):
                continue
            # if any PIDs don't actually exist, abort.
            raise CannotConfigureRigError("Invalid PID provided: %s" % proc)
        if self.args['state']:
            _supported_states = [
                psutil.STATUS_RUNNING,
                psutil.STATUS_SLEEPING,
                psutil.STATUS_DISK_SLEEP,
                psutil.STATUS_STOPPED,
                psutil.STATUS_ZOMBIE,
                psutil.STATUS_DEAD
            ]
            if self.args['state'].strip('!') not in _supported_states:
                msg = ("Invalid status '%s' provided. Must be one of the "
                       "following: %s" % (
                        self.args['state'],
                        ', '.join(s for s in _supported_states))
                       )
                raise CannotConfigureRigError(msg)
        if self.args['rss']:
            self.rss_limit = self._get_bytes(self.args['rss'])
        if self.args['vms']:
            self.vms_limit = self._get_bytes(self.args['vms'])
        return True

    def setup(self):
        '''
        Create a monitoring thread for each PID discovered or provided for each
        process item we can monitor for and the user requested.
        '''
        self._validate()
        stat = self.args['state']
        for proc in self.proc_list:
            if self.args['state']:
                invert = stat.startswith('!')
                self.add_watcher_thread(self.watch_process_for_status,
                                        args=(proc, stat, invert))
            if self.args['rss']:
                self.add_watcher_thread(self.watch_process_for_mem,
                                        args=(proc, self.rss_limit, 'rss'))
            if self.args['vms']:
                self.add_watcher_thread(self.watch_process_for_mem,
                                        args=(proc, self.vms_limit, 'vms'))
            if self.args['memperc']:
                limit = float(self.args['memperc'])
                self.add_watcher_thread(self.watch_process_for_perc,
                                        args=(proc, limit, 'memory'))
            if self.args['cpuperc']:
                limit = float(self.args['cpuperc'])
                self.add_watcher_thread(self.watch_process_for_perc,
                                        args=(proc, limit, 'cpu'))

    def watch_process_for_status(self, process, status, invert):
        '''
        Used to watch the given process(es) for status changes and compares
        the current status to the trigger defined by the status option.

        Positional arguments
            process         The PID of the process to watch
            status          The state of the process to trigger on
            invert          Should the boolean comparison for status against
                            current actual process state be reversed
        '''
        proc = psutil.Process(process)
        user_stat = status.strip('!')
        self.log_info("Beginning watch of process %s for status '%s'"
                      % (process, status))
        while True:
            try:
                _stat = proc.status()
                if status == '!running' and _stat == 'sleeping':
                    pass
                elif ((_stat == user_stat and invert is False) or
                      (_stat != user_stat and invert is True)):
                    self.log_info("State for process %s is '%s', matching "
                                  "trigger state '%s'."
                                  % (process, _stat, status))
                    return True
                time.sleep(1)
            except psutil._exceptions.NoSuchProcess:
                if status == '!running':
                    self.log_info("Process %s is no longer running, matching "
                                  "trigger state '%s'" % (process, status))
                    return True
                self.log_info("Process %s is no longer running and desired "
                              "trigger state is not '!running'. Stopping "
                              "watcher thread without triggering rig."
                              % process)
                return False

    def watch_process_for_mem(self, process, limit, mem_type):
        '''
        Watch the given process(es) for mem consumption values that exceed the
        amount specified by limit.

        Positional arguments:
            process     The PID of the process to watch
            limit       The usage threshold in bytes
            mem_type    The memory stat to watch - e.g. rss or vms.
        '''
        proc = psutil.Process(process)
        self.log_info("Beginning watch of process %s for %s memory usage of "
                      "%s bytes or higher" % (process, mem_type, limit))
        while True:
            try:
                _mem = proc.memory_info()
                _check = getattr(_mem, mem_type)
                if _check >= limit:
                    self.log_info("Process %s has %s usage of %s, exceeding "
                                  "trigger threshold of %s."
                                  % (process, mem_type, _check, limit))
                    return True
                time.sleep(1)
            except psutil._exceptions.NoSuchProcess:
                self.log_info("Process %s is no longer running, stopping %s "
                              "monitor." % (process, mem_type))
                return False

    def watch_process_for_perc(self, process, limit, resource):
        '''
        Watch the given process(es) for memory consumption higher than the
        percentage of system memory defined by limit.

        Positional arguments:
            process     The PID of the process to watch
            limit       The usage percentage threshold as a float
            resource    'memory' or 'cpu' - which to monitor
        '''
        proc = psutil.Process(process)
        self.log_info("Beginning watch of process %s for total %s usage of"
                      " %s%% or higher" % (process, resource, limit))
        while True:
            try:
                if resource == 'memory':
                    _perc = float("{0:.2f}".format(proc.memory_percent()))
                elif resource == 'cpu':
                    _perc = float(proc.cpu_percent())
                if _perc >= limit:
                    self.log_info("Process %s has total %s usage of %s%% "
                                  "exceeding trigger threshold of %s%%"
                                  % (process, resource, _perc, limit))
                    return True
                time.sleep(1)
            except psutil._exceptions.NoSuchProcess:
                self.log_info("Process %s is no longer running, stopping "
                              "%s percentage monitor." % (process, resource))
                return False
