"""
Frontend Type Compatibility Tests
Validates that TypeScript types match Python backend types.
"""

import pytest
import sys
import json
import re
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import ChannelConfig, ChannelType, ThermocoupleType

class TestChannelTypeAlignment:
    """Test that Python and TypeScript channel types match."""

    @pytest.fixture
    def typescript_types(self):
        """Read TypeScript type definitions."""
        ts_path = Path(__file__).parent.parent / "dashboard" / "src" / "types" / "index.ts"
        if not ts_path.exists():
            pytest.skip("TypeScript types file not found")
        return ts_path.read_text()

    def test_channel_types_match(self, typescript_types):
        """Test that all Python ChannelType values exist in TypeScript."""
        python_types = [ct.value for ct in ChannelType]

        for ptype in python_types:
            assert f"'{ptype}'" in typescript_types, f"ChannelType '{ptype}' missing from TypeScript"

    def test_thermocouple_types_match(self, typescript_types):
        """Test that all thermocouple types exist in TypeScript."""
        python_tc_types = [tc.value for tc in ThermocoupleType]

        for tc in python_tc_types:
            assert f"'{tc}'" in typescript_types, f"ThermocoupleType '{tc}' missing from TypeScript"

class TestChannelConfigFieldAlignment:
    """Test that Python ChannelConfig fields exist in TypeScript."""

    @pytest.fixture
    def typescript_types(self):
        """Read TypeScript type definitions."""
        ts_path = Path(__file__).parent.parent / "dashboard" / "src" / "types" / "index.ts"
        if not ts_path.exists():
            pytest.skip("TypeScript types file not found")
        return ts_path.read_text()

    def test_basic_fields_exist(self, typescript_types):
        """Test that basic fields exist in TypeScript."""
        required_fields = [
            "name",
            "channel_type",
            "physical_channel",
            "unit",  # TypeScript uses 'unit', Python uses 'units'
            "group",
            "description",
            "visible"
        ]
        for field in required_fields:
            assert field in typescript_types, f"Field '{field}' missing from TypeScript interface"

    def test_scaling_fields_exist(self, typescript_types):
        """Test that scaling fields exist in TypeScript."""
        scaling_fields = [
            "scale_slope",
            "scale_offset",
            "scale_type",
            "four_twenty_scaling",
            "eng_units_min",
            "eng_units_max",
            "pre_scaled_min",
            "pre_scaled_max",
            "scaled_min",
            "scaled_max"
        ]
        for field in scaling_fields:
            assert field in typescript_types, f"Scaling field '{field}' missing from TypeScript"

    def test_thermocouple_fields_exist(self, typescript_types):
        """Test that thermocouple fields exist in TypeScript."""
        tc_fields = [
            "thermocouple_type",
            "cjc_source"
        ]
        for field in tc_fields:
            assert field in typescript_types, f"Thermocouple field '{field}' missing from TypeScript"

    def test_rtd_fields_exist(self, typescript_types):
        """Test that RTD fields exist in TypeScript."""
        rtd_fields = [
            "rtd_type",
            "rtd_resistance",
            "rtd_wiring",
            "rtd_current"
        ]
        for field in rtd_fields:
            assert field in typescript_types, f"RTD field '{field}' missing from TypeScript"

    def test_strain_fields_exist(self, typescript_types):
        """Test that strain fields exist in TypeScript."""
        strain_fields = [
            "strain_config",
            "strain_excitation_voltage",
            "strain_gage_factor",
            "strain_resistance"
        ]
        for field in strain_fields:
            assert field in typescript_types, f"Strain field '{field}' missing from TypeScript"

    def test_iepe_fields_exist(self, typescript_types):
        """Test that IEPE fields exist in TypeScript."""
        iepe_fields = [
            "iepe_sensitivity",
            "iepe_current",
            "iepe_coupling"
        ]
        for field in iepe_fields:
            assert field in typescript_types, f"IEPE field '{field}' missing from TypeScript"

    def test_resistance_fields_exist(self, typescript_types):
        """Test that resistance fields exist in TypeScript."""
        resistance_fields = [
            "resistance_range",
            "resistance_wiring"
        ]
        for field in resistance_fields:
            assert field in typescript_types, f"Resistance field '{field}' missing from TypeScript"

    def test_counter_fields_exist(self, typescript_types):
        """Test that counter fields exist in TypeScript."""
        counter_fields = [
            "counter_mode",
            "counter_edge",
            "pulses_per_unit",
            "counter_reset_on_read",
            "counter_min_freq",
            "counter_max_freq"
        ]
        for field in counter_fields:
            assert field in typescript_types, f"Counter field '{field}' missing from TypeScript"

    def test_terminal_config_exists(self, typescript_types):
        """Test that terminal_config exists in TypeScript."""
        assert "terminal_config" in typescript_types, "terminal_config missing from TypeScript"

    def test_limit_fields_exist(self, typescript_types):
        """Test that limit fields exist in TypeScript."""
        limit_fields = [
            "low_limit",
            "high_limit",
            "low_warning",
            "high_warning"
        ]
        for field in limit_fields:
            assert field in typescript_types, f"Limit field '{field}' missing from TypeScript"

    def test_safety_fields_exist(self, typescript_types):
        """Test that safety fields exist in TypeScript."""
        safety_fields = [
            "safety_action",
            "safety_interlock"
        ]
        for field in safety_fields:
            assert field in typescript_types, f"Safety field '{field}' missing from TypeScript"

    def test_logging_fields_exist(self, typescript_types):
        """Test that logging fields exist in TypeScript."""
        log_fields = [
            "log",
            "log_interval_ms"
        ]
        for field in log_fields:
            assert field in typescript_types, f"Logging field '{field}' missing from TypeScript"

    def test_digital_io_fields_exist(self, typescript_types):
        """Test that digital I/O fields exist in TypeScript."""
        dio_fields = [
            "invert",
            "default_value",
            "default_state"
        ]
        for field in dio_fields:
            assert field in typescript_types, f"Digital I/O field '{field}' missing from TypeScript"

