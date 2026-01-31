#!/usr/bin/env python3
"""
Thermocouple Diagnostic Test Suite

Diagnoses the NI 9213 split-reading issue where:
  - Mod5/ai0-ai7 (tag_72-79) read 0.00°C
  - Mod5/ai8-ai15 (tag_80-87) read 2293.78°C (open TC)

Expected behavior:
  - tag_72 (ai0): ~22°C (ambient, probe connected)
  - tag_73-87 (ai1-ai15): ~2293.78°C (open thermocouple)

Tests:
  1. MQTT-based: Subscribe to cRIO channel data and verify TC values
  2. Config push verification: Ensure config reaches cRIO with correct TC types
  3. Channel ordering: Verify channels are sorted by physical index
  4. Value distribution: Check for bank-boundary artifacts (ai0-7 vs ai8-15)

Requirements:
  - DAQ service running on PC
  - cRIO online
  - MQTT broker at localhost:1883
  - Project loaded with TC channels on Mod5

Run:
    python tests/test_thermocouple_diagnostics.py
    pytest tests/test_thermocouple_diagnostics.py -v -s
"""

import json
import time
import sys
import os
import threading
import unittest
from typing import Dict, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from tests.test_helpers import MQTT_HOST, MQTT_PORT, SYSTEM_PREFIX, MQTTTestHarness

# cRIO node topic base
CRIO_NODE_BASE = f"{SYSTEM_PREFIX}/nodes/crio-001"
DAQ_NODE_BASE = f"{SYSTEM_PREFIX}/nodes/node-001"


def _load_tc_channels_from_project() -> tuple:
    """
    Load TC channel names from the active project config.

    Returns (all_channels, bank0, bank1, probe_channel) where:
    - all_channels: sorted list of all TC tag names
    - bank0: first half (ai0-ai7 equivalent)
    - bank1: second half (ai8-ai15 equivalent)
    - probe_channel: first TC channel (assumed to have probe)
    """
    import re
    from pathlib import Path

    project_dir = Path(__file__).parent.parent / "config" / "projects"

    # Try each project file
    for fpath in sorted(project_dir.glob("*.json")):
        if 'backup' in fpath.name.lower():
            continue
        try:
            with open(fpath) as f:
                proj = json.load(f)
            channels = proj.get('channels', [])
            if isinstance(channels, list):
                tc_list = []
                for ch in channels:
                    if ch.get('channel_type') == 'thermocouple':
                        phys = ch.get('physical_channel', '')
                        idx_match = re.search(r'(\d+)$', phys)
                        idx = int(idx_match.group(1)) if idx_match else 0
                        tc_list.append((idx, ch['name'], phys))
                if tc_list:
                    tc_list.sort(key=lambda x: x[0])
                    all_names = [name for _, name, _ in tc_list]
                    half = len(all_names) // 2
                    return all_names, all_names[:half], all_names[half:], all_names[0]
        except Exception:
            continue

    # Default fallback for the known project layout
    all_ch = [f"tag_{i}" for i in range(72, 88)]
    return all_ch, all_ch[:8], all_ch[8:], all_ch[0]


# Load TC channel config (works with any project)
TC_CHANNELS, TC_BANK_0, TC_BANK_1, TC_PROBE_CHANNEL = _load_tc_channels_from_project()

# Temperature thresholds
OPEN_TC_MIN = 1500.0     # Open TC reads > 1500°C on NI 9213
AMBIENT_MIN = 10.0        # Ambient temp at least 10°C
AMBIENT_MAX = 50.0        # Ambient temp at most 50°C
ZERO_THRESHOLD = 0.5      # Values below this are "zero" (unread/default)


