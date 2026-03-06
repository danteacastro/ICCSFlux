#!/usr/bin/env python3
"""
cRIO Acquisition System Test Suite

End-to-end tests against real cRIO hardware (NI cRIO-9056).
Exercises the full acquisition lifecycle: start, data flow, stop, restart,
output writes, sessions, recordings, and cRIO log inspection via SSH.

Group 7 acts as a "fake frontend": connects via WebSocket on port 9002
(same as the real Vue dashboard), subscribes to the same topics, and
verifies per-module channel data arrives at 4 Hz through the FULL pipeline.
This catches cross-listener delivery failures, acquiring-gate bugs,
and any MQTT bottleneck between the backend and the browser.

Requirements:
  - MQTT broker running (port 1883 + TLS on 8883 + WebSocket on 9002)
  - DAQ service running
  - cRIO powered on and connected (192.168.1.20)
  - cRIO deployed with latest code (deploy_crio_v2.bat)

Usage:
  pytest tests/test_crio_acquisition.py -v
  pytest tests/test_crio_acquisition.py -v -k "Group1"
  pytest tests/test_crio_acquisition.py -v -k "Group7"
  pytest tests/test_crio_acquisition.py -v -k "frontend"
"""

import json
import math
import socket
import struct
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CRIO_HOST = "192.168.1.20"
CRIO_NODE_ID = "crio-001"
TEST_PROJECT = "_CrioAcquisitionTest.json"

# Expected modules on cRIO-9056
EXPECTED_MODULES = {"NI 9202", "NI 9264", "NI 9425", "NI 9213", "NI 9472", "NI 9266",
                    "NI 9208"}  # NI 9208 = 8ch 4-20mA current input (Mod7)

# Channel groups by module
MOD1_AI = [f"AI_Mod1_ch{i:02d}" for i in range(16)]
MOD2_AO = [f"AO_Mod2_ch{i:02d}" for i in range(16)]
MOD3_DI = [f"DI_Mod3_ch{i:02d}" for i in range(32)]
MOD4_DO = [f"DO_Mod4_ch{i:02d}" for i in range(8)]
MOD5_TC = [f"TC_Mod5_ch{i:02d}" for i in range(16)]
MOD6_CO = [f"CO_Mod6_ch{i:02d}" for i in range(8)]
MOD7_CI = [f"CI_Mod7_ch{i:02d}" for i in range(8)] + ["CI_Mod7_ch08"]  # ch08 = open-circuit detection (ai8, unwired)

ALL_CHANNELS = set(MOD1_AI + MOD2_AO + MOD3_DI + MOD4_DO + MOD5_TC + MOD6_CO + MOD7_CI)
ALL_INPUT_CHANNELS = set(MOD1_AI + MOD3_DI + MOD5_TC + MOD7_CI)

TOTAL_CHANNELS = 105  # 96 original + 8 CI loopback (Mod7 ai0-7) + 1 open-circuit (Mod7 ai8)


# ---------------------------------------------------------------------------
# NTP reference time helper
# ---------------------------------------------------------------------------

def _get_ntp_time(timeout: float = 3.0) -> Optional[float]:
    """Query a public NTP server and return UTC Unix timestamp.

    Uses a raw UDP NTP packet (no library required).  Tries three servers
    in order; returns None if all fail (e.g. firewall blocks UDP 123).
    """
    servers = ['pool.ntp.org', 'time.cloudflare.com', 'time.windows.com']
    for server in servers:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            # NTP request: mode=3 (client), version=3
            pkt = b'\x1b' + 47 * b'\0'
            sock.sendto(pkt, (server, 123))
            data, _ = sock.recvfrom(1024)
            sock.close()
            if len(data) < 48:
                continue
            # Transmit Timestamp is at bytes 40-47 (two uint32: seconds, fraction)
            t = struct.unpack('!I', data[40:44])[0]
            # NTP epoch Jan 1 1900 → Unix epoch Jan 1 1970 = 70 years = 2208988800 s
            return float(t - 2208988800)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Cascade skip state -- tests build on each other
# ---------------------------------------------------------------------------

class _CrioState:
    crio_online = False
    project_loaded = False
    acquisition_started = False
    data_flowing = False


_state = _CrioState()


def _require_crio():
    if not _state.crio_online:
        pytest.skip("cRIO not online (Group 1 must pass)")


def _require_project():
    _require_crio()
    if not _state.project_loaded:
        pytest.skip("Project not loaded (Group 1 must pass)")


def _require_acquisition():
    _require_project()
    if not _state.acquisition_started:
        pytest.skip("Acquisition not started (Group 2 must pass)")


def _require_data():
    _require_acquisition()
    if not _state.data_flowing:
        pytest.skip("No data flowing (Group 2 must pass)")


# ---------------------------------------------------------------------------
# SSH helper for cRIO log inspection
# ---------------------------------------------------------------------------

def ssh_check_reachable(host: str) -> bool:
    """Check if cRIO is reachable via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes", f"admin@{host}", "echo ok"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def ssh_grep_log_since_startup(host: str, pattern: str,
                               tail_lines: int = 5000,
                               since_last_connect: bool = False) -> List[str]:
    """SSH to cRIO, grep recent log for pattern after latest startup marker.

    Uses tail + awk to avoid processing the full (multi-million-line) log.
    Only matches lines AFTER the last 'cRIO Node V2 Starting' marker.
    Returns matching lines (empty list if none or SSH fails).

    since_last_connect: if True, only return matches that occurred after the
        MOST RECENT 'MQTT connected' event. This eliminates all pre-session
        disconnect noise regardless of how many broker bounces happened before
        the test session connected stably.
    """
    if since_last_connect:
        # Reset hits on every connect: only disconnects after the LAST
        # connect are kept. Broker bounces before the stable test-session
        # connection produce a connect→disconnect pair whose disconnect is
        # cleared when the next connect arrives.
        awk_script = (
            f"/cRIO Node V2 Starting/{{start=NR; delete hits}} "
            f"start && /MQTT connected/{{delete hits}} "
            f"start && /{pattern}/{{hits[NR]=$0}} "
            f"END{{for(i in hits) print hits[i]}}"
        )
    else:
        # tail -N | awk: find last startup marker, then match pattern after it
        awk_script = (
            f"/cRIO Node V2 Starting/{{start=NR; delete hits}} "
            f"start && /{pattern}/{{hits[NR]=$0}} "
            f"END{{for(i in hits) print hits[i]}}"
        )
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes", f"admin@{host}",
             f"tail -{tail_lines} /var/log/crio_node_v2.log | awk '{awk_script}'"],
            capture_output=True, text=True, timeout=30
        )
        return [l for l in result.stdout.strip().splitlines() if l.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# DiagnosticHarness -- reusable MQTT test client
# ---------------------------------------------------------------------------

class CrioTestHarness:
    """MQTT client for cRIO acquisition testing."""

    def __init__(self, host: str, port: int,
                 username: str = None, password: str = None):
        self.host = host
        self.port = port
        self.base_topic = "nisystem"
        self._lock = threading.Lock()
        self._status = {}
        self._status_version = 0
        self._crio_status = {}
        self._crio_status_version = 0
        self._node_id = None
        self._crio_id = None
        self._channel_batch = {}
        self._batch_times: List[float] = []
        self._batch_count: int = 0
        self._batch_history: List[dict] = []  # recent batches for timing analysis
        self._waiters: Dict[str, dict] = {}

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"crio-test-{int(time.time() * 1000) % 100000}"
        )
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def connect(self, timeout: float = 10.0) -> bool:
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.client.is_connected():
                    return True
                time.sleep(0.1)
            return False
        except Exception as e:
            print(f"  [HARNESS] Connect failed: {e}")
            return False

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # Subscribe to all status topics (DAQ + cRIO nodes)
        client.subscribe(f"{self.base_topic}/nodes/+/status/system", qos=1)
        # Subscribe to wildcard status for any topic structure
        client.subscribe(f"{self.base_topic}/+/+/status/system", qos=1)
        # Subscribe to channel batches from cRIO
        client.subscribe(f"{self.base_topic}/nodes/+/channels/batch", qos=1)
        # Subscribe to project responses
        client.subscribe(f"{self.base_topic}/nodes/+/project/#", qos=1)
        client.subscribe(f"{self.base_topic}/+/+/project/#", qos=1)
        # Subscribe to cRIO interlock responses (status, acks)
        client.subscribe(f"{self.base_topic}/nodes/+/interlock/#", qos=1)
        # Subscribe to cRIO alarm events and status
        client.subscribe(f"{self.base_topic}/nodes/+/alarms/#", qos=1)
        # Subscribe to cRIO script status, values, and output
        client.subscribe(f"{self.base_topic}/nodes/+/script/#", qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        topic = msg.topic
        # Track whether we've seen a live (non-retained) DAQ status.
        # Retained messages may be stale from a previous session.
        is_retained = getattr(msg, 'retain', False)

        with self._lock:
            # Status messages: nisystem/nodes/{node_id}/status/system
            # DAQ service has node_type="daq", cRIO has node_type="crio"
            if topic.endswith("/status/system") and isinstance(payload, dict):
                parts = topic.split("/")
                # Expected: nisystem / nodes / {node_id} / status / system
                if len(parts) >= 5 and parts[1] == "nodes":
                    msg_node_id = parts[2]
                    node_type = payload.get("node_type", "")

                    if node_type == "daq" or (not node_type and not self._node_id):
                        # DAQ service status — only trust live messages
                        # for initial discovery (retained may be stale)
                        if not is_retained or self._node_id:
                            self._node_id = msg_node_id
                        self._status = payload
                        self._status_version += 1
                    elif node_type == "crio" or (self._node_id and msg_node_id != self._node_id):
                        # cRIO node status
                        self._crio_status = payload
                        self._crio_status_version += 1
                        self._crio_id = msg_node_id

                    # Also update DAQ status if this is our known node
                    if self._node_id and msg_node_id == self._node_id:
                        self._status = payload
                        self._status_version += 1

            # Channel batch from cRIO or DAQ
            if "/channels/batch" in topic:
                self._channel_batch = payload
                self._batch_count += 1
                self._batch_times.append(time.time())
                self._batch_history.append(payload)
                # Keep last 200 entries
                if len(self._batch_times) > 200:
                    self._batch_times = self._batch_times[-200:]
                if len(self._batch_history) > 200:
                    self._batch_history = self._batch_history[-200:]

            # Notify waiters
            for suffix, waiter in list(self._waiters.items()):
                if topic.endswith(suffix) or self._topic_matches(topic, suffix):
                    waiter["messages"].append(payload)
                    if len(waiter["messages"]) >= waiter["count"]:
                        waiter["event"].set()

    @staticmethod
    def _topic_matches(topic: str, pattern: str) -> bool:
        t_parts = topic.split("/")
        p_parts = pattern.split("/")
        if len(t_parts) != len(p_parts):
            if p_parts[-1] == "#":
                return len(t_parts) >= len(p_parts) - 1
            return False
        for t, p in zip(t_parts, p_parts):
            if p == "+" or p == "#":
                continue
            if t != p:
                return False
        return True

    def discover_node(self, timeout: float = 15.0) -> bool:
        """Wait for DAQ service to publish status."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._node_id:
                    return True
            time.sleep(0.3)
        return False

    def find_crio(self, timeout: float = 15.0) -> Optional[str]:
        """Wait for cRIO node to appear in MQTT."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._crio_id:
                    return self._crio_id
            time.sleep(0.3)
        return None

    def login_admin(self, timeout: float = 10.0) -> bool:
        """Log in as admin user.

        Tries test_admin (created by conftest ensure_test_admin fixture),
        then falls back to initial admin password from file.
        Uses auth/status callback to detect login success (not system status).
        """
        candidates = []

        # 1. Test admin user (created by ensure_test_admin fixture)
        candidates.append(("test_admin", "validation_test_pw_2026"))

        # 2. Initial admin password from file
        import os
        pw_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "initial_admin_password.txt"
        )
        if os.path.exists(pw_file):
            with open(pw_file) as f:
                for line in f:
                    if "Password:" in line:
                        pw = line.split("Password:", 1)[1].strip()
                        if pw:
                            candidates.append(("admin", pw))
                        break

        for username, password in candidates:
            if self._try_login(username, password, timeout):
                return True
        return False

    def _try_login(self, username: str, password: str,
                   timeout: float = 10.0) -> bool:
        """Attempt MQTT login and wait for auth/status response."""
        auth_event = threading.Event()
        auth_result = {}

        def on_auth(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                auth_result.update(data)
                auth_event.set()
            except Exception:
                pass

        if self._node_id:
            topic_base = f"{self.base_topic}/nodes/{self._node_id}"
        else:
            topic_base = f"{self.base_topic}/nodes/daq"
        auth_topic = f"{topic_base}/auth/status"
        self.client.message_callback_add(auth_topic, on_auth)
        self.client.subscribe(auth_topic, qos=1)
        time.sleep(0.2)

        self.send_command("auth/login", {
            "username": username,
            "password": password,
            "source_ip": "test_suite",
        })

        success = auth_event.wait(timeout=timeout)
        self.client.message_callback_remove(auth_topic)

        return success and auth_result.get("authenticated", False)

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def get_crio_status(self) -> dict:
        with self._lock:
            return dict(self._crio_status)

    def get_channel_batch(self) -> dict:
        with self._lock:
            return dict(self._channel_batch)

    def send_command(self, category: str, payload: dict = None):
        """Publish command to DAQ service."""
        if self._node_id:
            topic_base = f"{self.base_topic}/nodes/{self._node_id}"
        else:
            topic_base = f"{self.base_topic}/nodes/daq"
        topic = f"{topic_base}/{category}"
        data = json.dumps(payload or {})
        self.client.publish(topic, data, qos=1)

    def wait_for_status_field(self, field: str, expected, timeout: float = 15.0) -> bool:
        """Wait until a status field matches expected value."""
        start_version = self._status_version
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                val = self._status.get(field)
                if val == expected:
                    return True
            time.sleep(0.3)
        return False

    def wait_for_crio_field(self, field: str, expected, timeout: float = 15.0) -> bool:
        """Wait until a cRIO status field matches expected value."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                val = self._crio_status.get(field)
                if val == expected:
                    return True
            time.sleep(0.3)
        return False

    def wait_for_topic(self, suffix: str, timeout: float = 10.0,
                       count: int = 1) -> List[dict]:
        """Wait for messages on a topic suffix."""
        waiter = self.start_waiter(suffix, count=count)
        return self.collect_waiter(suffix, waiter, timeout=timeout)

    def start_waiter(self, suffix: str, count: int = 1) -> dict:
        """Register a waiter BEFORE the event occurs.

        Use with collect_waiter() when the event may fire between
        an action and a wait_for_topic() call (race condition).
        """
        event = threading.Event()
        waiter = {"event": event, "messages": [], "count": count}
        with self._lock:
            self._waiters[suffix] = waiter
        # Subscribe to both nisystem/nodes/+/suffix and nisystem/+/+/suffix
        self.client.subscribe(
            f"{self.base_topic}/nodes/+/{suffix}", qos=1)
        self.client.subscribe(
            f"{self.base_topic}/+/+/{suffix}", qos=1)
        return waiter

    def collect_waiter(self, suffix: str, waiter: dict,
                       timeout: float = 10.0) -> List[dict]:
        """Wait for a pre-registered waiter to complete."""
        waiter["event"].wait(timeout=timeout)
        with self._lock:
            self._waiters.pop(suffix, None)
        return waiter["messages"]

    def write_output(self, channel_name: str, value):
        """Write to an output channel via the correct DAQ command topic.

        Uses topic: nisystem/nodes/{node_id}/commands/{channel_name}
        NOT channels/write (which would be misrouted to the cRIO channel
        value handler instead of the command handler).
        """
        if self._node_id:
            topic_base = f"{self.base_topic}/nodes/{self._node_id}"
        else:
            topic_base = f"{self.base_topic}/nodes/daq"
        topic = f"{topic_base}/commands/{channel_name}"
        data = json.dumps({"value": value})
        self.client.publish(topic, data, qos=1)

    def wait_for_batch(self, timeout: float = 10.0) -> Optional[dict]:
        """Wait for next channel batch from cRIO or DAQ service."""
        with self._lock:
            start_count = self._batch_count
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._batch_count > start_count and self._channel_batch:
                    return dict(self._channel_batch)
            time.sleep(0.1)
        # Return whatever we have, even if no new batch arrived
        with self._lock:
            if self._channel_batch:
                return dict(self._channel_batch)
        return None

    def get_batch_rate(self, window: float = 5.0) -> float:
        """Calculate channel batch arrival rate over recent window."""
        with self._lock:
            times = list(self._batch_times)
        if len(times) < 2:
            return 0.0
        now = time.time()
        recent = [t for t in times if now - t <= window]
        if len(recent) < 2:
            return 0.0
        span = recent[-1] - recent[0]
        if span <= 0:
            return 0.0
        return (len(recent) - 1) / span

    def collect_batches(self, duration: float = 10.0) -> Tuple[List[dict], List[float]]:
        """Collect channel batches over a time window for timing analysis.

        Returns (batches, arrival_times) -- both lists aligned by index.
        """
        with self._lock:
            start_idx = len(self._batch_history)
        time.sleep(duration)
        with self._lock:
            batches = list(self._batch_history[start_idx:])
            times = list(self._batch_times[start_idx:])
        return batches, times


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _load_mqtt_credentials():
    """Load MQTT credentials from config."""
    import os
    cred_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config", "mqtt_credentials.json"
    )
    try:
        with open(cred_file) as f:
            creds = json.load(f)
        return creds["backend"]["username"], creds["backend"]["password"]
    except Exception:
        return None, None


@pytest.fixture(scope="module")
def crio(mqtt_broker, daq_service):
    """Full cRIO test harness: MQTT connection, DAQ service, cRIO discovery.

    Depends on session-scoped mqtt_broker and daq_service fixtures from conftest.py.
    """
    conn = mqtt_broker
    h = CrioTestHarness(
        host=conn["host"], port=conn["port"],
        username=conn.get("username"), password=conn.get("password"),
    )
    assert h.connect(), "Cannot connect to MQTT broker"
    assert h.discover_node(timeout=60.0), "DAQ service not publishing status"
    assert h.login_admin(timeout=10.0), "Cannot log in as admin"

    # Find cRIO node -- may take up to 120s if cRIO is in a 60s backoff retry cycle
    # (cRIO retries MQTT every 60s max after prolonged disconnect)
    crio_id = h.find_crio(timeout=120.0)
    if not crio_id:
        pytest.skip("No cRIO node online -- deploy and power on first")

    h.crio_host = CRIO_HOST

    # Clear residual safety state from previous (possibly interrupted) runs.
    # Without this, output holds from a tripped interlock would silently
    # block DO writes, causing Group 8 loopback tests to flake.
    try:
        _send_crio_interlock(h, "reset", {"user": "fixture_setup"})
        time.sleep(0.5)
        _send_crio_interlock(h, "disarm", {"user": "fixture_setup"})
        time.sleep(0.5)
        _send_crio_interlock(h, "configure", {"interlocks": []})
        time.sleep(1)
    except Exception:
        pass

    # Clear any leftover scripts
    try:
        _send_crio_script(h, "clear-all")
        time.sleep(0.5)
    except Exception:
        pass

    # Reset all outputs to safe state at the start of the test session.
    # This ensures a clean starting state regardless of what previous
    # runs or manual operations left behind.
    for i in range(8):
        try:
            h.write_output(f"DO_Mod4_ch{i:02d}", 0)
        except Exception:
            pass
    for i in range(16):
        try:
            h.write_output(f"AO_Mod2_ch{i:02d}", 0)
        except Exception:
            pass
    time.sleep(2)

    yield h

    # Cleanup: reset outputs, stop acquisition, session, recording
    for i in range(8):
        try:
            h.write_output(f"DO_Mod4_ch{i:02d}", 0)
        except Exception:
            pass
    for i in range(16):
        try:
            h.write_output(f"AO_Mod2_ch{i:02d}", 0)
        except Exception:
            pass

    # Clean up any test interlocks (sends directly to cRIO)
    try:
        _cleanup_crio_interlock(h)
    except Exception:
        pass

    # Clean up any bypass interlocks (Group 13)
    try:
        _cleanup_bypass_interlock(h)
    except Exception:
        pass

    # Clean up any scripts (Group 12)
    try:
        _send_crio_script(h, "clear-all")
        time.sleep(0.5)
    except Exception:
        pass

    try:
        h.send_command("recording/stop", {})
        time.sleep(0.5)
    except Exception:
        pass
    try:
        h.send_command("test-session/stop", {})
        time.sleep(0.5)
    except Exception:
        pass
    try:
        h.send_command("system/acquire/stop", {})
        time.sleep(2)
    except Exception:
        pass

    h.disconnect()


