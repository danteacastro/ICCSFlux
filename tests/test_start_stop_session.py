#!/usr/bin/env python3
"""
Live Start/Stop/Session Integration Test

Tests the full acquisition lifecycle against a running DAQ service + cRIO
using the "CRIO Test 192168120" project (DCFlux).

Project channels:
  - tag_0..31:  Digital Inputs  (NI 9425, Mod3)
  - tag_32..47: Voltage Inputs  (Mod1)
  - tag_48..71: Voltage Outputs (NI 9264, Mod2)
  - tag_72..79: Digital Outputs (NI 9472, Mod4)
  - tag_80..95: Thermocouples   (NI 9213, Mod5)

Session script: "Digital Output Cycle Test" cycles tag_72-75 ON/OFF
Interlock: "Test" monitors tag_0/tag_1, controls tag_48/49 + tag_72-75

Requirements:
  - DAQ service running on PC
  - cRIO online at 192.168.1.20 (or wherever configured)
  - MQTT broker running (localhost:1883)
  - Project loaded

Run:
    python tests/test_start_stop_session.py
    pytest tests/test_start_stop_session.py -v -s
"""

import json
import time
import sys
import os
import uuid
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from tests.test_helpers import MQTT_HOST, MQTT_PORT, SYSTEM_PREFIX

# Node-prefixed topic base (DAQ service uses this for all topics)
NODE_BASE = f"{SYSTEM_PREFIX}/nodes/node-001"

# Known channels from the project
DO_CHANNEL = "tag_72"       # Digital output (NI 9472)
VO_CHANNEL = "tag_48"       # Voltage output (NI 9264)

# Test credentials - NOT for production use
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"  # Default password from UserSessionManager fixture

class LiveTestClient:
    """MQTT test client using correct node-prefixed topics."""

    def __init__(self, transport='tcp', port=1883):
        self.port = port
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"test-startstop-{uuid.uuid4().hex[:6]}",
            transport=transport
        )
        self.connected = False
        self._status = None
        self._status_lock = threading.Lock()
        self._auth_status = None
        self._auth_lock = threading.Lock()
        self._messages = {}
        self._msg_lock = threading.Lock()

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = (rc == 0 or rc.value == 0) if hasattr(rc, 'value') else (rc == 0)
        if self.connected:
            # Subscribe to DAQ service status (node-prefixed)
            client.subscribe(f"{NODE_BASE}/status/system")
            # Subscribe to auth status
            client.subscribe(f"{NODE_BASE}/auth/status")
            # Subscribe to command acks (for verifying command delivery)
            client.subscribe(f"{NODE_BASE}/command/ack")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

        # Cache system status from DAQ service (node-001)
        if msg.topic == f"{NODE_BASE}/status/system":
            with self._status_lock:
                self._status = payload

        # Cache auth status
        if msg.topic == f"{NODE_BASE}/auth/status":
            with self._auth_lock:
                self._auth_status = payload

        with self._msg_lock:
            if msg.topic not in self._messages:
                self._messages[msg.topic] = []
            self._messages[msg.topic].append(payload)

    def connect(self, timeout=5.0) -> bool:
        try:
            self.client.connect(MQTT_HOST, self.port)
            self.client.loop_start()
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            return self.connected
        except Exception as e:
            print(f"Connect error: {e}")
            return False

    def login(self, username=TEST_USERNAME, password=TEST_PASSWORD, timeout=5.0) -> bool:
        """Authenticate with the DAQ service via MQTT."""
        self.publish(f"{NODE_BASE}/auth/login", {
            "username": username,
            "password": password,
            "source_ip": "test_runner"
        })
        start = time.time()
        while (time.time() - start) < timeout:
            with self._auth_lock:
                if self._auth_status and self._auth_status.get("authenticated"):
                    return True
            time.sleep(0.15)
        return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload)

    def get_status(self):
        with self._status_lock:
            return dict(self._status) if self._status else None

    def wait_for_status(self, timeout=5.0):
        start = time.time()
        while (time.time() - start) < timeout:
            s = self.get_status()
            if s:
                return s
            time.sleep(0.15)
        return None

    def refresh_status(self, timeout=2.0):
        """Wait for a fresh status update (different timestamp)."""
        with self._status_lock:
            old_ts = self._status.get("timestamp") if self._status else None
        start = time.time()
        while (time.time() - start) < timeout:
            time.sleep(0.15)
            with self._status_lock:
                if self._status:
                    if self._status.get("timestamp") != old_ts:
                        return dict(self._status)
        return self.get_status()

    # --- Commands (using correct node-prefixed topics) ---

    def send_acquire_start(self) -> str:
        rid = str(uuid.uuid4())
        self.publish(f"{NODE_BASE}/system/acquire/start", {"request_id": rid})
        return rid

    def send_acquire_stop(self) -> str:
        rid = str(uuid.uuid4())
        self.publish(f"{NODE_BASE}/system/acquire/stop", {"request_id": rid})
        return rid

    def send_session_start(self) -> str:
        rid = str(uuid.uuid4())
        self.publish(f"{NODE_BASE}/test-session/start", {
            "name": "Integration Test",
            "operator": "test_runner",
            "request_id": rid
        })
        return rid

    def send_session_stop(self) -> str:
        rid = str(uuid.uuid4())
        self.publish(f"{NODE_BASE}/test-session/stop", {
            "reason": "test_complete",
            "request_id": rid
        })
        return rid

    def send_output(self, channel: str, value):
        self.publish(f"{NODE_BASE}/commands/{channel}", {"value": value})

    # --- Wait helpers ---

    def wait_acquiring(self, expected: bool, timeout=5.0) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            s = self.get_status()
            if s and s.get("acquiring") == expected:
                return True
            time.sleep(0.2)
        return False

    def wait_session(self, expected: bool, timeout=5.0) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            s = self.get_status()
            if s and s.get("session_active") == expected:
                return True
            time.sleep(0.2)
        return False

    def ensure_not_acquiring(self, timeout=5.0) -> bool:
        s = self.get_status()
        if s and not s.get("acquiring"):
            return True
        self.send_acquire_stop()
        return self.wait_acquiring(False, timeout)

    def ensure_acquiring(self, timeout=5.0) -> bool:
        s = self.get_status()
        if s and s.get("acquiring"):
            return True
        self.send_acquire_start()
        return self.wait_acquiring(True, timeout)

# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_start_acquisition(client: LiveTestClient) -> bool:
    """START -> acquiring=True, data flows."""
    rid = client.send_acquire_start()

    if not client.wait_acquiring(True, timeout=8.0):
        # Check for command ACKs to diagnose why START failed
        ack_topic = f"{NODE_BASE}/command/ack"
        with client._msg_lock:
            acks = client._messages.get(ack_topic, [])
        if acks:
            for ack in acks[-5:]:
                print(f"  ACK: cmd={ack.get('command')}, success={ack.get('success')}, error={ack.get('error')}")
        else:
            print(f"  No command ACKs received (handler may not be firing)")
        status = client.get_status()
        print(f"  FAIL: acquiring not True after 8s. state={status.get('acquisition_state')}, auth={status.get('authenticated')}")
        return False

    print("  OK: Acquisition started, acquiring=True")
    return True

def test_stop_acquisition(client: LiveTestClient) -> bool:
    """STOP -> acquiring=False, stays stopped for 2s."""
    if not client.ensure_acquiring():
        print("  FAIL: Could not start acquisition for stop test")
        return False

    client.send_acquire_stop()

    if not client.wait_acquiring(False, timeout=5.0):
        status = client.get_status()
        print(f"  FAIL: acquiring not False after STOP. Status: {status}")
        return False

    # Verify stays stopped (no self-echo flipping it back)
    time.sleep(2.0)
    status = client.refresh_status(timeout=2.0)
    if status and status.get("acquiring"):
        print("  FAIL: acquiring flipped back to True after 2s! Self-echo bug.")
        return False

    print("  OK: Acquisition stopped, stayed stopped for 2s")
    return True

def test_rapid_start_stop(client: LiveTestClient, cycles: int = 5) -> bool:
    """Rapid START/STOP x5 -> always reaches correct state."""
    client.ensure_not_acquiring()

    for i in range(cycles):
        client.send_acquire_start()
        if not client.wait_acquiring(True, timeout=5.0):
            print(f"  FAIL: Cycle {i+1} START failed")
            return False
        time.sleep(0.3)

        client.send_acquire_stop()
        if not client.wait_acquiring(False, timeout=5.0):
            print(f"  FAIL: Cycle {i+1} STOP failed")
            return False
        time.sleep(0.3)

    # Final stability check
    time.sleep(1.0)
    status = client.refresh_status(timeout=2.0)
    if status and status.get("acquiring"):
        print(f"  FAIL: After {cycles} cycles, acquiring is True")
        return False

    print(f"  OK: {cycles} rapid START/STOP cycles, final state: stopped")
    return True

