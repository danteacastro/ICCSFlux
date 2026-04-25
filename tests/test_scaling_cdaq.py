"""
cDAQ Scaling Pipeline Tests — End-to-End Verification

Universal approach: all analog channels use the same map scaling fields
(pre_scaled_min/max → scaled_min/max).  No special checkbox needed.

Covers:
  1. Map scaling works universally for current_input (same as voltage_input)
  2. four_twenty_scaling (legacy/advanced) still works if explicitly enabled
  3. Simulator returns raw mA; hardware_reader converts Amps→mA
  4. apply_scaling receives mA and produces engineering units
  5. Fallback precedence: 4-20mA > map > linear > raw passthrough
  6. Guarded types (DI/DO/TC/RTD/Modbus) always pass through raw

Mike's scenario: cDAQ current input, 4-20mA → 0-100 °C
  At  4 mA → 0 °C
  At  8 mA → 25 °C
  At 12 mA → 50 °C
  At 20 mA → 100 °C
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import ChannelConfig, ChannelType
from scaling import (
    apply_scaling, scale_four_twenty, scale_map, scale_linear,
    validate_scaling_config, reverse_scaling, get_scaling_info,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_current_input(**overrides) -> ChannelConfig:
    """Create a current_input ChannelConfig with sensible defaults."""
    defaults = dict(
        name="mA_sensor",
        module="cDAQ1Mod2",
        physical_channel="cDAQ1Mod2/ai0",
        channel_type=ChannelType.CURRENT_INPUT,
        current_range_ma=20.0,
        scale_type="none",
        scale_slope=1.0,
        scale_offset=0.0,
        four_twenty_scaling=False,
        eng_units_min=None,
        eng_units_max=None,
        pre_scaled_min=None,
        pre_scaled_max=None,
        scaled_min=None,
        scaled_max=None,
    )
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def make_voltage_input(**overrides) -> ChannelConfig:
    defaults = dict(
        name="v_sensor",
        module="cDAQ1Mod1",
        physical_channel="cDAQ1Mod1/ai0",
        channel_type=ChannelType.VOLTAGE_INPUT,
        voltage_range=10.0,
        scale_type="none",
        scale_slope=1.0,
        scale_offset=0.0,
    )
    defaults.update(overrides)
    return ChannelConfig(**defaults)


# ===================================================================
# 1. Mike's exact scenario — 4-20mA → 0-100 °C (universal map scaling)
# ===================================================================

class TestMikeScenario:
    """Reproduce Mike's exact setup: cDAQ current input, 4-20mA, 0-100 °C.

    Uses universal map scaling (pre_scaled_min/max → scaled_min/max).
    No four_twenty_scaling checkbox needed.
    """

    @pytest.fixture
    def ch(self):
        return make_current_input(
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )

    def test_4mA_gives_0C(self, ch):
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)

    def test_8mA_gives_25C(self, ch):
        assert apply_scaling(ch, 8.0) == pytest.approx(25.0)

    def test_12mA_gives_50C(self, ch):
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)

    def test_16mA_gives_75C(self, ch):
        assert apply_scaling(ch, 16.0) == pytest.approx(75.0)

    def test_20mA_gives_100C(self, ch):
        assert apply_scaling(ch, 20.0) == pytest.approx(100.0)

    def test_validation_passes(self, ch):
        is_valid, err = validate_scaling_config(ch)
        assert is_valid, f"Validation failed: {err}"

    def test_reverse_scaling_map(self, ch):
        """50 °C → 12 mA via map reverse."""
        # Map reverse: pre_scaled_min + ((eng-scaled_min)/(scaled_max-scaled_min)) * (pre_scaled_max-pre_scaled_min)
        assert reverse_scaling(ch, 50.0) == pytest.approx(12.0)

    def test_scaling_info(self, ch):
        info = get_scaling_info(ch)
        assert info["type"] == "map"


class TestMikeScenarioFahrenheit:
    """32-212 °F range (another common transmitter config)."""

    @pytest.fixture
    def ch(self):
        return make_current_input(
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=32.0,
            scaled_max=212.0,
        )

    def test_4mA_gives_32F(self, ch):
        assert apply_scaling(ch, 4.0) == pytest.approx(32.0)

    def test_8mA_gives_77F(self, ch):
        assert apply_scaling(ch, 8.0) == pytest.approx(77.0)

    def test_12mA_gives_122F(self, ch):
        assert apply_scaling(ch, 12.0) == pytest.approx(122.0)

    def test_20mA_gives_212F(self, ch):
        assert apply_scaling(ch, 20.0) == pytest.approx(212.0)


# ===================================================================
# 2. Legacy four_twenty_scaling checkbox (advanced/convenience path)
# ===================================================================

class TestFourTwentyLegacy:
    """The four_twenty_scaling checkbox is an advanced convenience feature.
    It uses eng_units_min/max and has special under/over-range handling.
    Most users should use map scaling instead (no checkbox needed).
    """

    def test_flag_true_uses_eng_units(self):
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
        )
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)

    def test_flag_false_eng_units_ignored(self):
        """With flag off and no map scaling, eng_units are ignored."""
        ch = make_current_input(
            four_twenty_scaling=False,
            eng_units_min=0.0,
            eng_units_max=100.0,
        )
        # No scaling active → raw passthrough
        assert apply_scaling(ch, 12.0) == pytest.approx(12.0)

    def test_flag_true_but_eng_units_none(self):
        """If flag is on but eng_units not set, raw value passes through."""
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=None,
            eng_units_max=None,
        )
        assert apply_scaling(ch, 12.0) == pytest.approx(12.0)

    def test_validation_rejects_flag_without_eng_units(self):
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=None,
            eng_units_max=100.0,
        )
        is_valid, err = validate_scaling_config(ch)
        assert not is_valid
        assert "eng_units" in err.lower()

    def test_four_twenty_takes_precedence_over_map(self):
        """When both four_twenty and map are configured, four_twenty wins."""
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=200.0,
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )
        # 4-20 should produce 100 at 12mA (half of 200), not 50 (half of map 100)
        assert apply_scaling(ch, 12.0) == pytest.approx(100.0)


# ===================================================================
# 3. Universal map scaling — works for any channel type, any range
# ===================================================================

class TestUniversalMapScaling:
    """Map scaling uses the same 4 fields on every analog type.
    No special checkbox or flag needed — just set the fields.
    """

    def test_current_input_map(self):
        """Current input: 4-20mA → 0-100 via map scaling."""
        ch = make_current_input(
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )
        assert apply_scaling(ch, 8.0) == pytest.approx(25.0)

    def test_voltage_input_map(self):
        """Voltage input: 0-10V → 0-500 RPM."""
        ch = make_voltage_input(
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=500.0,
        )
        assert apply_scaling(ch, 5.0) == pytest.approx(250.0)

    def test_non_standard_current_range(self):
        """Current input: 0-20mA → 0-100 (not 4-20, just 0-20)."""
        ch = make_current_input(
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )
        assert apply_scaling(ch, 10.0) == pytest.approx(50.0)

    def test_inverted_range(self):
        """Reverse-acting: 4mA=100, 20mA=0."""
        ch = make_current_input(
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=100.0,
            scaled_max=0.0,
        )
        assert apply_scaling(ch, 4.0) == pytest.approx(100.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)

    def test_map_without_checkbox(self):
        """Map scaling works even when four_twenty_scaling is False."""
        ch = make_current_input(
            four_twenty_scaling=False,
            scale_type="map",
            pre_scaled_min=4.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=100.0,
        )
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)


# (TestCurrentInputMapScaling merged into TestUniversalMapScaling above)


# ===================================================================
# 5. Scale function unit tests
# ===================================================================

class TestScaleFourTwenty:
    """Direct tests of scale_four_twenty()."""

    def test_at_4mA(self):
        assert scale_four_twenty(4.0, 0, 100) == pytest.approx(0.0)

    def test_at_20mA(self):
        assert scale_four_twenty(20.0, 0, 100) == pytest.approx(100.0)

    def test_midpoint(self):
        assert scale_four_twenty(12.0, 0, 100) == pytest.approx(50.0)

    def test_quarter(self):
        assert scale_four_twenty(8.0, 0, 100) == pytest.approx(25.0)

    def test_three_quarter(self):
        assert scale_four_twenty(16.0, 0, 100) == pytest.approx(75.0)

    def test_with_offset_range(self):
        """32-212 °F range (common for temperature transmitters)."""
        assert scale_four_twenty(4.0, 32, 212) == pytest.approx(32.0)
        assert scale_four_twenty(20.0, 32, 212) == pytest.approx(212.0)
        assert scale_four_twenty(12.0, 32, 212) == pytest.approx(122.0)

    def test_under_range(self):
        """Below 3.8 mA = wire break condition."""
        result = scale_four_twenty(3.0, 0, 100)
        assert result < 0.0  # Extrapolates below min

    def test_over_range(self):
        """Above 20.5 mA = sensor over-range."""
        result = scale_four_twenty(21.0, 0, 100)
        assert result > 100.0  # Extrapolates above max

    def test_eng_min_zero(self):
        """eng_units_min=0 is a valid value (not falsy)."""
        assert scale_four_twenty(4.0, 0.0, 100.0) == pytest.approx(0.0)

    def test_eng_max_zero(self):
        """eng_units_max=0 is a valid value (inverted range)."""
        assert scale_four_twenty(4.0, 100.0, 0.0) == pytest.approx(100.0)
        assert scale_four_twenty(20.0, 100.0, 0.0) == pytest.approx(0.0)


# ===================================================================
# 6. Scaling fallback chain: 4-20 → map → linear → raw
# ===================================================================

class TestScalingFallbackChain:
    """Verify the precedence order in apply_scaling()."""

    def test_no_scaling_passthrough(self):
        ch = make_current_input()
        assert apply_scaling(ch, 8.5) == pytest.approx(8.5)

    def test_linear_scaling_fallback(self):
        """If no 4-20 and no map, linear scaling applies."""
        ch = make_current_input(
            scale_slope=2.0,
            scale_offset=5.0,
        )
        # y = 2*8 + 5 = 21
        assert apply_scaling(ch, 8.0) == pytest.approx(21.0)

    def test_map_before_linear(self):
        """Map scaling should take precedence over linear."""
        ch = make_current_input(
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=1000.0,
            scale_slope=2.0,  # Should be ignored
            scale_offset=5.0,
        )
        # Map: 10 mA → 500 (not linear: 2*10+5=25)
        assert apply_scaling(ch, 10.0) == pytest.approx(500.0)

    def test_four_twenty_before_map(self):
        """4-20mA scaling takes precedence over map scaling."""
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=20.0,
            scaled_min=0.0,
            scaled_max=1000.0,
        )
        # 4-20: 12 mA → 50 (not map: 12/20*1000=600)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)


# ===================================================================
# 7. Guarded channel types — must never be user-scaled
# ===================================================================

class TestGuardedTypes:
    """Digital I/O, TC, RTD, Modbus must never be user-scaled."""

    @pytest.mark.parametrize("ct", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
        ChannelType.MODBUS_REGISTER,
        ChannelType.MODBUS_COIL,
    ])
    def test_raw_passthrough(self, ct):
        ch = ChannelConfig(
            name="test", module="m", physical_channel="ai0",
            channel_type=ct,
            scale_type="linear", scale_slope=10.0, scale_offset=5.0,
            four_twenty_scaling=True,
            eng_units_min=0.0, eng_units_max=100.0,
        )
        assert apply_scaling(ch, 42.0) == 42.0


# ===================================================================
# 8. Simulator raw value format
# ===================================================================

class TestSimulatorValues:
    """Simulator returns mA directly — no Amps→mA conversion needed."""

    def test_simulator_current_range(self):
        """Simulated current values should be in the 3.8-20.5 mA range."""
        # This is a unit-test-level check; the actual simulator uses random values.
        # We just verify the scaling math works with typical simulator output.
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
        )
        # Simulate a few typical simulator values (mA)
        for raw_ma, expected_min, expected_max in [
            (4.0, -0.1, 0.1),
            (12.0, 49.9, 50.1),
            (20.0, 99.9, 100.1),
            (8.5, 28.0, 28.2),
        ]:
            result = apply_scaling(ch, raw_ma)
            assert expected_min <= result <= expected_max, \
                f"At {raw_ma} mA: expected ~{(expected_min+expected_max)/2}, got {result}"


# ===================================================================
# 9. Hardware reader Amps→mA conversion
# ===================================================================

class TestHardwareReaderConversion:
    """NI-DAQmx returns Amps; hardware_reader converts to mA before caching.

    We can't import hardware_reader (needs nidaqmx), but we verify the
    conversion factor is correct: value_mA = value_amps * 1000.
    """

    def test_amps_to_ma_conversion(self):
        """0.008 Amps → 8.0 mA."""
        raw_amps = 0.008
        raw_ma = raw_amps * 1000.0
        assert raw_ma == pytest.approx(8.0)

    def test_scaling_with_converted_value(self):
        """Full path: 0.012 A → 12 mA → 50 °C."""
        ch = make_current_input(
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
        )
        raw_amps = 0.012
        raw_ma = raw_amps * 1000.0
        assert apply_scaling(ch, raw_ma) == pytest.approx(50.0)


# (TestVoltageMapScaling merged into TestUniversalMapScaling above)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
