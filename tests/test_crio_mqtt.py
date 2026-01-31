#!/usr/bin/env python3
"""
Test cRIO MQTT publishing (run from PC) - ALL MODULES.

Tests that the cRIO node correctly publishes values from all
channel types over MQTT when configured and started.

Prerequisites:
- cRIO node running:
  ssh admin@192.168.1.20 "cd /home/admin/nisystem && python3 run_crio_v2.py --broker 192.168.1.1"
- MQTT broker running on PC (or wherever BROKER points)

Usage:
  python tests/test_crio_mqtt.py
"""
import json
import time
import threading
import sys

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)


CRIO_NODE_ID = "crio-001"
BROKER = "localhost"
PORT = 1883


class CRIOTester:
    """Test client for cRIO MQTT communication."""

    def __init__(self):
        # Try both MQTT client API versions
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="crio-mqtt-test"
            )
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id="crio-mqtt-test")

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = threading.Event()
        self.config_ack = threading.Event()
        self.channel_values = {}
        self.batch_count = 0

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Handle MQTT connection."""
        is_success = (rc == 0) if isinstance(rc, int) else not rc.is_failure
        if is_success:
            self.connected.set()
            client.subscribe(f"nisystem/nodes/{CRIO_NODE_ID}/#")
        else:
            print(f"Connection failed: {rc}")

    def _on_message(self, client, userdata, msg):
        """Handle incoming messages."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except:
            return

        topic = msg.topic

        if '/config/response' in topic:
            self.config_ack.set()

        if '/channels/batch' in topic:
            self.batch_count += 1
            # Store ALL channel values
            for name, data in payload.items():
                self.channel_values[name] = data.get('value', 0)

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            self.client.connect(BROKER, PORT)
            self.client.loop_start()
            return self.connected.wait(timeout=5.0)
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def send_config(self, channels: dict):
        """Push channel config to cRIO."""
        config = {'channels': channels}

        self.config_ack.clear()
        self.client.publish(
            f"nisystem/nodes/{CRIO_NODE_ID}/config/full",
            json.dumps(config),
            qos=1
        )

        if self.config_ack.wait(timeout=5.0):
            return True
        else:
            print("  (No config ACK received, continuing anyway)")
            time.sleep(1.0)
            return True

    def start_acquisition(self):
        """Start acquisition on cRIO."""
        self.client.publish(
            f"nisystem/nodes/{CRIO_NODE_ID}/system/acquire/start",
            json.dumps({}),
            qos=1
        )
        time.sleep(1.0)

    def stop_acquisition(self):
        """Stop acquisition on cRIO."""
        self.client.publish(
            f"nisystem/nodes/{CRIO_NODE_ID}/system/acquire/stop",
            json.dumps({})
        )
        time.sleep(0.5)

    def wait_for_values(self, seconds: float = 5.0):
        """Wait for channel values to arrive."""
        self.channel_values.clear()
        self.batch_count = 0
        time.sleep(seconds)

    def disconnect(self):
        """Disconnect from MQTT."""
        self.client.loop_stop()
        self.client.disconnect()


def build_all_channels_config():
    """
    Build channel config for typical cRIO setup.
    Adjust module names/slots as needed for your hardware.
    """
    channels = {}
    ch_idx = 0

    # Mod1: NI 9202 - 16 voltage inputs
    for i in range(16):
        channels[f'vi_{i}'] = {
            'name': f'vi_{i}',
            'physical_channel': f'Mod1/ai{i}',
            'channel_type': 'voltage_input',
            'voltage_range': 10.0
        }
        ch_idx += 1

    # Mod2: NI 9264 - 16 voltage outputs
    for i in range(16):
        channels[f'vo_{i}'] = {
            'name': f'vo_{i}',
            'physical_channel': f'Mod2/ao{i}',
            'channel_type': 'voltage_output',
            'default_value': 0.0
        }
        ch_idx += 1

    # Mod3: NI 9425 - 32 digital inputs
    for i in range(32):
        channels[f'di_{i}'] = {
            'name': f'di_{i}',
            'physical_channel': f'Mod3/port0/line{i}',
            'channel_type': 'digital_input'
        }
        ch_idx += 1

    # Mod4: NI 9472 - 8 digital outputs
    for i in range(8):
        channels[f'do_{i}'] = {
            'name': f'do_{i}',
            'physical_channel': f'Mod4/port0/line{i}',
            'channel_type': 'digital_output',
            'default_value': 0.0
        }
        ch_idx += 1

    # Mod5: NI 9213 - 16 thermocouples
    for i in range(16):
        channels[f'tc_{i}'] = {
            'name': f'tc_{i}',
            'physical_channel': f'Mod5/ai{i}',
            'channel_type': 'thermocouple',
            'thermocouple_type': 'K'
        }
        ch_idx += 1

    # Mod6: NI 9266 - 8 current outputs
    for i in range(8):
        channels[f'co_{i}'] = {
            'name': f'co_{i}',
            'physical_channel': f'Mod6/ao{i}',
            'channel_type': 'current_output',
            'current_range_ma': 20.0,
            'default_value': 0.0
        }
        ch_idx += 1

    return channels


