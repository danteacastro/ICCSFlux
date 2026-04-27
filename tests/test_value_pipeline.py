#!/usr/bin/env python3
"""
Value Pipeline Validation Test

Compares channel values from cRIO directly against what DAQ service publishes.
This validates the entire data pipeline: cRIO -> MQTT -> DAQ Service -> Dashboard

Usage:
    python tests/test_value_pipeline.py --broker 192.168.1.1 --duration 10

The test:
1. Subscribes to cRIO's raw channel/batch topic
2. Subscribes to DAQ service's processed channel/batch topic
3. Compares values channel-by-channel
4. Reports any discrepancies (missing channels, value mismatches, delays)
"""

import json
import time
import argparse
import threading
import sys
import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    if __name__ == "__main__":
        print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
        sys.exit(1)

@dataclass
class ChannelSample:
    """A single channel value sample."""
    name: str
    value: float
    timestamp: float
    quality: str
    receive_time: float  # When we received it
    source: str  # 'crio' or 'daq'

@dataclass
class ChannelComparison:
    """Comparison result for a single channel."""
    name: str
    crio_value: Optional[float] = None
    daq_value: Optional[float] = None
    crio_timestamp: Optional[float] = None
    daq_timestamp: Optional[float] = None
    crio_quality: Optional[str] = None
    daq_quality: Optional[str] = None
    value_diff: Optional[float] = None
    timestamp_diff: Optional[float] = None
    match: bool = False
    issues: List[str] = field(default_factory=list)

