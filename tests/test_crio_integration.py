#!/usr/bin/env python3
"""
Test cRIO Integration Without Hardware

This script simulates a cRIO node publishing data to validate:
1. MQTT message format is correct
2. DAQ service receives and processes cRIO values
3. Channel mapping works (cRIO channel -> NISystem tag)
4. Discovery/status messages are handled

Run this while NISystem is running to test the full integration.
"""

import json
import time
import random
import argparse
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.client import CallbackAPIVersion
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    exit(1)

class MockCRIONode:
    """Simulates a cRIO node for testing"""

    def __init__(self, broker: str = "localhost", port: int = 1883, node_id: str = "crio-test"):
        self.broker = broker
        self.port = port
        self.node_id = node_id
        self.mqtt_base = "nisystem"

        # Simulated hardware
        self.product_type = "cRIO-9056"
        self.serial_number = "01ABC234"
        self.device_name = f"{self.product_type}-{self.serial_number}"

        # Simulated modules and channels
        self.modules = [
            {"name": "Mod1", "product_type": "NI 9213", "slot": 1, "channels": self._make_tc_channels("Mod1", 16)},
            {"name": "Mod2", "product_type": "NI 9213", "slot": 2, "channels": self._make_tc_channels("Mod2", 16)},
            {"name": "Mod3", "product_type": "NI 9205", "slot": 3, "channels": self._make_voltage_channels("Mod3", 32)},
            {"name": "Mod4", "product_type": "NI 9264", "slot": 4, "channels": self._make_ao_channels("Mod4", 16)},
            {"name": "Mod5", "product_type": "NI 9375", "slot": 5, "channels": self._make_di_channels("Mod5", 16)},
            {"name": "Mod6", "product_type": "NI 9375", "slot": 6, "channels": self._make_do_channels("Mod6", 16)},
        ]

        # Channel values (simulated)
        self.channel_values = {}
        for mod in self.modules:
            for ch in mod["channels"]:
                self.channel_values[ch["name"]] = 0.0

        # MQTT client
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"mock-crio-{node_id}"
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.connected = False

    def _make_tc_channels(self, mod: str, count: int):
        """Create thermocouple channel list"""
        return [
            {
                "name": f"{mod}/ai{i}",
                "display_name": f"{self.device_name}/{mod}/ai{i}",
                "channel_type": "analog_input",
                "category": "thermocouple"
            }
            for i in range(count)
        ]

    def _make_voltage_channels(self, mod: str, count: int):
        """Create voltage channel list"""
        return [
            {
                "name": f"{mod}/ai{i}",
                "display_name": f"{self.device_name}/{mod}/ai{i}",
                "channel_type": "analog_input",
                "category": "voltage"
            }
            for i in range(count)
        ]

    def _make_ao_channels(self, mod: str, count: int):
        """Create analog output channel list"""
        return [
            {
                "name": f"{mod}/ao{i}",
                "display_name": f"{self.device_name}/{mod}/ao{i}",
                "channel_type": "voltage_output",
                "category": "voltage"
            }
            for i in range(count)
        ]

    def _make_di_channels(self, mod: str, count: int):
        """Create digital input channel list"""
        return [
            {
                "name": f"{mod}/port0/line{i}",
                "display_name": f"{self.device_name}/{mod}/port0/line{i}",
                "channel_type": "digital_input",
                "category": "digital"
            }
            for i in range(count)
        ]

    def _make_do_channels(self, mod: str, count: int):
        """Create digital output channel list"""
        return [
            {
                "name": f"{mod}/port1/line{i}",
                "display_name": f"{self.device_name}/{mod}/port1/line{i}",
                "channel_type": "digital_output",
                "category": "digital"
            }
            for i in range(count)
        ]

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self.connected = True
            print(f"[MOCK CRIO] Connected to MQTT broker")

            # Subscribe to discovery ping
            client.subscribe(f"{self.mqtt_base}/discovery/ping")

            # Publish initial status
            self._publish_status()
        else:
            print(f"[MOCK CRIO] Connection failed: {reason_code}")

    def _on_message(self, client, userdata, msg):
        if "discovery/ping" in msg.topic:
            print(f"[MOCK CRIO] Received discovery ping - publishing status")
            self._publish_status()

    def _get_topic(self, category: str, entity: str = ""):
        """Build MQTT topic"""
        base = f"{self.mqtt_base}/nodes/{self.node_id}"
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    def _publish_status(self):
        """Publish status message (same format as real cRIO node)"""
        status = {
            "status": "online",
            "acquiring": True,
            "node_type": "crio",
            "node_id": self.node_id,
            "pc_connected": True,
            "channels": sum(len(m["channels"]) for m in self.modules),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ip_address": "192.168.1.50",  # Simulated
            "product_type": self.product_type,
            "serial_number": self.serial_number,
            "device_name": self.device_name,
            "modules": self.modules
        }

        topic = self._get_topic("status", "system")
        self.client.publish(topic, json.dumps(status), retain=True)
        print(f"[MOCK CRIO] Published status: {self.device_name} with {status['channels']} channels")

    def _publish_heartbeat(self):
        """Publish heartbeat"""
        heartbeat = {
            "seq": int(time.time()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acquiring": True,
            "pc_connected": True,
            "node_type": "crio",
            "node_id": self.node_id,
            "channels": sum(len(m["channels"]) for m in self.modules)
        }
        self.client.publish(self._get_topic("heartbeat"), json.dumps(heartbeat))

    def _publish_channel_values(self):
        """Publish simulated channel values"""
        now = time.time()

        for channel_name, _ in self.channel_values.items():
            # Generate simulated values based on channel type
            if "Mod1" in channel_name or "Mod2" in channel_name:
                # Thermocouples: 20-30°C with some variation
                value = 25.0 + random.uniform(-5, 5) + random.uniform(-0.5, 0.5)
            elif "Mod3" in channel_name:
                # Voltage: 0-10V
                value = 5.0 + random.uniform(-2, 2)
            elif "Mod4" in channel_name:
                # Analog output: 0-10V
                value = random.uniform(0, 10)
            elif "port0" in channel_name:
                # Digital input: 0 or 1
                value = 1.0 if random.random() > 0.5 else 0.0
            else:
                # Digital output: 0 or 1
                value = 1.0 if random.random() > 0.7 else 0.0

            self.channel_values[channel_name] = value

            # Publish
            topic = self._get_topic("channels", channel_name)
            payload = {"value": value, "timestamp": now}
            self.client.publish(topic, json.dumps(payload))

    def connect(self):
        """Connect to MQTT broker"""
        print(f"[MOCK CRIO] Connecting to {self.broker}:{self.port}...")
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            # Wait for connection
            for _ in range(50):
                if self.connected:
                    return True
                time.sleep(0.1)

            print("[MOCK CRIO] Connection timeout")
            return False
        except Exception as e:
            print(f"[MOCK CRIO] Connection error: {e}")
            return False

    def run(self, duration: int = 30, publish_rate: float = 0.5):
        """Run the mock cRIO node"""
        if not self.connect():
            return False

        print(f"\n[MOCK CRIO] Running for {duration} seconds...")
        print(f"[MOCK CRIO] Publishing {len(self.channel_values)} channel values every {publish_rate}s")
        print(f"[MOCK CRIO] Node ID: {self.node_id}")
        print(f"[MOCK CRIO] Device: {self.device_name}")
        print()

        start_time = time.time()
        heartbeat_time = start_time

        try:
            while time.time() - start_time < duration:
                # Publish channel values
                self._publish_channel_values()

                # Heartbeat every 2 seconds
                if time.time() - heartbeat_time >= 2.0:
                    self._publish_heartbeat()
                    heartbeat_time = time.time()

                # Show progress
                elapsed = int(time.time() - start_time)
                print(f"\r[MOCK CRIO] Running... {elapsed}s / {duration}s", end="", flush=True)

                time.sleep(publish_rate)
        except KeyboardInterrupt:
            print("\n[MOCK CRIO] Interrupted by user")

        print("\n[MOCK CRIO] Stopping...")

        # Publish offline status
        self.client.publish(
            self._get_topic("status", "system"),
            json.dumps({"status": "offline", "node_type": "crio"}),
            retain=True
        )

        self.client.loop_stop()
        self.client.disconnect()
        print("[MOCK CRIO] Stopped")
        return True

def main():
    parser = argparse.ArgumentParser(description="Test cRIO Integration (Mock)")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--node-id", default="crio-test", help="Node ID for mock cRIO")
    parser.add_argument("--duration", type=int, default=60, help="Run duration in seconds")
    parser.add_argument("--rate", type=float, default=0.5, help="Publish rate in seconds")

    args = parser.parse_args()

    print("=" * 60)
    print("  Mock cRIO Node - Integration Test")
    print("=" * 60)
    print()
    print("This simulates a cRIO-9056 with 6 modules and 96 channels.")
    print()
    print("To test:")
    print("  1. Make sure NISystem backend is running")
    print("  2. Open the dashboard")
    print("  3. Go to Configuration > Scan Devices")
    print("  4. You should see 'crio-test' appear with 96 channels")
    print("  5. Add some channels and start acquisition")
    print("  6. Values should update in real-time")
    print()

    mock = MockCRIONode(
        broker=args.broker,
        port=args.port,
        node_id=args.node_id
    )

    mock.run(duration=args.duration, publish_rate=args.rate)

if __name__ == "__main__":
    main()