def test_session_on_off(client: LiveTestClient) -> bool:
    """SESSION ON/OFF while acquiring."""
    if not client.ensure_acquiring():
        print("  FAIL: Could not start acquisition")
        return False

    # SESSION ON
    client.send_session_start()
    if not client.wait_session(True, timeout=5.0):
        status = client.get_status()
        print(f"  FAIL: session_active not True. Status: {status}")
        return False
    print("  OK: Session started, session_active=True")

    time.sleep(2.0)

    # SESSION OFF
    client.send_session_stop()
    if not client.wait_session(False, timeout=5.0):
        status = client.get_status()
        print(f"  FAIL: session_active not False. Status: {status}")
        return False

    # Verify stays off
    time.sleep(1.5)
    status = client.refresh_status(timeout=2.0)
    if status and status.get("session_active"):
        print("  FAIL: session_active flipped back to True!")
        return False

    print("  OK: Session stopped, stayed stopped")
    return True

def test_rapid_session_toggle(client: LiveTestClient, cycles: int = 3) -> bool:
    """Rapid SESSION ON/OFF x3 while acquiring."""
    if not client.ensure_acquiring():
        print("  FAIL: Could not start acquisition")
        return False

    for i in range(cycles):
        client.send_session_start()
        if not client.wait_session(True, timeout=5.0):
            print(f"  FAIL: Cycle {i+1} session start failed")
            return False
        time.sleep(0.5)

        client.send_session_stop()
        if not client.wait_session(False, timeout=5.0):
            print(f"  FAIL: Cycle {i+1} session stop failed")
            return False
        time.sleep(0.5)

    print(f"  OK: {cycles} rapid SESSION ON/OFF cycles completed")
    return True

def test_output_during_acquisition(client: LiveTestClient) -> bool:
    """DO toggle + VO set while acquiring -> acquisition NOT killed."""
    if not client.ensure_acquiring():
        print("  FAIL: Could not start acquisition")
        return False
    time.sleep(0.5)

    # Toggle DO
    client.send_output(DO_CHANNEL, True)
    time.sleep(1.0)
    status = client.get_status()
    if not status or not status.get("acquiring"):
        print("  FAIL: acquiring=False after DO toggle (output ACK bug)")
        return False
    print(f"  OK: DO {DO_CHANNEL}=ON, still acquiring")

    # Set VO
    client.send_output(VO_CHANNEL, 2.5)
    time.sleep(1.0)
    status = client.get_status()
    if not status or not status.get("acquiring"):
        print("  FAIL: acquiring=False after VO set (output ACK bug)")
        return False
    print(f"  OK: VO {VO_CHANNEL}=2.5V, still acquiring")

    # Reset to safe
    client.send_output(DO_CHANNEL, False)
    client.send_output(VO_CHANNEL, 0.0)
    time.sleep(0.5)

    status = client.get_status()
    if not status or not status.get("acquiring"):
        print("  FAIL: acquiring=False after output reset")
        return False
    print("  OK: Outputs reset, still acquiring")
    return True

def test_full_cycle(client: LiveTestClient) -> bool:
    """START -> DO toggle -> SESSION ON -> SESSION OFF -> STOP."""
    client.ensure_not_acquiring()
    time.sleep(0.5)

    # 1. START
    client.send_acquire_start()
    if not client.wait_acquiring(True, timeout=5.0):
        print("  FAIL: Step 1 START")
        return False
    print("  Step 1: START -> acquiring=True")
    time.sleep(1.0)

    # 2. Toggle output
    client.send_output(DO_CHANNEL, True)
    time.sleep(0.5)
    client.send_output(DO_CHANNEL, False)
    time.sleep(0.5)
    status = client.get_status()
    if not status or not status.get("acquiring"):
        print("  FAIL: Step 2 lost acquisition after DO toggle")
        return False
    print("  Step 2: DO toggle -> still acquiring")

    # 3. SESSION ON
    client.send_session_start()
    if not client.wait_session(True, timeout=5.0):
        print("  FAIL: Step 3 SESSION ON")
        return False
    print("  Step 3: SESSION ON -> session_active=True")
    time.sleep(2.0)

    # 4. SESSION OFF
    client.send_session_stop()
    if not client.wait_session(False, timeout=5.0):
        print("  FAIL: Step 4 SESSION OFF")
        return False
    status = client.get_status()
    if not status or not status.get("acquiring"):
        print("  FAIL: Step 4 lost acquisition after session stop")
        return False
    print("  Step 4: SESSION OFF -> still acquiring")
    time.sleep(0.5)

    # 5. STOP
    client.send_acquire_stop()
    if not client.wait_acquiring(False, timeout=5.0):
        print("  FAIL: Step 5 STOP")
        return False

    time.sleep(2.0)
    status = client.refresh_status(timeout=2.0)
    if status and status.get("acquiring"):
        print("  FAIL: Step 5 acquiring flipped back to True")
        return False
    print("  Step 5: STOP -> acquiring=False, stable")

    return True

