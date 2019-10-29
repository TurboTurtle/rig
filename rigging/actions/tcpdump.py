# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import datetime as dt
import glob
import os
import shlex
import subprocess

from pipes import quote
from rigging.actions import BaseAction
from rigging.exceptions import CannotConfigureRigError

TCPDUMP_BIN = '/usr/sbin/tcpdump'
# -Z is needed to avoid the privilege drop that happens before opening the
# first savefile, which would result in an ENOPERM and a failed rig
TCPDUMP_OPTS = '-Z root -s 0 -n'


class Tcpdump(BaseAction):
    '''
    Start a tcpdump and stop it once the trigger condition is met
    '''

    action_name = 'tcpdump'
    enabling_opt = 'tcpdump'
    enabling_opt_desc = 'Start a tcpdump that ends when rig is triggered'
    priority = 2
    required_binaries = ('tcpdump',)

    def add_action_options(self, parser):
        parser.add_argument('--tcpdump', action='store_true',
                            help=self.enabling_opt_desc)
        parser.add_argument('--filter', default=None,
                            help='Packet filter to use')
        parser.add_argument('--iface', '--interface', default='eth0',
                            help='Interface to listen on (default eth0)')
        parser.add_argument('--size', default=10, type=int,
                            help='Maximum size of packet capture in MB')
        parser.add_argument('--captures', default=1, type=int,
                            help='Number of capture files to keep')
        return parser

    def pre_action(self):
        '''
        Launch the tcpdump
        '''
        _date = dt.datetime.today().strftime("%d-%m-%Y-%H:%M:%S")
        name = "%s-%s-%s" % (self.exec_cmd('hostname')['stdout'].strip(),
                             _date,
                             self.get_option('iface'))
        self.loc = "%s%s.pcap" % (self.tmp_dir, name)
        cmd = ("%s %s -i %s -C %s -W %s "
               % (TCPDUMP_BIN, TCPDUMP_OPTS, self.get_option('iface'),
                  self.get_option('size'), self.get_option('captures'))
               )
        cmd += "-w %s" % self.loc
        if self.get_option('filter'):
            cmd += " %s" % quote(self.get_option('filter'))
        self.log_debug("Running tcpdump as '%s'" % cmd)
        self.devnull = open(os.devnull, 'w')
        self.proc = subprocess.Popen(shlex.split(cmd), shell=False,
                                     stdout=self.devnull,
                                     stderr=subprocess.PIPE)
        try:
            # if we hit an error in the first second of execution, it means
            # tcpdump was configured incorrectly
            stdout, stderr = self.proc.communicate(timeout=1)
            if stderr:
                raise CannotConfigureRigError(stderr.decode('utf-8').strip())
        except subprocess.TimeoutExpired:
            pass
        self.log_debug("Started background tcpdump on interface '%s'"
                       % self.args['iface'])
        return True

    def trigger_action(self):
        self.log_debug("Stopping tcpdump")
        try:
            self.proc.terminate()
            _files = glob.glob(self.loc + '*')
            self.add_report_file(_files)
            self.devnull.close()
        except Exception as err:
            self.log_error("Could not stop tcpdump: %s" % err)
        return True

    def cleanup(self):
        try:
            self.proc.terminate()
            self.devnull.close()
        except Exception:
            pass

    def action_info(self):
        return "A packet capture from interface %s using filter %s" % (
            self.get_option('iface'),
            self.get_option('filter')
        )
