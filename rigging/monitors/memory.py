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
from rigging.utilities import convert_to_bytes, convert_to_human


class MemoryMonitor(BaseMonitor):
    """
    Watches memory usage statistics of the system, and may trigger based on
    availability or usage of specific memory stats or overall memory usage.

    When providing a value for total memory usage, users should use the
    suffixes K, M, G, or T.
    """

    monitor_name = 'memory'

    def configure(self, percent=None, used=None, slab=None):
        """
        :param percent: Memory usage threshold expressed as a percentage
        :param used: Threshold for total amount of memory used
        :param slab: Threshold for total amount of slab
        """
        _mem_metrics = {
            'percent': percent,
            'used': used,
            'slab': slab
        }

        if not any(m is not None for m in _mem_metrics.values()):
            raise Exception(
                f"Must specify at least one of "
                f"{', '.join(m for m in _mem_metrics.keys())}."
            )

        for _m in _mem_metrics:
            if _mem_metrics[_m] is not None:
                if _m == 'percent':
                    try:
                        float(_mem_metrics[_m])
                    except Exception:
                        raise Exception(f"'percent' must be integer or float. "
                                        f"Not {_mem_metrics[_m].__class__}")
                else:
                    try:
                        convert_to_bytes(_mem_metrics[_m])
                    except ValueError:
                        raise Exception(
                            f"Invalid unit '{_mem_metrics[_m][-1]}'. "
                            f"Use K, M, G, or T"
                        )
                    except TypeError:
                        raise Exception(
                            f"'{_m}' must be integer or float. "
                            f"Not {_mem_metrics[_m].__class__}"
                        )
                    except Exception as err:
                        raise Exception(
                            f"Unexpected error parsing {_m}: {err}"
                        )

        self.add_monitor_thread(self.watch_memory_usage, (_mem_metrics, ))

    def watch_memory_usage(self, metrics):
        """
        Monitor system memory usage for specified statistics, and trigger if
        any of the metrics are exceeded,

        :param metrics: dict of statistics and their threshold values to
                        compare against psutil reporting
        """
        _mem = {}
        for _metric in metrics:
            if metrics[_metric] is not None:
                if _metric == 'percent':
                    _mem[_metric] = float(metrics[_metric])
                else:
                    _mem[_metric] = convert_to_bytes(metrics[_metric])

        # first result is sometimes garbage
        psutil.virtual_memory()
        while True:
            _poll = psutil.virtual_memory()
            for metric in _mem:
                _val = float(getattr(_poll, metric))
                if _val >= _mem[metric]:
                    if metric == 'percent':
                        self.logger.info(
                            f"Memory usage of {_val}% exceeds specified "
                            f"threshold of {_mem[metric]}%."
                        )
                        return True
                    self.logger.info(
                        f"Memory {metric} usage of {convert_to_human(_val)} "
                        f"exceeds specified threshold of "
                        f"{convert_to_human(_mem[metric])}."
                    )
                    return True
            self.wait_loop()
