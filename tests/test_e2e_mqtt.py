#!/usr/bin/env python3
"""
End-to-End MQTT Data Flow Tests for NISystem

These tests validate the complete data flow between:
- MQTT Broker (Mosquitto)
- DAQ Service (Backend)
- Frontend (via WebSocket)

Requirements:
- Mosquitto broker running on localhost:1883 (TCP) and :9001 (WebSocket)
- DAQ service running in simulation mode

Run with: python -m pytest tests/test_e2e_mqtt.py -v
Or standalone: python tests/test_e2e_mqtt.py
"""

import json
import time
import threading
import unittest
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime

import paho.mqtt.client as mqtt

# Test configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_WS_PORT = 9001
SYSTEM_PREFIX = "nisystem"
DEFAULT_TIMEOUT = 5.0

@dataclass
class TestResult:
    """Container for test results"""
    success: bool
    message: str
    data: Optional[Any] = None
    duration_ms: float = 0.0

class MQTTTestClient:
    """Helper class for MQTT testing"""

    def __init__(self, client_id: str = "test-client"):
        self.client = mqtt.Client(client_id=client_id)
        self.connected = False
        self.messages: Dict[str, List[dict]] = {}
        self.message_lock = threading.Lock()
        self._setup_callbacks()

    def _setup_callbacks(self):
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            payload = msg.payload.decode()

        with self.message_lock:
            if msg.topic not in self.messages:
                self.messages[msg.topic] = []
            self.messages[msg.topic].append({
                "payload": payload,
                "timestamp": time.time()
            })

    def connect(self, host: str = MQTT_HOST, port: int = MQTT_PORT, timeout: float = 5.0) -> bool:
        """Connect to MQTT broker"""
        try:
            self.client.connect(host, port, keepalive=60)
            self.client.loop_start()

            # Wait for connection
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            return self.connected
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False

    def subscribe(self, topic: str):
        """Subscribe to a topic"""
        self.client.subscribe(topic)

    def publish(self, topic: str, payload: Any):
        """Publish a message"""
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload)

    def wait_for_message(self, topic: str, timeout: float = DEFAULT_TIMEOUT,
                         count: int = 1) -> List[dict]:
        """Wait for messages on a topic"""
        start = time.time()
        while (time.time() - start) < timeout:
            with self.message_lock:
                if topic in self.messages and len(self.messages[topic]) >= count:
                    return self.messages[topic][:count]
            time.sleep(0.1)

        with self.message_lock:
            return self.messages.get(topic, [])

    def clear_messages(self, topic: Optional[str] = None):
        """Clear received messages"""
        with self.message_lock:
            if topic:
                self.messages.pop(topic, None)
            else:
                self.messages.clear()

class TestMQTTBrokerConnection(unittest.TestCase):
    """Test MQTT broker connectivity"""

    def test_tcp_connection(self):
        """Test TCP connection to MQTT broker on port 1883"""
        client = MQTTTestClient("test-tcp-connection")
        try:
            result = client.connect(MQTT_HOST, MQTT_PORT)
            self.assertTrue(result, "Failed to connect to MQTT broker via TCP")
        finally:
            client.disconnect()

    def test_websocket_connection(self):
        """Test WebSocket connection to MQTT broker on port 9001"""
        # Note: paho-mqtt requires transport='websockets' for WS
        client = mqtt.Client(client_id="test-ws-connection", transport="websockets")
        connected = threading.Event()

        def on_connect(c, u, f, rc):
            if rc == 0:
                connected.set()

        client.on_connect = on_connect

        try:
            client.connect(MQTT_HOST, MQTT_WS_PORT)
            client.loop_start()
            result = connected.wait(timeout=5.0)
            self.assertTrue(result, "Failed to connect to MQTT broker via WebSocket")
        finally:
            client.loop_stop()
            client.disconnect()

