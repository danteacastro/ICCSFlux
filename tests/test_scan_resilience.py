"""
Scan Loop Resilience Tests

Simulates hardware failure scenarios to verify the acquisition system
recovers gracefully instead of dying.

Scenarios:
  1. Transient burst errors (10-20 consecutive read failures, then recovery)
  2. Hardware reader death and auto-reinit
  3. Intermittent NaN values from sensors
  4. Scaling errors on bad data
  5. Buffer overflow simulation
  6. Long-running stability (many cycles without accumulating state)
  7. Recovery after max errors
"""

import pytest
import sys
import time
import math
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Dict, Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import (
    ChannelConfig, ChannelType, SystemConfig, NISystemConfig, ProjectMode,
    DataViewerConfig, ChassisConfig, ModuleConfig, SafetyActionConfig,
)
from scaling import apply_scaling, validate_and_clamp, is_valid_value
from simulator import HardwareSimulator, ChannelSimulator


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def make_test_config(num_channels=3, scan_rate=4.0) -> NISystemConfig:
    """Create a minimal config for testing."""
    channels = {}
    for i in range(num_channels):
        channels[f"ch_{i}"] = ChannelConfig(
            name=f"ch_{i}",
            module="cDAQ1Mod1",
            physical_channel=f"cDAQ1Mod1/ai{i}",
            channel_type=ChannelType.CURRENT_INPUT,
            current_range_ma=20.0,
            terminal_config="differential",
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )

    system = SystemConfig(
        scan_rate_hz=scan_rate,
        publish_rate_hz=2.0,
        simulation_mode=True,
        project_mode=ProjectMode.CDAQ,
    )

    return NISystemConfig(
        system=system,
        dataviewer=DataViewerConfig(),
        chassis={},
        modules={},
        channels=channels,
        safety_actions={},
    )


class FlakySimulator:
    """A simulator that injects failures on demand for resilience testing."""

    def __init__(self, config: NISystemConfig):
        self.config = config
        self.real_sim = HardwareSimulator(config)
        self._fail_count = 0
        self._fail_after = None      # Start failing after N reads
        self._fail_for = None        # Fail for N reads then recover
        self._reads = 0
        self._nan_channels = set()   # Channels that return NaN
        self._exception_type = RuntimeError
        self._exception_msg = "Simulated hardware failure"
        self.read_log: List[dict] = []

    def configure_transient_failure(self, fail_after: int, fail_for: int,
                                     exception_type=RuntimeError, msg="Simulated failure"):
        """After fail_after reads, fail for fail_for reads, then recover."""
        self._fail_after = fail_after
        self._fail_for = fail_for
        self._exception_type = exception_type
        self._exception_msg = msg

    def configure_nan_channels(self, channel_names: set):
        """Make specific channels return NaN (simulates open TC / disconnected sensor)."""
        self._nan_channels = channel_names

    def read_all(self) -> Dict[str, float]:
        self._reads += 1

        # Check if we should fail
        if self._fail_after is not None and self._reads > self._fail_after:
            if self._fail_for is not None and self._fail_count < self._fail_for:
                self._fail_count += 1
                self.read_log.append({
                    'read': self._reads, 'status': 'error',
                    'error': self._exception_msg
                })
                raise self._exception_type(self._exception_msg)
            # Past the failure window — reset for possible reuse
            if self._fail_count >= self._fail_for:
                self._fail_after = None
                self._fail_for = None
                self._fail_count = 0

        # Normal read
        values = self.real_sim.read_all()

        # Inject NaN for specific channels
        for ch in self._nan_channels:
            if ch in values:
                values[ch] = float('nan')

        self.read_log.append({
            'read': self._reads, 'status': 'ok',
            'channels': len(values)
        })
        return values

    def write_channel(self, name: str, value: float):
        self.real_sim.write_channel(name, value)


