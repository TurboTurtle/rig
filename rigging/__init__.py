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
import json
import logging
import os
import sys
import socket

from logging.handlers import RotatingFileHandler
from rigging.exceptions import *

__version__ = '1.1'


class Rigging():
    """
    Main rig class

    All resources and subcommands are initially handled here. Each of the
    supported resources or subcommands should define argparse options that are
    relevant to it.

    Positional arguments:
        parser - argparse.ArgumentParser object
        args - parsed arguments from the calling rig binary

    """

    def __init__(self, parser, args, supported_rigs=None):
        self.parser = parser
        self.args = args
        self.supported_rigs = supported_rigs

    def _setup_logging(self):
        """Setup logging to /var/log/rig/rig.log"""
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
        self.console.setLevel(logging.INFO)
        self.console.addHandler(ui)

    def log_error(self, msg):
        self.console.error(msg)

    def log_info(self, msg):
        self.console.info(msg)

    def log_debug(self, msg):
        self.console.debug(msg)

    def log_warn(self, msg):
        self.console.warn(msg)

    def parse_rig_args(self):
        """
        Parse passed args from the cmdline right now, rather than waiting for
        a specific rig to do so
        """
        self.args = vars(self.parser.parse_args())

    def get_id(self):
        """
        Return the value of --id, or raise exception if not provided
        """
        self.parse_rig_args()
        if 'id' in self.args.keys() and self.args['id']:
            return self.args['id']
        print('No rig ID provided, specify a rig with -i/--id')
        raise SystemExit(1)

    def execute(self):
        """
        Based on commandline invocation, setup an appropriate rig or execute a
        subcommand.
        """
        if self.args['subcmd'] == 'list':
            self.list_rigs()
            return 0
        if self.args['subcmd'] == 'info':
            try:
                _rig = RigConnection(self.get_id())
                print(_rig.info())
            except MissingSocketError:
                print("No such rig exists: %s" % self.args['id'])
            return
        self._setup_logging()
        if self.args['subcmd'] == 'destroy':
            return self.destroy_rig(self.get_id())
        if self.args['subcmd'] == 'trigger':
            return self.trigger_rig(self.get_id())
        # load known resource monitors
        if self.args['subcmd'] in self.supported_rigs:
            rig = self.supported_rigs[self.args['subcmd']](self.parser)
            if rig._can_run:
                return rig.execute()
        else:
            self.log_error("Unknown rig type %s provided" %
                           self.args['subcmd'])
            return 1

    def trigger_rig(self, rig_id):
        """
        Trigger a rig right now, rather than waiting for a trigger condition to
        be met.

        Returns
            int - exit code based on success of triggering
                0 - success
                1 - failed to trigger
                2 - invalid command invocation
        """
        if rig_id == '-1':
            self.log_error('Error:  \'trigger\' requires a rig id')
            return 2
        try:
            _rig = RigConnection(rig_id)
            try:
                ret = _rig.trigger()
                if ret['success']:
                    print("Manually triggered rig %s" % rig_id)
                else:
                    print("Failed to trigger rig %s" % rig_id)
                    return 1
            except Exception as err:
                self.log_error("Could not manually trigger rig %s: %s"
                               % (rig_id, err))
                return 1
        except MissingSocketError:
            self.log_error("Non-existing rig %s specified" % rig_id)
            return 1
        return 0

    def destroy_rig(self, rig_id):
        """
        Cleanly shutdown an existing rig with the given id

        Returns
            int - exit code based on destroy behavior
                0 - success
                1 - failed to destroy 1 or more rigs
                2 - invalid command invocation
        """
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
                    if ret['success'] and ret['id'] == rig:
                        self.log_info("%s destroyed" % ret['id'])
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
        """
        Lists known rigs.
        Rigs are known by delving into /var/run/rig and querying the available
        sockets.

        This does not return anything, but instead prints directly to console.
        """
        _fmt = "{id:7}{pid:7}{rig_type:8}{watch:30} {trigger:<35} {status:<10}"
        try:
            socks = os.listdir('/var/run/rig')
        except Exception:
            socks = []
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
    """
    Connect to an existing rig's socket, and be able to communicate with the
    rig.
    """

    def __init__(self, socket_name):
        self.name = socket_name
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        _address = "/var/run/rig/%s" % socket_name
        try:
            self.sock.connect(_address)
        except ConnectionRefusedError:
            raise BindSocketError
        except OSError:
            raise MissingSocketError(_address)

    def _rig_communicate(self, command, extra=''):
        """
        Facilitates communicating with the rig over the socket the rig is
        listening on.

        Messages are sent as json, and at current support the following
        elements:
            command:    the command/function that the rig should run/return
            extra:      Optional, any value that should be passed to the
                        function specified by command

        Returns:
            A dict with the rig's ID, the command that was run, a 'success'
            boolean that indicates if the command was run successfully or not,
            and the resulting output from the command.
        """
        cmd = json.dumps({
            'command': command,
            'extra': extra
        })
        self.sock.settimeout(2)
        self.sock.sendall(cmd.encode())
        try:
            data = self.sock.recv(1024)
        except Exception as err:
            return {'id': None, 'command': 'Unknown', 'success': False}
        return data

    def status(self):
        """
        Query the rig's status.

        Returns
            dict of rig's status information
        """
        try:
            ret = json.loads(self._rig_communicate('status').decode())
            if ret['success']:
                return ast.literal_eval(ret['result'])
        except Exception as err:
            print("Error retreiving status for %s: %s" % (self.name, err))
            return {
                'id': self.name,
                'pid': '',
                'rig_type': '',
                'watch': 'Error retrieving status',
                'trigger': '',
                'status': 'Unknown'
            }

    def info(self):
        """
        Query detailed rig information
        """
        ret = json.loads(self._rig_communicate('info').decode())
        if ret['success']:
            return json.dumps(ast.literal_eval(ret['result']), indent=4)
        return ''

    def destroy(self):
        """
        Tell the rig to shutdown cleanly and remove its socket.

        Returns
            str matching the rig ID
        """
        return json.loads(self._rig_communicate('destroy').decode())

    def trigger(self):
        """
        Triggers the rig
        """
        return json.loads(self._rig_communicate('manual_trigger').decode())


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
            print('Could not create logfile at %s: %s' % (path, err))
            sys.exit(1)
        RotatingFileHandler.__init__(self, filename, mode, maxBytes,
                                     backupCount, encoding, delay)