def run_test():
    """Run the cRIO MQTT publishing test for ALL modules."""
    print("=" * 55)
    print("cRIO MQTT Publishing Test - ALL MODULES")
    print("=" * 55)
    print()
    print(f"Broker: {BROKER}:{PORT}")
    print(f"Node ID: {CRIO_NODE_ID}")
    print()

    tester = CRIOTester()

    # Step 1: Connect
    print("[1] Connecting to MQTT broker...", end=" ")
    if not tester.connect():
        print("FAIL")
        print("\nMake sure MQTT broker is running.")
        return False
    print("OK")

    # Step 2: Build and send config for all modules
    print("[2] Building config for all modules...")
    channels = build_all_channels_config()
    print(f"    Configured {len(channels)} channels")

    print("[3] Pushing config to cRIO...", end=" ")
    tester.send_config(channels)
    print("OK")

    # Step 4: Start acquisition
    print("[4] Starting acquisition...", end=" ")
    tester.start_acquisition()
    print("OK")

    # Step 5: Wait for values
    print("[5] Waiting for values (5 seconds)...")
    tester.wait_for_values(5.0)
    print(f"    Received {tester.batch_count} batches")

    # Step 6: Analyze results by channel type
    print()
    print("=" * 55)
    print("RESULTS BY CHANNEL TYPE")
    print("=" * 55)

    # Group by prefix
    by_type = {
        'vi_': ('Voltage Input', []),
        'vo_': ('Voltage Output', []),
        'di_': ('Digital Input', []),
        'do_': ('Digital Output', []),
        'tc_': ('Thermocouple', []),
        'co_': ('Current Output', [])
    }

    for name, value in tester.channel_values.items():
        for prefix, (type_name, values) in by_type.items():
            if name.startswith(prefix):
                values.append((name, value))
                break

    total_received = 0
    total_non_zero = 0

    for prefix, (type_name, values) in by_type.items():
        if values:
            print(f"\n{type_name} ({len(values)} channels):")
            print("-" * 40)

            # Show first 5
            for name, val in sorted(values)[:5]:
                if val is None:
                    print(f"  {name}: None")
                else:
                    print(f"  {name}: {val:10.4f}")

            if len(values) > 5:
                print(f"  ... and {len(values) - 5} more")

            non_zero = sum(1 for _, v in values if v is not None and v != 0.0)
            print(f"  Non-zero: {non_zero}/{len(values)}")

            total_received += len(values)
            total_non_zero += non_zero
        else:
            print(f"\n{type_name}: No values received")

    # Cleanup
    tester.stop_acquisition()
    tester.disconnect()

    # Summary
    print()
    print("=" * 55)
    print("SUMMARY")
    print("=" * 55)
    print(f"Batches received: {tester.batch_count}")
    print(f"Channels received: {total_received}")
    print(f"Non-zero values: {total_non_zero}/{total_received}")

    if total_received == 0:
        print()
        print("FAIL: No channel values received")
        print("\nTroubleshooting:")
        print("  1. Is cRIO node running?")
        print("     ssh admin@192.168.1.20 'cd /home/admin/nisystem && python3 run_crio_v2.py --broker 192.168.1.1'")
        print("  2. Is MQTT broker reachable from cRIO?")
        print("  3. Check cRIO node logs for errors")
        return False

    if total_non_zero > 0:
        print()
        print("PASS: cRIO publishing values to MQTT")
        return True
    else:
        print()
        print("FAIL: All values are 0.0")
        print("\nThis may indicate:")
        print("  - Hardware not reading correctly")
        print("  - Config not being applied")
        print("  - Channel types not recognized")
        return False


if __name__ == '__main__':
    success = run_test()
    print()
    print("=" * 55)
    sys.exit(0 if success else 1)
