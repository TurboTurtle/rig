# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information

from rigging.monitors import BaseMonitor
from enum import Enum, IntFlag
from socket import socket, AF_PACKET, SOCK_RAW, \
                   IPPROTO_TCP, IPPROTO_UDP, IPPROTO_ICMP, \
                   htons, inet_ntoa, if_nametoindex
from struct import unpack

import re

ETH_P_ALL = 3
ETH_IPV4 = 0x0800
ETH_ARP = 0x0806
ETH_VLAN = 0x8100
ETH_IPV6 = 0x86dd

SOL_PACKET = 263
SO_ATTACH_FILTER = 26


class PayloadMatch:
    def __init__(self, regex):
        self._regex = regex
        self._re = re.compile(regex.encode())

    def __eq__(self, other):
        if not isinstance(other, bytes):
            return False

        if other == b'':
            return False

        return self._re.search(other)

    def __repr__(self):
        return self._regex


class TCP_FLAGS(IntFlag):
    FIN = 1
    SYN = 2
    RST = 4
    PSH = 8
    ACK = 16
    URG = 32
    ECN = 64
    CWR = 128


class ICMP_TYPES(Enum):
    ECHO_REPLY = 0
    DESTINATION_UNREACHABLE = 3
    REDIRECT = 5
    ECHO = 8
    ROUTER_ADVERTISEMENT = 9
    ROUTER_SELECTION = 10
    TIME_EXCEEDED = 11
    PARAMETER_PROBLEM = 12
    TIMESTAMP = 13
    TIMESTAMP_REPLY = 14
    INFORMATION_REQUEST = 15
    INFORMATION_REPLY = 16
    ADDRESS_MASK_REQUEST = 17
    ADDRESS_MASK_REPLY = 18
    TRACEROUTE = 30


class ICMP_DEST_UNREACH(Enum):
    NETWORK_UNREACHABLE = 0
    HOST_UNREACHABLE = 1
    PROTOCOL_UNREACHABLE = 2
    PORT_UNREACHABLE = 3
    FRAGMENT_NEEDED = 4
    SOURCE_ROUTE_FAILED = 5
    DEST_NET_UNKNOWN = 6
    DEST_HOST_UNKNOWN = 7
    SOURCE_HOST_ISOLATED = 8
    DEST_NET_PROHIBITED = 9
    DEST_HOST_PROHIBITED = 10
    DEST_NET_UNREACH_TOS = 11
    DEST_HOST_UNREACH_TOS = 12
    ADMIN_PROHIBITED = 13
    HOST_PRECEDENCE = 14
    PRECEDENCE_CUTOFF = 15


class ICMP_REDIRECT(Enum):
    NETWORK = 0
    HOST = 1
    TOS_NETWORK = 2
    TOS_HOST = 3


ICMP_TYPE_CODE = {
    0: lambda x: "",
    3: ICMP_DEST_UNREACH,
    5: ICMP_REDIRECT,
    8: lambda x: "",
}


