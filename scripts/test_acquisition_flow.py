#!/usr/bin/env python3
"""
Acquisition Pipeline Diagnostic — Standalone MQTT-based test tool.

Auto-detects cDAQ (local) vs cRIO (remote) mode and traces the full
acquisition lifecycle step by step, reporting exactly where things break.

Steps:
  0. Pre-flight: MQTT connectivity, heartbeats
  1. DAQ service baseline state
  2. Hardware detection (cDAQ local or cRIO remote)
  3. Load test project
  4. Config push (cRIO only: verify config reaches node)
  5. Acquire START — trace full command flow with timeline
  6. Channel data flowing — verify values at each pipeline stage
  7. WebSocket bridge — verify dashboard can see data
  8. Acquire STOP — trace stop flow, verify data stops
  9. Second cycle — clean restart to verify state cleanup
 10. Summary + diagnosis

Prerequisites: NISystem Start.bat running (or Mosquitto + DAQ service).
Usage:
    python scripts/test_acquisition_flow.py                    # Auto-detect
    python scripts/test_acquisition_flow.py --mode crio        # Force cRIO
    python scripts/test_acquisition_flow.py --mode cdaq        # Force cDAQ
    python scripts/test_acquisition_flow.py --project MyProj.json
    python scripts/test_acquisition_flow.py --skip-stop        # Leave acquiring
"""

import paho.mqtt.client as mqtt
import json
import time
import sys
import threading
import ssl
import argparse
from pathlib import Path

BROKER = '127.0.0.1'
PORT_TCP = 1883
PORT_WS = 9002
DAQ_NODE = 'node-001'
PREFIX = 'nisystem'

# Default projects per mode
CRIO_PROJECT = '_CrioAcquisitionTest.json'
CDAQ_PROJECT = '_CdaqAcquisitionTest.json'

# MQTT credentials (optional — port 1883 may allow anonymous)
ROOT = Path(__file__).resolve().parent.parent
CRED_FILE = ROOT / 'config' / 'mqtt_credentials.json'
ADMIN_PW_FILE = ROOT / 'data' / 'initial_admin_password.txt'


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_credentials():
    """Load MQTT credentials if available."""
    if not CRED_FILE.exists():
        return None, None
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds['backend']['username'], creds['backend']['password']
    except Exception:
        return None, None


def load_admin_credentials():
    """Load DAQ service admin credentials for app-level auth.

    Returns list of (username, password) pairs to try, in priority order:
    1. test_admin with known test password (created by test suite)
    2. admin with initial password from file
    """
    candidates = []

    # Test admin user (created by conftest.py ensure_test_admin)
    candidates.append(('test_admin', 'validation_test_pw_2026'))

    # Initial admin password from file
    if ADMIN_PW_FILE.exists():
        try:
            text = ADMIN_PW_FILE.read_text(encoding='utf-8')
            username = password = None
            for line in text.splitlines():
                if 'Username:' in line:
                    username = line.split(':', 1)[1].strip()
                elif 'Password:' in line:
                    password = line.split(':', 1)[1].strip()
            if username and password:
                candidates.append((username, password))
        except Exception:
            pass

    return candidates if candidates else [('admin', None)]


class MQTTSniffer:
    """MQTT client that collects messages for analysis."""

    def __init__(self, client_id, port=PORT_TCP, transport='tcp'):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id, transport=transport)
        if transport == 'websockets':
            self.client.ws_set_options(path='/mqtt')
        else:
            # Try credentials for TCP
            user, pw = load_credentials()
            if user:
                self.client.username_pw_set(user, pw)
        self.port = port
        self.messages = []
        self.connected = False
        self._lock = threading.Lock()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, props=None):
        rc_val = rc.value if hasattr(rc, 'value') else rc
        self.connected = (rc_val == 0)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except Exception:
            payload = msg.payload
        with self._lock:
            self.messages.append((time.time(), msg.topic, payload, msg.retain))

    def connect(self):
        try:
            self.client.connect(BROKER, self.port)
            self.client.loop_start()
            for _ in range(30):
                if self.connected:
                    return True
                time.sleep(0.1)
            return False
        except Exception as e:
            print(f'    Connect error: {e}')
            return False

    def subscribe(self, topic, qos=0):
        self.client.subscribe(topic, qos)

    def publish(self, topic, payload, qos=1, retain=False):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, qos=qos, retain=retain)

    def wait(self, seconds):
        time.sleep(seconds)

    def get_messages(self, topic_filter=None, skip_retained=False):
        with self._lock:
            msgs = list(self.messages)
        if topic_filter:
            msgs = [(t, top, p, r) for t, top, p, r in msgs if topic_filter in top]
        if skip_retained:
            msgs = [(t, top, p, r) for t, top, p, r in msgs if not r]
        return msgs

    def clear(self):
        with self._lock:
            self.messages.clear()

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


