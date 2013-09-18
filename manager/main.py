import gevent.monkey

gevent.monkey.patch_all(ssl=False, thread=False)

import logging
import logging.handlers
import sys
import os
import config
import traceback
import httplib
import fqsocks.httpd
import fqsocks.fqsocks
import wifi
import shell
import iptables
import shutdown_hook
import shlex
import subprocess
import functools
import comp_scrambler
import comp_shortcut


__import__('free_internet')
__import__('wifi_repeater')


FQROUTER_VERSION = 'UNKNOWN'
LOGGER = logging.getLogger('fqrouter.%s' % __name__)
LOG_DIR = '/data/data/fq.router2/log'
MANAGER_LOG_FILE = os.path.join(LOG_DIR, 'manager.log')
WIFI_LOG_FILE = os.path.join(LOG_DIR, 'wifi.log')
FQDNS_LOG_FILE = os.path.join(LOG_DIR, 'fqdns.log')
FQLAN_LOG_FILE = os.path.join(LOG_DIR, 'fqlan.log')
DNS_RULES = [
    (
        {'target': 'ACCEPT', 'extra': 'udp dpt:53 mark match 0xcafe', 'optional': True},
        ('nat', 'OUTPUT', '-p udp --dport 53 -m mark --mark 0xcafe -j ACCEPT')
    ), (
        {'target': 'DNAT', 'extra': 'udp dpt:53 to:10.1.2.3:12345'},
        ('nat', 'OUTPUT', '-p udp ! -s 10.1.2.3 --dport 53 -j DNAT --to-destination 10.1.2.3:12345')
    ), (
        {'target': 'DNAT', 'extra': 'udp dpt:53 to:10.1.2.3:12345'},
        ('nat', 'PREROUTING', '-p udp ! -s 10.1.2.3 --dport 53 -j DNAT --to-destination 10.1.2.3:12345')
    )]
SOCKS_RULES = [
    (
        {'target': 'ACCEPT', 'destination': '127.0.0.1'},
        ('nat', 'OUTPUT', '-p tcp -d 127.0.0.1 -j ACCEPT')
    ), (
        {'target': 'DNAT', 'extra': 'to:10.1.2.3:12345'},
        ('nat', 'OUTPUT', '-p tcp ! -s 10.1.2.3 -j DNAT --to-destination 10.1.2.3:12345')
    ), (
        {'target': 'DNAT', 'extra': 'to:10.1.2.3:12345'},
        ('nat', 'PREROUTING', '-p tcp ! -s 10.1.2.3 -j DNAT --to-destination 10.1.2.3:12345')
    )]
default_dns_server = config.get_default_dns_server()


def handle_ping(environ, start_response):
    try:
        LOGGER.info('PONG/%s' % FQROUTER_VERSION)
    except:
        traceback.print_exc()
        os._exit(1)
    start_response(httplib.OK, [('Content-Type', 'text/plain')])
    yield 'PONG/%s' % FQROUTER_VERSION


fqsocks.httpd.HANDLERS[('GET', 'ping')] = handle_ping


def setup_logging():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    handler = logging.handlers.RotatingFileHandler(
        MANAGER_LOG_FILE, maxBytes=1024 * 256, backupCount=0)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger('fqrouter').addHandler(handler)
    handler = logging.handlers.RotatingFileHandler(
        FQDNS_LOG_FILE, maxBytes=1024 * 256, backupCount=0)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger('fqdns').addHandler(handler)
    handler = logging.handlers.RotatingFileHandler(
        FQLAN_LOG_FILE, maxBytes=1024 * 256, backupCount=0)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger('fqlan').addHandler(handler)
    handler = logging.handlers.RotatingFileHandler(
        WIFI_LOG_FILE, maxBytes=1024 * 512, backupCount=1)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger('wifi').addHandler(handler)


def needs_su():
    if os.getuid() == 0:
        return False
    else:
        return True


def run():
    iptables.init_fq_chains()
    shutdown_hook.add(iptables.flush_fq_chain)
    iptables.insert_rules(DNS_RULES)
    shutdown_hook.add(functools.partial(iptables.delete_rules, DNS_RULES))
    iptables.insert_rules(SOCKS_RULES)
    shutdown_hook.add(functools.partial(iptables.delete_rules, SOCKS_RULES))
    wifi.setup_lo_alias()
    try:
        comp_scrambler.start()
        shutdown_hook.add(comp_scrambler.stop)
    except:
        LOGGER.exception('failed to start comp_scrambler')
        comp_scrambler.stop()
    try:
        comp_shortcut.start()
        shutdown_hook.add(comp_shortcut.stop)
    except:
        LOGGER.exception('failed to start comp_shortcut')
        comp_shortcut.stop()
    args = [
        '--log-level', 'INFO',
        '--log-file', '/data/data/fq.router2/log/fqsocks.log',
        '--ifconfig-command', '/data/data/fq.router2/busybox',
        '--ip-command', '/data/data/fq.router2/busybox',
        '--tcp-listen', '10.1.2.3:12345',
        '--dns-listen', '10.1.2.3:12345',
        '--manager-listen', '*:2515',
        '--http-listen', '*:2516']
    args = config.configure_fqsocks(args)
    if config.read().get('tcp_scrambler_enabled', True):
        args += ['--http-request-mark', '0xbabe'] # trigger scrambler
    fqsocks.fqsocks.main(args)


def clean():
    LOGGER.info('clean...')
    try:
        iptables.flush_fq_chain()
        try:
            LOGGER.info('iptables -L -v -n')
            LOGGER.info(shell.check_output(shlex.split('iptables -L -v -n')))
        except subprocess.CalledProcessError, e:
            LOGGER.error('failed to dump filter table: %s' % (sys.exc_info()[1]))
            LOGGER.error(e.output)
        try:
            LOGGER.info('iptables -t nat -L -v -n')
            LOGGER.info(shell.check_output(shlex.split('iptables -t nat -L -v -n')))
        except subprocess.CalledProcessError, e:
            LOGGER.error('failed to dump nat table: %s' % (sys.exc_info()[1]))
            LOGGER.error(e.output)
    except:
        LOGGER.exception('clean failed')


if '__main__' == __name__:
    setup_logging()
    LOGGER.info('environment: %s' % os.environ.items())
    LOGGER.info('default dns server: %s' % default_dns_server)
    FQROUTER_VERSION = os.getenv('FQROUTER_VERSION')
    action = sys.argv[1]
    if 'clean' == action:
        shell.USE_SU = needs_su()
        clean()
    elif 'run' == action:
        shell.USE_SU = needs_su()
        run()
    elif 'netd-execute' == action:
        wifi.netd_execute(sys.argv[2])
    else:
        raise Exception('unknown action: %s' % action)