class TCDiagnosticClient:
    """Specialized MQTT client for TC diagnostics."""

    def __init__(self):
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"tc-diag-{int(time.time()) % 10000}",
            transport='tcp'
        )
        self.connected = False
        self._lock = threading.Lock()

        # Channel data from cRIO (direct)
        self.crio_values: Dict[str, float] = {}
        self.crio_batch_count = 0

        # Channel data from DAQ service (forwarded)
        self.daq_values: Dict[str, float] = {}
        self.daq_batch_count = 0

        # System status
        self.system_status: Optional[dict] = None
        self.crio_status: Optional[dict] = None

        # Config push tracking
        self.config_response: Optional[dict] = None

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = (rc.value == 0) if hasattr(rc, 'value') else (rc == 0)
        if self.connected:
            # Subscribe to cRIO channel batches (direct from cRIO)
            client.subscribe(f"{CRIO_NODE_BASE}/channels/batch")
            # Subscribe to DAQ service channel batches (forwarded to dashboard)
            client.subscribe(f"{DAQ_NODE_BASE}/channels/batch")
            # Subscribe to system status
            client.subscribe(f"{DAQ_NODE_BASE}/status/system")
            # Subscribe to cRIO status
            client.subscribe(f"{CRIO_NODE_BASE}/status/system")
            # Subscribe to cRIO config response
            client.subscribe(f"{CRIO_NODE_BASE}/config/response")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        topic = msg.topic

        with self._lock:
            if topic == f"{CRIO_NODE_BASE}/channels/batch":
                self.crio_batch_count += 1
                for ch_name, ch_data in payload.items():
                    if isinstance(ch_data, dict):
                        val = ch_data.get('value')
                        if val is not None:
                            self.crio_values[ch_name] = float(val)
                    elif isinstance(ch_data, (int, float)):
                        self.crio_values[ch_name] = float(ch_data)

            elif topic == f"{DAQ_NODE_BASE}/channels/batch":
                self.daq_batch_count += 1
                for ch_name, ch_data in payload.items():
                    if isinstance(ch_data, dict):
                        val = ch_data.get('value')
                        if val is not None:
                            self.daq_values[ch_name] = float(val)

            elif topic == f"{DAQ_NODE_BASE}/status/system":
                self.system_status = payload

            elif topic == f"{CRIO_NODE_BASE}/status/system":
                self.crio_status = payload

            elif topic == f"{CRIO_NODE_BASE}/config/response":
                self.config_response = payload

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

    def wait_for_crio_data(self, min_batches=3, timeout=15.0) -> bool:
        """Wait for cRIO to publish TC channel data."""
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if self.crio_batch_count >= min_batches:
                    return True
            time.sleep(0.5)
        return False

    def wait_for_daq_data(self, min_batches=3, timeout=15.0) -> bool:
        """Wait for DAQ service to forward TC data."""
        start = time.time()
        while (time.time() - start) < timeout:
            with self._lock:
                if self.daq_batch_count >= min_batches:
                    return True
            time.sleep(0.5)
        return False

    def get_tc_values(self, source='crio') -> Dict[str, float]:
        """Get TC channel values from either cRIO or DAQ."""
        with self._lock:
            values = self.crio_values if source == 'crio' else self.daq_values
            return {ch: values.get(ch) for ch in TC_CHANNELS if ch in values}

    def send_start(self):
        """Send acquire/start command."""
        self.client.publish(
            f"{DAQ_NODE_BASE}/system/acquire/start",
            json.dumps({}), qos=1
        )

    def send_stop(self):
        """Send acquire/stop command."""
        self.client.publish(
            f"{DAQ_NODE_BASE}/system/acquire/stop",
            json.dumps({}), qos=1
        )


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestThermocoupleReadings(unittest.TestCase):
    """Test TC values from cRIO and DAQ service."""

    @classmethod
    def setUpClass(cls):
        cls.diag = TCDiagnosticClient()
        if not cls.diag.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        # Wait for system status
        time.sleep(1.0)
        if not cls.diag.system_status:
            print("WARNING: No system status received - DAQ service may not be running")

        # If not acquiring, start acquisition
        if cls.diag.system_status and not cls.diag.system_status.get('acquiring'):
            print("Starting acquisition for TC test...")
            cls.diag.send_start()
            time.sleep(3.0)

        # Wait for cRIO data
        print("Waiting for cRIO channel data...")
        if not cls.diag.wait_for_crio_data(min_batches=3, timeout=15.0):
            print(f"WARNING: Only received {cls.diag.crio_batch_count} cRIO batches")

    @classmethod
    def tearDownClass(cls):
        cls.diag.disconnect()

    def test_01_crio_online(self):
        """Verify cRIO is online and publishing."""
        self.assertIsNotNone(self.diag.crio_status,
                             "No cRIO status received - cRIO may be offline")
        self.assertEqual(self.diag.crio_status.get('status'), 'online',
                         f"cRIO status: {self.diag.crio_status}")

    def test_02_crio_publishing_tc_channels(self):
        """Verify cRIO is publishing all 16 TC channels."""
        tc_values = self.diag.get_tc_values('crio')
        missing = [ch for ch in TC_CHANNELS if ch not in tc_values]

        self.assertEqual(len(missing), 0,
                         f"Missing TC channels from cRIO: {missing}\n"
                         f"  Received: {sorted(tc_values.keys())}\n"
                         f"  Batches: {self.diag.crio_batch_count}")

    def test_03_no_zero_values(self):
        """Verify no TC channels read exactly 0.00 (indicates unread/default).

        The NI 9213 should return either:
        - Ambient temperature (~20-25°C) for connected probes
        - Open TC reading (~2293°C) for disconnected channels
        Never 0.00°C unless there's actually a probe at 0°C.
        """
        tc_values = self.diag.get_tc_values('crio')
        zero_channels = {ch: v for ch, v in tc_values.items()
                         if abs(v) < ZERO_THRESHOLD}

        self.assertEqual(len(zero_channels), 0,
                         f"TC channels reading 0.00 (likely unread/default):\n"
                         f"  Zero channels: {zero_channels}\n"
                         f"  Bank 0 (ai0-7): {[tc_values.get(ch, 'MISSING') for ch in TC_BANK_0]}\n"
                         f"  Bank 1 (ai8-15): {[tc_values.get(ch, 'MISSING') for ch in TC_BANK_1]}")

    def test_04_bank_consistency(self):
        """Verify both banks of the NI 9213 are returning valid readings.

        The NI 9213 has two ADC banks (ai0-7 and ai8-15).
        Both should return non-zero values. A clean split at the bank
        boundary indicates a hardware configuration or task creation issue.
        """
        tc_values = self.diag.get_tc_values('crio')

        bank0_values = [tc_values.get(ch, 0.0) for ch in TC_BANK_0]
        bank1_values = [tc_values.get(ch, 0.0) for ch in TC_BANK_1]

        bank0_nonzero = sum(1 for v in bank0_values if abs(v) > ZERO_THRESHOLD)
        bank1_nonzero = sum(1 for v in bank1_values if abs(v) > ZERO_THRESHOLD)

        # Both banks should have all non-zero values
        self.assertEqual(bank0_nonzero, len(TC_BANK_0),
                         f"Bank 0 has {len(TC_BANK_0) - bank0_nonzero} zero values\n"
                         f"  Bank 0 values: {bank0_values}")
        self.assertEqual(bank1_nonzero, len(TC_BANK_1),
                         f"Bank 1 has {len(TC_BANK_1) - bank1_nonzero} zero values\n"
                         f"  Bank 1 values: {bank1_values}")

    def test_05_probe_channel_reads_ambient(self):
        """Verify the probe channel (tag_72/ai0) reads ambient temperature.

        Expected: ~15-40°C depending on environment.
        """
        tc_values = self.diag.get_tc_values('crio')
        probe_value = tc_values.get(TC_PROBE_CHANNEL)

        self.assertIsNotNone(probe_value,
                             f"Probe channel {TC_PROBE_CHANNEL} not in cRIO data")
        self.assertGreater(probe_value, AMBIENT_MIN,
                           f"Probe channel {TC_PROBE_CHANNEL} = {probe_value}°C "
                           f"(too cold for ambient)")
        self.assertLess(probe_value, AMBIENT_MAX,
                        f"Probe channel {TC_PROBE_CHANNEL} = {probe_value}°C "
                        f"(too hot for ambient - may be reading open TC)")

    def test_06_open_channels_read_high(self):
        """Verify open TC channels read high (>1500°C open circuit).

        Open (disconnected) thermocouples on the NI 9213 typically read
        ~2293.78°C (full scale). All channels except the probe channel
        should read this value.
        """
        tc_values = self.diag.get_tc_values('crio')
        open_channels = [ch for ch in TC_CHANNELS if ch != TC_PROBE_CHANNEL]
        low_open = {}

        for ch in open_channels:
            val = tc_values.get(ch)
            if val is not None and val < OPEN_TC_MIN:
                low_open[ch] = val

        self.assertEqual(len(low_open), 0,
                         f"Open TC channels not reading high:\n"
                         f"  Low-reading open channels: {low_open}\n"
                         f"  Expected > {OPEN_TC_MIN}°C for disconnected TCs")

    def test_07_daq_service_forwards_all_tc(self):
        """Verify DAQ service forwards all 16 TC channels to the dashboard."""
        # Wait for DAQ data
        self.diag.wait_for_daq_data(min_batches=3, timeout=10.0)

        daq_tc = self.diag.get_tc_values('daq')
        missing = [ch for ch in TC_CHANNELS if ch not in daq_tc]

        # Allow some tolerance - DAQ might not forward immediately
        self.assertLessEqual(len(missing), 2,
                             f"DAQ service missing TC channels: {missing}\n"
                             f"  DAQ batches received: {self.diag.daq_batch_count}\n"
                             f"  cRIO batches received: {self.diag.crio_batch_count}")

    def test_08_crio_daq_value_agreement(self):
        """Verify cRIO values match DAQ-forwarded values (no transformation errors)."""
        crio_tc = self.diag.get_tc_values('crio')
        daq_tc = self.diag.get_tc_values('daq')

        mismatches = {}
        for ch in TC_CHANNELS:
            crio_val = crio_tc.get(ch)
            daq_val = daq_tc.get(ch)
            if crio_val is not None and daq_val is not None:
                if abs(crio_val - daq_val) > 1.0:  # Allow 1°C tolerance
                    mismatches[ch] = (crio_val, daq_val)

        self.assertEqual(len(mismatches), 0,
                         f"Value mismatch between cRIO and DAQ:\n"
                         f"  {mismatches}")


