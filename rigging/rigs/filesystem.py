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
from pathlib import Path

import os
import time


class Filesystem(BaseRig):
    """Monitor a filesystem, directory, or file.

    May watch an entity for changes, reaching a size threshold, creation or
    deletion, and more.
    """

    parser_description = 'Monitor a filesystem, directory, or file.'

    def set_parser_options(self, parser):
        parser.add_argument('--path', type=str,
                            help='Specify the path to monitor')

        parser.add_argument('--size', type=str,
                            help=('Trigger if directory/file size exceeds '
                                  'this threshold')
                            )
        parser.add_argument('--fs-used', type=int,
                            help=('Trigger if FS backing --path if over this '
                                  '%% used')
                            )
        parser.add_argument('--fs-size', type=str,
                            help=('Trigger if FS backing --path is over this '
                                  'total size'))
        return parser

    @property
    def watching(self):
        return self.get_option('path')

    @property
    def trigger(self):
        msg = "%s over" % self.get_option('path')
        if self.get_option('size'):
            msg += " %s in size" % self.get_option('size')
        if self.get_option('fs_used'):
            msg += " %s%% used filesystem space" % self.get_option('fs_used')
        if self.get_option('fs_size'):
            msg += " %s filesystem space utilized" % self.get_option('fs_size')
        return msg

    def _fmt_size(self, val):
        """Takes the size value and parses it into a bytes value
        """
        units = {
            'K': 1024,
            'M': 1048576,
            'G': 1073741824,
            'T': 1099511627776
        }
        size = val[:-1]
        unit = val[-1]

        try:
            size = float(size)
        except Exception:
            raise CannotConfigureRigError("Invalid size '%s' provided" % size)

        if unit not in units.keys():
            raise CannotConfigureRigError("Unknown unit '%s' provided" % unit)

        return size * units[unit]

    def setup(self):
        if not self.get_option('path'):
            raise CannotConfigureRigError('Must specify path to watch')

        path = Path(self.get_option('path'))
        if not path.exists():
            raise CannotConfigureRigError(
                "Path '%s' does not exist" % self.get_option('path')
            )

        if self.get_option('size'):
            size = self._fmt_size(self.get_option('size'))
            self.add_watcher_thread(target=self.watch_path_size,
                                    args=(path, size))

        if self.get_option('fs_used') or self.get_option('fs_size'):
            self.add_watcher_thread(target=self.watch_fs_used,
                                    args=path)

    def watch_fs_used(self, path):
        """Watch the filesystem backing the specified path, and trigger if it
        exceeds the --fs-used/size used space
        """
        fs_stat = os.statvfs(path)
        # Get full size of fs in bytes
        fs_size = fs_stat.f_frsize * fs_stat.f_blocks
        # Determine max allowed bytes used based on --fs-used or --fs-size
        if self.get_option('fs_used'):
            fs_max_used = (fs_size * (self.get_option('fs_used') / 100))
        else:
            fs_max_used = self._fmt_size(self.get_option('fs_size'))

        self.log_debug("Determined max allowed used space for %s to be %sB"
                       % (path, fs_max_used))

        while True:
            fs = os.statvfs(path)
            # Get current used amount in bytes
            free = fs.f_frsize * fs.f_bfree
            current_used = fs_size - free
            if current_used > fs_max_used:
                perc = round((current_used/fs_size * 100))
                self.log_info("Used space on %s is %sB (%s%%) exceeding "
                              "threshold of %sB."
                              % (path, current_used, perc, fs_max_used))
                return True
            time.sleep(1)

    def watch_path_size(self, path, size):
        """Watch the specified path and trigger if its size exceeds the
        provided --size in bytes
        """

        while True:
            if path.is_dir():
                cur_size = sum(f.stat().st_size for f in path.glob('**/*')
                               if f.is_file())
            else:
                cur_size = path.stat().st_size

            if cur_size > size:
                self.log_info(
                    "Size of path '%s' is %s bytes, exceeding threshold of %s."
                    % (self.get_option('path'), cur_size, size)
                )
                return True

            time.sleep(1)
