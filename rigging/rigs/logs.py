# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import os
import re
import select
import time

from rigging.rigs import BaseRig
from rigging.exceptions import CannotConfigureRigError
from systemd import journal


class Logs(BaseRig):
    '''
    Supports watching one or more log files and/or one or more journals.
    May also watch the system journal.

    Resource triggers and argparse options:
        :opt logfile: The full path of the file(s) to watch. Defaults to
            /var/log/messages.
        :opt journal: The name of the journal unit to watch. Defaults to
            the system journal.
        :opt no-files: Disable watching log files
        :opt no-journal: Disable watching the journal
        :opt message: Trigger string (capable of shell-style regex) to
            watch logfile or journal for.
    '''

    parser_description = ('Watch one or more log files and/or one or more '
                          'journals for a specified log message')

    def set_parser_options(self, subparser):
        subparser.add_argument('--logfile', default='/var/log/messages',
                               help='log(s) to be watched')
        subparser.add_argument('--journal', default='system',
                               help='journal unit(s) to be watched')
        subparser.add_argument('--no-files', default=False,
                               action='store_true',
                               help='Do not watch any log files')
        subparser.add_argument('--no-journal', default=False,
                               action='store_true',
                               help='Do not watch any journals')
        subparser.add_argument('-m', '--message', required=True,
                               help='String to trigger against')
        subparser.add_argument('--count', default=1, type=int,
                               help=('Trigger only after message has been '
                                     'matched this many times'))
        return subparser

    @property
    def watching(self):
        files = (self.get_option('logfile').replace('/var/log/', '') if not
                 self.get_option('no_files') else '')
        units = ('journals: ' + self.get_option('journal') if not
                 self.get_option('no_journal') else 'no journals')
        watch = [files] + [units]
        ret = ', '.join([w for w in watch if w])
        return ret

    @property
    def trigger(self):
        return self.get_option('message')

    def setup(self):
        '''
        Watch logs and/or unit files for the provided message
        '''
        self.counter = 0
        self.message = self.get_option('message')
        watch_files = []
        watch_units = []
        watcher_threads = []
        if not self.get_option('no_files'):
            for mfile in self.get_option('logfile').split(','):
                if os.path.isfile(mfile):
                    watch_files.append(mfile)
                else:
                    if (mfile == '/var/log/messages' and not
                            self.get_option('no_journal')):
                        self.log_info(
                            'This system does not have a %s file. '
                            'Ignoring files and only watching journal'
                            % mfile)
                        continue
                    msg = "%s is not a file. Aborting..." % mfile
                    raise CannotConfigureRigError(msg)
        if not self.get_option('no_journal'):
            _j = self.get_option('journal')
            self.add_watcher_thread(target=self.watch_journal, args=_j)
        for wfile in watch_files:
            self.add_watcher_thread(target=self.watch_file, args=wfile)

    def watch_journal(self, journals):
        '''
        Watches the journal for new entries and compares them to the provided
        message option

        Note that all journals specified will be monitored via single reader
        rather than one per journal like we (need to) do with files. This
        should reduce system load on polling journald to a minimum.

        Positional arguments
            journals - a list of journal units to filter on. If empty, we are
                       monitoring the full system journal

        Returns
            bool - True when message is matched
        '''
        _journs = journals.split(',')
        journ = journal.Reader()
        journ.log_level(journal.LOG_INFO)
        journ.this_boot()
        journ.this_machine()
        self.log_info("Beginning watch of journal(s): %s" % _journs)
        for unit in _journs:
            if unit == 'system':
                continue
            j = unit
            if not j.endswith('.service'):
                j += '.service'
            journ.add_match(_SYSTEMD_UNIT=j)
        journ.seek_tail()
        journ.get_previous()
        _poll = select.poll()
        _journ_fd = journ.fileno()
        _poll_event = journ.get_events()
        _poll.register(_journ_fd, _poll_event)

        while True:
            if _poll.poll(500):
                if journ.process() == journal.APPEND:
                    for entry in journ:
                        if self._match_line(entry['MESSAGE'], 'journal'):
                            return True

    def _match_line(self, line, src):
        '''
        Helper function that simply looks for a regex match between the given
        line or journal entry and the provided message

        Positional arugments
            line - the line check for a match against the message option
            src  - where the line is coming from, used for logging purposes

        Returns
            bool - did line match the message option *and* is the count option
                   threshold met.
        '''
        if re.match(self.message, line):
            self.counter += 1
            self.log_info(
                "Matched user-specified message \"%s\" against line \"%s\""
                " from %s. Message counter at %s of max %s."
                % (self.message, line, src, self.counter,
                   self.get_option('count'))
            )
            return self.counter >= self.get_option('count')
        return False

    def _read_file(self, fileobj):
        '''
        Takes an open file object and continually reads from it

        Lifted from David Beazley's Generator Tricks for Python.
        '''
        fileobj.seek(0, 2)
        while True:
            line = fileobj.readline()
            if not line:
                time.sleep(1)
                continue
            yield line

    def watch_file(self, filename):
        '''
        Watches the provided filename for the given message

        Positional arguments:
            filename - the full path of the file to watch

        Blocks until rig option message is matched in the file

        Returns:
             bool - True when message is matched
        '''
        with open(filename, 'r') as wfile:
            self.log_info('Beginning watch of file %s' % filename)
            logs = self._read_file(wfile)
            for line in logs:
                line = line.strip()
                if self._match_line(line, filename):
                    return True
