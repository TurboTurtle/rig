# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import os
import re
import select

from rigging.monitors import BaseMonitor
from systemd import journal


class Logs(BaseMonitor):
    """
    This monitor is used to watch log files and/or journals for specific
    messages or message patterns.

    Multiple files may be specified as may multiple journal units. To watch
    the 'main' journal instead of a specific unit, the value of 'system' is
    used.
    """

    monitor_name = 'logs'

    def configure(self, message, files='/var/log/messages', journals='system'):
        """
        :param message: A string or python regex pattern to match
        :param files: A file or list of files to watch
        :param journals: A unit or list of units to watch
        """
        self.message = self.validate_message(message)

        try:
            if files is None:
                files = []
            if isinstance(files, str):
                files = [files]
            self.files = [f for f in files if os.path.exists(f)]
        except Exception:
            raise Exception(
                f"'files' must be string, list, or null; not {files.__class__}"
            )

        try:
            if journals is None:
                journals = []
            if isinstance(journals, str):
                journals = [journals]
            self.journals = [j for j in journals if j]
        except Exception:
            raise Exception(
                f"'journals' must be string, list, or null; not "
                f"{journals.__class__}"
            )

        if not self.files and not self.journals:
            raise Exception('No existing files or journals specified')

        if self.journals:
            self.add_monitor_thread(self.watch_journal, (self.journals,))

        if self.files:
            for log in self.files:
                self.add_monitor_thread(self.watch_file, (log, ))

    def validate_message(self, message):
        """
        Validate that the string passed to message is usable by the python
        `re` module for pattern matching.

        :param message: The message or pattern string to match against

        :return: A compiled regex based on message, else raise Exception
        """
        if not isinstance(message, str):
            raise Exception(
                f"'message' must be string, not {message.__class__}"
            )

        try:
            return re.compile(message, re.I)
        except re.error:
            raise Exception(
                f'\'message\' parameter {message} does not compile. Patterns '
                f'must be python-regex compliant.'
            )
        except Exception as err:
            self.logger.debug(f"Could not compile 'message': {err}")
            raise

    def _match_line(self, line):
        """
        Compare a sourced line to the message pattern this monitor is meant
        to look for.

        :param line: A line sourced from a log file or journal

        :return: True if a match is found, else False
        """
        return self.message.match(line.strip())

    def watch_journal(self, journals):
        """
        Watches the journal for new entries and compares them to the provided
        message option

        Note that all journals specified will be monitored via single reader
        rather than one per journal like we (need to) do with files. This
        should reduce system load on polling journald to a minimum.

        :param journals: A list of journal units to watch. Use 'system' for the
                         full journal

        """
        journ = journal.Reader()
        journ.log_level(journal.LOG_INFO)
        journ.this_boot()
        journ.this_machine()
        self.logger.info(f"Beginning watch of journal(s): {journals}")
        for unit in journals:
            if unit == 'system':
                continue
            j = unit
            if not unit.endswith('.service'):
                j += '.service'
            journ.add_match(_SYSTEMD_UNIT=j)
        journ.seek_tail()
        journ.get_previous()
        _poll = select.poll()
        _journ_fd = journ.fileno()
        _poll_event = journ.get_events()
        _poll.register(_journ_fd, _poll_event)

        while True:
            if _poll.poll(self.config['interval']):
                if journ.process() == journal.APPEND:
                    for entry in journ:
                        if self._match_line(entry['MESSAGE']):
                            self.logger.info(
                                f"Logged message in journal matches pattern "
                                f"'{self.message.pattern}'"
                            )
                            return True

    def watch_file(self, filename):
        """
        Watch a file for a line that matches the specified message pattern.

        There will be a separate thread for each file specified.

        :param filename: The absolute filepath of the file to monitor
        """
        with open(filename, 'r') as wfile:
            self.logger.info(f'Beginning watch of file {filename}')
            logs = self._read_file(wfile)
            for line in logs:
                line = line.strip()
                if self._match_line(line):
                    self.logger.info(
                        f"Logged message in {filename} matches pattern "
                        f"'{self.message.pattern}'"
                    )
                    return True

    def _read_file(self, fileobj):
        """
        A generator that allows us to read from the file line by line as new
        lines are written to it.
        """
        fileobj.seek(0, 2)
        while True:
            line = fileobj.readline()
            if not line:
                self.wait_loop()
                continue
            yield line
