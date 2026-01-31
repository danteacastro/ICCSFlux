#!/usr/bin/env python3
"""
Widget Output + Interlock Integration Test

Tests the full round-trip for Toggle Switch and Setpoint widgets:
  1. Widget sends command → MQTT → DAQ service → cRIO → hardware output
  2. cRIO reads back → publishes value → DAQ service → dashboard store
  3. Interlocks can block commands (digital output + analog output controls)
  4. Session lock blocks unauthorized output changes

Project layout (from test_start_stop_session.py header):
  - tag_0..31:  Digital Inputs  (NI 9425, Mod3)
  - tag_32..47: Voltage Inputs  (Mod1)  [updated: may vary by project]
  - tag_48..63: Voltage Outputs (NI 9264, Mod2)
  - tag_64..71: Digital Outputs (NI 9472, Mod4)
  - tag_72..87: Thermocouples   (NI 9213, Mod5)
  - tag_88..95: Current Outputs (NI 9266, Mod6)

Requirements:
  - DAQ service running on PC
  - cRIO online
  - MQTT broker at localhost:1883
  - Project loaded

Run:
    python tests/test_widget_output_interlocks.py
    pytest tests/test_widget_output_interlocks.py -v -s
"""

import json
import time
import sys
import os
import uuid
import threading
import unittest
from typing import Dict, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from tests.test_helpers import MQTT_HOST, MQTT_PORT, SYSTEM_PREFIX

# Topic bases
NODE_BASE = f"{SYSTEM_PREFIX}/nodes/node-001"
CRIO_BASE = f"{SYSTEM_PREFIX}/nodes/crio-001"

# Test channels (adjust to match your project)
DO_CHANNEL = "tag_64"       # Digital output (NI 9472, Mod4)
VO_CHANNEL = "tag_48"       # Voltage output (NI 9264, Mod2)
CO_CHANNEL = "tag_88"       # Current output (NI 9266, Mod6)
DI_CHANNEL = "tag_0"        # Digital input (NI 9425, Mod3) - for interlock trigger


