# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import fnmatch

from rigging.actions import BaseAction


class SosAction(BaseAction):
    """
    This action will call `sos` when a rig is triggered. sos is a diagnostic
    data collection tool for Linux and is widely used by commercial support
    organizations.

    The most popular functionality of sos is to generate a report for a single
    system; an 'sos report'. The tool also allows for collection of reports
    from multiple systems at once using the `collect` subcommand.

    This action provides support for both generating a local report, and the
    collection of reports.

    Note that `sos collect` supports a --password option that would prompt
    users for an SSH password if SSH keys are not deployed. This option is not
    supported by rig - `sos collect` executions by rig _require_ the use of
    SSH keys or alternative transports supported by the sos utility.
    """

    action_name = 'sos'
    description = 'Generate an sos report or collect archive'
    required_binaries = ('sos', )

    def configure(self, report=None, collect=None, initial_archive=False,
                  timeout=300):
        """
        :param report: If defined, collect an sos report locally
        :param collect: If defined, start an `sos collect` collection
        :param initial_archive: Collect an sos archive before the rig starts
        :param timeout: Number of seconds to allow sos commands to execute
        """

        if report and collect:
            raise Exception(
                "Both 'report' and 'collect' defined. Only one is supported at"
                " a time."
            )

        if report is None and collect is None:
            raise Exception(
                "Neither 'report' nor 'collect' defined, or configuration is "
                "empty. Provide configuration or set to 'enabled'."
            )

        self.initial_archive = initial_archive
        try:
            self.timeout = int(timeout)
        except Exception:
            raise Exception(f"'timeout' must be provided as int in seconds, "
                            f"not '{timeout}'")

        if report:
            config = self._validate_config(report, 'report')
        else:
            config = self._validate_config(collect, 'collect')

        self.sos_cmd = self._compile_sos_command(config)

    def trigger(self):
        self.logger.info(f"Collecting sos archive as '{self.sos_cmd}'")
        try:
            if self.execute_sos_cmd():
                self.logger.info('sos archive successfully collected')
                return True
            else:
                self.logger.error('sos archive failed to be collected')
        except Exception as err:
            self.logger.error(f"Error during triggered sos collection: {err}")

        return False

    def execute_sos_cmd(self, label=None):
        """
        Actually perform the sos command execution, then search for the output
        path and add that to the rig's archive.

        :param label: Optionally, add a label to an archive run. If requested,
                      the initial sos archive will always be labelled as such
        """
        _label = ''
        if label:
            _label = f" --label {label}"
        try:
            ret = self.exec_cmd(self.sos_cmd + _label,
                                timeout=self.timeout)
        except Exception as err:
            raise Exception(f"Error during sos execution: {err}")

        path = ''
        if ret['status'] == 0:
            for line in ret['stdout'].splitlines():
                if fnmatch.fnmatch(line, '*sos*-*.tar.*'):
                    path = line.strip()
                    break
            if not path:
                self.logger.error(
                    'Could not determine final path of sos archive'
                )
                return False
            self.add_archive_file(path)
            return True
        self.logger.error(
            f"Error running sos command, output was: "
            f"{ret['stderr'] or ' '.join(ret['stdout'].splitlines()[-3:])}"
        )
        return False

    def pre_action(self):
        """
        If this action is configured to capture an initial archive, do so
        here
        """
        if self.initial_archive:
            self.logger.info(
                'Generating initial sos archive, this may take some time'
            )
            try:
                if self.execute_sos_cmd(label='initial'):
                    self.logger.info(
                        'Initial sos archive successfully collected'
                    )
                else:
                    raise Exception(
                        'Initial sos archive failed to be collected'
                    )
            except Exception as err:
                raise Exception(
                    f"Initial sos collection encountered an error: {err}"
                )

    def _compile_sos_command(self, config):
        """
        Create the sos command to be executed to generate the report or
        collect archive

        :param config: A dict of all supported options that are set in the
        rigfile
        :return: A string of the command being executed
        """
        _cmd = f"sos {config.pop('command')} --batch"
        if 'clean' in config:
            # allow extra time for obfuscation
            self.timeout += 180

        for k, v in config.items():
            _val = v
            if isinstance(_val, list):
                _val = ','.join(e for e in _val)
            elif isinstance(_val, bool):
                if _val is True:
                    _val = ''
                else:
                    continue
            elif isinstance(_val, dict):
                _val = ','.join(f"{k}={v}" for k, v in _val.items())
            _cmd += f" --{k.replace('_', '-')} {_val}"
        _cmd = _cmd.strip()
        self.logger.debug(f"sos command set to '{_cmd}'")
        return _cmd

    def _validate_config(self, config, cmd):
        """
        Validates the configuration set for the command specified in the
        rigfile.

        :param config: Configuration set for report in rigfile
        :param cmd: The command that sos will run - 'report' or 'collect'
        """
        if config is None:
            return config

        if config in [True, 'true', 'enabled', 'on']:
            _cmd_config = {}
        else:
            _cmd_config = config

        if not isinstance(_cmd_config, dict):
            raise Exception(
                f"Invalid configuration for '{cmd}': '{config}'. "
                f"Provide configuration options, or set '{cmd}' to enabled"
            )

        _report_opts = {
            'case_id': '',
            'clean': False,
            'only_plugins': [],
            'skip_plugins': [],
            'enable_plugins': [],
            'plugin_option': {},
            'log_size': 25,
            'skip_commands': [],
            'skip_files': [],
            'verify': False
        }

        _collect_opts = {
            'primary': '',
            'cluster_type': '',
            'cluster_option': {},
            'nodes': [],
            'no_local': False,
            'timeout': self.timeout,
            'ssh_user': '',
            'transport': '',
        }

        _config = {}

        _compare_opts = [_report_opts]
        if cmd == 'collect':
            if 'timeout' not in _config:
                _config['timeout'] = self.timeout
            _compare_opts.append(_collect_opts)

        for _cmd in _compare_opts:
            for opt in _cmd:
                if opt in _cmd_config:
                    if not isinstance(_cmd_config[opt], type(_cmd[opt])):
                        raise Exception(
                            f"'{opt}' must be given as {_cmd[opt].__class__}"
                        )
                    _config[opt] = _cmd_config.pop(opt)

        # check to see if there are any lingering options specified
        if _cmd_config:
            raise Exception(
                f"'{cmd}' does not support options(s): "
                f"{', '.join(k for k in _cmd_config.keys())}"
            )

        _config['command'] = cmd
        return _config

    @property
    def produces(self):
        return "an sos report tarball for this system"