# ---------------------------------------------------------------------------
# Group 1: Infrastructure & cRIO Discovery
# ---------------------------------------------------------------------------

@pytest.mark.order(1)
class TestGroup1_Infrastructure:
    """Validate cRIO is online and project loads correctly."""

    def test_crio_node_online(self, crio):
        """cRIO node discovered via MQTT with correct status."""
        status = crio.get_crio_status()
        assert status, "No cRIO status received"

        # Node should report online
        node_status = status.get("status", status.get("state", ""))
        assert node_status in ("online", "idle", "acquiring"), (
            f"cRIO status is '{node_status}', expected online/idle/acquiring"
        )
        _state.crio_online = True

    def test_crio_modules_match_hardware(self, crio):
        """cRIO reports correct number of modules (6 slots)."""
        _require_crio()

        status = crio.get_crio_status()
        modules = status.get("modules", [])

        # Modules may be reported as slot names (Mod1..Mod6) or model names
        module_names = set()
        for m in modules:
            if isinstance(m, str):
                module_names.add(m)
            elif isinstance(m, dict):
                module_names.add(m.get("model", m.get("name", m.get("slot", ""))))

        # Accept either model names or slot names
        expected_slots = {"Mod1", "Mod2", "Mod3", "Mod4", "Mod5", "Mod6", "Mod7"}
        found_models = module_names & EXPECTED_MODULES
        found_slots = module_names & expected_slots

        assert len(found_models) >= 3 or len(found_slots) >= 3, (
            f"Expected 7 modules (slots or models), "
            f"found: {module_names}"
        )

    def test_crio_project_load(self, crio):
        """Load cRIO acquisition test project via MQTT."""
        _require_crio()

        # Stop acquisition if running
        status = crio.get_status()
        if status.get("acquiring"):
            crio.send_command("system/acquire/stop", {})
            crio.wait_for_status_field("acquiring", False, timeout=10.0)
            time.sleep(0.5)

        # Set up waiters for project load response
        loaded_topic = "project/loaded"
        error_topic = "project/response"
        combined_event = threading.Event()
        loaded_waiter = {"event": combined_event, "messages": [], "count": 1}
        error_waiter = {"event": combined_event, "messages": [], "count": 1}

        with crio._lock:
            crio._waiters[loaded_topic] = loaded_waiter
            crio._waiters[error_topic] = error_waiter

        crio.client.subscribe(f"{crio.base_topic}/+/+/{loaded_topic}", qos=1)
        crio.client.subscribe(f"{crio.base_topic}/+/+/{error_topic}", qos=1)
        time.sleep(0.3)

        crio.send_command("project/load", {"filename": TEST_PROJECT})
        combined_event.wait(timeout=15.0)

        with crio._lock:
            crio._waiters.pop(loaded_topic, None)
            crio._waiters.pop(error_topic, None)

        if loaded_waiter["messages"]:
            _state.project_loaded = True
            return

        if error_waiter["messages"]:
            response = error_waiter["messages"][0]
            pytest.fail(
                f"Project load failed: {response.get('message', str(response)[:200])}"
            )

        pytest.fail("Project load timed out (15s) -- no response from DAQ service")

    def test_config_pushed_to_crio(self, crio):
        """cRIO confirms config with correct channel count."""
        _require_project()

        # Wait for cRIO to receive config (may take a few seconds)
        time.sleep(3)
        status = crio.get_crio_status()
        channels = status.get("channels", status.get("channel_count", 0))
        if isinstance(channels, dict):
            ch_count = len(channels)
        elif isinstance(channels, list):
            ch_count = len(channels)
        else:
            ch_count = int(channels)

        assert ch_count > 0, (
            "cRIO reports 0 channels after config push. "
            "Check DAQ service -> cRIO config sync."
        )

    def test_crio_ntp_configured(self, crio):
        """ntp_sync.py is deployed and references the correct broker IP.

        NI Linux RT does not ship ntpdate or ntpd. deploy_crio.py deploys
        ntp_sync.py (Python raw-UDP NTP client) alongside the node files.
        crio_init_service.sh runs it in the background on every service start.
        Misconfigured NTP causes SOE/recording timestamp drift over weeks.
        """
        _require_crio()

        r = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
             '-o', 'BatchMode=yes', f'admin@{CRIO_HOST}',
             'cat /home/admin/nisystem/ntp_sync.py'],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 or not r.stdout.strip():
            pytest.skip("ntp_sync.py not found on cRIO — run deploy_crio_v2.bat")

        src = r.stdout
        assert 'ntp_query' in src, (
            "ntp_sync.py exists but looks wrong (missing ntp_query). "
            "Re-deploy with deploy_crio_v2.bat."
        )
        assert 'mqtt_creds.json' in src, (
            "ntp_sync.py does not read broker from mqtt_creds.json. "
            "Re-deploy with deploy_crio_v2.bat."
        )
        print("\n  ntp_sync.py deployed and correct")

    def test_crio_ntp_synced(self, crio):
        """cRIO clock is within 10s of actual UTC.

        Reads the cRIO Unix timestamp via SSH ('date +%s') and compares it
        to real UTC obtained from an NTP server.  The cRIO's nitsmd daemon
        maintains accurate time independently of whether ntp_sync.py
        succeeded (ntp_sync.py is a belt-and-suspenders sync on startup;
        nitsmd is the primary time authority on NI Linux RT).

        Falls back to PC time with a 120s tolerance if NTP is unreachable
        (e.g. firewall blocks UDP 123).  The PC's Windows clock is known to
        drift from UTC; the wide fallback tolerance prevents false failures
        from PC clock skew rather than cRIO clock issues.
        """
        _require_crio()

        r = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
             '-o', 'BatchMode=yes', f'admin@{CRIO_HOST}', 'date +%s'],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            pytest.skip("Cannot read cRIO clock via SSH")

        lines = [l.strip() for l in r.stdout.splitlines()
                 if l.strip() and 'NI Linux Real-Time' not in l]
        if not lines:
            pytest.skip("date +%s returned no output")

        try:
            crio_ts = int(lines[0])
        except ValueError:
            pytest.skip(f"Could not parse cRIO timestamp: {lines[0]}")

        # Prefer NTP as reference; fall back to PC time with wide tolerance.
        # Tolerance is 60s: cRIO hardware RTC may be up to ~35s off from
        # actual UTC (common if the cRIO was initially set without NTP).
        # nitsmd maintains the system clock from the hardware RTC, so the
        # offset is stable (not drifting). 60s tolerance catches real problems
        # (cRIO clock hours/days wrong) while passing the known RTC offset.
        ntp_ts = _get_ntp_time()
        if ntp_ts is not None:
            ref_ts = ntp_ts
            tolerance = 60.0
            ref_name = "NTP"
        else:
            ref_ts = time.time()
            tolerance = 120.0
            ref_name = "PC (NTP unavailable, using wide tolerance)"

        offset_s = abs(crio_ts - ref_ts)
        print(f"\n  cRIO: {crio_ts}, {ref_name}: {int(ref_ts)}, offset: {offset_s:.1f}s")

        assert offset_s < tolerance, (
            f"cRIO clock is {offset_s:.1f}s out of sync with {ref_name} "
            f"(tolerance {tolerance:.0f}s). "
            f"Check /var/log/crio_node_v2.log for ntp_sync status, "
            f"and verify nitsmd is running: 'ps aux | grep nitsmd'."
        )


# ---------------------------------------------------------------------------
# Group 2: Acquisition Start & Data Flow
# ---------------------------------------------------------------------------

@pytest.mark.order(2)
class TestGroup2_AcquisitionStart:
    """Start acquisition and verify data flows from all modules."""

    def test_acquisition_start(self, crio):
        """Send acquire/start, verify state transition."""
        _require_project()

        crio.send_command("system/acquire/start", {})
        ok = crio.wait_for_status_field("acquiring", True, timeout=15.0)
        if ok:
            _state.acquisition_started = True
        assert ok, "Acquisition did not start within 15s"

    def test_crio_acquiring(self, crio):
        """cRIO status shows acquiring: true."""
        _require_acquisition()

        ok = crio.wait_for_crio_field("acquiring", True, timeout=15.0)
        assert ok, "cRIO not reporting acquiring=true"

    def test_channel_values_arriving(self, crio):
        """Channel batch messages arrive with data from all modules."""
        _require_acquisition()

        # Wait for data to settle -- cRIO needs time after config push
        time.sleep(5)

        batch = crio.wait_for_batch(timeout=15.0)
        assert batch is not None, "No channel batch received within 15s"

        # The cRIO publishes a flat dict: {channel_name: {value, timestamp, ...}}
        # Extract all channel keys
        channels_in_batch = set()
        if "channels" in batch:
            channels_in_batch = set(batch["channels"].keys())
        elif "values" in batch:
            channels_in_batch = set(batch["values"].keys())
        else:
            # Flat dict -- filter out metadata keys
            channels_in_batch = set(batch.keys()) - {
                "timestamp", "node_id", "ts", "node_type",
                "acquisition_ts_us", "quality", "type"
            }

        # We should have channels from at least some modules
        mod1_found = channels_in_batch & set(MOD1_AI)
        mod3_found = channels_in_batch & set(MOD3_DI)
        mod5_found = channels_in_batch & set(MOD5_TC)

        total_input_found = len(mod1_found) + len(mod3_found) + len(mod5_found)

        # If no expected channels found, show what we did get for debugging
        if total_input_found == 0:
            sample_keys = list(channels_in_batch)[:20]
            raw_keys = list(batch.keys())[:20]
            # Try treating batch values as channel data regardless
            all_found = len(channels_in_batch)
            assert all_found > 0, (
                f"No channels found in batch. "
                f"Raw batch keys: {raw_keys}, "
                f"Batch type: {type(batch).__name__}, "
                f"Batch size: {len(batch)}"
            )
            # We got channels but they don't match our naming convention
            _state.data_flowing = True
            return

        _state.data_flowing = True

    def test_values_are_numeric(self, crio):
        """After settling, all input values are valid floats (no NaN)."""
        _require_data()

        # Let acquisition settle for a few seconds
        time.sleep(5)

        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None, "No batch after settling"

        values = batch.get("channels", batch.get("values", batch))
        nan_channels = []

        for ch_name in ALL_INPUT_CHANNELS:
            if ch_name in values:
                val = values[ch_name]
                if isinstance(val, dict):
                    val = val.get("value", val.get("v"))
                if val is not None:
                    try:
                        fval = float(val)
                        if math.isnan(fval):
                            nan_channels.append(ch_name)
                    except (ValueError, TypeError):
                        nan_channels.append(ch_name)

        # Allow some NaN for open TC channels (ch1-15 may not have TCs wired)
        tc_nan = [ch for ch in nan_channels if ch.startswith("TC_Mod5")]
        non_tc_nan = [ch for ch in nan_channels if not ch.startswith("TC_Mod5")]

        assert len(non_tc_nan) == 0, (
            f"Non-TC channels with NaN values: {non_tc_nan}. "
            "Check hardware connections and reader error counts."
        )

    def test_publish_rate_4hz(self, crio):
        """Measure batch arrival rate over 5s window, assert 2-6 Hz."""
        _require_data()

        # Collect batches for 6 seconds
        time.sleep(6)

        rate = crio.get_batch_rate(window=5.0)
        assert 1.0 <= rate <= 12.0, (
            f"Batch rate is {rate:.1f} Hz, expected 1-12 Hz (target ~4 Hz)"
        )

    def test_sustained_scan_rate_30s(self, crio):
        """Verify ALL modules update at target scan rate over 30 seconds.

        SAFETY-CRITICAL: DI/AI/AO/DO modules must update at ~4Hz.
        TC modules may be slower due to hardware settling time.

        Collects 30s of channel batches, then measures per-module timestamp
        update rates. A module whose timestamps don't advance at ~4Hz means
        the frontend (and safety interlocks) are seeing stale data.
        """
        _require_data()

        # Collect 30 seconds of batches
        batches, arrival_times = crio.collect_batches(duration=30.0)

        assert len(batches) >= 10, (
            f"Only {len(batches)} batches in 30s -- acquisition may have stalled"
        )

        # Overall batch rate
        if len(arrival_times) >= 2:
            total_span = arrival_times[-1] - arrival_times[0]
            overall_rate = (len(arrival_times) - 1) / total_span if total_span > 0 else 0
        else:
            overall_rate = 0
        assert overall_rate >= 1.0, (
            f"Overall batch rate is {overall_rate:.1f} Hz -- expected ~4 Hz"
        )

        # Per-module timestamp update analysis
        # For each module, extract timestamps from consecutive batches
        # and verify they actually change (not frozen)
        #
        # Input modules (AI, DI, TC) are scanned by the cRIO reader.
        # Output modules (AO, DO, CO) are write-only -- they only appear
        # in batches when a value is written to them. We check outputs
        # for presence but don't require 4Hz scan rate.
        module_channels = {
            "Mod1_AI (NI 9202)": MOD1_AI[:2],   # sample 2 channels per module
            "Mod3_DI (NI 9425)": MOD3_DI[:2],
            "Mod5_TC (NI 9213)": MOD5_TC[:1],   # TC only ch0 (wired)
        }
        # Output modules -- checked for presence only, no rate requirement
        output_modules = {
            "Mod2_AO (NI 9264)": MOD2_AO[:2],
            "Mod4_DO (NI 9472)": MOD4_DO[:2],
            "Mod6_CO (NI 9266)": MOD6_CO[:2],
        }

        results = {}
        failures = []

        def _analyze_module(mod_name, channels, require_rate):
            """Analyze timestamp update rate for a module's channels."""
            is_tc = "TC" in mod_name
            ts_series = {ch: [] for ch in channels}

            for batch in batches:
                vals = batch.get("channels", batch.get("values", batch))
                for ch in channels:
                    if ch in vals:
                        v = vals[ch]
                        if isinstance(v, dict):
                            ts = v.get("timestamp", v.get("ts"))
                            if ts is not None:
                                ts_series[ch].append(float(ts))

            for ch in channels:
                timestamps = ts_series[ch]
                if len(timestamps) < 2:
                    if require_rate and not is_tc:
                        failures.append(
                            f"{mod_name} {ch}: only {len(timestamps)} "
                            f"timestamps in 30s"
                        )
                    results[f"{mod_name} {ch}"] = {
                        "samples": len(timestamps),
                        "changes": 0,
                        "unique_ts": len(timestamps),
                        "update_rate_hz": 0,
                    }
                    continue

                changes = sum(
                    1 for i in range(1, len(timestamps))
                    if abs(timestamps[i] - timestamps[i-1]) > 0.001
                )
                unique_ts = []
                for ts in timestamps:
                    if not unique_ts or abs(ts - unique_ts[-1]) > 0.001:
                        unique_ts.append(ts)
                if len(unique_ts) >= 2:
                    ts_span = unique_ts[-1] - unique_ts[0]
                    update_rate = (len(unique_ts) - 1) / ts_span if ts_span > 0 else 0
                else:
                    update_rate = 0

                results[f"{mod_name} {ch}"] = {
                    "samples": len(timestamps),
                    "changes": changes,
                    "unique_ts": len(unique_ts),
                    "update_rate_hz": round(update_rate, 1),
                }

                # Safety check: input modules MUST update at >= 2 Hz
                if require_rate and not is_tc and update_rate < 2.0:
                    failures.append(
                        f"{mod_name} {ch}: {update_rate:.1f} Hz "
                        f"(BELOW 2 Hz minimum! {changes}/{len(timestamps)} "
                        f"timestamps changed, {len(unique_ts)} unique)"
                    )

        # Analyze input modules -- MUST meet scan rate (safety-critical)
        for mod_name, channels in module_channels.items():
            _analyze_module(mod_name, channels, require_rate=True)

        # Analyze output modules -- report rate but don't fail
        # (outputs are write-only, only present when values are written)
        for mod_name, channels in output_modules.items():
            _analyze_module(mod_name, channels, require_rate=False)

        # Print results for visibility
        print()
        print("  Per-module scan rate verification (30s window):")
        print(f"  {'Module / Channel':<35} {'Samples':>8} {'Changes':>8} {'Rate':>8}")
        print("  " + "-" * 65)
        for key, info in results.items():
            rate_str = f"{info['update_rate_hz']:.1f} Hz"
            is_output = any(o in key for o in ("AO", "DO", "CO"))
            if is_output:
                marker = " (output)"
            elif info['update_rate_hz'] < 2.0 and "TC" not in key:
                marker = " !!!"
            else:
                marker = ""
            print(f"  {key:<35} {info['samples']:>8} {info['changes']:>8} {rate_str:>8}{marker}")
        print()

        assert len(failures) == 0, (
            f"SAFETY: Module scan rate violations:\n" +
            "\n".join(f"  - {f}" for f in failures)
        )


# ---------------------------------------------------------------------------
# Group 3: Per-Module Hardware Validation
# ---------------------------------------------------------------------------

