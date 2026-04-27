#!/usr/bin/env python3
"""
Test All Channel Values

Validates that ALL channels from ALL modules publish valid values.
This test runs against real hardware (cRIO or cDAQ).

Usage:
    python tests/test_all_channel_values.py [--broker HOST] [--node NODE_ID]
"""

import json
import time
import argparse
import threading
import sys
import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    # This module is meant to be run directly (`python tests/test_all_channel_values.py`)
    # but lives in tests/ so it gets collected by pytest. Don't sys.exit() at
    # module load — that aborts pytest collection of unrelated tests in the
    # same directory. The hard exit only fires when run as a script.
    if __name__ == "__main__":
        print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
        sys.exit(1)

@dataclass
class ChannelValue:
    """Captured channel value."""
    name: str
    value: float
    timestamp: float
    quality: str
    channel_type: Optional[str] = None

class ChannelCollector:
    """Collects and validates channel values from MQTT."""

    def __init__(self, broker: str, port: int = 1883):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id=f"channel-validator-{int(time.time())}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.connected = False
        self._lock = threading.Lock()

        # Discovery
        self.discovered_nodes: Dict[str, Dict] = {}
        self.discovered_channels: Dict[str, Dict] = {}  # name -> channel info

        # Values
        self.channel_values: Dict[str, ChannelValue] = {}
        self.batch_count = 0
        self.last_batch_time = 0.0

    def connect(self) -> bool:
        try:
            self.client.connect(self.broker, self.port)
            self.client.loop_start()
            for _ in range(50):
                if self.connected:
                    return True
                time.sleep(0.1)
            return False
        except Exception as e:
            print(f"Connect error: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            # Subscribe to all nisystem topics
            client.subscribe("nisystem/#")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except:
            return

        topic = msg.topic

        # Node status (for discovery)
        if "/status/system" in topic:
            node_id = payload.get('node_id', 'unknown')
            with self._lock:
                self.discovered_nodes[node_id] = payload

        # Config response (channel list)
        if "/config/response" in topic or "/discovery/channels" in topic:
            channels = payload.get('channels', {})
            if isinstance(channels, dict):
                with self._lock:
                    self.discovered_channels.update(channels)

        # Batch values
        if "/channels/batch" in topic:
            with self._lock:
                self.batch_count += 1
                self.last_batch_time = time.time()

                for name, data in payload.items():
                    if isinstance(data, dict) and 'value' in data:
                        self.channel_values[name] = ChannelValue(
                            name=name,
                            value=data.get('value', 0.0),
                            timestamp=data.get('timestamp', 0.0),
                            quality=data.get('quality', 'unknown'),
                            channel_type=data.get('type')
                        )

        # Individual channel values
        if "/channels/" in topic and "/batch" not in topic:
            # Extract channel name from topic
            parts = topic.split("/channels/")
            if len(parts) > 1:
                ch_name = parts[1]
                if isinstance(payload, dict) and 'value' in payload:
                    with self._lock:
                        self.channel_values[ch_name] = ChannelValue(
                            name=ch_name,
                            value=payload.get('value', 0.0),
                            timestamp=payload.get('timestamp', 0.0),
                            quality=payload.get('quality', 'good'),
                            channel_type=payload.get('type')
                        )

    def send_discovery_ping(self):
        """Send discovery ping to find nodes."""
        self.client.publish("nisystem/discovery/ping", json.dumps({
            'source': 'test',
            'timestamp': datetime.now().isoformat()
        }))

    def send_acquire_start(self, node_id: str):
        """Start acquisition on a node."""
        self.client.publish(
            f"nisystem/nodes/{node_id}/system/acquire/start",
            json.dumps({'command': 'start', 'request_id': f'test-{int(time.time())}'})
        )

    def send_acquire_stop(self, node_id: str):
        """Stop acquisition on a node."""
        self.client.publish(
            f"nisystem/nodes/{node_id}/system/acquire/stop",
            json.dumps({'command': 'stop', 'request_id': f'test-{int(time.time())}'})
        )

    def get_channel_count(self) -> int:
        with self._lock:
            return len(self.channel_values)

    def get_batch_count(self) -> int:
        with self._lock:
            return self.batch_count

    def get_all_values(self) -> Dict[str, ChannelValue]:
        with self._lock:
            return dict(self.channel_values)

    def clear_values(self):
        with self._lock:
            self.channel_values.clear()
            self.batch_count = 0

def validate_channel_value(ch: ChannelValue, expected_type: str = None) -> List[str]:
    """Validate a channel value. Returns list of errors (empty if valid)."""
    errors = []

    # Check value is numeric
    if not isinstance(ch.value, (int, float)):
        errors.append(f"value not numeric: {type(ch.value)}")

    # Check timestamp
    if not isinstance(ch.timestamp, (int, float)):
        errors.append(f"timestamp not numeric: {type(ch.timestamp)}")
    elif ch.timestamp <= 0:
        errors.append(f"timestamp invalid: {ch.timestamp}")

    # Check quality
    valid_qualities = ('good', 'bad', 'uncertain', 'unknown')
    if ch.quality not in valid_qualities:
        errors.append(f"invalid quality: {ch.quality}")

    # Type-specific validation
    ch_type = expected_type or ch.channel_type or ''

    if 'thermocouple' in ch_type.lower() or ch_type == 'TC':
        # TC should be in reasonable range (-40 to 1300 C)
        # Open circuit reads ~2300C
        if not (-50 <= ch.value <= 2500):
            errors.append(f"TC value out of range: {ch.value}")

    elif 'digital' in ch_type.lower() or ch_type in ('DI', 'DO'):
        # Digital should be 0 or 1
        if ch.value not in (0.0, 1.0, 0, 1):
            errors.append(f"digital value not 0/1: {ch.value}")

    elif 'voltage' in ch_type.lower() or ch_type in ('VI', 'VO'):
        # Voltage typically -10 to +10V
        if not (-15 <= ch.value <= 15):
            errors.append(f"voltage out of typical range: {ch.value}")

    elif 'current' in ch_type.lower():
        # Current typically 0-20mA or 4-20mA
        if not (-5 <= ch.value <= 25):
            errors.append(f"current out of typical range: {ch.value}")

    return errors

def run_validation(broker: str, node_id: str = None, duration: float = 5.0) -> bool:
    """
    Run channel value validation.

    Args:
        broker: MQTT broker address
        node_id: Specific node to test, or None for all
        duration: How long to collect values

    Returns:
        True if all validations pass
    """
    print("\n" + "=" * 70)
    print("Channel Value Validation Test")
    print("=" * 70)
    print(f"Broker: {broker}")
    print(f"Node: {node_id or 'all'}")
    print(f"Duration: {duration}s")

    collector = ChannelCollector(broker)

    if not collector.connect():
        print("\nERROR: Could not connect to MQTT broker")
        return False

    print("\nConnected to MQTT broker")

    # Discover nodes
    print("\nDiscovering nodes...")
    collector.send_discovery_ping()
    time.sleep(2.0)

    nodes = list(collector.discovered_nodes.keys())
    if not nodes:
        print("WARNING: No nodes responded to discovery ping")
        print("Assuming values are already flowing...")
    else:
        print(f"Found nodes: {nodes}")

    # Start acquisition if node specified
    if node_id:
        print(f"\nStarting acquisition on {node_id}...")
        collector.send_acquire_start(node_id)
        time.sleep(1.0)

    # Collect values
    print(f"\nCollecting values for {duration} seconds...")
    collector.clear_values()
    time.sleep(duration)

    # Get results
    values = collector.get_all_values()
    batch_count = collector.get_batch_count()

    print(f"\nResults:")
    print(f"  Batches received: {batch_count}")
    print(f"  Channels with values: {len(values)}")

    if len(values) == 0:
        print("\nERROR: No channel values received!")
        collector.disconnect()
        return False

    # Validate each channel
    print("\n" + "-" * 70)
    print("Channel Validation")
    print("-" * 70)

    all_valid = True
    valid_count = 0
    error_count = 0

    # Group by type for organized output
    by_type: Dict[str, List[ChannelValue]] = {}
    for ch in values.values():
        ch_type = ch.channel_type or 'unknown'
        if ch_type not in by_type:
            by_type[ch_type] = []
        by_type[ch_type].append(ch)

    for ch_type, channels in sorted(by_type.items()):
        print(f"\n{ch_type.upper()} Channels ({len(channels)}):")

        for ch in sorted(channels, key=lambda x: x.name):
            errors = validate_channel_value(ch)

            if errors:
                print(f"  [FAIL] {ch.name}: value={ch.value:.4f}, quality={ch.quality}")
                for err in errors:
                    print(f"         - {err}")
                error_count += 1
                all_valid = False
            else:
                print(f"  [OK]   {ch.name}: value={ch.value:.4f}, quality={ch.quality}")
                valid_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total channels: {len(values)}")
    print(f"Valid: {valid_count}")
    print(f"Errors: {error_count}")

    if batch_count < 3:
        print(f"\nWARNING: Only {batch_count} batches received (expected more)")

    # Stop acquisition if we started it
    if node_id:
        collector.send_acquire_stop(node_id)

    collector.disconnect()

    print("\n" + "=" * 70)
    if all_valid:
        print("RESULT: ALL CHANNELS VALID")
    else:
        print("RESULT: VALIDATION ERRORS FOUND")
    print("=" * 70)

    return all_valid

def main():
    parser = argparse.ArgumentParser(description='Validate all channel values')
    parser.add_argument('--broker', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--node', default=None, help='Specific node ID to test')
    parser.add_argument('--duration', type=float, default=5.0, help='Collection duration in seconds')
    args = parser.parse_args()

    success = run_validation(
        broker=args.broker,
        node_id=args.node,
        duration=args.duration
    )

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