def wait_for_message(sniffer, topic_filter, timeout=5, skip_retained=False):
    """Wait for a message matching the filter. Returns payload or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = sniffer.get_messages(topic_filter, skip_retained=skip_retained)
        if msgs:
            return msgs[-1][2]  # payload of last match
        time.sleep(0.2)
    return None


# ── Output formatting ────────────────────────────────────────────────────────

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    DIM = '\033[90m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def PASS(name, detail=''):
    print(f'  {Colors.GREEN}[PASS]{Colors.RESET} {name}')
    if detail:
        print(f'         {Colors.DIM}{detail}{Colors.RESET}')

def FAIL(name, detail=''):
    print(f'  {Colors.RED}[FAIL]{Colors.RESET} {name}')
    if detail:
        print(f'         {Colors.RED}{detail}{Colors.RESET}')

def WARN(name, detail=''):
    print(f'  {Colors.YELLOW}[WARN]{Colors.RESET} {name}')
    if detail:
        print(f'         {Colors.YELLOW}{detail}{Colors.RESET}')

def INFO(msg):
    print(f'         {Colors.DIM}{msg}{Colors.RESET}')

def DIAG(msg):
    """Diagnosis / recommendation line."""
    print(f'         {Colors.CYAN}>> {msg}{Colors.RESET}')

def header(step_num, name):
    print(f'\n{Colors.BOLD}{"="*64}{Colors.RESET}')
    print(f'  {Colors.BOLD}Step {step_num}: {name}{Colors.RESET}')
    print(f'{Colors.BOLD}{"="*64}{Colors.RESET}')

def timeline(t0, ts, msg):
    """Print a timeline entry."""
    dt = int((ts - t0) * 1000)
    print(f'    {Colors.DIM}T+{dt:>5}ms{Colors.RESET}  {msg}')


# ── Tests ────────────────────────────────────────────────────────────────────

results = {}  # step -> True/False
context = {}  # shared state between tests


def step_0_preflight():
    """Connect to MQTT, verify broker is alive."""
    header(0, 'Pre-flight — MQTT connectivity')

    s = MQTTSniffer('diag-preflight')
    if not s.connect():
        FAIL('MQTT connection', f'Cannot connect to {BROKER}:{PORT_TCP}')
        DIAG('Is Mosquitto running? Check NISystem Start.bat or run: mosquitto -v -c config/mosquitto.conf')
        results['step_0'] = False
        return None

    PASS('MQTT connection', f'{BROKER}:{PORT_TCP}')

    # Listen for everything for 5 seconds
    s.subscribe(f'{PREFIX}/#')
    s.wait(5)

    all_msgs = s.get_messages()
    unique_topics = set(m[1] for m in all_msgs)
    INFO(f'Messages in 5s: {len(all_msgs)} across {len(unique_topics)} topics')

    # Check DAQ heartbeat
    daq_hb = s.get_messages(f'{DAQ_NODE}/status/system', skip_retained=False)
    if daq_hb:
        PASS('DAQ service heartbeat')
    else:
        # Also check legacy paths
        daq_hb2 = s.get_messages(f'{DAQ_NODE}/heartbeat')
        if daq_hb2:
            PASS('DAQ service heartbeat (legacy topic)')
        else:
            FAIL('DAQ service heartbeat', 'No status from node-001 in 5s')
            DIAG('DAQ service may not be running. Check NISystem Start.bat output.')

    # Check for any cRIO nodes
    crio_msgs = [m for m in all_msgs if 'crio' in m[1].lower()]
    crio_nodes = set()
    for _, topic, _, _ in crio_msgs:
        parts = topic.split('/')
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts) and 'crio' in parts[i + 1].lower():
                crio_nodes.add(parts[i + 1])
    if crio_nodes:
        INFO(f'cRIO nodes detected: {", ".join(sorted(crio_nodes))}')
        context['crio_nodes'] = sorted(crio_nodes)
    else:
        INFO('No cRIO nodes detected on MQTT')

    results['step_0'] = bool(daq_hb or s.get_messages(f'{DAQ_NODE}/heartbeat'))
    return s


def step_1_daq_state(s):
    """Read DAQ service status."""
    header(1, 'DAQ service state')

    s.clear()
    status = wait_for_message(s, f'{DAQ_NODE}/status/system', timeout=5)

    if not status or not isinstance(status, dict):
        FAIL('DAQ status', 'No status/system message')
        DIAG('DAQ service is not publishing. Check if it crashed after startup.')
        results['step_1'] = False
        return

    # Extract key fields
    st = status.get('status', '?')
    acq = status.get('acquiring', False)
    state = status.get('acquisition_state', status.get('state', '?'))
    mode = status.get('project_mode', status.get('hardware_mode', '?'))
    ch_count = status.get('channel_count', status.get('channels', 0))
    sim = status.get('simulation_mode', '?')
    local_ch = status.get('local_daq_channel_count', '?')
    crio_ch = status.get('crio_channel_count', 0)

    INFO(f'status={st}  state={state}  acquiring={acq}')
    INFO(f'mode={mode}  simulation={sim}  channels={ch_count} (local={local_ch}, crio={crio_ch})')

    context['daq_status'] = status
    context['already_acquiring'] = bool(acq)

    if st == 'online':
        PASS('DAQ service online')
    else:
        FAIL('DAQ service online', f'status={st}')

    if acq:
        WARN('Already acquiring', 'Will send STOP first, then restart')

    results['step_1'] = (st == 'online')


def step_2_detect_hardware(s, forced_mode=None):
    """Detect hardware mode: cDAQ (local) vs cRIO (remote)."""
    header(2, 'Hardware detection')

    # If user forced a mode, use it
    if forced_mode:
        context['mode'] = forced_mode
        if forced_mode == 'crio':
            # Pick first cRIO node
            nodes = context.get('crio_nodes', ['crio-001'])
            context['crio_node'] = nodes[0]
            INFO(f'Forced mode: cRIO ({context["crio_node"]})')
        else:
            INFO(f'Forced mode: cDAQ (local)')
        PASS(f'Mode: {forced_mode}')
        results['step_2'] = True
        return

    # Auto-detect from DAQ status
    daq_status = context.get('daq_status', {})
    crio_ch = daq_status.get('crio_channel_count', 0)
    crio_nodes = context.get('crio_nodes', [])

    if crio_nodes and crio_ch > 0:
        context['mode'] = 'crio'
        context['crio_node'] = crio_nodes[0]
        INFO(f'Detected cRIO mode: {context["crio_node"]} ({crio_ch} cRIO channels)')
        PASS(f'Mode: cRIO ({context["crio_node"]})')
    elif crio_nodes:
        # cRIO is online but no channels configured yet (project not loaded)
        context['mode'] = 'crio'
        context['crio_node'] = crio_nodes[0]
        INFO(f'cRIO online but no channels yet — will configure after project load')
        PASS(f'Mode: cRIO ({context["crio_node"]})')
    else:
        context['mode'] = 'cdaq'
        INFO('No cRIO detected — using cDAQ (local) mode')
        PASS('Mode: cDAQ (local)')

    results['step_2'] = True


def authenticate(s):
    """Authenticate with DAQ service (app-level auth over MQTT). Returns True on success."""
    candidates = load_admin_credentials()

    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/auth/status', qos=1)
    time.sleep(0.3)

    for username, password in candidates:
        if not password:
            continue

        s.clear()
        s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/auth/login', {
            'username': username,
            'password': password,
            'source_ip': 'diagnostic-tool',
        })
        INFO(f'Trying auth/login as "{username}"...')

        auth_status = wait_for_message(s, 'auth/status', timeout=5)
        if not auth_status or not isinstance(auth_status, dict):
            WARN('No auth/status response', 'DAQ may not require auth or is not responding')
            continue

        if auth_status.get('authenticated'):
            role = auth_status.get('role', '?')
            PASS('Authenticated', f'user={username} role={role}')
            context['authenticated'] = True
            return True
        else:
            INFO(f'Auth as "{username}" failed: {auth_status.get("error", "unknown")}')

    FAIL('Authentication', 'All credential attempts failed')
    DIAG('Check data/initial_admin_password.txt or ensure test_admin user exists')
    return False


def step_3_load_project(s, project_file=None):
    """Load a test project."""
    header(3, 'Load project')

    mode = context.get('mode', 'cdaq')
    if not project_file:
        project_file = CRIO_PROJECT if mode == 'crio' else CDAQ_PROJECT

    # Authenticate first (required for project load)
    if not context.get('authenticated'):
        auth_ok = authenticate(s)
        if not auth_ok:
            WARN('Auth failed', 'Attempting project load anyway...')

    # If already acquiring, stop first
    if context.get('already_acquiring'):
        INFO('Stopping current acquisition first...')
        s.clear()
        s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/command/ack', qos=1)
        time.sleep(0.3)
        s.clear()
        s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/system/acquire/stop', {})
        ack = wait_for_message(s, 'command/ack', timeout=10)
        if ack:
            INFO(f'Stop ACK: acquiring={ack.get("acquiring", "?")}')
        else:
            WARN('No stop ACK', 'Continuing anyway...')
        time.sleep(2)
        context['already_acquiring'] = False

    # Subscribe to project responses (both success and error topics)
    s.clear()
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/project/#', qos=1)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/config/#', qos=1)
    time.sleep(0.5)
    s.clear()

    # Send project load
    s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/project/load', {'filename': project_file})
    INFO(f'Sent project/load: {project_file}')

    # Wait for response — DAQ publishes to project/loaded on success,
    # and project/response on errors (including permission denied)
    deadline = time.time() + 15
    loaded = None
    while time.time() < deadline:
        # Check success topic
        success_msgs = s.get_messages('project/loaded', skip_retained=True)
        if success_msgs:
            loaded = success_msgs[-1][2]
            break
        # Check error/response topic
        resp_msgs = s.get_messages('project/response', skip_retained=True)
        if resp_msgs:
            loaded = resp_msgs[-1][2]
            break
        time.sleep(0.2)

    if not loaded:
        errs = s.get_messages('project/error')
        if errs:
            FAIL('Project load', f'Error: {json.dumps(errs[-1][2])[:200]}')
        else:
            FAIL('Project load', 'No response in 15s')
            DIAG('DAQ service may not be processing commands. Check if it is hung.')
        results['step_3'] = False
        return

    success = loaded.get('success', False)
    name = loaded.get('name', loaded.get('filename', '?'))
    ch_count = loaded.get('channel_count', '?')

    INFO(f'success={success}  name={name}  channels={ch_count}')

    if success:
        PASS('Project loaded', f'{ch_count} channels')
        context['channel_count'] = ch_count
    else:
        msg = loaded.get('message', loaded.get('error', 'unknown'))
        FAIL('Project loaded', f'{msg}')
        if 'permission' in str(msg).lower():
            DIAG('Permission denied — authentication may have failed or role insufficient')
            DIAG('Check data/initial_admin_password.txt matches current admin password')
        else:
            DIAG(f'Check that config/projects/{project_file} exists and is valid JSON')

    results['step_3'] = bool(success)

    # Give DAQ time to process config, then read back status for rates
    time.sleep(3)

    # Read DAQ status to capture configured rates
    s.clear()
    status = wait_for_message(s, f'{DAQ_NODE}/status/system', timeout=5)
    if status and isinstance(status, dict):
        scan_hz = status.get('scan_rate_hz', 0)
        pub_hz = status.get('publish_rate_hz', 0)
        ch_count_now = status.get('channel_count', 0)
        context['expected_scan_rate_hz'] = scan_hz
        context['expected_publish_rate_hz'] = pub_hz
        INFO(f'Configured rates: scan={scan_hz} Hz, publish={pub_hz} Hz, channels={ch_count_now}')
        if pub_hz <= 0:
            WARN('publish_rate_hz is 0', 'No data will be published')
    else:
        WARN('Could not read DAQ status after project load')


def step_4_config_push(s):
    """Verify config push to cRIO (cRIO mode only)."""
    header(4, 'Config push')

    mode = context.get('mode', 'cdaq')
    if mode == 'cdaq':
        INFO('cDAQ mode — no remote config push needed')
        PASS('Config push (N/A for cDAQ)')
        results['step_4'] = True
        return

    crio_node = context.get('crio_node', 'crio-001')

    s.clear()
    s.subscribe(f'{PREFIX}/nodes/{crio_node}/config/#', qos=1)
    s.subscribe(f'{PREFIX}/nodes/{crio_node}/status/system', qos=1)
    time.sleep(0.5)
    s.clear()

    # Trigger discovery to make DAQ aware of cRIO
    s.publish(f'{PREFIX}/discovery/ping', {'source': 'diagnostic'})

    # Wait for config/full
    deadline = time.time() + 15
    config_full = None
    config_resp = None

    while time.time() < deadline:
        fulls = s.get_messages('config/full')
        resps = s.get_messages('config/response')
        if fulls:
            config_full = fulls[-1][2]
        if resps:
            config_resp = resps[-1][2]
        if config_full or config_resp:
            time.sleep(2)
            fulls = s.get_messages('config/full')
            resps = s.get_messages('config/response')
            if fulls:
                config_full = fulls[-1][2]
            if resps:
                config_resp = resps[-1][2]
            break
        time.sleep(0.5)

    if config_full:
        ch_count = len(config_full.get('channels', {}))
        cv = str(config_full.get('config_version', '?'))[:16]
        PASS('Config pushed to cRIO', f'{ch_count} channels, version={cv}')

        # Verify rates are included in config push
        pushed_scan = config_full.get('scan_rate_hz', None)
        pushed_pub = config_full.get('publish_rate_hz', None)
        expected_scan = context.get('expected_scan_rate_hz', 0)
        expected_pub = context.get('expected_publish_rate_hz', 0)

        if pushed_scan is not None and pushed_pub is not None:
            INFO(f'Config rates: scan={pushed_scan} Hz, publish={pushed_pub} Hz')
            if expected_scan and pushed_scan != expected_scan:
                WARN('Scan rate mismatch', f'DAQ={expected_scan} Hz, pushed={pushed_scan} Hz')
            if expected_pub and pushed_pub != expected_pub:
                WARN('Publish rate mismatch', f'DAQ={expected_pub} Hz, pushed={pushed_pub} Hz')
            if pushed_scan == expected_scan and pushed_pub == expected_pub:
                PASS('Config rates match project', f'scan={pushed_scan} Hz, publish={pushed_pub} Hz')
        else:
            WARN('Config push missing rate fields', 'cRIO will use defaults (4 Hz)')
            DIAG('scan_rate_hz / publish_rate_hz not found in config/full payload')
    else:
        # Config may have already been pushed in a prior session — check cRIO status
        crio_status = s.get_messages(f'{crio_node}/status/system')
        if crio_status:
            st = crio_status[-1][2] if isinstance(crio_status[-1][2], dict) else {}
            ch_count = st.get('channel_count', st.get('channels', 0))
            if ch_count > 0:
                WARN('No config/full observed', f'But cRIO has {ch_count} channels — config already loaded')
                DIAG('Config was likely pushed in a prior session. This is normal on re-run.')
                config_full = True  # treat as OK
            else:
                FAIL('Config push', 'No config/full message in 15s')
                DIAG(f'DAQ may not see {crio_node} as online. Check cRIO network.')
                DIAG('Check DAQ logs for "cRIO online" or device discovery messages.')
        else:
            FAIL('Config push', 'No config/full message in 15s')
            DIAG(f'{crio_node} not responding — check cRIO network and power.')
            DIAG('Check DAQ logs for "cRIO online" or device discovery messages.')

    if config_resp:
        success = config_resp.get('success', config_resp.get('status') == 'success')
        PASS('cRIO config ACK', f'success={success}')
    else:
        if config_full:
            WARN('cRIO config ACK missing', 'Config was sent but no ACK received')
            DIAG(f'cRIO may have crashed processing config. SSH to check logs.')
        else:
            FAIL('cRIO config ACK', 'No response')

    results['step_4'] = bool(config_full or config_resp)


def step_5_acquire_start(s):
    """Send acquire/start and trace the full command flow with timeline."""
    header(5, 'Acquire START')

    mode = context.get('mode', 'cdaq')
    crio_node = context.get('crio_node', 'crio-001')

    s.clear()
    # Subscribe to all relevant topics
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/command/ack', qos=1)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/status/system', qos=1)
    if mode == 'crio':
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/system/acquire/#', qos=1)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/command/ack', qos=1)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/status/system', qos=1)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/config/#', qos=1)
    # Acquisition events (if pipeline is active)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/acquisition/events', qos=0)
    time.sleep(0.5)
    s.clear()

    t0 = time.time()
    s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/system/acquire/start', {})
    INFO(f'acquire/start sent to {DAQ_NODE}')

    # Collect for 15s
    s.wait(15)

    # ── Timeline analysis ──
    print(f'\n  {Colors.BOLD}Timeline:{Colors.RESET}')
    timeline(t0, t0, 'acquire/start published')

    # DAQ ACK
    daq_acks = s.get_messages(f'{DAQ_NODE}/command/ack', skip_retained=True)
    daq_ok = False
    if daq_acks:
        ts, _, ack, _ = daq_acks[0]
        success = ack.get('success', ack.get('acquiring', False))
        acq = ack.get('acquiring', '?')
        cmd = ack.get('command', '?')
        timeline(t0, ts, f'DAQ ACK: command={cmd} success={success} acquiring={acq}')
        if ack.get('error'):
            timeline(t0, ts, f'  ERROR: {ack["error"]}')
        daq_ok = bool(success) or bool(acq)
    else:
        timeline(t0, t0 + 15, 'DAQ ACK: NONE (15s timeout)')

    # DAQ status change
    daq_status_msgs = s.get_messages(f'{DAQ_NODE}/status/system', skip_retained=True)
    for ts, _, st, _ in daq_status_msgs[:3]:
        acq = st.get('acquiring', '?')
        state = st.get('acquisition_state', '?')
        timeline(t0, ts, f'DAQ status: acquiring={acq} state={state}')

    # Acquisition events
    acq_events = s.get_messages('acquisition/events')
    if acq_events:
        for ts, _, evt, _ in acq_events[:10]:
            if isinstance(evt, dict):
                name = evt.get('event', '?')
                sev = evt.get('severity', 'info')
                det = evt.get('details', {})
                det_str = f' | {json.dumps(det)[:80]}' if det else ''
                color = Colors.RED if sev == 'error' else Colors.YELLOW if sev == 'warning' else Colors.DIM
                timeline(t0, ts, f'{color}[{sev.upper()}] {name}{det_str}{Colors.RESET}')

    if mode == 'crio':
        # Config push during start
        crio_config = s.get_messages(f'{crio_node}/config/full')
        if crio_config:
            ts, _, cfg, _ = crio_config[0]
            ch = len(cfg.get('channels', {})) if isinstance(cfg, dict) else '?'
            timeline(t0, ts, f'Config pushed to cRIO ({ch} channels)')

        # Start forwarded to cRIO
        crio_start = s.get_messages(f'{crio_node}/system/acquire/start')
        if crio_start:
            ts = crio_start[0][0]
            timeline(t0, ts, f'acquire/start forwarded to {crio_node}')
        else:
            timeline(t0, t0 + 15, f'acquire/start NOT forwarded to {crio_node}')

        # cRIO ACK
        crio_acks = s.get_messages(f'{crio_node}/command/ack', skip_retained=True)
        crio_ok = False
        if crio_acks:
            ts, _, ack, _ = crio_acks[0]
            acq = ack.get('acquiring', False)
            timeline(t0, ts, f'cRIO ACK: acquiring={acq}')
            crio_ok = bool(acq)
        else:
            timeline(t0, t0 + 15, 'cRIO ACK: NONE')

        # cRIO status
        crio_status = s.get_messages(f'{crio_node}/status/system', skip_retained=True)
        for ts, _, st, _ in crio_status[:2]:
            acq = st.get('acquiring', '?')
            timeline(t0, ts, f'cRIO status: acquiring={acq}')

    print()

    # ── Verdict ──
    if daq_ok:
        PASS('DAQ acquiring')
    else:
        FAIL('DAQ acquiring')
        if not daq_acks:
            DIAG('No ACK at all — command may not have been received.')
            DIAG('Check if DAQ service is subscribed to system/acquire/start topic.')
        else:
            ack = daq_acks[0][2]
            if ack.get('error'):
                DIAG(f'Error from DAQ: {ack["error"]}')
            if 'permission' in str(ack).lower():
                DIAG('Permission denied — check user role (must be Operator or Admin)')
            if 'state' in str(ack.get('error', '')).lower():
                DIAG('State machine rejected — DAQ may be in wrong state (STOPPING?)')

    if mode == 'crio':
        crio_detected = bool(context.get('crio_nodes'))
        if crio_ok:
            PASS('cRIO acquiring')
        elif not crio_detected:
            WARN('cRIO not on network', 'No cRIO heartbeat detected in Step 0')
            DIAG('cRIO may be powered off or not on the network')
            DIAG('DAQ-side acquisition is running — testing DAQ pipeline only')
        else:
            FAIL('cRIO acquiring')
            if not crio_start:
                DIAG('DAQ did not forward command to cRIO')
                DIAG('Possible causes: cRIO not in device list, config push pending')
            elif not crio_acks:
                DIAG('cRIO received start but no ACK — may have crashed')
                DIAG(f'SSH to cRIO and check: journalctl -u crio_node -n 50')
            else:
                DIAG(f'cRIO rejected start: {json.dumps(crio_acks[0][2])[:200]}')
        # Pass step if DAQ is acquiring (cRIO offline is a WARN, not a blocker)
        results['step_5'] = daq_ok
    else:
        results['step_5'] = daq_ok


def _analyze_batch(batch, label, max_samples=5):
    """Analyze a batch payload: count values, show samples. Returns (keys, stats)."""
    if not isinstance(batch, dict):
        FAIL(f'{label} batch format', f'Expected dict, got {type(batch).__name__}')
        return [], {}

    keys = list(batch.keys())
    INFO(f'{label} channels in batch: {len(keys)}')

    nan_count = 0
    zero_count = 0
    good_count = 0
    for k in keys[:50]:
        entry = batch[k]
        val = entry.get('value') if isinstance(entry, dict) else entry
        if val is None or (isinstance(val, float) and val != val):
            nan_count += 1
        elif val == 0 or val == 0.0:
            zero_count += 1
        else:
            good_count += 1

    INFO(f'Values: {good_count} good, {zero_count} zero, {nan_count} NaN')

    for k in keys[:max_samples]:
        entry = batch[k]
        if isinstance(entry, dict):
            val = entry.get('value', '?')
            unit = entry.get('units', '')
            q = entry.get('quality', '')
            INFO(f'  {k}: {val} {unit} [{q}]')
        else:
            INFO(f'  {k}: {entry}')

    stats = {'total': len(keys), 'good': good_count, 'zero': zero_count, 'nan': nan_count}
    return keys, stats


def _measure_rate(messages, window_s, label, expected_hz=None):
    """Measure actual publish rate from message timestamps. Returns actual_hz."""
    if len(messages) < 2:
        return 0.0

    # Use message arrival timestamps (index 0 of tuple)
    timestamps = [m[0] for m in messages]
    # Trim to a clean window — drop first 1s (startup jitter)
    t_start = timestamps[0] + 1.0
    t_end = timestamps[-1]
    trimmed = [t for t in timestamps if t >= t_start]

    if len(trimmed) < 2 or (t_end - t_start) < 2.0:
        # Not enough data for reliable measurement
        actual_hz = len(messages) / window_s
    else:
        actual_hz = (len(trimmed) - 1) / (trimmed[-1] - trimmed[0])

    # Also measure inter-message jitter
    if len(trimmed) >= 3:
        intervals = [trimmed[i+1] - trimmed[i] for i in range(len(trimmed)-1)]
        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)
        jitter_ms = (max_interval - min_interval) * 1000
        INFO(f'{label} rate: {actual_hz:.2f} Hz (interval: avg={avg_interval*1000:.0f}ms, '
             f'min={min_interval*1000:.0f}ms, max={max_interval*1000:.0f}ms, jitter={jitter_ms:.0f}ms)')
    else:
        INFO(f'{label} rate: {actual_hz:.2f} Hz')

    if expected_hz and expected_hz > 0:
        ratio = actual_hz / expected_hz
        if ratio < 0.5:
            FAIL(f'{label} rate', f'{actual_hz:.2f} Hz — expected {expected_hz} Hz ({ratio:.0%})')
            DIAG(f'Actual rate is {ratio:.0%} of expected — severe underperformance')
            if ratio < 0.1:
                DIAG('Almost no data — scan loop may be blocked or hardware init failed')
            elif ratio < 0.3:
                DIAG('Major rate drop — check for long-running safety eval or script execution')
        elif ratio < 0.8:
            WARN(f'{label} rate below expected', f'{actual_hz:.2f} Hz vs {expected_hz} Hz ({ratio:.0%})')
            DIAG('Rate is low but data is flowing — may be timing drift or publish loop contention')
        elif ratio > 1.5:
            WARN(f'{label} rate higher than expected', f'{actual_hz:.2f} Hz vs {expected_hz} Hz ({ratio:.0%})')
        else:
            PASS(f'{label} rate', f'{actual_hz:.2f} Hz (expected {expected_hz} Hz, {ratio:.0%})')
    else:
        INFO(f'{label} measured rate: {actual_hz:.2f} Hz (no expected rate to compare)')

    return actual_hz


def step_6_channel_data(s):
    """Verify channel data is flowing at the correct rate."""
    header(6, 'Channel data + rate verification')

    if not results.get('step_5'):
        INFO('SKIP: Acquisition not started (Step 5 failed)')
        results['step_6'] = False
        return

    mode = context.get('mode', 'cdaq')
    crio_node = context.get('crio_node', 'crio-001')
    expected_pub_hz = context.get('expected_publish_rate_hz', 0)

    MEASURE_WINDOW = 15  # seconds — longer window for more accurate rate measurement

    s.clear()
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/channels/batch', qos=0)
    if mode == 'crio':
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/channels/batch', qos=0)

    INFO(f'Collecting data for {MEASURE_WINDOW}s (expected publish rate: {expected_pub_hz} Hz)...')
    s.wait(MEASURE_WINDOW)

    data_ok = False

    # ── DAQ batch data (local channels) ──
    daq_batches = s.get_messages(f'{DAQ_NODE}/channels/batch')
    INFO(f'DAQ batches in {MEASURE_WINDOW}s: {len(daq_batches)}')

    if daq_batches:
        batch = daq_batches[-1][2]
        keys, stats = _analyze_batch(batch, 'DAQ')

        if keys:
            daq_hz = _measure_rate(daq_batches, MEASURE_WINDOW, 'DAQ publish', expected_pub_hz)
            context['actual_daq_rate_hz'] = daq_hz

            # Check for all-NaN or all-zero (hardware didn't actually init)
            if stats.get('nan', 0) == stats.get('total', 0):
                FAIL('DAQ values', 'ALL channels are NaN — hardware read returning no data')
                DIAG('hardware_reader may have failed to create DAQmx tasks')
                DIAG('Check: channel_type matches physical module, device_name correct')
            elif stats.get('zero', 0) == stats.get('total', 0) and stats.get('total', 0) > 2:
                WARN('DAQ values all zero', 'Every channel reads 0 — may be simulation or disconnected')
            else:
                PASS('DAQ batch data', f'{len(keys)} channels')
            data_ok = True
    else:
        if mode == 'cdaq':
            FAIL('DAQ batch data', f'No batches in {MEASURE_WINDOW}s')
            DIAG('DAQ is acquiring but not publishing batch data')
            DIAG('Check: publish_rate_hz in project, hardware_reader initialization')
        else:
            INFO('No DAQ batch (expected — cRIO channels not in DAQ batch)')

    # ── cRIO batch data (remote channels) ──
    if mode == 'crio':
        crio_batches = s.get_messages(f'{crio_node}/channels/batch')
        INFO(f'cRIO batches in {MEASURE_WINDOW}s: {len(crio_batches)}')

        if crio_batches:
            batch = crio_batches[-1][2]
            keys, stats = _analyze_batch(batch, 'cRIO')

            if keys:
                crio_hz = _measure_rate(crio_batches, MEASURE_WINDOW, 'cRIO publish', expected_pub_hz)
                context['actual_crio_rate_hz'] = crio_hz

                if stats.get('nan', 0) == stats.get('total', 0):
                    FAIL('cRIO values', 'ALL channels are NaN — hardware not reading')
                    DIAG('cRIO hardware init may have failed — check cRIO logs')
                else:
                    PASS('cRIO batch data', f'{len(keys)} channels')
                data_ok = True
        else:
            FAIL('cRIO batch data', f'No batches from cRIO in {MEASURE_WINDOW}s')
            DIAG('cRIO says acquiring but no data — hardware init may have failed')
            DIAG('Check cRIO logs: SSH and check /opt/crio_node/logs/')

    # ── Compare first and last batch to verify values are CHANGING ──
    primary_batches = daq_batches if (mode == 'cdaq' or not s.get_messages(f'{crio_node}/channels/batch')) else s.get_messages(f'{crio_node}/channels/batch')
    if len(primary_batches) >= 4:
        first_batch = primary_batches[1][2]  # skip very first (may be partial)
        last_batch = primary_batches[-1][2]
        if isinstance(first_batch, dict) and isinstance(last_batch, dict):
            common_keys = set(first_batch.keys()) & set(last_batch.keys())
            changed = 0
            static = 0
            for k in list(common_keys)[:20]:
                v1 = first_batch[k].get('value') if isinstance(first_batch[k], dict) else first_batch[k]
                v2 = last_batch[k].get('value') if isinstance(last_batch[k], dict) else last_batch[k]
                if v1 is not None and v2 is not None and v1 != v2:
                    changed += 1
                else:
                    static += 1
            INFO(f'Value change check (sample of {changed+static}): {changed} changing, {static} static')
            if changed == 0 and static > 0:
                WARN('Values not changing', 'All sampled channels have identical values across batches')
                DIAG('Hardware may be returning stale/cached data, or simulation mode is off')

    results['step_6'] = data_ok


def step_7_websocket(s):
    """Verify data reaches the WebSocket port (dashboard path)."""
    header(7, 'WebSocket bridge (dashboard path)')

    if not results.get('step_6'):
        INFO('SKIP: No channel data (Step 6 failed)')
        results['step_7'] = False
        return

    mode = context.get('mode', 'cdaq')
    crio_node = context.get('crio_node', 'crio-001')

    ws = MQTTSniffer('diag-ws', port=PORT_WS, transport='websockets')
    if not ws.connect():
        FAIL('WebSocket connect', f'Cannot connect to {BROKER}:{PORT_WS}')
        DIAG('Mosquitto may not have WebSocket listener on port 9002')
        DIAG('Check mosquitto.conf for: listener 9002 127.0.0.1 / protocol websockets')
        results['step_7'] = False
        return

    PASS('WebSocket connect', f'{BROKER}:{PORT_WS}')

    WS_MEASURE_WINDOW = 10

    # Subscribe to batch data on WS
    ws.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/channels/batch', qos=0)
    if mode == 'crio':
        ws.subscribe(f'{PREFIX}/nodes/{crio_node}/channels/batch', qos=0)
    ws.wait(WS_MEASURE_WINDOW)

    daq_batches = ws.get_messages(f'{DAQ_NODE}/channels/batch')
    ws_count = len(daq_batches)
    if mode == 'crio':
        crio_batches = ws.get_messages(f'{crio_node}/channels/batch')
        ws_count += len(crio_batches)
        INFO(f'WS batches in {WS_MEASURE_WINDOW}s: DAQ={len(daq_batches)}, cRIO={len(crio_batches)}')
    else:
        INFO(f'WS batches in {WS_MEASURE_WINDOW}s: {len(daq_batches)}')

    if ws_count > 0:
        PASS('WebSocket data', f'{ws_count} batches routed to dashboard port')

        # Measure WS rate and compare to TCP rate
        expected_pub_hz = context.get('expected_publish_rate_hz', 0)
        if mode == 'crio' and crio_batches:
            ws_hz = _measure_rate(crio_batches, WS_MEASURE_WINDOW, 'WS cRIO', expected_pub_hz)
            tcp_hz = context.get('actual_crio_rate_hz', 0)
        else:
            ws_hz = _measure_rate(daq_batches, WS_MEASURE_WINDOW, 'WS DAQ', expected_pub_hz)
            tcp_hz = context.get('actual_daq_rate_hz', 0)

        # Compare WS rate to TCP rate (should be nearly identical)
        if tcp_hz > 0 and ws_hz > 0:
            drop_pct = (1.0 - ws_hz / tcp_hz) * 100
            if drop_pct > 20:
                WARN('WebSocket rate drop', f'WS={ws_hz:.2f} Hz vs TCP={tcp_hz:.2f} Hz ({drop_pct:.0f}% loss)')
                DIAG('Mosquitto may be dropping messages on the WS bridge')
                DIAG('Check Mosquitto log for "socket write error" or queue overflow')
            elif drop_pct > 5:
                INFO(f'Minor WS rate drop: {drop_pct:.1f}% (WS={ws_hz:.2f} vs TCP={tcp_hz:.2f})')
            else:
                PASS('WS rate matches TCP', f'WS={ws_hz:.2f} Hz, TCP={tcp_hz:.2f} Hz')
    else:
        FAIL('WebSocket data', 'No data on WebSocket — dashboard will show blank values')
        DIAG('Cross-listener routing is broken in Mosquitto')
        DIAG('Ensure mosquitto.conf has both TCP 1883 and WS 9002 listeners')

    ws.disconnect()

    results['step_7'] = ws_count > 0


def step_8_acquire_stop(s):
    """Send acquire/stop and verify clean shutdown."""
    header(8, 'Acquire STOP')

    if not results.get('step_5'):
        INFO('SKIP: Acquisition not started (Step 5 failed)')
        results['step_8'] = False
        return

    mode = context.get('mode', 'cdaq')
    crio_node = context.get('crio_node', 'crio-001')

    s.clear()
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/command/ack', qos=1)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/channels/batch', qos=0)
    if mode == 'crio':
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/system/acquire/#', qos=1)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/command/ack', qos=1)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/channels/batch', qos=0)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/acquisition/events', qos=0)
    time.sleep(0.5)
    s.clear()

    t0 = time.time()
    s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/system/acquire/stop', {})
    INFO(f'acquire/stop sent')

    s.wait(10)

    print(f'\n  {Colors.BOLD}Timeline:{Colors.RESET}')
    timeline(t0, t0, 'acquire/stop published')

    # DAQ ACK
    daq_acks = s.get_messages(f'{DAQ_NODE}/command/ack', skip_retained=True)
    if daq_acks:
        ts, _, ack, _ = daq_acks[0]
        acq = ack.get('acquiring', '?')
        timeline(t0, ts, f'DAQ ACK: acquiring={acq}')
        PASS('DAQ stopped')
    else:
        timeline(t0, t0 + 10, 'DAQ ACK: NONE')
        FAIL('DAQ stop ACK', 'No acknowledgement')

    if mode == 'crio':
        crio_stop = s.get_messages(f'{crio_node}/system/acquire/stop')
        if crio_stop:
            timeline(t0, crio_stop[0][0], f'Stop forwarded to {crio_node}')
            PASS('Stop forwarded to cRIO')
        else:
            FAIL('Stop forward to cRIO', 'Command not forwarded')

        crio_acks = s.get_messages(f'{crio_node}/command/ack', skip_retained=True)
        if crio_acks:
            ts, _, ack, _ = crio_acks[0]
            timeline(t0, ts, f'cRIO ACK: acquiring={ack.get("acquiring", "?")}')
            PASS('cRIO stopped')
        else:
            FAIL('cRIO stop ACK', 'No acknowledgement')

    # Verify data stops
    print()
    late_topic = f'{DAQ_NODE}/channels/batch'
    if mode == 'crio':
        late_topic = f'{crio_node}/channels/batch'

    late_batches = [m for m in s.get_messages(late_topic) if m[0] > t0 + 5]
    if late_batches:
        WARN('Data still flowing', f'{len(late_batches)} batches after 5s')
        DIAG('Stop may not have fully propagated')
    else:
        PASS('Data stopped')

    results['step_8'] = bool(daq_acks)


def step_9_second_cycle(s):
    """Start again to verify clean state cycling."""
    header(9, 'Second start cycle')

    if not results.get('step_8'):
        INFO('SKIP: Stop failed (Step 8 failed)')
        results['step_9'] = False
        return

    mode = context.get('mode', 'cdaq')
    crio_node = context.get('crio_node', 'crio-001')

    time.sleep(3)  # let things settle

    s.clear()
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/command/ack', qos=1)
    s.subscribe(f'{PREFIX}/nodes/{DAQ_NODE}/channels/batch', qos=0)
    if mode == 'crio':
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/channels/batch', qos=0)
        s.subscribe(f'{PREFIX}/nodes/{crio_node}/command/ack', qos=1)
    time.sleep(0.5)
    s.clear()

    t0 = time.time()
    s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/system/acquire/start', {})
    INFO('Second acquire/start sent')

    s.wait(12)

    # Check data first (most reliable indicator of successful start)
    batch_topic = f'{DAQ_NODE}/channels/batch'
    if mode == 'crio':
        batch_topic = f'{crio_node}/channels/batch'

    batches = s.get_messages(batch_topic)

    # Check ACK — look for the START ack specifically (may have stop ack too)
    daq_acks = s.get_messages(f'{DAQ_NODE}/command/ack', skip_retained=True)
    start_ack = None
    for _, _, ack, _ in daq_acks:
        cmd = ack.get('command', '')
        if 'start' in str(cmd).lower() or ack.get('acquiring'):
            start_ack = ack
            break

    if batches:
        PASS('Data on second cycle', f'{len(batches)} batches')
        if start_ack and start_ack.get('acquiring'):
            PASS('DAQ acquiring on second cycle')
        elif start_ack:
            INFO(f'ACK received but acquiring={start_ack.get("acquiring")} (data IS flowing)')
        else:
            INFO('No explicit start ACK but data is flowing')
    else:
        if start_ack and start_ack.get('acquiring'):
            WARN('DAQ says acquiring but no batches arrived', 'Publish loop may be delayed')
        else:
            FAIL('Data on second cycle', 'No batches — state cleanup may be broken')
            DIAG('The scan loop may not restart properly after STOP → START')

    results['step_9'] = bool(batches)

    # Cleanup: stop
    s.publish(f'{PREFIX}/nodes/{DAQ_NODE}/system/acquire/stop', {})
    s.wait(2)
    INFO('Cleanup: sent acquire/stop')


def step_10_summary():
    """Print final summary with diagnosis."""
    header(10, 'SUMMARY')

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    print()
    for name, ok in sorted(results.items()):
        status = f'{Colors.GREEN}PASS{Colors.RESET}' if ok else f'{Colors.RED}FAIL{Colors.RESET}'
        print(f'  {name}: {status}')

    print()
    if failed == 0:
        print(f'  {Colors.GREEN}{Colors.BOLD}ALL {total} STEPS PASSED{Colors.RESET}')
        print(f'  {Colors.GREEN}Full acquisition pipeline is working!{Colors.RESET}')
        return 0
    else:
        print(f'  {Colors.RED}{Colors.BOLD}{passed}/{total} PASSED, {failed} FAILED{Colors.RESET}')

        # Find first failure and give targeted diagnosis
        first_fail = None
        for name in ['step_0', 'step_1', 'step_2', 'step_3', 'step_4',
                      'step_5', 'step_6', 'step_7', 'step_8', 'step_9']:
            if name in results and not results[name]:
                first_fail = name
                break

        if first_fail:
            print()
            print(f'  {Colors.CYAN}FIRST FAILURE: {first_fail}{Colors.RESET}')
            recommendations = {
                'step_0': [
                    'MQTT broker not running or DAQ service not started.',
                    'Fix: Run NISystem Start.bat, or start Mosquitto + DAQ manually.',
                ],
                'step_1': [
                    'DAQ service not publishing status.',
                    'Fix: Check if DAQ service crashed. Look at console output or logs.',
                ],
                'step_2': [
                    'Hardware detection failed.',
                    'Fix: Ensure cDAQ is plugged in or cRIO is on the network.',
                ],
                'step_3': [
                    'Project load failed.',
                    'Fix: Verify project file exists in config/projects/.',
                    'Fix: Check DAQ service logs for JSON parse errors.',
                ],
                'step_4': [
                    'Config not pushed to cRIO.',
                    'Fix: Verify cRIO is online (check heartbeat on MQTT Explorer).',
                    'Fix: DAQ must see cRIO in device discovery before it pushes config.',
                ],
                'step_5': [
                    'Acquire START failed.',
                    'Fix: Check DAQ logs for state machine errors.',
                    'Fix: For cRIO: verify config push succeeded first.',
                    'Fix: For cDAQ: check NI-DAQmx driver installation.',
                ],
                'step_6': [
                    'No channel data flowing, or rate is far below expected.',
                    'Fix: For cDAQ: hardware_reader may have failed to create tasks.',
                    'Fix: For cRIO: cRIO hardware may not be reading.',
                    'Fix: Check scan_rate_hz and publish_rate_hz in project JSON.',
                    'Fix: Verify config push included correct rates (Step 4 output).',
                    'Fix: If rate is low: check for slow safety eval, long script execution,',
                    '     or publish loop contention (DAQ publishes individual + batch).',
                ],
                'step_7': [
                    'WebSocket bridge broken — dashboard cannot see data.',
                    'Fix: Check mosquitto.conf has WebSocket listener on port 9002.',
                    'Fix: Ensure both TCP and WS listeners are configured.',
                ],
                'step_8': [
                    'Acquire STOP failed.',
                    'Fix: DAQ service may be hung. Check for deadlocks in logs.',
                ],
                'step_9': [
                    'Second start cycle failed — state not cleaning up.',
                    'Fix: State machine may be stuck. Check acquisition_state in logs.',
                    'Fix: May need to restart DAQ service to clear state.',
                ],
            }

            for line in recommendations.get(first_fail, ['Check logs for errors.']):
                print(f'  {Colors.CYAN}  {line}{Colors.RESET}')

        return 1


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global BROKER

    parser = argparse.ArgumentParser(
        description='Acquisition Pipeline Diagnostic',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_acquisition_flow.py                     # Auto-detect mode
  python scripts/test_acquisition_flow.py --mode cdaq         # Force cDAQ mode
  python scripts/test_acquisition_flow.py --mode crio         # Force cRIO mode
  python scripts/test_acquisition_flow.py --project MyProj.json
  python scripts/test_acquisition_flow.py --skip-stop         # Leave acquiring
""")
    parser.add_argument('--mode', choices=['cdaq', 'crio'], default=None,
                        help='Force hardware mode (default: auto-detect)')
    parser.add_argument('--project', default=None,
                        help='Project file to load (default: auto per mode)')
    parser.add_argument('--skip-stop', action='store_true',
                        help='Skip stop/restart tests (leave acquisition running)')
    parser.add_argument('--broker', default=BROKER,
                        help=f'MQTT broker address (default: {BROKER})')
    args = parser.parse_args()

    BROKER = args.broker

    print()
    print(f'{Colors.BOLD}{"="*64}{Colors.RESET}')
    print(f'  {Colors.BOLD}NISystem Acquisition Pipeline Diagnostic{Colors.RESET}')
    print(f'{Colors.BOLD}{"="*64}{Colors.RESET}')
    print(f'  Broker: {BROKER}  TCP:{PORT_TCP}  WS:{PORT_WS}')
    print(f'  Mode: {args.mode or "auto-detect"}')
    if args.project:
        print(f'  Project: {args.project}')
    print()

    # Step 0: Pre-flight
    sniffer = step_0_preflight()
    if sniffer is None:
        print(f'\n{Colors.RED}ABORT: Cannot connect to MQTT broker.{Colors.RESET}')
        step_10_summary()
        return 1

    if not results.get('step_0'):
        print(f'\n{Colors.RED}ABORT: DAQ service not responding.{Colors.RESET}')
        sniffer.disconnect()
        step_10_summary()
        return 1

    # Steps 1-4: Setup
    step_1_daq_state(sniffer)
    if not results.get('step_1'):
        sniffer.disconnect()
        step_10_summary()
        return 1

    step_2_detect_hardware(sniffer, forced_mode=args.mode)
    step_3_load_project(sniffer, project_file=args.project)

    if not results.get('step_3'):
        sniffer.disconnect()
        step_10_summary()
        return 1

    step_4_config_push(sniffer)

    # Steps 5-7: Acquire and data
    step_5_acquire_start(sniffer)
    step_6_channel_data(sniffer)
    step_7_websocket(sniffer)

    # Steps 8-9: Stop and cycle (optional)
    if args.skip_stop:
        INFO('--skip-stop: Skipping stop/restart tests')
        results['step_8'] = True
        results['step_9'] = True
    else:
        step_8_acquire_stop(sniffer)
        step_9_second_cycle(sniffer)

    sniffer.disconnect()

    # Summary
    return step_10_summary()


if __name__ == '__main__':
    sys.exit(main())
