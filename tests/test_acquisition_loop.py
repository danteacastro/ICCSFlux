#!/usr/bin/env python3
"""
Acquisition Loop Integration Tests

Tests the complete acquisition loop between DAQ service and cRIO:
1. Command flow (start/stop with ACKs)
2. State synchronization
3. Value publishing
4. Session management
5. Alarm forwarding

Run:
    python tests/test_acquisition_loop.py
    pytest tests/test_acquisition_loop.py -v
"""

import json
import time
import threading
import uuid
import sys
import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("Warning: paho-mqtt not installed")

# Configuration
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_BASE = "nisystem"
CRIO_NODE_ID = "crio-001"

@dataclass
class Message:
    topic: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

class MessageCollector:
    """Collects MQTT messages for test assertions."""

    def __init__(self):
        self.messages: List[Message] = []
        self._lock = threading.Lock()

    def add(self, topic: str, payload: Dict):
        with self._lock:
            self.messages.append(Message(topic, payload))

    def clear(self):
        with self._lock:
            self.messages.clear()

    def find(self, topic_contains: str, timeout: float = 5.0) -> Optional[Message]:
        """Wait for message containing topic pattern."""
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                for msg in reversed(self.messages):
                    if topic_contains in msg.topic:
                        return msg
            time.sleep(0.05)
        return None

    def find_with_field(self, topic_contains: str, field: str, value: Any,
                        timeout: float = 5.0) -> Optional[Message]:
        """Wait for message with specific field value."""
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                for msg in reversed(self.messages):
                    if topic_contains in msg.topic:
                        if msg.payload.get(field) == value:
                            return msg
            time.sleep(0.05)
        return None

    def count(self, topic_contains: str) -> int:
        """Count messages matching pattern."""
        with self._lock:
            return sum(1 for m in self.messages if topic_contains in m.topic)

    def all(self, topic_contains: str) -> List[Message]:
        """Get all messages matching pattern."""
        with self._lock:
            return [m for m in self.messages if topic_contains in m.topic]

