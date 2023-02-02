# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import os
import shutil
import socket
import sys
import tarfile
import time

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures import thread
from datetime import datetime
from rigging.exceptions import (SocketExistsError, CreateSocketError,
                                CannotConfigureRigError, DestroyRig)
from rigging.utilities import load_rig_monitors, load_rig_actions

RIG_DIR = '/var/run/rig/'


class BaseRig():
    """
    The building block from which we construct rigs that will watch for
    specific conditions and then take pre-defined actions. The rig is first
    initialized and given a UNIX socket for communication, and then given
    a set of monitors and actions to take once those monitors are triggered.

    A rig must have at least one monitor and one action in order to be
    considered valid. Note that some actions will start immediately in the
    background, while others (most) will be executed after the condition(s)
    being monitored are met.
    """

    def __init__(self, config, logger):
        """
        :param config: A dict of config options, not including the options
                       being set for monitors or actions
        :param logger: The instantiated logger from the calling RigCmd
        """
        self.logger = logger
        self._loaded_monitors = load_rig_monitors()
        self._loaded_actions = load_rig_actions()
        self.files = []
        self.monitors = []
        self.actions = []
        self.config = self._extrapolate_rig_defaults(config)
        self.tmpdir = self.config['tmpdir']
        self.name = self.config['name']
        self._triggered_from_cmdline = False
        self.kdump_configured = False

    def _extrapolate_rig_defaults(self, config):
        _defaults = {
            'foreground': False,
            'repeat': 0,
            'repeat_delay': 1,
            'delay': 0,
            'interval': 1,
            'no_archive': False
        }
        _defaults.update(config)
        return _defaults

    def detach(self):
        """
        Here we effectively daemonize the process by using the double-fork
        method. The rig will continue to run until a trigger event, or until
        the rig cli is used to send a termination signal to the socket the rig
        is listening on.
        """
        def _fork():
            try:
                pid = os.fork()
                if pid > 0:
                    sys.exit(0)
            except OSError as e:
                self.logger.error("Fork failed: %s" % e)
                sys.exit(1)
        _fork()
        os.setsid()
        os.umask(0)
        _fork()

        sys.stdin = sys.__stdin__
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        sys.stdout.flush()
        sys.stderr.flush()
        _std = getattr(os, 'devnull', '/dev/null')
        sin = open(_std, 'r')
        sout = open(_std, 'a+')
        serr = open(_std, 'a+')
        os.dup2(sin.fileno(), sys.stdin.fileno())
        os.dup2(sout.fileno(), sys.stdin.fileno())
        os.dup2(serr.fileno(), sys.stderr.fileno())

        self.pid = os.getpid()
        self.logger.debug('Detaching from console')
        return True

    def _create_socket(self):
        """
        Creates the UNIX socket that the rig will listen on for lifecycle
        management.

        This socket is used by the rig cli when getting status information or
        destroying a deployed rig before the trigger event happens.
        """
        if not os.path.exists(RIG_DIR):
            os.makedirs(RIG_DIR)
        _sock_address = f"{RIG_DIR}{self.name}"
        try:
            os.unlink(_sock_address)
        except OSError:
            if os.path.exists(_sock_address):
                raise SocketExistsError(_sock_address)
        try:
            _sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _sock.bind(_sock_address)
            _sock.listen(1)
            self.logger.debug(f"Socket created at {_sock_address}")
            return (_sock, _sock_address)
        except Exception as err:
            self.logger.error(f"Unable to create unix socket: {err}")
            raise CreateSocketError

    def _find_monitor(self, monitor):
        """
        Attempt to find an available monitor that rig supports based on the
        name given in the configuration file

        :param monitor: The name of the monitor to deploy
        :return: The found monitor class, else Exception
        """
        try:
            return self._loaded_monitors[monitor]
        except KeyError:
            raise Exception(f"Unknown monitor '{monitor}'")
        except Exception as err:
            raise Exception(f"Error during monitor lookup: {err}")

    def _find_action(self, action):
        """
        Attempt to find an action that rig supports based on the name given
        in the configuration file

        :param action: The name of the action
        :return: The found action class, else Exception
        """
        try:
            return self._loaded_actions[action]
        except KeyError:
            raise Exception(f"Unknown action '{action}'")
        except Exception as err:
            raise Exception(f"Error during action lookup: {err}")

    def add_monitor(self, monitor, config):
        """
        Validates the configuration of a monitor, and then adds it to the rig
        so that when the rig starts, we will be monitoring properly.

        Each monitor will run in a separate thread, and the rig will trigger
        when ANY of the monitors meet their specified condition.

        :param monitor: The name of the monitor to add to this rig
        :param config:  A dict that will be used to provide the config options
                        to the monitor

        :return: True if successful, else Exception
        """
        if not config:
            raise CannotConfigureRigError(
                f"Empty configuration for monitor {monitor} received"
            )
        try:
            mon = self._find_monitor(monitor)
            _mon = mon(self.config, self.logger, **config)
            self.logger.debug(f"Monitor {monitor} configured and validated")
            self.monitors.append(_mon)
        except TypeError as terr:
            if 'required positional argument' in terr.args[0]:
                _missing = terr.args[0].split(': ')[-1]
                raise CannotConfigureRigError(
                    f"{monitor} monitor requires the arguments {_missing}"
                )
            elif 'unexpected keyword argument' in terr.args[0]:
                _unknown = terr.args[0].split('argument ')[-1]
                raise CannotConfigureRigError(
                    f"Unknown argument {_unknown} passed to {monitor} monitor"
                )
            raise
        except Exception as err:
            raise CannotConfigureRigError(
                f"Unable to configure {monitor} monitor: {err}"
            )
        return True

    def add_action(self, action, config):
        """
        Validates the configuration of an action, then adds it to the rig so
        that when at least one rig monitor triggers, the action will be
        executed.

        Actions are run serially in the main thread.

        :param action: The name of the action being added to the rig
        :param config: A dict that will be used to configure the action

        :return: True if successful, else Exception
        """
        if not config:
            raise CannotConfigureRigError(
                f"Empty configuration for action {action} received"
            )
        try:
            act = self._find_action(action)
            _act = act(self.config, self.logger, self.tmpdir, **config)
            self.logger.debug(f"Action {action} configured and validated")
            self.actions.append(_act)
            if _act.action_name == 'kdump':
                self.kdump_configured = True
        except TypeError as terr:
            if 'required positional argument' in terr.args[0]:
                _missing = terr.args[0].split(': ')[-1]
                raise CannotConfigureRigError(
                    f"{action} action requires the parameters {_missing}"
                )
            elif 'unexpected keyword argument' in terr.args[0]:
                _unknown = terr.args[0].split('argument ')[-1]
                raise CannotConfigureRigError(
                    f"Unknown argument {_unknown} passed to {action} action"
                )
            raise
        except Exception as err:
            raise CannotConfigureRigError(
                f"Unable to configure {action} action: {err}"
            )

    def start_rig(self):
        self._sock, self._sock_address = self._create_socket()
        for action in self.actions:
            try:
                action.pre_action()
            except Exception as err:
                self.logger.error(
                    f"Error during {action.action_name} pre-action: {err}"
                )
                self.logger.info('Rig terminating due to previous error')
                self._exit(1)
        ret = self._create_and_monitor()
        if ret:
            arc_name = self.create_archive()
            if arc_name:
                self.logger.info(
                    f"An archive containing this rig's data is available at "
                    f"{arc_name}"
                )
        self._cleanup_threads()
        if self.kdump_configured:
            self.logger.info(
                'Kdump action has been configured, please note that rig '
                'archive will not contain generated vmcore'
            )
            for _act in self.actions:
                if _act.action_name == 'kdump':
                    _act.trigger()
        self.logger.info(f"Rig {self.name} terminating")
        self._exit(0)

    def trigger_actions(self):
        """
        Execute the configured actions for the rig, serially. Actions are
        executed based on their defined priority, and this is not currently
        user controllable.
        """
        self._status = 'Triggered'
        try:
            self.logger.info('Beginning triggering of actions')
            for action in sorted(self.actions, key=lambda x: x.priority):
                if action.action_name == 'kdump':
                    self.logger.info(
                        'Skipping action kdump until rig has otherwise '
                        'completed all actions and generated its archive'
                    )
                    continue
                self.logger.debug(f"Triggering action {action.action_name}")
                action.trigger_action()
                self.files.extend(action.finish_execution())
        except Exception as err:
            self.logger.error(f"Error executing actions: {err}")

    def _create_and_monitor(self):
        """
        Here we kick off two threads in a pool. One will listen on the socket
        for the rig and respond to any requests that come over it. The other
        will start the monitors and wait for one of them to return. When either
        thread returns, this method will return, which may result in the
        configured actions being executed. It may, for example when being
        forcibly destroyed, simply kill the rig process without performing any
        of the actions.

        :return: True if the rig gets triggered
        """
        _threads = []
        # listen on the UDS socket in one thread, spin the watcher
        # off in a separate thread
        self._control_pool = ThreadPoolExecutor(2)
        _threads.append(self._control_pool.submit(self._listen_on_socket))
        _threads.append(self._control_pool.submit(self._start_monitors))
        self._status = 'Running'
        ret = wait(_threads, return_when=FIRST_COMPLETED)
        self._cleanup_threads()
        return ret

    def _listen_on_socket(self):
        """
        Actively listen on the UNIX socket configured for this rig and respond
        as necessary to those requests.

        If this thread exits, the rig will exit as well.
        """
        self.logger.debug(f"Listening on {self._sock_address}")
        while True:
            conn, client = self._sock.accept()
            try:
                req = conn.recv(1024).decode()
                print(req)
            except Exception as err:
                self.logger.error(f"Error on socket: {err}")
        # TODO: build this out to actually react to socket traffic

    def _start_monitors(self):
        """
        Starts the threads for the monitors attached to this rig. If any of
        these monitors returns, that is considered to 'trigger' the rig and
        thus the other threads are terminated, and the rig proceeds to perform
        its configured actions
        """
        try:
            ret = self._start_monitor_threads()
            if ret:
                self.logger.info('Stopping other watcher threads')
                self.pool._threads.clear()
                if self.config['delay']:
                    self.logger.debug(
                        f"Delaying trigger for {self.config['delay']} seconds"
                    )
                    time.sleep(self.config['delay'])
                self.trigger_actions()
        except Exception as err:
            self.logger.error(err)
            raise

    def _start_monitor_threads(self):
        """
        Start the threadpool and submits the requested watcher threads as jobs.

        Blocks until one of the threads returns, acting as a trigger event for
        the rig
        """
        try:
            futs = []
            self.pool = ThreadPoolExecutor()
            for mon in self.monitors:
                futs.append(self.pool.submit(mon.start_monitor))
            futs.append(self.pool.submit(self._watch_for_manual_trigger))
            results = wait(futs, return_when=FIRST_COMPLETED)
            result = list(results[0])[0].result()
            self.logger.info('Monitor thread completed. Triggering rig.')
            return result
        except DestroyRig:
            self._exit(0)
        except Exception as err:
            self.logger.error(f"Exception caught for rig {self.name}: {err}")
            self._exit(1)

    def _watch_for_manual_trigger(self):
        """
        This thread will watch for a manual trigger request from the cmdline,
        and return True iff that request is made
        """
        while not self._triggered_from_cmdline:
            time.sleep(1)
        self.logger.debug('Trigger from cmdline received. Triggering monitor')
        return True

    def create_archive(self):
        """
        Takes the contents on the temp directory used for the rig and creates
        a tarball of them, placing the archive in /var/tmp.

        Later, the rig will remove the temp directory for itself.
        """
        if not os.listdir(self.tmpdir):
            self.logger.info('No data generated to archive for this rig.')
            return
        _arc_date = datetime.strftime(datetime.now(), '%Y-%m-%d-%H%M%S')
        _arc_name = "rig-%s-%s" % (self.name, _arc_date)
        _arc_fname = "/var/tmp/%s.tar.gz" % _arc_name
        with tarfile.open(_arc_fname, 'w:gz') as tar:
            tar.add(self.tmpdir, arcname=_arc_name)
        return _arc_fname

    def _cleanup_threads(self):
        try:
            self.pool.shutdown(wait=False)
            self.pool._threads.clear()
        except AttributeError:
            pass
        try:
            self._control_pool.shutdown(wait=False)
            self._control_pool._threads.clear()
        except AttributeError:
            pass
        thread._threads_queues.clear()

    def _cleanup_socket(self):
        try:
            os.remove(self._sock_address)
        except OSError as err:
            if err.errno == 2:
                pass
            else:
                self.logger.error(
                    f"Failed to remove socket {self._sock_address}: {err}"
                )

    def _exit(self, errno):
        """
        Handles exiting the main thread.
        """
        self._cleanup_threads()
        self._cleanup_socket()
        if errno:
            raise SystemExit(errno)
        else:
            try:
                shutil.rmtree(self.tmpdir)
            except Exception as err:
                self.logger.error(f"Could not remove temp directory: {err}")
            os._exit(0)
