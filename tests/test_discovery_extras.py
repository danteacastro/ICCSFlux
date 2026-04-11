"""
Additional tests for device_discovery.py and config_parser.py

Covers gaps not addressed by existing test files:
- ChannelConfig properties: is_opto22, is_remote_node, is_virtual, hardware_source_display
- HardwareSource edge cases (opto22, COM-port modbus)
- DeviceDiscovery._generate_channel_name() all type prefixes
- DeviceDiscovery._get_default_unit() all channel types
- NI_MODULE_DATABASE channel count validation
- Thread safety of concurrent cRIO registration
- ChannelType legacy alias handling via _missing_

Run with: pytest tests/test_discovery_extras.py -v
"""

import pytest
import json
import threading
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from device_discovery import (
    DeviceDiscovery, NI_MODULE_DATABASE, ModuleCategory,
)
from config_parser import (
    ChannelConfig, ChannelType, HardwareSource, ProjectMode,
)


# ---------------------------------------------------------------------------
# 1. ChannelConfig Properties
# ---------------------------------------------------------------------------

class TestChannelConfigProperties:
    """Test ChannelConfig convenience properties."""

    def test_is_opto22_true(self):
        ch = ChannelConfig(
            name="opto_ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="opto22",
        )
        assert ch.is_opto22 is True
        assert ch.is_crio is False

    def test_is_opto22_false_for_crio(self):
        ch = ChannelConfig(
            name="crio_ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
        )
        assert ch.is_opto22 is False

    def test_is_remote_node_crio(self):
        ch = ChannelConfig(
            name="crio_ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
        )
        assert ch.is_remote_node is True

    def test_is_remote_node_opto22(self):
        ch = ChannelConfig(
            name="opto_ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="opto22",
        )
        assert ch.is_remote_node is True

    def test_is_remote_node_false_for_local(self):
        ch = ChannelConfig(
            name="local_ch",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.is_remote_node is False

    def test_is_remote_node_false_for_modbus(self):
        ch = ChannelConfig(
            name="mb_ch",
            physical_channel="192.168.1.100:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.is_remote_node is False

    def test_is_virtual_true(self):
        ch = ChannelConfig(
            name="calc_ch",
            physical_channel="virtual://computed",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.is_virtual is True

    def test_is_virtual_false_for_local(self):
        ch = ChannelConfig(
            name="local_ch",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.is_virtual is False

    def test_is_local_daq_true(self):
        ch = ChannelConfig(
            name="local_ch",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.is_local_daq is True

    def test_is_local_daq_false_for_crio(self):
        ch = ChannelConfig(
            name="crio_ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
        )
        assert ch.is_local_daq is False


# ---------------------------------------------------------------------------
# 2. hardware_source_display property
# ---------------------------------------------------------------------------

class TestHardwareSourceDisplay:
    """Test human-readable hardware source display strings."""

    def test_crio_display_with_node_id(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
            source_node_id="crio-001",
        )
        assert ch.hardware_source_display == "cRIO (crio-001)"

    def test_crio_display_without_node_id(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
            source_node_id="",
        )
        assert ch.hardware_source_display == "cRIO (cRIO)"

    def test_local_daq_display_with_chassis(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="cDAQ1Mod3/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        display = ch.hardware_source_display
        assert display.startswith("Local DAQ (")
        assert "cDAQ1Mod3" in display

    def test_local_daq_display_without_slash(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="Dev1",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.hardware_source_display == "Local DAQ"

    def test_modbus_tcp_display(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="192.168.1.100:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.hardware_source_display == "Modbus TCP"

    def test_modbus_rtu_display(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="rtu://COM3:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.hardware_source_display == "Modbus RTU"

    def test_virtual_display(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="virtual://computed",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.hardware_source_display == "Virtual"


# ---------------------------------------------------------------------------
# 3. HardwareSource edge cases
# ---------------------------------------------------------------------------

class TestHardwareSourceEdgeCases:
    """Test HardwareSource detection for tricky formats."""

    def test_opto22_source_type(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="opto22",
        )
        assert ch.hardware_source == HardwareSource.OPTO22

    def test_modbus_with_com_in_path(self):
        """COM port in physical_channel without rtu:// prefix should still detect RTU."""
        ch = ChannelConfig(
            name="ch",
            physical_channel="COM3:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.hardware_source == HardwareSource.MODBUS_RTU

    def test_source_type_crio_overrides_physical_channel(self):
        """source_type should take priority over physical_channel format."""
        ch = ChannelConfig(
            name="ch",
            physical_channel="cDAQ1Mod1/ai0",  # Looks local
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",  # But marked as cRIO
        )
        assert ch.hardware_source == HardwareSource.CRIO

    def test_default_source_type_local(self):
        """Channels with source_type='local' should be LOCAL_DAQ."""
        ch = ChannelConfig(
            name="ch",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="local",
        )
        assert ch.hardware_source == HardwareSource.LOCAL_DAQ


# ---------------------------------------------------------------------------
# 4. ChannelType legacy alias handling
# ---------------------------------------------------------------------------

class TestChannelTypeLegacyAliases:
    """Test that ChannelType._missing_ handles backwards compatibility."""

    def test_voltage_maps_to_voltage_input(self):
        assert ChannelType("voltage") == ChannelType.VOLTAGE_INPUT

    def test_current_maps_to_current_input(self):
        assert ChannelType("current") == ChannelType.CURRENT_INPUT

    def test_analog_output_maps_to_voltage_output(self):
        assert ChannelType("analog_output") == ChannelType.VOLTAGE_OUTPUT

    def test_analog_input_maps_to_voltage_input(self):
        assert ChannelType("analog_input") == ChannelType.VOLTAGE_INPUT

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            ChannelType("totally_unknown")


# ---------------------------------------------------------------------------
# 5. _generate_channel_name() — all type prefixes
# ---------------------------------------------------------------------------

class TestGenerateChannelName:
    """Test DeviceDiscovery._generate_channel_name() for all channel types."""

    @pytest.fixture
    def discovery(self):
        return DeviceDiscovery()

    @pytest.mark.parametrize("ch_type,expected_prefix", [
        ("thermocouple", "TC"),
        ("rtd", "RTD"),
        ("voltage", "AI"),
        ("current", "mA"),
        ("strain", "STR"),
        ("iepe", "IEPE"),
        ("digital_input", "DI"),
        ("digital_output", "DO"),
        ("analog_output", "AO"),
        ("counter", "CTR"),
    ])
    def test_type_prefix(self, discovery, ch_type, expected_prefix):
        channel = {
            "device": "cDAQ1Mod3",
            "channel_type": ch_type,
            "index": 5,
        }
        name = discovery._generate_channel_name(channel)
        assert name.startswith(expected_prefix)

    def test_unknown_type_uses_ch_prefix(self, discovery):
        channel = {
            "device": "cDAQ1Mod1",
            "channel_type": "unknown",
            "index": 0,
        }
        name = discovery._generate_channel_name(channel)
        assert name.startswith("CH")

    def test_module_number_extracted(self, discovery):
        channel = {
            "device": "cDAQ1Mod5",
            "channel_type": "thermocouple",
            "index": 3,
        }
        name = discovery._generate_channel_name(channel)
        assert "5" in name  # Module number extracted

    def test_index_zero_padded(self, discovery):
        channel = {
            "device": "cDAQ1Mod1",
            "channel_type": "voltage",
            "index": 7,
        }
        name = discovery._generate_channel_name(channel)
        assert name.endswith("_07")

    def test_no_mod_in_device(self, discovery):
        channel = {
            "device": "Dev1",
            "channel_type": "voltage",
            "index": 0,
        }
        name = discovery._generate_channel_name(channel)
        assert name == "AI_00"


# ---------------------------------------------------------------------------
# 6. _get_default_unit() — all channel types
# ---------------------------------------------------------------------------

class TestGetDefaultUnit:
    """Test DeviceDiscovery._get_default_unit() for all channel types."""

    @pytest.fixture
    def discovery(self):
        return DeviceDiscovery()

    @pytest.mark.parametrize("ch_type,expected_unit", [
        ("thermocouple", "degC"),
        ("rtd", "degC"),
        ("voltage", "V"),
        ("current", "mA"),
        ("strain", "µε"),
        ("iepe", "g"),
        ("digital_input", ""),
        ("digital_output", ""),
        ("analog_output", "V"),
        ("counter", "counts"),
    ])
    def test_known_type_unit(self, discovery, ch_type, expected_unit):
        assert discovery._get_default_unit(ch_type) == expected_unit

    def test_unknown_type_empty(self, discovery):
        assert discovery._get_default_unit("unknown") == ""


# ---------------------------------------------------------------------------
# 7. NI_MODULE_DATABASE channel count validation
# ---------------------------------------------------------------------------

class TestModuleDatabaseChannelCounts:
    """Verify channel counts in NI_MODULE_DATABASE are reasonable."""

    @pytest.mark.parametrize("model,expected_channels", [
        # Thermocouples
        ("NI 9210", 4),
        ("NI 9211", 4),
        ("NI 9212", 8),
        ("NI 9213", 16),
        ("NI 9214", 16),
        # RTD
        ("NI 9216", 8),
        ("NI 9217", 4),
        ("NI 9226", 8),
        # Voltage input — common modules
        ("NI 9201", 8),
        ("NI 9202", 16),
        ("NI 9205", 32),
        ("NI 9215", 4),
        ("NI 9239", 4),
        # Current input
        ("NI 9203", 8),
        ("NI 9207", 16),
        ("NI 9208", 16),
        # Digital I/O
        ("NI 9375", 32),
        ("NI 9425", 32),
        ("NI 9472", 8),
        ("NI 9476", 32),
        # Voltage output
        ("NI 9264", 16),
        ("NI 9263", 4),
        # Current output
        ("NI 9265", 4),
        ("NI 9266", 8),
        # Counter
        ("NI 9361", 8),
        # Universal
        ("NI 9219", 4),
        # Relay
        ("NI 9481", 4),
        ("NI 9482", 4),
        ("NI 9485", 8),
    ])
    def test_channel_count(self, model, expected_channels):
        entry = NI_MODULE_DATABASE[model]
        assert entry["channels"] == expected_channels

    def test_all_entries_have_positive_channel_count(self):
        for model, entry in NI_MODULE_DATABASE.items():
            assert entry["channels"] > 0, \
                f"{model} has invalid channel count: {entry['channels']}"

    def test_all_entries_have_description(self):
        for model, entry in NI_MODULE_DATABASE.items():
            assert entry.get("description"), \
                f"{model} is missing description"

    def test_all_entries_have_valid_category(self):
        valid = {mc.value for mc in ModuleCategory}
        for model, entry in NI_MODULE_DATABASE.items():
            cat = entry["category"]
            cat_val = cat.value if hasattr(cat, 'value') else str(cat)
            assert cat_val in valid, \
                f"{model} has invalid category: {cat_val}"


# ---------------------------------------------------------------------------
# 8. Thread safety of concurrent cRIO registration
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """Test concurrent cRIO registration doesn't corrupt state."""

    @staticmethod
    def _fresh_discovery():
        """Create a DeviceDiscovery with no persisted nodes."""
        d = DeviceDiscovery()
        d._crio_nodes.clear()
        d._opto22_nodes.clear()
        d._gc_nodes.clear()
        d._cfp_nodes.clear()
        return d

    def test_concurrent_register_same_node(self):
        """Multiple threads registering the same node shouldn't corrupt."""
        discovery = self._fresh_discovery()
        errors = []

        def register(thread_id):
            try:
                for i in range(50):
                    discovery.register_crio_node("crio-001", {
                        "status": "online",
                        "ip_address": f"192.168.1.{thread_id}",
                        "product_type": "cRIO-9056",
                        "serial_number": "ABC",
                        "channels": 96,
                        "modules": [],
                    })
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=register, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent registration: {errors}"
        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "crio-001"

    def test_concurrent_register_different_nodes(self):
        """Multiple threads registering different nodes simultaneously."""
        discovery = self._fresh_discovery()
        errors = []

        def register(node_num):
            try:
                for i in range(20):
                    discovery.register_crio_node(f"crio-{node_num:03d}", {
                        "status": "online",
                        "ip_address": f"192.168.1.{node_num}",
                        "product_type": "cRIO-9056",
                        "serial_number": f"SN{node_num}",
                        "channels": 16,
                        "modules": [],
                    })
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=register, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent registration: {errors}"
        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 10

    def test_concurrent_register_and_heartbeat(self):
        """Concurrent full registration + heartbeat updates."""
        discovery = self._fresh_discovery()
        errors = []

        def register():
            try:
                for _ in range(30):
                    discovery.register_crio_node("crio-001", {
                        "status": "online",
                        "ip_address": "192.168.1.20",
                        "product_type": "cRIO-9056",
                        "serial_number": "ABC",
                        "channels": 96,
                        "modules": [
                            {"name": "Mod1", "product_type": "NI 9213",
                             "slot": 1, "category": "thermocouple",
                             "channels": []}
                        ],
                    })
            except Exception as e:
                errors.append(f"register: {e}")

        def heartbeat():
            try:
                for _ in range(30):
                    discovery.update_crio_heartbeat("crio-001", {
                        "status": "online",
                        "channels": 96,
                    })
            except Exception as e:
                errors.append(f"heartbeat: {e}")

        def offline():
            try:
                for _ in range(30):
                    discovery.mark_crio_offline("crio-001")
            except Exception as e:
                errors.append(f"offline: {e}")

        threads = [
            threading.Thread(target=register),
            threading.Thread(target=heartbeat),
            threading.Thread(target=offline),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent ops: {errors}"
        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1


# ---------------------------------------------------------------------------
# 9. safety_can_run_locally
# ---------------------------------------------------------------------------

class TestSafetyCanRunLocally:
    """Test the safety_can_run_locally property."""

    def test_crio_channel_can_run_locally(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type="crio",
        )
        assert ch.safety_can_run_locally is True

    def test_local_daq_cannot_run_locally(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.safety_can_run_locally is False

    def test_modbus_cannot_run_locally(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="192.168.1.100:1:40001",
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.safety_can_run_locally is False

    def test_virtual_cannot_run_locally(self):
        ch = ChannelConfig(
            name="ch",
            physical_channel="virtual://calc",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.safety_can_run_locally is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
