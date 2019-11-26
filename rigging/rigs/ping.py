# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.

import re
import shlex

from rigging.rigs import BaseRig
from rigging.exceptions import CannotConfigureRigError
from subprocess import Popen, PIPE, TimeoutExpired

PING_BIN = '/usr/bin/ping'


class Ping(BaseRig):
    """
    A basic connectivity testing rig. While running, this rig will send a ping
    at a defined interval and record the results. After the ping completes,
    the recorded results are compared to a defined trigger condition (e.g.
    number of packets lost).

    Resource options:
        :opt host:              The IP or hostname to ping
        :opt ping-timeout:      Timeout for individual pings
        :opt ping-time-ms       Max time for ping response in ms
        :opt ping-interval:     Time to wait between pings
        :opt lost-count:        Number of packets to lose to trigger rig
    """

    parser_description = 'Send pings at a regular interval'

    def set_parser_options(self, subparser):
        subparser.add_argument('--host',
                               help='IP address or hostname to ping')
        subparser.add_argument('--ping-timeout', default=1, type=float,
                               help='Timeout in seconds for response')
        subparser.add_argument('--lost-count', default=1, type=int,
                               help='Packet loss count threshold for trigger')
        subparser.add_argument('--ping-ms-max', default=None, type=int,
                               help='Max RTT threshold for pings')
        subparser.add_argument('--ping-ms-count', default=5, type=int,
                               help='Threshold for packets over max RTT')
        return subparser

    @property
    def watching(self):
        return "Pinging %s" % self.get_option('host')

    @property
    def trigger(self):
        msg = "%s lost/dropped packets" % self.get_option('lost_count')
        if self.get_option('ping_ms_max'):
            msg += (" or %s packets exceeding RTT of %s ms"
                    % (self.get_option('ping_ms_count'),
                       self.get_option('ping_ms_max'))
                    )
        return msg

    def reset_counters(self):
        self.lost_packets = 0
        self.packet_ms_count = 0

    def _run_ping(self):
        try:
            proc = Popen(shlex.split(self.ping_cmd), stderr=PIPE, stdout=PIPE)
            stdout, stderr = proc.communicate(
                                timeout=self.get_option('ping_timeout'))
            rc = proc.returncode
        except TimeoutExpired:
            # need to set this manually
            self.log_info("Registered packet timeout to %s"
                          % self.get_option('host'))
            self.lost_packets += 1
            # a timed-out packet is by nature exceeding the RTT
            self.packet_ms_count += 1
            if self._check_loss():
                return False
            else:
                return True
        if rc == 0 or rc == 1:
            if self.parse_ping_failure(stdout):
                return False
            return True
        elif rc == 2:
            msg = "Host %s did not resolve" % self.get_option('host')
        else:
            msg = "Error running ping. Return code %s" % rc
        raise Exception(msg)

    def parse_ping_failure(self, output):
        status = output.splitlines()[-2].decode('utf-8', 'ignore')
        recv = int(re.match(r'.*, (\d+) received, .*', status).group(1))
        if recv == 0:
            self.log_debug("Registered lost packet to %s"
                           % self.get_option('host'))
            self.lost_packets += 1
            if self._check_loss():
                self.log_info("Number of lost packets is %s, triggering "
                              "rig" % self.lost_packets)
                return True
        ms_status = output.splitlines()[-1].decode('utf-8', 'ignore')
        if self.get_option('ping_ms_max') and ms_status:
            # we have to match on the summary line at the end, as it is more
            # reliable for standardized output than the individual ping result
            # lines returned during ping execution
            ms_reg = r'(.* =) ((\d+.\d+)/(\d+.\d+)/(\d+.\d+)/(.*) ms)'
            ms = re.match(ms_reg, ms_status)
            if ms:
                ms = int(float(ms.group(5)))
            if ms >= int(self.get_option('ping_ms_max')):
                self.log_debug("Registered packet with RTT of %s (threshold: "
                               "%s)" % (ms, self.get_option('ping_ms_max')))
                self.packet_ms_count += 1
                if self.packet_ms_count >= self.get_option('ping_ms_count'):
                    self.log_info("Number of packets exceeding RTT threshold "
                                  "exceeded, triggering rig.")
                    return True
        return False

    def _test_initial_ping(self):
        """
        Perform a sanity check ping before launching the rig.
        """
        self.log_debug('Sending a sanity check ping before initialization')
        try:
            self._run_ping()
            if self.lost_packets == 0:
                self.log_debug('Sanity check passed. Ping successful')
                return True
            else:
                raise CannotConfigureRigError(
                    "Initial ping response not received from %s"
                    % self.get_option('host')
                )
        except CannotConfigureRigError:
            raise
        except Exception as err:
            raise CannotConfigureRigError(err)

    def setup(self):
        if not self.get_option('host'):
            raise CannotConfigureRigError('Target host must be provided')
        self.lost_packets = 0
        self.packet_ms_count = 0
        if (self.get_option('ping_ms_max') and self.get_option('ping_timeout')
                < (self.get_option('ping_ms_max') / 1000)):
            _new_timeout = (self.get_option('ping_timeout') +
                            (self.get_option('ping_ms_max') / 1000))
            self.log_info("Ping timeout lower than configured RTT threshold. "
                          "Increasing ping timeout to %s seconds."
                          % _new_timeout)
            self.set_option('ping_timeout', _new_timeout)
        self.ping_cmd = "%s -c 1 %s" % (PING_BIN, self.get_option('host'))
        self._test_initial_ping()
        self.add_watcher_thread(target=self.ping_host, args=None)

    def ping_host(self, hldr):
        """
        Actually ping the host

        Positional arguments:
            hldr:       A holder to account for start_watcher_threads() always
                        passing a positional arg. Unused.
        """
        while True:
            try:
                resp = self._run_ping()
                if not resp:
                    return True
                self.wait_loop()
            except Exception as err:
                self.log_error(err)
                # don't inadvertantly trigger rig on an error
                return False

    def _check_loss(self):
        return self.lost_packets >= self.get_option('lost_count')
