# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import argparse
import ast
import inspect
import logging
import os
import sys
import socket

from logging.handlers import RotatingFileHandler
from rigging.exceptions import *


class Rigging():
    '''
    Main rig class

    All resources and subcommands are initially handled here. Each of the
    supported resources or subcommands should define argparse options that are
    relevant to it.

    Positional arguments:
        parser - argparse.ArgumentParser object
        args - parsed arguments from the calling rig binary

    '''

    def __init__(self, parser, args):
        self.parser = parser
        self.args = args
        # match supported rigs and load one by name.

    def _setup_logging(self):
        '''Setup logging to /var/log/rig/rig.log'''
        self.logger = logging.getLogger('rig')
        self.logger.setLevel(logging.DEBUG)
        hndlr = RigRotatingFileHandler('/var/log/rig/rig.log')
        hndlr.setFormatter(logging.Formatter(
            '%(asctime)s::%(rig_id)s::%(levelname)s: %(message)s'))
        self.logger.addHandler(hndlr)

        # also print to console (optionally)
        self.console = logging.getLogger('rig_console')
        ui = logging.StreamHandler()
        ui.setFormatter(logging.Formatter('%(message)s'))
        self.console.setLevel(logging.DEBUG)
        self.console.addHandler(ui)

    def _import_modules(self, modname):
        '''
        Import helper to import all classes from a rig definition.
        '''
        mod_short_name = modname.split('.')[2]
        module = __import__(modname, globals(), locals(), [mod_short_name])
        modules = inspect.getmembers(module, inspect.isclass)
        for mod in modules:
            if mod[0] in ('Rigging', 'BaseRig'):
                modules.remove(mod)
        return modules

    def _load_supported_rigs(self):
        '''
        Discover locally available resource monitor types.

        Monitors are added to a dict that is later iterated over to check if
        the requested monitor is one that we have available to us.
        '''
        import rigging.rigs
        monitors = rigging.rigs
        self._supported_rigs = {}
        modules = []
        for path in monitors.__path__:
            if os.path.isdir(path):
                for pyfile in sorted(os.listdir(path)):
                    if not pyfile.endswith('.py') or '__' in pyfile:
                        continue
                    fname, ext = os.path.splitext(pyfile)
                    _mod = "rigging.rigs.%s" % fname
                    modules.extend(self._import_modules(_mod))
        for mod in modules:
            self._supported_rigs[mod[0].lower()] = mod[1]

    def log_error(self, msg):
        self.console.error(msg)

    def log_info(self, msg):
        self.console.info(msg)

    def log_debug(self, msg):
        self.console.debug(msg)

    def log_warn(self, msg):
        self.console.warn(msg)

    def execute(self):
        '''
        Based on commandline invocation, setup an appropriate rig or execute a
        subcommand.
        '''
        if self.args['subcmd'] == 'list':
            self.list_rigs()
            return 0
        self._setup_logging()
        if self.args['subcmd'] == 'destroy':
            self.args = vars(self.parser.parse_args())
            return self.destroy_rig(self.args['id'])
        # load known resource monitors
        self._load_supported_rigs()
        if self.args['subcmd'] in self._supported_rigs:
            rig = self._supported_rigs[self.args['subcmd']](self.parser)
            if rig._can_run:
                return rig.execute()
        else:
            self.log_error("Unknown rig type %s provided" %
                           self.args['subcmd'])
            return 1

    def destroy_rig(self, rig_id):
        '''
        Cleanly shutdown an existing rig with the given id

        Returns
            int - exit code based on destroy behavior
                0 - success
                1 - failed to destroy 1 or more rigs
                2 - invalid command invocation
        '''
        if rig_id == '-1':
            self.log_error("Error: 'destroy' requires a rig id or 'all'")
            return 2
        existing_rigs = os.listdir('/var/run/rig')
        if rig_id == 'all':
            rig_id = existing_rigs
        if not isinstance(rig_id, list):
            rig_id = [rig_id]
        for rig in rig_id:
            try:
                if rig in existing_rigs:
                    _rig = RigConnection(rig)
                    ret = _rig.destroy()
                    if ret == rig:
                        self.log_info("%s destroyed" % ret)
                    else:
                        self.log_error(ret)

                else:
                    self.log_error("Non-existing rig id(s) provided: %s" % rig)
                    return 1
            except BindSocketError:
                if not self.args['force']:
                    self.log_warn("Could not destroy rig %s, rig is not "
                                  "running." % rig)
                else:
                    os.remove('/var/run/rig/%s' % rig)
        return 0

    def list_rigs(self):
        '''
        Lists known rigs.
        Rigs are known by delving into /var/run/rig and querying the available
        sockets.

        This does not return anything, but instead prints directly to console.
        '''
        _fmt = "{id:7}{pid:7}{rig_type:8}{watch:30} {trigger:<35} {status:<10}"
        socks = os.listdir('/var/run/rig')
        rigs = []
        for sock in socks:
            try:
                rig = RigConnection(sock)
                rigs.append(rig.status())
            except Exception as err:
                rigs.append({
                                'id': sock,
                                'pid': ' ',
                                'rig_type': ' ',
                                'watch': '%s' % err,
                                'trigger': '',
                                'status': 'Unknown'
                            })
        print(_fmt.format(
            id='ID',
            pid='PID',
            rig_type='Type',
            watch='Watching',
            trigger='Trigger',
            status='Status'
        ))
        print('=' * 100)
        for rig in rigs:
            print(_fmt.format(**rig))


class RigConnection():
    '''
    Connect to an existing rig's socket, and be able to communicate with the
    rig.
    '''

    def __init__(self, socket_name):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        _address = "/var/run/rig/%s" % socket_name
        try:
            self.sock.connect(_address)
        except ConnectionRefusedError:
            raise BindSocketError
        except OSError:
            raise MissingSocketError(_address)

    def _rig_communicate(self, element):
        self.sock.settimeout(2)
        self.sock.sendall(element.encode())
        try:
            data = self.sock.recv(1024).decode()
        except Exception as err:
            return 'Unknown'
        return data

    def status(self):
        '''
        Query the rig's status.

        Returns
            dict of rig's status information
        '''
        return ast.literal_eval(self._rig_communicate('status'))

    def destroy(self):
        '''
        Tell the rig to shutdown cleanly and remove its socket.

        Returns
            str matching the rig ID
        '''
        return self._rig_communicate('destroy')


class RigRotatingFileHandler(RotatingFileHandler):
    '''
    The logging module does not create parent directories for specified log
    files.

    This does, so we use it to create the parent directory.
    '''

    def __init__(self, filename, mode='a', maxBytes=1048576, backupCount=5,
                 encoding=None, delay=0):
        try:
            path = os.path.split(filename)[0]
            # will fail on python2, we only support python3
            os.makedirs(path, exist_ok=True)
        except Exception as err:
            print('Could not create logfile at %s: %s' % (path, err))
            sys.exit(1)
        RotatingFileHandler.__init__(self, filename, mode, maxBytes,
                                     backupCount, encoding, delay)
