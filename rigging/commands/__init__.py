# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import logging
import os
import sys
import tempfile

from logging.handlers import RotatingFileHandler


class RigCmd():
    """
    Base class for building commands to control the operation of the `rig`
    binary. Anything that a user would invoke via `rig <cmd> [opts]` needs to
    be built from a RigCmd.
    """

    parser_description = "Base rig command class, should not see this."
    parser_usage = ''
    root_required = True
    tmpdir = None
    name = None

    def __init__(self, options):
        """
        Minimal initialization should be done here, as this is the main builder
        class for all rig commands. Options are set, and logging is initialzed
        here.

        Logging is not setup by default. If a command needs to log to a file,
        the command needs to call `_setup_logging()` within its own `execute()`
        or the attempts to log will fail.

        :param options: The options as parsed from `parse_args()` from the
                        cmdline string.
        :type options:  dict
        """
        self.options = options

    @classmethod
    def add_parser_options(cls, parser):
        """
        Add command-specific options to the (sub) parser. Note that this method
        should NOT return the parser explicitly.
        """
        pass

    def execute(self):
        """
        The main entry point for rig commands. All commands will need to
        override this method to define how they perform whatever it is they are
        meant to do.
        """
        raise NotImplementedError('This command has not been defined')

    def _setup_logging(self):
        """
        Setup the logging mechanisms we will use for this rig. Note that all
        rigs will log to both /var/log/rig/rig.log and to a rig-specific file
        that will be included in the final tarball that gets produced for a
        trigger rig.
        """
        if not self.tmpdir:
            self.tmpdir = tempfile.mkdtemp(prefix='rig.', dir='/var/tmp/')
        self.logger = logging.getLogger('rig')
        self.logger.setLevel(logging.DEBUG)
        self._main_log = '/var/log/rig/rig.log'
        self._private_log = os.path.join(self.tmpdir, f"rig_{self.name}.log")
        for flog in [self._main_log, self._private_log]:
            _flog = RigRotatingFileHandler(flog)
            _flog.setFormatter(logging.Formatter(
                '%(asctime)s::%(rig_id)s::%(levelname)s: %(message)s'))
            self.logger.addHandler(_flog)
        self.logger = logging.LoggerAdapter(self.logger,
                                            extra={'rig_id': self.name})


class RigRotatingFileHandler(RotatingFileHandler):
    """
    The logging module does not create parent directories for specified log
    files.

    This does, so we use it to create the parent directory.
    """

    def __init__(self, filename, mode='a', maxBytes=1048576, backupCount=5,
                 encoding=None, delay=0):
        try:
            path = os.path.split(filename)[0]
            # will fail on python2, we only support python3
            os.makedirs(path, exist_ok=True)
        except Exception as err:
            print('Could not create logfile at %s: %s' % (filename, err))
            sys.exit(1)
        RotatingFileHandler.__init__(self, filename, mode, maxBytes,
                                     backupCount, encoding, delay)