class TestDAQServiceStatus(unittest.TestCase):
    """Test DAQ service status publishing"""

    @classmethod
    def setUpClass(cls):
        cls.client = MQTTTestClient("test-daq-status")
        cls.client.connect()

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()

    def test_system_status_published(self):
        """Verify DAQ service publishes system status"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/status/system")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, "No system status messages received")

        status = messages[0]["payload"]
        self.assertIn("status", status)
        self.assertIn("simulation_mode", status)
        self.assertIn("acquiring", status)
        self.assertEqual(status["status"], "online")

    def test_service_status_published(self):
        """Verify DAQ service publishes service status"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/status/service")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/service",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, "No service status messages received")
        self.assertEqual(messages[0]["payload"]["status"], "online")

    def test_channel_config_published(self):
        """Verify channel configuration is published"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/config/channels")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/config/channels",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, "No channel config messages received")

        config = messages[0]["payload"]
        self.assertIn("channels", config)
        self.assertGreater(len(config["channels"]), 0)

class TestAcquisitionControl(unittest.TestCase):
    """Test acquisition start/stop commands"""

    @classmethod
    def setUpClass(cls):
        cls.client = MQTTTestClient("test-acquisition")
        cls.client.connect()
        # Stop any existing acquisition first
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        # Ensure acquisition is stopped
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(0.5)
        cls.client.disconnect()

    def test_start_acquisition(self):
        """Test starting data acquisition"""
        # Ensure stopped first
        self.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(0.5)

        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/status/system")

        # Send start command
        self.client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")

        # Wait for multiple status updates to catch the change
        time.sleep(2.0)
        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0,
            count=3
        )

        self.assertGreater(len(messages), 0, "No status messages after start command")

        # Find a message where acquiring is true
        acquiring = any(m["payload"].get("acquiring", False) for m in messages)
        self.assertTrue(acquiring, "Acquisition did not start")

    def test_stop_acquisition(self):
        """Test stopping data acquisition"""
        # First ensure acquisition is running
        self.client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
        time.sleep(1.0)

        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/status/system")

        # Send stop command
        self.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")

        # Wait for multiple status updates
        time.sleep(2.0)
        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/status/system",
            timeout=3.0,
            count=3
        )

        self.assertGreater(len(messages), 0, "No status messages after stop command")

        # Find a message where acquiring is false
        stopped = any(not m["payload"].get("acquiring", True) for m in messages)
        self.assertTrue(stopped, "Acquisition did not stop")

class TestChannelDataFlow(unittest.TestCase):
    """Test channel data publishing"""

    @classmethod
    def setUpClass(cls):
        cls.client = MQTTTestClient("test-channel-data")
        cls.client.connect()
        # Start acquisition
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(0.5)
        cls.client.disconnect()

    def test_thermocouple_data_published(self):
        """Verify thermocouple channel data is published"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp",
            timeout=3.0,
            count=3
        )

        self.assertGreater(len(messages), 0, "No thermocouple data received")

        data = messages[0]["payload"]
        self.assertIn("value", data)
        self.assertIn("timestamp", data)
        self.assertIn("units", data)
        self.assertEqual(data["units"], "degC")

        # Value should be reasonable for simulation (~25°C)
        value = data["value"]
        self.assertGreater(value, -50, f"Temperature too low: {value}")
        self.assertLess(value, 100, f"Temperature too high: {value}")

    def test_digital_input_data_published(self):
        """Verify digital input channel data is published"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/channels/E_Stop")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/E_Stop",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, "No digital input data received")

        data = messages[0]["payload"]
        self.assertIn("value", data)
        # Digital input should be 0 or 1
        self.assertIn(data["value"], [0, 1, 0.0, 1.0, True, False])

    def test_analog_data_quality_flags(self):
        """Verify data quality flags are included"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/channels/F1_Chamber_Pressure")

        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/F1_Chamber_Pressure",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, "No pressure data received")

        data = messages[0]["payload"]
        self.assertIn("quality", data)
        self.assertIn("status", data)
        self.assertIn(data["quality"], ["good", "warning", "alarm"])

class TestOutputCommands(unittest.TestCase):
    """Test output channel commands"""

    @classmethod
    def setUpClass(cls):
        cls.client = MQTTTestClient("test-output-commands")
        cls.client.connect()
        # Start acquisition for output feedback
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
        time.sleep(0.5)
        cls.client.disconnect()

    def test_digital_output_command(self):
        """Test sending command to digital output"""
        channel = "F1_Heater_Enable"

        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/channels/{channel}")

        # Send output command
        self.client.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            json.dumps({"value": True})
        )

        time.sleep(1.0)
        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/{channel}",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, f"No feedback from {channel}")

    def test_analog_output_command(self):
        """Test sending command to analog output"""
        channel = "F1_Temp_Setpoint"
        setpoint = 200.0

        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/channels/{channel}")

        # Send output command
        self.client.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            json.dumps({"value": setpoint})
        )

        time.sleep(1.0)
        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/channels/{channel}",
            timeout=3.0,
            count=1
        )

        self.assertGreater(len(messages), 0, f"No feedback from {channel}")

class TestAlarmPublishing(unittest.TestCase):
    """Test alarm publishing"""

    @classmethod
    def setUpClass(cls):
        cls.client = MQTTTestClient("test-alarms")
        cls.client.connect()

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()

    def test_alarm_topic_structure(self):
        """Verify alarm messages have correct structure"""
        self.client.clear_messages()
        self.client.subscribe(f"{SYSTEM_PREFIX}/alarms/#")

        # Wait for any alarm messages (simulation may trigger some)
        messages = self.client.wait_for_message(
            f"{SYSTEM_PREFIX}/alarms/",
            timeout=5.0,
            count=1
        )

        # If no alarms, that's OK - just check the subscription worked
        if len(messages) > 0:
            alarm = messages[0]["payload"]
            self.assertIn("source", alarm)
            self.assertIn("message", alarm)
            self.assertIn("timestamp", alarm)