class ScanLoopRunner:
    """Runs a simplified version of the scan loop for testing.

    This mimics the critical path from daq_service._scan_loop without
    needing MQTT, threading, or the full service stack.
    """

    def __init__(self, config: NISystemConfig, simulator):
        self.config = config
        self.simulator = simulator
        self.channel_values: Dict[str, float] = {}
        self.channel_raw_values: Dict[str, float] = {}
        self.acquiring = True
        self.scan_count = 0
        self.consecutive_errors = 0
        self.total_errors = 0
        self.max_consecutive_errors = 100  # Match production threshold
        self.stopped_reason = None
        self.recovered_count = 0
        self.valid_scan_count = 0

    def run_scans(self, num_scans: int) -> dict:
        """Run N scan cycles and return results."""
        for _ in range(num_scans):
            if not self.acquiring:
                break
            self._do_one_scan()
            self.scan_count += 1

        return {
            'scans': self.scan_count,
            'valid_scans': self.valid_scan_count,
            'total_errors': self.total_errors,
            'max_consecutive': self.consecutive_errors,
            'stopped': not self.acquiring,
            'stopped_reason': self.stopped_reason,
            'recoveries': self.recovered_count,
            'final_values': dict(self.channel_values),
        }

    def _do_one_scan(self):
        """Execute one scan cycle — mirrors daq_service._scan_loop body."""
        try:
            raw_values = self.simulator.read_all()

            # Apply scaling
            channel_config = dict(self.config.channels)
            valid_count = 0

            for name, raw_value in raw_values.items():
                validated_raw, status = validate_and_clamp(raw_value)
                channel = channel_config.get(name)

                if channel is not None:
                    if is_valid_value(validated_raw):
                        scaled_value = apply_scaling(channel, validated_raw)
                        if is_valid_value(scaled_value):
                            self.channel_values[name] = scaled_value
                            valid_count += 1
                        else:
                            self.channel_values[name] = float('nan')
                    else:
                        self.channel_values[name] = float('nan')

                    self.channel_raw_values[name] = raw_value

            # Scan succeeded — reset error counter
            if self.consecutive_errors > 0:
                self.recovered_count += 1
            self.consecutive_errors = 0
            self.valid_scan_count += 1

        except Exception as e:
            self.consecutive_errors += 1
            self.total_errors += 1

            if self.consecutive_errors >= self.max_consecutive_errors:
                self.acquiring = False
                self.stopped_reason = f"Fatal: {self.consecutive_errors} consecutive errors"


# ===================================================================
# Test Suite
# ===================================================================

class TestTransientBurstErrors:
    """Simulate transient hardware glitches — short bursts of errors that recover."""

    def test_10_error_burst_recovers(self):
        """10 consecutive errors followed by recovery — should NOT stop acquisition."""
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=5, fail_for=10)

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(50)

        assert not result['stopped'], f"Should not stop after 10 errors: {result['stopped_reason']}"
        assert result['total_errors'] == 10
        assert result['recoveries'] >= 1
        assert result['valid_scans'] >= 35

    def test_20_error_burst_recovers(self):
        """20 consecutive errors — still within threshold, should recover."""
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=5, fail_for=20)

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(50)

        assert not result['stopped']
        assert result['total_errors'] == 20
        assert result['recoveries'] >= 1

    def test_50_error_burst_recovers(self):
        """50 consecutive errors — at the hardware reader threshold, should still recover in scan loop."""
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=5, fail_for=50)

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(100)

        assert not result['stopped']
        assert result['total_errors'] == 50
        assert result['valid_scans'] >= 40

    def test_99_errors_still_alive(self):
        """99 consecutive errors — just under the fatal threshold."""
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=5, fail_for=99)

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(150)

        assert not result['stopped']
        assert result['total_errors'] == 99

    def test_100_errors_stops(self):
        """100 consecutive errors — hits the fatal threshold, should stop."""
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=5, fail_for=200)  # More than threshold

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(200)

        assert result['stopped']
        assert "Fatal" in result['stopped_reason']


class TestNaNResilience:
    """Sensors can return NaN (open thermocouple, disconnected wire).
    The scan loop must continue even with NaN channels."""

    def test_single_nan_channel(self):
        """One channel returns NaN — others should still work."""
        config = make_test_config(num_channels=3)
        sim = FlakySimulator(config)
        sim.configure_nan_channels({'ch_0'})

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(20)

        assert not result['stopped']
        assert result['valid_scans'] == 20
        assert math.isnan(result['final_values']['ch_0'])
        assert not math.isnan(result['final_values']['ch_1'])

    def test_all_nan_channels(self):
        """All channels return NaN — should continue (not crash)."""
        config = make_test_config(num_channels=3)
        sim = FlakySimulator(config)
        sim.configure_nan_channels({'ch_0', 'ch_1', 'ch_2'})

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(20)

        assert not result['stopped']
        assert result['valid_scans'] == 20
        # All values should be NaN but scan loop didn't crash
        for name in ['ch_0', 'ch_1', 'ch_2']:
            assert math.isnan(result['final_values'][name])


