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
    DEST_UNREACH = 3
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
    NET_UNREACH = 0
    HOST_UNREACH = 1
    PROTOCOL_UNREACH = 2
    PORT_UNREACH = 3
    FRAG_NEEDED = 4
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

        parser.add_argument('--srcport', type=str,
                            help='Match source port/protocol')

        parser.add_argument('--dstport', type=str,
                            help='Match destination port/protocol')

        parser.add_argument('--tcpflags', type=str,
                            help='Match TCP flags')

        parser.add_argument('--icmpcode', type=str,
                            help='Match ICMP code')

    @property
    def watching(self):
        return "Network traffic"

    @property
    def trigger(self):
        triggers = []
        for x in [ "srcip", "dstip", "srcport", "dstport", "tcpflags",
                   "icmpcode" ]:
            val = self.get_option(x)
            if val:
                triggers.append(f'{x} is {val}')

        return " and ".join(triggers)

    def setup(self):
        srcip = self.get_option('srcip')
        dstip = self.get_option('dstip')
        srcport = self.get_option('srcport')
        dstport = self.get_option('dstport')
        tcpflags = self.get_option('tcpflags')
        icmpcode = self.get_option('icmpcode')

        self.add_watcher_thread(target=self._read_from_socket,
                                args=(srcip, dstip))


    @staticmethod
    def _strmac(mac):
        return ":".join([ f"{i:02x}" for i in mac])

    def _read_from_socket(self, srcip, dstip):
        sock = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL))

        while True:
            eth, addrinfo = sock.recvfrom(65535)

            pkt_str = ""

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

            # L4

            if ip_proto == IPPROTO_TCP:
                tcp = ip[ip_hdrlen:]
                tcp_src, tcp_dst, tcp_seq, tcp_ack, tcp_hdrlen, tcp_flags, \
                        tcp_win, tcp_chksum = unpack("!HHLLBBHH", tcp[0:18])

                tcp_hdrlen = (tcp_hdrlen >> 4) * 4 # 32bit incrs
                tcp_flags = TCP_FLAGS(tcp_flags)

                pkt_str = (f"{ip_src:>15s}:{tcp_src:<5d} ({eth_src}) -> "
                             f"{ip_dst:>15s}:{tcp_dst:<5d} ({eth_dst}) "
                             f"{str(tcp_flags).replace('TCP_FLAGS.', '')}")

            elif ip_proto == IPPROTO_UDP:
                udp = ip[ip_hdrlen:]
                udp_src, udp_dst, udp_hdrlen, udp_cksum = unpack("!HHHH", udp[:8])

            elif ip_proto == IPPROTO_ICMP:
                icmp = ip[ip_hdrlen:]
                icmp_type, icmp_code, icmp_cksum, icmp_id, icmp_seq = \
                        unpack("!BBHHH", icmp[:8])

                try:
                    icmp_code = ICMP_TYPE_CODE[icmp_type](icmp_code)
                except:
                    pass

                icmp_type = ICMP_TYPES(icmp_type)


            if srcip and ip_src == srcip:
                self.log_info(f"Packet matching srcip {srcip} found: {pkt_str}")
                return True

            if dstip and ip_dst == dstip:
                self.log_info(f"Packet matching dstip {dstip} found: {pkt_str}")
                return True
