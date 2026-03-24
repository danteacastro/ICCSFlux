"""
Tests for device_discovery.py
Covers NI DAQmx device scanning and channel enumeration.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from device_discovery import (
    DeviceDiscovery, DiscoveryResult, Chassis, Module, PhysicalChannel,
    CRIONode, Opto22Node, ModuleCategory, NI_MODULE_DATABASE
)

class TestModuleCategory:
    """Tests for ModuleCategory enum"""

    def test_category_values(self):
        """Test all category values exist"""
        assert ModuleCategory.THERMOCOUPLE.value == "thermocouple"
        assert ModuleCategory.RTD.value == "rtd"
        assert ModuleCategory.VOLTAGE_INPUT.value == "voltage_input"
        assert ModuleCategory.CURRENT_INPUT.value == "current_input"
        assert ModuleCategory.DIGITAL_INPUT.value == "digital_input"
        assert ModuleCategory.DIGITAL_OUTPUT.value == "digital_output"
        assert ModuleCategory.ANALOG_OUTPUT.value == "analog_output"

class TestNIModuleDatabase:
    """Tests for NI module database"""

    def test_thermocouple_modules(self):
        """Test thermocouple modules in database"""
        assert "NI 9213" in NI_MODULE_DATABASE
        assert NI_MODULE_DATABASE["NI 9213"]["category"] == ModuleCategory.THERMOCOUPLE
        assert NI_MODULE_DATABASE["NI 9213"]["channels"] == 16

    def test_voltage_modules(self):
        """Test voltage input modules in database"""
        assert "NI 9205" in NI_MODULE_DATABASE
        assert NI_MODULE_DATABASE["NI 9205"]["category"] == ModuleCategory.VOLTAGE_INPUT
        assert NI_MODULE_DATABASE["NI 9205"]["channels"] == 32

    def test_current_modules(self):
        """Test current input modules in database"""
        assert "NI 9203" in NI_MODULE_DATABASE
        assert NI_MODULE_DATABASE["NI 9203"]["category"] == ModuleCategory.CURRENT_INPUT

    def test_digital_modules(self):
        """Test digital I/O modules in database"""
        assert "NI 9472" in NI_MODULE_DATABASE
        assert NI_MODULE_DATABASE["NI 9472"]["category"] == ModuleCategory.DIGITAL_OUTPUT

class TestPhysicalChannel:
    """Tests for PhysicalChannel dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        channel = PhysicalChannel(
            name="cDAQ1Mod1/ai0",
            device="cDAQ1Mod1",
            channel_type="ai",
            index=0,
            category="thermocouple",
            description="Thermocouple 0"
        )

        d = channel.to_dict()

        assert d['name'] == "cDAQ1Mod1/ai0"
        assert d['device'] == "cDAQ1Mod1"
        assert d['channel_type'] == "ai"
        assert d['category'] == "thermocouple"

class TestModule:
    """Tests for Module dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        module = Module(
            name="cDAQ1Mod1",
            product_type="NI 9213",
            serial_number="SIM001",
            slot=1,
            chassis="cDAQ1",
            category="thermocouple",
            description="16-Ch Thermocouple"
        )
        module.channels.append(PhysicalChannel(
            name="cDAQ1Mod1/ai0",
            device="cDAQ1Mod1",
            channel_type="ai",
            index=0,
            category="thermocouple"
        ))

        d = module.to_dict()

        assert d['name'] == "cDAQ1Mod1"
        assert d['product_type'] == "NI 9213"
        assert len(d['channels']) == 1

class TestChassis:
    """Tests for Chassis dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        chassis = Chassis(
            name="cDAQ1",
            product_type="cDAQ-9189",
            serial_number="SIM001",
            slot_count=8
        )

        d = chassis.to_dict()

        assert d['name'] == "cDAQ1"
        assert d['slot_count'] == 8
        assert d['modules'] == []