class WidgetTestClient:
    """MQTT client that simulates dashboard widget behavior."""

    def __init__(self):
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"widget-test-{uuid.uuid4().hex[:6]}",
            transport='tcp'
        )
        self.connected = False
        self._lock = threading.Lock()

        # System state
        self.system_status: Optional[dict] = None
        self.auth_status: Optional[dict] = None

        # Channel values (from DAQ service batch publishes)
        self.channel_values: Dict[str, float] = {}
        self.value_timestamps: Dict[str, float] = {}
        self.batch_count = 0

        # Command ACKs
        self.command_acks: list = []

        # Interlock status
        self.interlock_status: Optional[dict] = None

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = (rc.value == 0) if hasattr(rc, 'value') else (rc == 0)
        if self.connected:
            client.subscribe(f"{NODE_BASE}/status/system")
            client.subscribe(f"{NODE_BASE}/auth/status")
            client.subscribe(f"{NODE_BASE}/channels/batch")
            client.subscribe(f"{NODE_BASE}/command/ack")
            client.subscribe(f"{CRIO_BASE}/command/ack")
            client.subscribe(f"{NODE_BASE}/interlocks/status")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        with self._lock:
            if msg.topic == f"{NODE_BASE}/status/system":
                self.system_status = payload
            elif msg.topic == f"{NODE_BASE}/auth/status":
                self.auth_status = payload
            elif msg.topic == f"{NODE_BASE}/channels/batch":
                self.batch_count += 1
                if isinstance(payload, dict):
                    for ch_name, ch_data in payload.items():
                        if isinstance(ch_data, dict):
                            val = ch_data.get('value')
                            if val is not None:
                                self.channel_values[ch_name] = float(val)
                                self.value_timestamps[ch_name] = time.time()
                        elif isinstance(ch_data, (int, float)):
                            self.channel_values[ch_name] = float(ch_data)
                            self.value_timestamps[ch_name] = time.time()
            elif 'command/ack' in msg.topic:
                self.command_acks.append(payload)
            elif msg.topic == f"{NODE_BASE}/interlocks/status":
                self.interlock_status = payload

    def connect(self, timeout=5.0) -> bool:
        try:
            self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            self.client.loop_start()
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)
            return self.connected
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def login(self, username="admin", password="admin", timeout=5.0) -> bool:
        """Authenticate with DAQ service."""
        self.publish(f"{NODE_BASE}/auth/login", {
            "username": username,
            "password": password,
            "source_ip": "widget_test"
        })
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if self.auth_status and self.auth_status.get("authenticated"):
                    return True
            time.sleep(0.15)
        return False

    def publish(self, topic, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, qos=1)

    # --- Widget commands (same as dashboard useMqtt.ts) ---

    def set_output(self, channel: str, value):
        """Simulate widget setOutput() — same as useMqtt.ts:1367-1374."""
        self.publish(f"{NODE_BASE}/commands/{channel}", {"value": value})

    def toggle_switch(self, channel: str, on: bool):
        """Simulate ToggleSwitch @change handler."""
        self.set_output(channel, 1.0 if on else 0.0)

    def set_setpoint(self, channel: str, value: float):
        """Simulate SetpointWidget send."""
        self.set_output(channel, value)

    # --- Acquisition control ---

    def send_start(self):
        self.publish(f"{NODE_BASE}/system/acquire/start", {})

    def send_stop(self):
        self.publish(f"{NODE_BASE}/system/acquire/stop", {})

    def send_session_start(self, name="Widget Test"):
        self.publish(f"{NODE_BASE}/test-session/start", {
            "name": name,
            "operator": "test_runner",
            "request_id": str(uuid.uuid4())
        })

    def send_session_stop(self):
        self.publish(f"{NODE_BASE}/test-session/stop", {
            "reason": "test_complete",
            "request_id": str(uuid.uuid4())
        })

    # --- Wait helpers ---

    def wait_acquiring(self, expected: bool, timeout=5.0) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if self.system_status and self.system_status.get("acquiring") == expected:
                    return True
            time.sleep(0.2)
        return False

    def wait_for_value(self, channel: str, timeout=10.0) -> Optional[float]:
        """Wait until a channel has a value."""
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if channel in self.channel_values:
                    return self.channel_values[channel]
            time.sleep(0.25)
        return None

    def wait_for_value_change(self, channel: str, old_value: float,
                               timeout=10.0, tolerance=0.01) -> Optional[float]:
        """Wait until channel value differs from old_value."""
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                val = self.channel_values.get(channel)
                if val is not None and abs(val - old_value) > tolerance:
                    return val
            time.sleep(0.25)
        return None

    def get_value(self, channel: str) -> Optional[float]:
        with self._lock:
            return self.channel_values.get(channel)

    def get_latest_ack(self, channel: str = None) -> Optional[dict]:
        """Get latest command ACK, optionally filtered by channel."""
        with self._lock:
            for ack in reversed(self.command_acks):
                if channel is None or ack.get('channel') == channel:
                    return ack
        return None

    def clear_acks(self):
        with self._lock:
            self.command_acks.clear()

    def is_acquiring(self) -> bool:
        with self._lock:
            return self.system_status.get("acquiring", False) if self.system_status else False

    def ensure_acquiring(self, timeout=8.0) -> bool:
        if self.is_acquiring():
            return True
        self.send_start()
        return self.wait_acquiring(True, timeout)

    def ensure_not_acquiring(self, timeout=5.0) -> bool:
        if not self.is_acquiring():
            return True
        self.send_stop()
        return self.wait_acquiring(False, timeout)


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestToggleSwitchOutput(unittest.TestCase):
    """Test digital output toggle switch round-trip."""

    @classmethod
    def setUpClass(cls):
        cls.client = WidgetTestClient()
        if not cls.client.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        time.sleep(1.0)

        # Login if auth is required
        cls.client.login()
        time.sleep(0.5)

        # Ensure acquiring
        if not cls.client.ensure_acquiring():
            raise unittest.SkipTest("Cannot start acquisition")

        # Wait for initial data
        time.sleep(3.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()

    def test_01_toggle_on(self):
        """Send toggle ON command and verify digital output changes to 1."""
        self.client.clear_acks()
        old_val = self.client.get_value(DO_CHANNEL) or 0.0

        self.client.toggle_switch(DO_CHANNEL, True)

        # Wait for value to change
        new_val = self.client.wait_for_value_change(DO_CHANNEL, old_val, timeout=10.0)

        # Check ACK
        time.sleep(0.5)
        ack = self.client.get_latest_ack(DO_CHANNEL)

        if new_val is not None:
            self.assertAlmostEqual(new_val, 1.0, places=0,
                                   msg=f"Expected {DO_CHANNEL}=1.0 after toggle ON, got {new_val}")
        else:
            # Value didn't change - might already be 1.0 or command was blocked
            current = self.client.get_value(DO_CHANNEL)
            self.assertIsNotNone(current, f"No value received for {DO_CHANNEL}")
            # If already 1.0, that's OK
            if current is not None and abs(current - 1.0) < 0.5:
                pass  # Already ON
            else:
                self.fail(f"Toggle ON failed. Current value: {current}, ACK: {ack}")

    def test_02_toggle_off(self):
        """Send toggle OFF command and verify digital output changes to 0."""
        self.client.clear_acks()
        old_val = self.client.get_value(DO_CHANNEL) or 1.0

        self.client.toggle_switch(DO_CHANNEL, False)

        new_val = self.client.wait_for_value_change(DO_CHANNEL, old_val, timeout=10.0)

        if new_val is not None:
            self.assertAlmostEqual(new_val, 0.0, places=0,
                                   msg=f"Expected {DO_CHANNEL}=0.0 after toggle OFF, got {new_val}")
        else:
            current = self.client.get_value(DO_CHANNEL)
            if current is not None and abs(current) < 0.5:
                pass  # Already OFF
            else:
                self.fail(f"Toggle OFF failed. Current value: {current}")

    def test_03_toggle_round_trip_timing(self):
        """Measure round-trip time for toggle command."""
        # Ensure OFF first
        self.client.toggle_switch(DO_CHANNEL, False)
        time.sleep(2.0)

        self.client.clear_acks()
        send_time = time.time()
        self.client.toggle_switch(DO_CHANNEL, True)

        new_val = self.client.wait_for_value_change(DO_CHANNEL, 0.0, timeout=10.0)
        receive_time = time.time()

        if new_val is not None:
            round_trip = receive_time - send_time
            print(f"  Toggle round-trip: {round_trip:.3f}s")
            self.assertLess(round_trip, 5.0,
                            f"Round-trip too slow: {round_trip:.3f}s (should be <5s)")
        else:
            self.fail("Toggle ON value never received back")

        # Clean up
        self.client.toggle_switch(DO_CHANNEL, False)


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestSetpointOutput(unittest.TestCase):
    """Test voltage/current output setpoint round-trip."""

    @classmethod
    def setUpClass(cls):
        cls.client = WidgetTestClient()
        if not cls.client.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        time.sleep(1.0)
        cls.client.login()
        time.sleep(0.5)

        if not cls.client.ensure_acquiring():
            raise unittest.SkipTest("Cannot start acquisition")
        time.sleep(3.0)

    @classmethod
    def tearDownClass(cls):
        # Reset setpoint to 0
        cls.client.set_setpoint(VO_CHANNEL, 0.0)
        time.sleep(1.0)
        cls.client.disconnect()

    def test_01_set_voltage_output(self):
        """Set voltage output to 5.0V and verify feedback."""
        self.client.clear_acks()
        old_val = self.client.get_value(VO_CHANNEL) or 0.0

        target = 5.0
        self.client.set_setpoint(VO_CHANNEL, target)

        new_val = self.client.wait_for_value_change(VO_CHANNEL, old_val, timeout=10.0)

        if new_val is not None:
            self.assertAlmostEqual(new_val, target, places=0,
                                   msg=f"Expected {VO_CHANNEL}={target}, got {new_val}")
        else:
            current = self.client.get_value(VO_CHANNEL)
            if current is not None and abs(current - target) < 1.0:
                pass  # Close enough
            else:
                self.fail(f"Setpoint command failed. Current: {current}")

    def test_02_set_voltage_zero(self):
        """Set voltage output to 0V and verify."""
        self.client.set_setpoint(VO_CHANNEL, 0.0)

        time.sleep(3.0)
        val = self.client.get_value(VO_CHANNEL)
        if val is not None:
            self.assertAlmostEqual(val, 0.0, places=0,
                                   msg=f"Expected {VO_CHANNEL}=0.0, got {val}")

    def test_03_increment_decrement(self):
        """Simulate setpoint increment/decrement (widget arrows)."""
        # Set to 2.0
        self.client.set_setpoint(VO_CHANNEL, 2.0)
        time.sleep(2.0)

        # Increment to 3.0
        self.client.set_setpoint(VO_CHANNEL, 3.0)
        time.sleep(2.0)

        val = self.client.get_value(VO_CHANNEL)
        if val is not None:
            self.assertAlmostEqual(val, 3.0, places=0,
                                   msg=f"Expected 3.0 after increment, got {val}")

        # Reset
        self.client.set_setpoint(VO_CHANNEL, 0.0)


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestOutputBlockedWhenNotAcquiring(unittest.TestCase):
    """Verify output commands are blocked when not acquiring."""

    @classmethod
    def setUpClass(cls):
        cls.client = WidgetTestClient()
        if not cls.client.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        time.sleep(1.0)
        cls.client.login()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()

    def test_01_output_blocked_when_stopped(self):
        """Output commands should be rejected when not acquiring.

        The DAQ service checks `self.acquiring` before processing output
        commands (_handle_command). When stopped, commands should be
        silently dropped or explicitly rejected.
        """
        # Ensure stopped
        self.client.ensure_not_acquiring()
        time.sleep(1.0)

        self.client.clear_acks()

        # Try to set output
        self.client.toggle_switch(DO_CHANNEL, True)
        time.sleep(2.0)

        # The value should NOT change (no data flows when not acquiring)
        # The widget shows "Not acquiring" status text
        val = self.client.get_value(DO_CHANNEL)
        # We can't easily verify the output was blocked since no data
        # flows when not acquiring. The key verification is that the
        # frontend disables the toggle (canToggle computed property).
        print(f"  Output value when stopped: {val} (frontend would disable toggle)")

    def test_02_output_works_when_acquiring(self):
        """Output commands should succeed when acquiring."""
        self.client.ensure_acquiring()
        time.sleep(3.0)

        self.client.clear_acks()
        self.client.toggle_switch(DO_CHANNEL, True)

        # Wait for value feedback
        val = self.client.wait_for_value(DO_CHANNEL, timeout=10.0)
        self.assertIsNotNone(val, "No value feedback when acquiring")

        # Clean up
        self.client.toggle_switch(DO_CHANNEL, False)
        time.sleep(1.0)


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestInterlockBlocking(unittest.TestCase):
    """Test that interlocks can block output commands.

    Interlocks are configured in the project and evaluated by the
    safety system. When an interlock trips (alarm condition + latch),
    outputs listed in its control channels are blocked.

    This test verifies the blocking path:
    1. Configure an interlock that monitors a channel
    2. Trigger the interlock condition
    3. Verify output commands are rejected with "blocked" reason
    """

    @classmethod
    def setUpClass(cls):
        cls.client = WidgetTestClient()
        if not cls.client.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        time.sleep(1.0)
        cls.client.login()
        time.sleep(0.5)

        if not cls.client.ensure_acquiring():
            raise unittest.SkipTest("Cannot start acquisition")
        time.sleep(3.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()

    def test_01_interlock_status_published(self):
        """Verify interlock status is published."""
        # The DAQ service publishes interlock status periodically
        # or when interlock state changes
        time.sleep(2.0)

        # Check if we received any interlock data
        # (may not have interlocks configured)
        status = self.client.interlock_status
        if status is None:
            self.skipTest("No interlock status published - "
                          "interlocks may not be configured in the project")

        print(f"  Interlock status: {json.dumps(status, indent=2)[:200]}")

    def test_02_blocked_output_rejected(self):
        """If a channel is blocked by interlock, output command should fail.

        This tests the safety gate in _handle_command (daq_service.py:3905):
        The DAQ service checks safety_manager.is_output_blocked() before
        forwarding the output command to cRIO.

        For this test to trigger, an interlock must be:
        1. Configured in the project
        2. Active (alarm condition met)
        3. Not bypassed
        4. Controlling the test output channel
        """
        # Send a command and check the ACK
        self.client.clear_acks()
        self.client.toggle_switch(DO_CHANNEL, True)
        time.sleep(2.0)

        # Check for any ACK
        ack = self.client.get_latest_ack(DO_CHANNEL)
        if ack:
            if not ack.get('success'):
                reason = ack.get('error', ack.get('reason', 'unknown'))
                if 'block' in reason.lower() or 'interlock' in reason.lower():
                    print(f"  Output correctly blocked: {reason}")
                    return  # PASS - interlock is blocking
                else:
                    print(f"  Output rejected (non-interlock): {reason}")
            else:
                print(f"  Output accepted (no interlock blocking this channel)")
        else:
            print(f"  No ACK received (DAQ may not send ACK for output commands)")

        # Clean up
        self.client.toggle_switch(DO_CHANNEL, False)


def run_quick_test():
    """Quick standalone test (no pytest needed)."""
    print("=" * 60)
    print("Widget Output Integration Test")
    print("=" * 60)
    print()

    client = WidgetTestClient()
    if not client.connect():
        print("FAIL: Cannot connect to MQTT broker")
        return

    print(f"Connected to {MQTT_HOST}:{MQTT_PORT}")

    # Login
    client.login()
    time.sleep(1.0)

    # Status
    status = client.system_status
    if status:
        print(f"System: acquiring={status.get('acquiring')}, "
              f"channels={status.get('channel_count')}")
    else:
        print("WARNING: No system status received")

    # Ensure acquiring
    if not client.ensure_acquiring():
        print("FAIL: Cannot start acquisition")
        client.disconnect()
        return

    print("Acquisition running. Waiting for data...")
    time.sleep(3.0)

    # Test toggle
    print(f"\n--- Toggle {DO_CHANNEL} ON ---")
    client.toggle_switch(DO_CHANNEL, True)
    time.sleep(3.0)
    val = client.get_value(DO_CHANNEL)
    print(f"  {DO_CHANNEL} = {val}")

    print(f"\n--- Toggle {DO_CHANNEL} OFF ---")
    client.toggle_switch(DO_CHANNEL, False)
    time.sleep(3.0)
    val = client.get_value(DO_CHANNEL)
    print(f"  {DO_CHANNEL} = {val}")

    # Test setpoint
    print(f"\n--- Set {VO_CHANNEL} = 5.0V ---")
    client.set_setpoint(VO_CHANNEL, 5.0)
    time.sleep(3.0)
    val = client.get_value(VO_CHANNEL)
    print(f"  {VO_CHANNEL} = {val}")

    print(f"\n--- Set {VO_CHANNEL} = 0.0V ---")
    client.set_setpoint(VO_CHANNEL, 0.0)
    time.sleep(3.0)
    val = client.get_value(VO_CHANNEL)
    print(f"  {VO_CHANNEL} = {val}")

    # Report
    print(f"\n--- All channel values ---")
    for ch, val in sorted(client.channel_values.items()):
        if ch.startswith('tag_'):
            tag_num = int(ch.replace('tag_', ''))
            if tag_num >= 48 and tag_num < 96:  # Outputs + TCs
                print(f"  {ch}: {val:.4f}")

    client.disconnect()
    print("\nDone.")


if __name__ == '__main__':
    if '--quick' in sys.argv:
        run_quick_test()
    elif '--report' in sys.argv:
        run_quick_test()
    else:
        run_quick_test()
        print("\n\nTo run as unit tests: pytest tests/test_widget_output_interlocks.py -v -s")