class CRIOSimulator:
    """
    Simulates cRIO Node V2 behavior for testing.

    Implements the same MQTT protocol as the real cRIO node:
    - Responds to acquire/start, acquire/stop
    - Publishes command ACKs
    - Publishes channel values when acquiring
    - Handles session start/stop
    - Publishes alarm events
    """

    def __init__(self, broker: str = MQTT_BROKER, node_id: str = CRIO_NODE_ID):
        self.broker = broker
        self.node_id = node_id
        self.topic_prefix = f"{MQTT_BASE}/nodes/{node_id}"

        self.client = mqtt.Client(client_id=f"crio-sim-{node_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        # State
        self.connected = False
        self.state = "IDLE"  # IDLE, ACQUIRING, SESSION
        self.channels: Dict[str, Dict] = {}
        self.config_version = 0

        # Value simulation
        self._acquiring = False
        self._value_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Callbacks for test hooks
        self.on_command: Optional[Callable] = None

    @property
    def acquiring(self) -> bool:
        return self.state in ("ACQUIRING", "SESSION")

    @property
    def session_active(self) -> bool:
        return self.state == "SESSION"

    def connect(self) -> bool:
        try:
            self.client.connect(self.broker, MQTT_PORT)
            self.client.loop_start()
            for _ in range(50):
                if self.connected:
                    return True
                time.sleep(0.1)
            return False
        except Exception as e:
            print(f"CRIOSimulator connect error: {e}")
            return False

    def disconnect(self):
        self._stop_event.set()
        if self._value_thread:
            self._value_thread.join(timeout=2.0)
        self._publish("status/offline", {"node_id": self.node_id})
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            # Subscribe to commands
            client.subscribe(f"{self.topic_prefix}/system/acquire/#")
            client.subscribe(f"{self.topic_prefix}/session/#")
            client.subscribe(f"{self.topic_prefix}/config/#")
            client.subscribe(f"{self.topic_prefix}/alarm/#")
            client.subscribe(f"{MQTT_BASE}/discovery/ping")
            # Publish initial status
            self._publish_status()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except:
            payload = {}

        topic = msg.topic

        # Notify test hook
        if self.on_command:
            self.on_command(topic, payload)

        # Route commands
        if "/acquire/start" in topic:
            self._cmd_acquire_start(payload)
        elif "/acquire/stop" in topic:
            self._cmd_acquire_stop(payload)
        elif "/session/start" in topic:
            self._cmd_session_start(payload)
        elif "/session/stop" in topic:
            self._cmd_session_stop(payload)
        elif "/config/full" in topic:
            self._cmd_config_full(payload)
        elif "discovery/ping" in topic:
            self._publish_status()

    def _cmd_acquire_start(self, payload: Dict):
        request_id = payload.get('request_id', '')

        if self.state == "IDLE":
            self.state = "ACQUIRING"
            self._start_value_publishing()
            self._publish_ack('acquire/start', True, request_id=request_id)
        elif self.acquiring:
            self._publish_ack('acquire/start', True, reason='Already acquiring',
                            request_id=request_id)
        else:
            self._publish_ack('acquire/start', False, reason='Invalid state',
                            request_id=request_id)

        self._publish_status()

    def _cmd_acquire_stop(self, payload: Dict):
        request_id = payload.get('request_id', '')

        if self.acquiring:
            self.state = "IDLE"
            self._stop_event.set()
            self._publish_ack('acquire/stop', True, request_id=request_id)
        else:
            self._publish_ack('acquire/stop', True, reason='Not acquiring',
                            request_id=request_id)

        self._publish_status()

    def _cmd_session_start(self, payload: Dict):
        request_id = payload.get('request_id', '')

        if self.state != "ACQUIRING":
            self._publish_ack('session/start', False,
                            reason='Must be acquiring to start session',
                            request_id=request_id)
            return

        self.state = "SESSION"
        self._publish_ack('session/start', True, request_id=request_id)
        self._publish_session_status()

    def _cmd_session_stop(self, payload: Dict):
        request_id = payload.get('request_id', '')

        if self.state == "SESSION":
            self.state = "ACQUIRING"
            self._publish_ack('session/stop', True, request_id=request_id)
        else:
            self._publish_ack('session/stop', True, reason='No active session',
                            request_id=request_id)

        self._publish_session_status()

    def _cmd_config_full(self, payload: Dict):
        channels_data = payload.get('channels', {})

        if isinstance(channels_data, list):
            self.channels = {ch['name']: ch for ch in channels_data}
        else:
            self.channels = channels_data

        self.config_version += 1

        self._publish("config/response", {
            'status': 'success',
            'success': True,
            'channels': len(self.channels),
            'config_version': self.config_version,
            'timestamp': datetime.now().isoformat()
        })

    def _start_value_publishing(self):
        self._stop_event.clear()
        self._value_thread = threading.Thread(target=self._value_loop, daemon=True)
        self._value_thread.start()

    def _value_loop(self):
        import random

        while not self._stop_event.is_set() and self.acquiring:
            ts = time.time()

            # Publish batch
            batch = {}
            for name, ch in self.channels.items():
                ch_type = ch.get('channel_type', 'voltage_input')
                if 'thermocouple' in ch_type:
                    value = 25.0 + random.uniform(-0.5, 0.5)
                elif 'digital' in ch_type:
                    value = float(random.choice([0, 1]))
                else:
                    value = random.uniform(0, 10)

                batch[name] = {
                    'value': value,
                    'timestamp': ts,
                    'quality': 'good'
                }

            if batch:
                self._publish("channels/batch", batch)

            # Publish sys channels
            self._publish("channels/sys.acquiring", {
                'value': 1.0 if self.acquiring else 0.0,
                'timestamp': ts
            })
            self._publish("channels/sys.session_active", {
                'value': 1.0 if self.session_active else 0.0,
                'timestamp': ts
            })

            time.sleep(0.1)

    def _publish(self, subtopic: str, payload: Dict):
        self.client.publish(f"{self.topic_prefix}/{subtopic}", json.dumps(payload))

    def _publish_status(self):
        self._publish("status/system", {
            'status': 'online',
            'node_type': 'crio',
            'node_id': self.node_id,
            'acquiring': self.acquiring,
            'session_active': self.session_active,
            'channels': len(self.channels),
            'config_version': self.config_version,
            'timestamp': datetime.now().isoformat()
        })

    def _publish_session_status(self):
        self._publish("session/status", {
            'state': self.state,
            'acquiring': self.acquiring,
            'session_active': self.session_active,
            'timestamp': datetime.now().isoformat()
        })

    def _publish_ack(self, command: str, success: bool, reason: str = None,
                     request_id: str = None):
        ack = {
            'success': success,
            'command': command,
            'node_id': self.node_id,
            'state': self.state,
            'acquiring': self.acquiring,
            'session_active': self.session_active,
            'timestamp': datetime.now().isoformat()
        }
        if reason:
            ack['reason'] = reason
        if request_id:
            ack['request_id'] = request_id

        self._publish("command/ack", ack)

    # Test helpers
    def trigger_alarm(self, channel: str, alarm_type: str, value: float, limit: float):
        """Trigger a simulated alarm for testing."""
        self._publish("alarm/event", {
            'channel': channel,
            'alarm_type': alarm_type,
            'value': value,
            'limit': limit,
            'severity': 'CRITICAL' if alarm_type in ('hihi', 'lolo') else 'WARNING',
            'state': 'ACTIVE',
            'timestamp': datetime.now().isoformat()
        })

        self._publish("alarm/status", {
            'counts': {'active': 1, 'acknowledged': 0, 'returned': 0, 'total': 1},
            'active': [{'channel': channel, 'alarm_type': alarm_type}],
            'timestamp': datetime.now().isoformat()
        })

class DAQServiceSimulator:
    """
    Simulates DAQ service behavior for testing cRIO responses.

    Sends commands and collects responses to validate protocol.
    """

    def __init__(self, broker: str = MQTT_BROKER):
        self.broker = broker
        self.client = mqtt.Client(client_id=f"daq-sim-{uuid.uuid4().hex[:8]}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.connected = False
        self.messages = MessageCollector()

    def connect(self) -> bool:
        try:
            self.client.connect(self.broker, MQTT_PORT)
            self.client.loop_start()
            for _ in range(50):
                if self.connected:
                    return True
                time.sleep(0.1)
            return False
        except Exception as e:
            print(f"DAQServiceSimulator connect error: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe(f"{MQTT_BASE}/#")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except:
            payload = {}
        self.messages.add(msg.topic, payload)

    def send_acquire_start(self, node_id: str = CRIO_NODE_ID) -> str:
        """Send acquire start command, return request_id."""
        request_id = str(uuid.uuid4())
        self.client.publish(
            f"{MQTT_BASE}/nodes/{node_id}/system/acquire/start",
            json.dumps({'command': 'start', 'request_id': request_id})
        )
        return request_id

    def send_acquire_stop(self, node_id: str = CRIO_NODE_ID) -> str:
        """Send acquire stop command, return request_id."""
        request_id = str(uuid.uuid4())
        self.client.publish(
            f"{MQTT_BASE}/nodes/{node_id}/system/acquire/stop",
            json.dumps({'command': 'stop', 'request_id': request_id})
        )
        return request_id

    def send_session_start(self, node_id: str = CRIO_NODE_ID,
                          name: str = "test", operator: str = "tester") -> str:
        """Send session start command."""
        request_id = str(uuid.uuid4())
        self.client.publish(
            f"{MQTT_BASE}/nodes/{node_id}/session/start",
            json.dumps({
                'name': name,
                'operator': operator,
                'request_id': request_id
            })
        )
        return request_id

    def send_session_stop(self, node_id: str = CRIO_NODE_ID) -> str:
        """Send session stop command."""
        request_id = str(uuid.uuid4())
        self.client.publish(
            f"{MQTT_BASE}/nodes/{node_id}/session/stop",
            json.dumps({'reason': 'user_command', 'request_id': request_id})
        )
        return request_id

    def send_config(self, channels: List[Dict], node_id: str = CRIO_NODE_ID):
        """Push channel config to cRIO."""
        self.client.publish(
            f"{MQTT_BASE}/nodes/{node_id}/config/full",
            json.dumps({'channels': channels})
        )

    def send_discovery_ping(self):
        """Send discovery ping."""
        self.client.publish(f"{MQTT_BASE}/discovery/ping", json.dumps({'source': 'test'}))

# =============================================================================
# TESTS
# =============================================================================

class TestAcquisitionLoop:
    """Test acquisition loop with command ACKs."""

    @classmethod
    def setup_class(cls):
        if not MQTT_AVAILABLE:
            return

        cls.crio = CRIOSimulator()
        cls.daq = DAQServiceSimulator()

        assert cls.crio.connect(), "cRIO simulator failed to connect"
        assert cls.daq.connect(), "DAQ simulator failed to connect"
        time.sleep(0.5)

    @classmethod
    def teardown_class(cls):
        if not MQTT_AVAILABLE:
            return
        cls.daq.disconnect()
        cls.crio.disconnect()

    def setup_method(self):
        if not MQTT_AVAILABLE:
            return
        self.daq.messages.clear()
        # Ensure cRIO is in IDLE state
        if self.crio.acquiring:
            self.daq.send_acquire_stop()
            time.sleep(0.3)

    def test_acquire_start_ack(self):
        """Test that acquire/start returns proper ACK."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        request_id = self.daq.send_acquire_start()

        # Wait for ACK
        ack = self.daq.messages.find_with_field("command/ack", "command", "acquire/start", timeout=2.0)
        assert ack is not None, "No ACK received for acquire/start"
        assert ack.payload['success'] == True
        assert ack.payload['request_id'] == request_id
        assert ack.payload['acquiring'] == True
        assert ack.payload['state'] == 'ACQUIRING'

    def test_acquire_stop_ack(self):
        """Test that acquire/stop returns proper ACK."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        # First start
        self.daq.send_acquire_start()
        time.sleep(0.3)

        request_id = self.daq.send_acquire_stop()

        # Wait for ACK
        ack = self.daq.messages.find_with_field("command/ack", "command", "acquire/stop", timeout=2.0)
        assert ack is not None, "No ACK received for acquire/stop"
        assert ack.payload['success'] == True
        assert ack.payload['request_id'] == request_id
        assert ack.payload['acquiring'] == False

    def test_values_published_while_acquiring(self):
        """Test that channel values are published during acquisition."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        # Push config with multiple channel types
        self.daq.send_config([
            {'name': 'CH_1', 'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
            {'name': 'CH_2', 'physical_channel': 'Mod1/ai1', 'channel_type': 'voltage_input'},
            {'name': 'TC_01', 'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
            {'name': 'DI_01', 'physical_channel': 'Mod3/port0/line0', 'channel_type': 'digital_input'},
        ])
        time.sleep(0.2)

        # Start acquiring
        self.daq.messages.clear()
        self.daq.send_acquire_start()
        time.sleep(0.3)

        # Collect values
        self.daq.messages.clear()
        time.sleep(1.0)

        batches = self.daq.messages.all("channels/batch")
        assert len(batches) >= 5, f"Expected ~10 batches, got {len(batches)}"

        # Verify batch content - all channels present
        last_batch = batches[-1]
        for ch_name in ['CH_1', 'CH_2', 'TC_01', 'DI_01']:
            assert ch_name in last_batch.payload, f"Channel {ch_name} missing from batch"

        # Verify each channel has required fields
        for ch_name, ch_data in last_batch.payload.items():
            # value field
            assert 'value' in ch_data, f"{ch_name} missing 'value'"
            assert isinstance(ch_data['value'], (int, float)), f"{ch_name} value not numeric"

            # timestamp field
            assert 'timestamp' in ch_data, f"{ch_name} missing 'timestamp'"
            assert isinstance(ch_data['timestamp'], (int, float)), f"{ch_name} timestamp not numeric"
            assert ch_data['timestamp'] > 0, f"{ch_name} timestamp invalid"

            # quality field
            assert 'quality' in ch_data, f"{ch_name} missing 'quality'"
            assert ch_data['quality'] in ('good', 'bad', 'uncertain'), f"{ch_name} invalid quality"

        # Verify TC value is in plausible range (not 0-10V)
        tc_data = last_batch.payload['TC_01']
        assert -40 <= tc_data['value'] <= 1300, f"TC value {tc_data['value']} out of range"

        # Verify DI value is 0 or 1
        di_data = last_batch.payload['DI_01']
        assert di_data['value'] in (0.0, 1.0), f"DI value {di_data['value']} not boolean"

        # Cleanup
        self.daq.send_acquire_stop()

    def test_session_requires_acquiring(self):
        """Test that session start fails if not acquiring."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        # Ensure not acquiring
        self.crio.state = "IDLE"

        request_id = self.daq.send_session_start()

        ack = self.daq.messages.find_with_field("command/ack", "command", "session/start", timeout=2.0)
        assert ack is not None, "No ACK received"
        assert ack.payload['success'] == False
        assert 'acquiring' in ack.payload.get('reason', '').lower()

    def test_session_start_stop_flow(self):
        """Test complete session flow."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        # Start acquiring
        self.daq.send_acquire_start()
        time.sleep(0.3)

        # Start session
        self.daq.messages.clear()
        request_id = self.daq.send_session_start(name="TestSession", operator="TestOp")

        ack = self.daq.messages.find_with_field("command/ack", "command", "session/start", timeout=2.0)
        assert ack is not None, "No ACK for session start"
        assert ack.payload['success'] == True
        assert ack.payload['session_active'] == True
        assert ack.payload['state'] == 'SESSION'

        # Verify session status
        status = self.daq.messages.find("session/status", timeout=2.0)
        assert status is not None
        assert status.payload['session_active'] == True

        # Stop session
        self.daq.messages.clear()
        self.daq.send_session_stop()

        ack = self.daq.messages.find_with_field("command/ack", "command", "session/stop", timeout=2.0)
        assert ack is not None
        assert ack.payload['success'] == True
        assert ack.payload['session_active'] == False

        # Cleanup
        self.daq.send_acquire_stop()

    def test_sys_channel_sync(self):
        """Test sys.acquiring and sys.session_active channels."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        # Start acquiring
        self.daq.messages.clear()
        self.daq.send_acquire_start()
        time.sleep(0.5)

        # Check sys.acquiring
        msg = self.daq.messages.find("channels/sys.acquiring", timeout=2.0)
        assert msg is not None, "No sys.acquiring published"
        assert msg.payload['value'] == 1.0

        # Cleanup
        self.daq.send_acquire_stop()

    def test_config_push_response(self):
        """Test config push receives proper response."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        self.daq.messages.clear()
        self.daq.send_config([
            {'name': 'TC_01', 'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
            {'name': 'TC_02', 'physical_channel': 'Mod5/ai1', 'channel_type': 'thermocouple'},
            {'name': 'AI_01', 'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
        ])

        response = self.daq.messages.find("config/response", timeout=2.0)
        assert response is not None, "No config response"
        assert response.payload['status'] == 'success'
        assert response.payload['channels'] == 3

    def test_alarm_event_publishing(self):
        """Test alarm events are published correctly."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        self.daq.messages.clear()

        # Trigger simulated alarm
        self.crio.trigger_alarm('TC_01', 'hihi', 105.5, 100.0)

        # Check alarm event
        event = self.daq.messages.find("alarm/event", timeout=2.0)
        assert event is not None, "No alarm event published"
        assert event.payload['channel'] == 'TC_01'
        assert event.payload['alarm_type'] == 'hihi'
        assert event.payload['severity'] == 'CRITICAL'

        # Check alarm status
        status = self.daq.messages.find("alarm/status", timeout=2.0)
        assert status is not None
        assert status.payload['counts']['active'] == 1

    def test_discovery_response(self):
        """Test cRIO responds to discovery ping."""
        if not MQTT_AVAILABLE:
            print("SKIP: MQTT not available")
            return

        self.daq.messages.clear()
        self.daq.send_discovery_ping()

        status = self.daq.messages.find("status/system", timeout=2.0)
        assert status is not None, "No status response to discovery"
        assert status.payload['node_type'] == 'crio'
        assert status.payload['node_id'] == CRIO_NODE_ID

def run_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("Acquisition Loop Integration Tests")
    print("="*60)

    if not MQTT_AVAILABLE:
        print("\nERROR: paho-mqtt not installed")
        print("Run: pip install paho-mqtt")
        return False

    # Setup
    crio = CRIOSimulator()
    daq = DAQServiceSimulator()

    if not crio.connect():
        print("\nERROR: Could not connect cRIO simulator to MQTT")
        print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
        return False

    if not daq.connect():
        print("\nERROR: Could not connect DAQ simulator to MQTT")
        crio.disconnect()
        return False

    time.sleep(0.5)

    tests = [
        ("Acquire Start ACK", lambda: test_acquire_start_ack(crio, daq)),
        ("Acquire Stop ACK", lambda: test_acquire_stop_ack(crio, daq)),
        ("Values While Acquiring", lambda: test_values_while_acquiring(crio, daq)),
        ("Session Requires Acquiring", lambda: test_session_requires_acquiring(crio, daq)),
        ("Session Flow", lambda: test_session_flow(crio, daq)),
        ("Sys Channel Sync", lambda: test_sys_channel_sync(crio, daq)),
        ("Config Push", lambda: test_config_push(crio, daq)),
        ("Alarm Events", lambda: test_alarm_events(crio, daq)),
        ("Discovery Response", lambda: test_discovery_response(crio, daq)),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        # Reset state
        daq.messages.clear()
        if crio.acquiring:
            daq.send_acquire_stop()
            time.sleep(0.3)
            daq.messages.clear()

        print(f"\nTest: {name}")
        try:
            test_fn()
            print(f"  [PASS]")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1

    # Cleanup
    daq.disconnect()
    crio.disconnect()

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)

    return failed == 0

# Standalone test functions
def test_acquire_start_ack(crio: CRIOSimulator, daq: DAQServiceSimulator):
    request_id = daq.send_acquire_start()
    ack = daq.messages.find_with_field("command/ack", "command", "acquire/start", timeout=2.0)
    assert ack is not None, "No ACK received"
    assert ack.payload['success'] == True
    assert ack.payload['request_id'] == request_id
    assert ack.payload['acquiring'] == True

def test_acquire_stop_ack(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.send_acquire_start()
    time.sleep(0.3)
    daq.messages.clear()

    request_id = daq.send_acquire_stop()
    ack = daq.messages.find_with_field("command/ack", "command", "acquire/stop", timeout=2.0)
    assert ack is not None, "No ACK received"
    assert ack.payload['success'] == True
    assert ack.payload['acquiring'] == False

def test_values_while_acquiring(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.send_config([
        {'name': 'CH_1', 'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
    ])
    time.sleep(0.2)

    daq.messages.clear()
    daq.send_acquire_start()
    time.sleep(1.0)

    batches = daq.messages.all("channels/batch")
    assert len(batches) >= 5, f"Expected ~10 batches, got {len(batches)}"

    daq.send_acquire_stop()

def test_session_requires_acquiring(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.send_session_start()
    ack = daq.messages.find_with_field("command/ack", "command", "session/start", timeout=2.0)
    assert ack is not None
    assert ack.payload['success'] == False

def test_session_flow(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.send_acquire_start()
    time.sleep(0.3)
    daq.messages.clear()

    daq.send_session_start()
    ack = daq.messages.find_with_field("command/ack", "command", "session/start", timeout=2.0)
    assert ack is not None
    assert ack.payload['success'] == True
    assert ack.payload['session_active'] == True

    daq.messages.clear()
    daq.send_session_stop()
    ack = daq.messages.find_with_field("command/ack", "command", "session/stop", timeout=2.0)
    assert ack is not None
    assert ack.payload['session_active'] == False

    daq.send_acquire_stop()

def test_sys_channel_sync(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.messages.clear()
    daq.send_acquire_start()
    time.sleep(0.5)

    msg = daq.messages.find("channels/sys.acquiring", timeout=2.0)
    assert msg is not None
    assert msg.payload['value'] == 1.0

    daq.send_acquire_stop()

def test_config_push(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.messages.clear()
    daq.send_config([
        {'name': 'TC_01', 'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
    ])

    response = daq.messages.find("config/response", timeout=2.0)
    assert response is not None
    assert response.payload['status'] == 'success'

def test_alarm_events(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.messages.clear()
    crio.trigger_alarm('TC_01', 'hihi', 105.5, 100.0)

    event = daq.messages.find("alarm/event", timeout=2.0)
    assert event is not None
    assert event.payload['alarm_type'] == 'hihi'

def test_discovery_response(crio: CRIOSimulator, daq: DAQServiceSimulator):
    daq.messages.clear()
    daq.send_discovery_ping()

    status = daq.messages.find("status/system", timeout=2.0)
    assert status is not None
    assert status.payload['node_type'] == 'crio'

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
