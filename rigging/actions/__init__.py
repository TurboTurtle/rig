# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import logging
import os
import shlex
import shutil
import time

from rigging.exceptions import *
from subprocess import Popen, PIPE


class BaseAction():
    """
    Base class that all rig actions need to subclass.

    Actions are what rig does when a resource monitor (the rig) is triggered.
    This will typically be a one-off execution of some command, for example
    generating an application core when a log message is matched. In this
    example the log message is matched by the Logs rig, and the generation of
    the application core would be the Action.
    """

    enabling_opt = ''
    enabling_opt_desc = ''
    action_name = ''
    priority = 10
    required_binaries = ()
    repeatable = False

    def __init__(self, rig):
        self.rig = rig
        self.id = self.rig.id
        self.repeat_count = 0

    def set_tmp_dir(self, tmp_dir):
        if os.path.exists(tmp_dir):
            self.tmp_dir = tmp_dir
        else:
            raise CannotConfigureRigError("%s does not exist" % tmp_dir)

    def load(self, args):
        """
        Actually load the commandline configuration into the instantiated
        action.
        """
        self.args = args
        self.detached = False
        self.report_files = []
        self.report_message = None
        self._setup_action_logging()
        loaded = self._pre_action()
        if not loaded:
            self.log_error("Failed to load action %s"
                           % self.action_name)
            self.cleanup()
        return loaded

    def _setup_action_logging(self):
        extra = {'rig_id': self.id}
        self.logger = logging.getLogger('rig')
        self.logger = logging.LoggerAdapter(self.logger, extra)
        self.console = logging.getLogger('rig_console')
        self.console = logging.LoggerAdapter(self.console, extra)

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
        if not self.detached:
            self.console.debug(msg)

    def action_info(self):
        """
        Return information about what the action should generate. This is
        called during 'rig info <rig id>' and appears as the 'expected_result'
        element.

        MUST be overridden by specific actions
        """
        return 'Not defined by action'

    def get_option(self, option):
        """
        Return the value for the given option from the rig or the command line
        args
        """
        return self.rig.get_option(option)

    def exec_cmd(self, cmd):
        """
        Executes the given command via Popen() without getting a TTY.

        Positional arguments
            cmd - a string containing the full command to run

        Returns
            dict containing the exit status and output from the cmd
        """
        self.log_debug("Running command %s" % cmd)
        cmd = shlex.split(cmd)
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, encoding='utf-8',
                     shell=False)
        stdout, stderr = proc.communicate(timeout=180)
        rc = proc.returncode
        return {'status': rc, 'stdout': stdout, 'stderr': stderr}

    @classmethod
    def _add_action_options(cls, parser):
        """Add an argument group for the action to better format --help output
        """
        act_grp = parser.add_argument_group(
            "%s Action Options" % cls.__name__.title()
        )
        cls.add_action_options(act_grp)
        return parser

    @classmethod
    def add_action_options(cls, parser):
        """
        This is where the action-specific options are added.

        Returns:
            parser - ArgumentParser (sub) parser object
        """
        pass

    def _check_exists(self, binary):
        """
        Checks to see if the given binary exists in PATH.
        """
        paths = os.environ.get("PATH", "").split(os.path.pathsep)
        cmds = [os.path.join(p, binary) for p in paths]
        return any(os.access(path, os.X_OK) for path in cmds)

    def _pre_action(self):
        """
        This is called prior to setting up a resource monitor, and wraps an
        Action's pre_action() method, if one is defined.

        Returns:
            bool - True if pre_action completes successfully or if no
                   pre_action is defined. Raises an exception if not successful
        """
        try:
            for binary in self.required_binaries:
                if not self._check_exists(binary):
                    self.log_error("Required binary %s not found" % binary)
                    return False
            return self.pre_action()
        except CannotConfigureRigError:
            raise
        except Exception as err:
            self.log_error("Could not execute pre-action for action %s: %s"
                           % (self.action_name, err))
            return False

    def pre_action(self):
        """
        MAY be overriden by any rig action subclassing BaseAction.

        Prior to a monitor starting, this is called to allow rig actions to
        perform any needed setup.

        For example the network action may start a packet capture during rig
        creation and uses a pre-action to do so. The trigger_action would then
        be stopping the packet capture.
        """
        return True

    def _trigger_action(self):
        """
        This is called whenever an action should be triggered by a monitor on
        a resource.

        The action's trigger_action() method must override the default
        trigger_action() method.

        Returns:
            bool - True if trigger completes without issue or an exception
        """
        try:
            self.trigger_action()
            if self.get_option('repeat') > 0 and self.repeatable:
                while self.repeat_count < self.get_option('repeat'):
                    # sleep here instead of after the trigger so that the first
                    # repeat is also delayed from the initial execution.
                    time.sleep(self.get_option('repeat_delay'))
                    self.repeat_count += 1
                    self.log_info("Triggering action %s again. Repeat count is"
                                  " now %s. Will repeat %s times total"
                                  % (self.action_name, self.repeat_count,
                                     self.get_option('repeat')))
                    self.trigger_action()
            return True
        except Exception as err:
            self.log_error("Exception triggering action %s: %s" %
                           (self.action_name, err))
            raise

    def trigger_action(self):
        """
        MUST be overriden by a rig action subclassing BaseAction.

        This method should perform all needed actions for when a resource
        monitor is triggered.

        Does not need to return any specific value, but should raise exceptions
        when the action cannot be completed successfully (rather than returning
        False)

        If an action is generating a file to be collected, it needs to be
        handled by the action's report_result() rather than here.
        """
        raise NotImplementedError

    def _post_action(self):
        """
        This is called after a resource monitor has triggered, the action's
        trigger_action() has been called, and the resource monitor is no longer
        running.

        Returns:
            bool - True if post action completes, or raises an exception
        """
        try:
            self.post_action()
            return True
        except Exception:
            raise

    def post_action(self):
        """
        MAY be overridden by a rig action subclassing BaseAction.

        This method should perform any necessary cleanup as a result of the
        action's trigger_action().

        Does not need to return any specific value, but should raise exceptions
        when the post action cannot be comepleted successfully.
        """
        pass

    def finish_execution(self):
        """
        Called when an aciton has completed it's trigger, and we need to
        perform closing operations to cleanly exit the action.
        """
        self._report_results()
        return self.report_files
        # TODO: consider tar'ing up the tmp directory

    def _report_results(self):
        """
        This is called at the end of execution.

        This will create a single log entry that includes any of the files
        the action created and used add_report_files() with, as well as the
        add_report_message() string(s).
        """
        if not self.report_files and not self.report_message:
            return
        msg = "Action %s" % self.action_name
        if self.report_files:
            self.log_debug(msg + " generated the following files: %s" %
                           ','.join(f for f in self.report_files))
        if self.report_message:
            self.log_info(msg + " generated the following message: %s" %
                          (self.report_message))

    def add_report_file(self, filename):
        """
        Used to report file(s) that have been generated to the user.

        Positional arguments:
            filename (list or str) - The full path of the file to report to the
                    user. Can accept a string or list of strings
        """
        if not isinstance(filename, list):
            filename = [filename]
        for fname in filename:
            if not fname.startswith(self.tmp_dir):
                try:
                    shutil.move(fname, self.tmp_dir)
                except OSError:
                    self.log_error("Could not move %s to rig tmp dir %s"
                                   % (fname, self.tmp_dir))
        self.report_files.extend(filename)

    def add_report_message(self, message):
        """
        Used to provide arbritary text notifications to the user.

        Note that in the event the rig calling this action is run daemonized,
        any messages will only appear in the rig log

        Positional arguments:
            message (str) - The message to be printed/reported to the user.
        """
        if not isinstance(message, str):
            raise TypeError('message must be of type str')
        self.report_message = message

    def cleanup(self):
        """
        Used on select actions that may have bits that need to be cleanup up
        in the event that a rig fails to start, but are not automatically
        handled by the system.

        For example, with the tcpdump action there is a possiblity we could
        fail to start the rig, but still have a detached thread running the
        tcpdump command that we would want to kill
        """
        pass