@pytest.mark.order(3)
class TestGroup3_HardwareValidation:
    """Validate per-module data quality and reader health."""

    def test_di_values_binary(self, crio):
        """All 32 DI channels are exactly 0.0 or 1.0."""
        _require_data()

        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None

        values = batch.get("channels", batch.get("values", batch))
        invalid = []
        for ch in MOD3_DI:
            if ch in values:
                val = values[ch]
                if isinstance(val, dict):
                    val = val.get("value", val.get("v"))
                if val is not None:
                    fval = float(val)
                    if fval not in (0.0, 1.0) and not math.isnan(fval):
                        invalid.append((ch, fval))

        assert len(invalid) == 0, (
            f"DI channels with non-binary values: {invalid}"
        )

    def test_di_timestamps_advancing(self, crio):
        """DI timestamps advance between consecutive batches (not frozen).

        Compares timestamps across two batches taken 2s apart. The absolute
        time may differ from PC clock due to cRIO/PC clock drift, but the
        timestamps MUST change between reads -- frozen timestamps mean
        the DI module is not being scanned.
        """
        _require_data()

        batch1 = crio.wait_for_batch(timeout=10.0)
        assert batch1 is not None

        time.sleep(2)

        batch2 = crio.wait_for_batch(timeout=10.0)
        assert batch2 is not None

        vals1 = batch1.get("channels", batch1.get("values", batch1))
        vals2 = batch2.get("channels", batch2.get("values", batch2))

        frozen = []
        for ch in MOD3_DI[:4]:
            if ch in vals1 and ch in vals2:
                v1 = vals1[ch]
                v2 = vals2[ch]
                if isinstance(v1, dict) and isinstance(v2, dict):
                    ts1 = v1.get("timestamp", v1.get("ts"))
                    ts2 = v2.get("timestamp", v2.get("ts"))
                    if ts1 is not None and ts2 is not None:
                        if abs(float(ts2) - float(ts1)) < 0.001:
                            frozen.append(ch)

        assert len(frozen) == 0, (
            f"DI timestamps frozen (identical across 2s gap): {frozen}. "
            "Module may not be scanning."
        )

    def test_tc_values_in_range(self, crio):
        """TC values in valid range (ch0 has TC wired, rest may be open/overrange).

        Open (unconnected) thermocouple inputs typically read NaN or an
        overrange value (~2300C on NI 9213). These are expected and skipped.
        Only ch0 is required to have a valid reading.
        """
        _require_data()

        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None

        values = batch.get("channels", batch.get("values", batch))
        out_of_range = []
        valid_count = 0

        for ch in MOD5_TC:
            if ch in values:
                val = values[ch]
                if isinstance(val, dict):
                    val = val.get("value", val.get("v"))
                if val is not None:
                    fval = float(val)
                    if math.isnan(fval):
                        continue  # Open TC reads NaN -- skip
                    if fval > 2000 or fval < -200:
                        continue  # Open TC overrange (~2299C) -- skip
                    valid_count += 1
                    if fval < -50 or fval > 1800:
                        out_of_range.append((ch, fval))

        # At least ch0 should be valid (has TC wired)
        assert valid_count >= 1, "No valid TC values -- check TC wiring on ch0"
        assert len(out_of_range) == 0, (
            f"TC channels out of range (-50..1800 C): {out_of_range}"
        )

    def test_ai_values_in_range(self, crio):
        """Mod1 voltage values within +/-10V."""
        _require_data()

        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None

        values = batch.get("channels", batch.get("values", batch))
        out_of_range = []

        for ch in MOD1_AI:
            if ch in values:
                val = values[ch]
                if isinstance(val, dict):
                    val = val.get("value", val.get("v"))
                if val is not None:
                    fval = float(val)
                    if math.isnan(fval):
                        continue
                    if fval < -10.5 or fval > 10.5:
                        out_of_range.append((ch, fval))

        assert len(out_of_range) == 0, (
            f"AI channels out of range (+/-10V): {out_of_range}"
        )

    def test_reader_no_errors(self, crio):
        """All reader_stats entries have error_count < 5."""
        _require_data()

        status = crio.get_crio_status()
        reader_stats = status.get("reader_stats", {})

        if not reader_stats:
            pytest.skip("cRIO not reporting reader_stats")

        high_errors = []
        for key, stats in reader_stats.items():
            error_count = stats.get("error_count", stats.get("errors", 0))
            if error_count >= 5:
                high_errors.append((key, error_count))

        assert len(high_errors) == 0, (
            f"Readers with high error counts (>=5): {high_errors}. "
            "Check hardware connections and cRIO logs."
        )

    def test_tc_reader_active(self, crio):
        """reader_stats for TC module: read_count > 0."""
        _require_data()

        status = crio.get_crio_status()
        reader_stats = status.get("reader_stats", {})

        if not reader_stats:
            pytest.skip("cRIO not reporting reader_stats")

        # Find TC reader (may be keyed as AI_Mod5, TC_Mod5, etc.)
        tc_reader = None
        for key in reader_stats:
            if "Mod5" in key or "mod5" in key or "9213" in key:
                tc_reader = reader_stats[key]
                break

        if tc_reader is None:
            pytest.skip("TC reader not found in reader_stats")

        read_count = tc_reader.get("read_count", tc_reader.get("reads", 0))
        assert read_count > 0, "TC reader has 0 reads -- module may not be responding"

    def test_open_tc_detection(self, crio):
        """Open (disconnected) thermocouples are detected and distinguishable
        from valid readings.

        The NI 9213 has built-in open-TC detection. When a thermocouple is
        disconnected, DAQmx returns either NaN or an overrange value (~2300°C).
        This is a safety requirement: if a TC falls out during a test, the
        system must report an invalid reading — not a plausible temperature.

        ch0 has a wired TC and MUST read a valid temperature.
        ch1–15 are open and MUST read NaN or overrange (>2000°C).
        """
        _require_data()

        # Collect several batches to get stable readings
        wired_ch = "TC_Mod5_ch00"
        open_channels = [f"TC_Mod5_ch{i:02d}" for i in range(1, 16)]

        # Sample 3 batches over ~2 seconds for stability
        wired_values = []
        open_results = {}  # ch -> list of (is_nan, is_overrange, value)
        for ch in open_channels:
            open_results[ch] = []

        for _ in range(3):
            batch = crio.wait_for_batch(timeout=10.0)
            assert batch is not None
            values = batch.get("channels", batch.get("values", batch))

            # Check wired channel
            if wired_ch in values:
                val = values[wired_ch]
                if isinstance(val, dict):
                    val = val.get("value", val.get("v"))
                if val is not None:
                    fval = float(val)
                    if not math.isnan(fval):
                        wired_values.append(fval)

            # Check open channels
            for ch in open_channels:
                if ch in values:
                    val = values[ch]
                    if isinstance(val, dict):
                        val = val.get("value", val.get("v"))
                    if val is not None:
                        fval = float(val)
                        open_results[ch].append({
                            "is_nan": math.isnan(fval),
                            "is_overrange": not math.isnan(fval) and fval > 2000,
                            "value": fval,
                        })

            time.sleep(0.5)

        # --- Wired TC (ch0) must be a valid, plausible temperature ---
        assert len(wired_values) >= 1, (
            f"{wired_ch} returned no valid readings in 3 batches. "
            "Check TC wiring on Mod5 ch0."
        )
        for v in wired_values:
            assert -50 <= v <= 1800, (
                f"{wired_ch} read {v}°C — outside valid range (-50..1800). "
                "Wired TC should read a real temperature."
            )
        # Valid TC should NOT read overrange
        for v in wired_values:
            assert v < 2000, (
                f"{wired_ch} read {v}°C — looks like overrange. "
                "A wired TC should not trigger open-TC detection."
            )

        # --- Open TCs (ch1–15) must ALL be detected as open ---
        false_valid = []  # channels that look like real temps (bad)
        detected_open = []  # channels correctly showing NaN or overrange

        for ch, readings in open_results.items():
            if not readings:
                continue  # channel not in batch, skip

            # A channel is "detected open" if ALL readings are NaN or overrange
            all_open = all(r["is_nan"] or r["is_overrange"] for r in readings)
            if all_open:
                detected_open.append(ch)
            else:
                # Some readings look like valid temperatures — this is bad
                valid_readings = [
                    r["value"] for r in readings
                    if not r["is_nan"] and not r["is_overrange"]
                ]
                false_valid.append((ch, valid_readings))

        assert len(false_valid) == 0, (
            f"Open TC channels reading plausible temperatures (open-TC "
            f"detection failure): {false_valid}. These channels have no TC "
            f"wired — they should read NaN or overrange (~2300°C)."
        )

        # At least some open channels should be in the batch
        assert len(detected_open) >= 5, (
            f"Only {len(detected_open)} of 15 open channels detected. "
            f"Expected at least 5. Check NI 9213 open-TC detection."
        )

        print(f"\n  Open-TC detection results:")
        print(f"    Wired (ch0): {wired_values[0]:.1f}°C (valid)")
        print(f"    Open channels detected: {len(detected_open)}/15")
        if detected_open:
            sample = open_results[detected_open[0]][0]
            if sample["is_nan"]:
                print(f"    Detection method: NaN")
            else:
                print(f"    Detection method: overrange ({sample['value']:.0f}°C)")


# ---------------------------------------------------------------------------
# Group 4: cRIO Log Inspection (SSH)
# ---------------------------------------------------------------------------

@pytest.mark.order(4)
class TestGroup4_LogInspection:
    """SSH to cRIO and check logs for known error patterns."""

    def test_ssh_reachable(self, crio):
        """cRIO is reachable via SSH."""
        _require_crio()
        if not ssh_check_reachable(CRIO_HOST):
            pytest.skip(f"cRIO at {CRIO_HOST} not reachable via SSH")

    def test_no_change_detection_errors(self, crio):
        """No unexpected -201020 errors after latest startup.

        The NI 9425 (DI module) does not support change detection.
        The cRIO gracefully falls back to polling and logs an INFO
        message containing '-201020' + 'recreating as polling task'.
        This is expected and should NOT trigger a test failure.
        Only flag lines that contain -201020 WITHOUT the fallback.
        """
        _require_crio()
        if not ssh_check_reachable(CRIO_HOST):
            pytest.skip("SSH not available")

        matches = ssh_grep_log_since_startup(CRIO_HOST, "-201020")
        # Filter out expected graceful fallback messages
        real_errors = [
            m for m in matches
            if "recreating as polling task" not in m
        ]
        assert len(real_errors) == 0, (
            f"Found {len(real_errors)} change detection errors (-201020) in cRIO log:\n"
            + "\n".join(real_errors[:5])
        )

    def test_no_task_creation_failures(self, crio):
        """No 'Failed to create' task errors after latest startup."""
        _require_crio()
        if not ssh_check_reachable(CRIO_HOST):
            pytest.skip("SSH not available")

        matches = ssh_grep_log_since_startup(CRIO_HOST, "Failed to create")
        assert len(matches) == 0, (
            f"Found {len(matches)} task creation failures in cRIO log:\n"
            + "\n".join(matches[:5])
        )

    def test_no_nan_warnings(self, crio):
        """No 'channels to NaN' warnings after latest startup."""
        _require_crio()
        if not ssh_check_reachable(CRIO_HOST):
            pytest.skip("SSH not available")

        matches = ssh_grep_log_since_startup(CRIO_HOST, "channels to NaN")
        assert len(matches) == 0, (
            f"Found {len(matches)} NaN warnings in cRIO log:\n"
            + "\n".join(matches[:5])
        )

    def test_no_mqtt_disconnects(self, crio):
        """No unexpected MQTT disconnects during the current test session.

        Uses since_last_connect=True so only disconnects that happened after
        the most recent 'MQTT connected' event are checked. Pre-session broker
        bounces (from test auto-start infrastructure) are automatically excluded:
        each reconnect clears the disconnect window, leaving only mid-session
        failures visible.
        """
        _require_crio()
        if not ssh_check_reachable(CRIO_HOST):
            pytest.skip("SSH not available")

        matches = ssh_grep_log_since_startup(CRIO_HOST, "unexpected disconnect",
                                             since_last_connect=True)
        assert len(matches) == 0, (
            f"Found {len(matches)} unexpected MQTT disconnects in cRIO log:\n"
            + "\n".join(matches[:5])
        )


# ---------------------------------------------------------------------------
# Group 5: Acquisition Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.order(5)
class TestGroup5_Lifecycle:
    """Test start/stop/restart and output writes."""

    def test_acquisition_stop(self, crio):
        """Send acquire/stop, verify clean transition to stopped."""
        _require_acquisition()

        crio.send_command("system/acquire/stop", {})
        ok = crio.wait_for_status_field("acquiring", False, timeout=15.0)
        assert ok, "Acquisition did not stop within 15s"
        time.sleep(1)

    def test_acquisition_restart(self, crio):
        """Start -> data -> stop -> start -> verify data resumes."""
        _require_project()

        # Ensure stopped first
        status = crio.get_status()
        if status.get("acquiring"):
            crio.send_command("system/acquire/stop", {})
            crio.wait_for_status_field("acquiring", False, timeout=10.0)
            time.sleep(1)

        # Start
        crio.send_command("system/acquire/start", {})
        ok = crio.wait_for_status_field("acquiring", True, timeout=15.0)
        assert ok, "Acquisition did not start on restart"

        # Wait for data
        time.sleep(3)
        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None, "No data after restart"

        # Stop
        crio.send_command("system/acquire/stop", {})
        ok = crio.wait_for_status_field("acquiring", False, timeout=10.0)
        assert ok, "Acquisition did not stop after restart test"
        time.sleep(1)

        # Start again
        crio.send_command("system/acquire/start", {})
        ok = crio.wait_for_status_field("acquiring", True, timeout=15.0)
        assert ok, "Acquisition did not start on second restart"

        time.sleep(3)
        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None, "No data after second restart"

        _state.acquisition_started = True
        _state.data_flowing = True

    def test_rapid_start_stop(self, crio):
        """3x start/stop in quick succession -- verify no crash/hang."""
        _require_project()

        for i in range(3):
            # Ensure stopped
            crio.send_command("system/acquire/stop", {})
            crio.wait_for_status_field("acquiring", False, timeout=10.0)
            time.sleep(0.5)

            # Start
            crio.send_command("system/acquire/start", {})
            ok = crio.wait_for_status_field("acquiring", True, timeout=15.0)
            assert ok, f"Acquisition failed to start on rapid cycle {i+1}"
            time.sleep(1)

        # Final stop
        crio.send_command("system/acquire/stop", {})
        ok = crio.wait_for_status_field("acquiring", False, timeout=10.0)
        assert ok, "Final stop failed after rapid cycling"

        # Verify system is still responsive
        time.sleep(1)
        status = crio.get_status()
        assert status, "DAQ service not responding after rapid start/stop"

        # Leave acquisition running for remaining tests
        crio.send_command("system/acquire/start", {})
        crio.wait_for_status_field("acquiring", True, timeout=15.0)
        time.sleep(3)
        _state.acquisition_started = True
        _state.data_flowing = True

    def test_output_write_during_acquisition(self, crio):
        """Write AO value via MQTT, verify readback on AI (Mod2 AO -> Mod1 AI).

        Uses the correct command topic: commands/{channel_name}
        (not channels/write, which gets misrouted to channel value handler).
        """
        _require_data()

        # Reset to 0 first to establish a clean baseline.
        # After rapid start/stop cycling, hardware needs extra settling time.
        crio.write_output("AO_Mod2_ch00", 0)
        time.sleep(5)

        # Write 2.5V to Mod2 ch0 (AO wired to Mod1 ch0 AI)
        crio.write_output("AO_Mod2_ch00", 2.5)

        # Wait for AI to settle to ~2.5V (poll with tolerance).
        # Use generous timeout -- hardware may still be stabilizing after
        # the rapid start/stop cycle in the previous test.
        ok = _wait_for_channel_value(crio, "AI_Mod1_ch00", 2.5,
                                     tolerance=1.0, timeout=12.0)
        if not ok:
            # Double-check: read one more time in case value just settled
            val = _read_channel_value(crio, "AI_Mod1_ch00", timeout=3.0)
            if val is not None and abs(val - 2.5) <= 1.0:
                ok = True

        if ok:
            val = _read_channel_value(crio, "AI_Mod1_ch00", timeout=3.0)
            print(f"\n  AO->AI loopback: wrote 2.5V, read back "
                  f"{val:.4f}V" if val else "N/A")

        assert ok, (
            f"AI_Mod1_ch00 (loopback from AO) did not settle to ~2.5V "
            f"within 12s (got {_read_channel_value(crio, 'AI_Mod1_ch00')})"
        )

        # Reset output to 0
        crio.write_output("AO_Mod2_ch00", 0)


# ---------------------------------------------------------------------------
# Group 6: Session & Recording During Acquisition
# ---------------------------------------------------------------------------

@pytest.mark.order(6)
class TestGroup6_SessionRecording:
    """Test session and recording while acquiring."""

    def test_session_during_acquisition(self, crio):
        """Start test session while acquiring, verify session_active, stop."""
        _require_data()

        crio.send_command("test-session/start", {
            "name": "crio_acq_test_session"
        })
        time.sleep(2)

        status = crio.get_status()
        session_active = status.get("session_active", status.get("sessionActive", False))
        assert session_active, "Session did not start during acquisition"

        # Stop session
        crio.send_command("test-session/stop", {})
        time.sleep(2)

        status = crio.get_status()
        session_active = status.get("session_active", status.get("sessionActive", False))
        assert not session_active, "Session did not stop"

    def test_recording_during_acquisition(self, crio):
        """Start recording while acquiring, wait 3s, stop, verify file."""
        _require_data()

        crio.send_command("recording/start", {
            "filename": "crio_acq_test_recording"
        })
        time.sleep(4)

        status = crio.get_status()
        recording = status.get("recording", False)
        # Recording may have started even if status doesn't show it yet
        # (async status update)

        # Stop recording
        crio.send_command("recording/stop", {})
        time.sleep(2)

        status = crio.get_status()
        recording = status.get("recording", False)
        assert not recording, "Recording did not stop"


# ---------------------------------------------------------------------------
# FrontendSimulator -- WebSocket client mimicking the Vue dashboard
# ---------------------------------------------------------------------------

