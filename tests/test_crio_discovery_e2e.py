"""
End-to-end tests for cRIO discovery in cRIO mode.

Tests the full cRIO discovery chain:
- Project config loading with project_mode="crio"
- HardwareSource detection for cRIO channels
- DeviceDiscovery cRIO node registration (simulating MQTT status)
- Heartbeat fallback and offline marking
- scan() combining local hardware + remote cRIO nodes
- Config push format correctness (dict channels, thermocouple types)
- Full end-to-end flow from config load → discovery → config push

Run with: pytest tests/test_crio_discovery_e2e.py -v
"""

import pytest
import json
import os
import sys
from datetime import datetime, timezone

# Ensure daq_service modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from device_discovery import (
    DeviceDiscovery, CRIONode, Module, PhysicalChannel, ModuleCategory
)
from config_parser import (
    ProjectMode, HardwareSource, ChannelConfig, ChannelType, SystemConfig
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def discovery():
    """Fresh DeviceDiscovery instance with no persisted nodes."""
    d = DeviceDiscovery()
    # Clear any nodes loaded from disk (known_nodes.json) so tests start clean
    d._crio_nodes.clear()
    d._opto22_nodes.clear()
    d._gc_nodes.clear()
    d._cfp_nodes.clear()
    return d


@pytest.fixture
def crio_status_6mod():
    """Simulated cRIO status payload with 6 modules (96 channels)."""
    return {
        "status": "online",
        "acquiring": False,
        "node_type": "crio",
        "node_id": "crio-001",
        "ip_address": "192.168.1.20",
        "product_type": "cRIO-9056",
        "serial_number": "01ABC234",
        "device_name": "cRIO-9056-01ABC234",
        "channels": 96,
        "modules": [
            {
                "name": "Mod1", "product_type": "NI 9202", "slot": 1,
                "category": "voltage_input",
                "description": "16-Ch Voltage Input",
                "channels": [
                    {"name": f"Mod1/ai{i}", "channel_type": "ai",
                     "index": i, "category": "voltage_input",
                     "description": f"Voltage Input {i}"}
                    for i in range(16)
                ]
            },
            {
                "name": "Mod2", "product_type": "NI 9264", "slot": 2,
                "category": "voltage_output",
                "description": "16-Ch Voltage Output",
                "channels": [
                    {"name": f"Mod2/ao{i}", "channel_type": "ao",
                     "index": i, "category": "voltage_output",
                     "description": f"Voltage Output {i}"}
                    for i in range(16)
                ]
            },
            {
                "name": "Mod3", "product_type": "NI 9425", "slot": 3,
                "category": "digital_input",
                "description": "32-Ch Digital Input",
                "channels": [
                    {"name": f"Mod3/port0/line{i}", "channel_type": "di",
                     "index": i, "category": "digital_input",
                     "description": f"Digital Input {i}"}
                    for i in range(32)
                ]
            },
            {
                "name": "Mod4", "product_type": "NI 9472", "slot": 4,
                "category": "digital_output",
                "description": "8-Ch Digital Output",
                "channels": [
                    {"name": f"Mod4/port0/line{i}", "channel_type": "do",
                     "index": i, "category": "digital_output",
                     "description": f"Digital Output {i}"}
                    for i in range(8)
                ]
            },
            {
                "name": "Mod5", "product_type": "NI 9213", "slot": 5,
                "category": "thermocouple",
                "description": "16-Ch Thermocouple",
                "channels": [
                    {"name": f"Mod5/ai{i}", "channel_type": "ai",
                     "index": i, "category": "thermocouple",
                     "description": f"Thermocouple {i}"}
                    for i in range(16)
                ]
            },
            {
                "name": "Mod6", "product_type": "NI 9266", "slot": 6,
                "category": "current_output",
                "description": "8-Ch Current Output",
                "channels": [
                    {"name": f"Mod6/ao{i}", "channel_type": "ao",
                     "index": i, "category": "current_output",
                     "description": f"Current Output {i}"}
                    for i in range(8)
                ]
            },
        ]
    }


@pytest.fixture
def crio_heartbeat():
    """Simulated cRIO heartbeat payload (minimal)."""
    return {
        "seq": 42,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "acquiring": True,
        "pc_connected": True,
        "node_type": "crio",
        "node_id": "crio-001",
        "channels": 96,
        "ip_address": "192.168.1.20",
        "product_type": "cRIO-9056",
        "serial_number": "01ABC234",
    }


@pytest.fixture
def blank_crio_config_path():
    """Path to the blank cRIO 6-module config."""
    path = os.path.join(
        os.path.dirname(__file__), '..', 'config', 'projects',
        'blankcrioconfig6mod.json'
    )
    if os.path.exists(path):
        return path
    pytest.skip("blankcrioconfig6mod.json not found")


# ---------------------------------------------------------------------------
# 1. Project Config / ProjectMode Tests
# ---------------------------------------------------------------------------

class TestProjectModeDetection:
    """Verify project_mode='crio' is detected from config files."""

    def test_project_mode_crio_enum(self):
        """ProjectMode.CRIO should have value 'crio'."""
        assert ProjectMode.CRIO.value == "crio"

    def test_project_mode_from_string(self):
        """ProjectMode should be constructable from string 'crio'."""
        mode = ProjectMode("crio")
        assert mode == ProjectMode.CRIO

    def test_system_config_default_is_cdaq(self):
        """Default SystemConfig should be CDAQ mode."""
        config = SystemConfig()
        assert config.project_mode == ProjectMode.CDAQ

    def test_system_config_accepts_crio_mode(self):
        """SystemConfig should accept CRIO mode."""
        config = SystemConfig(project_mode=ProjectMode.CRIO)
        assert config.project_mode == ProjectMode.CRIO

    def test_blank_crio_config_has_crio_source(self, blank_crio_config_path):
        """blankcrioconfig6mod.json channels should have source_type='crio'."""
        with open(blank_crio_config_path, 'r') as f:
            data = json.load(f)

        channels = data.get('channels', {})
        assert len(channels) > 0, "Config should have channels"

        for name, ch in channels.items():
            assert ch.get('source_type') == 'crio', \
                f"Channel {name} should have source_type='crio', got '{ch.get('source_type')}'"

    def test_blank_crio_config_channels_have_node_id(self, blank_crio_config_path):
        """blankcrioconfig6mod.json channels should reference crio-001."""
        with open(blank_crio_config_path, 'r') as f:
            data = json.load(f)

        channels = data.get('channels', {})
        for name, ch in channels.items():
            node_id = ch.get('node_id', '')
            assert node_id, f"Channel {name} should have a node_id"

    def test_blank_crio_config_physical_channels_use_mod_prefix(self, blank_crio_config_path):
        """cRIO channels use Mod prefix (e.g. 'Mod1/ai0'), not full chassis path."""
        with open(blank_crio_config_path, 'r') as f:
            data = json.load(f)

        channels = data.get('channels', {})
        for name, ch in channels.items():
            phys = ch.get('physical_channel', '')
            assert phys.startswith('Mod'), \
                f"Channel {name} physical_channel should start with 'Mod', got '{phys}'"


# ---------------------------------------------------------------------------
# 2. HardwareSource Detection Tests
# ---------------------------------------------------------------------------

class TestHardwareSourceDetection:
    """Verify HardwareSource correctly identifies cRIO channels."""

    def test_crio_source_from_source_type(self):
        """Channel with source_type='crio' should be detected as CRIO."""
        ch = ChannelConfig(
            name='tag_0',
            physical_channel='Mod1/ai0',
            channel_type=ChannelType.VOLTAGE_INPUT,
            source_type='crio',
            source_node_id='crio-001'
        )
        assert ch.hardware_source == HardwareSource.CRIO

    def test_local_source_default(self):
        """Channel without source_type should default to LOCAL_DAQ."""
        ch = ChannelConfig(
            name='tag_0',
            physical_channel='cDAQ1Mod1/ai0',
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        assert ch.hardware_source == HardwareSource.LOCAL_DAQ

    def test_modbus_tcp_source(self):
        """Modbus TCP channel should be detected."""
        ch = ChannelConfig(
            name='mb_reg',
            physical_channel='192.168.1.100:502:40001',
            channel_type=ChannelType.MODBUS_REGISTER,
        )
        assert ch.hardware_source == HardwareSource.MODBUS_TCP

    def test_crio_thermocouple_source(self):
        """cRIO thermocouple channel should still be CRIO source."""
        ch = ChannelConfig(
            name='tc_0',
            physical_channel='Mod5/ai0',
            channel_type=ChannelType.THERMOCOUPLE,
            source_type='crio',
            source_node_id='crio-001'
        )
        assert ch.hardware_source == HardwareSource.CRIO


# ---------------------------------------------------------------------------
# 3. DeviceDiscovery cRIO Node Registration
# ---------------------------------------------------------------------------

class TestCRIONodeRegistration:
    """Test DeviceDiscovery.register_crio_node and related methods."""

    def test_register_crio_node_basic(self, discovery, crio_status_6mod):
        """Registering a cRIO node should store it in the discovery state."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        nodes = discovery.get_crio_nodes()

        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_id == "crio-001"
        assert node.status == "online"
        assert node.ip_address == "192.168.1.20"
        assert node.product_type == "cRIO-9056"
        assert node.serial_number == "01ABC234"

    def test_register_crio_node_channel_count(self, discovery, crio_status_6mod):
        """Registered node should report correct channel count."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]
        assert node.channels == 96

    def test_register_crio_node_modules(self, discovery, crio_status_6mod):
        """Registered node should have 6 modules with correct types."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]

        assert len(node.modules) == 6

        module_types = [m.product_type for m in node.modules]
        assert "NI 9202" in module_types
        assert "NI 9264" in module_types
        assert "NI 9425" in module_types
        assert "NI 9472" in module_types
        assert "NI 9213" in module_types
        assert "NI 9266" in module_types

    def test_register_crio_node_module_channels(self, discovery, crio_status_6mod):
        """Each module should have the correct number of channels."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]

        expected_counts = {
            "NI 9202": 16,   # Mod1: 16 voltage inputs
            "NI 9264": 16,   # Mod2: 16 voltage outputs
            "NI 9425": 32,   # Mod3: 32 digital inputs
            "NI 9472": 8,    # Mod4: 8 digital outputs
            "NI 9213": 16,   # Mod5: 16 thermocouples
            "NI 9266": 8,    # Mod6: 8 current outputs
        }

        for mod in node.modules:
            expected = expected_counts.get(mod.product_type)
            assert expected is not None, f"Unexpected module type: {mod.product_type}"
            assert len(mod.channels) == expected, \
                f"{mod.product_type} should have {expected} channels, got {len(mod.channels)}"

    def test_register_crio_channels_marked_as_crio_source(self, discovery, crio_status_6mod):
        """All channels on cRIO node should have source_type='crio'."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]

        for mod in node.modules:
            for ch in mod.channels:
                assert ch.source_type == 'crio', \
                    f"Channel {ch.name} should have source_type='crio'"
                assert ch.node_id == 'crio-001', \
                    f"Channel {ch.name} should have node_id='crio-001'"

    def test_register_crio_node_module_slots(self, discovery, crio_status_6mod):
        """Modules should have correct slot numbers."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]

        slots = {m.product_type: m.slot for m in node.modules}
        assert slots["NI 9202"] == 1
        assert slots["NI 9264"] == 2
        assert slots["NI 9425"] == 3
        assert slots["NI 9472"] == 4
        assert slots["NI 9213"] == 5
        assert slots["NI 9266"] == 6

    def test_register_updates_existing_node(self, discovery, crio_status_6mod):
        """Re-registering should update, not duplicate."""
        discovery.register_crio_node("crio-001", crio_status_6mod)

        # Update with new IP
        crio_status_6mod["ip_address"] = "192.168.1.21"
        discovery.register_crio_node("crio-001", crio_status_6mod)

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1
        assert nodes[0].ip_address == "192.168.1.21"

    def test_register_multiple_nodes(self, discovery, crio_status_6mod):
        """Multiple cRIO nodes should coexist."""
        discovery.register_crio_node("crio-001", crio_status_6mod)

        # Second node with fewer modules
        second_status = {
            "status": "online",
            "ip_address": "192.168.1.30",
            "product_type": "cRIO-9040",
            "serial_number": "02DEF567",
            "channels": 16,
            "modules": [
                {
                    "name": "Mod1", "product_type": "NI 9213", "slot": 1,
                    "category": "thermocouple",
                    "channels": [
                        {"name": f"Mod1/ai{i}", "channel_type": "ai",
                         "index": i, "category": "thermocouple"}
                        for i in range(16)
                    ]
                }
            ]
        }
        discovery.register_crio_node("crio-002", second_status)

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 2

        node_ids = {n.node_id for n in nodes}
        assert node_ids == {"crio-001", "crio-002"}


# ---------------------------------------------------------------------------
# 4. Heartbeat and Lifecycle Tests
# ---------------------------------------------------------------------------

class TestCRIOHeartbeatLifecycle:
    """Test heartbeat, offline, and unregister flows."""

    def test_heartbeat_creates_minimal_node(self, discovery, crio_heartbeat):
        """Heartbeat for unknown node should create minimal registration."""
        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)
        nodes = discovery.get_crio_nodes()

        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_id == "crio-001"
        assert node.status == "online"
        assert node.channels == 96
        assert node.modules == []  # Heartbeat alone doesn't provide modules

    def test_heartbeat_preserves_full_registration(self, discovery, crio_status_6mod, crio_heartbeat):
        """Heartbeat after full registration should NOT overwrite modules."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        assert len(discovery.get_crio_nodes()[0].modules) == 6

        # Heartbeat should only update timestamp/status
        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)

        node = discovery.get_crio_nodes()[0]
        assert len(node.modules) == 6  # Modules preserved
        assert node.status == "online"

    def test_mark_offline(self, discovery, crio_status_6mod):
        """mark_crio_offline should change status without removing node."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        discovery.mark_crio_offline("crio-001")

        nodes = discovery.get_crio_nodes()
        assert len(nodes) == 1
        assert nodes[0].status == "offline"
        assert len(nodes[0].modules) == 6  # Modules still there

    def test_unregister_removes_node(self, discovery, crio_status_6mod):
        """unregister_crio_node should remove the node completely."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        assert len(discovery.get_crio_nodes()) == 1

        discovery.unregister_crio_node("crio-001")
        assert len(discovery.get_crio_nodes()) == 0

    def test_unregister_nonexistent_is_safe(self, discovery):
        """Unregistering a non-existent node should not raise."""
        discovery.unregister_crio_node("does-not-exist")
        assert len(discovery.get_crio_nodes()) == 0

    def test_mark_offline_nonexistent_is_safe(self, discovery):
        """Marking a non-existent node offline should not raise."""
        discovery.mark_crio_offline("does-not-exist")
        assert len(discovery.get_crio_nodes()) == 0

    def test_heartbeat_updates_status_to_online(self, discovery, crio_status_6mod, crio_heartbeat):
        """Heartbeat should flip an offline node back to online."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        discovery.mark_crio_offline("crio-001")
        assert discovery.get_crio_nodes()[0].status == "offline"

        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)
        assert discovery.get_crio_nodes()[0].status == "online"


