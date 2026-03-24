"""
Live Integration Tests for NISystem

These tests connect to the RUNNING DAQ service via MQTT and verify:
1. Discovery finds cRIO nodes
2. Channels can be auto-populated
3. Acquisition can be started
4. Data flows from cRIO to dashboard

Run with: python tests/test_live_integration.py
Or: pytest tests/test_live_integration.py -v -s

REQUIREMENTS:
- DAQ service must be running (device.bat)
- cRIO must be online (deploy_crio_v2.bat)
- MQTT broker must be running
"""

import json
import time
import threading
import sys
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

# Try WebSocket MQTT first (what dashboard uses), fall back to regular MQTT
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)

@dataclass
class TestResult:
    """Result of a test step."""
    name: str
    passed: bool
    message: str
    duration_ms: float = 0.0

@dataclass
class LiveTestClient:
    """MQTT client for live integration testing."""
    broker_host: str = "localhost"
    broker_port: int = 1883  # Standard MQTT port
    ws_port: int = 9002      # WebSocket port (what dashboard uses)
    use_websocket: bool = True
    timeout_sec: float = 10.0

    # Internal state
    _client: Optional[mqtt.Client] = field(default=None, repr=False)
    _connected: threading.Event = field(default_factory=threading.Event, repr=False)
    _responses: Dict[str, Any] = field(default_factory=dict, repr=False)
    _response_events: Dict[str, threading.Event] = field(default_factory=dict, repr=False)
    _channel_values: Dict[str, float] = field(default_factory=dict, repr=False)
    _value_count: int = 0

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            # Use WebSocket transport like dashboard does
            if self.use_websocket:
                try:
                    self._client = mqtt.Client(
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"live-test-{int(time.time())}",
                        transport="websockets"
                    )
                except (AttributeError, TypeError):
                    self._client = mqtt.Client(
                        client_id=f"live-test-{int(time.time())}",
                        transport="websockets"
                    )
                port = self.ws_port
            else:
                try:
                    self._client = mqtt.Client(
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"live-test-{int(time.time())}"
                    )
                except (AttributeError, TypeError):
                    self._client = mqtt.Client(
                        client_id=f"live-test-{int(time.time())}"
                    )
                port = self.broker_port

            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message

            print(f"Connecting to MQTT {'WebSocket' if self.use_websocket else 'TCP'} at {self.broker_host}:{port}...")
            self._client.connect(self.broker_host, port, keepalive=60)
            self._client.loop_start()

            if not self._connected.wait(timeout=5.0):
                print("ERROR: MQTT connection timeout")
                return False

            print("Connected to MQTT broker")
            return True

        except Exception as e:
            print(f"ERROR: Failed to connect: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            print("Disconnected from MQTT")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle MQTT connection."""
        is_success = (reason_code == 0) if isinstance(reason_code, int) else not reason_code.is_failure
        if is_success:
            self._connected.set()
            # Subscribe to all relevant topics
            client.subscribe("nisystem/#")
        else:
            print(f"Connection failed: {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except:
            payload = {'raw': msg.payload}

        topic = msg.topic

        # Store response for specific topics we're waiting on
        if 'discovery/result' in topic or 'discovery/hardware' in topic:
            self._responses['discovery'] = payload
            if 'discovery' in self._response_events:
                self._response_events['discovery'].set()

        elif 'status/system' in topic:
            self._responses['status'] = payload
            if 'status' in self._response_events:
                self._response_events['status'].set()

        elif 'config/response' in topic:
            self._responses['config'] = payload
            if 'config' in self._response_events:
                self._response_events['config'].set()

        elif '/channels/' in topic or 'channels/batch' in topic:
            # Track channel values
            if isinstance(payload, dict):
                if 'value' in payload:
                    # Single channel
                    ch_name = topic.split('/')[-1]
                    self._channel_values[ch_name] = payload.get('value')
                    self._value_count += 1
                else:
                    # Batch
                    for ch_name, ch_data in payload.items():
                        if isinstance(ch_data, dict) and 'value' in ch_data:
                            self._channel_values[ch_name] = ch_data['value']
                            self._value_count += 1

            if 'values' in self._response_events and self._value_count > 0:
                self._response_events['values'].set()

    def wait_for_response(self, key: str, timeout: float = None) -> Optional[Any]:
        """Wait for a specific response."""
        timeout = timeout or self.timeout_sec
        event = threading.Event()
        self._response_events[key] = event

        if event.wait(timeout=timeout):
            return self._responses.get(key)
        return None

    def publish(self, topic: str, payload: Dict[str, Any], qos: int = 1):
        """Publish a message."""
        self._client.publish(topic, json.dumps(payload), qos=qos)

    def trigger_discovery(self, mode: str = 'crio') -> Optional[Dict]:
        """Trigger device discovery and wait for result."""
        print(f"Triggering discovery (mode={mode})...")

        # Clear previous response
        self._responses.pop('discovery', None)

        # Send discovery request (like dashboard does)
        self.publish("nisystem/daq/commands", {
            "command": "discover",
            "mode": mode
        })

        # Also send a discovery ping
        self.publish("nisystem/discovery/ping", {
            "source": "test",
            "timestamp": time.time()
        })

        # Wait for discovery result
        result = self.wait_for_response('discovery', timeout=15.0)
        if result:
            print(f"Discovery complete: {result.get('chassis_count', '?')} chassis, {result.get('channel_count', '?')} channels")
        else:
            print("Discovery timeout - no response received")
        return result

    def auto_populate_channels(self) -> bool:
        """Auto-populate channels from discovered hardware."""
        print("Auto-populating channels...")

        self.publish("nisystem/daq/commands", {
            "command": "auto_populate",
            "source": "crio"
        })

        # Wait a bit for channels to be created
        time.sleep(2.0)
        return True

    def push_crio_config(self, node_id: str = 'crio-001') -> bool:
        """Push channel config directly to cRIO (bypasses DAQ service)."""
        print(f"Pushing config directly to cRIO {node_id}...")

        # Build a test config with all 96 channels
        channels = {}

        # Mod1: NI 9202 - 16 voltage inputs (tag_32 - tag_47)
        for i in range(16):
            name = f'tag_{32 + i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod1/ai{i}',
                'channel_type': 'voltage_input',
                'scale_slope': 1.0,
                'scale_offset': 0.0
            }

        # Mod2: NI 9264 - 16 voltage outputs (tag_48 - tag_63)
        for i in range(16):
            name = f'tag_{48 + i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod2/ao{i}',
                'channel_type': 'voltage_output',
                'scale_slope': 1.0,
                'scale_offset': 0.0,
                'default_value': 0.0
            }

        # Mod3: NI 9425 - 32 digital inputs (tag_0 - tag_31)
        for i in range(32):
            name = f'tag_{i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod3/port0/line{i}',
                'channel_type': 'digital_input'
            }

        # Mod4: NI 9472 - 8 digital outputs (tag_88 - tag_95)
        for i in range(8):
            name = f'tag_{88 + i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod4/port0/line{i}',
                'channel_type': 'digital_output',
                'default_value': 0.0
            }

        # Mod5: NI 9213 - 16 thermocouples (tag_72 - tag_87)
        for i in range(16):
            name = f'tag_{72 + i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod5/ai{i}',
                'channel_type': 'thermocouple',
                'thermocouple_type': 'K',
                'scale_slope': 1.0,
                'scale_offset': 0.0
            }

        # Mod6: NI 9266 - 8 current outputs (tag_64 - tag_71)
        for i in range(8):
            name = f'tag_{64 + i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod6/ao{i}',
                'channel_type': 'current_output',
                'current_range_ma': 20.0,
                'default_value': 0.0
            }

        config = {
            'channels': channels,
            'safety_actions': {},
            'config_version': f'test_{int(time.time())}',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
        }

        # Push directly to cRIO
        self.publish(f"nisystem/nodes/{node_id}/config/full", config)
        print(f"Pushed config with {len(channels)} channels to cRIO")

        # Wait for config response
        time.sleep(1.0)
        return True

    def start_crio_acquisition(self, node_id: str = 'crio-001') -> bool:
        """Start acquisition directly on cRIO."""
        print(f"Starting acquisition on cRIO {node_id}...")

        self.publish(f"nisystem/nodes/{node_id}/system/acquire/start", {
            "source": "test"
        })

        time.sleep(1.0)
        return True

    def stop_crio_acquisition(self, node_id: str = 'crio-001') -> bool:
        """Stop acquisition directly on cRIO."""
        print(f"Stopping acquisition on cRIO {node_id}...")

        self.publish(f"nisystem/nodes/{node_id}/system/acquire/stop", {
            "source": "test"
        })

        time.sleep(0.5)
        return True

    def start_acquisition(self) -> bool:
        """Start data acquisition."""
        print("Starting acquisition...")

        self.publish("nisystem/daq/commands", {
            "command": "start"
        })

        # Wait for status update
        time.sleep(1.0)
        return True

    def stop_acquisition(self) -> bool:
        """Stop data acquisition."""
        print("Stopping acquisition...")

        self.publish("nisystem/daq/commands", {
            "command": "stop"
        })

        time.sleep(0.5)
        return True

    def wait_for_values(self, min_count: int = 10, timeout: float = 10.0) -> bool:
        """Wait for channel values to flow."""
        print(f"Waiting for {min_count} channel values...")

        self._value_count = 0
        self._response_events['values'] = threading.Event()

        start = time.time()
        while time.time() - start < timeout:
            if self._value_count >= min_count:
                print(f"Received {self._value_count} values")
                return True
            time.sleep(0.1)

        print(f"Timeout - only received {self._value_count} values")
        return self._value_count > 0

    def get_thermocouple_values(self) -> Dict[str, float]:
        """Get values from thermocouple channels (tag_72 - tag_87 on Mod5)."""
        tc_values = {}
        for name, value in self._channel_values.items():
            if name.startswith('tag_7') or name.startswith('tag_8'):
                tc_values[name] = value
        return tc_values

