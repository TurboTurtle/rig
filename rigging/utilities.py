# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import inspect
import os

from rigging.actions import BaseAction
from rigging.commands import RigCmd
from rigging.monitors import BaseMonitor

UNITS = {
    'B': 1,
    'K': 1 << 10,
    'M': 1 << 20,
    'G': 1 << 30,
    'T': 1 << 40,
    'P': 1 << 50
}


def import_modules(modname, subclass):
    """
    Import helper to import all classes from a rig definition.

    :param modname: The module name to inspect
    :param subclass: The subclass that we should match found entities on

    :return: A list of discovered modules
    """
    mod_short_name = modname.split('.')[2]
    module = __import__(modname, globals(), locals(), [mod_short_name])
    _modules = inspect.getmembers(module, inspect.isclass)
    modules = []
    for mod in _modules:
        if not isinstance(mod, list):
            mod = [mod]
        for _mod in mod:
            if _mod[0] in ('Rigging', subclass.__name__):
                continue
            if not issubclass(_mod[1], subclass):
                continue
            modules.append(_mod)
    return modules


def find_modules(pkg, pkgstr, subclass):
    modules = []
    for path in pkg.__path__:
        if os.path.isdir(path):
            for pyfile in sorted(os.listdir(path)):
                if not pyfile.endswith('.py') or '__' in pyfile:
                    continue
                fname, ext = os.path.splitext(pyfile)
                _mod = f"{pkgstr}.{fname}"
                modules.extend(import_modules(_mod, subclass))
    return modules


def load_rig_commands():
    import rigging.commands
    cmds = rigging.commands
    rig_cmds = {}
    modules = find_modules(cmds, 'rigging.commands', RigCmd)
    for mod in modules:
        rig_cmds[mod[0].lower().rstrip('cmd')] = mod[1]
    return rig_cmds


def load_rig_monitors():
    """
    Discover locally available resource monitor types.

    Monitors are added to a dict that is later iterated over to check if
    the requested monitor is one that we have available to us.
    """
    import rigging.monitors
    monitors = rigging.monitors
    _supported_monitors = {}
    modules = find_modules(monitors, 'rigging.monitors', BaseMonitor)
    for mod in modules:
        _supported_monitors[mod[1].monitor_name.lower()] = mod[1]
    return _supported_monitors


def load_rig_actions():
    """
    Discover locally available actions
    """
    import rigging.actions
    actions = rigging.actions
    _supported_actions = {}
    modules = find_modules(actions, 'rigging.actions', BaseAction)
    for mod in modules:
        _supported_actions[mod[1].action_name.lower()] = mod[1]
    return _supported_actions


def convert_to_bytes(val):
    """
    Takes a human-friendly size value and parses it into a bytes value
    """

    size = val[:-1]
    unit = val[-1]

    if unit not in UNITS.keys():
        raise ValueError(f"Unknown unit '{unit}' provided")

    try:
        size = float(size)
    except Exception:
        raise TypeError(f"Invalid size {size} provided")

    return size * UNITS[unit]


def convert_to_human(size):
    """
    Takes a size in bytes and converts it to a human-friendly string
    """
    try:
        float(size)
    except Exception:
        return size

    for suffix, _base in sorted(UNITS.items(), key=lambda x: x[1],
                                reverse=True):
        if size >= _base:
            _size = round(float(size / _base), 2)
            return f"{_size}{suffix}"