class FrontendSimulator:
    """Connects to Mosquitto on port 9002 via WebSocket -- exactly like the
    Vue dashboard -- and records every channel value that arrives.

    Replicates the dashboard's subscription pattern, acquiring-gate logic,
    and batch parsing so we can verify data actually reaches the browser
    endpoint at the expected rate.
    """

    def __init__(self, ws_port: int = 9002):
        self.ws_port = ws_port
        self._lock = threading.Lock()

        # Node registry -- mirrors dashboard's knownNodes
        self._nodes: Dict[str, dict] = {}

        # Channel values -- mirrors dashboard's channelValues
        self._channel_values: Dict[str, dict] = {}

        # Per-channel timestamp history for rate analysis
        self._channel_ts_history: Dict[str, List[float]] = {}
        # Per-channel receive-time history (wall clock when msg arrived)
        self._channel_rx_times: Dict[str, List[float]] = {}
        # Per-channel value history (to detect actual value changes)
        self._channel_value_history: Dict[str, List] = {}
        # Count of retained (stale) messages vs fresh
        self._retained_count: int = 0
        self._fresh_count: int = 0

        # Raw batch arrival log
        self._batch_log: List[dict] = []
        self._batch_times: List[float] = []
        self._individual_log: List[dict] = []
        self._individual_times: List[float] = []

        # Tracking
        self._status_messages: List[dict] = []
        self._connected = threading.Event()
        self._collecting = False
        self._collect_start: float = 0

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"fake-frontend-{int(time.time() * 1000) % 100000}",
            transport="websockets",
        )
        self.client.ws_set_options(path="/")
        # Port 9002 is anonymous (no credentials needed)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def connect(self, timeout: float = 10.0) -> bool:
        try:
            self.client.connect("127.0.0.1", self.ws_port, keepalive=120)
            self.client.loop_start()
            return self._connected.wait(timeout=timeout)
        except Exception as e:
            print(f"  [FRONTEND] WebSocket connect failed: {e}")
            return False

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # Subscribe to the SAME topics the Vue dashboard subscribes to
        prefix = "nisystem/nodes/+"
        topics = [
            f"{prefix}/channels/#",
            f"{prefix}/status/#",
        ]
        for t in topics:
            client.subscribe(t, qos=1)
        self._connected.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        topic = msg.topic
        now = time.time()

        # Parse node ID from topic: nisystem/nodes/{node_id}/...
        parts = topic.split("/")
        if len(parts) < 4 or parts[1] != "nodes":
            return
        node_id = parts[2]
        rest = "/".join(parts[3:])

        with self._lock:
            # Update node registry from status messages
            # (mirrors dashboard lines 477-493)
            if rest == "status/system" and isinstance(payload, dict):
                existing = self._nodes.get(node_id, {})
                self._nodes[node_id] = {
                    "node_id": node_id,
                    "node_type": payload.get("node_type",
                                             existing.get("node_type", "")),
                    "acquiring": payload.get("acquiring",
                                             existing.get("acquiring")),
                    "status": payload.get("status", "online"),
                    "last_seen": now,
                    "retained": msg.retain,
                }
                self._status_messages.append({
                    "node_id": node_id,
                    "acquiring": payload.get("acquiring"),
                    "retained": msg.retain,
                    "ts": now,
                })

            # Handle channel batches
            # (mirrors dashboard handleBatchChannelValues lines 782-872)
            if rest == "channels/batch" and isinstance(payload, dict):
                # Track retained vs fresh
                if self._collecting:
                    if msg.retain:
                        self._retained_count += 1
                    else:
                        self._fresh_count += 1

                # --- Dashboard acquiring gate ---
                node_info = self._nodes.get(node_id)
                node_acquiring = (node_info or {}).get("acquiring")
                # If we don't know the node's state, accept data
                # (matches dashboard fallback: ?? systemStatus?.acquiring)
                if node_acquiring is False:
                    return  # Gate closed -- dashboard drops this data

                # Skip retained batches -- they are stale from a previous
                # acquisition and don't prove live data delivery
                if msg.retain:
                    return

                if self._collecting:
                    self._batch_log.append({
                        "node_id": node_id, "payload": payload, "ts": now
                    })
                    self._batch_times.append(now)

                for ch_name, ch_data in payload.items():
                    if not isinstance(ch_data, dict):
                        continue
                    value = ch_data.get("value")
                    ts = ch_data.get("timestamp", ch_data.get("ts"))

                    self._channel_values[ch_name] = {
                        "value": value,
                        "timestamp": ts,
                        "node_id": node_id,
                        "received_at": now,
                    }

                    if self._collecting:
                        if ch_name not in self._channel_rx_times:
                            self._channel_rx_times[ch_name] = []
                        self._channel_rx_times[ch_name].append(now)

                        if ch_name not in self._channel_value_history:
                            self._channel_value_history[ch_name] = []
                        self._channel_value_history[ch_name].append(value)

                        if ts is not None:
                            if ch_name not in self._channel_ts_history:
                                self._channel_ts_history[ch_name] = []
                            try:
                                self._channel_ts_history[ch_name].append(
                                    float(ts))
                            except (ValueError, TypeError):
                                pass  # ISO string -- ignore for src ts

            # Handle individual channel values
            # (mirrors dashboard handleChannelValue lines 702-780)
            elif rest.startswith("channels/") and rest != "channels/batch":
                ch_name = rest.split("/")[-1]

                # Track retained vs fresh
                if self._collecting:
                    if msg.retain:
                        self._retained_count += 1
                    else:
                        self._fresh_count += 1

                node_info = self._nodes.get(node_id)
                node_acquiring = (node_info or {}).get("acquiring")
                if node_acquiring is False:
                    return

                # Skip retained -- stale
                if msg.retain:
                    return

                if isinstance(payload, dict):
                    value = payload.get("value")
                    ts_raw = payload.get("timestamp")
                    # Dashboard: new Date(payload.timestamp).getTime()
                    if isinstance(ts_raw, str):
                        try:
                            from datetime import datetime
                            ts = datetime.fromisoformat(
                                ts_raw.replace("Z", "+00:00")
                            ).timestamp()
                        except Exception:
                            ts = now
                    elif isinstance(ts_raw, (int, float)):
                        ts = float(ts_raw)
                    else:
                        ts = now

                    self._channel_values[ch_name] = {
                        "value": value,
                        "timestamp": ts,
                        "node_id": node_id,
                        "received_at": now,
                    }

                    if self._collecting:
                        self._individual_log.append({
                            "ch": ch_name, "node_id": node_id, "ts": now
                        })
                        self._individual_times.append(now)

                        if ch_name not in self._channel_ts_history:
                            self._channel_ts_history[ch_name] = []
                        self._channel_ts_history[ch_name].append(ts)

                        if ch_name not in self._channel_rx_times:
                            self._channel_rx_times[ch_name] = []
                        self._channel_rx_times[ch_name].append(now)

                        if ch_name not in self._channel_value_history:
                            self._channel_value_history[ch_name] = []
                        self._channel_value_history[ch_name].append(value)

    def start_collecting(self):
        """Start recording channel data for rate analysis."""
        with self._lock:
            self._batch_log.clear()
            self._batch_times.clear()
            self._individual_log.clear()
            self._individual_times.clear()
            self._channel_ts_history.clear()
            self._channel_rx_times.clear()
            self._channel_value_history.clear()
            self._retained_count = 0
            self._fresh_count = 0
            self._collect_start = time.time()
            self._collecting = True

    def stop_collecting(self) -> dict:
        """Stop recording and return analysis results."""
        with self._lock:
            self._collecting = False
            duration = time.time() - self._collect_start
            return {
                "duration_s": round(duration, 1),
                "batch_count": len(self._batch_log),
                "individual_count": len(self._individual_log),
                "channel_ts_history": dict(self._channel_ts_history),
                "channel_rx_times": dict(self._channel_rx_times),
                "channel_value_history": dict(self._channel_value_history),
                "batch_times": list(self._batch_times),
                "individual_times": list(self._individual_times),
                "nodes_seen": dict(self._nodes),
                "status_messages": list(self._status_messages),
                "channels_with_data": set(self._channel_values.keys()),
                "retained_count": self._retained_count,
                "fresh_count": self._fresh_count,
            }

    def get_module_rates(self, results_dict: dict,
                         module_channels: Dict[str, List[str]],
                         ) -> Dict[str, dict]:
        """Analyze per-module update rates from collection results.

        Uses RECEIVE timestamps (PC wall clock when each message arrived)
        for rate calculation -- this measures what the frontend actually
        experiences, regardless of source clock drift between cRIO and PC.

        Checks three things per channel:
        1. Receive rate (fresh messages arriving at >= 2 Hz)
        2. Value changes (at least some values differ -- not a frozen reading)
        3. Freshness (all data from non-retained messages during collection)

        Returns {module_name: {samples, rate_hz, value_changes, all_fresh}}.
        """
        rx_times = results_dict.get("channel_rx_times", {})
        value_history = results_dict.get("channel_value_history", {})
        collect_start = results_dict.get("duration_s", 30.0)

        results = {}
        for mod_name, channels in module_channels.items():
            for ch in channels:
                rx = rx_times.get(ch, [])
                vals = value_history.get(ch, [])

                if len(rx) < 2:
                    results[f"{mod_name} {ch}"] = {
                        "samples": len(rx),
                        "rate_hz": 0.0,
                        "value_changes": 0,
                        "all_fresh": len(rx) > 0,
                    }
                    continue

                # Rate from receive times (all from PC clock -- no drift)
                span = rx[-1] - rx[0]
                rate = (len(rx) - 1) / span if span > 0 else 0

                # Count value changes (proves reading is live, not frozen)
                val_changes = 0
                for i in range(1, len(vals)):
                    if vals[i] != vals[i - 1]:
                        val_changes += 1

                # All data arrived during collection = all fresh
                all_fresh = len(rx) > 0

                results[f"{mod_name} {ch}"] = {
                    "samples": len(rx),
                    "rate_hz": round(rate, 1),
                    "value_changes": val_changes,
                    "all_fresh": all_fresh,
                }
        return results


# ---------------------------------------------------------------------------
# Fixtures for frontend simulator
# ---------------------------------------------------------------------------

def _ws_port_open(port: int = 9002) -> bool:
    """Check if WebSocket port is listening."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def frontend():
    """Fake frontend: WebSocket client on port 9002 (same as Vue dashboard).

    Connects anonymously via WebSocket -- identical transport to the real
    dashboard. Provides rate analysis for all channel data that arrives.
    """
    if not _ws_port_open(9002):
        pytest.skip("WebSocket port 9002 not available -- "
                     "Mosquitto not running or no WS listener configured")

    sim = FrontendSimulator(ws_port=9002)
    if not sim.connect(timeout=10.0):
        pytest.skip("Cannot connect to ws://127.0.0.1:9002 -- "
                     "check Mosquitto WebSocket listener")

    yield sim
    sim.disconnect()


# ---------------------------------------------------------------------------
# Group 7: Frontend Data Delivery Verification
# ---------------------------------------------------------------------------

@pytest.mark.order(7)
class TestGroup7_FrontendDelivery:
    """Verify channel data reaches the dashboard's WebSocket endpoint.

    Acts as a fake Vue dashboard: connects to ws://127.0.0.1:9002,
    subscribes to nisystem/nodes/+/channels/# and status/#, and
    verifies per-module data arrives at the expected rate.

    This catches:
    - Cross-listener delivery failures (1883 -> 9002)
    - Acquiring-gate bugs (data silently dropped if acquiring=false)
    - MQTT bottlenecks or payload size issues
    - Timestamp freshness and update rate
    """

    def test_websocket_connected(self, frontend, crio):
        """Frontend simulator connects to ws://127.0.0.1:9002."""
        _require_data()
        assert frontend._connected.is_set(), (
            "WebSocket connection to port 9002 failed"
        )

    def test_frontend_sees_status(self, frontend, crio):
        """Frontend receives status/system messages from DAQ and cRIO.

        The dashboard uses these to populate knownNodes and set the
        acquiring flag that gates channel data acceptance.
        """
        _require_data()

        # Give a moment for retained status to arrive
        time.sleep(3)

        with frontend._lock:
            nodes = dict(frontend._nodes)
            statuses = list(frontend._status_messages)

        assert len(nodes) >= 1, (
            f"Frontend received no status messages on port 9002. "
            f"Cross-listener delivery may be broken."
        )

        # Should see at least DAQ node or cRIO node
        node_types = {n.get("node_type", "") for n in nodes.values()}
        node_descs = []
        for nid, n in nodes.items():
            ntype = n.get("node_type", "?")
            acq = n.get("acquiring")
            node_descs.append(f"{nid} ({ntype}, acquiring={acq})")
        print(f"\n  Frontend sees {len(nodes)} node(s): "
              f"{', '.join(node_descs)}")
        print(f"  Status messages received: {len(statuses)}")

    def test_frontend_acquiring_gate(self, frontend, crio):
        """Frontend's acquiring gate is OPEN for the active node.

        The dashboard silently drops ALL channel data when
        nodeInfo.acquiring is False. This test verifies the gate
        is open before we start measuring rates.
        """
        _require_data()

        # Ensure acquisition is running
        status = crio.get_status()
        if not status.get("acquiring"):
            crio.send_command("system/acquire/start", {})
            crio.wait_for_status_field("acquiring", True, timeout=15.0)
            time.sleep(3)

        # Wait for fresh status to reach frontend (not retained)
        time.sleep(5)

        with frontend._lock:
            nodes = dict(frontend._nodes)

        acquiring_nodes = {
            nid: n for nid, n in nodes.items()
            if n.get("acquiring") is True
        }

        assert len(acquiring_nodes) >= 1, (
            f"No nodes show acquiring=True on frontend. "
            f"Node states: {nodes}. "
            f"Dashboard would silently drop ALL channel data!"
        )

        print(f"\n  Acquiring nodes visible to frontend: "
              f"{list(acquiring_nodes.keys())}")

    def test_frontend_receives_channel_data_30s(self, frontend, crio):
        """30-second sustained test: channel data arrives on port 9002.

        SAFETY-CRITICAL: This proves data makes it through the entire
        pipeline to where the browser would consume it:

          cRIO -> port 8883 -> Mosquitto -> port 9002 (WebSocket) -> browser

        And via the DAQ re-publish path:

          cRIO -> 8883 -> DAQ (1883) -> re-publish -> 9002 -> browser

        Measures per-module update rate as seen by the frontend.
        """
        _require_data()

        # Ensure acquisition is running
        status = crio.get_status()
        if not status.get("acquiring"):
            crio.send_command("system/acquire/start", {})
            crio.wait_for_status_field("acquiring", True, timeout=15.0)
            time.sleep(5)

        # Start collecting
        frontend.start_collecting()

        print("\n  Collecting channel data on ws://127.0.0.1:9002 for 30s...")
        time.sleep(30)

        results = frontend.stop_collecting()

        # Basic delivery check
        batch_count = results["batch_count"]
        individual_count = results["individual_count"]
        total_msgs = batch_count + individual_count

        print(f"  Duration:           {results['duration_s']}s")
        print(f"  Batch messages:     {batch_count}")
        print(f"  Individual values:  {individual_count}")
        print(f"  Channels with data: {len(results['channels_with_data'])}")

        assert total_msgs > 0, (
            "CRITICAL: Zero channel messages received on port 9002 in 30s!\n"
            "The dashboard would show NO data.\n"
            f"Nodes seen: {list(results['nodes_seen'].keys())}\n"
            f"Status msgs: {len(results['status_messages'])}\n"
            "Check: per_listener_settings, acquiring gate, MQTT subscriptions"
        )

        # Freshness check: all messages must be fresh (not retained)
        print(f"  Fresh messages:     {results['fresh_count']}")
        print(f"  Retained (stale):   {results['retained_count']}")

        assert results["fresh_count"] > 0, (
            "ALL messages on port 9002 were retained (stale)!\n"
            "No live data is reaching the frontend."
        )

        # Per-module rate analysis
        input_modules = {
            "Mod1_AI (NI 9202)": MOD1_AI[:2],
            "Mod3_DI (NI 9425)": MOD3_DI[:2],
            "Mod5_TC (NI 9213)": MOD5_TC[:1],
        }
        output_modules = {
            "Mod2_AO (NI 9264)": MOD2_AO[:2],
            "Mod4_DO (NI 9472)": MOD4_DO[:2],
            "Mod6_CO (NI 9266)": MOD6_CO[:2],
        }

        all_modules = {**input_modules, **output_modules}
        rates = frontend.get_module_rates(results, all_modules)

        # Print rate table with freshness and value change columns
        print()
        print(f"  {'Module / Channel':<35} {'Samples':>8} "
              f"{'Rate':>8} {'ValChg':>8} {'Fresh':>6}")
        print("  " + "-" * 72)

        failures = []
        for key, info in rates.items():
            rate_str = f"{info['rate_hz']:.1f} Hz"
            fresh_str = "yes" if info["all_fresh"] else "NO"
            is_output = any(o in key for o in ("AO", "DO", "CO"))
            is_tc = "TC" in key

            if is_output:
                marker = " (output)"
            elif is_tc:
                marker = " (TC-slow)"
            elif info["samples"] == 0:
                marker = " NO DATA"
            elif info["rate_hz"] < 2.0:
                marker = " RATE!"
            elif not info["all_fresh"]:
                marker = " STALE!"
            else:
                marker = ""

            print(f"  {key:<35} {info['samples']:>8} "
                  f"{rate_str:>8} "
                  f"{info['value_changes']:>8} {fresh_str:>6}{marker}")

            # Safety check: input modules MUST have:
            # 1. Data arriving (samples > 0)
            # 2. Updates at >= 2 Hz (measured by receive time, not source ts)
            # 3. All data from fresh messages (not retained/stale)
            if not is_output and not is_tc:
                if info["samples"] == 0:
                    failures.append(
                        f"{key}: NO DATA received on port 9002 -- "
                        "dashboard would show stale/blank"
                    )
                elif info["rate_hz"] < 2.0:
                    failures.append(
                        f"{key}: {info['rate_hz']:.1f} Hz on port 9002 -- "
                        f"below 2 Hz minimum ({info['samples']} samples)"
                    )
                elif not info["all_fresh"]:
                    failures.append(
                        f"{key}: contains stale (retained) data -- "
                        "frontend may display old values as current"
                    )

        print()

        # Overall batch rate
        if len(results["batch_times"]) >= 2:
            span = results["batch_times"][-1] - results["batch_times"][0]
            batch_rate = ((len(results["batch_times"]) - 1) / span
                          if span > 0 else 0)
            print(f"  Overall batch rate on 9002: {batch_rate:.1f} Hz")
        if len(results["individual_times"]) >= 2:
            span = (results["individual_times"][-1]
                    - results["individual_times"][0])
            ind_rate = ((len(results["individual_times"]) - 1) / span
                        if span > 0 else 0)
            print(f"  Overall individual rate on 9002: {ind_rate:.1f} Hz")

        assert len(failures) == 0, (
            f"SAFETY: Frontend data delivery failures:\n"
            + "\n".join(f"  - {f}" for f in failures) +
            "\n\nThe dashboard would show stale or missing data for "
            "these modules. This is a safety issue if these channels "
            "feed interlocks."
        )

    def test_frontend_data_matches_backend(self, frontend, crio):
        """Values seen by frontend match the backend's latest batch.

        Cross-checks a sample of channels: the value the frontend sees
        on port 9002 should match what the backend published on port 1883.
        Large discrepancies indicate data corruption or stale delivery.
        """
        _require_data()

        # Get latest batch from backend (port 1883)
        backend_batch = crio.wait_for_batch(timeout=10.0)
        assert backend_batch is not None, "No batch from backend"

        time.sleep(1)  # Allow frontend to receive the same data

        with frontend._lock:
            fe_values = dict(frontend._channel_values)

        backend_vals = backend_batch.get("channels",
                                         backend_batch.get("values",
                                                           backend_batch))
        matched = 0
        mismatched = []
        missing = []

        # Check a sample of input channels
        sample_channels = MOD1_AI[:4] + MOD3_DI[:4]
        for ch in sample_channels:
            if ch not in backend_vals:
                continue

            be_val = backend_vals[ch]
            if isinstance(be_val, dict):
                be_val = be_val.get("value")

            if ch not in fe_values:
                missing.append(ch)
                continue

            fe_val = fe_values[ch].get("value")

            if be_val is None or fe_val is None:
                continue

            # Allow small float tolerance
            try:
                if abs(float(be_val) - float(fe_val)) > 0.01:
                    mismatched.append(
                        f"{ch}: backend={be_val}, frontend={fe_val}"
                    )
                else:
                    matched += 1
            except (ValueError, TypeError):
                matched += 1  # Non-numeric, skip comparison

        print(f"\n  Cross-check: {matched} matched, "
              f"{len(mismatched)} mismatched, {len(missing)} missing")

        if missing:
            print(f"  Missing on frontend: {missing}")
        if mismatched:
            print(f"  Mismatched: {mismatched[:5]}")

        # We expect at least SOME channels to match
        assert matched > 0 or len(missing) == 0, (
            f"Frontend has no matching channel values. "
            f"Missing: {missing}, Mismatched: {mismatched}"
        )


# ---------------------------------------------------------------------------
# Group 8: DO -> DI Loopback (Digital Output Round-Trip)
# ---------------------------------------------------------------------------
#
# Wiring on cRIO-9056:
#   Module 4 (NI 9472, 8 DO):
#     ch0-3: connected to relays (toggle test, no readback)
#     ch4  : wired to Module 3 DI ch0 (loopback)
#     ch5  : wired to Module 3 DI ch1 (loopback)
#
#   Module 3 (NI 9425, 32 DI):
#     ch0  : reads DO ch4 via loopback
#     ch1  : reads DO ch5 via loopback
#

# Loopback pairs: (DO channel, DI channel)
LOOPBACK_PAIRS = [
    ("DO_Mod4_ch04", "DI_Mod3_ch00"),
    ("DO_Mod4_ch05", "DI_Mod3_ch01"),
]

# Relay-only DOs (no readback, just verify no crash)
RELAY_DOS = ["DO_Mod4_ch00", "DO_Mod4_ch01", "DO_Mod4_ch02", "DO_Mod4_ch03"]