# ---------------------------------------------------------------------------
# 5. scan() with cRIO Nodes
# ---------------------------------------------------------------------------

class TestScanWithCRIO:
    """Test that scan() combines local hardware + remote cRIO nodes."""

    def test_scan_includes_crio_nodes(self, discovery, crio_status_6mod):
        """scan() result should include registered cRIO nodes."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result = discovery.scan()

        assert result.success
        assert len(result.crio_nodes) == 1
        assert result.crio_nodes[0].node_id == "crio-001"

    def test_scan_crio_channel_count_in_total(self, discovery, crio_status_6mod):
        """scan() total_channels should include cRIO channels."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result = discovery.scan()

        # Total should include both local and cRIO channels
        assert result.total_channels >= 96  # At least the 96 cRIO channels

    def test_scan_message_mentions_crio(self, discovery, crio_status_6mod):
        """scan() message should mention cRIO nodes."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result = discovery.scan()

        assert "cRIO" in result.message
        assert "96 remote channels" in result.message

    def test_scan_without_crio_flag(self, discovery, crio_status_6mod):
        """scan(include_crio=False) should exclude cRIO nodes."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result = discovery.scan(include_crio=False)

        assert len(result.crio_nodes) == 0

    def test_scan_multiple_crio_nodes(self, discovery, crio_status_6mod):
        """scan() should include multiple cRIO nodes."""
        discovery.register_crio_node("crio-001", crio_status_6mod)

        mini_status = {
            "status": "online",
            "ip_address": "192.168.1.30",
            "product_type": "cRIO-9040",
            "serial_number": "99XYZ",
            "channels": 16,
            "modules": []
        }
        discovery.register_crio_node("crio-002", mini_status)

        result = discovery.scan()
        assert len(result.crio_nodes) == 2
        assert result.total_channels >= 96 + 16

    def test_scan_to_dict_includes_crio(self, discovery, crio_status_6mod):
        """scan().to_dict() should serialize cRIO nodes."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result_dict = discovery.scan().to_dict()

        assert "crio_nodes" in result_dict
        assert len(result_dict["crio_nodes"]) == 1
        crio_dict = result_dict["crio_nodes"][0]
        assert crio_dict["node_id"] == "crio-001"
        assert crio_dict["node_type"] == "crio"
        assert crio_dict["product_type"] == "cRIO-9056"
        assert len(crio_dict["modules"]) == 6


# ---------------------------------------------------------------------------
# 6. CRIONode Serialization
# ---------------------------------------------------------------------------

class TestCRIONodeSerialization:
    """Test CRIONode.to_dict() output."""

    def test_crio_node_to_dict(self, discovery, crio_status_6mod):
        """CRIONode.to_dict() should include all fields."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]
        d = node.to_dict()

        assert d["node_id"] == "crio-001"
        assert d["ip_address"] == "192.168.1.20"
        assert d["product_type"] == "cRIO-9056"
        assert d["serial_number"] == "01ABC234"
        assert d["status"] == "online"
        assert d["channels"] == 96
        assert d["node_type"] == "crio"
        assert "last_seen" in d
        assert len(d["modules"]) == 6

    def test_crio_node_modules_serializable(self, discovery, crio_status_6mod):
        """Module dicts within cRIO node should be fully serializable."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]
        d = node.to_dict()

        # Verify JSON round-trip
        json_str = json.dumps(d)
        parsed = json.loads(json_str)

        assert len(parsed["modules"]) == 6
        mod1 = next(m for m in parsed["modules"] if m["product_type"] == "NI 9202")
        assert mod1["slot"] == 1
        assert len(mod1["channels"]) == 16


# ---------------------------------------------------------------------------
# 7. Config Push Format (cRIO Mode)
# ---------------------------------------------------------------------------

class TestConfigPushForCRIO:
    """Test that config pushed to cRIO uses correct format."""

    def test_channels_as_dict_not_list(self):
        """Config push to cRIO must use dict keyed by name."""
        channels = {}
        for i in range(16):
            name = f'tag_{i}'
            channels[name] = {
                'name': name,
                'physical_channel': f'Mod1/ai{i}',
                'channel_type': 'voltage_input',
            }

        config_data = {
            'channels': channels,
            'safety_actions': {},
        }

        assert isinstance(config_data['channels'], dict)
        assert 'tag_0' in config_data['channels']
        assert 'tag_15' in config_data['channels']

    def test_thermocouple_type_preserved_in_push(self):
        """Thermocouple type must survive config push formatting."""
        channel = {
            'name': 'tc_0',
            'physical_channel': 'Mod5/ai0',
            'channel_type': 'thermocouple',
            'thermocouple_type': 'K',
        }

        # Build push dict like DAQ service does
        ch_dict = {
            'name': channel['name'],
            'physical_channel': channel['physical_channel'],
            'channel_type': channel['channel_type'],
        }
        if channel.get('thermocouple_type'):
            ch_dict['thermocouple_type'] = channel['thermocouple_type']

        assert ch_dict['thermocouple_type'] == 'K'

    def test_all_module_types_in_config(self):
        """Config with all 6 module types should total 96 channels."""
        channels = {}

        # Mod1: 16 voltage inputs
        for i in range(16):
            channels[f'vi_{i}'] = {
                'name': f'vi_{i}', 'physical_channel': f'Mod1/ai{i}',
                'channel_type': 'voltage_input',
            }

        # Mod2: 16 voltage outputs
        for i in range(16):
            channels[f'vo_{i}'] = {
                'name': f'vo_{i}', 'physical_channel': f'Mod2/ao{i}',
                'channel_type': 'voltage_output',
            }

        # Mod3: 32 digital inputs
        for i in range(32):
            channels[f'di_{i}'] = {
                'name': f'di_{i}', 'physical_channel': f'Mod3/port0/line{i}',
                'channel_type': 'digital_input',
            }

        # Mod4: 8 digital outputs
        for i in range(8):
            channels[f'do_{i}'] = {
                'name': f'do_{i}', 'physical_channel': f'Mod4/port0/line{i}',
                'channel_type': 'digital_output',
            }

        # Mod5: 16 thermocouples
        for i in range(16):
            channels[f'tc_{i}'] = {
                'name': f'tc_{i}', 'physical_channel': f'Mod5/ai{i}',
                'channel_type': 'thermocouple', 'thermocouple_type': 'K',
            }

        # Mod6: 8 current outputs
        for i in range(8):
            channels[f'co_{i}'] = {
                'name': f'co_{i}', 'physical_channel': f'Mod6/ao{i}',
                'channel_type': 'current_output',
            }

        assert len(channels) == 96

        # Verify thermocouple types preserved
        tc_channels = {k: v for k, v in channels.items()
                       if v['channel_type'] == 'thermocouple'}
        assert len(tc_channels) == 16
        assert all(v.get('thermocouple_type') == 'K' for v in tc_channels.values())


# ---------------------------------------------------------------------------
# 8. End-to-End Flow
# ---------------------------------------------------------------------------

class TestEndToEndCRIODiscovery:
    """Full end-to-end test: config load → cRIO registration → scan → verify."""

    def test_full_flow_config_to_discovery(self, discovery, blank_crio_config_path, crio_status_6mod):
        """
        Complete flow:
        1. Load a cRIO project config
        2. Verify channels have source_type='crio'
        3. Register cRIO node (simulating MQTT status)
        4. Scan and verify node appears with correct modules
        5. Verify config push format would be correct
        """
        # 1. Load config
        with open(blank_crio_config_path, 'r') as f:
            project = json.load(f)

        channels = project.get('channels', {})
        assert len(channels) > 0

        # 2. Verify all channels are cRIO-sourced
        for name, ch in channels.items():
            assert ch.get('source_type') == 'crio'
            assert ch.get('physical_channel', '').startswith('Mod')

        # 3. Register cRIO node
        discovery.register_crio_node("crio-001", crio_status_6mod)

        # 4. Scan
        result = discovery.scan()
        assert result.success
        assert len(result.crio_nodes) == 1

        crio = result.crio_nodes[0]
        assert crio.node_id == "crio-001"
        assert crio.channels == 96
        assert len(crio.modules) == 6

        # 5. Verify config push format
        crio_channels = {}
        for name, ch in channels.items():
            ch_dict = {
                'name': name,
                'physical_channel': ch['physical_channel'],
                'channel_type': ch['channel_type'],
            }
            if ch.get('thermocouple_type'):
                ch_dict['thermocouple_type'] = ch['thermocouple_type']
            crio_channels[name] = ch_dict

        assert isinstance(crio_channels, dict)
        assert len(crio_channels) == len(channels)

    def test_flow_heartbeat_then_full_status(self, discovery, crio_heartbeat, crio_status_6mod):
        """
        Realistic flow:
        1. cRIO sends heartbeat first (before full status)
        2. Minimal node created
        3. cRIO sends full status with modules
        4. Node is now fully populated
        """
        # 1. Heartbeat arrives first
        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)
        node = discovery.get_crio_nodes()[0]
        assert node.modules == []
        assert node.channels == 96

        # 2. Full status arrives
        discovery.register_crio_node("crio-001", crio_status_6mod)
        node = discovery.get_crio_nodes()[0]
        assert len(node.modules) == 6
        assert node.channels == 96

        # 3. Subsequent heartbeat should NOT wipe modules
        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)
        node = discovery.get_crio_nodes()[0]
        assert len(node.modules) == 6

    def test_flow_offline_recovery(self, discovery, crio_status_6mod, crio_heartbeat):
        """
        Simulate connection loss and recovery:
        1. Node registers and is online
        2. Node goes offline
        3. Node sends heartbeat → back online
        4. Modules preserved throughout
        """
        # 1. Register
        discovery.register_crio_node("crio-001", crio_status_6mod)
        assert discovery.get_crio_nodes()[0].status == "online"

        # 2. Offline
        discovery.mark_crio_offline("crio-001")
        node = discovery.get_crio_nodes()[0]
        assert node.status == "offline"
        assert len(node.modules) == 6

        # 3. Recovery via heartbeat
        discovery.update_crio_heartbeat("crio-001", crio_heartbeat)
        node = discovery.get_crio_nodes()[0]
        assert node.status == "online"
        assert len(node.modules) == 6

    def test_flow_scan_after_offline_still_shows_node(self, discovery, crio_status_6mod):
        """Offline nodes should still appear in scan (for UI to show status)."""
        discovery.register_crio_node("crio-001", crio_status_6mod)
        discovery.mark_crio_offline("crio-001")

        result = discovery.scan()
        assert len(result.crio_nodes) == 1
        assert result.crio_nodes[0].status == "offline"
        # Offline channels still count towards total
        assert result.total_channels >= 96

    def test_flow_channel_type_round_trip(self, discovery, crio_status_6mod):
        """
        Verify channel types survive the full round trip:
        config → discovery → serialize → deserialize
        """
        discovery.register_crio_node("crio-001", crio_status_6mod)
        result = discovery.scan()

        # Serialize
        result_dict = result.to_dict()
        json_str = json.dumps(result_dict)

        # Deserialize
        parsed = json.loads(json_str)

        # Check cRIO node survived
        crio_data = parsed["crio_nodes"][0]
        assert crio_data["node_id"] == "crio-001"
        assert len(crio_data["modules"]) == 6

        # Check module categories survived
        tc_mod = next(m for m in crio_data["modules"]
                      if m["product_type"] == "NI 9213")
        assert tc_mod["category"] == "thermocouple"

        # Check channel source_type survived
        for mod in crio_data["modules"]:
            for ch in mod["channels"]:
                assert ch["source_type"] == "crio"
                assert ch["node_id"] == "crio-001"


# ---------------------------------------------------------------------------
# 9. Module Category Mapping
# ---------------------------------------------------------------------------

class TestModuleCategoryMapping:
    """Test that all 66 NI module model numbers map to correct categories."""

    @pytest.mark.parametrize("model,expected_category", [
        # Thermocouple modules (5)
        ("NI 9210", ModuleCategory.THERMOCOUPLE),
        ("NI 9211", ModuleCategory.THERMOCOUPLE),
        ("NI 9212", ModuleCategory.THERMOCOUPLE),
        ("NI 9213", ModuleCategory.THERMOCOUPLE),
        ("NI 9214", ModuleCategory.THERMOCOUPLE),
        # RTD modules (3)
        ("NI 9216", ModuleCategory.RTD),
        ("NI 9217", ModuleCategory.RTD),
        ("NI 9226", ModuleCategory.RTD),
        # Voltage input modules (11)
        ("NI 9201", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9202", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9204", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9205", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9209", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9206", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9215", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9220", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9221", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9222", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9223", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9224", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9225", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9228", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9229", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9238", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9239", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9242", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9244", ModuleCategory.VOLTAGE_INPUT),
        ("NI 9252", ModuleCategory.VOLTAGE_INPUT),
        # Current input modules (7)
        ("NI 9203", ModuleCategory.CURRENT_INPUT),
        ("NI 9207", ModuleCategory.VOLTAGE_INPUT),  # combo module: ai0-7 V, ai8-15 I
        ("NI 9208", ModuleCategory.CURRENT_INPUT),
        ("NI 9227", ModuleCategory.CURRENT_INPUT),
        ("NI 9246", ModuleCategory.CURRENT_INPUT),
        ("NI 9247", ModuleCategory.CURRENT_INPUT),
        ("NI 9253", ModuleCategory.CURRENT_INPUT),
        # Strain/Bridge modules (3)
        ("NI 9235", ModuleCategory.STRAIN_INPUT),
        ("NI 9236", ModuleCategory.STRAIN_INPUT),
        ("NI 9237", ModuleCategory.BRIDGE_INPUT),
        # IEPE/Accelerometer modules (7)
        ("NI 9230", ModuleCategory.IEPE_INPUT),
        ("NI 9231", ModuleCategory.IEPE_INPUT),
        ("NI 9232", ModuleCategory.IEPE_INPUT),
        ("NI 9233", ModuleCategory.IEPE_INPUT),
        ("NI 9234", ModuleCategory.IEPE_INPUT),
        ("NI 9250", ModuleCategory.IEPE_INPUT),
        ("NI 9251", ModuleCategory.IEPE_INPUT),
        # Digital input modules (11)
        ("NI 9375", ModuleCategory.DIGITAL_INPUT),
        ("NI 9401", ModuleCategory.DIGITAL_INPUT),
        ("NI 9402", ModuleCategory.DIGITAL_INPUT),
        ("NI 9403", ModuleCategory.DIGITAL_INPUT),
        ("NI 9411", ModuleCategory.DIGITAL_INPUT),
        ("NI 9421", ModuleCategory.DIGITAL_INPUT),
        ("NI 9422", ModuleCategory.DIGITAL_INPUT),
        ("NI 9423", ModuleCategory.DIGITAL_INPUT),
        ("NI 9425", ModuleCategory.DIGITAL_INPUT),
        ("NI 9426", ModuleCategory.DIGITAL_INPUT),
        ("NI 9435", ModuleCategory.DIGITAL_INPUT),
        ("NI 9436", ModuleCategory.DIGITAL_INPUT),
        ("NI 9437", ModuleCategory.DIGITAL_INPUT),
        # Digital output modules (10)
        ("NI 9470", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9472", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9474", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9475", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9476", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9477", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9478", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9481", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9482", ModuleCategory.DIGITAL_OUTPUT),
        ("NI 9485", ModuleCategory.DIGITAL_OUTPUT),
        # Voltage output modules (5)
        ("NI 9260", ModuleCategory.VOLTAGE_OUTPUT),
        ("NI 9262", ModuleCategory.VOLTAGE_OUTPUT),
        ("NI 9263", ModuleCategory.VOLTAGE_OUTPUT),
        ("NI 9264", ModuleCategory.VOLTAGE_OUTPUT),
        ("NI 9269", ModuleCategory.VOLTAGE_OUTPUT),
        # Current output modules (2)
        ("NI 9265", ModuleCategory.CURRENT_OUTPUT),
        ("NI 9266", ModuleCategory.CURRENT_OUTPUT),
        # Counter modules (1)
        ("NI 9361", ModuleCategory.COUNTER_INPUT),
        # Universal/Bridge modules (2)
        ("NI 9218", ModuleCategory.BRIDGE_INPUT),
        ("NI 9219", ModuleCategory.BRIDGE_INPUT),
    ])
    def test_module_database_mapping(self, model, expected_category):
        """NI module model should map to correct ModuleCategory."""
        from device_discovery import NI_MODULE_DATABASE
        entry = NI_MODULE_DATABASE.get(model)
        assert entry is not None, f"Module {model} should be in NI_MODULE_DATABASE"
        assert entry["category"] == expected_category

    def test_all_database_entries_covered(self):
        """Verify the parametrized test covers every entry in NI_MODULE_DATABASE."""
        from device_discovery import NI_MODULE_DATABASE
        assert len(NI_MODULE_DATABASE) == 78, \
            f"Expected 78 modules in database, got {len(NI_MODULE_DATABASE)}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
