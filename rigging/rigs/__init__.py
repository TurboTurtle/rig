# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import ast
import inspect
import json
import logging
import os
import random
import shutil
import string
import socket
import sys
import tarfile
import time

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures import thread
from datetime import datetime
from rigging.actions import BaseAction
from rigging.exceptions import *

RIG_DIR = '/var/run/rig/'
RIG_TMP_DIR_PREFIX = '/var/tmp/rig'


class BaseRig():
    """
    Base class for resources/triggers.

    Will build a set of argparse options based upon what the rig provides by
    itself, as well as the defined actions it supports.

    Two class members must be defined by a rig:
        resource_name: The canonical name of the rig as used to invoke it
                       on the commandline.
        parser_description: The argparse description text for the Rig's submenu
        parser_usage:  The argparse usage text for the Rig's submenu
    """

    parser_description = None
    parser_usage = """
    rig %(name)s <options>

    Valid actions:

    """
    triggered = False
    watcher_threads = []
    rig_wide_opts = ()
    _triggered_from_cmdline = False

    def __init__(self, parser):
        self.detached = False
        self._status = 'Initializing'
        self.resource_name = self.__class__.__name__.lower()
        self.parser_usage = self.parser_usage % {'name': self.resource_name}
        self.pool = None
        self.parser = parser
        self.restart_count = 0
        subparser = self.parser.add_subparsers()
        self.rig_parser = subparser.add_parser(self.resource_name)
        self.rig_parser = self._setup_parser(self.rig_parser)

        self.supported_actions = self._load_supported_actions()
        for action in self.supported_actions:
            self.supported_actions[action]._add_action_options(self.rig_parser)
            self.parser_usage += '\t{:<15} {:>30}\n'.format(
                self.supported_actions[action].enabling_opt,
                self.supported_actions[action].enabling_opt_desc
            )

        if self.parser_description:
            self.rig_parser.description = self.parser_description
        if self.parser_usage:
            self.rig_parser.usage = self.parser_usage

        self._can_run = self._load_args()
        if self._can_run:
            self.set_rig_id()
            self.pid = os.getpid()
            self.created_time = datetime.strftime(datetime.now(),
                                                  '%D %H:%M:%S')
            self.rig_options = {}
            self._load_rig_wide_options()
            self._setup_rig_logging()
            self.log_debug("Initializing %s rig %s" %
                           (self.resource_name, self.id))
            self._sock, self._sock_address = self._create_rig_socket()
            self._tmp_dir = self._create_temp_dir()
            self.files = []

    def set_rig_id(self):
        """If the --name option is given, update the rig's ID to that value.
        """
        if self.args['name']:
            self.id = self.args['name']
        else:
            self.id = (''.join(random.choice(string.ascii_lowercase)
                       for x in range(5)))

    def _exit(self, errno):
        """
        Handles pre-mature exits due to errors
        """
        self._cleanup_threads()
        self._cleanup_socket()
        raise SystemExit(errno)

    def _detach(self):
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
                self.log_error("Fork failed: %s" % e)
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
        return True

    def _create_rig_socket(self):
        """
        Creates the UNIX socket that the rig will listen on for lifecycle
        management.

        This socket is used by the rig cli when getting status information or
        destroying a deployed rig before the trigger event happens.
        """
        if not os.path.exists(RIG_DIR):
            os.makedirs(RIG_DIR)
        _sock_address = "%s%s" % (RIG_DIR, self.id)
        try:
            os.unlink(_sock_address)
        except OSError:
            if os.path.exists(_sock_address):
                raise SocketExistsError(_sock_address)
        try:
            _sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _sock.bind(_sock_address)
            _sock.listen(1)
            return (_sock, _sock_address)
        except Exception as err:
            self.log_error("Unable to create unix socket: %s" % err)
            raise CreateSocketException

    def _create_temp_dir(self):
        """
        Create a temp directory for rig to use for saving created files too
        """
        try:
            _dir = "%s.%s/" % (RIG_TMP_DIR_PREFIX, self.id)
            os.makedirs(_dir)
            return _dir
        except OSError:
            raise CannotConfigureRigError('failed to create temp directory')

    def _load_args(self):
        """
        Parses the args given to us by the user.

        This is called while trying to load a rig. If we do not have any args,
        then that means that '--help' was called, in which case we return False
        to ensure we don't begin logging for no reason.

        If there is an unknown option provided, argparse appends it to another
        namespace list, thus if this list contains more than just the resource
        as an element, it means we have an unknown arg.
        """
        args = self.rig_parser.parse_known_args()
        filt = ['--debug', '--foreground']
        unknowns = [x for x in args[1][1:] if x not in filt]
        if len(unknowns):
            print("Unknown option %s specified." %
                  unknowns[0].split('=')[0])
            return False
        self.args = vars(self.rig_parser.parse_known_args()[0])
        self.debug = self.args['debug']
        if self.args:
            return True
        return False

    def _load_supported_actions(self):
        """
        Looks at the defined actions available to rig, and if they match any
        of the strings listed in supported_actions instantiates them.
        """
        actions = {}
        import rigging.actions
        pkg = rigging.actions
        for path in pkg.__path__:
            if os.path.isdir(path):
                for pyfile in sorted(os.listdir(path)):
                    if not pyfile.endswith('.py') or '__' in pyfile:
                        continue
                    fname, ext = os.path.splitext(pyfile)
                    modname = 'rigging.actions.%s' % fname
                    mod_short_name = modname.split('.')[2]
                    mod = __import__(modname, globals(), locals(),
                                     [mod_short_name])
                    modules = inspect.getmembers(mod, inspect.isclass)
                    for module in modules:
                        if module[1] == BaseAction:
                            continue
                        if not issubclass(module[1], BaseAction):
                            continue
                        actions[module[1].action_name] = module[1]
        return actions

    def _load_rig_wide_options(self):
        """
        Based on the rig's rig_wide_options member, take the values for those
        options and load them into the rig_options dict to be used for global
        usage in actions, so we can avoid having to specify the same value over
        and over between rigs and actions.
        """
        for opt in self.rig_wide_opts:
            if opt in self.args:
                self.rig_options[opt] = self.args[opt]

    def _setup_parser(self, parser):
        """
        Builds the option parser based on supported actions, then appends the
        rig-specific options.

        Returns:
            parser: an ArgumentParser object that contains the rig-specific
                    options.
        """
        # Add the common rigging options here
        global_grp = parser.add_argument_group('Global Options')
        global_grp.add_argument('--foreground', action='store_true',
                                default=False,
                                help='Run the rig in the foreground')
        global_grp.add_argument('--debug', action='store_true',
                                help='Print debug messages to console')
        global_grp.add_argument('--delay', type=int, default=0,
                                help='Seconds to delay running actions')
        global_grp.add_argument('--name', type=str, default='',
                                help='Specify a name for the rig')
        global_grp.add_argument('--no-archive', default=False,
                                action='store_true',
                                help='Do not create a tar archive of results')
        global_grp.add_argument('--restart', default=0, type=int,
                                help='Number of times a rig should restart '
                                     'itself')
        global_grp.add_argument('--repeat', default=0, type=int,
                                help=('Number of times to repeat actions that '
                                      'support repitition'))
        global_grp.add_argument('--repeat-delay', default=1, type=int,
                                help='Seconds to delay between repeating '
                                     'actions')
        global_grp.add_argument('--interval', default=1, type=int,
                                help='Time to wait between rig polling '
                                     'intervals')
        return self._set_parser_options(parser)

    def compile_details(self):
        try:
            args = sys.argv[2:]
            return ' '.join(args)[:40]
        except Exception:
            return ''

    @property
    def watching(self):
        """
        MUST be overridden by rigs. This should return a string describing
        what resource(s) the rig is monitoring
        """
        return NotImplementedError

    @property
    def trigger(self):
        """
        MUST be overridden by rigs. This should return a string containing the
        trigger event for the monitored resource.
        """
        return NotImplementedError

    @property
    def status(self, value=None):
        """
        Returns the current status of the rig.

        :param value: Unused, but passed by the listening socket
        """
        return {
            'id': self.id,
            'pid': str(self.pid),
            'rig_type': self.resource_name,
            'watch': self.watching[:30],
            'trigger': self.trigger[:35],
            'status': self._status
        }

    @property
    def info(self, value=None):
        """
        Returns detailed information about the rig for a more in-depth view
        than status provides
        """
        return {
            'id': self.id,
            'pid': str(self.pid),
            'rig_type': self.resource_name,
            'status': self._status,
            'restart_max': self.args['restart'],
            'restart_count': self.restart_count,
            'cmdline': " ".join(sys.argv),
            'debug': self.debug,
            'watch': self.watching,
            'trigger': self.trigger,
            'created': self.created_time,
            'actions': self._get_action_info()
        }

    def _setup_rig_logging(self):
        extra = {'rig_id': self.id}
        self.logger = logging.getLogger('rig')
        self.logger = logging.LoggerAdapter(self.logger, extra)
        self.console = logging.getLogger('rig_console')
        self.console = logging.LoggerAdapter(self.console, extra)
        if self.get_option('debug'):
            self.logger.setLevel(logging.DEBUG)
            self.console.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    def log_error(self, msg):
        self.logger.error(msg)
        if not self.detached:
            self.console.error(msg)

    def log_info(self, msg):
        self.logger.info(msg)
        if not self.detached:
            self.console.info(msg)

    def log_debug(self, msg):
        self.logger.debug(msg)
        if not self.detached and self.debug:
            self.console.debug(msg)

    def log_warn(self, msg):
        self.logger.warn(msg)
        if not self.detached:
            self.console.warn(msg)

    def set_option(self, option, value):
        """
        Override the rig_wide_option for OPTION with VALUE.
        """
        self.rig_options[option] = value

    def get_option(self, option):
        """
        Retrieve a specified option from the loaded commandline options.

        An invalid option returns as False, rather than raises an exception.

        Returns
            str or bool - If the option has a value other than True, it is
                returned as a string. Otherwise return True or False depending
                on if it has a value at all.
        """
        if option in self.rig_options.keys() and self.rig_options[option]:
            return self.rig_options[option]
        if option in self.args.keys():
            _opt = self.args[option]
            # if the option is not set from the cmdline, and it is loaded from
            # the rig options (as opposed to action options), give the rig-wide
            # option
            if not _opt and option in self.rig_options.keys():
                return self.rig_options[option]
            # otherwise, provide the action-specific option value
            else:
                return _opt
        return False

    def _set_parser_options(self, parser):
        """Internal helper that automatically creates a new argument group
        for each rig
        """
        rig_group = parser.add_argument_group(
            "%s Rig Options" % self.__class__.__name__
        )
        self.set_parser_options(rig_group)
        return parser

    def set_parser_options(self, parser):
        """
        This is where the rig-specific options are actually specified.

        Returns:
            parser - ArgumentParser (sub) parser object
        """
        pass

    def _fmt_return(self, command, output='', success=True):
        """
        Formats a return value as a dict specifying the id of this rig, the
        command run, any output, and if the command was successful
        """
        return json.dumps({
            'id': self.id,
            'command': command,
            'result': output,
            'success': success
        }).encode()

    def _listen_on_socket(self):
        self.log_debug('Listening on %s' % self._sock_address)
        while True:
            conn, client = self._sock.accept()
            try:
                req = json.loads(conn.recv(1024).decode())
            except Exception as err:
                self.log_debug("Error parsing socket request: %s" % err)
                return self._fmt_return(command="Unknown", result=err,
                                        success=False)
            self.log_debug("Received request '%s' from socket"
                           % req['command'])
            if req['command'] == 'destroy':
                self._status = 'destroying'
                self.log_debug("Shutting down rig")
                ret = self._fmt_return(command='destroy')
                conn.sendall(ret)
                raise DestroyRig
            try:
                ret = str(getattr(self, req['command']))
                self.log_debug("Sending '%s' back to client" % ret)
                conn.sendall(self._fmt_return(command=req['command'],
                                              output=ret))
            except Exception as err:
                self.log_debug(err)
                self.log_error('No attribute: %s' % req['command'])
                conn.sendall(self._fmt_return(command=req['command'],
                                              output='No such attribute',
                                              success=False))
            continue

    def _register_actions(self):
        """
        Compare the commandline options to supported actions for the rig.

        For any options matched against the supported actions, we initialize
        those actions to then be triggered once the rig hits the triggering
        conditions.
        """
        self._actions = {}
        for action in self.supported_actions:
            _act = self.supported_actions[action]
            if action in self.args and self.args[_act.enabling_opt]:
                _action = self.supported_actions[action](self)
                _action.set_tmp_dir(self._tmp_dir)
                loaded = _action.load(self.args)
                if not loaded:
                    self._exit(1)
                self._actions[action] = _action

    def _get_action_info(self):
        """
        Provide detailed information about the actions that will be taken
        when the rig is triggered

        Returns:
            dict of action dicts with associated information
        """
        acts = {}
        for action in self._actions:
            _act = self._actions[action]
            acts[action] = {
                'name': action,
                'priority': _act.priority,
                'expected_result': _act.action_info()
            }
        return acts

    def setup(self):
        """
        MUST be overridden by rigs subclassing BaseRig.

        This is where rigs will define their watcher threads.
        """
        raise NotImplementedError

    def execute(self):
        """
        Main entry point for rigs.
        """
        try:
            # detach from console
            if not self.args['foreground']:
                print(self.id)
                self._detach()
                self.detached = True
            self.setup()
            self._register_actions()
            if self.detached:
                for action in self._actions:
                    self._actions[action].detached = True
            ret = self._create_and_monitor()
            if self.args['restart'] != 0:
                while (self.restart_count < self.args['restart'] or
                        self.args['restart'] == -1):
                    self.restart_count += 1
                    self.log_info("Restarting rig %s. Current restart count is"
                                  " %s" % (self.id, self.restart_count))
                    # Re-create the temp dir for the rig every restart so we
                    # don't overlap data being archived
                    self._create_temp_dir()
                    # clear and re-load the configured rig options
                    self.reset_counters()
                    ret = self._create_and_monitor()
            self.trigger_kdump()
            self._status = 'Exiting'
            self._cleanup_socket()
            if ret:
                os._exit(0)
            else:
                os._exit(ret)
        except KeyboardInterrupt:
            self.log_debug('Received keyboard interrupt, destroying rig.')
            self._exit(140)
        except Exception as err:
            self.log_error(err)
            self._exit(1)

    def _create_and_monitor(self):
        """
        Create the threads for listening on the socket and monitoring the bits
        the rig is meant to monitor.

        Blocks until either the monitoring thread returns, or there is a socket
        related problem that interrupts the listening thread.

        After waiting for the first thread to exit, this will clean itself up
        by removing both the thread pool and the temp dir used after the
        results are archived.

        This method may be called multiple times if the rig is configured to
        restart itself after being triggered, hence it is responsible for the
        entire creation and take down process.
        """
        _threads = []
        # listen on the UDS socket in one thread, spin the watcher
        # off in a separate thread
        self._control_pool = ThreadPoolExecutor(2)
        _threads.append(self._control_pool.submit(self._listen_on_socket))
        _threads.append(self._control_pool.submit(self._monitor_resource))
        self._status = 'Running'
        ret = wait(_threads, return_when=FIRST_COMPLETED)
        self.archive_name = self.create_archive()
        self.report_created_files()
        self._cleanup_threads()
        return ret

    def _monitor_resource(self):
        """
        This is the main function in which we watch for a resource's trigger
        condition(s).

        This will block until the rig has self.triggered become True.
        """
        try:
            ret = self.start_watcher_threads()
            if ret:
                self.log_info(
                    'Watcher thread triggered. Stopping other watcher threads')
                self.pool._threads.clear()
                if self.args['delay']:
                    self.log_debug('Delaying trigger for %s seconds'
                                   % self.args['delay'])
                    time.sleep(self.args['delay'])
                self.trigger_actions()
        except Exception:
            raise

    @property
    def manual_trigger(self):
        """
        Manually triggers the rig, kicking off the watcher thread
        """
        self.log_info('Received request to manually trigger rig.')
        self._triggered_from_cmdline = True

    def _watch_for_manual_trigger(self):
        """
        This thread will watch for a manual trigger request from the cmdline,
        and return True iff that request is made
        """
        while not self._triggered_from_cmdline:
            time.sleep(1)
        self.log_debug('Trigger from cmdline received. Triggering watcher')
        return True

    def reset_counters(self):
        """
        Reset whatever counters a rig uses to determine trigger state. This is
        called when a rig restarts itself, so that a previous run does not
        influence the run of the now-restarted rig.

        This SHOULD BE overridden by specific rigs, though if there is not some
        form of counter that the rig uses, it can be ignored.
        """
        pass

    def create_archive(self):
        """
        Takes the contents on the temp directory used for the rig and creates
        a tarball of them, placing the archive in /var/tmp.

        Later, the rig will remove the temp directory for itself.
        """
        if self.get_option('no_archive'):
            self.log_info('Not creating a tar archive of collected data')
            return
        if not os.listdir(self._tmp_dir):
            self.log_info('No data generated to archive for this rig.')
            return
        _arc_date = datetime.strftime(datetime.now(), '%Y-%m-%d-%H%M%S')
        _arc_name = "rig-%s-%s" % (self.id, _arc_date)
        _arc_fname = "/var/tmp/%s.tar.gz" % _arc_name
        with tarfile.open(_arc_fname, 'w:gz') as tar:
            tar.add(self._tmp_dir, arcname=_arc_name)
        return _arc_fname

    def report_created_files(self):
        """
        Report all files created by all actions
        """
        if not self.archive_name and self.files:
            self.log_info("The following files were created for this rig: %s"
                          % ', '.join(f for f in self.files))
        if self.archive_name:
            self.log_info("An archive containing this rig's data is available "
                          "at %s" % self.archive_name)

    def add_watcher_thread(self, target, args):
        """
        Used by rigs to define new thread(s) to start in order to monitor their
        respective resources. Each required thread should make a separate call
        to add_watcher_thread().

        Positional Arguments:
            target - A callable method, almost always defined by the rig
            args - Args that should be passed to the target method, if multiple
                pass this as a tuple.
        """
        if not callable(target):
            raise Exception("Unable to add watcher thread. Target must be a "
                            "callable method, received %s" % target.__class__)
        if not isinstance(args, tuple):
            args = (args, )
        self.watcher_threads.append((target, args))

    def start_watcher_threads(self):
        """
        Start the threadpool and submits the requested watcher threads as jobs.

        Blocks until one of the threads returns, acting as a trigger event for
        the rig
        """
        try:
            futures = []
            self.pool = ThreadPoolExecutor()
            for wthread in self.watcher_threads:
                futures.append(self.pool.submit(wthread[0], *wthread[1]))
            futures.append(self.pool.submit(self._watch_for_manual_trigger))
            results = wait(futures, return_when=FIRST_COMPLETED)
            result = list(results[0])[0].result()
            return result
        except Exception as err:
            self.log_error("Exception caught for rig %s: %s" % (self.id, err))
            self._exit(1)

    def trigger_actions(self):
        """
        This is called when a rig's monitoring condition is met. This will then
        invoke any and all actions defined by the user.
        """
        self._status = 'Triggered'
        self.files = []
        try:
            for action in sorted(self._actions,
                                 key=lambda x: self._actions[x].priority):
                if action == 'kdump':
                    continue
                self.log_debug("Triggering action %s" % action)
                self._actions[action]._trigger_action()
                self.files.extend(self._actions[action].finish_execution())
        except Exception as err:
            self.log_error("Error executing actions: %s" % err)

    def wait_loop(self):
        """Used to sleep a watcher thread for the length of time specified by
        --interval.

        Using this allows a standardized way to both ensure rigs wait the
        amount of time requested by the user between polling intervals, and
        to avoid doing repetitive 'import sleep; time.sleep()' calls.
        """
        time.sleep(self.get_option('interval'))

    def trigger_kdump(self):
        """
        If configured, kdump needs to be triggered at the end of execution.

        Thus, this is called after everything else.
        """
        if 'kdump' in self._actions.keys():
            # if we don't remove this here, we'll have a stale socket for
            # every kdump rig created
            self._cleanup_socket()
            self._actions['kdump']._trigger_action()

    def _cleanup_threads(self):
        try:
            for action in self._actions:
                self._actions[action].cleanup()
            self.pool.shutdown(wait=False)
            self.pool._threads.clear()
            self._control_pool.shutdown(wait=False)
            self._control_pool._threads.clear()
            thread._threads_queues.clear()
        except AttributeError:
            # _exit() called before rig was initialized
            pass

        try:
            if self.archive_name or self._status == 'destroying':
                shutil.rmtree(self._tmp_dir)
        except Exception as err:
            self.log_error("Could not remove temp dir: %s" % err)

    def _cleanup_socket(self):
        try:
            os.remove(self._sock_address)
        except OSError as err:
            if err.errno == 2:
                pass
            else:
                self.log_error("Failed to remove listening socket %s: %s" %
                               (self._sock_address, err))