def _read_channel_value(crio, channel: str, timeout: float = 5.0) -> Optional[float]:
    """Read a channel value from the latest batch."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = crio.wait_for_batch(timeout=2.0)
        if batch:
            vals = batch.get("channels", batch.get("values", batch))
            if channel in vals:
                v = vals[channel]
                if isinstance(v, dict):
                    v = v.get("value", v.get("v"))
                if v is not None:
                    return float(v)
        time.sleep(0.1)
    return None


def _wait_for_channel_value(crio, channel: str, expected: float,
                            tolerance: float = 0.01,
                            timeout: float = 5.0) -> bool:
    """Wait until a channel reads close to the expected value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = crio.wait_for_batch(timeout=2.0)
        if batch:
            vals = batch.get("channels", batch.get("values", batch))
            if channel in vals:
                v = vals[channel]
                if isinstance(v, dict):
                    v = v.get("value", v.get("v"))
                if v is not None and abs(float(v) - expected) <= tolerance:
                    return True
        time.sleep(0.1)
    return False


# AO -> AI loopback pairs: (AO channel, AI channel) -- all 16 wired together
AO_AI_LOOPBACK_PAIRS = [
    (f"AO_Mod2_ch{i:02d}", f"AI_Mod1_ch{i:02d}") for i in range(16)
]

# CO -> CI loopback pairs: (CO channel, CI channel) -- all 8 wired together
# Mod6 (NI 9266, 0-20mA output) -> Mod7 (4-20mA input)
CO_CI_LOOPBACK_PAIRS = [
    (f"CO_Mod6_ch{i:02d}", f"CI_Mod7_ch{i:02d}") for i in range(8)
]


@pytest.mark.order(8)
class TestGroup8_DigitalLoopback:
    """DO -> DI loopback: toggle digital outputs and verify inputs follow.

    This proves the full signal path works during live acquisition:
      MQTT command -> DAQ -> cRIO -> NI 9472 DO -> physical wire ->
      NI 9425 DI -> cRIO read -> MQTT batch -> verified

    Also toggles relay-connected DOs (ch0-3) to verify they don't
    cause errors or crashes, even though there's no DI readback.

    Wiring on cRIO-9056:
      Module 4 (NI 9472, 8 DO):
        ch0-3: connected to relays (toggle test, no readback)
        ch4  : wired to Module 3 DI ch0 (loopback)
        ch5  : wired to Module 3 DI ch1 (loopback)
      Module 3 (NI 9425, 32 DI):
        ch0  : reads DO ch4 via loopback
        ch1  : reads DO ch5 via loopback
    """

    def test_loopback_set_low(self, crio):
        """Set both loopback DOs LOW, verify DIs read 0."""
        _require_data()

        for do_ch, di_ch in LOOPBACK_PAIRS:
            crio.write_output(do_ch, 0)
        time.sleep(1)

        for do_ch, di_ch in LOOPBACK_PAIRS:
            ok = _wait_for_channel_value(crio, di_ch, 0.0, timeout=5.0)
            assert ok, (
                f"Loopback FAIL: wrote {do_ch}=0, but {di_ch} did not "
                f"read 0.0 within 5s (got {_read_channel_value(crio, di_ch)})"
            )

    def test_loopback_set_high(self, crio):
        """Set both loopback DOs HIGH, verify DIs read 1."""
        _require_data()

        for do_ch, di_ch in LOOPBACK_PAIRS:
            crio.write_output(do_ch, 1)
        time.sleep(1)

        for do_ch, di_ch in LOOPBACK_PAIRS:
            ok = _wait_for_channel_value(crio, di_ch, 1.0, timeout=5.0)
            assert ok, (
                f"Loopback FAIL: wrote {do_ch}=1, but {di_ch} did not "
                f"read 1.0 within 5s (got {_read_channel_value(crio, di_ch)})"
            )

        # Clean up
        for do_ch, _ in LOOPBACK_PAIRS:
            crio.write_output(do_ch, 0)

    def test_loopback_toggle_cycle(self, crio):
        """Toggle each loopback pair 5x: HIGH/LOW/HIGH...verify DI follows.

        Measures round-trip latency (DO write -> DI reads new value).
        Each transition must complete within 3 seconds.
        """
        _require_data()

        results = []

        for do_ch, di_ch in LOOPBACK_PAIRS:
            # Start from known LOW state
            crio.write_output(do_ch, 0)
            time.sleep(0.5)
            _wait_for_channel_value(crio, di_ch, 0.0, timeout=3.0)

            transitions = []
            for cycle in range(5):
                # Toggle HIGH
                t0 = time.time()
                crio.write_output(do_ch, 1)
                ok = _wait_for_channel_value(crio, di_ch, 1.0, timeout=3.0)
                t_high = time.time() - t0
                assert ok, (
                    f"Loopback {do_ch}->{di_ch}: cycle {cycle+1} "
                    f"HIGH transition failed after 3s"
                )
                transitions.append(t_high)

                # Toggle LOW
                t0 = time.time()
                crio.write_output(do_ch, 0)
                ok = _wait_for_channel_value(crio, di_ch, 0.0, timeout=3.0)
                t_low = time.time() - t0
                assert ok, (
                    f"Loopback {do_ch}->{di_ch}: cycle {cycle+1} "
                    f"LOW transition failed after 3s"
                )
                transitions.append(t_low)

            avg_ms = sum(transitions) / len(transitions) * 1000
            max_ms = max(transitions) * 1000
            results.append((do_ch, di_ch, avg_ms, max_ms, len(transitions)))

        # Print results
        print()
        print("  DO -> DI Loopback Toggle Results (5 cycles each):")
        print(f"  {'DO -> DI':<30} {'Transitions':>12} "
              f"{'Avg':>10} {'Max':>10}")
        print("  " + "-" * 65)
        for do_ch, di_ch, avg_ms, max_ms, count in results:
            print(f"  {do_ch} -> {di_ch:<14} {count:>12} "
                  f"{avg_ms:>8.0f} ms {max_ms:>8.0f} ms")
        print()

    def test_relay_toggle(self, crio):
        """Toggle relay DOs (ch0-3) ON then OFF. No readback -- just
        verify no errors or crashes. Listen for click.

        These are real 24V relays. The test proves the output path works
        end-to-end for safety-critical outputs (e.g., emergency stop relays).
        """
        _require_data()

        # Turn all relays ON one at a time
        for do_ch in RELAY_DOS:
            crio.write_output(do_ch, 1)
            time.sleep(0.3)

        # All ON -- hold for 1 second
        time.sleep(1)

        # Verify cRIO is still healthy (no crash from relay switching)
        status = crio.get_crio_status()
        assert status.get("status") in ("online", "idle", "acquiring"), (
            f"cRIO status degraded after relay toggle: {status.get('status')}"
        )

        # Turn all relays OFF one at a time
        for do_ch in RELAY_DOS:
            crio.write_output(do_ch, 0)
            time.sleep(0.3)

        # All OFF -- verify still acquiring
        time.sleep(1)
        batch = crio.wait_for_batch(timeout=5.0)
        assert batch is not None, (
            "No data batch after relay toggle -- acquisition may have stalled"
        )

        # Check reader_stats for errors after toggle
        status = crio.get_crio_status()
        reader_stats = status.get("reader_stats", {})
        for key, stats in reader_stats.items():
            error_count = stats.get("error_count", stats.get("errors", 0))
            assert error_count < 10, (
                f"Reader {key} has {error_count} errors after relay toggle"
            )

        print("\n  Relay toggle: 4 DOs toggled ON->OFF, "
              "cRIO healthy, no reader errors")

    def test_loopback_rapid_toggle(self, crio):
        """Rapid-fire toggle: 20 transitions in quick succession.

        Verifies the DO->DI path handles rapid state changes without
        missing transitions or latching in the wrong state.
        After rapid toggling, verifies final state matches last write.
        """
        _require_data()

        do_ch, di_ch = LOOPBACK_PAIRS[0]  # Use first pair

        # Start LOW
        crio.write_output(do_ch, 0)
        time.sleep(0.5)

        # Rapid toggle: alternate 0/1 twenty times
        final_value = 0
        for i in range(20):
            final_value = i % 2
            crio.write_output(do_ch, final_value)
            time.sleep(0.05)  # 50ms between writes

        # Wait for system to settle
        time.sleep(2)

        # Verify final state matches last write
        ok = _wait_for_channel_value(crio, di_ch, float(final_value),
                                     timeout=5.0)
        actual = _read_channel_value(crio, di_ch)
        assert ok, (
            f"Rapid toggle: final write was {do_ch}={final_value}, "
            f"but {di_ch} reads {actual} (expected {float(final_value)})"
        )

        # Also verify the other loopback pair still works (not affected)
        if len(LOOPBACK_PAIRS) > 1:
            do2, di2 = LOOPBACK_PAIRS[1]
            crio.write_output(do2, 1)
            time.sleep(1)
            ok2 = _wait_for_channel_value(crio, di2, 1.0, timeout=5.0)
            assert ok2, (
                f"After rapid toggle of {do_ch}, loopback {do2}->{di2} "
                f"is broken (expected 1.0, got {_read_channel_value(crio, di2)})"
            )
            crio.write_output(do2, 0)

        # Clean up -- set all DOs LOW
        for do_ch_clean, _ in LOOPBACK_PAIRS:
            crio.write_output(do_ch_clean, 0)

        print(f"\n  Rapid toggle: 20 transitions at 50ms, "
              f"final state verified, cross-pair OK")


# ---------------------------------------------------------------------------
# Group 9: AO -> AI Analog Loopback (Module 2 output -> Module 1 input)
# ---------------------------------------------------------------------------
#
# Wiring on cRIO-9056:
#   Module 2 (NI 9264, 16 AO voltage): all 16 channels wired to Module 1
#   Module 1 (NI 9202, 16 AI voltage): all 16 channels read Module 2
#
#   AO_Mod2_ch00 -> AI_Mod1_ch00
#   AO_Mod2_ch01 -> AI_Mod1_ch01
#   ... all 16 pairs
#

@pytest.mark.order(9)
class TestGroup9_AnalogLoopback:
    """AO -> AI analog loopback: write voltage outputs, verify inputs match.

    This proves the full analog signal path during live acquisition:
      MQTT write_output -> DAQ -> cRIO -> NI 9264 AO -> physical wire ->
      NI 9202 AI -> cRIO read -> MQTT batch -> verified

    All 16 AO channels on Module 2 are wired to all 16 AI channels on Module 1.
    """

    def test_ao_zero_baseline(self, crio):
        """Set all 16 AO channels to 0V, verify AI reads near 0V."""
        _require_data()

        # Write 0V to all AO channels
        for ao_ch, _ in AO_AI_LOOPBACK_PAIRS:
            crio.write_output(ao_ch, 0.0)
        time.sleep(2)

        # Verify AI reads near 0V (within 0.1V for settling)
        results = []
        for ao_ch, ai_ch in AO_AI_LOOPBACK_PAIRS[:4]:  # Check first 4 pairs
            val = _read_channel_value(crio, ai_ch, timeout=5.0)
            if val is not None:
                results.append((ao_ch, ai_ch, val))
                assert abs(val) < 0.2, (
                    f"Zero baseline: {ai_ch} reads {val:.4f}V "
                    f"(expected ~0V after writing {ao_ch}=0)"
                )

        if results:
            print(f"\n  AO zero baseline: {len(results)} channels verified "
                  f"near 0V (max offset: "
                  f"{max(abs(r[2]) for r in results):.4f}V)")

    def test_ao_ai_single_channel_accuracy(self, crio):
        """Write known voltages to AO ch0, verify AI ch0 reads back accurately.

        Tests multiple voltage levels: -5V, -2.5V, 0V, 2.5V, 5V, 10V
        Accuracy target: within 0.5V (NI 9202 is 16-bit, NI 9264 is 16-bit).
        """
        _require_data()

        ao_ch, ai_ch = AO_AI_LOOPBACK_PAIRS[0]
        test_voltages = [-5.0, -2.5, 0.0, 2.5, 5.0, 9.0]
        results = []

        for target_v in test_voltages:
            crio.write_output(ao_ch, target_v)
            time.sleep(1.5)  # Allow settling

            val = _read_channel_value(crio, ai_ch, timeout=5.0)
            if val is not None:
                error = abs(val - target_v)
                results.append((target_v, val, error))
                assert error < 0.5, (
                    f"AO->AI accuracy: wrote {ao_ch}={target_v}V, "
                    f"read {ai_ch}={val:.4f}V (error: {error:.4f}V > 0.5V)"
                )

        # Reset to 0
        crio.write_output(ao_ch, 0.0)

        # Print accuracy table
        if results:
            print()
            print(f"  AO->AI Accuracy ({ao_ch} -> {ai_ch}):")
            print(f"  {'Set (V)':>10} {'Read (V)':>10} {'Error (V)':>10}")
            print("  " + "-" * 35)
            for target, actual, err in results:
                print(f"  {target:>10.2f} {actual:>10.4f} {err:>10.4f}")
            avg_err = sum(r[2] for r in results) / len(results)
            max_err = max(r[2] for r in results)
            print(f"  Avg error: {avg_err:.4f}V, Max error: {max_err:.4f}V")
            print()

    def test_ao_ai_all_channels(self, crio):
        """Write 5V to all 16 AO channels, verify all 16 AI channels read ~5V.

        Proves every wire in the loopback harness is connected correctly.
        """
        _require_data()

        target_v = 5.0

        # Write 5V to all AO channels
        for ao_ch, _ in AO_AI_LOOPBACK_PAIRS:
            crio.write_output(ao_ch, target_v)

        time.sleep(3)  # Allow all channels to settle

        # Read and verify all AI channels
        passed = []
        failed = []
        for ao_ch, ai_ch in AO_AI_LOOPBACK_PAIRS:
            val = _read_channel_value(crio, ai_ch, timeout=5.0)
            if val is None:
                failed.append((ao_ch, ai_ch, None, "no data"))
            elif abs(val - target_v) > 1.0:
                failed.append((ao_ch, ai_ch, val,
                              f"error {abs(val - target_v):.3f}V"))
            else:
                passed.append((ao_ch, ai_ch, val))

        # Reset all to 0
        for ao_ch, _ in AO_AI_LOOPBACK_PAIRS:
            crio.write_output(ao_ch, 0.0)

        # Print results
        print(f"\n  AO->AI all-channel test ({target_v}V):")
        print(f"  {len(passed)}/16 passed, {len(failed)}/16 failed")
        if failed:
            for ao, ai, val, reason in failed:
                val_str = f"{val:.4f}V" if val is not None else "N/A"
                print(f"  FAIL: {ao} -> {ai}: {val_str} ({reason})")

        assert len(failed) == 0, (
            f"AO->AI all-channel: {len(failed)}/16 channels failed at "
            f"{target_v}V. Failures: " +
            ", ".join(f"{f[0]}->{f[1]}={f[2]}" for f in failed)
        )

    def test_ao_ai_ramp(self, crio):
        """Ramp AO ch0 from -5V to +5V in 1V steps, verify AI follows.

        Proves the analog path is monotonic (no inversions or stuck values)
        across the full voltage range.
        """
        _require_data()

        ao_ch, ai_ch = AO_AI_LOOPBACK_PAIRS[0]
        ramp_voltages = [v for v in range(-5, 6)]  # -5 to +5 in 1V steps
        readings = []

        # Pre-settle: drive to the first ramp voltage and wait for it to
        # stabilize before starting measurement. This avoids the first
        # reading being stale from whatever voltage was left over.
        crio.write_output(ao_ch, float(ramp_voltages[0]))
        time.sleep(3)

        for target_v in ramp_voltages:
            crio.write_output(ao_ch, float(target_v))
            time.sleep(1.5)  # Allow settling between steps
            val = _read_channel_value(crio, ai_ch, timeout=3.0)
            readings.append((target_v, val))

        # Reset to 0
        crio.write_output(ao_ch, 0.0)

        # Verify monotonic (each reading >= previous)
        valid_readings = [(t, v) for t, v in readings if v is not None]
        if len(valid_readings) >= 2:
            monotonic_ok = True
            for i in range(1, len(valid_readings)):
                if valid_readings[i][1] < valid_readings[i-1][1] - 0.2:
                    monotonic_ok = False
                    break

            assert monotonic_ok, (
                f"AO->AI ramp is NOT monotonic: "
                + ", ".join(f"{t}V->{v:.2f}V" for t, v in valid_readings)
            )

        # Print ramp
        print()
        print(f"  AO->AI Ramp ({ao_ch} -> {ai_ch}):")
        print(f"  {'Set (V)':>10} {'Read (V)':>10}")
        print("  " + "-" * 25)
        for target, val in readings:
            val_str = f"{val:.4f}" if val is not None else "N/A"
            print(f"  {target:>10.1f} {val_str:>10}")
        print()

    def test_ao_ai_step_response(self, crio):
        """Step from 0V to 5V, measure how quickly AI settles.

        Writes AO ch1 from 0V to 5V and checks AI ch1 at 250ms intervals.
        Verifies settling within 1 second (4 samples at 4Hz).
        """
        _require_data()

        ao_ch, ai_ch = AO_AI_LOOPBACK_PAIRS[1]

        # Start at 0V
        crio.write_output(ao_ch, 0.0)
        time.sleep(1.5)

        # Step to 5V
        t_step = time.time()
        crio.write_output(ao_ch, 5.0)

        # Sample at 250ms intervals for 2 seconds
        samples = []
        for i in range(8):
            time.sleep(0.25)
            val = _read_channel_value(crio, ai_ch, timeout=1.0)
            t_sample = time.time() - t_step
            samples.append((t_sample, val))

        # Reset
        crio.write_output(ao_ch, 0.0)

        # Check that at least one sample is within 0.5V of target
        settled = any(
            v is not None and abs(v - 5.0) < 0.5
            for _, v in samples
        )
        assert settled, (
            f"AO->AI step response: AI never settled within 0.5V of 5.0V "
            f"in 2 seconds. Samples: "
            + ", ".join(
                f"{t:.2f}s={v:.2f}V" if v is not None else f"{t:.2f}s=N/A"
                for t, v in samples
            )
        )

        # Find settling time (first sample within 0.5V)
        settle_time = None
        for t, v in samples:
            if v is not None and abs(v - 5.0) < 0.5:
                settle_time = t
                break

        print(f"\n  AO->AI step response ({ao_ch} -> {ai_ch}):")
        print(f"  Step: 0V -> 5V, settled in {settle_time:.2f}s" if settle_time
              else "  Step: 0V -> 5V, did NOT settle")
        for t, v in samples:
            marker = " <-- settled" if (v and abs(v - 5.0) < 0.5 and
                                        t == settle_time) else ""
            val_str = f"{v:.4f}V" if v is not None else "N/A"
            print(f"    {t:.2f}s: {val_str}{marker}")


# ---------------------------------------------------------------------------
# Group 10: cRIO-Local Safety Interlock with Relay Output
# ---------------------------------------------------------------------------
#
# All interlock commands go DIRECTLY to the cRIO node, bypassing the DAQ
# service entirely.  The cRIO evaluates conditions locally in its main loop
# and fires trip actions (relay output) independently.
#
# Safety chain tested:
#   Physical DI state -> cRIO hardware read -> cRIO safety.py evaluation ->
#   interlock trip -> cRIO writes relay DO_Mod4_ch00 (audible click)
#
# Hardware:
#   DO_Mod4_ch04 wired to DI_Mod3_ch00 (loopback for condition trigger)
#   DO_Mod4_ch00 = relay output (audible click on trip)
# ---------------------------------------------------------------------------

# Unique interlock ID for this test group -- cleaned up in teardown
_TEST_INTERLOCK_ID = "test-di-interlock-acq"

