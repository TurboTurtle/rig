# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import os
import shlex
import shutil
import time

from subprocess import Popen, PIPE


def check_exists(binary):
    """
    Checks to see if the given binary exists in PATH.

    :param binary: The binary/command to verify existence of
    """
    paths = os.environ.get("PATH", "").split(os.path.pathsep)
    cmds = [os.path.join(p, binary) for p in paths]
    return any(os.access(path, os.X_OK) for path in cmds)


class BaseAction():
    """
    The base class to build actions from. Actions are what rig will execute
    once any configured monitor(s) have triggered. Unlike monitors which each
    run in a separate thread concurrently, actions run serially from the main
    thread for the most part. Some actions may be executed at the start of
    monitoring and only be ended when the rig is triggered.

    Actions will need to override the `trigger()` method to define their
    collections. Actions that begin execution at the start of monitoring will
    need to have their `trigger()` methods stop whatever execution is occurring
    and must set those executions to be non-blocking from the `pre_action()`
    entry point.
    """

    required_binaries = ()
    action_name = 'Undefined'
    description = 'description not set'
    priority = 100
    repeatable = False

    def __init__(self, config, logger, tmpdir, **kwargs):
        """
        Here we handle global options like 'repeat' so that individual actions
        don't need to explicitly define them every time.

        We pass on any remaining kwargs that serve as action options to the
        action's `configure()` method.
        """
        self.action_files = []
        self.logger = logger
        self.config = config
        self.tmpdir = tmpdir
        for opt in ['repeat', 'repeat_delay']:
            self.config[opt] = kwargs.pop(opt, self.config[opt])

        for binary in self.required_binaries:
            if not check_exists(binary):
                raise Exception(f"Required binary '{binary}' not found")

    def configure(self, **kwargs):
        """
        Actions will need to override this method to support action options.
        Options should be created by defining them as parameters to this
        method.

        This method should also be used to validate that configuration.
        """
        raise NotImplementedError(
            f"Action {self.action_name} does not self-configure"
        )

    def pre_action(self):
        """
        This method should perform any necessary initial setup for an action,
        such as investigating host configuration or kicking off background
        processes that should be terminated when the rig triggers (e.g. the
        tcpdump action)

        Does not need to return any specific value, but should raise exceptions
        when the pre action cannot be completed successfully.
        """
        pass

    def post_action(self):
        """
        This method should perform any necessary cleanup as a result of the
        action's `trigger()`.

        Does not need to return any specific value, but should raise exceptions
        when the post action cannot be completed successfully.
        """
        pass

    def cleanup(self):
        """
        Any potential cleanup that an action needs to perform, regardless of
        if the rig was successfully triggered or not, should be defined here
        instead of in `post_action()` which is only called after a successful
        call of `trigger()`.
        """
        pass

    def trigger(self):
        """
        Actions will need to override this method to define the behavior of the
        action once the rig has been triggered by a monitor.
        """
        raise NotImplementedError(
            f"Action {self.__name__.lower()} does not define trigger behavior"
        )

    def trigger_action(self):
        """
        Wrapper used by `BaseRig` to call an action's `trigger()`, as well as
        automatically handling any configured repeating.

        :return: True if successful, else raise Exception
        """
        self.repeat_count = 0
        try:
            self.trigger()
            if self.config['repeat'] and self.repeatable:
                while self.repeat_count < self.config['repeat']:
                    # sleep here instead of after the trigger so that the first
                    # repeat is also delayed from the initial execution.
                    time.sleep(self.config['repeat_delay'])
                    self.repeat_count += 1
                    self.logger.info(
                        f"Triggering action {self.action_name} again. Repeat "
                        f"count is now {self.repeat_count}. Will repeat "
                        f"{self.config['repeat']} times total"
                    )
                    self.trigger()
            self.post_action()
            return True
        except Exception as err:
            self.logger.error(
                f"Exception triggering action {self.action_name}: {err}"
            )
            raise
        finally:
            self.cleanup()

    def exec_cmd(self, cmd, timeout=180):
        """
        Executes the given command via Popen() without getting a TTY.

        :param cmd: The command to execute as a string
        :param timeout: The amount of time in seconds to allow cmd to run

        :return: dict of {status, output, stderr}
        """
        self.logger.debug(f"Running command {cmd}")
        cmd = shlex.split(cmd)
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, encoding='utf-8',
                     shell=False)
        stdout, stderr = proc.communicate(timeout=timeout)
        rc = proc.returncode
        return {'status': rc, 'stdout': stdout, 'stderr': stderr}

    def add_archive_file(self, filename):
        """
        Add a file to the archive that will be generated at the conclusion of
        this rig.

        :param filename: The absolute filename of the file to add
        """
        if not filename.startswith(self.tmpdir):
            try:
                shutil.move(filename, self.tmpdir)
            except Exception as err:
                self.logger.error(
                    f"Unable to move {filename} to final rig archive: {err}"
                )
                return False
        self.action_files.append(filename)

    def finish_execution(self):
        """
        Called when an action has completed its main execution, and we need to
        log the results and report back any files created by the action.

        :return: List of created files, may be empty
        """
        if self.action_files:
            self.logger.info(
                f"Action {self.action_name} created files "
                f"{', '.join(f.split('/')[-1] for f in self.action_files)}"
            )
        return self.action_files

    def get_info(self):
        """
        Get information on the action and it's configuration in a way that is
        easily returned by the `rig info` command. This should be a dict that
        can be converted to JSON (so type restrictions apply).

        Calls the action's `produces` property.

        :return: dict containing configuration information
        """
        return {
            'type': self.action_name,
            'produces': self.produces
        }

    @property
    def produces(self):
        return 'undefined'