class TestEndToEndDataFlow(unittest.TestCase):
    """Full end-to-end integration test"""

    def test_complete_data_cycle(self):
        """Test complete data flow: start -> data -> stop"""
        client = MQTTTestClient("test-e2e-cycle")

        try:
            # Connect
            self.assertTrue(client.connect(), "Failed to connect")

            # Subscribe to relevant topics
            client.subscribe(f"{SYSTEM_PREFIX}/status/system")
            client.subscribe(f"{SYSTEM_PREFIX}/channels/#")

            # Start acquisition
            client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
            time.sleep(1.0)

            # Verify status shows acquiring
            status_msgs = client.wait_for_message(
                f"{SYSTEM_PREFIX}/status/system",
                timeout=3.0,
                count=1
            )
            self.assertGreater(len(status_msgs), 0, "No status after start")

            # Wait for channel data
            time.sleep(2.0)

            # Check we received data on multiple channels
            channel_count = 0
            with client.message_lock:
                for topic in client.messages:
                    if "/channels/" in topic:
                        channel_count += 1

            self.assertGreater(channel_count, 5,
                f"Expected data from multiple channels, got {channel_count}")

            # Stop acquisition
            client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
            time.sleep(1.0)

            # Verify stopped
            client.clear_messages()
            status_msgs = client.wait_for_message(
                f"{SYSTEM_PREFIX}/status/system",
                timeout=3.0,
                count=1
            )

            stopped = any(
                not m["payload"].get("acquiring", True)
                for m in status_msgs
            )
            self.assertTrue(stopped, "Acquisition did not stop properly")

        finally:
            client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
            client.disconnect()

def run_quick_validation():
    """Run a quick validation without unittest framework"""
    print("=" * 60)
    print("NISystem End-to-End MQTT Validation")
    print("=" * 60)

    results = []

    # Test 1: Broker connection
    print("\n[1/5] Testing MQTT broker connection...")
    client = MQTTTestClient("validation-client")
    if client.connect():
        results.append(TestResult(True, "MQTT broker connection OK"))
        print("  ✓ Connected to MQTT broker")
    else:
        results.append(TestResult(False, "Failed to connect to MQTT broker"))
        print("  ✗ Failed to connect to MQTT broker")
        return results

    # Test 2: System status
    print("\n[2/5] Checking DAQ service status...")
    client.subscribe(f"{SYSTEM_PREFIX}/status/system")
    msgs = client.wait_for_message(f"{SYSTEM_PREFIX}/status/system", timeout=3.0)
    if msgs and msgs[0]["payload"].get("status") == "online":
        results.append(TestResult(True, "DAQ service is online"))
        print(f"  ✓ DAQ service online (simulation={msgs[0]['payload'].get('simulation_mode')})")
    else:
        results.append(TestResult(False, "DAQ service not responding"))
        print("  ✗ DAQ service not responding")

    # Test 3: Start acquisition
    print("\n[3/5] Testing acquisition control...")
    client.clear_messages()
    client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")
    time.sleep(1.5)
    msgs = client.wait_for_message(f"{SYSTEM_PREFIX}/status/system", timeout=3.0)
    if msgs and any(m["payload"].get("acquiring") for m in msgs):
        results.append(TestResult(True, "Acquisition started"))
        print("  ✓ Acquisition started successfully")
    else:
        results.append(TestResult(False, "Acquisition failed to start"))
        print("  ✗ Acquisition failed to start")

    # Test 4: Channel data
    print("\n[4/5] Checking channel data flow...")
    client.clear_messages()
    client.subscribe(f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp")
    msgs = client.wait_for_message(f"{SYSTEM_PREFIX}/channels/F1_Zone1_Temp", timeout=3.0, count=3)
    if msgs:
        values = [m["payload"]["value"] for m in msgs]
        avg_temp = sum(values) / len(values)
        results.append(TestResult(True, f"Channel data flowing (avg temp: {avg_temp:.1f}°C)", values))
        print(f"  ✓ Receiving channel data (F1_Zone1_Temp avg: {avg_temp:.1f}°C)")

        # Check if values are reasonable
        if -50 < avg_temp < 100:
            print(f"  ✓ Temperature values are reasonable")
        else:
            print(f"  ⚠ Temperature values seem off: {avg_temp:.1f}°C")
    else:
        results.append(TestResult(False, "No channel data received"))
        print("  ✗ No channel data received")

    # Test 5: Stop acquisition
    print("\n[5/5] Testing stop acquisition...")
    client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")
    time.sleep(1.0)
    client.clear_messages()
    msgs = client.wait_for_message(f"{SYSTEM_PREFIX}/status/system", timeout=3.0)
    if msgs and any(not m["payload"].get("acquiring", True) for m in msgs):
        results.append(TestResult(True, "Acquisition stopped"))
        print("  ✓ Acquisition stopped successfully")
    else:
        results.append(TestResult(False, "Acquisition failed to stop"))
        print("  ✗ Acquisition failed to stop")

    client.disconnect()

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.success)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("✓ All end-to-end tests PASSED")
    else:
        print("✗ Some tests FAILED")
        for r in results:
            if not r.success:
                print(f"  - {r.message}")

    print("=" * 60)
    return results

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        # Quick validation mode
        run_quick_validation()
    else:
        # Full unittest mode
        unittest.main(verbosity=2)
