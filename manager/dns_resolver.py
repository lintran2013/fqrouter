import socket
import logging

import dpkt

on_blacklist_ip_resolved = None

LOGGER = logging.getLogger('fqrouter.%s' % __name__)
domains = {} # ip => domain

# source http://zh.wikipedia.org/wiki/%E5%9F%9F%E5%90%8D%E6%9C%8D%E5%8A%A1%E5%99%A8%E7%BC%93%E5%AD%98%E6%B1%A1%E6%9F%93
WRONG_ANSWERS = {
    '4.36.66.178',
    '8.7.198.45',
    '37.61.54.158',
    '46.82.174.68',
    '59.24.3.173',
    '64.33.88.161',
    '64.33.99.47',
    '64.66.163.251',
    '65.104.202.252',
    '65.160.219.113',
    '66.45.252.237',
    '72.14.205.99',
    '72.14.205.104',
    '78.16.49.15',
    '93.46.8.89',
    '128.121.126.139',
    '159.106.121.75',
    '169.132.13.103',
    '192.67.198.6',
    '202.106.1.2',
    '202.181.7.85',
    '203.161.230.171',
    '203.98.7.65',
    '207.12.88.98',
    '208.56.31.43',
    '209.36.73.33',
    '209.145.54.50',
    '209.220.30.174',
    '211.94.66.147',
    '213.169.251.35',
    '216.221.188.182',
    '216.234.179.13',
    '243.185.187.39'
}

GOOGLE_PLUS_WRONG_ANSWERS = {
    '74.125.127.102',
    '74.125.155.102',
    '74.125.39.113',
    '74.125.39.102',
    '209.85.229.138'
}


def resolve(domain_name, record_type=dpkt.dns.DNS_A):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
    sock.settimeout(3)
    request = dpkt.dns.DNS(qd=[dpkt.dns.DNS.Q(name=domain_name, type=record_type)])
    sock.sendto(str(request), ('8.8.8.8', 53))
    for i in range(3):
        data, addr = sock.recvfrom(1024)
        response = dpkt.dns.DNS(data)
        if contains_wrong_answer(response):
            continue
        if response.an:
            if dpkt.dns.DNS_A == record_type:
                return socket.inet_ntoa(response.an[0]['rdata'])
            return response.an[0]
        else:
            raise Exception('record not found: %s' % domain_name)


def contains_wrong_answer(dns_packet):
    questions = [question for question in dns_packet.qd if question.type == dpkt.dns.DNS_A]
    dns_packet.domain = questions[0].name if questions else None
    if dpkt.dns.DNS_A not in [question.type for question in dns_packet.qd]:
        return False # not answer to A question, might be PTR
    for answer in dns_packet.an:
        if dpkt.dns.DNS_A == answer.type:
            resolved_ip = socket.inet_ntoa(answer['rdata'])
            if resolved_ip in WRONG_ANSWERS:
                return True
            if 'plus.google.com' in dns_packet.domain and resolved_ip in GOOGLE_PLUS_WRONG_ANSWERS:
                return True
            else:
                domains[resolved_ip] = dns_packet.domain
                LOGGER.info('[%s] resolved %s => %s' % (dns_packet.id, dns_packet.domain, resolved_ip))
                if 'twitter.com' in dns_packet.domain:
                    if on_blacklist_ip_resolved:
                        on_blacklist_ip_resolved(resolved_ip)
                return False # if the blacklist is incomplete, we will think it is right answer
    return True # to find empty answer


def get_domain(ip):
    return domains.get(ip)