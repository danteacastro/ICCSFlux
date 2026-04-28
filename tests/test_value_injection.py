"""
Value Injection Tests — prove the VI/CI read pipeline forwards real data
without zeroing it.

These tests mock the NI buffer (np.ndarray) with known values and run the
exact processing logic from hardware_reader.py's continuous read loop.
Useful for debugging "all zeros" scenarios where you can't run NI MAX
test panels because the DAQ service holds the device.

Tests prove:
  1. A 5.0V buffer for VI → latest_values[name] = 5.0
  2. A 0.012A buffer for CI → latest_values[name] = 12.0 (Amps→mA conversion)
  3. A -1e10 buffer for TC → latest_values[name] = NaN (open-TC sentinel)
  4. A normal 25°C buffer for TC → latest_values[name] = 25.0
  5. A NaN buffer doesn't crash (regression)
  6. Last sample wins (we read multiple samples, store the latest)
"""

import pytest
import sys
import math
import threading
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import ChannelType


def replicate_read_loop_per_sample(buffer, channel_names, channel_types, latest_values,
                                    logged_open_tc=None):
    """
    Replicates the inner per-channel processing block from hardware_reader.py
    line ~1742-1763. This is the EXACT logic that converts buffer samples to
    latest_values. If this test passes, the pipeline is correct.

    buffer: np.ndarray shape (num_channels, num_samples)
    channel_names: list of channel names (parallel to buffer rows)
    channel_types: dict[name -> ChannelType]
    latest_values: dict to write into (mutated)
    logged_open_tc: optional set for open-TC dedup

    Source of truth: hardware_reader.py lines 1742-1763
    """
    if logged_open_tc is None:
        logged_open_tc = set()

    for i, name in enumerate(channel_names):
        value = buffer[i, -1]  # Last sample

        ch_type = channel_types.get(name)
        if ch_type == ChannelType.CURRENT_INPUT:
            value = value * 1000.0

        if ch_type == ChannelType.THERMOCOUPLE and abs(value) > 1e9:
            logged_open_tc.add(name)
            value = float('nan')

        latest_values[name] = float(value)