class TestJSONSerialization:
    """Test that channel configs can be serialized to JSON for frontend."""

    def test_channel_config_to_dict(self):
        """Test converting ChannelConfig to dictionary."""
        ch = ChannelConfig(
            name="test_channel",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            description="Test voltage channel",
            units="V",
            scale_type="linear",
            scale_slope=2.0,
            scale_offset=10.0,
            low_limit=0.0,
            high_limit=100.0
        )

        # Convert to dict (dataclass has __dict__)
        data = {
            "name": ch.name,
            "module": ch.module,
            "physical_channel": ch.physical_channel,
            "channel_type": ch.channel_type.value,
            "description": ch.description,
            "units": ch.units,
            "scale_type": ch.scale_type,
            "scale_slope": ch.scale_slope,
            "scale_offset": ch.scale_offset,
            "low_limit": ch.low_limit,
            "high_limit": ch.high_limit
        }

        # Should be JSON serializable
        json_str = json.dumps(data)
        assert json_str is not None

        # Should roundtrip correctly
        parsed = json.loads(json_str)
        assert parsed["name"] == "test_channel"
        assert parsed["channel_type"] == "voltage_input"
        assert parsed["scale_slope"] == 2.0

    def test_thermocouple_type_serialization(self):
        """Test thermocouple type can be serialized."""
        ch = ChannelConfig(
            name="temp",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.THERMOCOUPLE,
            thermocouple_type=ThermocoupleType.K
        )

        data = {
            "thermocouple_type": ch.thermocouple_type.value if ch.thermocouple_type else None
        }

        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["thermocouple_type"] == "K"

    def test_null_handling(self):
        """Test None values serialize to null."""
        ch = ChannelConfig(
            name="test",
            module="mod1",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            low_limit=None,
            high_limit=None
        )

        data = {
            "low_limit": ch.low_limit,
            "high_limit": ch.high_limit
        }

        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["low_limit"] is None
        assert parsed["high_limit"] is None

class TestFrontendConfigMessages:
    """Test that config messages match expected frontend format."""

    def test_channel_config_message_format(self):
        """Test the format of channel config messages."""
        ch = ChannelConfig(
            name="temp_1",
            module="temp_module",
            physical_channel="ai0",
            channel_type=ChannelType.THERMOCOUPLE,
            description="Zone 1 Temperature",
            units="C",
            thermocouple_type=ThermocoupleType.K,
            low_limit=0.0,
            high_limit=500.0,
            visible=True,
            group="Temperatures"
        )

        # Build message similar to what daq_service sends
        msg = {
            "name": ch.name,
            "display_name": ch.name,  # Frontend expects this
            "channel_type": ch.channel_type.value,
            "physical_channel": ch.physical_channel,
            "unit": ch.units,  # Frontend uses 'unit', not 'units'
            "group": ch.group,
            "description": ch.description,
            "low_limit": ch.low_limit,
            "high_limit": ch.high_limit,
            "visible": ch.visible,
            "thermocouple_type": ch.thermocouple_type.value if ch.thermocouple_type else None
        }

        # Validate required fields for frontend
        assert "name" in msg
        assert "channel_type" in msg
        assert "unit" in msg or "units" in msg
        assert msg["channel_type"] == "thermocouple"

    def test_channel_value_message_format(self):
        """Test the format of channel value messages."""
        value_msg = {
            "name": "temp_1",
            "value": 25.5,
            "raw_value": 0.0012,  # For scaled channels
            "timestamp": 1704067200.123,
            "alarm": False,
            "warning": False
        }

        # Should be JSON serializable
        json_str = json.dumps(value_msg)
        parsed = json.loads(json_str)

        assert parsed["name"] == "temp_1"
        assert parsed["value"] == 25.5
        assert isinstance(parsed["timestamp"], float)

class TestScaleTypeValues:
    """Test that scale_type values match between frontend and backend."""

    @pytest.fixture
    def typescript_types(self):
        """Read TypeScript type definitions."""
        ts_path = Path(__file__).parent.parent / "dashboard" / "src" / "types" / "index.ts"
        if not ts_path.exists():
            pytest.skip("TypeScript types file not found")
        return ts_path.read_text()

    def test_scale_type_values(self, typescript_types):
        """Test that scale_type values match."""
        backend_scale_types = ["none", "linear", "map", "four_twenty"]

        for scale_type in backend_scale_types:
            assert f"'{scale_type}'" in typescript_types, f"scale_type '{scale_type}' missing from TypeScript"

class TestTerminalConfigValues:
    """Test that terminal_config values match between frontend and backend."""

    @pytest.fixture
    def typescript_types(self):
        """Read TypeScript type definitions."""
        ts_path = Path(__file__).parent.parent / "dashboard" / "src" / "types" / "index.ts"
        if not ts_path.exists():
            pytest.skip("TypeScript types file not found")
        return ts_path.read_text()

    def test_terminal_config_values(self, typescript_types):
        """Test that terminal_config values are present."""
        # Backend accepts these (case-insensitive)
        terminal_configs = ["rse", "diff", "nrse", "pseudo_diff", "RSE", "DIFF", "NRSE", "PSEUDO_DIFF"]

        # At least some should be in TypeScript
        found = any(tc.lower() in typescript_types.lower() for tc in terminal_configs)
        assert found, "No terminal_config values found in TypeScript"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
