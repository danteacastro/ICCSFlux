"""
Scaling and Unit Conversion Tests
Validates that all scaling types work correctly.
"""

import pytest
import sys
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import ChannelConfig, ChannelType
from scaling import apply_scaling, validate_scaling_config, get_scaling_info


class TestLinearScaling:
    """Test linear scaling (y = mx + b)."""

    def test_identity_scaling(self):
        """Test no scaling (slope=1, offset=0)."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="none",
            scale_slope=1.0,
            scale_offset=0.0
        )
        assert apply_scaling(ch, 5.0) == 5.0
        assert apply_scaling(ch, 0.0) == 0.0
        assert apply_scaling(ch, -10.0) == -10.0

    def test_slope_only(self):
        """Test scaling with slope only."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=0.0
        )
        assert apply_scaling(ch, 5.0) == 10.0
        assert apply_scaling(ch, 0.0) == 0.0
        assert apply_scaling(ch, -5.0) == -10.0

    def test_offset_only(self):
        """Test scaling with offset only."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=1.0,
            scale_offset=10.0
        )
        assert apply_scaling(ch, 5.0) == 15.0
        assert apply_scaling(ch, 0.0) == 10.0
        assert apply_scaling(ch, -5.0) == 5.0

    def test_slope_and_offset(self):
        """Test scaling with both slope and offset."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=5.0
        )
        # y = 2*x + 5
        assert apply_scaling(ch, 0.0) == 5.0
        assert apply_scaling(ch, 5.0) == 15.0
        assert apply_scaling(ch, -2.5) == 0.0


class TestFourTwentyScaling:
    """Test 4-20mA scaling."""

    def test_basic_four_twenty(self):
        """Test basic 4-20mA scaling."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        # 4mA = 0, 20mA = 100
        assert apply_scaling(ch, 4.0) == pytest.approx(0.0, abs=0.1)
        assert apply_scaling(ch, 20.0) == pytest.approx(100.0, abs=0.1)
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0, abs=0.1)

    def test_four_twenty_with_offset(self):
        """Test 4-20mA scaling with non-zero minimum."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=50.0,
            eng_units_max=250.0
        )
        # 4mA = 50, 20mA = 250
        assert apply_scaling(ch, 4.0) == pytest.approx(50.0, abs=0.1)
        assert apply_scaling(ch, 20.0) == pytest.approx(250.0, abs=0.1)
        assert apply_scaling(ch, 12.0) == pytest.approx(150.0, abs=0.1)

    def test_four_twenty_below_four(self):
        """Test 4-20mA scaling below 4mA."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        # Below 4mA should extrapolate (sensor fault condition)
        result = apply_scaling(ch, 3.0)
        assert result < 0.0

    def test_four_twenty_above_twenty(self):
        """Test 4-20mA scaling above 20mA."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        # Above 20mA should extrapolate (sensor fault condition)
        result = apply_scaling(ch, 21.0)
        assert result > 100.0


class TestMapScaling:
    """Test map scaling (voltage to engineering units)."""

    def test_basic_map_scaling(self):
        """Test basic voltage to engineering units mapping."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=100.0
        )
        # 0-10V maps to 0-100
        assert apply_scaling(ch, 0.0) == pytest.approx(0.0, abs=0.1)
        assert apply_scaling(ch, 10.0) == pytest.approx(100.0, abs=0.1)
        assert apply_scaling(ch, 5.0) == pytest.approx(50.0, abs=0.1)

    def test_map_scaling_with_offset(self):
        """Test map scaling with offsets on both ends."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=1.0,
            pre_scaled_max=5.0,
            scaled_min=0.0,
            scaled_max=1000.0
        )
        # 1-5V maps to 0-1000
        assert apply_scaling(ch, 1.0) == pytest.approx(0.0, abs=0.1)
        assert apply_scaling(ch, 5.0) == pytest.approx(1000.0, abs=0.1)
        assert apply_scaling(ch, 3.0) == pytest.approx(500.0, abs=0.1)

    def test_map_scaling_negative_range(self):
        """Test map scaling with negative output range."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=-50.0,
            scaled_max=50.0
        )
        # 0-10V maps to -50 to +50
        assert apply_scaling(ch, 0.0) == pytest.approx(-50.0, abs=0.1)
        assert apply_scaling(ch, 10.0) == pytest.approx(50.0, abs=0.1)
        assert apply_scaling(ch, 5.0) == pytest.approx(0.0, abs=0.1)


class TestScalingValidation:
    """Test scaling configuration validation."""

    def test_valid_linear_scaling(self):
        """Test valid linear scaling config."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=10.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == True
        assert error is None or error == ""

    def test_valid_four_twenty_scaling(self):
        """Test valid 4-20mA scaling config."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == True

    def test_invalid_four_twenty_missing_min(self):
        """Test invalid 4-20mA scaling without eng_units_min."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=None,
            eng_units_max=100.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == False
        assert "eng_units_min" in error.lower() or "required" in error.lower()

    def test_valid_map_scaling(self):
        """Test valid map scaling config."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=100.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == True

    def test_invalid_map_missing_params(self):
        """Test invalid map scaling with missing parameters."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=None,  # Missing
            scaled_min=0.0,
            scaled_max=100.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == False