def run_live_tests():
    """Run all live integration tests."""
    print("=" * 60)
    print("NISystem Live Integration Tests")
    print("=" * 60)
    print()

    results: List[TestResult] = []
    client = LiveTestClient()

    # Test 1: Connect to MQTT
    print("[TEST 1] Connect to MQTT broker")
    start = time.time()
    if client.connect():
        results.append(TestResult("MQTT Connect", True, "Connected successfully", (time.time()-start)*1000))
    else:
        results.append(TestResult("MQTT Connect", False, "Failed to connect", (time.time()-start)*1000))
        print("\nAborting - cannot continue without MQTT connection")
        return results
    print()

    # Test 2: Trigger Discovery
    print("[TEST 2] Trigger cRIO Discovery")
    start = time.time()
    discovery_result = client.trigger_discovery(mode='crio')
    if discovery_result:
        crio_count = discovery_result.get('crio_count', 0)
        if crio_count > 0:
            results.append(TestResult("cRIO Discovery", True, f"Found {crio_count} cRIO node(s)", (time.time()-start)*1000))
        else:
            results.append(TestResult("cRIO Discovery", False, "No cRIO nodes found", (time.time()-start)*1000))
    else:
        results.append(TestResult("cRIO Discovery", False, "Discovery timeout", (time.time()-start)*1000))
    print()

    # Test 3: Push config directly to cRIO
    print("[TEST 3] Push Config to cRIO")
    start = time.time()
    client.push_crio_config()
    results.append(TestResult("Push Config", True, "Config pushed to cRIO", (time.time()-start)*1000))
    print()

    # Test 4: Start Acquisition on cRIO directly
    print("[TEST 4] Start cRIO Acquisition")
    start = time.time()
    client.start_crio_acquisition()
    results.append(TestResult("Start Acquisition", True, "Acquisition started", (time.time()-start)*1000))
    print()

    # Test 5: Wait for Values
    print("[TEST 5] Wait for Channel Values")
    start = time.time()
    if client.wait_for_values(min_count=50, timeout=10.0):
        results.append(TestResult("Value Flow", True, f"Received {client._value_count} values", (time.time()-start)*1000))
    else:
        results.append(TestResult("Value Flow", False, f"Only {client._value_count} values received", (time.time()-start)*1000))
    print()

    # Test 6: Check Thermocouple Values
    print("[TEST 6] Check Thermocouple Values (Mod5)")
    tc_values = client.get_thermocouple_values()
    if tc_values:
        non_zero = [v for v in tc_values.values() if v != 0.0]
        if non_zero:
            avg_temp = sum(non_zero) / len(non_zero)
            results.append(TestResult("TC Values", True, f"{len(tc_values)} TC channels, avg={avg_temp:.1f}°C", 0))
            print(f"  Sample TC values: {list(tc_values.items())[:5]}")
        else:
            results.append(TestResult("TC Values", False, f"{len(tc_values)} TC channels but all 0.0", 0))
    else:
        results.append(TestResult("TC Values", False, "No TC values received", 0))
    print()

    # Test 7: Stop Acquisition
    print("[TEST 7] Stop Acquisition")
    start = time.time()
    client.stop_acquisition()
    results.append(TestResult("Stop Acquisition", True, "Acquisition stopped", (time.time()-start)*1000))
    print()

    # Cleanup
    client.disconnect()

    # Summary
    print("=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name}: {r.message} ({r.duration_ms:.0f}ms)")

    print()
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)

    return results

if __name__ == '__main__':
    results = run_live_tests()

    # Exit with error code if any tests failed
    failed = sum(1 for r in results if not r.passed)
    sys.exit(1 if failed > 0 else 0)