class Packet(BaseMonitor):
    """Monitor network traffic.

    Detects network traffic matching a defined IP address, port,
    set of TCP flags or an ICMP code.
    """

    monitor_name = 'packet'
    description = ('Trigger when network interface receives traffic matching '
                   'a specification')

    def configure(self, interface, srcmac=None, dstmac=None, srcip=None,
                  dstip=None, srcport=None, dstport=None, tcpflags=None,
                  icmptype=None, payload=None, trigger_any=False):
        """
        :param interface: The network interface to listen on
        :param srcmac: Match this source mac address
        :param dstmac: Match this destination mac address
        :param srcip: Match this source IP address
        :param dstip: Match this destination IP address
        :param srcport: Match this source port
        :param dstport: Match this destination port
        :param tcpflags: Match these TCP protocol flags
        :param icmptype: Match this ICMP type
        :param payload: Match a clear text payload using a regex
        :param trigger_any: Trigger this monitor when any provided filter
                            matches, otherwise require all filters to match
        """

        self._match_ifname = None
        self.trigger_any = trigger_any

        self._must_match = {
            'srcmac': srcmac,
            'dstmac': dstmac,
            'srcip': srcip,
            'dstip': dstip,
            'srcport': srcport,
            'dstport': dstport,
        }

        # Build a TCP_FLAGS instance based on the provided flags
        if tcpflags:
            if isinstance(tcpflags, str):
                tcpflags = [tcpflags]
            elif not isinstance(tcpflags, list):
                raise Exception(
                    "'tcpflags' must be provided as string or list"
                )
            tcpflags_int = sum([
                getattr(TCP_FLAGS, x.upper()) for x in tcpflags
            ])

            self._must_match['tcpflags'] = TCP_FLAGS(tcpflags_int)

        # Get ICMP_TYPES instance from the provided icmp type name
        icmptype_str = icmptype
        if icmptype_str:
            self._must_match['icmptype'] = \
                getattr(
                    ICMP_TYPES, icmptype_str.upper().replace('-', '_'),
                    None
                )

        # Fail if the network interface doesn't exist on the system.
        if interface:
            try:
                if_nametoindex(interface)
                self._match_ifname = interface
            except OSError:
                raise Exception(f"Interface '{interface}' does not exist")

        # Build a comparable object if a payload regex is provided
        if payload:
            self._must_match['payload'] = PayloadMatch(payload)

        # Remove all attributes that have no value
        self._must_match = {k: v for k, v in self._must_match.items() if v}

        # No filters provided
        if not self._must_match:
            raise Exception("Must specify at least one filter")

        self.add_monitor_thread(self._read_from_socket, ())

    @staticmethod
    def _strmac(mac):
        return ":".join([f"{i:02x}" for i in mac])

    def _pkt_matches(self, pkt_attrs):
        matching_keys = {}
        for k, v in self._must_match.items():
            if k not in pkt_attrs:
                continue
            # Match tcpflags if any of the provided flags are set
            if isinstance(v, TCP_FLAGS) and v & pkt_attrs[k] != 0:
                matching_keys[k] = v
            # For all other keys we just compare them
            elif pkt_attrs[k] == v:
                matching_keys[k] = v

        if self.trigger_any:
            if len(matching_keys) > 0:
                return matching_keys
            else:
                return None

        else:
            # If --any wasn't set, then all provided filters must match.
            if len(matching_keys) == len(self._must_match):
                return matching_keys
            else:
                return None

    def _read_from_socket(self):
        sock = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL))

        while True:
            eth, addrinfo = sock.recvfrom(65535)

            pkt_str = ""
            pkt_attrs = {}
            payload = None

            iface, ethtype_info, _, _, srcmac_info = addrinfo

            if self._match_ifname and self._match_ifname != iface:
                continue

            if ethtype_info != ETH_IPV4:  # Only IPv4
                continue

            # L2
            eth_src = self._strmac(eth[:6])
            eth_dst = self._strmac(eth[6:12])
            # eth_type = struct.unpack("!H", eth[12:14])[0]

            pkt_attrs["srcmac"] = eth_src
            pkt_attrs["dstmac"] = eth_dst

            # L3
            ip = eth[14:]

            ip_ver, ip_hdrlen = divmod(ip[0], 16)
            ip_hdrlen *= 4  # 32bit incrs

            if ip_ver != 4:
                continue

            ip_pktlen, ip_id, ip_flags, ip_ttl, ip_proto, ip_cksum = \
                unpack("!HHHBBH", ip[2:12])

            ip_src = inet_ntoa(ip[12:16])
            ip_dst = inet_ntoa(ip[16:20])

            pkt_attrs['srcip'] = ip_src
            pkt_attrs['dstip'] = ip_dst

            # L4
            if ip_proto == IPPROTO_TCP:
                tcp = ip[ip_hdrlen:]
                tcp_src, tcp_dst, tcp_seq, tcp_ack, tcp_hdrlen, tcp_flags, \
                    tcp_win, tcp_chksum = unpack("!HHLLBBHH", tcp[0:18])

                tcp_hdrlen = (tcp_hdrlen >> 4) * 4  # 32bit incrs
                tcp_flags = TCP_FLAGS(tcp_flags)

                pkt_attrs['srcport'] = tcp_src
                pkt_attrs['dstport'] = tcp_dst

                pkt_attrs['tcpflags'] = tcp_flags

                payload = tcp[tcp_hdrlen:]

                pkt_str = (
                    f"{ip_src:>15s}:{tcp_src:<5d} ({eth_src}) -> "
                    f"{ip_dst:>15s}:{tcp_dst:<5d} ({eth_dst}) "
                    f"{str(tcp_flags).replace('TCP_FLAGS.', '')} {payload}"
                )

            elif ip_proto == IPPROTO_UDP:
                udp = ip[ip_hdrlen:]
                udp_src, udp_dst, udp_len, udp_cksum = unpack("!HHHH", udp[:8])

                pkt_attrs['srcport'] = udp_src
                pkt_attrs['dstport'] = udp_dst

                payload = udp[8:]  # UDP header is fixed 8 bytes

                pkt_str = (
                    f"{ip_src:>15s}:{udp_src:<5d} ({eth_src}) -> "
                    f"{ip_dst:>15s}:{udp_dst:<5d} ({eth_dst}) {payload}"
                )

            elif ip_proto == IPPROTO_ICMP:
                icmp = ip[ip_hdrlen:]
                icmp_type, icmp_code, icmp_cksum, icmp_id, icmp_seq = \
                    unpack("!BBHHH", icmp[:8])

                try:
                    icmp_type = ICMP_TYPES(icmp_type)
                    # If parsing the type raises an excp, then just ignore it.
                    pkt_attrs['icmptype'] = icmp_type
                except ValueError:
                    pass

                pkt_str = (
                    f"{ip_src:>15s} ({eth_src}) -> "
                    f"{ip_dst:>15s} ({eth_dst}) "
                    f"ICMP {icmp_type.name}"
                )
                self.logger.debug(pkt_str)

            pkt_attrs['payload'] = payload

            matching_keys = self._pkt_matches(pkt_attrs)
            if matching_keys:
                match_str = " and ".join([
                    f"{k} {v}" for k, v in matching_keys.items()
                ])
                self.logger.info(
                    f"Packet matching {match_str} found: {pkt_str}"
                )
                return True

    @property
    def monitoring(self):
        _info = {
            'interface': self._match_ifname
        }
        _info.update({k: str(v) for k, v in self._must_match.items()})
        return _info