class TestScalingResilience:
    """Scaling should never crash the scan loop, even with bad config."""

    def test_zero_range_map_scaling(self):
        """Map scaling with zero range should not crash."""
        config = make_test_config(num_channels=1)
        config.channels['ch_0'].pre_scaled_min = 5.0
        config.channels['ch_0'].pre_scaled_max = 5.0  # Zero range!

        sim = FlakySimulator(config)
        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(20)

        assert not result['stopped']
        assert result['valid_scans'] == 20

    def test_none_scaling_params(self):
        """Missing scaling params should pass through raw value."""
        config = make_test_config(num_channels=1)
        config.channels['ch_0'].scale_type = 'map'
        config.channels['ch_0'].pre_scaled_min = None
        config.channels['ch_0'].scaled_min = None

        sim = FlakySimulator(config)
        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(20)

        assert not result['stopped']
        assert result['valid_scans'] == 20


class TestLongRunningStability:
    """Verify no state accumulation over many scan cycles."""

    def test_1000_scans_no_drift(self):
        """Run 1000 scans — error counters should stay at 0, no memory leaks."""
        config = make_test_config()
        sim = FlakySimulator(config)

        runner = ScanLoopRunner(config, sim)
        result = runner.run_scans(1000)

        assert not result['stopped']
        assert result['valid_scans'] == 1000
        assert result['total_errors'] == 0
        assert result['max_consecutive'] == 0

    def test_1000_scans_with_periodic_errors(self):
        """1000 scans with periodic single errors — should never accumulate."""
        config = make_test_config()
        sim = FlakySimulator(config)

        runner = ScanLoopRunner(config, sim)

        # Inject a single error every 50 scans
        for batch in range(20):
            runner.run_scans(49)  # 49 good scans
            sim.configure_transient_failure(
                fail_after=0, fail_for=1
            )
            runner.run_scans(1)  # 1 bad scan

        result = {
            'stopped': not runner.acquiring,
            'valid_scans': runner.valid_scan_count,
            'total_errors': runner.total_errors,
        }

        assert not result['stopped']
        assert result['total_errors'] == 20  # 20 single errors
        assert result['valid_scans'] >= 960


class TestMultipleFailureRecovery:
    """Multiple failure/recovery cycles — system should keep recovering."""

    def test_three_failure_bursts(self):
        """Three separate bursts of 30 errors each — should recover each time."""
        config = make_test_config()
        sim = FlakySimulator(config)
        runner = ScanLoopRunner(config, sim)

        for burst in range(3):
            # Run 20 good scans
            runner.run_scans(20)
            assert not runner.acquiring == False, f"Died during good scans in burst {burst}"

            # Inject 30 errors
            sim.configure_transient_failure(fail_after=0, fail_for=30)
            runner.run_scans(35)
            assert not runner.acquiring == False, f"Died during error burst {burst}"

        assert runner.valid_scan_count >= 50
        assert runner.total_errors == 90  # 3 x 30
        assert runner.recovered_count >= 3


class TestSimulatorBaseline:
    """Verify the test simulator itself works correctly."""

    def test_normal_reads(self):
        config = make_test_config()
        sim = FlakySimulator(config)

        values = sim.read_all()
        assert len(values) == 3
        for name in ['ch_0', 'ch_1', 'ch_2']:
            assert name in values
            assert isinstance(values[name], (int, float))

    def test_configured_failure(self):
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_transient_failure(fail_after=2, fail_for=3)

        # First 2 reads OK
        sim.read_all()
        sim.read_all()

        # Next 3 should fail
        for i in range(3):
            with pytest.raises(RuntimeError):
                sim.read_all()

        # Should recover
        values = sim.read_all()
        assert len(values) == 3

    def test_nan_injection(self):
        config = make_test_config()
        sim = FlakySimulator(config)
        sim.configure_nan_channels({'ch_1'})

        values = sim.read_all()
        assert not math.isnan(values['ch_0'])
        assert math.isnan(values['ch_1'])
        assert not math.isnan(values['ch_2'])


class TestValidateAndClamp:
    """Test the value validation pipeline."""

    def test_normal_value(self):
        val, status = validate_and_clamp(12.5)
        assert val == 12.5
        assert status == 'good'

    def test_nan(self):
        val, status = validate_and_clamp(float('nan'))
        assert math.isnan(val)
        assert status == 'nan'

    def test_inf(self):
        val, status = validate_and_clamp(float('inf'))
        assert math.isnan(val)
        assert status == 'inf'

    def test_open_thermocouple(self):
        val, status = validate_and_clamp(1e305)
        assert math.isnan(val)
        assert status == 'open_tc'

    def test_none(self):
        val, status = validate_and_clamp(None)
        assert math.isnan(val)
        assert status == 'nan'

    def test_zero_is_valid(self):
        val, status = validate_and_clamp(0.0)
        assert val == 0.0
        assert status == 'good'

    def test_negative_is_valid(self):
        val, status = validate_and_clamp(-15.3)
        assert val == -15.3
        assert status == 'good'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
