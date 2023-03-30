# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import psutil

from rigging.monitors import BaseMonitor
from rigging.utilities import convert_to_bytes, convert_to_human, get_proc_pids
from rigging.exceptions import DestroyRig
from threading import Lock

PROC_STATES = {
    psutil.STATUS_RUNNING: ('running', 'R', 'run'),
    psutil.STATUS_DISK_SLEEP: ('disk-sleep', 'disk_sleep', 'D', 'UN',
                               'uninterruptible', 'uninterruptible_sleep'),
    psutil.STATUS_SLEEPING: ('sleeping', 'sleep', 'S'),
    psutil.STATUS_STOPPED: ('stopped', 'stop', 'T'),
    psutil.STATUS_ZOMBIE: ('zombie', 'Z')
}


class ProcessMonitor(BaseMonitor):
    """
    Watch a process for changes in process state, or resource consumption.
    Multiple processes may be watched at a time and processes may be specified
    by either name or PID.
    """

    monitor_name = 'process'

    def configure(self, procs, cpu_percent=None, memory_percent=None,
                  state=None, vms=None, rss=None):
        """
        :param procs: A process or list of process to watch. Specify either
                      a PID or command. If command, accepts a regex.
        :param cpu_percent: Trigger if CPU usage exceeds this threshold
        :param memory_percent: Trigger if memory usage exceeds this threshold
        :param state: The POSIX state of the process to trigger on
        :param vms: The virtual memory size threshold to trigger on
        :param rss: The resident set size threshold to trigger on
        """
        if state is not None:
            if not isinstance(state, str):
                raise Exception(f"'state' must be str, not {state}")
            self._state_invert_match = state.startswith('!')
        else:
            self._state_invert_match = False

        self.lock = Lock()

        self.metrics = {
            'cpu_percent': cpu_percent,
            'memory_percent': memory_percent,
            'state': self._get_state_code(state) if state else None,
            'vms': convert_to_bytes(vms) if vms else None,
            'rss': convert_to_bytes(rss) if rss else None
        }

        for perc in ['cpu_percent', 'memory_percent']:
            if self.metrics[perc] is not None:
                try:
                    self.metrics[perc] = float(self.metrics[perc])
                except Exception:
                    raise Exception(f"'{perc}' must be integer or float, not "
                                    f"{perc.__class__}")

        if not any([m is not None for m in self.metrics.values()]):
            raise Exception(
                f"Must specify at least one of "
                f"{', '.join(self.metrics.keys())}"
            )

        if isinstance(procs, str | int):
            _procs = [procs]
        elif isinstance(procs, list):
            _procs = procs
        else:
            raise Exception(
                f"'procs' must be string or list. Not {procs.__class__}"
            )

        self.procs = get_proc_pids(_procs)
        if not self.procs:
            raise Exception(
                "No PIDs matching specified process identifiers found. "
                "Aborting..."
            )

        _state = self.metrics['state']
        for proc in self.procs:
            if _state:
                self.add_monitor_thread(
                    self.watch_process_for_status,
                    (proc, _state, )
                )
            if any(m is not None for m in self.metrics.values()):
                self.add_monitor_thread(
                    self.watch_process_for_utilization,
                    (proc, )
                )

    @staticmethod
    def _get_state_code(state):
        """
        Converts the given state string to the string used by psutil. This
        allows us to be more flexible in what users can set in their rigfiles.

        :param state: The state specified in the rigfile
        :return: A matching string from a psutil.STATUS_* constant
        """
        for _state_code in PROC_STATES:
            if state.strip('!') in PROC_STATES[_state_code]:
                return _state_code
        raise Exception(
            f"Unable to parse specified process status '{state}'. "
            f"See man rig for supported values."
        )

    def watch_process_for_status(self, pid, state):
        """
        Monitor a specific pid for the defined status. Generally speaking, if
        a pid _enters_ this state, we trigger.

        This can be inverted if the user prefixed their rigfile `state` value
        with `!` to signify we should be looking for "not in this state".
        In such a case, the monitor will trigger when we first detect that the
        pid is _not_ in the defined state.

        However, in the specific case of state being `!running`, the monitor
        accepts that a state of `sleeping` is not a reason to trigger.

        :param pid: The PID of the process to monitor
        :param state: The status string used by psutil to match against
        """
        self.logger.debug(
            f"Launching monitor thread for PID {pid} in state "
            f"{'not ' if self._state_invert_match else ''}{state}"
        )
        proc = psutil.Process(pid)
        while True:
            try:
                _status = proc.status()
                if (state == 'running' and _status == 'sleeping' and
                        self._state_invert_match):
                    pass
                elif (((state == _status) and not self._state_invert_match) or
                      ((state != _status) and self._state_invert_match)):
                    self.logger.info(
                        f"Process {pid} is in state {_status} matching trigger"
                        f" state '{'!' if self._state_invert_match else ''}"
                        f"{state}'"
                    )
                    return True
                self.wait_loop()
            except psutil.NoSuchProcess:
                if state == 'running' and self._state_invert_match:
                    self.logger.info(
                        f"Process {pid} no longer exists, matching trigger "
                        f"state of !{state}."
                    )
                    return True
                self.logger.info(
                    f"Process {pid} no longer exists, and desired trigger "
                    f"state is not '!running'. Holding monitor active until "
                    f"all pid monitoring is resolved."
                )
                return self._hold_thread(pid)
            except Exception as err:
                self.logger.info(f"Error while polling process state: {err}")
                return self._hold_thread(pid)

    @property
    def all_pids_are_dead(self):
        return all(not psutil.pid_exists(p) for p in self.procs)

    def _hold_thread(self, pid):
        self.logger.debug(
            f"Process {pid} no longer exists. Holding monitor thread until all"
            f" specified pids either die or trigger rig."
        )
        while not self.all_pids_are_dead:
            with self.lock:
                self.wait_loop()
        raise DestroyRig(
            'All specified pids now dead, and state not defined to trigger'
            ' on this condition.'
        )
        # return False

    def watch_process_for_utilization(self, pid):
        """
        Monitor a given pid for exceeding any of the utilization metrics set in
        the rigfile.

        :param pid: The PID of the process to watch
        """
        _metrics = {}
        for _met in self.metrics:
            if _met == 'state':
                continue
            if self.metrics[_met] is not None:
                _metrics[_met] = self.metrics[_met]
        _log_msg = ', '.join([
            f"{k} above {convert_to_human(v) if 'percent' not in k else v }"
            for k, v in _metrics.items()
        ])
        self.logger.debug(
            f"Launching monitor thread for PID {pid} for "
            f"{_log_msg}"
        )

        proc = psutil.Process(pid)
        while True:
            try:
                for perc_met in ['cpu_percent', 'memory_percent']:
                    if _metrics.get(perc_met):
                        _metric = round(getattr(proc, perc_met)(), 2)
                        if _metric > _metrics[perc_met]:
                            self.logger.info(
                                f"Process {pid} {perc_met} usage of {_metric}%"
                                f" exceeds threshold of {_metrics[perc_met]}%"
                            )
                            return True
                for mem_stat in ['vms', 'rss']:
                    if _metrics.get(mem_stat):
                        _memory = proc.memory_info()
                        _stat = getattr(_memory, mem_stat)
                        if _stat > _metrics[mem_stat]:
                            self.logger.info(
                                f"Process {pid} {mem_stat} usage of "
                                f"{convert_to_human(_stat)} exceeds threshold "
                                f"of {convert_to_human(_metrics[mem_stat])}"
                            )
                            return True
                self.wait_loop()
            except psutil.NoSuchProcess:
                return self._hold_thread(pid)

    @property
    def monitoring(self):
        _info = {
            'pids': self.procs
        }
        for k, v in self.metrics.items():
            if v is None:
                continue
            if k == 'state':
                _info[k] = (
                    f"{'not ' if self._state_invert_match else '' }"
                    f"{PROC_STATES[self.metrics[k]][0]}"
                )
                continue
            _info[k] = f">= {f'{v}%' if 'perc' in k else convert_to_human(v)}"
        return _info