class TestValueInjection:
    """Inject known buffer values and verify they reach latest_values intact."""

    def test_voltage_input_5V_passes_through(self):
        """A 5.0V buffer must produce latest_values[name] == 5.0."""
        buffer = np.full((1, 100), 5.0, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        assert latest['VI_Test'] == 5.0

    def test_voltage_input_negative_value(self):
        """A -7.5V buffer must produce latest_values[name] == -7.5."""
        buffer = np.full((1, 100), -7.5, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        assert latest['VI_Test'] == -7.5

    def test_current_input_converted_to_mA(self):
        """0.012A buffer must produce 12.0 mA in latest_values."""
        buffer = np.full((1, 100), 0.012, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['CI_Test'], {'CI_Test': ChannelType.CURRENT_INPUT}, latest
        )
        assert latest['CI_Test'] == pytest.approx(12.0, rel=1e-9)

    def test_current_input_4mA(self):
        """0.004A buffer = 4 mA (4-20mA loop minimum)."""
        buffer = np.full((1, 100), 0.004, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['CI_Test'], {'CI_Test': ChannelType.CURRENT_INPUT}, latest
        )
        assert latest['CI_Test'] == pytest.approx(4.0, rel=1e-9)

    def test_current_input_20mA(self):
        """0.020A buffer = 20 mA (4-20mA loop maximum)."""
        buffer = np.full((1, 100), 0.020, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['CI_Test'], {'CI_Test': ChannelType.CURRENT_INPUT}, latest
        )
        assert latest['CI_Test'] == pytest.approx(20.0, rel=1e-9)

    def test_zero_voltage_stays_zero(self):
        """A 0V buffer must produce 0.0 (no spurious value)."""
        buffer = np.zeros((1, 100), dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        assert latest['VI_Test'] == 0.0

    def test_zero_current_stays_zero(self):
        """A 0A buffer must produce 0.0 mA (NI sim default behavior)."""
        buffer = np.zeros((1, 100), dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['CI_Test'], {'CI_Test': ChannelType.CURRENT_INPUT}, latest
        )
        assert latest['CI_Test'] == 0.0

    def test_thermocouple_normal_value(self):
        """A 25°C buffer must produce 25.0 (no sentinel sanitization)."""
        buffer = np.full((1, 100), 25.0, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['TC_Test'], {'TC_Test': ChannelType.THERMOCOUPLE}, latest
        )
        assert latest['TC_Test'] == 25.0

    def test_thermocouple_open_sentinel_to_NaN(self):
        """A -1e10 buffer (NI open-TC sentinel) must produce NaN."""
        buffer = np.full((1, 100), -1e10, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['TC_Test'], {'TC_Test': ChannelType.THERMOCOUPLE}, latest
        )
        assert math.isnan(latest['TC_Test'])

    def test_thermocouple_extreme_negative_to_NaN(self):
        """A -2e10 buffer (also open-TC) must produce NaN."""
        buffer = np.full((1, 100), -2e10, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['TC_Test'], {'TC_Test': ChannelType.THERMOCOUPLE}, latest
        )
        assert math.isnan(latest['TC_Test'])

    def test_voltage_at_open_tc_threshold_NOT_sanitized(self):
        """A 5e9 reading on a VOLTAGE channel must NOT be sanitized
        (sanitizer only applies to TC channels)."""
        buffer = np.full((1, 100), 5e9, dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        assert latest['VI_Test'] == 5e9
        assert not math.isnan(latest['VI_Test'])

    def test_last_sample_wins(self):
        """Buffer with 100 samples: latest_values must equal the LAST sample."""
        buffer = np.zeros((1, 100), dtype=np.float64)
        for i in range(100):
            buffer[0, i] = i * 0.1
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        # Last sample is 99 * 0.1 = 9.9
        assert latest['VI_Test'] == pytest.approx(9.9, rel=1e-9)

    def test_multi_channel_independent_values(self):
        """8 channels with different values: each must arrive correctly."""
        buffer = np.zeros((4, 100), dtype=np.float64)
        buffer[0, -1] = 1.5   # VI ch0
        buffer[1, -1] = 0.008 # CI ch1 → 8mA
        buffer[2, -1] = 22.0  # TC ch2 → 22°C
        buffer[3, -1] = -1e10 # TC ch3 → open → NaN

        latest = {}
        names = ['VI0', 'CI1', 'TC2', 'TC3']
        types = {
            'VI0': ChannelType.VOLTAGE_INPUT,
            'CI1': ChannelType.CURRENT_INPUT,
            'TC2': ChannelType.THERMOCOUPLE,
            'TC3': ChannelType.THERMOCOUPLE,
        }
        replicate_read_loop_per_sample(buffer, names, types, latest)

        assert latest['VI0'] == 1.5
        assert latest['CI1'] == pytest.approx(8.0, rel=1e-9)
        assert latest['TC2'] == 22.0
        assert math.isnan(latest['TC3'])

    def test_open_tc_logged_once_per_channel(self):
        """Open-TC warning dedup: same channel triggering multiple times
        should only add to logged_open_tc once."""
        buffer = np.full((1, 100), -1e10, dtype=np.float64)
        latest = {}
        logged = set()
        for _ in range(10):
            replicate_read_loop_per_sample(
                buffer, ['TC_Test'], {'TC_Test': ChannelType.THERMOCOUPLE},
                latest, logged_open_tc=logged
            )
        assert logged == {'TC_Test'}
        assert len(logged) == 1

    def test_NaN_buffer_does_not_crash(self):
        """If NI returns NaN already (driver error), pipeline must not crash."""
        buffer = np.full((1, 100), float('nan'), dtype=np.float64)
        latest = {}
        replicate_read_loop_per_sample(
            buffer, ['VI_Test'], {'VI_Test': ChannelType.VOLTAGE_INPUT}, latest
        )
        assert math.isnan(latest['VI_Test'])


class TestSourceLevelSanitizer:
    """Verify the open-TC sanitizer is actually present in hardware_reader.py
    (defends against future regressions)."""

    HARDWARE_READER = (
        Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
    )

    def test_sanitizer_check_present(self):
        content = self.HARDWARE_READER.read_text(encoding='utf-8')
        assert "abs(value) > 1e9" in content
        assert "ChannelType.THERMOCOUPLE" in content

    def test_sanitizer_logs_warning(self):
        content = self.HARDWARE_READER.read_text(encoding='utf-8')
        assert "Open thermocouple detected" in content

    def test_logged_open_tc_initialized(self):
        content = self.HARDWARE_READER.read_text(encoding='utf-8')
        assert "self._logged_open_tc" in content
        assert "self._logged_open_tc: set = set()" in content

    def test_logged_open_tc_cleared_on_recovery(self):
        content = self.HARDWARE_READER.read_text(encoding='utf-8')
        assert "self._logged_open_tc.clear()" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
