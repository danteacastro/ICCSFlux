"""
End-to-end integration test for DAQ Service + cRIO workflow.

Mimics dashboard workflow:
1. Login as admin
2. Trigger cRIO discovery
3. Create channels from discovery
4. Start acquisition
5. Verify 4Hz publishing
6. Check thermocouple readings

Requirements:
- DAQ service running (device.bat)
- cRIO online (deploy_crio_v2.bat)
- MQTT broker running

Run with: python tests/test_daq_integration.py
"""

import json
import time
import threading
import sys
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    if __name__ == "__main__":
        print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
        sys.exit(1)

TOPIC_BASE = "nisystem/nodes/node-001"

# Test credentials - NOT for production use
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"  # Default password from UserSessionManager fixture

@dataclass
class DAQIntegrationTest:
    """MQTT client for DAQ service integration testing."""
    broker_host: str = "localhost"
    ws_port: int = 9002

    _client: Optional[mqtt.Client] = field(default=None, repr=False)
    _connected: threading.Event = field(default_factory=threading.Event, repr=False)
    _responses: Dict[str, Any] = field(default_factory=dict, repr=False)
    _response_events: Dict[str, threading.Event] = field(default_factory=dict, repr=False)
    _batch_values: Dict[str, Any] = field(default_factory=dict, repr=False)
    _batch_count: int = 0

    def connect(self) -> bool:
        """Connect via WebSocket (port 9002)."""
        try:
            # Try paho-mqtt 2.x API first
            try:
                self._client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"daq-test-{int(time.time())}",
                    transport="websockets"
                )
            except (AttributeError, TypeError):
                # Fall back to 1.x API
                self._client = mqtt.Client(
                    client_id=f"daq-test-{int(time.time())}",
                    transport="websockets"
                )

            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message

            print(f"  Connecting to MQTT WebSocket at {self.broker_host}:{self.ws_port}...")
            self._client.connect(self.broker_host, self.ws_port, keepalive=60)
            self._client.loop_start()

            if not self._connected.wait(timeout=5.0):
                print("  ERROR: Connection timeout")
                return False

            return True

        except Exception as e:
            print(f"  ERROR: {e}")
            return False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle MQTT connection."""
        # Handle both paho-mqtt 1.x (int) and 2.x (ReasonCode) APIs
        is_success = (reason_code == 0) if isinstance(reason_code, int) else not reason_code.is_failure
        if is_success:
            self._connected.set()
            # Subscribe to DAQ service topics AND cRIO topics
            client.subscribe(f"{TOPIC_BASE}/#")
            client.subscribe("nisystem/nodes/crio-001/#")  # Also listen to cRIO directly
        else:
            print(f"  Connection failed: {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Route messages to appropriate handlers."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except:
            return

        topic = msg.topic

        if '/auth/status' in topic:
            self._responses['auth'] = payload
            self._signal('auth')
        elif '/discovery/result' in topic:
            self._responses['discovery'] = payload
            self._signal('discovery')
        elif '/bulk-create/response' in topic:
            self._responses['bulk_create'] = payload
            self._signal('bulk_create')
        elif '/channels/batch' in topic:
            # MERGE batch values (don't overwrite with empty DAQ service batches)
            ch_count = len(payload) if isinstance(payload, dict) else 0
            if isinstance(payload, dict) and ch_count > 0:
                self._batch_values.update(payload)
            self._batch_count += 1
            # Print batches with data, or first few empty ones
            if ch_count > 0 or self._batch_count <= 3:
                source = "cRIO" if "crio" in topic else "DAQ"
                print(f"    [DEBUG] Batch #{self._batch_count} from {source}: {ch_count} channels")
                if ch_count > 0 and ch_count <= 10:
                    # Show sample values
                    sample = list(payload.items())[:3]
                    for name, data in sample:
                        val = data.get('value') if isinstance(data, dict) else data
                        print(f"             {name}: {val}")
        elif '/command/ack' in topic:
            print(f"    [DEBUG] Command ACK: {payload}")
        elif '/status/system' in topic or '/session/status' in topic:
            acq = payload.get('acquiring', payload.get('acquisition_active', '?'))
            # Don't spam too many status messages
            pass  # print(f"    [DEBUG] Status: acquiring={acq}")
        elif '/config/response' in topic:
            print(f"    [DEBUG] cRIO Config Response: {payload}")

    def _signal(self, key: str):
        """Signal that a response was received."""
        if key in self._response_events:
            self._response_events[key].set()

    def prepare_wait(self, key: str):
        """Prepare to wait for a response (call BEFORE publishing)."""
        self._responses.pop(key, None)  # Clear any old response
        event = threading.Event()
        self._response_events[key] = event
        return event

    def wait_for(self, key: str, timeout: float = 15.0) -> Optional[Any]:
        """Wait for a specific response (must call prepare_wait first)."""
        event = self._response_events.get(key)
        if event and event.wait(timeout):
            return self._responses.get(key)
        return None

    def publish(self, topic: str, payload: dict):
        """Publish a message."""
        self._client.publish(topic, json.dumps(payload), qos=1)

    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            print("  Disconnected from MQTT")

    # === TEST METHODS ===

    def login(self, username: str = TEST_USERNAME, password: str = TEST_PASSWORD, retries: int = 3) -> bool:
        """Step 1: Login as admin with retry."""
        for attempt in range(retries):
            self.prepare_wait('auth')  # Prepare BEFORE publishing
            self.publish(f"{TOPIC_BASE}/auth/login", {
                "username": username,
                "password": password,
                "source_ip": "integration-test"
            })
            resp = self.wait_for('auth', timeout=5.0)
            if resp and resp.get('authenticated', False):
                return True
            print(f"    Login attempt {attempt + 1} failed, retrying...")
            time.sleep(1.0)
        return False

    def discover_crio(self) -> Optional[Dict]:
        """Step 2: Trigger cRIO discovery."""
        self.prepare_wait('discovery')  # Prepare BEFORE publishing
        self.publish(f"{TOPIC_BASE}/discovery/scan", {"mode": "crio"})
        return self.wait_for('discovery', timeout=15.0)

    def bulk_create_channels(self, discovery: Dict) -> bool:
        """Step 3: Create channels from discovery result."""
        channels = []
        tag_index = 0
        for node in discovery.get('crio_nodes', []):
            node_id = node.get('node_id', '')
            for mod in node.get('modules', []):
                mod_category = mod.get('category', '').lower()
                for ch in mod.get('channels', []):
                    # Discovery 'name' is actually the physical channel path (e.g., "Mod1/ai0")
                    physical_ch = ch.get('name', '')
                    ch_type = ch.get('channel_type', 'ai')

                    # Determine channel type from module category
                    if 'thermocouple' in mod_category:
                        channel_type = 'thermocouple'
                    elif 'current_output' in mod_category:
                        channel_type = 'current_output'
                    elif 'current_input' in mod_category:
                        channel_type = 'current_input'
                    elif 'digital_input' in mod_category:
                        channel_type = 'digital_input'
                    elif 'digital_output' in mod_category:
                        channel_type = 'digital_output'
                    elif 'voltage_output' in mod_category:
                        channel_type = 'voltage_output'
                    else:
                        # Map channel type from ai/ao/di/do
                        type_map = {'ai': 'voltage_input', 'ao': 'voltage_output',
                                    'di': 'digital_input', 'do': 'digital_output'}
                        channel_type = type_map.get(ch_type, 'voltage_input')

                    # Generate unique TAG name
                    tag_name = f"tag_{tag_index}"
                    tag_index += 1

                    ch_data = {
                        'name': tag_name,
                        'physical_channel': physical_ch,
                        'channel_type': channel_type,
                        'category': mod_category,
                        'source_type': 'crio',
                        'node_id': node_id,
                    }
                    # Only add thermocouple_type for thermocouple channels
                    if channel_type == 'thermocouple':
                        ch_data['thermocouple_type'] = 'K'
                    channels.append(ch_data)

        if not channels:
            print(f"    No channels found in discovery result")
            return False

        print(f"    Creating {len(channels)} channels...")
        self.prepare_wait('bulk_create')  # Prepare BEFORE publishing
        self.publish(f"{TOPIC_BASE}/config/channel/bulk-create", {"channels": channels})
        resp = self.wait_for('bulk_create', timeout=10.0)

        if resp:
            created = len(resp.get('created', []))
            failed = len(resp.get('failed', []))
            print(f"    Created: {created}, Failed: {failed}")
            # Print first failure reason if any
            failed_list = resp.get('failed', [])
            if failed_list and len(failed_list) > 0:
                first_fail = failed_list[0]
                print(f"    First failure: {first_fail}")  # Print full object to see structure
            # Consider success if either created > 0 OR if failed due to "already exists"
            if created > 0:
                return True
            # Check for "already exists" in 'reason' or 'error' field
            if failed > 0:
                first_error = str(failed_list[0].get('reason', '')) + str(failed_list[0].get('error', ''))
                if 'already exists' in first_error.lower():
                    print(f"    (Channels already exist - this is OK)")
                    return True
            return resp.get('success', False)
        return False

    def start_acquisition(self) -> bool:
        """Step 4: Start data acquisition."""
        print("    Publishing to: " + f"{TOPIC_BASE}/system/acquire/start")
        self.publish(f"{TOPIC_BASE}/system/acquire/start", {})
        time.sleep(2.0)  # Wait for acquisition to start
        print(f"    Batch count after start: {self._batch_count}")
        return True

    def stop_acquisition(self):
        """Cleanup: Stop acquisition on both DAQ service and cRIO."""
        # Stop cRIO first (cRIO is source of truth for acquiring state)
        self.publish("nisystem/nodes/crio-001/system/acquire/stop", {})
        time.sleep(0.5)
        # Then stop DAQ service
        self.publish(f"{TOPIC_BASE}/system/acquire/stop", {})
        time.sleep(0.5)
        # Send cRIO stop again to be sure
        self.publish("nisystem/nodes/crio-001/system/acquire/stop", {})
        time.sleep(1.0)

    def verify_4hz(self, duration: float = 5.0) -> tuple:
        """Step 5: Verify 4Hz data publishing."""
        self._batch_count = 0
        self._batch_values = {}  # Clear batch values to get fresh data
        time.sleep(duration)
        rate = self._batch_count / duration if duration > 0 else 0
        return (self._batch_count, rate)

    def get_tc_values(self) -> Dict[str, float]:
        """Step 6: Get thermocouple values from Mod5."""
        tc = {}
        for name, data in self._batch_values.items():
            # Mod5 thermocouples are typically tag_72 - tag_87
            if isinstance(data, dict) and ('tag_7' in name or 'tag_8' in name):
                tc[name] = data.get('value')
        return tc

def run_test():
    """Run the full integration test."""
    print("=" * 60)
    print("DAQ Service Integration Test")
    print("=" * 60)

    test = DAQIntegrationTest()
    results = []

    # 1. Connect
    print("\n[1/6] Connecting to MQTT...")
    if not test.connect():
        print("  FAIL: Cannot connect to MQTT broker")
        print("\n  Make sure:")
        print("    - DAQ service is running (device.bat)")
        print("    - MQTT broker is running on port 9002")
        return 1
    print("  PASS: Connected")
    results.append(("Connect", True))

    # Wait for subscription to be active
    time.sleep(1.0)

    # 2. Login
    print("\n[2/6] Login as admin...")
    if test.login():
        print("  PASS: Authenticated")
        print("  Waiting 5 seconds for system to be ready...")
        time.sleep(5.0)
        results.append(("Login", True))
    else:
        print("  FAIL: Authentication failed")
        print("    Check credentials (default: admin/admin)")
        results.append(("Login", False))
        test.disconnect()
        return 1

    # 2b. Stop any existing acquisition (clean state)
    print("  Ensuring acquisition is stopped (clean state)...")
    test.stop_acquisition()
    time.sleep(5.0)  # Wait even longer for cRIO to stop
    # Reset batch count for clean measurement later
    test._batch_count = 0
    print(f"  Batch count after stop: {test._batch_count}")

    # 3. Discovery
    print("\n[3/6] cRIO Discovery...")
    discovery = test.discover_crio()
    if discovery and discovery.get('crio_nodes'):
        crio_count = len(discovery['crio_nodes'])
        total_channels = sum(
            len(ch)
            for node in discovery['crio_nodes']
            for mod in node.get('modules', [])
            for ch in [mod.get('channels', [])]
        )
        print(f"  PASS: Found {crio_count} cRIO node(s) with {total_channels} channels")
        results.append(("Discovery", True))
    else:
        print("  FAIL: No cRIO nodes found")
        print("    Make sure cRIO is online (deploy_crio_v2.bat)")
        results.append(("Discovery", False))
        test.disconnect()
        return 1

    # 4. Create channels
    print("\n[4/6] Creating channels from discovery...")
    if test.bulk_create_channels(discovery):
        print("  PASS: Channels created")
        results.append(("Bulk Create", True))
    else:
        print("  FAIL: Channel creation failed or no channels created")
        results.append(("Bulk Create", False))

    # 5. Start acquisition and verify 4Hz
    print("\n[5/6] Start acquisition + verify 4Hz publishing...")
    test.start_acquisition()
    print("  Acquisition started, waiting 5 seconds...")
    count, rate = test.verify_4hz(5.0)
    if rate >= 3.5:
        print(f"  PASS: {count} batches in 5s ({rate:.1f} Hz)")
        results.append(("4Hz Publishing", True))
    else:
        print(f"  FAIL: Only {count} batches ({rate:.1f} Hz, expected ~4Hz)")
        results.append(("4Hz Publishing", False))

    # 6. Check thermocouples
    print("\n[6/6] Check thermocouple values (Mod5)...")
    tc = test.get_tc_values()
    print(f"    Total batch values collected: {len(test._batch_values)}")
    print(f"    Sample batch keys: {list(test._batch_values.keys())[:10]}")
    if tc:
        print(f"    TC channel names: {list(tc.keys())}")
        print(f"    TC values: {list(tc.values())[:5]}")
        non_zero = [v for v in tc.values() if v is not None and v != 0.0]
        if non_zero:
            avg_temp = sum(non_zero) / len(non_zero)
            print(f"  PASS: {len(tc)} TC channels, avg={avg_temp:.1f}C")
            print(f"    Sample values: {dict(list(tc.items())[:3])}")
            results.append(("TC Values", True))
        else:
            print(f"  FAIL: {len(tc)} TC channels but all values are 0.0 or None")
            print("    This indicates the cRIO hardware task isn't reading correctly")
            results.append(("TC Values", False))
    else:
        print("  FAIL: No thermocouple values received")
        print("    Make sure Mod5 (NI 9213) is present in cRIO")
        results.append(("TC Values", False))

    # Cleanup
    print("\nStopping acquisition...")
    test.stop_acquisition()
    test.disconnect()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, p in results if p)
    failed = sum(1 for _, p in results if not p)

    for name, passed_flag in results:
        status = "PASS" if passed_flag else "FAIL"
        print(f"  [{status}] {name}")

    print()
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == '__main__':
    exit_code = run_test()
    sys.exit(exit_code)