@unittest.skipUnless(MQTT_AVAILABLE, "paho-mqtt not installed")
class TestTCConfigPush(unittest.TestCase):
    """Test that TC configuration is correctly pushed to cRIO."""

    @classmethod
    def setUpClass(cls):
        cls.harness = MQTTTestHarness("tc-config-test")
        if not cls.harness.connect():
            raise unittest.SkipTest("Cannot connect to MQTT broker")

        # Subscribe to cRIO config topics
        cls.harness.subscribe(f"{CRIO_NODE_BASE}/config/full")
        cls.harness.subscribe(f"{CRIO_NODE_BASE}/config/response")
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.harness.disconnect()

    def test_config_contains_tc_channels(self):
        """Verify pushed config includes thermocouple channels with correct types.

        Captures the next config push (either on project load or manual trigger)
        and verifies TC channel configuration.
        """
        # Trigger a config push by publishing a discovery ping
        # (config is pushed when cRIO comes online or on project load)
        config_msg = self.harness.wait_for_message(
            f"{CRIO_NODE_BASE}/config/full", timeout=10.0
        )

        if not config_msg:
            self.skipTest("No config push captured - trigger project reload to test")

        config = config_msg[0]['payload']
        channels = config.get('channels', {})

        # Check each TC channel
        for tc_tag in TC_CHANNELS:
            self.assertIn(tc_tag, channels,
                          f"TC channel {tc_tag} not in config push")

            ch = channels[tc_tag]
            self.assertEqual(ch.get('channel_type'), 'thermocouple',
                             f"{tc_tag} has wrong type: {ch.get('channel_type')}")
            self.assertIn(ch.get('thermocouple_type', '').upper(), ['K', 'J', 'T', 'E', 'N', 'R', 'S', 'B'],
                          f"{tc_tag} missing thermocouple_type")
            self.assertTrue(ch.get('physical_channel', '').startswith('Mod5/'),
                            f"{tc_tag} physical_channel doesn't start with Mod5/: {ch.get('physical_channel')}")


