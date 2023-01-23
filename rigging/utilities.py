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

from rigging.commands import RigCmd
from rigging.rigs import BaseRig


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


def load_supported_rigs():
    """
    Discover locally available resource monitor types.

    Monitors are added to a dict that is later iterated over to check if
    the requested monitor is one that we have available to us.
    """
    import rigging.rigs
    monitors = rigging.rigs
    _supported_rigs = {}
    modules = find_modules(monitors, 'rigging.rigs', BaseRig)
    for mod in modules:
        _supported_rigs[mod[0].lower()] = mod[1]
    return _supported_rigs