class PipelineValidator:
    """Validates data pipeline from cRIO to DAQ service."""

    def __init__(self, broker: str, port: int = 1883,
                 crio_node: str = 'crio-001', daq_node: str = 'node-001'):
        self.broker = broker
        self.port = port
        self.crio_node = crio_node
        self.daq_node = daq_node

        self.client = mqtt.Client(client_id=f"pipeline-validator-{int(time.time())}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.connected = False
        self._lock = threading.Lock()

        # Store latest values from each source
        self.crio_values: Dict[str, ChannelSample] = {}
        self.daq_values: Dict[str, ChannelSample] = {}

        # Store all samples for analysis
        self.crio_samples: List[ChannelSample] = []
        self.daq_samples: List[ChannelSample] = []

        # Batch counters
        self.crio_batch_count = 0
        self.daq_batch_count = 0

        # Timing
        self.start_time = 0.0

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
            # Subscribe to both sources
            # cRIO publishes to: nisystem/nodes/crio-001/channels/batch
            # DAQ publishes to: nisystem/nodes/node-001/channels/batch
            client.subscribe(f"nisystem/nodes/{self.crio_node}/channels/batch")
            client.subscribe(f"nisystem/nodes/{self.daq_node}/channels/batch")
            # Also subscribe to individual channel topics
            client.subscribe(f"nisystem/nodes/{self.crio_node}/channels/#")
            client.subscribe(f"nisystem/nodes/{self.daq_node}/channels/#")
            print(f"Subscribed to {self.crio_node} and {self.daq_node} channel topics")

    def _on_message(self, client, userdata, msg):
        receive_time = time.time()

        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except:
            return

        topic = msg.topic

        # Determine source
        if self.crio_node in topic:
            source = 'crio'
        elif self.daq_node in topic:
            source = 'daq'
        else:
            return

        # Handle batch messages
        if '/channels/batch' in topic:
            with self._lock:
                if source == 'crio':
                    self.crio_batch_count += 1
                else:
                    self.daq_batch_count += 1

                for ch_name, ch_data in payload.items():
                    if isinstance(ch_data, dict) and 'value' in ch_data:
                        sample = ChannelSample(
                            name=ch_name,
                            value=ch_data.get('value', 0.0),
                            timestamp=ch_data.get('timestamp', 0.0),
                            quality=ch_data.get('quality', 'unknown'),
                            receive_time=receive_time,
                            source=source
                        )

                        if source == 'crio':
                            self.crio_values[ch_name] = sample
                            self.crio_samples.append(sample)
                        else:
                            self.daq_values[ch_name] = sample
                            self.daq_samples.append(sample)

    def clear(self):
        """Clear all collected data."""
        with self._lock:
            self.crio_values.clear()
            self.daq_values.clear()
            self.crio_samples.clear()
            self.daq_samples.clear()
            self.crio_batch_count = 0
            self.daq_batch_count = 0

    def get_comparison(self, tolerance: float = 0.001) -> List[ChannelComparison]:
        """
        Compare latest values from cRIO and DAQ service.

        Args:
            tolerance: Maximum allowed value difference (default 0.001)

        Returns:
            List of ChannelComparison results
        """
        results = []

        with self._lock:
            # Get all channel names from both sources
            all_channels = set(self.crio_values.keys()) | set(self.daq_values.keys())

            for ch_name in sorted(all_channels):
                comp = ChannelComparison(name=ch_name)

                crio_sample = self.crio_values.get(ch_name)
                daq_sample = self.daq_values.get(ch_name)

                if crio_sample:
                    comp.crio_value = crio_sample.value
                    comp.crio_timestamp = crio_sample.timestamp
                    comp.crio_quality = crio_sample.quality
                else:
                    comp.issues.append("Missing from cRIO")

                if daq_sample:
                    comp.daq_value = daq_sample.value
                    comp.daq_timestamp = daq_sample.timestamp
                    comp.daq_quality = daq_sample.quality
                else:
                    comp.issues.append("Missing from DAQ")

                # Compare if both present
                if crio_sample and daq_sample:
                    comp.value_diff = abs(crio_sample.value - daq_sample.value)
                    comp.timestamp_diff = abs(crio_sample.timestamp - daq_sample.timestamp)

                    # Check value match
                    if comp.value_diff > tolerance:
                        comp.issues.append(f"Value mismatch: diff={comp.value_diff:.6f}")

                    # Check timestamp (allow 1 second drift)
                    if comp.timestamp_diff > 1.0:
                        comp.issues.append(f"Timestamp drift: {comp.timestamp_diff:.3f}s")

                    # Check quality
                    if crio_sample.quality != daq_sample.quality:
                        comp.issues.append(f"Quality mismatch: {crio_sample.quality} vs {daq_sample.quality}")

                    comp.match = len(comp.issues) == 0

                results.append(comp)

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        with self._lock:
            return {
                'crio_batches': self.crio_batch_count,
                'daq_batches': self.daq_batch_count,
                'crio_channels': len(self.crio_values),
                'daq_channels': len(self.daq_values),
                'crio_samples': len(self.crio_samples),
                'daq_samples': len(self.daq_samples),
            }

def run_validation(broker: str, duration: float = 10.0,
                   crio_node: str = 'crio-001', daq_node: str = 'node-001',
                   tolerance: float = 0.001) -> Tuple[bool, List[ChannelComparison]]:
    """
    Run pipeline validation.

    Args:
        broker: MQTT broker address
        duration: How long to collect data
        crio_node: cRIO node ID
        daq_node: DAQ service node ID
        tolerance: Value match tolerance

    Returns:
        (success, comparisons)
    """
    print("\n" + "=" * 80)
    print("Value Pipeline Validation")
    print("=" * 80)
    print(f"Broker: {broker}")
    print(f"cRIO Node: {crio_node}")
    print(f"DAQ Node: {daq_node}")
    print(f"Duration: {duration}s")
    print(f"Tolerance: {tolerance}")

    validator = PipelineValidator(broker, crio_node=crio_node, daq_node=daq_node)

    if not validator.connect():
        print("\nERROR: Could not connect to MQTT broker")
        return False, []

    print("\nConnected to MQTT broker")
    print(f"Collecting data for {duration} seconds...")

    validator.clear()
    time.sleep(duration)

    stats = validator.get_stats()
    print(f"\nCollection Statistics:")
    print(f"  cRIO batches: {stats['crio_batches']}")
    print(f"  DAQ batches: {stats['daq_batches']}")
    print(f"  cRIO channels: {stats['crio_channels']}")
    print(f"  DAQ channels: {stats['daq_channels']}")

    if stats['crio_batches'] == 0:
        print(f"\nWARNING: No data received from cRIO ({crio_node})")
        print("  - Is the cRIO node running?")
        print("  - Is acquisition started?")

    if stats['daq_batches'] == 0:
        print(f"\nWARNING: No data received from DAQ service ({daq_node})")
        print("  - Is the DAQ service running?")
        print("  - Is acquisition started?")

    # Compare values
    comparisons = validator.get_comparison(tolerance)

    if not comparisons:
        print("\nNo channels to compare")
        validator.disconnect()
        return False, []

    # Print results
    print("\n" + "-" * 80)
    print("Channel-by-Channel Comparison")
    print("-" * 80)

    # Group by match status
    matched = [c for c in comparisons if c.match]
    mismatched = [c for c in comparisons if not c.match and c.crio_value is not None and c.daq_value is not None]
    crio_only = [c for c in comparisons if c.crio_value is not None and c.daq_value is None]
    daq_only = [c for c in comparisons if c.crio_value is None and c.daq_value is not None]

    # Print matched channels
    if matched:
        print(f"\n[MATCHED] {len(matched)} channels match exactly:")
        for c in matched[:10]:  # Show first 10
            print(f"  {c.name}: cRIO={c.crio_value:.4f}, DAQ={c.daq_value:.4f}")
        if len(matched) > 10:
            print(f"  ... and {len(matched) - 10} more")

    # Print mismatched channels (most important)
    if mismatched:
        print(f"\n[MISMATCH] {len(mismatched)} channels have discrepancies:")
        for c in mismatched:
            print(f"  {c.name}:")
            print(f"    cRIO: value={c.crio_value:.6f}, ts={c.crio_timestamp:.3f}, quality={c.crio_quality}")
            print(f"    DAQ:  value={c.daq_value:.6f}, ts={c.daq_timestamp:.3f}, quality={c.daq_quality}")
            print(f"    Diff: value={c.value_diff:.6f}, ts={c.timestamp_diff:.3f}s")
            for issue in c.issues:
                print(f"    -> {issue}")

    # Print cRIO-only channels
    if crio_only:
        print(f"\n[CRIO ONLY] {len(crio_only)} channels only in cRIO (not in DAQ):")
        for c in crio_only:
            print(f"  {c.name}: value={c.crio_value:.4f}")

    # Print DAQ-only channels
    if daq_only:
        print(f"\n[DAQ ONLY] {len(daq_only)} channels only in DAQ (not in cRIO):")
        for c in daq_only:
            print(f"  {c.name}: value={c.daq_value:.4f}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total channels: {len(comparisons)}")
    print(f"Matched:        {len(matched)}")
    print(f"Mismatched:     {len(mismatched)}")
    print(f"cRIO only:      {len(crio_only)}")
    print(f"DAQ only:       {len(daq_only)}")

    success = len(mismatched) == 0 and len(crio_only) == 0 and len(daq_only) == 0

    print("\n" + "=" * 80)
    if success:
        print("RESULT: ALL CHANNELS VALIDATED - Pipeline is working correctly")
    else:
        print("RESULT: VALIDATION ISSUES FOUND")
        if mismatched:
            print(f"  - {len(mismatched)} value/quality mismatches")
        if crio_only:
            print(f"  - {len(crio_only)} channels not reaching DAQ service")
        if daq_only:
            print(f"  - {len(daq_only)} channels in DAQ but not from cRIO")
    print("=" * 80)

    validator.disconnect()
    return success, comparisons

def run_detailed_channel_report(broker: str, duration: float = 5.0,
                                 crio_node: str = 'crio-001',
                                 daq_node: str = 'node-001') -> None:
    """
    Generate a detailed report of all channels with their values.

    Shows each channel's:
    - Name
    - cRIO value
    - DAQ value
    - Type (inferred)
    - Status
    """
    print("\n" + "=" * 80)
    print("Detailed Channel Report")
    print("=" * 80)

    validator = PipelineValidator(broker, crio_node=crio_node, daq_node=daq_node)

    if not validator.connect():
        print("ERROR: Could not connect to MQTT broker")
        return

    print(f"Collecting data for {duration} seconds...")
    validator.clear()
    time.sleep(duration)

    comparisons = validator.get_comparison()
    validator.disconnect()

    if not comparisons:
        print("No data collected")
        return

    # Sort by channel name to group by module
    comparisons.sort(key=lambda c: c.name)

    # Print table header
    print("\n" + "-" * 100)
    print(f"{'Channel':<25} {'Type':<12} {'cRIO Value':>15} {'DAQ Value':>15} {'Diff':>10} {'Status':<10}")
    print("-" * 100)

    for c in comparisons:
        # Infer type from name
        if 'TC' in c.name or 'tc' in c.name:
            ch_type = 'TC'
        elif 'DI' in c.name or 'di' in c.name:
            ch_type = 'DI'
        elif 'DO' in c.name or 'do' in c.name:
            ch_type = 'DO'
        elif 'AO' in c.name or 'ao' in c.name:
            ch_type = 'AO'
        elif 'AI' in c.name or 'ai' in c.name or 'VI' in c.name:
            ch_type = 'VI'
        elif 'Mod5' in c.name:
            ch_type = 'TC'
        elif 'Mod3' in c.name:
            ch_type = 'DI'
        elif 'Mod4' in c.name:
            ch_type = 'DO'
        elif 'Mod2' in c.name or 'Mod6' in c.name:
            ch_type = 'AO'
        else:
            ch_type = 'VI'

        # Format values
        crio_str = f"{c.crio_value:.4f}" if c.crio_value is not None else "N/A"
        daq_str = f"{c.daq_value:.4f}" if c.daq_value is not None else "N/A"
        diff_str = f"{c.value_diff:.6f}" if c.value_diff is not None else "N/A"

        # Status
        if c.match:
            status = "OK"
        elif c.crio_value is None:
            status = "NO_CRIO"
        elif c.daq_value is None:
            status = "NO_DAQ"
        else:
            status = "MISMATCH"

        print(f"{c.name:<25} {ch_type:<12} {crio_str:>15} {daq_str:>15} {diff_str:>10} {status:<10}")

    print("-" * 100)
    print(f"Total: {len(comparisons)} channels")

def main():
    parser = argparse.ArgumentParser(description='Validate data pipeline from cRIO to DAQ service')
    parser.add_argument('--broker', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--crio-node', default='crio-001', help='cRIO node ID')
    parser.add_argument('--daq-node', default='node-001', help='DAQ service node ID')
    parser.add_argument('--duration', type=float, default=10.0, help='Collection duration in seconds')
    parser.add_argument('--tolerance', type=float, default=0.001, help='Value match tolerance')
    parser.add_argument('--report', action='store_true', help='Generate detailed channel report')
    args = parser.parse_args()

    if args.report:
        run_detailed_channel_report(
            broker=args.broker,
            duration=args.duration,
            crio_node=args.crio_node,
            daq_node=args.daq_node
        )
        return

    success, _ = run_validation(
        broker=args.broker,
        duration=args.duration,
        crio_node=args.crio_node,
        daq_node=args.daq_node,
        tolerance=args.tolerance
    )

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