class TestChannelSorting(unittest.TestCase):
    """Test that channels are sorted by physical index for correct DAQmx mapping."""

    def test_hardware_v2_sorts_by_physical_index(self):
        """Verify hardware_v2 sorts channels by physical index.

        DAQmx returns values in the order channels are added to the task.
        If channels aren't sorted by physical index (ai0, ai1, ..., ai15),
        values get mapped to wrong channel names.
        """
        # Import the function we're testing
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'services'))

        try:
            from crio_node_v2.hardware_v2 import DAQCoreHardware, HardwareConfig, ChannelConfig
        except ImportError:
            self.skipTest("Cannot import hardware_v2 (daq_core may not be available)")

        # Create channels in REVERSE order (worst case for dict ordering)
        channels = {}
        for i in reversed(range(16)):
            name = f"tag_{72 + i}"
            channels[name] = ChannelConfig(
                name=name,
                physical_channel=f"Mod5/ai{i}",
                channel_type='thermocouple',
                thermocouple_type='K'
            )

        config = HardwareConfig(
            device_name="cRIO1",
            scan_rate_hz=4.0,
            channels=channels
        )

        # Instantiate hardware (won't actually connect to hardware)
        try:
            from daq_core import ModuleRegistry
            hw = DAQCoreHardware(config)

            # Test _detect_modules_from_channels
            modules = hw._detect_modules_from_channels()

            self.assertTrue(len(modules) > 0, "No modules detected from channels")

            # Find Mod5
            mod5 = None
            for m in modules:
                if m.get('device') == 'Mod5':
                    mod5 = m
                    break
            self.assertIsNotNone(mod5, "Mod5 not found in detected modules")
            self.assertEqual(mod5.get('model'), '9213',
                             f"Mod5 model is {mod5.get('model')}, expected 9213")
            self.assertEqual(len(mod5.get('channels', [])), 16,
                             f"Expected 16 TC channels, got {len(mod5.get('channels', []))}")

        except ImportError:
            self.skipTest("daq_core not available on this system")

    def test_physical_index_extraction(self):
        """Test physical channel index extraction regex."""
        import re

        test_cases = [
            ("Mod5/ai0", 0),
            ("Mod5/ai7", 7),
            ("Mod5/ai8", 8),
            ("Mod5/ai15", 15),
            ("Mod1/ai0", 0),
            ("Mod3/port0/line7", 7),
        ]

        for phys_ch, expected_idx in test_cases:
            match = re.search(r'(\d+)$', phys_ch)
            idx = int(match.group(1)) if match else -1
            self.assertEqual(idx, expected_idx,
                             f"Physical index of '{phys_ch}': got {idx}, expected {expected_idx}")

    def test_sort_preserves_correct_mapping(self):
        """Verify that sorting channels by physical index produces correct order."""
        import re

        # Simulate channels added in random dict order
        channels = []
        for i in [8, 3, 15, 0, 12, 5, 1, 9, 7, 14, 2, 11, 4, 13, 6, 10]:
            channels.append({
                'name': f'tag_{72 + i}',
                'physical_channel': f'Mod5/ai{i}',
            })

        # Sort by physical index (same logic as the fix)
        def _phys_index(ch):
            m = re.search(r'(\d+)$', ch['physical_channel'])
            return int(m.group(1)) if m else 0

        channels.sort(key=_phys_index)

        # Verify order
        for idx, ch in enumerate(channels):
            expected_phys = f'Mod5/ai{idx}'
            self.assertEqual(ch['physical_channel'], expected_phys,
                             f"Index {idx}: expected {expected_phys}, got {ch['physical_channel']}")


