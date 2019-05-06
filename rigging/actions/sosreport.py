# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import fnmatch

from rigging.actions import BaseAction

SOS_BIN = '/usr/sbin/sosreport --batch'


class SoSReport(BaseAction):

    action_name = 'sosreport'
    enabling_opt = 'sosreport'
    enabling_opt_desc = 'Generate a sosreport when triggered'
    priority = 100
    required_binaries = ('sosreport',)

    def trigger_action(self):
        try:
            cmd = "%s --tmp-dir=%s" % (SOS_BIN, self.tmp_dir)
            if self.args['sos_opts']:
                cmd += " %s" % self.args['sos_opts']
            ret = self.exec_cmd(cmd)
        except Exception as err:
            self.log_debug(err)
        if ret['status'] == 0:
            path = 'unknown'
            for line in ret['stdout'].splitlines():
                if fnmatch.fnmatch(line, '*sosreport-*tar*'):
                    path = line.strip()
            if path == 'unknown':
                self.log_error('Could not determine path for sosreport')
                self.log_debug(ret['stdout'])
                return False
            self.add_report_file(path)
        else:
            self.log_error("Error during sosreport collection: %s" %
                           (ret['stderr'] or ret['stdout']))
        return True

    def add_action_options(self, parser):
        parser.add_argument('--sosreport', action='store_true',
                            help=self.enabling_opt_desc)
        parser.add_argument('--sos-opts',
                            help='commandline options for sosreport')
        return parser