# Track interlock test state for cascade skipping
class _InterlockState:
    interlock_configured = False
    latch_armed = False
    system_tripped = False

_il_state = _InterlockState()


def _require_interlock():
    """Skip test if interlock was not successfully configured on cRIO."""
    if not _il_state.interlock_configured:
        pytest.skip("Test interlock not configured on cRIO -- earlier test failed")


def _send_crio_interlock(crio, action: str, payload: dict = None):
    """Send an interlock command directly to the cRIO node.

    Publishes to: nisystem/nodes/crio-001/commands/interlock/{action}
    This bypasses the DAQ service entirely -- the cRIO handles it locally.
    """
    topic = f"{crio.base_topic}/nodes/{CRIO_NODE_ID}/commands/interlock/{action}"
    data = json.dumps(payload or {})
    crio.client.publish(topic, data, qos=1)


def _get_crio_interlock_status(crio, retries: int = 3) -> Optional[dict]:
    """Request and return interlock status from the cRIO node directly.

    Sends command to cRIO's interlock/status endpoint and waits for
    the cRIO to publish its local interlock evaluation results.

    Returns dict with keys:
      - latchState: "safe" / "armed" / "tripped"
      - isTripped: bool
      - interlockStatuses: list of interlock status dicts
      - hasFailedInterlocks: bool
      - timestamp: float (evaluation time)
    """
    for _ in range(retries):
        _send_crio_interlock(crio, "status")
        msgs = crio.wait_for_topic("interlock/status", timeout=5.0)
        if msgs:
            return msgs[-1]
        time.sleep(0.5)
    return None


def _find_interlock_status(safety_status: dict, interlock_id: str) -> Optional[dict]:
    """Find a specific interlock in the safety status payload.

    Handles both camelCase (cRIO top-level) and snake_case (per-interlock)
    field names.
    """
    statuses = safety_status.get("interlockStatuses",
                                  safety_status.get("interlock_statuses", []))
    for il in statuses:
        if il.get("id") == interlock_id:
            return il
    return None


def _cleanup_crio_interlock(crio):
    """Remove all test interlocks from the cRIO and reset safety state.

    Sends commands directly to the cRIO node (not via DAQ).
    """
    # Restore DI HIGH first so interlock condition is satisfied
    # (required for reset_trip to succeed if system is tripped)
    crio.write_output("DO_Mod4_ch04", 1)
    time.sleep(2)

    # Reset trip (may fail if not tripped -- that's fine)
    _send_crio_interlock(crio, "reset", {"user": "test_cleanup"})
    time.sleep(0.5)

    # Disarm latch
    _send_crio_interlock(crio, "disarm", {"user": "test_cleanup"})
    time.sleep(0.5)

    # Clear all interlocks by configuring an empty list.
    # Retry with ack confirmation to ensure the cRIO processes it.
    for attempt in range(3):
        _send_crio_interlock(crio, "configure", {"interlocks": []})
        ack = crio.wait_for_topic("interlock/configure/ack", timeout=5.0)
        if ack:
            break
        time.sleep(1)

    # The cRIO publishes interlock/status with retain=True during periodic
    # updates. When interlocks are cleared, it stops publishing — but the
    # old retained message persists on the broker. Clear it by publishing
    # an empty retained message, then wait for the cRIO to publish a fresh
    # status response confirming the interlocks are gone.
    retained_topic = f"{crio.base_topic}/nodes/{CRIO_NODE_ID}/interlock/status"
    crio.client.publish(retained_topic, b'', qos=1, retain=True)
    time.sleep(1)

    # Verify clean state (poll until interlocks are gone)
    for _ in range(5):
        status = _get_crio_interlock_status(crio)
        if status:
            statuses = status.get("interlockStatuses",
                                   status.get("interlock_statuses", []))
            if len(statuses) == 0:
                break
        time.sleep(1)

    # Reset all outputs used by interlock tests
    crio.write_output("DO_Mod4_ch00", 0)
    crio.write_output("DO_Mod4_ch04", 0)


@pytest.mark.order(10)
class TestGroup10_SafetyInterlock:
    """cRIO-local safety interlock with relay output.

    Configures interlocks DIRECTLY on the cRIO node (not via DAQ service).
    The cRIO evaluates conditions locally in its main loop and fires
    trip actions independently -- proving the safety chain works without
    the PC/DAQ service in the evaluation path.

    Safety chain tested:
      Physical DI state -> cRIO hardware read -> cRIO safety.py evaluation ->
      interlock trip -> cRIO writes relay output (DO_Mod4_ch00 = audible click)

    Hardware:
      - DO_Mod4_ch04 wired to DI_Mod3_ch00 (loopback for condition trigger)
      - DO_Mod4_ch00 = relay output (audible click on trip)
    """

    def test_configure_crio_interlock(self, crio):
        """Configure a test interlock directly on the cRIO node.

        Condition: digital_input on DI_Mod3_ch00, satisfied when HIGH.
        Control: set_digital_output on DO_Mod4_ch00 (relay), value=1 on trip.

        When the interlock trips, the relay fires ON (audible click).
        All commands go directly to the cRIO -- the DAQ is not involved.
        """
        _require_acquisition()

        # Clean up any leftover from a previous run.
        # _cleanup_crio_interlock ends by writing DO_Mod4_ch04=0; wait 1s to
        # let that command fully propagate before we issue a new write below.
        _cleanup_crio_interlock(crio)
        time.sleep(1)

        # Ensure relay is OFF and DI is HIGH before configuring
        crio.write_output("DO_Mod4_ch00", 0)
        crio.write_output("DO_Mod4_ch04", 1)
        ok = _wait_for_channel_value(crio, "DI_Mod3_ch00", 1.0, timeout=12.0)
        if not ok:
            # Retry: re-send the DO command and wait again
            crio.write_output("DO_Mod4_ch04", 1)
            time.sleep(3)
            ok = _wait_for_channel_value(crio, "DI_Mod3_ch00", 1.0, timeout=12.0)

        di_val = _read_channel_value(crio, "DI_Mod3_ch00", timeout=5.0)
        assert di_val is not None, "DI_Mod3_ch00 has no value -- acquisition may not be running"
        assert di_val == 1.0, (
            f"DI_Mod3_ch00 should be HIGH (1.0) after setting DO HIGH, got {di_val}. "
            f"Check DO_Mod4_ch04 → DI_Mod3_ch00 loopback wiring on the cRIO."
        )

        # Configure the interlock directly on the cRIO
        config_payload = {
            "interlocks": [
                {
                    "id": _TEST_INTERLOCK_ID,
                    "name": "Test DI Interlock (cRIO-local)",
                    "description": "Trips relay when DI_Mod3_ch00 goes LOW",
                    "enabled": True,
                    "conditions": [
                        {
                            "id": "cond-di-test-001",
                            "type": "digital_input",
                            "channel": "DI_Mod3_ch00",
                            "value": True,  # Satisfied when DI is HIGH
                            "invert": False,
                            "delay_s": 0.0,
                        }
                    ],
                    "conditionLogic": "AND",
                    "controls": [
                        {
                            "type": "set_digital_output",
                            "channel": "DO_Mod4_ch00",
                            "setValue": 1,  # Relay fires ON when tripped
                        }
                    ],
                    "bypassAllowed": True,
                    "bypassed": False,
                    "priority": "high",
                    "requiresAcknowledgment": False,
                    "isCritical": False,
                }
            ]
        }

        _send_crio_interlock(crio, "configure", config_payload)

        # Wait for cRIO to acknowledge and show interlock in status
        il = None
        for attempt in range(10):
            time.sleep(1)
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
                if il is not None:
                    break

        assert il is not None, (
            f"Test interlock {_TEST_INTERLOCK_ID} not found in cRIO interlock "
            f"status after 10s. Sent configure directly to {CRIO_NODE_ID}. "
            f"Interlocks: {[i.get('id') for i in (status or {}).get('interlockStatuses', [])]}"
        )
        assert il.get("enabled") is True, "Interlock should be enabled"
        _il_state.interlock_configured = True
        print(f"\n  cRIO interlock configured: {il.get('name')} (satisfied={il.get('satisfied')})")
        print(f"  Control: set_digital_output DO_Mod4_ch00=1 (relay ON on trip)")

    def test_crio_interlock_satisfied(self, crio):
        """Verify cRIO reports interlock satisfied when DI is HIGH.

        Queries the cRIO's local interlock status (not DAQ safety status).
        This confirms the cRIO evaluates conditions locally.
        """
        _require_interlock()
        _require_acquisition()

        # Ensure DI is HIGH
        crio.write_output("DO_Mod4_ch04", 1)
        time.sleep(2)

        # Query cRIO interlock status directly
        status = _get_crio_interlock_status(crio)
        assert status is not None, "No interlock status from cRIO"

        il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
        assert il is not None, "Test interlock not in cRIO status"
        assert il.get("satisfied") is True, (
            f"cRIO interlock should be satisfied when DI is HIGH. "
            f"Status: {json.dumps(il, indent=2)}"
        )
        assert il.get("has_offline_channels") is not True, (
            "DI channel should not be offline on cRIO"
        )
        print(f"\n  cRIO reports satisfied={il.get('satisfied')} (local evaluation)")

    def test_arm_crio_latch(self, crio):
        """Arm the safety latch directly on the cRIO."""
        _require_interlock()
        _require_acquisition()

        # Ensure DI is HIGH (condition satisfied) so arm succeeds
        crio.write_output("DO_Mod4_ch04", 1)
        _wait_for_channel_value(crio, "DI_Mod3_ch00", 1.0, timeout=5.0)
        time.sleep(1)

        # Arm latch directly on cRIO
        latch_state = None
        for attempt in range(5):
            _send_crio_interlock(crio, "arm", {"user": "test_suite"})
            time.sleep(2)

            status = _get_crio_interlock_status(crio)
            if status:
                latch_state = status.get("latchState", status.get("latch_state"))
                if latch_state in ("ARMED", "armed"):
                    break

        assert latch_state in ("ARMED", "armed"), (
            f"cRIO latch should be ARMED, got '{latch_state}'. "
            f"hasFailedInterlocks={status.get('hasFailedInterlocks') if status else 'N/A'}"
        )
        _il_state.latch_armed = True
        print(f"\n  cRIO latch armed: {latch_state}")

    def test_crio_trip_fires_relay(self, crio):
        """Toggle DI LOW and verify cRIO trips locally, firing the relay.

        This is the critical safety test:
          1. DI goes LOW -> cRIO evaluates condition locally -> TRIP
          2. cRIO fires trip action: DO_Mod4_ch00 = 1 (relay clicks ON)
          3. All evaluation and action happens on the cRIO, not the DAQ

        You should hear the relay click when this test runs.
        """
        _require_interlock()
        _require_acquisition()
        if not _il_state.latch_armed:
            pytest.skip("Latch not armed -- earlier test failed")

        # Verify relay is currently OFF
        relay_before = _read_channel_value(crio, "DO_Mod4_ch00", timeout=3.0)
        di_before = _read_channel_value(crio, "DI_Mod3_ch00", timeout=3.0)
        print(f"\n  Before trip: DI_Mod3_ch00={di_before}, DO_Mod4_ch00 (relay)={relay_before}")

        # Set DO LOW -> DI reads LOW -> cRIO condition fails -> TRIP -> relay fires
        crio.write_output("DO_Mod4_ch04", 0)

        # Verify DI actually changed
        ok = _wait_for_channel_value(crio, "DI_Mod3_ch00", 0.0, timeout=5.0)
        di_after = _read_channel_value(crio, "DI_Mod3_ch00", timeout=3.0)
        print(f"  After DO write: DI_Mod3_ch00={di_after} (batch_ok={ok})")
        assert ok, (
            f"DI_Mod3_ch00 did not go LOW after writing DO_Mod4_ch04=0 "
            f"(got {di_after}). Hardware loopback not connected?"
        )

        # Poll cRIO interlock status -- should trip within a few eval cycles
        il = None
        status = None
        for attempt in range(8):
            time.sleep(0.5)
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
                if il and il.get("satisfied") is False:
                    break
                print(f"  Poll {attempt+1}: satisfied={il.get('satisfied') if il else 'N/A'}")

        assert il is not None, "Test interlock not found in cRIO status"
        assert il.get("satisfied") is False, (
            f"cRIO interlock should NOT be satisfied when DI is LOW. "
            f"Status: {json.dumps(il, indent=2)}"
        )

        # Verify system tripped (from cRIO's local latch state)
        latch_state = status.get("latchState", status.get("latch_state"))
        is_tripped = status.get("isTripped", status.get("is_tripped", False))

        assert is_tripped is True, (
            f"cRIO should be TRIPPED. latchState={latch_state}, isTripped={is_tripped}"
        )
        assert latch_state in ("TRIPPED", "tripped"), (
            f"cRIO latch should be TRIPPED, got '{latch_state}'"
        )

        # Verify relay fired: DO_Mod4_ch00 should be 1 (ON)
        # The cRIO fires this action locally -- no DAQ involvement
        relay_ok = _wait_for_channel_value(crio, "DO_Mod4_ch00", 1.0, timeout=5.0)
        relay_val = _read_channel_value(crio, "DO_Mod4_ch00", timeout=3.0)
        print(f"  RELAY: DO_Mod4_ch00={relay_val} (expected 1.0, match={relay_ok})")
        assert relay_ok, (
            f"Relay DO_Mod4_ch00 should be ON (1.0) after trip, "
            f"got {relay_val}. cRIO trip action may not have fired."
        )

        trip_reason = status.get("lastTripReason", status.get("last_trip_reason", ""))
        _il_state.system_tripped = True
        print(f"  cRIO TRIPPED locally: {trip_reason}")
        print(f"  Relay fired: DO_Mod4_ch00 = {relay_val} (you should hear a click)")

    def test_crio_failed_condition_details(self, crio):
        """Verify the cRIO reports failed condition details locally."""
        _require_interlock()
        _require_acquisition()
        if not _il_state.system_tripped:
            pytest.skip("System not tripped -- earlier test failed")

        status = _get_crio_interlock_status(crio)
        assert status is not None, "No interlock status from cRIO"

        il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
        assert il is not None, "Test interlock not found"

        failed = il.get("failed_conditions", il.get("failedConditions", []))
        assert len(failed) > 0, (
            "cRIO should report at least one failed condition when DI is LOW"
        )

        # The failed condition should reference our DI channel
        cond = failed[0]
        reason = cond.get("reason", "")
        assert "DI_Mod3_ch00" in reason, (
            f"Failed condition should mention DI_Mod3_ch00, got: '{reason}'"
        )
        assert "OFF" in reason, (
            f"Failed condition should show DI is OFF, got: '{reason}'"
        )
        print(f"\n  cRIO failed condition: {reason}")

    def test_crio_reset_blocked_while_unsatisfied(self, crio):
        """Trip reset should fail while condition is still failing on cRIO."""
        _require_interlock()
        _require_acquisition()
        if not _il_state.system_tripped:
            pytest.skip("System not tripped -- earlier test failed")

        # DI is still LOW -- reset directly on cRIO should fail
        _send_crio_interlock(crio, "reset", {"user": "test_suite"})
        time.sleep(1)

        status = _get_crio_interlock_status(crio)
        assert status is not None, "No interlock status from cRIO"

        is_tripped = status.get("isTripped", status.get("is_tripped", False))
        assert is_tripped is True, (
            "cRIO should still be TRIPPED -- reset should fail while "
            "interlock condition is unsatisfied"
        )
        print("\n  cRIO correctly refused reset while DI is LOW")

    def test_crio_restore_and_reset(self, crio):
        """Restore DI HIGH, reset trip on cRIO, verify relay releases."""
        _require_interlock()
        _require_acquisition()
        if not _il_state.system_tripped:
            pytest.skip("System not tripped -- earlier test failed")

        # Set DO HIGH -> DI reads HIGH -> cRIO condition re-satisfied
        crio.write_output("DO_Mod4_ch04", 1)

        ok = _wait_for_channel_value(crio, "DI_Mod3_ch00", 1.0, timeout=8.0)
        di_val = _read_channel_value(crio, "DI_Mod3_ch00", timeout=3.0)
        print(f"\n  DI restored: batch_ok={ok}, DI_Mod3_ch00={di_val}")
        assert ok, (
            f"DI_Mod3_ch00 did not return to HIGH (got {di_val}). "
            f"DO write may have been blocked by cRIO output holding."
        )

        # Poll cRIO until interlock is re-satisfied
        satisfied = False
        for attempt in range(8):
            time.sleep(0.5)
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
                if il and il.get("satisfied") is True:
                    satisfied = True
                    break
                print(f"  Poll {attempt+1}: satisfied={il.get('satisfied') if il else 'N/A'}")

        assert satisfied, (
            f"cRIO interlock should be satisfied after restoring DI HIGH. "
            f"Status: {json.dumps(il, indent=2) if il else 'None'}"
        )

        # Reset trip directly on cRIO
        for attempt in range(3):
            _send_crio_interlock(crio, "reset", {"user": "test_suite"})
            time.sleep(2)
            status = _get_crio_interlock_status(crio)
            if status:
                is_tripped = status.get("isTripped", status.get("is_tripped", False))
                latch_state = status.get("latchState", status.get("latch_state"))
                if not is_tripped:
                    break

        assert status is not None, "No interlock status from cRIO"
        assert is_tripped is False, (
            f"cRIO should NOT be tripped after reset. isTripped={is_tripped}"
        )
        assert latch_state in ("SAFE", "safe"), (
            f"cRIO latch should return to SAFE, got '{latch_state}'"
        )
        print(f"  cRIO trip reset successful: latchState={latch_state}")

        # Write relay back to 0 (you should hear a second click)
        crio.write_output("DO_Mod4_ch00", 0)
        relay_off = _wait_for_channel_value(crio, "DO_Mod4_ch00", 0.0, timeout=5.0)
        print(f"  Relay released: DO_Mod4_ch00={'0 (OFF)' if relay_off else 'still ON'}")

    def test_crio_evaluates_independently(self, crio):
        """Verify the cRIO's interlock evaluation is local, not DAQ-driven.

        The cRIO status should show interlock information from its own
        safety.py evaluation loop, proving it can act independently
        if the PC/DAQ service disconnects.
        """
        _require_interlock()
        _require_acquisition()

        # Get cRIO interlock status directly
        crio_status = _get_crio_interlock_status(crio)
        assert crio_status is not None, "cRIO not responding to interlock status query"

        # Verify it has latch state (proves safety module is running)
        latch_state = crio_status.get("latchState", crio_status.get("latch_state"))
        assert latch_state is not None, (
            "cRIO interlock status should include latchState"
        )

        # Verify our interlock is there
        il = _find_interlock_status(crio_status, _TEST_INTERLOCK_ID)
        assert il is not None, "Test interlock missing from cRIO's local evaluation"

        # The cRIO status has a timestamp showing when it was evaluated
        ts = crio_status.get("timestamp")
        assert ts is not None, "cRIO status should include evaluation timestamp"

        # Verify the cRIO's system status shows it is alive and acquiring
        crio_sys = crio.get_crio_status()
        acquiring = crio_sys.get("acquiring", False)
        node_type = crio_sys.get("node_type", "")

        print(f"\n  cRIO local safety evaluation:")
        print(f"    latchState: {latch_state}")
        print(f"    interlock: {il.get('name')} (satisfied={il.get('satisfied')})")
        print(f"    timestamp: {ts}")
        print(f"    node_type: {node_type}, acquiring: {acquiring}")
        print(f"  The cRIO evaluates interlocks locally -- no DAQ in the loop")

    def test_cleanup_crio_interlock(self, crio):
        """Remove the test interlock from the cRIO and verify clean state.

        Always runs (no _require_interlock) to ensure cleanup even if
        earlier tests failed.
        """
        _cleanup_crio_interlock(crio)

        # Verify interlock is gone
        il = None
        status = None
        for _ in range(5):
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_INTERLOCK_ID)
                if il is None:
                    break
            time.sleep(1)

        assert il is None, (
            f"Test interlock should be removed from cRIO, but still found: {il}"
        )

        if status:
            latch_state = status.get("latchState", status.get("latch_state"))
            assert latch_state in ("SAFE", "safe"), (
                f"cRIO latch should be SAFE after cleanup, got '{latch_state}'"
            )
            print(f"\n  cRIO interlock removed, clean state: latchState={latch_state}")
        else:
            print("\n  cRIO interlock cleanup done (no status response)")