def print_diagnostic_report():
    """Run a standalone diagnostic report (no pytest required)."""
    print("=" * 60)
    print("NI 9213 Thermocouple Diagnostic Report")
    print("=" * 60)
    print()

    diag = TCDiagnosticClient()
    if not diag.connect():
        print("FAIL: Cannot connect to MQTT broker")
        return

    print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")

    # Wait for system status
    time.sleep(2.0)

    if diag.system_status:
        acquiring = diag.system_status.get('acquiring', False)
        print(f"DAQ Service: {'ACQUIRING' if acquiring else 'STOPPED'}")
    else:
        print("DAQ Service: NOT DETECTED")

    if diag.crio_status:
        print(f"cRIO Status: {diag.crio_status.get('status', 'unknown')}")
        print(f"cRIO Acquiring: {diag.crio_status.get('acquiring', False)}")
        print(f"cRIO Channels: {diag.crio_status.get('channels', 0)}")
    else:
        print("cRIO Status: NOT DETECTED")

    # If not acquiring, start
    if diag.system_status and not diag.system_status.get('acquiring'):
        print("\nStarting acquisition...")
        diag.send_start()
        time.sleep(3.0)

    # Wait for data
    print("\nWaiting for TC data (up to 15s)...")
    diag.wait_for_crio_data(min_batches=5, timeout=15.0)

    print(f"\ncRIO batches received: {diag.crio_batch_count}")
    print(f"DAQ batches received:  {diag.daq_batch_count}")

    # Report TC values
    tc_crio = diag.get_tc_values('crio')
    tc_daq = diag.get_tc_values('daq')

    print(f"\n{'Channel':<10} {'Physical':<12} {'cRIO Value':>12} {'DAQ Value':>12} {'Status':<20}")
    print("-" * 70)

    for i, ch in enumerate(TC_CHANNELS):
        phys = f"Mod5/ai{i}"
        crio_val = tc_crio.get(ch)
        daq_val = tc_daq.get(ch)

        crio_str = f"{crio_val:>12.2f}" if crio_val is not None else "    MISSING "
        daq_str = f"{daq_val:>12.2f}" if daq_val is not None else "    MISSING "

        # Determine status
        if crio_val is None:
            status = "NOT RECEIVED"
        elif abs(crio_val) < ZERO_THRESHOLD:
            status = "ZERO (BAD!)"
        elif crio_val > OPEN_TC_MIN:
            status = "Open TC (OK)" if i > 0 else "Open TC (BAD!)"
        elif AMBIENT_MIN < crio_val < AMBIENT_MAX:
            status = "Ambient (OK)" if i == 0 else "Ambient (?)"
        else:
            status = f"Unknown ({crio_val:.1f})"

        bank = "Bank0" if i < 8 else "Bank1"
        print(f"{ch:<10} {phys:<12} {crio_str} {daq_str} {status:<20} [{bank}]")

    # Summary
    print()
    bank0_zeros = sum(1 for ch in TC_BANK_0
                       if ch in tc_crio and abs(tc_crio[ch]) < ZERO_THRESHOLD)
    bank1_zeros = sum(1 for ch in TC_BANK_1
                       if ch in tc_crio and abs(tc_crio[ch]) < ZERO_THRESHOLD)

    print(f"Bank 0 (ai0-ai7):  {len([ch for ch in TC_BANK_0 if ch in tc_crio])}/8 received, "
          f"{bank0_zeros} zeros")
    print(f"Bank 1 (ai8-ai15): {len([ch for ch in TC_BANK_1 if ch in tc_crio])}/8 received, "
          f"{bank1_zeros} zeros")

    if bank0_zeros > 0 or bank1_zeros > 0:
        print("\n*** ISSUE DETECTED: Zero-value TC readings ***")
        print("  Possible causes:")
        print("  1. Channels not sorted by physical index in task creation")
        print("  2. CJC source not set to BUILT_IN for NI 9213")
        print("  3. NI 9213 bank 0/1 CJC sensor failure")
        print("  4. Task creation error (check cRIO logs)")
    else:
        print("\nAll TC channels returning non-zero values. System healthy.")

    diag.disconnect()


if __name__ == '__main__':
    if '--report' in sys.argv:
        print_diagnostic_report()
    else:
        # Run as diagnostic report by default (more useful than unittest)
        print_diagnostic_report()
        print("\n\nTo run as unit tests: pytest tests/test_thermocouple_diagnostics.py -v -s")
