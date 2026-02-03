"""
Tests for cRIO Node V2 channel_types.py

Covers:
- ChannelType enum classification (is_input, is_output, is_analog, needs_thermocouple_type)
- get_internal_type() for all semantic types + legacy aliases
- MODULE_TYPE_MAP exhaustive coverage (all 66 entries)
- get_module_channel_type() format handling (plain number, "NI 9213", "NI-9213")
- get_relay_type() for relay, SSR, and non-relay modules
- RELAY_MODULES data integrity
- Cross-map parity: MODULE_TYPE_MAP vs NI_MODULE_DATABASE

Run with: pytest tests/test_channel_types.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from crio_node_v2.channel_types import (
    ChannelType, MODULE_TYPE_MAP, RELAY_MODULES,
    get_module_channel_type, get_relay_type,
)


# ---------------------------------------------------------------------------
# 1. ChannelType.is_input()
# ---------------------------------------------------------------------------

class TestIsInput:
    """Test ChannelType.is_input() for all channel types."""

    @pytest.mark.parametrize("channel_type", [
        "voltage_input", "current_input", "thermocouple", "rtd",
        "strain_input", "bridge_input", "iepe_input", "resistance_input",
        "digital_input", "counter_input", "frequency_input",
        "modbus_register", "modbus_coil",
    ])
    def test_input_types_return_true(self, channel_type):
        assert ChannelType.is_input(channel_type) is True

    @pytest.mark.parametrize("legacy_alias", [
        "analog_input", "voltage", "current", "strain", "iepe",
        "counter", "resistance",
    ])
    def test_legacy_input_aliases_return_true(self, legacy_alias):
        assert ChannelType.is_input(legacy_alias) is True

    @pytest.mark.parametrize("channel_type", [
        "voltage_output", "current_output", "digital_output",
        "counter_output", "pulse_output",
    ])
    def test_output_types_return_false(self, channel_type):
        assert ChannelType.is_input(channel_type) is False

    def test_unknown_type_returns_false(self):
        assert ChannelType.is_input("nonexistent_type") is False

    def test_empty_string_returns_false(self):
        assert ChannelType.is_input("") is False


# ---------------------------------------------------------------------------
# 2. ChannelType.is_output()
# ---------------------------------------------------------------------------

class TestIsOutput:
    """Test ChannelType.is_output() for all channel types."""

    @pytest.mark.parametrize("channel_type", [
        "voltage_output", "current_output", "digital_output",
        "counter_output", "pulse_output",
    ])
    def test_output_types_return_true(self, channel_type):
        assert ChannelType.is_output(channel_type) is True

    def test_legacy_analog_output_returns_true(self):
        assert ChannelType.is_output("analog_output") is True

    @pytest.mark.parametrize("channel_type", [
        "voltage_input", "current_input", "thermocouple", "rtd",
        "digital_input", "counter_input", "frequency_input",
    ])
    def test_input_types_return_false(self, channel_type):
        assert ChannelType.is_output(channel_type) is False

    def test_unknown_type_returns_false(self):
        assert ChannelType.is_output("nonexistent_type") is False


# ---------------------------------------------------------------------------
# 3. ChannelType.is_analog()
# ---------------------------------------------------------------------------

class TestIsAnalog:
    """Test ChannelType.is_analog() for all channel types."""

    @pytest.mark.parametrize("channel_type", [
        "voltage_input", "current_input", "thermocouple", "rtd",
        "strain_input", "bridge_input", "iepe_input", "resistance_input",
        "voltage_output", "current_output",
    ])
    def test_analog_types_return_true(self, channel_type):
        assert ChannelType.is_analog(channel_type) is True

    @pytest.mark.parametrize("legacy_alias", [
        "analog_input", "analog_output", "voltage", "current",
        "strain", "iepe", "resistance",
    ])
    def test_legacy_analog_aliases_return_true(self, legacy_alias):
        assert ChannelType.is_analog(legacy_alias) is True

    @pytest.mark.parametrize("channel_type", [
        "digital_input", "digital_output",
        "counter_input", "counter_output",
        "frequency_input", "pulse_output",
    ])
    def test_digital_and_counter_types_return_false(self, channel_type):
        assert ChannelType.is_analog(channel_type) is False

    def test_unknown_type_returns_false(self):
        assert ChannelType.is_analog("nonexistent_type") is False


# ---------------------------------------------------------------------------
# 4. ChannelType.needs_thermocouple_type()
# ---------------------------------------------------------------------------

class TestNeedsThermocoupleType:
    """Test ChannelType.needs_thermocouple_type()."""

    def test_thermocouple_needs_type(self):
        assert ChannelType.needs_thermocouple_type("thermocouple") is True

    @pytest.mark.parametrize("channel_type", [
        "voltage_input", "current_input", "rtd", "strain_input",
        "bridge_input", "iepe_input", "resistance_input",
        "voltage_output", "current_output",
        "digital_input", "digital_output",
        "counter_input", "counter_output",
    ])
    def test_non_thermocouple_types_return_false(self, channel_type):
        assert ChannelType.needs_thermocouple_type(channel_type) is False


# ---------------------------------------------------------------------------
# 5. ChannelType.get_internal_type() — exhaustive
# ---------------------------------------------------------------------------

class TestGetInternalType:
    """Test get_internal_type() maps all semantic types to DAQmx internal types."""

    @pytest.mark.parametrize("semantic,expected_internal", [
        # All analog inputs → analog_input
        ("voltage_input", "analog_input"),
        ("current_input", "analog_input"),
        ("thermocouple", "analog_input"),
        ("rtd", "analog_input"),
        ("strain_input", "analog_input"),
        ("bridge_input", "analog_input"),
        ("iepe_input", "analog_input"),
        ("resistance_input", "analog_input"),
        # Analog outputs → analog_output
        ("voltage_output", "analog_output"),
        ("current_output", "analog_output"),
        # Digital → digital_input / digital_output
        ("digital_input", "digital_input"),
        ("digital_output", "digital_output"),
        # Counter/timer
        ("counter_input", "counter_input"),
        ("counter_output", "counter_output"),
        ("frequency_input", "counter_input"),
        ("pulse_output", "counter_output"),
    ])
    def test_semantic_types(self, semantic, expected_internal):
        assert ChannelType.get_internal_type(semantic) == expected_internal

    @pytest.mark.parametrize("legacy,expected_internal", [
        ("voltage", "analog_input"),
        ("current", "analog_input"),
        ("strain", "analog_input"),
        ("iepe", "analog_input"),
        ("resistance", "analog_input"),
        ("counter", "counter_input"),
        ("analog_input", "analog_input"),
        ("analog_output", "analog_output"),
    ])
    def test_legacy_aliases(self, legacy, expected_internal):
        assert ChannelType.get_internal_type(legacy) == expected_internal

    def test_unknown_type_returns_itself(self):
        """Unknown types should pass through unchanged."""
        assert ChannelType.get_internal_type("unknown_type") == "unknown_type"

    def test_empty_string_returns_itself(self):
        assert ChannelType.get_internal_type("") == ""


# ---------------------------------------------------------------------------
# 6. get_module_channel_type() — format handling
# ---------------------------------------------------------------------------

class TestGetModuleChannelType:
    """Test get_module_channel_type() with various input formats."""

    def test_plain_number(self):
        assert get_module_channel_type("9213") == ChannelType.THERMOCOUPLE

    def test_ni_space_format(self):
        assert get_module_channel_type("NI 9213") == ChannelType.THERMOCOUPLE

    def test_ni_dash_format(self):
        assert get_module_channel_type("NI-9213") == ChannelType.THERMOCOUPLE

    def test_unknown_module_defaults_to_voltage_input(self):
        assert get_module_channel_type("9999") == ChannelType.VOLTAGE_INPUT

    def test_empty_string_defaults_to_voltage_input(self):
        assert get_module_channel_type("") == ChannelType.VOLTAGE_INPUT

    @pytest.mark.parametrize("model,expected", [
        ("9213", ChannelType.THERMOCOUPLE),
        ("9217", ChannelType.RTD),
        ("9202", ChannelType.VOLTAGE_INPUT),
        ("9208", ChannelType.CURRENT_INPUT),
        ("9264", ChannelType.VOLTAGE_OUTPUT),
        ("9266", ChannelType.CURRENT_OUTPUT),
        ("9425", ChannelType.DIGITAL_INPUT),
        ("9472", ChannelType.DIGITAL_OUTPUT),
        ("9361", ChannelType.COUNTER_INPUT),
        ("9234", ChannelType.IEPE_INPUT),
        ("9237", ChannelType.BRIDGE_INPUT),
        ("9236", ChannelType.STRAIN_INPUT),
        ("9219", ChannelType.BRIDGE_INPUT),
    ])
    def test_representative_modules(self, model, expected):
        assert get_module_channel_type(model) == expected


# ---------------------------------------------------------------------------
# 7. MODULE_TYPE_MAP exhaustive — all 66 entries
# ---------------------------------------------------------------------------

class TestModuleTypeMap:
    """Test MODULE_TYPE_MAP has all entries with correct ChannelType values."""

    @pytest.mark.parametrize("model_num,expected_type", [
        # Thermocouple (5)
        ("9210", ChannelType.THERMOCOUPLE),
        ("9211", ChannelType.THERMOCOUPLE),
        ("9212", ChannelType.THERMOCOUPLE),
        ("9213", ChannelType.THERMOCOUPLE),
        ("9214", ChannelType.THERMOCOUPLE),
        # RTD (3)
        ("9216", ChannelType.RTD),
        ("9217", ChannelType.RTD),
        ("9226", ChannelType.RTD),
        # Voltage input (11)
        ("9201", ChannelType.VOLTAGE_INPUT),
        ("9202", ChannelType.VOLTAGE_INPUT),
        ("9205", ChannelType.VOLTAGE_INPUT),
        ("9206", ChannelType.VOLTAGE_INPUT),
        ("9215", ChannelType.VOLTAGE_INPUT),
        ("9220", ChannelType.VOLTAGE_INPUT),
        ("9221", ChannelType.VOLTAGE_INPUT),
        ("9222", ChannelType.VOLTAGE_INPUT),
        ("9223", ChannelType.VOLTAGE_INPUT),
        ("9229", ChannelType.VOLTAGE_INPUT),
        ("9239", ChannelType.VOLTAGE_INPUT),
        # Current input (7)
        ("9203", ChannelType.CURRENT_INPUT),
        ("9207", ChannelType.CURRENT_INPUT),
        ("9208", ChannelType.CURRENT_INPUT),
        ("9227", ChannelType.CURRENT_INPUT),
        ("9246", ChannelType.CURRENT_INPUT),
        ("9247", ChannelType.CURRENT_INPUT),
        ("9253", ChannelType.CURRENT_INPUT),
        # IEPE (7)
        ("9230", ChannelType.IEPE_INPUT),
        ("9231", ChannelType.IEPE_INPUT),
        ("9232", ChannelType.IEPE_INPUT),
        ("9233", ChannelType.IEPE_INPUT),
        ("9234", ChannelType.IEPE_INPUT),
        ("9250", ChannelType.IEPE_INPUT),
        ("9251", ChannelType.IEPE_INPUT),
        # Strain/Bridge (3)
        ("9235", ChannelType.STRAIN_INPUT),
        ("9236", ChannelType.STRAIN_INPUT),
        ("9237", ChannelType.BRIDGE_INPUT),
        # Universal (1)
        ("9219", ChannelType.BRIDGE_INPUT),
        # Voltage output (5)
        ("9260", ChannelType.VOLTAGE_OUTPUT),
        ("9262", ChannelType.VOLTAGE_OUTPUT),
        ("9263", ChannelType.VOLTAGE_OUTPUT),
        ("9264", ChannelType.VOLTAGE_OUTPUT),
        ("9269", ChannelType.VOLTAGE_OUTPUT),
        # Current output (2)
        ("9265", ChannelType.CURRENT_OUTPUT),
        ("9266", ChannelType.CURRENT_OUTPUT),
        # Digital input (11)
        ("9375", ChannelType.DIGITAL_INPUT),
        ("9401", ChannelType.DIGITAL_INPUT),
        ("9402", ChannelType.DIGITAL_INPUT),
        ("9403", ChannelType.DIGITAL_INPUT),
        ("9411", ChannelType.DIGITAL_INPUT),
        ("9421", ChannelType.DIGITAL_INPUT),
        ("9422", ChannelType.DIGITAL_INPUT),
        ("9423", ChannelType.DIGITAL_INPUT),
        ("9425", ChannelType.DIGITAL_INPUT),
        ("9426", ChannelType.DIGITAL_INPUT),
        ("9435", ChannelType.DIGITAL_INPUT),
        # Digital output (10)
        ("9470", ChannelType.DIGITAL_OUTPUT),
        ("9472", ChannelType.DIGITAL_OUTPUT),
        ("9474", ChannelType.DIGITAL_OUTPUT),
        ("9475", ChannelType.DIGITAL_OUTPUT),
        ("9476", ChannelType.DIGITAL_OUTPUT),
        ("9477", ChannelType.DIGITAL_OUTPUT),
        ("9478", ChannelType.DIGITAL_OUTPUT),
        ("9481", ChannelType.DIGITAL_OUTPUT),
        ("9482", ChannelType.DIGITAL_OUTPUT),
        ("9485", ChannelType.DIGITAL_OUTPUT),
        # Counter (1)
        ("9361", ChannelType.COUNTER_INPUT),
    ])
    def test_module_type_map_entry(self, model_num, expected_type):
        assert MODULE_TYPE_MAP[model_num] == expected_type

    def test_module_type_map_size(self):
        """Guard: fail if a module is added/removed without updating tests."""
        assert len(MODULE_TYPE_MAP) == 66


# ---------------------------------------------------------------------------
# 8. get_relay_type()
# ---------------------------------------------------------------------------

class TestGetRelayType:
    """Test get_relay_type() for relay and non-relay modules."""

    def test_9481_spst(self):
        assert get_relay_type("9481") == "spst"

    def test_9482_spdt(self):
        assert get_relay_type("9482") == "spdt"

    def test_9485_ssr(self):
        assert get_relay_type("9485") == "ssr"

    def test_ni_prefix_format(self):
        """Should handle 'NI 9481' format."""
        assert get_relay_type("NI 9481") == "spst"

    def test_ni_dash_format(self):
        """Should handle 'NI-9482' format."""
        assert get_relay_type("NI-9482") == "spdt"

    def test_non_relay_module(self):
        assert get_relay_type("9213") == "none"

    def test_unknown_module(self):
        assert get_relay_type("9999") == "none"

    def test_relay_modules_dict_size(self):
        assert len(RELAY_MODULES) == 3


# ---------------------------------------------------------------------------
# 9. Cross-map parity: MODULE_TYPE_MAP vs NI_MODULE_DATABASE
# ---------------------------------------------------------------------------

class TestCrossMapParity:
    """
    Verify MODULE_TYPE_MAP (channel_types.py, cRIO-side) agrees with
    NI_MODULE_DATABASE (device_discovery.py, PC-side) on module categories.
    """

    @pytest.fixture
    def ni_module_database(self):
        from device_discovery import NI_MODULE_DATABASE
        return NI_MODULE_DATABASE

    def _extract_number(self, model_string: str) -> str:
        """Extract numeric model number from 'NI 9213' format."""
        return ''.join(c for c in model_string if c.isdigit())

    # Map ModuleCategory values → ChannelType values for comparison
    # These should agree for the same module
    CATEGORY_TO_CHANNEL_TYPE = {
        "thermocouple": "thermocouple",
        "rtd": "rtd",
        "voltage_input": "voltage_input",
        "current_input": "current_input",
        "strain_input": "strain_input",
        "bridge_input": "bridge_input",
        "iepe_input": "iepe_input",
        "resistance_input": "resistance_input",
        "voltage_output": "voltage_output",
        "current_output": "current_output",
        "digital_input": "digital_input",
        "digital_output": "digital_output",
        "counter_input": "counter_input",
        "counter_output": "counter_output",
        "frequency_input": "frequency_input",
    }

    def test_all_database_modules_in_type_map(self, ni_module_database):
        """Every module in NI_MODULE_DATABASE should exist in MODULE_TYPE_MAP."""
        missing = []
        for model_str in ni_module_database:
            num = self._extract_number(model_str)
            if num not in MODULE_TYPE_MAP:
                missing.append(model_str)
        assert missing == [], f"Modules in NI_MODULE_DATABASE but not MODULE_TYPE_MAP: {missing}"

    def test_all_type_map_modules_in_database(self, ni_module_database):
        """Every module in MODULE_TYPE_MAP should exist in NI_MODULE_DATABASE."""
        db_numbers = {self._extract_number(m) for m in ni_module_database}
        missing = []
        for num in MODULE_TYPE_MAP:
            if num not in db_numbers:
                missing.append(num)
        assert missing == [], f"Modules in MODULE_TYPE_MAP but not NI_MODULE_DATABASE: {missing}"

    def test_categories_agree(self, ni_module_database):
        """Both maps should classify each module the same way."""
        mismatches = []
        for model_str, db_entry in ni_module_database.items():
            num = self._extract_number(model_str)
            if num not in MODULE_TYPE_MAP:
                continue

            db_category = db_entry["category"].value  # ModuleCategory enum → string
            type_map_value = MODULE_TYPE_MAP[num].value  # ChannelType enum → string

            # Both should map to the same semantic string
            expected = self.CATEGORY_TO_CHANNEL_TYPE.get(db_category, db_category)
            if type_map_value != expected:
                mismatches.append(
                    f"{model_str}: NI_MODULE_DATABASE={db_category}, "
                    f"MODULE_TYPE_MAP={type_map_value}"
                )

        assert mismatches == [], \
            f"Category mismatches between maps:\n" + "\n".join(mismatches)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