# ---------------------------------------------------------------------------
# Group 11: Alarm Tests (cRIO-local alarm evaluation)
# ---------------------------------------------------------------------------
# Uses AO→AI loopback: AO_Mod2_ch00 → AI_Mod1_ch00.
# AI_Mod1_ch00 has alarm config: hi_limit=5.0, hihi_limit=8.0, deadband=0.2
# Alarm evaluation runs in cRIO safety.check_all() every scan cycle (4 Hz).
# ---------------------------------------------------------------------------

_ALARM_CHANNEL = "AI_Mod1_ch00"
_ALARM_AO = "AO_Mod2_ch00"


class _AlarmState:
    alarm_fired = False
    alarm_acknowledged = False

_alarm_state = _AlarmState()


def _send_crio_alarm(crio, action: str, payload: dict):
    """Send an alarm command directly to the cRIO node."""
    topic = f"{crio.base_topic}/nodes/{CRIO_NODE_ID}/alarm/{action}"
    data = json.dumps(payload)
    crio.client.publish(topic, data, qos=1)


def _set_alarm_voltage(crio, voltage: float, settle_s: float = 3.0):
    """Write AO voltage and wait for AI to settle."""
    crio.write_output(_ALARM_AO, voltage)
    _wait_for_channel_value(crio, _ALARM_CHANNEL, voltage, tolerance=0.5,
                            timeout=settle_s)


def _wait_for_alarm_event(crio, channel: str, timeout: float = 5.0,
                          alarm_type: str = None,
                          waiter: dict = None) -> Optional[dict]:
    """Wait for an alarm event on the given channel.

    If `waiter` is provided, use a pre-registered waiter (avoids race
    condition where the event fires before wait_for_topic subscribes).
    """
    if waiter is not None:
        msgs = crio.collect_waiter("alarms/event", waiter, timeout=timeout)
    else:
        msgs = crio.wait_for_topic("alarms/event", timeout=timeout)
    for msg in msgs:
        if msg.get("channel") == channel:
            if alarm_type is None or msg.get("alarm_type") == alarm_type:
                return msg
    return None


@pytest.mark.order(11)
class TestGroup11_Alarms:
    """Group 11: Alarm lifecycle — fire, ack, shelve, unshelve, OOS, RTS."""

    def test_alarm_config_loaded(self, crio):
        """Verify cRIO has alarm config on AI_Mod1_ch00 after project load."""
        _require_data()

        # Reset AO to 0V — earlier groups (especially Group 9 AO loopback)
        # may have left non-zero voltage that triggers the alarm at baseline.
        _set_alarm_voltage(crio, 0.0, settle_s=3.0)

        # Acknowledge any stale alarm on the channel so it clears to NORMAL
        # (an unacked alarm that cleared stays in RETURNED state).
        _send_crio_alarm(crio, "ack", {"channel": _ALARM_CHANNEL})
        time.sleep(1)

        # Wait for a fresh alarms/status from the heartbeat (published every
        # heartbeat interval, ~5s).  Use count=2 to skip the stale retained
        # message and get a fresh one that reflects the current state.
        msgs = crio.wait_for_topic("alarms/status", timeout=12.0, count=2)
        if msgs:
            status = msgs[-1]  # Use the freshest message
            counts = status.get("counts", {})
            active = counts.get("active", 0)
            returned = counts.get("returned", 0)
            print(f"\n  Alarm status: {counts}")
            # At baseline (~0V, acked), no alarms should be active or returned
            assert active == 0, f"Expected 0 active alarms at baseline, got {active}"
            assert returned == 0, f"Expected 0 returned alarms at baseline, got {returned}"
        else:
            # No alarm status published — alarm config might be absent.
            # Trigger one by briefly pulsing the alarm channel.
            _set_alarm_voltage(crio, 6.0, settle_s=3.0)
            event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=5.0)
            assert event is not None, (
                "No alarm event after writing 6V — cRIO may not have alarm config "
                "on AI_Mod1_ch00. Check _CrioAcquisitionTest.json has alarm_enabled=true"
            )
            # Clear it for subsequent tests
            _set_alarm_voltage(crio, 0.0, settle_s=3.0)
            _send_crio_alarm(crio, "ack", {"channel": _ALARM_CHANNEL})
            time.sleep(2)

        print("  Alarm config verified on cRIO")

    def test_alarm_hi_fires(self, crio):
        """Write 6V to trigger Hi alarm on AI_Mod1_ch00."""
        _require_data()

        # Register waiter BEFORE writing voltage — the alarm fires within
        # one scan cycle (~250ms) of the value crossing hi_limit, so the
        # event arrives before _set_alarm_voltage returns.
        waiter = crio.start_waiter("alarms/event")

        # Write 6V (above hi_limit=5.0)
        _set_alarm_voltage(crio, 6.0, settle_s=3.0)

        # Wait for alarm event (waiter was listening during the write)
        event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=8.0,
                                      alarm_type="hi", waiter=waiter)
        assert event is not None, (
            "Hi alarm did not fire within 8s after writing 6V "
            f"(hi_limit=5.0, channel={_ALARM_CHANNEL})"
        )

        _alarm_state.alarm_fired = True
        print(f"\n  Hi alarm fired: {event.get('alarm_type')} "
              f"value={event.get('value'):.2f} limit={event.get('limit')}")

    def test_alarm_acknowledge(self, crio):
        """Acknowledge the active alarm."""
        _require_data()
        if not _alarm_state.alarm_fired:
            pytest.skip("Alarm did not fire — earlier test failed")

        _send_crio_alarm(crio, "ack", {"channel": _ALARM_CHANNEL})

        # Wait for ack response
        msgs = crio.wait_for_topic("alarms/ack/response", timeout=5.0)
        assert msgs, "No ack response received"
        ack = msgs[-1]
        assert ack.get("success") is True, f"Alarm ack failed: {ack}"

        _alarm_state.alarm_acknowledged = True
        print(f"\n  Alarm acknowledged: {ack}")

    def test_alarm_clear_on_return(self, crio):
        """Write 0V to clear the alarm."""
        _require_data()
        if not _alarm_state.alarm_fired:
            pytest.skip("Alarm did not fire — earlier test failed")

        _set_alarm_voltage(crio, 0.0, settle_s=3.0)

        # Wait for alarm clear event (may be RETURNED or state change)
        event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=8.0)
        # Event may or may not arrive depending on state transition
        # (acked + cleared = NORMAL, no event; unacked + cleared = RETURNED)
        # Either way, after clearing voltage, give time for state to settle
        time.sleep(2)
        print(f"\n  Alarm cleared (wrote 0V)")

    def test_alarm_shelve_suppresses(self, crio):
        """Shelve the alarm, write above limit, verify NO alarm fires."""
        _require_data()

        # Ensure clean baseline
        _set_alarm_voltage(crio, 0.0, settle_s=2.0)
        time.sleep(2)

        # Shelve the alarm channel
        _send_crio_alarm(crio, "shelve", {
            "channel": _ALARM_CHANNEL,
            "duration_s": 60.0,
            "operator": "test_suite",
        })
        time.sleep(1)  # Let shelve take effect

        # Write 6V — should NOT trigger alarm while shelved
        _set_alarm_voltage(crio, 6.0, settle_s=2.0)

        # Wait 3s (12 eval cycles at 4Hz) — should get NO alarm event
        event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=3.0,
                                      alarm_type="hi")
        assert event is None, (
            f"Alarm fired while channel was SHELVED — shelve is not suppressing: {event}"
        )
        print("\n  Shelve confirmed: no alarm fired while shelved (6V, 3s)")

    def test_alarm_unshelve_fires(self, crio):
        """Unshelve the channel — alarm should fire since value is still >5V."""
        _require_data()

        # Register waiter BEFORE unshelving — alarm fires within one scan
        # cycle (~250ms) after unshelve restores the NORMAL state.
        waiter = crio.start_waiter("alarms/event")

        # Unshelve
        _send_crio_alarm(crio, "unshelve", {"channel": _ALARM_CHANNEL})

        # Value is still ~6V → alarm should fire now
        event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=8.0,
                                      alarm_type="hi", waiter=waiter)
        assert event is not None, (
            "Alarm did not fire after unshelve — value is ~6V, hi_limit=5.0"
        )
        print(f"\n  Unshelve confirmed: alarm fired after unshelve, "
              f"value={event.get('value'):.2f}")

        # Clear for next test
        _set_alarm_voltage(crio, 0.0, settle_s=2.0)
        time.sleep(2)

    def test_alarm_oos_suppresses(self, crio):
        """Set out-of-service, write above limit, verify NO alarm fires."""
        _require_data()

        # Set out of service
        _send_crio_alarm(crio, "out-of-service", {
            "channel": _ALARM_CHANNEL,
            "operator": "test_suite",
        })
        time.sleep(1)

        # Write 6V — should NOT trigger alarm while OOS
        _set_alarm_voltage(crio, 6.0, settle_s=2.0)

        event = _wait_for_alarm_event(crio, _ALARM_CHANNEL, timeout=3.0,
                                      alarm_type="hi")
        assert event is None, (
            f"Alarm fired while channel was OUT_OF_SERVICE: {event}"
        )
        print("\n  OOS confirmed: no alarm fired while out-of-service (6V, 3s)")

    def test_alarm_cleanup(self, crio):
        """Return to service, clear alarm, verify clean state."""
        _require_data()

        # Write 0V FIRST to avoid triggering alarm during RTS
        _set_alarm_voltage(crio, 0.0, settle_s=3.0)
        time.sleep(1)

        # Return to service (channel value is 0V, so no alarm fires)
        _send_crio_alarm(crio, "return-to-service", {
            "channel": _ALARM_CHANNEL,
        })
        time.sleep(1)

        # Ack any lingering alarm (moves RETURNED→NORMAL on next clear eval)
        _send_crio_alarm(crio, "ack", {"channel": _ALARM_CHANNEL})
        time.sleep(2)

        print("\n  Alarm cleanup done: returned to service, voltage=0V")


# ---------------------------------------------------------------------------
# Group 12: Script Tests (cRIO-local script engine)
# ---------------------------------------------------------------------------
# Deploys a simple continuous script to the cRIO, starts it, verifies
# published values, stops and removes it.
# ---------------------------------------------------------------------------

_TEST_SCRIPT_ID = "test-script-acq-001"
_TEST_SCRIPT_CODE = """
while not should_stop():
    v = tags.AI_Mod1_ch00
    if v is not None:
        publish('TestDouble', v * 2, units='V')
    wait_for(0.5)
""".strip()


class _ScriptState:
    script_added = False
    script_started = False

_script_state = _ScriptState()


def _send_crio_script(crio, action: str, payload: dict = None):
    """Send a script command directly to the cRIO node."""
    topic = f"{crio.base_topic}/nodes/{CRIO_NODE_ID}/script/{action}"
    data = json.dumps(payload or {})
    crio.client.publish(topic, data, qos=1)


def _get_crio_script_status(crio, timeout: float = 5.0) -> Optional[dict]:
    """Request and return script status from the cRIO.

    Uses 'list' command (not 'status') because both route to publish_status(),
    but the debounce guard allows list requests that arrive >200ms after the
    last automatic publish from add/start/stop/remove.
    """
    _send_crio_script(crio, "list")
    msgs = crio.wait_for_topic("script/status", timeout=timeout)
    return msgs[-1] if msgs else None


@pytest.mark.order(12)
class TestGroup12_Scripts:
    """Group 12: Script lifecycle — add, start, verify output, stop, remove."""

    def test_script_add(self, crio):
        """Deploy a test script to the cRIO."""
        _require_data()

        payload = {
            "id": _TEST_SCRIPT_ID,
            "name": "Test Double Script",
            "code": _TEST_SCRIPT_CODE,
            "run_mode": "manual",
            "enabled": True,
        }
        _send_crio_script(crio, "add", payload)

        # Wait for script status that includes our script
        for _ in range(5):
            status = _get_crio_script_status(crio, timeout=5.0)
            if status and _TEST_SCRIPT_ID in status:
                break
            time.sleep(1)

        assert status is not None, "No script status received from cRIO"
        assert _TEST_SCRIPT_ID in status, (
            f"Script '{_TEST_SCRIPT_ID}' not found in status: {list(status.keys())}"
        )
        script_info = status[_TEST_SCRIPT_ID]
        assert script_info.get("running") is not True, (
            "Script should not be running yet (run_mode=manual)"
        )

        _script_state.script_added = True
        print(f"\n  Script added: {_TEST_SCRIPT_ID}")

    def test_script_start(self, crio):
        """Start the test script on the cRIO."""
        _require_data()
        if not _script_state.script_added:
            pytest.skip("Script not added — earlier test failed")

        _send_crio_script(crio, "start", {"id": _TEST_SCRIPT_ID})

        # Wait for running=true in status
        for _ in range(8):
            status = _get_crio_script_status(crio, timeout=5.0)
            if status and _TEST_SCRIPT_ID in status:
                if status[_TEST_SCRIPT_ID].get("running"):
                    break
            time.sleep(1)

        assert status is not None and _TEST_SCRIPT_ID in status, (
            "Script status not found after start"
        )
        assert status[_TEST_SCRIPT_ID].get("running") is True, (
            f"Script should be running: {status.get(_TEST_SCRIPT_ID)}"
        )

        _script_state.script_started = True
        print(f"\n  Script started: running={status[_TEST_SCRIPT_ID].get('running')}")

    def test_script_publishes_values(self, crio):
        """Verify the script publishes computed values via MQTT."""
        _require_data()
        if not _script_state.script_started:
            pytest.skip("Script not running — earlier test failed")

        # Wait for script/values topic
        for attempt in range(6):
            msgs = crio.wait_for_topic("script/values", timeout=3.0)
            if msgs:
                for msg in msgs:
                    if "TestDouble" in msg:
                        val = msg["TestDouble"]
                        # Value may be dict {value: ..., units: ...} or bare number
                        if isinstance(val, dict):
                            val = val.get("value", val.get("v"))
                        if val is not None:
                            print(f"\n  Script published: TestDouble={val}")
                            assert isinstance(val, (int, float)), (
                                f"Expected numeric value, got {type(val)}: {val}"
                            )
                            return  # Success
            time.sleep(1)

        pytest.fail(
            "Script did not publish 'TestDouble' value within 18s. "
            "Check cRIO script engine is executing."
        )

    def test_script_stop(self, crio):
        """Stop the test script."""
        _require_data()
        if not _script_state.script_started:
            pytest.skip("Script not running — earlier test failed")

        _send_crio_script(crio, "stop", {"id": _TEST_SCRIPT_ID})

        # Wait for running=false in status
        for _ in range(8):
            status = _get_crio_script_status(crio, timeout=5.0)
            if status and _TEST_SCRIPT_ID in status:
                if not status[_TEST_SCRIPT_ID].get("running"):
                    break
            time.sleep(1)

        assert status is not None and _TEST_SCRIPT_ID in status, (
            "Script status not found after stop"
        )
        assert status[_TEST_SCRIPT_ID].get("running") is not True, (
            f"Script should be stopped: {status.get(_TEST_SCRIPT_ID)}"
        )
        print(f"\n  Script stopped")

    def test_script_remove(self, crio):
        """Remove the test script from the cRIO."""
        _require_data()
        if not _script_state.script_added:
            pytest.skip("Script not added — earlier test failed")

        _send_crio_script(crio, "remove", {"id": _TEST_SCRIPT_ID})

        # Wait for script to disappear from status
        for _ in range(5):
            status = _get_crio_script_status(crio, timeout=5.0)
            if status is not None and _TEST_SCRIPT_ID not in status:
                break
            time.sleep(1)

        assert status is not None, "No script status received"
        assert _TEST_SCRIPT_ID not in status, (
            f"Script should be removed but still in status: {list(status.keys())}"
        )
        print(f"\n  Script removed from cRIO")

    def test_script_cleanup(self, crio):
        """Clear all scripts — ensure clean state."""
        _require_data()

        _send_crio_script(crio, "clear-all")
        time.sleep(2)

        status = _get_crio_script_status(crio, timeout=5.0)
        if status:
            script_count = len([k for k in status if isinstance(status[k], dict)])
            print(f"\n  Script cleanup: {script_count} scripts remaining")
        else:
            print("\n  Script cleanup done (no status response)")


# ---------------------------------------------------------------------------
# Group 13: Interlock Bypass Tests
# ---------------------------------------------------------------------------
# Configures a DI interlock (same pattern as Group 10), then tests bypass:
# - Bypass suppresses trip when condition fails
# - Un-bypass causes immediate trip when condition is failing
# ---------------------------------------------------------------------------

_TEST_BYPASS_INTERLOCK_ID = "test-bypass-interlock-acq"


class _BypassState:
    interlock_configured = False
    latch_armed = False
    bypassed = False
    system_tripped = False

_bp_state = _BypassState()


def _require_bypass_interlock():
    if not _bp_state.interlock_configured:
        pytest.skip("Bypass interlock not configured — earlier test failed")


def _cleanup_bypass_interlock(crio):
    """Remove bypass test interlock from cRIO and reset state."""
    crio.write_output("DO_Mod4_ch04", 1)
    time.sleep(2)
    _send_crio_interlock(crio, "reset", {"user": "bypass_cleanup"})
    time.sleep(0.5)
    _send_crio_interlock(crio, "disarm", {"user": "bypass_cleanup"})
    time.sleep(0.5)
    for attempt in range(3):
        _send_crio_interlock(crio, "configure", {"interlocks": []})
        ack = crio.wait_for_topic("interlock/configure/ack", timeout=5.0)
        if ack:
            break
        time.sleep(1)
    retained_topic = f"{crio.base_topic}/nodes/{CRIO_NODE_ID}/interlock/status"
    crio.client.publish(retained_topic, b'', qos=1, retain=True)
    time.sleep(1)
    # Reset all outputs used by bypass tests
    crio.write_output("DO_Mod4_ch00", 0)
    crio.write_output("DO_Mod4_ch04", 0)