class TestCRIONode:
    """Tests for CRIONode dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        node = CRIONode(
            node_id="crio-001",
            ip_address="192.168.1.50",
            product_type="cRIO-9056",
            serial_number="12345",
            status="online",
            last_seen="2025-01-15T10:00:00",
            channels=32
        )

        d = node.to_dict()

        assert d['node_id'] == "crio-001"
        assert d['node_type'] == "crio"
        assert d['status'] == "online"

class TestOpto22Node:
    """Tests for Opto22Node dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        node = Opto22Node(
            node_id="opto22-001",
            ip_address="192.168.1.60",
            product_type="groov EPIC",
            serial_number="67890",
            status="online",
            last_seen="2025-01-15T10:00:00",
            channels=16
        )

        d = node.to_dict()

        assert d['node_id'] == "opto22-001"
        assert d['node_type'] == "opto22"

class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        result = DiscoveryResult(
            success=True,
            message="Found 1 chassis",
            timestamp="2025-01-15T10:00:00",
            total_channels=48,
            simulation_mode=True
        )

        d = result.to_dict()

        assert d['success'] is True
        assert d['simulation_mode'] is True
        assert d['total_channels'] == 48

class TestDeviceDiscovery:
    """Tests for DeviceDiscovery class"""

    @pytest.fixture
    def discovery(self):
        """Create a DeviceDiscovery instance"""
        return DeviceDiscovery()

    # =========================================================================
    # SCAN TESTS
    # =========================================================================

    def test_scan_returns_valid_result(self, discovery):
        """Test scanning returns a valid result (real or simulated)"""
        result = discovery.scan()

        assert result.success is True
        assert result.total_channels > 0
        assert len(result.chassis) > 0

    def test_scan_returns_chassis(self, discovery):
        """Test scan returns chassis info"""
        result = discovery.scan()

        assert len(result.chassis) >= 1
        chassis = result.chassis[0]
        assert chassis.name  # Has a name
        assert "cDAQ" in chassis.product_type

    def test_scan_returns_modules(self, discovery):
        """Test scan returns module info"""
        result = discovery.scan()

        chassis = result.chassis[0]
        assert len(chassis.modules) > 0

        # Check a thermocouple module
        tc_module = next((m for m in chassis.modules if "9213" in m.product_type), None)
        assert tc_module is not None
        assert tc_module.category == "thermocouple"

    def test_scan_returns_channels(self, discovery):
        """Test scan returns channel info"""
        result = discovery.scan()

        chassis = result.chassis[0]
        module = chassis.modules[0]
        assert len(module.channels) > 0

        channel = module.channels[0]
        assert channel.name.startswith("cDAQ")
        assert channel.device == module.name

    def test_scan_caches_result(self, discovery):
        """Test that scan caches the result"""
        result1 = discovery.scan()
        result2 = discovery._last_result

        assert result2 is not None
        assert result2.timestamp == result1.timestamp

    # =========================================================================
    # CRIO NODE TESTS
    # =========================================================================

    def test_register_crio_node(self, discovery):
        """Test registering a cRIO node"""
        discovery.register_crio_node("crio-001", {
            'ip_address': '192.168.1.50',
            'product_type': 'cRIO-9056',
            'serial_number': '12345',
            'status': 'online',
            'channels': 32
        })

        nodes = discovery.get_crio_nodes()

        assert len(nodes) == 1
        assert nodes[0].node_id == "crio-001"
        assert nodes[0].status == "online"

    def test_update_crio_node(self, discovery):
        """Test updating an existing cRIO node"""
        discovery.register_crio_node("crio-001", {
            'status': 'online',
            'channels': 32
        })

        discovery.register_crio_node("crio-001", {
            'status': 'online',
            'channels': 48  # Updated
        })

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1
        assert nodes[0].channels == 48

    def test_unregister_crio_node(self, discovery):
        """Test unregistering a cRIO node"""
        discovery.register_crio_node("crio-001", {'status': 'online'})
        discovery.unregister_crio_node("crio-001")

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 0

    def test_mark_crio_offline(self, discovery):
        """Test marking a cRIO node as offline"""
        discovery.register_crio_node("crio-001", {'status': 'online'})
        discovery.mark_crio_offline("crio-001")

        nodes = discovery.get_crio_nodes()
        assert nodes[0].status == "offline"

    def test_update_crio_heartbeat_existing(self, discovery):
        """Test updating cRIO heartbeat for existing node"""
        discovery.register_crio_node("crio-001", {
            'status': 'online',
            'ip_address': '192.168.1.50',
            'channels': 32
        })

        discovery.update_crio_heartbeat("crio-001", {
            'status': 'online'
        })

        nodes = discovery.get_crio_nodes()
        assert nodes[0].status == "online"
        # Should preserve original data
        assert nodes[0].ip_address == "192.168.1.50"

    def test_update_crio_heartbeat_new(self, discovery):
        """Test updating cRIO heartbeat creates new node"""
        discovery.update_crio_heartbeat("crio-new", {
            'status': 'online',
            'ip_address': '192.168.1.100'
        })

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "crio-new"

    def test_scan_includes_crio_nodes(self, discovery):
        """Test that scan includes registered cRIO nodes"""
        discovery.register_crio_node("crio-001", {
            'status': 'online',
            'channels': 32
        })

        result = discovery.scan(include_crio=True)

        assert len(result.crio_nodes) == 1
        # Total channels should include cRIO channels
        assert result.total_channels >= 32

    def test_scan_excludes_crio_nodes(self, discovery):
        """Test that scan can exclude cRIO nodes"""
        discovery.register_crio_node("crio-001", {
            'status': 'online',
            'channels': 32
        })

        result = discovery.scan(include_crio=False)

        assert len(result.crio_nodes) == 0

    # =========================================================================
    # OPTO22 NODE TESTS
    # =========================================================================

    def test_register_opto22_node(self, discovery):
        """Test registering an Opto22 node"""
        discovery.register_opto22_node("opto22-001", {
            'ip_address': '192.168.1.60',
            'product_type': 'groov EPIC',
            'serial_number': '67890',
            'status': 'online',
            'channels': 16
        })

        nodes = discovery.get_opto22_nodes()

        assert len(nodes) == 1
        assert nodes[0].node_id == "opto22-001"

    def test_unregister_opto22_node(self, discovery):
        """Test unregistering an Opto22 node"""
        discovery.register_opto22_node("opto22-001", {'status': 'online'})
        discovery.unregister_opto22_node("opto22-001")

        nodes = discovery.get_opto22_nodes()
        assert len(nodes) == 0

    def test_mark_opto22_offline(self, discovery):
        """Test marking an Opto22 node as offline"""
        discovery.register_opto22_node("opto22-001", {'status': 'online'})
        discovery.mark_opto22_offline("opto22-001")

        nodes = discovery.get_opto22_nodes()
        assert nodes[0].status == "offline"

    def test_scan_includes_opto22_nodes(self, discovery):
        """Test that scan includes registered Opto22 nodes"""
        discovery.register_opto22_node("opto22-001", {
            'status': 'online',
            'channels': 16
        })

        result = discovery.scan(include_opto22=True)

        assert len(result.opto22_nodes) == 1

    # =========================================================================
    # CHANNEL ENUMERATION TESTS
    # =========================================================================

    def test_get_available_channels(self, discovery):
        """Test getting available channels"""
        discovery.scan()

        channels = discovery.get_available_channels()

        assert len(channels) > 0
        # Check channel structure
        ch = channels[0]
        assert 'physical_channel' in ch
        assert 'device' in ch
        assert 'channel_type' in ch

    def test_get_available_channels_auto_scans(self, discovery):
        """Test that get_available_channels auto-scans if needed"""
        discovery._last_result = None

        channels = discovery.get_available_channels()

        assert len(channels) > 0

    # =========================================================================
    # CONFIG TEMPLATE TESTS
    # =========================================================================

    def test_generate_config_template(self, discovery):
        """Test generating configuration template"""
        discovery.scan()

        config = discovery.generate_config_template()

        assert 'chassis' in config
        assert 'modules' in config
        assert 'channels' in config

    def test_generate_config_template_structure(self, discovery):
        """Test config template structure"""
        discovery.scan()
        config = discovery.generate_config_template()

        # Check chassis (name varies by hardware)
        assert len(config['chassis']) >= 1

        # Check modules
        assert any('Mod' in name for name in config['modules'])

        # Check channels have proper structure
        for ch_name, ch_config in config['channels'].items():
            assert 'physical_channel' in ch_config
            assert 'channel_type' in ch_config
            assert 'enabled' in ch_config

    def test_generate_channel_name(self, discovery):
        """Test channel name generation"""
        channel = {
            'device': 'cDAQ1Mod1',
            'channel_type': 'thermocouple',
            'index': 5
        }

        name = discovery._generate_channel_name(channel)

        assert 'TC' in name  # Thermocouple prefix
        assert '1' in name   # Module number
        assert '05' in name  # Index with padding

    def test_get_default_unit(self, discovery):
        """Test getting default units"""
        assert discovery._get_default_unit('thermocouple') == 'degC'
        assert discovery._get_default_unit('rtd') == 'degC'
        assert discovery._get_default_unit('voltage') == 'V'
        assert discovery._get_default_unit('current') == 'mA'
        assert discovery._get_default_unit('counter') == 'counts'

    # =========================================================================
    # HELPER METHOD TESTS
    # =========================================================================

    def test_get_chassis_slots(self, discovery):
        """Test getting chassis slot count"""
        assert discovery._get_chassis_slots("cDAQ-9178") == 8
        assert discovery._get_chassis_slots("cDAQ-9174") == 4
        assert discovery._get_chassis_slots("cDAQ-9171") == 1
        assert discovery._get_chassis_slots("unknown") == 8  # Default

    def test_extract_chassis_name(self, discovery):
        """Test extracting chassis name from device"""
        assert discovery._extract_chassis_name("cDAQ1Mod1") == "cDAQ1"
        assert discovery._extract_chassis_name("cDAQ2Mod3") == "cDAQ2"
        assert discovery._extract_chassis_name("Dev1") is None

    def test_extract_slot_number(self, discovery):
        """Test extracting slot number from device"""
        assert discovery._extract_slot_number("cDAQ1Mod1") == 1
        assert discovery._extract_slot_number("cDAQ1Mod5") == 5
        assert discovery._extract_slot_number("Dev1") == 0

