"""
Industrial Math & Scaling Test Suite

Comprehensive verification that real-world sensor scenarios produce correct
readings. Built to catch the kinds of math bugs that cause "weird numbers
on Monday morning" — off-by-one errors, sign mistakes, floating-point
precision issues, inverted ranges, etc.

Categories:
  1. Pressure transmitters (4-20mA → PSI/bar/kPa)
  2. Temperature sensors (TC, RTD, voltage divider)
  3. Flow measurement (counter pulses → GPM)
  4. Level measurement (0-10V → 0-100%, ultrasonic)
  5. Setpoint output (engineering → mA write, reverse scaling)
  6. Symmetric round-trip (raw → scaled → raw lossless)
  7. Floating-point precision (very small/large values)
  8. Boundary conditions (exactly at min/max, just outside)
  9. Inverted/negative ranges (vacuum, reverse-acting)
 10. Narrow-span precision (e.g., 24.95-25.05 for tight control)
 11. Wide-span dynamic range (0 to 1e6 totalizers)
 12. Mixed sign ranges (-50 to +50 differential pressure)
"""

import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import ChannelConfig, ChannelType
from scaling import (
    apply_scaling, scale_four_twenty, scale_map, scale_linear, scale_counter,
    reverse_scaling, validate_and_clamp, is_valid_value,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_4_20_channel(eng_min, eng_max, units="psi"):
    """Standard 4-20mA pressure/level/flow transmitter."""
    return ChannelConfig(
        name="xmtr",
        module="cDAQ1Mod1",
        physical_channel="cDAQ1Mod1/ai0",
        channel_type=ChannelType.CURRENT_INPUT,
        current_range_ma=20.0,
        terminal_config="differential",
        scale_type="map",
        pre_scaled_min=4.0,
        pre_scaled_max=20.0,
        scaled_min=eng_min,
        scaled_max=eng_max,
        units=units,
    )


def make_voltage_map_channel(v_min, v_max, eng_min, eng_max, units=""):
    """Voltage divider with linear map scaling."""
    return ChannelConfig(
        name="vsensor",
        module="cDAQ1Mod1",
        physical_channel="cDAQ1Mod1/ai0",
        channel_type=ChannelType.VOLTAGE_INPUT,
        voltage_range=10.0,
        scale_type="map",
        pre_scaled_min=v_min,
        pre_scaled_max=v_max,
        scaled_min=eng_min,
        scaled_max=eng_max,
        units=units,
    )


def make_linear_channel(slope, offset, ct=ChannelType.VOLTAGE_INPUT):
    """Linear y = mx + b scaling."""
    return ChannelConfig(
        name="lin",
        module="cDAQ1Mod1",
        physical_channel="cDAQ1Mod1/ai0",
        channel_type=ct,
        scale_type="linear",
        scale_slope=slope,
        scale_offset=offset,
    )


def make_counter_channel(pulses_per_unit, mode="frequency"):
    return ChannelConfig(
        name="ctr",
        module="cDAQ1Mod1",
        physical_channel="cDAQ1Mod1/ctr0",
        channel_type=ChannelType.COUNTER,
        pulses_per_unit=pulses_per_unit,
        counter_mode=mode,
    )


# ===================================================================
# 1. Pressure Transmitters — the most common 4-20mA application
# ===================================================================

class TestPressureTransmitters:
    """Real-world pressure transmitter scenarios."""

    def test_0_100_psi_transmitter(self):
        ch = make_4_20_channel(0, 100, "psi")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 8.0) == pytest.approx(25.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 16.0) == pytest.approx(75.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(100.0)

    def test_0_500_psi_transmitter(self):
        ch = make_4_20_channel(0, 500, "psi")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(250.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(500.0)

    def test_0_1000_psi_transmitter(self):
        ch = make_4_20_channel(0, 1000, "psi")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(500.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(1000.0)

    def test_15_psi_atmospheric_zero(self):
        """Absolute pressure: 4mA = 0 PSIA, 20mA = 50 PSIA, atmospheric = 14.7"""
        ch = make_4_20_channel(0, 50, "psia")
        # Find the mA value for 14.7 PSIA
        # 14.7 = 0 + ((mA - 4)/16) * 50 → mA = 4 + 14.7/50 * 16 = 8.704
        result = apply_scaling(ch, 8.704)
        assert result == pytest.approx(14.7, abs=0.01)

    def test_vacuum_transmitter_negative_range(self):
        """Vacuum transmitter: -14.7 to 0 PSIG"""
        ch = make_4_20_channel(-14.7, 0, "psig")
        assert apply_scaling(ch, 4.0) == pytest.approx(-14.7)
        assert apply_scaling(ch, 12.0) == pytest.approx(-7.35)
        assert apply_scaling(ch, 20.0) == pytest.approx(0.0)

    def test_compound_gauge(self):
        """Compound gauge: -15 to +30 PSI (vacuum + positive pressure)"""
        ch = make_4_20_channel(-15, 30, "psi")
        assert apply_scaling(ch, 4.0) == pytest.approx(-15.0)
        # Atmospheric (0 PSIG) at: 4 + (15/45)*16 = 9.333 mA
        assert apply_scaling(ch, 9.333) == pytest.approx(0.0, abs=0.01)
        assert apply_scaling(ch, 20.0) == pytest.approx(30.0)

    def test_differential_pressure_transmitter(self):
        """DP transmitter: -50 to +50 inH2O (bidirectional flow)"""
        ch = make_4_20_channel(-50, 50, "inH2O")
        assert apply_scaling(ch, 4.0) == pytest.approx(-50.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(0.0)  # zero flow at midpoint
        assert apply_scaling(ch, 20.0) == pytest.approx(50.0)

    def test_high_pressure_5000_psi(self):
        """High-pressure transmitter: 0-5000 PSI"""
        ch = make_4_20_channel(0, 5000, "psi")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(2500.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(5000.0)

    def test_metric_units_bar(self):
        """Pressure in bar: 0-10 bar"""
        ch = make_4_20_channel(0, 10, "bar")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(10.0)
        # 1 bar = 14.5 PSI, so this is a 0-145 PSI sensor

    def test_metric_units_kpa(self):
        """Pressure in kPa: 0-1000 kPa"""
        ch = make_4_20_channel(0, 1000, "kPa")
        assert apply_scaling(ch, 12.0) == pytest.approx(500.0)


# ===================================================================
# 2. Temperature Sensors
# ===================================================================

class TestTemperatureScaling:

    def test_4_20ma_to_celsius(self):
        """4-20mA temperature transmitter: 0-100°C"""
        ch = make_4_20_channel(0, 100, "C")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(100.0)

    def test_4_20ma_to_fahrenheit(self):
        """4-20mA temperature transmitter: 32-212°F (water freeze to boil)"""
        ch = make_4_20_channel(32, 212, "F")
        assert apply_scaling(ch, 4.0) == pytest.approx(32.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(122.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(212.0)

    def test_4_20ma_high_temp_furnace(self):
        """High-temp furnace: 0-1500°C"""
        ch = make_4_20_channel(0, 1500, "C")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(750.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(1500.0)

    def test_4_20ma_cryogenic(self):
        """Cryogenic transmitter: -200 to 0 °C (LN2 to ice)"""
        ch = make_4_20_channel(-200, 0, "C")
        assert apply_scaling(ch, 4.0) == pytest.approx(-200.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(-100.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(0.0)

    def test_thermocouple_passes_through(self):
        """TC channels return engineering units directly from NI-DAQmx — no scaling."""
        ch = ChannelConfig(
            name="tc",
            module="cDAQ1Mod1",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.THERMOCOUPLE,
        )
        # Even if scale_type='linear', TC channels pass through (guarded)
        assert apply_scaling(ch, 25.0) == 25.0
        assert apply_scaling(ch, 1000.0) == 1000.0

    def test_rtd_passes_through(self):
        ch = ChannelConfig(
            name="rtd",
            module="cDAQ1Mod1",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.RTD,
        )
        assert apply_scaling(ch, 25.0) == 25.0
        assert apply_scaling(ch, -40.0) == -40.0


# ===================================================================
# 3. Flow Measurement (Counter/Pulse)
# ===================================================================

class TestFlowMeasurement:

    def test_simple_pulse_counter(self):
        """100 pulses per gallon, reading 5 GPS = 500 Hz"""
        ch = make_counter_channel(100.0, mode="frequency")
        # 500 Hz / 100 pulses-per-gal = 5 GPS
        assert apply_scaling(ch, 500.0) == pytest.approx(5.0)

    def test_high_resolution_flow_meter(self):
        """1000 pulses per gallon (high-res turbine meter)"""
        ch = make_counter_channel(1000.0, mode="frequency")
        # 100 Hz / 1000 = 0.1 GPS
        assert apply_scaling(ch, 100.0) == pytest.approx(0.1)

    def test_paddlewheel_low_resolution(self):
        """5 pulses per gallon (low-res paddlewheel)"""
        ch = make_counter_channel(5.0, mode="frequency")
        # 50 Hz / 5 = 10 GPS
        assert apply_scaling(ch, 50.0) == pytest.approx(10.0)

    def test_count_mode_totalizer(self):
        """Totalizer mode: 1500 pulses at 100 ppg = 15 gallons"""
        ch = make_counter_channel(100.0, mode="count")
        assert apply_scaling(ch, 1500.0) == pytest.approx(15.0)

    def test_period_mode(self):
        """Period mode: period in seconds → frequency → engineering units"""
        ch = make_counter_channel(100.0, mode="period")
        # period=0.01s → frequency=100Hz → 100/100 = 1.0 GPS
        assert apply_scaling(ch, 0.01) == pytest.approx(1.0)

    def test_zero_pulses_per_unit_safe(self):
        """Zero pulses_per_unit must not cause divide-by-zero."""
        ch = make_counter_channel(0.0, mode="frequency")
        assert apply_scaling(ch, 1000.0) == 0.0

    def test_period_zero_safe(self):
        """Period of zero must not cause divide-by-zero."""
        ch = make_counter_channel(100.0, mode="period")
        assert apply_scaling(ch, 0.0) == 0.0


# ===================================================================
# 4. Level Measurement (Voltage divider, ultrasonic)
# ===================================================================

class TestLevelMeasurement:

    def test_0_10v_to_0_100_percent(self):
        """Voltage divider: 0-10V → 0-100% tank level"""
        ch = make_voltage_map_channel(0, 10, 0, 100, "%")
        assert apply_scaling(ch, 0.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 5.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 10.0) == pytest.approx(100.0)

    def test_0_5v_to_0_100_percent(self):
        """3.3V/5V system: 0-5V → 0-100%"""
        ch = make_voltage_map_channel(0, 5, 0, 100, "%")
        assert apply_scaling(ch, 0.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 2.5) == pytest.approx(50.0)
        assert apply_scaling(ch, 5.0) == pytest.approx(100.0)

    def test_1_5v_offset(self):
        """1-5V transmitter (live-zero): 1V = 0%, 5V = 100%"""
        ch = make_voltage_map_channel(1.0, 5.0, 0, 100, "%")
        assert apply_scaling(ch, 1.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 3.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 5.0) == pytest.approx(100.0)

    def test_ultrasonic_4_20ma_to_feet(self):
        """Ultrasonic level: 4mA = 0 ft, 20mA = 30 ft"""
        ch = make_4_20_channel(0, 30, "ft")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(15.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(30.0)

    def test_inverted_radar_level(self):
        """Inverted radar (mounted at bottom): 4mA = 100%, 20mA = 0%"""
        ch = make_4_20_channel(100, 0, "%")
        assert apply_scaling(ch, 4.0) == pytest.approx(100.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(0.0)


# ===================================================================
# 5. Setpoint / Output Reverse Scaling
# ===================================================================

class TestReverseScaling:
    """Engineering setpoint → raw mA/V for output channels."""

    def test_4_20ma_reverse_simple(self):
        """50 PSI on a 0-100 PSI scale → 12 mA output"""
        ch = make_4_20_channel(0, 100, "psi")
        assert reverse_scaling(ch, 50.0) == pytest.approx(12.0)
        assert reverse_scaling(ch, 0.0) == pytest.approx(4.0)
        assert reverse_scaling(ch, 100.0) == pytest.approx(20.0)

    def test_4_20ma_reverse_offset(self):
        """100°F on 32-212°F scale → 10.04 mA"""
        ch = make_4_20_channel(32, 212, "F")
        # 100°F: (100-32)/(212-32) * 16 + 4 = 68/180*16 + 4 = 6.044 + 4 = 10.044
        assert reverse_scaling(ch, 100.0) == pytest.approx(10.044, abs=0.01)

    def test_map_reverse_linear(self):
        """0-10V → 0-500 RPM scaled, 250 RPM → 5V output"""
        ch = make_voltage_map_channel(0, 10, 0, 500, "rpm")
        assert reverse_scaling(ch, 250.0) == pytest.approx(5.0)
        assert reverse_scaling(ch, 0.0) == pytest.approx(0.0)
        assert reverse_scaling(ch, 500.0) == pytest.approx(10.0)

    def test_linear_reverse(self):
        """y = 2x + 5 → reverse: x = (y - 5) / 2"""
        ch = make_linear_channel(2.0, 5.0)
        # y=15 → x=5
        assert reverse_scaling(ch, 15.0) == pytest.approx(5.0)
        # y=5 → x=0
        assert reverse_scaling(ch, 5.0) == pytest.approx(0.0)

    def test_zero_slope_reverse_safe(self):
        """Zero slope should not cause divide-by-zero in reverse."""
        ch = make_linear_channel(0.0, 5.0)
        result = reverse_scaling(ch, 10.0)
        # Returns eng_value when slope is 0 (safe behavior)
        assert result == 10.0


# ===================================================================
# 6. Symmetric Round-Trip — raw → scaled → raw must be lossless
# ===================================================================

class TestRoundTrip:
    """Round-trip verification: scale and reverse-scale should preserve value."""

    @pytest.mark.parametrize("ma", [4.0, 8.0, 12.0, 16.0, 20.0, 6.5, 13.7, 18.234])
    def test_4_20_round_trip(self, ma):
        ch = make_4_20_channel(0, 100, "psi")
        eng = apply_scaling(ch, ma)
        ma_back = reverse_scaling(ch, eng)
        assert ma_back == pytest.approx(ma, abs=1e-6)

    @pytest.mark.parametrize("v", [0.0, 2.5, 5.0, 7.5, 10.0, 3.14159, 7.777])
    def test_voltage_map_round_trip(self, v):
        ch = make_voltage_map_channel(0, 10, 0, 500, "rpm")
        eng = apply_scaling(ch, v)
        v_back = reverse_scaling(ch, eng)
        assert v_back == pytest.approx(v, abs=1e-6)

    @pytest.mark.parametrize("v", [-10.0, -5.0, 0.0, 5.0, 10.0, 1e-3, 1e-6])
    def test_linear_round_trip(self, v):
        ch = make_linear_channel(3.7, -2.3)
        scaled = apply_scaling(ch, v)
        v_back = reverse_scaling(ch, scaled)
        assert v_back == pytest.approx(v, rel=1e-9, abs=1e-9)

    def test_round_trip_inverted_range(self):
        """Round-trip works even with inverted ranges (4mA=100, 20mA=0)."""
        ch = make_4_20_channel(100, 0, "%")
        for ma in [4.0, 8.0, 12.0, 16.0, 20.0]:
            eng = apply_scaling(ch, ma)
            ma_back = reverse_scaling(ch, eng)
            assert ma_back == pytest.approx(ma, abs=1e-6)


# ===================================================================
# 7. Floating Point Precision
# ===================================================================

class TestFloatingPointPrecision:

    def test_very_small_engineering_range(self):
        """Tight precision: 24.95 - 25.05 °C (0.1° span)"""
        ch = make_4_20_channel(24.95, 25.05, "C")
        assert apply_scaling(ch, 4.0) == pytest.approx(24.95)
        assert apply_scaling(ch, 12.0) == pytest.approx(25.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(25.05)

    def test_very_large_engineering_range(self):
        """Wide range: 0 to 1e6 (totalizer style)"""
        ch = make_4_20_channel(0, 1e6, "gal")
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 12.0) == pytest.approx(500000.0)
        assert apply_scaling(ch, 20.0) == pytest.approx(1e6)

    def test_extreme_dynamic_range(self):
        """Range 0 to 1e9"""
        ch = make_4_20_channel(0, 1e9, "")
        assert apply_scaling(ch, 12.0) == pytest.approx(5e8)

    def test_micro_strain(self):
        """Micro-strain: linear scaling with very small slope"""
        ch = make_linear_channel(1e-6, 0.0)
        # 1V input → 1e-6 strain
        assert apply_scaling(ch, 1.0) == pytest.approx(1e-6)

    def test_precision_at_midpoint(self):
        """Half-mA increments should give exact half-percentage results."""
        ch = make_4_20_channel(0, 100, "%")
        for half in range(8, 41):  # 4.0 to 20.0 in 0.5 steps
            ma = half / 2.0
            expected = (ma - 4.0) / 16.0 * 100.0
            assert apply_scaling(ch, ma) == pytest.approx(expected, abs=1e-9)

    def test_no_floating_point_drift_repeated(self):
        """Apply scaling 10000 times — should be pure function, no drift."""
        ch = make_4_20_channel(0, 100, "psi")
        results = [apply_scaling(ch, 12.0) for _ in range(10000)]
        # All identical — no state, no drift
        assert all(r == results[0] for r in results)


# ===================================================================
# 8. Boundary Conditions
# ===================================================================

class TestBoundaryConditions:

    def test_exactly_at_4ma(self):
        ch = make_4_20_channel(0, 100, "psi")
        assert apply_scaling(ch, 4.0) == 0.0

    def test_exactly_at_20ma(self):
        ch = make_4_20_channel(0, 100, "psi")
        assert apply_scaling(ch, 20.0) == 100.0

    def test_just_under_4ma_normal_range(self):
        """3.85 mA is within normal allowance (3.8-20.5)."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, 3.85)
        # Just slightly negative
        assert -1.0 < result < 0.0

    def test_under_3_8ma_extrapolates(self):
        """Below 3.8 mA = wire break; extrapolates negative."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, 3.0)
        # Significantly negative — wire break indicator
        assert result < -5.0

    def test_just_over_20ma_normal(self):
        """20.4 mA is within normal allowance (3.8-20.5)."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, 20.4)
        # Just slightly over 100
        assert 100.0 < result < 105.0

    def test_over_20_5ma_extrapolates(self):
        """Above 20.5 mA = sensor over-range."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, 21.0)
        assert result > 100.0

    def test_zero_ma(self):
        """0 mA = wire break; large negative number."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, 0.0)
        assert result < -20.0  # Definitely indicates fault


# ===================================================================
# 9. Edge Cases & Defensive Coding
# ===================================================================

class TestEdgeCases:

    def test_zero_span_map_safe(self):
        """pre_scaled_min == pre_scaled_max — must not divide by zero."""
        ch = make_voltage_map_channel(5.0, 5.0, 0, 100, "%")
        result = apply_scaling(ch, 5.0)
        assert result is not None
        assert not math.isnan(result)
        assert not math.isinf(result)

    def test_zero_span_4_20_safe(self):
        """eng_min == eng_max in 4-20mA scaling."""
        ch = ChannelConfig(
            name="x",
            module="m",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            four_twenty_scaling=True,
            eng_units_min=50.0,
            eng_units_max=50.0,
        )
        result = scale_four_twenty(12.0, 50.0, 50.0)
        assert result == 50.0  # Constant output for zero span

    def test_negative_voltage_inputs(self):
        """Bipolar voltage measurements: -10V to +10V"""
        ch = make_voltage_map_channel(-10, 10, -100, 100, "")
        assert apply_scaling(ch, -10.0) == pytest.approx(-100.0)
        assert apply_scaling(ch, 0.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 10.0) == pytest.approx(100.0)

    def test_nan_input_pass_through(self):
        """NaN inputs should not crash scaling (already NaN-validated upstream)."""
        ch = make_4_20_channel(0, 100, "psi")
        result = apply_scaling(ch, float('nan'))
        assert math.isnan(result)

    def test_inf_handling(self):
        """validate_and_clamp catches infinities."""
        val, status = validate_and_clamp(float('inf'))
        assert status == 'inf'
        assert math.isnan(val)

    def test_very_small_pre_scaled_diff(self):
        """Pre-scaled range smaller than floating-point precision threshold."""
        ch = make_voltage_map_channel(1.0, 1.0000001, 0, 100, "")
        # Should not crash; result depends on input
        result = apply_scaling(ch, 1.00000005)
        assert result is not None
        assert not math.isnan(result)


# ===================================================================
# 10. Real-World Transmitter Scenarios (Mike's worksite)
# ===================================================================

class TestRealWorldScenarios:
    """Concrete sensor/transmitter combinations from typical industrial sites."""

    def test_steam_pressure_transmitter(self):
        """Steam line: 0-300 PSI, monitoring at 12 mA"""
        ch = make_4_20_channel(0, 300, "psi")
        # 150 PSI at 12 mA
        assert apply_scaling(ch, 12.0) == pytest.approx(150.0)

    def test_chiller_temperature_loop(self):
        """Chilled water: 30-65°F, 4-20mA"""
        ch = make_4_20_channel(30, 65, "F")
        # Setpoint 45°F at: (45-30)/35 * 16 + 4 = 10.857 mA
        assert apply_scaling(ch, 10.857) == pytest.approx(45.0, abs=0.01)

    def test_boiler_drum_level(self):
        """Boiler drum level: -12 to +12 inches (centered)"""
        ch = make_4_20_channel(-12, 12, "in")
        assert apply_scaling(ch, 12.0) == pytest.approx(0.0)  # midpoint = 0

    def test_furnace_flue_temperature(self):
        """Flue gas: 0-2000°F"""
        ch = make_4_20_channel(0, 2000, "F")
        assert apply_scaling(ch, 16.0) == pytest.approx(1500.0)

    def test_stack_oxygen_analyzer(self):
        """O2 analyzer: 0-25%"""
        ch = make_4_20_channel(0, 25, "%")
        assert apply_scaling(ch, 8.32) == pytest.approx(6.75, abs=0.01)

    def test_compressor_discharge_temp(self):
        """Discharge temp: 0-400°F"""
        ch = make_4_20_channel(0, 400, "F")
        assert apply_scaling(ch, 12.0) == pytest.approx(200.0)

    def test_pump_motor_current_4_20(self):
        """Motor current transmitter: 0-50A (CT secondary)"""
        ch = make_4_20_channel(0, 50, "A")
        assert apply_scaling(ch, 12.0) == pytest.approx(25.0)

    def test_wind_speed_anemometer(self):
        """Anemometer pulse output: 1 pulse per 1 mph"""
        ch = make_counter_channel(1.0, mode="frequency")
        assert apply_scaling(ch, 25.0) == pytest.approx(25.0)  # 25 Hz = 25 mph


# ===================================================================
# 11. Setpoint Output Loops (Reverse scaling for AOs)
# ===================================================================

class TestSetpointOutputLoops:
    """Common output loops where engineering setpoint → mA write."""

    def test_valve_position_command(self):
        """Valve: 0-100% position → 4-20mA"""
        ch = make_4_20_channel(0, 100, "%")
        # Operator sets 75% → output 16 mA
        assert reverse_scaling(ch, 75.0) == pytest.approx(16.0)
        assert reverse_scaling(ch, 25.0) == pytest.approx(8.0)

    def test_vfd_speed_command(self):
        """VFD speed: 0-1800 RPM → 4-20mA"""
        ch = make_4_20_channel(0, 1800, "rpm")
        # Setpoint 900 RPM → 12 mA
        assert reverse_scaling(ch, 900.0) == pytest.approx(12.0)

    def test_pid_output_temperature(self):
        """PID output controlling 0-150°F via 4-20mA"""
        ch = make_4_20_channel(0, 150, "F")
        # Setpoint 75°F → 12 mA
        assert reverse_scaling(ch, 75.0) == pytest.approx(12.0)


# ===================================================================
# 12. Output Channels Pass Through (No Scaling Applied)
# ===================================================================

class TestOutputChannelsPassThrough:
    """Output channels store engineering units directly — backend should
    not apply scaling to them on the read path (only on the write path
    via reverse_scaling)."""

    def test_voltage_output_passthrough(self):
        ch = ChannelConfig(
            name="vo",
            module="m",
            physical_channel="ao0",
            channel_type=ChannelType.VOLTAGE_OUTPUT,
            scale_type="map",
            pre_scaled_min=0,
            pre_scaled_max=10,
            scaled_min=0,
            scaled_max=100,
        )
        # Output channels in the read pipeline: scaling DOES apply
        # because we want to display the engineering value.
        # (This documents current behavior.)
        result = apply_scaling(ch, 5.0)
        assert result == pytest.approx(50.0)


# ===================================================================
# 13. Linear Scaling Variations
# ===================================================================

class TestLinearScalingVariations:

    def test_thermocouple_extension(self):
        """Custom voltage→temp linear: y = 100x - 50"""
        ch = make_linear_channel(100.0, -50.0)
        assert apply_scaling(ch, 0.5) == pytest.approx(0.0)
        assert apply_scaling(ch, 1.0) == pytest.approx(50.0)

    def test_negative_slope(self):
        """Inverted sensor: y = -10x + 100"""
        ch = make_linear_channel(-10.0, 100.0)
        assert apply_scaling(ch, 0.0) == pytest.approx(100.0)
        assert apply_scaling(ch, 5.0) == pytest.approx(50.0)
        assert apply_scaling(ch, 10.0) == pytest.approx(0.0)

    def test_unity_pass_through(self):
        """y = 1*x + 0 = pass through"""
        ch = make_linear_channel(1.0, 0.0)
        # Note: defaults trigger no-scaling path, so check explicitly
        # When slope=1 AND offset=0, scaling is skipped (raw passes through)
        assert apply_scaling(ch, 42.0) == 42.0

    def test_constant_offset_only(self):
        """y = 1*x + 273.15 (Kelvin → no, this is offset only)"""
        ch = make_linear_channel(1.0, 273.15)
        assert apply_scaling(ch, 25.0) == pytest.approx(298.15)

    def test_voltage_to_amps_via_shunt(self):
        """Voltage across shunt → amps. 0.1Ω shunt: V * 10 = A"""
        ch = make_linear_channel(10.0, 0.0)
        assert apply_scaling(ch, 1.5) == pytest.approx(15.0)


# ===================================================================
# 14. Comprehensive Cross-Range Integrity
# ===================================================================

class TestComprehensiveCrossRange:
    """Sweep through a range of inputs to verify monotonicity, continuity,
    and correct boundary behavior."""

    def test_monotonic_4_20_increasing(self):
        """4-20mA scaling must be monotonically increasing (for normal range)."""
        ch = make_4_20_channel(0, 100, "%")
        prev = None
        for ma_x10 in range(40, 201):  # 4.0 to 20.0 in 0.1 steps
            ma = ma_x10 / 10.0
            val = apply_scaling(ch, ma)
            if prev is not None:
                assert val >= prev, f"Monotonicity violated at {ma}mA"
            prev = val

    def test_monotonic_4_20_decreasing(self):
        """Inverted range: 4-20mA mapping to 100-0 must be monotonically decreasing."""
        ch = make_4_20_channel(100, 0, "%")
        prev = None
        for ma_x10 in range(40, 201):
            ma = ma_x10 / 10.0
            val = apply_scaling(ch, ma)
            if prev is not None:
                assert val <= prev, f"Inverted monotonicity violated at {ma}mA"
            prev = val

    def test_linearity_4_20(self):
        """4-20mA scaling must be linear: equal mA steps = equal eng steps."""
        ch = make_4_20_channel(0, 100, "%")
        diffs = []
        for ma in [4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]:
            diffs.append(apply_scaling(ch, ma))
        # Each step should be identical (12.5)
        step_diffs = [diffs[i+1] - diffs[i] for i in range(len(diffs)-1)]
        for d in step_diffs:
            assert d == pytest.approx(step_diffs[0], abs=1e-9)


# ===================================================================
# 15. Validation & Quality
# ===================================================================

class TestValidation:

    def test_clamp_high(self):
        val, status = validate_and_clamp(1e16, max_valid=1e10)
        assert status == 'clamped_high'
        assert val == 1e10

    def test_clamp_low(self):
        val, status = validate_and_clamp(-1e16, min_valid=-1e10)
        assert status == 'clamped_low'
        assert val == -1e10

    def test_valid_normal(self):
        val, status = validate_and_clamp(42.0)
        assert val == 42.0
        assert status == 'good'

    def test_zero_is_valid(self):
        val, status = validate_and_clamp(0.0)
        assert val == 0.0
        assert status == 'good'

    def test_open_thermocouple_detected(self):
        """NI returns ~1e308 for open TC."""
        val, status = validate_and_clamp(1e305)
        assert status == 'open_tc'
        assert math.isnan(val)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