class TestScalingInfo:
    """Test scaling information retrieval."""

    def test_no_scaling_info(self):
        """Test scaling info for unscaled channel."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="none"
        )
        info = get_scaling_info(ch)
        assert info is not None
        assert info.get("type") == "none" or "none" in str(info).lower()

    def test_linear_scaling_info(self):
        """Test scaling info for linear scaling."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=10.0
        )
        info = get_scaling_info(ch)
        assert info is not None
        assert "linear" in str(info).lower()

    def test_four_twenty_scaling_info(self):
        """Test scaling info for 4-20mA scaling."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        info = get_scaling_info(ch)
        assert info is not None
        assert "4-20" in str(info) or "four_twenty" in str(info).lower()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_range_map_scaling(self):
        """Test map scaling with zero input range."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="map",
            pre_scaled_min=5.0,
            pre_scaled_max=5.0,  # Zero range
            scaled_min=0.0,
            scaled_max=100.0
        )
        # Should handle gracefully (not divide by zero)
        try:
            result = apply_scaling(ch, 5.0)
            # Either returns input or some reasonable value
            assert result is not None
        except ZeroDivisionError:
            pytest.fail("Zero range should be handled gracefully")

    def test_very_large_values(self):
        """Test scaling with very large values."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=1e6,
            scale_offset=0.0
        )
        result = apply_scaling(ch, 1000.0)
        assert result == pytest.approx(1e9, rel=0.01)

    def test_very_small_values(self):
        """Test scaling with very small values."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=1e-6,
            scale_offset=0.0
        )
        result = apply_scaling(ch, 1000.0)
        assert result == pytest.approx(1e-3, rel=0.01)

    def test_negative_slope(self):
        """Test scaling with negative slope (inverted)."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=-1.0,
            scale_offset=100.0
        )
        # y = -x + 100
        assert apply_scaling(ch, 0.0) == pytest.approx(100.0)
        assert apply_scaling(ch, 100.0) == pytest.approx(0.0)
        assert apply_scaling(ch, 50.0) == pytest.approx(50.0)


class TestScalingGuards:
    """Test that scaling is blocked on channel types that should never be scaled."""

    @pytest.mark.parametrize("channel_type", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
    ])
    def test_no_scaling_applied(self, channel_type):
        """Scaling must pass through raw value for DI/DO/TC/RTD."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=10.0
        )
        # Even with linear scaling configured, raw value should pass through
        assert apply_scaling(ch, 5.0) == 5.0
        assert apply_scaling(ch, 0.0) == 0.0
        assert apply_scaling(ch, 1.0) == 1.0

    @pytest.mark.parametrize("channel_type", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
    ])
    def test_map_scaling_blocked(self, channel_type):
        """Map scaling must not apply to DI/DO/TC/RTD."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type,
            scale_type="map",
            pre_scaled_min=0.0,
            pre_scaled_max=10.0,
            scaled_min=0.0,
            scaled_max=100.0
        )
        assert apply_scaling(ch, 5.0) == 5.0

    @pytest.mark.parametrize("channel_type", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
    ])
    def test_four_twenty_blocked_on_digital(self, channel_type):
        """4-20mA scaling must not apply to digital channels."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type,
            scale_type="none",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        assert apply_scaling(ch, 12.0) == 12.0

    @pytest.mark.parametrize("channel_type", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
    ])
    def test_validation_rejects_scaling(self, channel_type):
        """validate_scaling_config must reject scaling on guarded types."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=10.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == False
        assert "not supported" in error.lower()

    @pytest.mark.parametrize("channel_type", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
    ])
    def test_validation_accepts_no_scaling(self, channel_type):
        """validate_scaling_config must accept guarded types with no scaling."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=channel_type,
            scale_type="none",
            scale_slope=1.0,
            scale_offset=0.0
        )
        is_valid, error = validate_scaling_config(ch)
        assert is_valid == True

    def test_voltage_input_still_scales(self):
        """Voltage input should still accept scaling (not guarded)."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=5.0
        )
        assert apply_scaling(ch, 10.0) == 25.0

    def test_current_input_still_scales(self):
        """Current input should still accept 4-20mA scaling (not guarded)."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            scale_type="four_twenty",
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0
        )
        assert apply_scaling(ch, 12.0) == pytest.approx(50.0, abs=0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