def test_stop_stays_stopped(client: LiveTestClient) -> bool:
    """After STOP, stays stopped for 10 seconds."""
    client.ensure_acquiring()
    time.sleep(0.5)

    client.send_acquire_stop()
    if not client.wait_acquiring(False, timeout=5.0):
        print("  FAIL: Could not stop acquisition")
        return False

    print("  Monitoring for 10s...")
    for i in range(20):
        time.sleep(0.5)
        status = client.get_status()
        if status and status.get("acquiring"):
            print(f"  FAIL: acquiring flipped True at {(i+1)*0.5:.1f}s!")
            return False

    print("  OK: Stayed stopped for 10s")
    return True

# =============================================================================
# MAIN
# =============================================================================

def run_all_tests():
    if not MQTT_AVAILABLE:
        print("ERROR: paho-mqtt not installed")
        return False

    print("\n" + "=" * 70)
    print("  Live Start/Stop/Session Integration Test")
    print("  Project: CRIO Test 192168120 (DCFlux)")
    print(f"  Broker:  {MQTT_HOST}:{MQTT_PORT}")
    print(f"  Topics:  {NODE_BASE}/...")
    print("=" * 70)

    client = LiveTestClient()
    if not client.connect():
        print(f"\nFAIL: Cannot connect to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
        return False

    # Wait for DAQ service status
    status = client.wait_for_status(timeout=5.0)
    if not status:
        print("\nFAIL: No system status received - is DAQ service running?")
        client.disconnect()
        return False

    mode = status.get("project_mode", "?")
    acq = status.get("acquiring", False)
    sess = status.get("session_active", False)
    print(f"\nDAQ service online. Mode: {mode}, Acquiring: {acq}, Session: {sess}")

    # Always authenticate explicitly - retained auth/status messages don't
    # guarantee the DAQ service has an active session (e.g., after restart).
    print("Authenticating as admin...")
    if client.login(TEST_USERNAME, TEST_PASSWORD):
        print("Authenticated OK")
    else:
        print("WARNING: Authentication may have failed - commands may be rejected")

    # Clean starting state
    if sess:
        print("Stopping existing session...")
        client.send_session_stop()
        client.wait_session(False, timeout=3.0)
    if acq:
        print("Stopping existing acquisition...")
        client.ensure_not_acquiring()
    time.sleep(1.0)

    tests = [
        ("1. Start Acquisition",          test_start_acquisition),
        ("2. Stop Acquisition",            test_stop_acquisition),
        ("3. Rapid Start/Stop (5x)",       test_rapid_start_stop),
        ("4. Session On/Off",             test_session_on_off),
        ("5. Rapid Session Toggle (3x)",  test_rapid_session_toggle),
        ("6. Output During Acquisition",  test_output_during_acquisition),
        ("7. Full Lifecycle Cycle",       test_full_cycle),
        ("8. Stop Stays Stopped (10s)",   test_stop_stays_stopped),
    ]

    passed = 0
    failed = 0
    results = []

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            # Clean state between independent tests
            if name.startswith("1.") or name.startswith("2.") or name.startswith("4.") or name.startswith("6."):
                client.ensure_not_acquiring()
                time.sleep(0.5)

            ok = test_fn(client)
            if ok:
                passed += 1
                results.append((name, "PASS"))
            else:
                failed += 1
                results.append((name, "FAIL"))
        except Exception as e:
            failed += 1
            results.append((name, f"ERROR: {e}"))
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Cleanup
    client.ensure_not_acquiring()
    client.disconnect()

    # Summary
    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)
    for name, result in results:
        icon = "PASS" if result == "PASS" else "FAIL"
        print(f"  [{icon}] {name}")
    print(f"\n  Total: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 70)

    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
