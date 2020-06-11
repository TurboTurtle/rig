# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import fnmatch

from pipes import quote
from rigging.actions import BaseAction
from rigging.exceptions import CannotConfigureRigError

SOS_BIN = '/usr/sbin/sosreport --batch'


class SoSReport(BaseAction):

    action_name = 'sosreport'
    enabling_opt = 'sosreport'
    enabling_opt_desc = 'Generate a sosreport when triggered'
    priority = 100
    required_binaries = ('sosreport',)
    sos_opts = ('only_plugins', 'skip_plugins', 'enable_plugins',
                'plugin_option')

    def pre_action(self):
        """
        Performs basic sanity checks against any passed --sos-opts and will
        abort rig creation if suspect items like shell code are found
        """
        _filt = ['<', '>', '|', '&', ';']
        for _opt in self.sos_opts:
            _cmd = self.get_option(_opt)
            if not _cmd:
                continue
            if any(f in _cmd for f in _filt):
                raise CannotConfigureRigError(
                    "Potential shell-code found in option %s. Aborting rig "
                    "configuration." % _opt
                )
        return True

    def trigger_action(self):
        try:
            cmd = "%s --tmp-dir=%s" % (SOS_BIN, self.tmp_dir)
            for _opt in self.sos_opts:
                if self.get_option(_opt):
                    cmd += " --%s %s" % (
                        _opt.replace('_', '-'),
                        quote(self.get_option(_opt))
                    )
            self.log_info("Collecting sosreport as %s" % cmd)
            ret = self.exec_cmd(cmd)
        except Exception as err:
            self.log_debug(err)
            return False
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

    @classmethod
    def add_action_options(cls, parser):
        parser.add_argument('--sosreport', action='store_true',
                            help=cls.enabling_opt_desc)
        parser.add_argument('-e', '--enable-plugins', type=str,
                            help="Explicitly enable these sosreport plugins")
        parser.add_argument('-k', '--plugin-option', type=str,
                            help="Specify sosreport plugin options")
        parser.add_argument('-n', '--skip-plugins', type=str,
                            help="Skip these sosreport plugins")
        parser.add_argument('-o', '--only-plugins', type=str,
                            help="Only enable these sosreport plugins")
        return parser

    def action_info(self):
        return "An sosreport from the host in %s" % self.tmp_dir
