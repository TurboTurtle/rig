# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

import os

from pathlib import Path
from rigging.monitors import BaseMonitor
from rigging.utilities import convert_to_bytes, convert_to_human


class Filesystem(BaseMonitor):
    """
    Monitor a filesystem, directory, or file for changes. Changes that can be
    monitored include changes-on-disk, size reaching a threshold, creation,
    deletion, and more.
    """

    monitor_name = 'filesystem'

    def configure(self, path, size=None, used_perc=None, used_size=None):
        """
        :param path: The path of the directory/file to monitor
        :param size: Threshold size of `path` to trigger on
        :param used_perc: Threshold of backing filesystem space used as
                          a percent to trigger on
        :param used_size: Total used amount of backing filesystem space to
                          trigger on
        """
        if not any([size, used_perc, used_size]):
            raise Exception("Must specify at least one of 'size', 'used_perc',"
                            " or 'used_size'")

        self.path = Path(path)
        if not self.path.exists():
            raise Exception(f"Provided path '{path}' does not exist")

        self.stats = {
            'size': size,
            'used_perc': used_perc,
            'used_size': used_size
        }

        if size:
            self.add_monitor_thread(self.watch_path_size, (size,))

        if used_perc or used_size:
            self.add_monitor_thread(self.watch_fs_used, (used_perc, used_size))

    def watch_path_size(self, size):
        """
        Watch the specified path's size and trigger if it meets or exceeds the
        given size.

        :param size: The threshold size to monitor the configured path for
        """
        max_size = convert_to_bytes(size)
        while True:
            if self.path.is_dir():
                cur_size = sum(f.stat().st_size for f in self.path.glob('**/*')
                               if f.is_file())
            else:
                cur_size = self.path.stat().st_size

            if cur_size >= max_size:
                self.logger.info(
                    f"Size of path {self.path.as_posix()} is "
                    f"{convert_to_human(cur_size)}, exceeding threshold of "
                    f"{size}."
                )
                return True

            self.wait_loop()

    def watch_fs_used(self, used_perc=None, used_size=None):
        """
        Watch the backing filesystem for a provided path for either
        total used size or used percentage threshold.

        :param used_perc: Percentage as an integer to watch utilization for
        :param used_size: Absolute used size to watch utilization for
        """
        fs_stat = os.statvfs(self.path)
        # Get full size of fs in bytes
        fs_size = fs_stat.f_frsize * fs_stat.f_blocks
        # Determine max allowed bytes used based on --fs-used or --fs-size
        if used_perc:
            fs_max_used = (fs_size * (used_perc / 100))
        elif used_size:
            fs_max_used = convert_to_bytes(used_size)
        else:
            raise Exception("Monitoring a backing filesystem requires either "
                            "'used_perc' or 'used_size' parameters")

        self.logger.debug(
            f"Determined max allowed used space for {self.path.as_posix()} to "
            f"be {fs_max_used}B"
        )

        while True:
            fs = os.statvfs(self.path)
            # Get current used amount in bytes
            free = fs.f_frsize * fs.f_bfree
            current_used = fs_size - free
            if current_used > fs_max_used:
                perc = round((current_used/fs_size * 100))
                self.logger.info(
                    f"Used space on {self.path.as_posix()} is "
                    f"{convert_to_human(current_used)} ({perc}%) exceeding "
                    f"threshold of {convert_to_human(fs_max_used)}."
                )
                return True
            self.wait_loop()

    @property
    def monitoring(self):
        info = {'path': self.path.as_posix()}
        for k, v in self.stats.items():
            if v is not None:
                info[k] = f">= {v}"
        return info
