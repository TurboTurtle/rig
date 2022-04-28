from rigging.rigs import BaseRig
from rigging.exceptions import CannotConfigureRigError
from enum import Enum, IntFlag
from socket import socket, AF_PACKET, SOCK_RAW, \
                   IPPROTO_TCP, IPPROTO_UDP, IPPROTO_ICMP, \
                   htons, inet_ntoa
from struct import unpack

ETH_P_ALL = 3
ETH_IPV4 = 0x800
ETH_IPV6 = 0x86dd

SOL_PACKET = 263
SO_ATTACH_FILTER = 26

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
    ROUTER_ADVERTISMENT = 9
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


class Network(BaseRig):
    """Monitor network traffic.

    Detects network traffic matching a defined IP address, port, 
    set of TCP flags or an ICMP code.
    """

    parser_description = 'Monitor network traffic.'

    def set_parser_options(self, parser):
        parser.add_argument('--srcip', type=str,
                            help='Match source IP address')

        parser.add_argument('--dstip', type=str,
                            help='Match destination IP address')

        parser.add_argument('--srcport', type=int,
                            help='Match source port/protocol')

        parser.add_argument('--dstport', type=int,
                            help='Match destination port/protocol')

        parser.add_argument('--tcpflags', type=str,
                            help='Match TCP flags')

        parser.add_argument('--icmptype', type=str,
                            help='Match ICMP code')

        parser.add_argument('--any', action="store_true",
                            help='Any parameter triggers (default: all params)')

    @property
    def watching(self):
        return "Network traffic"

    @property
    def trigger(self):
        triggers = []
        op_str = " or " if self.get_option('any') else " and "
        for x, v in self._must_match.items():
            triggers.append(f'{x} is {v}')

        return op_str.join(triggers)

    def setup(self):

        self._must_match = {
            'srcip': self.get_option('srcip'),
            'dstip': self.get_option('dstip'),
            'srcport': self.get_option('srcport'),
            'dstport': self.get_option('dstport'),
            #'icmptype': self.get_option('icmpcode'),
        }

        tcpflags_str = self.get_option('tcpflags')
        if tcpflags_str:
            self._must_match['tcpflags'] = \
                sum([ getattr(TCP_FLAGS, x.upper()) for x in tcpflags_str.split('|') ])

        icmptype_str = self.get_option('icmptype')
        if icmptype_str:
            self._must_match['icmptype'] = \
                getattr(ICMP_TYPES, icmptype_str.upper().replace('-', '_'), None)

        self._must_match = { k: v for k, v in self._must_match.items() if v }

        self.add_watcher_thread(target=self._read_from_socket, args=())


    @staticmethod
    def _strmac(mac):
        return ":".join([ f"{i:02x}" for i in mac])

    def _pkt_matches(self, pkt_attrs):

        self.log_debug(f"PKT {pkt_attrs} -- MUST {self._must_match}")
        matching_keys = {}

        for k, v in self._must_match.items():
            if k in pkt_attrs and pkt_attrs[k] == v:
                matching_keys[k] = v

        if self.get_option("any"):
            if len(matching_keys) > 0:
                return matching_keys
            else:
                return None

        else:
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

            iface, ethtype_info, _, _, srcmac_info = addrinfo

            # L2

            eth_src = self._strmac(eth[:6])
            eth_dst = self._strmac(eth[6:12])
            #eth_type = struct.unpack("!H", eth[12:14])[0]

            if ethtype_info != ETH_IPV4: # Only IPv4
                continue

            # L3

            ip = eth[14:]

            ip_ver, ip_hdrlen = divmod(ip[0], 16)
            ip_hdrlen *= 4 # 32bit incrs

            if ip_ver != 4:
                continue

            ip_diffserv = ip[1]

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

                tcp_hdrlen = (tcp_hdrlen >> 4) * 4 # 32bit incrs
                tcp_flags = TCP_FLAGS(tcp_flags)

                pkt_attrs['srcport'] = tcp_src
                pkt_attrs['dstport'] = tcp_dst

                pkt_attrs['tcpflags'] = tcp_flags

                pkt_str = (f"{ip_src:>15s}:{tcp_src:<5d} ({eth_src}) -> "
                             f"{ip_dst:>15s}:{tcp_dst:<5d} ({eth_dst}) "
                             f"{str(tcp_flags).replace('TCP_FLAGS.', '')}")

            elif ip_proto == IPPROTO_UDP:
                udp = ip[ip_hdrlen:]
                udp_src, udp_dst, udp_hdrlen, udp_cksum = unpack("!HHHH", udp[:8])

                pkt_attrs['srcport'] = udp_src
                pkt_attrs['dstport'] = udp_dst

                pkt_str = (f"{ip_src:>15s}:{udp_src:<5d} ({eth_src}) -> "
                             f"{ip_dst:>15s}:{udp_dst:<5d} ({eth_dst}) ")

            elif ip_proto == IPPROTO_ICMP:
                icmp = ip[ip_hdrlen:]
                icmp_type, icmp_code, icmp_cksum, icmp_id, icmp_seq = \
                        unpack("!BBHHH", icmp[:8])

                try:
                    icmp_code = ICMP_TYPE_CODE[icmp_type](icmp_code)
                except:
                    pass

                icmp_type = ICMP_TYPES(icmp_type)

                pkt_attrs['icmptype'] = icmp_type

                pkt_str = (f"{ip_src:>15s}:{tcp_src:<5d} ({eth_src}) -> "
                             f"{ip_dst:>15s}:{tcp_dst:<5d} ({eth_dst}) "
                             f"ICMP {icmp_type.name}")


            self.log_debug(pkt_str)
            
            matching_keys = self._pkt_matches(pkt_attrs)
            if matching_keys:
                match_str = " and ".join([ f"{k} {v}" for k, v in matching_keys.items() ])
                self.log_info(f"Packet matching {match_str} found: {pkt_str}")
                return True


