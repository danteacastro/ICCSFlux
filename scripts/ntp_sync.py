#!/usr/bin/env python3
"""One-shot NTP time sync for NI Linux RT.

NI Linux RT does not ship ntpdate or ntpd. This script provides equivalent
functionality using only Python stdlib (socket + struct) and the BusyBox
'date' command available on all NI RT targets.

Reads the broker IP and port from mqtt_creds.json, waits up to 120s for it
to be reachable via TCP (handles cold-boot race where network comes up after
this script starts), queries NTP (UDP 123), and sets the system clock via
'date -s @T'.

TCP reachability check (not ICMP ping) is used because Windows Firewall
commonly blocks ICMP echo requests from the cRIO — TCP connects to the
broker's MQTT port, which is always open when the broker is running.

Called from crio_init_service.sh in the background so it does not block
the cRIO node from starting. Any failure is non-fatal — the node starts
regardless and drift accumulates until the next service restart.

Usage (as root on cRIO):
    python3 /home/admin/nisystem/ntp_sync.py
"""
import json
import os
import socket
import struct
import sys
import time

CREDS = '/home/admin/nisystem/mqtt_creds.json'
NTP_TIMEOUT_S = 5
WAIT_MAX_S = 120
WAIT_STEP_S = 5
NTP_EPOCH_DELTA = 2208988800  # seconds between 1900-01-01 and 1970-01-01

def get_broker_info():
    """Return (ip, port) from mqtt_creds.json, or (None, None) on error."""
    try:
        with open(CREDS) as f:
            data = json.load(f)
        return data['broker'], int(data.get('port', 8883))
    except Exception:
        return None, None

def ntp_query(server):
    """Query NTP server (UDP 123), return Unix timestamp of transmit field."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(NTP_TIMEOUT_S)
    # LI=0, VN=3, Mode=3 (client)
    s.sendto(bytes([0x1b] + [0] * 47), (server, 123))
    data, _ = s.recvfrom(1024)
    s.close()
    # Transmit Timestamp is word 10 in the 48-byte NTP packet
    return struct.unpack('!12I', data)[10] - NTP_EPOCH_DELTA

def host_reachable(ip, port):
    """Check reachability via TCP connect (works through Windows Firewall).

    ICMP ping is not used because Windows Firewall commonly blocks ICMP echo
    requests from the cRIO, causing false 'unreachable' results even when the
    broker is fully operational on TCP.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False

broker, broker_port = get_broker_info()
if not broker:
    print('ntp_sync: broker IP not found in mqtt_creds.json — skipping', flush=True)
    sys.exit(0)

print(f'ntp_sync: waiting for {broker}:{broker_port}...', flush=True)
waited = 0
while waited < WAIT_MAX_S and not host_reachable(broker, broker_port):
    time.sleep(WAIT_STEP_S)
    waited += WAIT_STEP_S

if not host_reachable(broker, broker_port):
    print(f'ntp_sync: {broker}:{broker_port} unreachable after {WAIT_MAX_S}s — skipping', flush=True)
    sys.exit(0)

try:
    t = ntp_query(broker)
    offset = t - time.time()
    os.system(f'date -s @{int(t)}')
    print(f'ntp_sync: synced to {broker}, offset={offset:+.1f}s', flush=True)
except Exception as e:
    print(f'ntp_sync: query failed: {e}', flush=True)
    sys.exit(0)
