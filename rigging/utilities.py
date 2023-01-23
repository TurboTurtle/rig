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

from rigging.rigs import BaseRig


def import_modules(modname):
    """
    Import helper to import all classes from a rig definition.
    """
    mod_short_name = modname.split('.')[2]
    module = __import__(modname, globals(), locals(), [mod_short_name])
    _modules = inspect.getmembers(module, inspect.isclass)
    modules = []
    for mod in _modules:
        if not isinstance(mod, list):
            mod = [mod]
        for _mod in mod:
            if _mod[0] in ('Rigging', 'BaseRig'):
                continue
            if not issubclass(_mod[1], BaseRig):
                continue
            modules.append(_mod)
    return modules


def load_supported_rigs():
    """
    Discover locally available resource monitor types.

    Monitors are added to a dict that is later iterated over to check if
    the requested monitor is one that we have available to us.
    """
    import rigging.rigs
    monitors = rigging.rigs
    _supported_rigs = {}
    modules = []
    for path in monitors.__path__:
        if os.path.isdir(path):
            for pyfile in sorted(os.listdir(path)):
                if not pyfile.endswith('.py') or '__' in pyfile:
                    continue
                fname, ext = os.path.splitext(pyfile)
                _mod = "rigging.rigs.%s" % fname
                modules.extend(import_modules(_mod))
    for mod in modules:
        _supported_rigs[mod[0].lower()] = mod[1]
    return _supported_rigs