class TestHardwareDiscovery:
    """Tests for hardware discovery (works with real or simulated hardware)"""

    @pytest.fixture
    def discovery(self):
        return DeviceDiscovery()

    def test_chassis_has_valid_structure(self, discovery):
        """Test discovered chassis has proper structure"""
        result = discovery.scan()

        chassis = result.chassis[0]
        assert chassis.slot_count > 0
        assert len(chassis.modules) >= 1

    def test_modules_have_channels(self, discovery):
        """Test each discovered module has channels"""
        result = discovery.scan()

        all_modules = []
        for chassis in result.chassis:
            all_modules.extend(chassis.modules)
        all_modules.extend(result.standalone_devices)

        assert len(all_modules) >= 1
        for mod in all_modules:
            assert len(mod.channels) >= 1, f"Module {mod.name} ({mod.product_type}) has no channels"

    def test_modules_have_valid_category(self, discovery):
        """Test each module has a valid category from ModuleCategory"""
        result = discovery.scan()

        valid_categories = {mc.value for mc in ModuleCategory}

        for chassis in result.chassis:
            for mod in chassis.modules:
                assert mod.category in valid_categories, \
                    f"Module {mod.name} has unknown category: {mod.category}"

    def test_channels_have_valid_type(self, discovery):
        """Test channels have valid channel_type (ai, ao, di, do, ci, co)"""
        result = discovery.scan()

        valid_types = {"ai", "ao", "di", "do", "ci", "co"}

        for chassis in result.chassis:
            for mod in chassis.modules:
                for ch in mod.channels:
                    assert ch.channel_type in valid_types, \
                        f"Channel {ch.name} has unknown type: {ch.channel_type}"