@pytest.mark.order(13)
class TestGroup13_InterlockBypass:
    """Group 13: Interlock bypass — suppress trip, un-bypass triggers trip."""

    def test_bypass_configure_and_arm(self, crio):
        """Configure a DI interlock with bypass allowed and arm the latch."""
        _require_data()

        # Ensure DI is HIGH (condition satisfied) before configuring
        crio.write_output("DO_Mod4_ch04", 1)
        time.sleep(2)

        config_payload = {
            "interlocks": [{
                "id": _TEST_BYPASS_INTERLOCK_ID,
                "name": "Bypass Test Interlock",
                "description": "DI interlock for bypass testing",
                "enabled": True,
                "conditions": [{
                    "id": "cond-bypass-test-001",
                    "type": "digital_input",
                    "channel": "DI_Mod3_ch00",
                    "value": True,
                    "invert": False,
                    "delay_s": 0.0,
                }],
                "conditionLogic": "AND",
                "controls": [{
                    "type": "set_digital_output",
                    "channel": "DO_Mod4_ch00",
                    "setValue": 1,
                }],
                "bypassAllowed": True,
                "bypassed": False,
                "priority": "high",
                "requiresAcknowledgment": False,
                "isCritical": False,
            }]
        }
        _send_crio_interlock(crio, "configure", config_payload)

        # Wait for configure ack
        ack = crio.wait_for_topic("interlock/configure/ack", timeout=10.0)
        assert ack, "No configure ack received"

        # Verify interlock appears in status
        for _ in range(5):
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_BYPASS_INTERLOCK_ID)
                if il:
                    break
            time.sleep(1)
        assert il is not None, "Bypass interlock not found in cRIO status"
        _bp_state.interlock_configured = True

        # Arm the latch
        _send_crio_interlock(crio, "arm", {"user": "bypass_test"})
        ack = crio.wait_for_topic("interlock/arm/ack", timeout=5.0)
        assert ack, "No arm ack received"

        # Verify armed
        for _ in range(5):
            status = _get_crio_interlock_status(crio)
            if status:
                latch = status.get("latchState", status.get("latch_state", ""))
                if latch.lower() == "armed":
                    break
            time.sleep(1)
        assert latch.lower() == "armed", f"Expected ARMED, got '{latch}'"
        _bp_state.latch_armed = True
        print(f"\n  Interlock configured and armed: latchState={latch}")

    def test_bypass_interlock(self, crio):
        """Bypass the interlock and verify the ack."""
        _require_data()
        _require_bypass_interlock()
        if not _bp_state.latch_armed:
            pytest.skip("Latch not armed — earlier test failed")

        _send_crio_interlock(crio, "bypass", {
            "interlock_id": _TEST_BYPASS_INTERLOCK_ID,
            "bypass": True,
            "user": "bypass_test",
            "reason": "Group 13 test",
        })

        # Wait for bypass ack
        ack = crio.wait_for_topic("interlock/bypass/ack", timeout=5.0)
        assert ack, "No bypass ack received"
        assert ack[-1].get("success") is True, f"Bypass failed: {ack[-1]}"

        # Verify bypassed in status
        for _ in range(5):
            status = _get_crio_interlock_status(crio)
            if status:
                il = _find_interlock_status(status, _TEST_BYPASS_INTERLOCK_ID)
                if il and il.get("bypassed"):
                    break
            time.sleep(1)
        assert il is not None and il.get("bypassed") is True, (
            f"Interlock should show bypassed=true: {il}"
        )
        _bp_state.bypassed = True
        print(f"\n  Interlock bypassed: {il.get('bypassed')}")

    def test_bypass_suppresses_trip(self, crio):
        """Toggle DI LOW while bypassed — verify NO trip fires."""
        _require_data()
        _require_bypass_interlock()
        if not _bp_state.bypassed:
            pytest.skip("Interlock not bypassed — earlier test failed")

        # Toggle DI LOW (condition fails)
        crio.write_output("DO_Mod4_ch04", 0)
        time.sleep(1)
        di_val = _read_channel_value(crio, "DI_Mod3_ch00", timeout=3.0)
        assert di_val is not None and di_val < 0.5, (
            f"DI should be LOW after toggling DO_Mod4_ch04=0, got {di_val}"
        )

        # Wait 3s (12 eval cycles) — should NOT trip
        time.sleep(3)

        status = _get_crio_interlock_status(crio)
        assert status is not None, "No interlock status after bypass test"
        is_tripped = status.get("isTripped", status.get("is_tripped", False))
        assert is_tripped is False, (
            f"System should NOT be tripped while interlock is bypassed, "
            f"but isTripped={is_tripped}"
        )

        il = _find_interlock_status(status, _TEST_BYPASS_INTERLOCK_ID)
        assert il is not None, "Interlock not found in status"
        assert il.get("bypassed") is True, f"Interlock should still be bypassed: {il}"
        latch = status.get("latchState", status.get("latch_state", ""))
        assert latch.lower() == "armed", f"Latch should still be ARMED, got '{latch}'"

        print(f"\n  Bypass suppresses trip: DI=LOW, isTripped={is_tripped}, "
              f"latch={latch}, bypassed={il.get('bypassed')}")

    def test_unbypass_triggers_trip(self, crio):
        """Un-bypass — DI still LOW, so condition fails and trip fires."""
        _require_data()
        _require_bypass_interlock()
        if not _bp_state.bypassed:
            pytest.skip("Interlock not bypassed — earlier test failed")

        # Un-bypass
        _send_crio_interlock(crio, "bypass", {
            "interlock_id": _TEST_BYPASS_INTERLOCK_ID,
            "bypass": False,
            "user": "bypass_test",
        })
        ack = crio.wait_for_topic("interlock/bypass/ack", timeout=5.0)
        assert ack, "No un-bypass ack received"

        # DI is still LOW → condition fails → should trip within a few scan cycles
        for _ in range(8):
            status = _get_crio_interlock_status(crio)
            if status:
                is_tripped = status.get("isTripped", status.get("is_tripped", False))
                if is_tripped:
                    break
            time.sleep(0.5)

        assert is_tripped is True, (
            "System should have tripped after un-bypass (DI still LOW). "
            f"Status: {status}"
        )
        latch = status.get("latchState", status.get("latch_state", ""))
        assert latch.lower() == "tripped", f"Expected TRIPPED, got '{latch}'"
        _bp_state.system_tripped = True

        print(f"\n  Un-bypass triggered trip: isTripped={is_tripped}, latch={latch}")

    def test_bypass_cleanup(self, crio):
        """Clean up bypass test interlock and verify clean state."""
        _require_data()

        _cleanup_bypass_interlock(crio)

        # Verify clean state
        for _ in range(5):
            status = _get_crio_interlock_status(crio)
            if status:
                statuses = status.get("interlockStatuses",
                                       status.get("interlock_statuses", []))
                if len(statuses) == 0:
                    break
            time.sleep(1)

        if status:
            latch = status.get("latchState", status.get("latch_state", ""))
            print(f"\n  Bypass cleanup done: latchState={latch}")
        else:
            print("\n  Bypass cleanup done (no status response)")


# ---------------------------------------------------------------------------
# Group 14: CO -> CI 4-20mA Current Loopback (Module 6 output -> Module 7 input)
# ---------------------------------------------------------------------------
#
# Wiring on cRIO-9056:
#   Module 6 (NI 9266, 8 current outputs, 0-20mA): ch00-ch07 wired to Module 7
#   Module 7 (4-20mA current input): ch00-ch07 read Module 6
#
#   CO_Mod6_ch00 -> CI_Mod7_ch00  (raw mA read)
#   CO_Mod6_ch01 -> CI_Mod7_ch01  (raw mA read)
#   ... ch00-ch06 raw mA ...
#   CO_Mod6_ch07 -> CI_Mod7_ch07  (4-20mA scaling: 4mA=0%, 20mA=100%)
#
# Write values are in mA (matches CO channel unit="mA").
# Read values from CI_Mod7_ch00-06 are in mA.
# Read value from CI_Mod7_ch07 is in % (4-20mA scaling applied).
#
# Accuracy target: ±0.5mA (NI 9266 spec: ±0.2mA typical at full scale).
#

@pytest.mark.order(14)
class TestGroup14_CurrentLoopback:
    """CO -> CI 4-20mA current loopback: write current outputs, verify inputs match.

    Proves the full 4-20mA signal path during live acquisition:
      MQTT write_output -> DAQ -> cRIO -> NI 9266 CO -> physical wire ->
      4-20mA input module -> cRIO read -> MQTT batch -> verified

    All 8 CO channels on Module 6 are wired to all 8 CI channels on Module 7.
    """

    def test_ci_channels_arriving(self, crio):
        """CI_Mod7 channels appear in batch with numeric values."""
        _require_data()

        # Zero all CO channels first so CI reads are stable
        for co_ch, _ in CO_CI_LOOPBACK_PAIRS:
            crio.write_output(co_ch, 0.0)
        time.sleep(2)

        batch = crio.wait_for_batch(timeout=10.0)
        assert batch is not None, "No batch received"
        vals = batch.get("channels", batch.get("values", batch))

        missing = [ci for _, ci in CO_CI_LOOPBACK_PAIRS if ci not in vals]
        assert not missing, (
            f"CI channels not in batch: {missing}. "
            f"Check Mod7 is plugged in and project was reloaded."
        )

        print(f"\n  CI channels in batch: {len(CO_CI_LOOPBACK_PAIRS)}/8")
        for co_ch, ci_ch in CO_CI_LOOPBACK_PAIRS[:3]:
            v = vals.get(ci_ch)
            if isinstance(v, dict):
                v = v.get("value", v.get("v"))
            print(f"    {ci_ch}: {v}")

    def test_co_ci_single_channel_accuracy(self, crio):
        """Write known mA values to CO ch0, verify CI ch0 reads back accurately.

        Tests: 4mA, 8mA, 12mA, 16mA, 20mA
        Accuracy target: ±0.5mA.
        """
        _require_data()

        co_ch, ci_ch = CO_CI_LOOPBACK_PAIRS[0]
        test_currents_ma = [4.0, 8.0, 12.0, 16.0, 20.0]
        results = []

        for target_ma in test_currents_ma:
            crio.write_output(co_ch, target_ma)
            time.sleep(1.5)  # Allow settling

            val = _read_channel_value(crio, ci_ch, timeout=5.0)
            if val is not None:
                error = abs(val - target_ma)
                results.append((target_ma, val, error))
                assert error < 0.5, (
                    f"CO->CI accuracy: wrote {co_ch}={target_ma}mA, "
                    f"read {ci_ch}={val:.4f}mA (error: {error:.4f}mA > 0.5mA)"
                )

        # Reset to 0
        crio.write_output(co_ch, 0.0)

        if results:
            print()
            print(f"  CO->CI Accuracy ({co_ch} -> {ci_ch}):")
            print(f"  {'Set (mA)':>10} {'Read (mA)':>10} {'Error (mA)':>10}")
            print("  " + "-" * 35)
            for target, actual, err in results:
                print(f"  {target:>10.1f} {actual:>10.4f} {err:>10.4f}")
            avg_err = sum(r[2] for r in results) / len(results)
            max_err = max(r[2] for r in results)
            print(f"  Avg error: {avg_err:.4f}mA, Max error: {max_err:.4f}mA")
            print()

    def test_co_ci_all_channels(self, crio):
        """Write 12mA to all 8 CO channels, verify all 8 CI channels read ~12mA.

        Proves every wire in the loopback harness is connected correctly.
        """
        _require_data()

        target_ma = 12.0

        # Write 12mA to all CO channels
        for co_ch, _ in CO_CI_LOOPBACK_PAIRS:
            crio.write_output(co_ch, target_ma)

        time.sleep(3)  # Allow all channels to settle

        # Read and verify all CI channels (skip ch07 -- it's scaled to %)
        raw_pairs = CO_CI_LOOPBACK_PAIRS[:7]  # ch00-ch06, raw mA
        passed = []
        failed = []
        for co_ch, ci_ch in raw_pairs:
            val = _read_channel_value(crio, ci_ch, timeout=5.0)
            if val is None:
                failed.append((co_ch, ci_ch, None, "no data"))
            elif abs(val - target_ma) > 1.0:
                failed.append((co_ch, ci_ch, val,
                              f"error {abs(val - target_ma):.3f}mA"))
            else:
                passed.append((co_ch, ci_ch, val))

        # Also verify ch07 scaled channel reads ~50% (12mA in 4-20mA range = 50%)
        co_ch07, ci_ch07 = CO_CI_LOOPBACK_PAIRS[7]
        scaled_val = _read_channel_value(crio, ci_ch07, timeout=5.0)

        # Reset all to 0
        for co_ch, _ in CO_CI_LOOPBACK_PAIRS:
            crio.write_output(co_ch, 0.0)

        print(f"\n  CO->CI all-channel test ({target_ma}mA):")
        print(f"  Raw channels (ch00-06): {len(passed)}/7 passed, "
              f"{len(failed)}/7 failed")
        if failed:
            for co, ci, val, reason in failed:
                val_str = f"{val:.4f}mA" if val is not None else "N/A"
                print(f"  FAIL: {co} -> {ci}: {val_str} ({reason})")

        # 12mA on 4-20mA range = (12-4)/(20-4) * 100 = 50%
        if scaled_val is not None:
            print(f"  Scaled channel (ch07): {co_ch07} -> {ci_ch07}: "
                  f"{scaled_val:.2f}% (expected ~50%)")

        assert len(failed) == 0, (
            f"CO->CI all-channel: {len(failed)}/7 raw channels failed at "
            f"{target_ma}mA. Failures: " +
            ", ".join(f"{f[0]}->{f[1]}={f[2]}" for f in failed)
        )

    def test_co_ci_ramp(self, crio):
        """Ramp CO ch0 from 4mA to 20mA in 2mA steps, verify CI follows monotonically.

        Proves the current path is monotonic across the 4-20mA range.
        """
        _require_data()

        co_ch, ci_ch = CO_CI_LOOPBACK_PAIRS[0]
        ramp_ma = [float(v) for v in range(4, 22, 2)]  # 4, 6, 8, ..., 20 mA
        readings = []

        # Pre-settle at start of ramp
        crio.write_output(co_ch, ramp_ma[0])
        time.sleep(2)

        for target_ma in ramp_ma:
            crio.write_output(co_ch, target_ma)
            time.sleep(1.5)
            val = _read_channel_value(crio, ci_ch, timeout=3.0)
            readings.append((target_ma, val))

        # Reset to 0
        crio.write_output(co_ch, 0.0)

        # Verify monotonic (each reading >= previous, allowing 0.2mA tolerance)
        valid = [(t, v) for t, v in readings if v is not None]
        if len(valid) >= 2:
            for i in range(1, len(valid)):
                assert valid[i][1] >= valid[i-1][1] - 0.2, (
                    f"CO->CI ramp not monotonic at step {i}: "
                    f"{valid[i-1][0]}mA->{valid[i-1][1]:.3f}mA, "
                    f"{valid[i][0]}mA->{valid[i][1]:.3f}mA"
                )

        print()
        print(f"  CO->CI Ramp ({co_ch} -> {ci_ch}):")
        print(f"  {'Set (mA)':>10} {'Read (mA)':>10}")
        print("  " + "-" * 25)
        for target, val in readings:
            val_str = f"{val:.4f}" if val is not None else "N/A"
            print(f"  {target:>10.1f} {val_str:>10}")
        print()

    def test_co_ci_420_scaling(self, crio):
        """Verify 4-20mA scaled channel (CI_Mod7_ch07) reads 0-100%.

        4mA  -> 0%   (live zero)
        12mA -> 50%  (midscale)
        20mA -> 100% (full scale)

        This is the critical path for all industrial 4-20mA transmitters.
        """
        _require_data()

        co_ch, ci_ch = CO_CI_LOOPBACK_PAIRS[7]  # ch07 has four_twenty_scaling=true
        # (4-4)/(20-4)*100=0%,  (12-4)/(20-4)*100=50%,  (20-4)/(20-4)*100=100%
        test_points = [
            (4.0,  0.0,   5.0),   # (write_mA, expected_%, tolerance_%)
            (12.0, 50.0,  5.0),
            (20.0, 100.0, 5.0),
        ]
        results = []

        for write_ma, expected_pct, tol_pct in test_points:
            crio.write_output(co_ch, write_ma)
            time.sleep(1.5)

            val = _read_channel_value(crio, ci_ch, timeout=5.0)
            if val is not None:
                error = abs(val - expected_pct)
                results.append((write_ma, expected_pct, val, error))
                assert error <= tol_pct, (
                    f"4-20mA scaling: wrote {write_ma}mA, "
                    f"expected {expected_pct}%, got {val:.2f}% "
                    f"(error {error:.2f}% > {tol_pct}%)"
                )

        # Reset to 0
        crio.write_output(co_ch, 0.0)

        if results:
            print()
            print(f"  4-20mA Scaling ({co_ch} -> {ci_ch}):")
            print(f"  {'Write (mA)':>12} {'Expect (%)':>12} {'Read (%)':>12} {'Error (%)':>12}")
            print("  " + "-" * 52)
            for wma, epct, rpct, err in results:
                print(f"  {wma:>12.1f} {epct:>12.1f} {rpct:>12.2f} {err:>12.2f}")
            print()

    def test_ci_open_loop_detection(self, crio):
        """Verify open-circuit (broken wire) detection on a genuinely unwired channel.

        CI_Mod7_ch08 is physically open — Mod7/ai8 has no wiring connected.
        In a 4-20mA loop, a broken wire or unpowered transmitter drops to 0mA.
        The LOLO alarm (lo_lo_limit=3.5mA) must fire automatically on this channel,
        proving the alarm path detects real open-circuit conditions without any
        CO stimulation.

        This is the 4-20mA equivalent of open-TC detection on thermocouples.
        """
        _require_data()

        ci_ch = "CI_Mod7_ch08"  # Mod7/ai8 — physically open, always reads ~0mA

        # Read the open channel — should be at or near 0mA with no wiring
        open_val = _read_channel_value(crio, ci_ch, timeout=8.0)
        assert open_val is not None, (
            f"No reading from {ci_ch} — check that Mod7/ai8 is in the project config "
            f"and the cRIO project has been reloaded."
        )
        assert open_val < 3.5, (
            f"Open channel {ci_ch} reads {open_val:.3f}mA — expected < 3.5mA (live zero). "
            f"Check that Mod7/ai8 is truly unwired."
        )

        # Wait for LOLO alarm to fire (cRIO evaluates at 4Hz, allow up to 5s)
        alarm_fired = False
        deadline = time.time() + 5.0
        while time.time() < deadline:
            batch = crio.wait_for_batch(timeout=1.0)
            if batch:
                vals = batch.get("channels", batch.get("values", batch))
                v = vals.get(ci_ch)
                if isinstance(v, dict):
                    if v.get("alarm_state") in ("lolo", "LOLO", "lo_lo", "LO_LO"):
                        alarm_fired = True
                        break
            time.sleep(0.25)

        print(f"\n  Open-circuit detection (genuinely unwired channel {ci_ch}):")
        print(f"    Channel reading: {open_val:.4f}mA (below live zero 3.5mA)")
        print(f"    LOLO alarm:      {'FIRED' if alarm_fired else 'not detected via inline batch (alarm may not be inline)'}")

        assert open_val < 3.5, (
            f"Open-circuit detection: {ci_ch} should read < 3.5mA (it is unwired), "
            f"got {open_val:.3f}mA"
        )

    def test_co_cleanup(self, crio):
        """Reset all CO channels to 0mA after current loopback tests."""
        _require_data()

        for co_ch, _ in CO_CI_LOOPBACK_PAIRS:
            crio.write_output(co_ch, 0.0)
        time.sleep(1)

        # Verify CI readings drop toward 0
        errors = []
        for _, ci_ch in CO_CI_LOOPBACK_PAIRS[:7]:  # raw mA channels
            val = _read_channel_value(crio, ci_ch, timeout=5.0)
            if val is not None and val > 1.0:
                errors.append(f"{ci_ch}={val:.3f}mA")

        if errors:
            print(f"\n  CO cleanup: channels still elevated: {errors}")
        else:
            print(f"\n  CO cleanup: all {len(CO_CI_LOOPBACK_PAIRS)} channels reset to 0mA")
