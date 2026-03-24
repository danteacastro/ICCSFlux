"""
Integration tests for cRIO Node V2 and DAQ Service config flow.

Tests the data format compatibility between:
- Dashboard -> DAQ Service (channels as list)
- DAQ Service -> cRIO Node (channels as dict)
- cRIO Node config parsing and hardware task creation
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Import the modules under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))

class TestChannelFormatConversion:
    """Test that channel format conversion works correctly."""

    def test_list_to_dict_conversion(self):
        """DAQ service should convert channels list to dict before pushing to cRIO."""
        # This is what the dashboard sends (list format)
        channels_list = [
            {'name': 'TC001', 'channel_type': 'thermocouple', 'physical_channel': 'Mod5/ai0'},
            {'name': 'TC002', 'channel_type': 'thermocouple', 'physical_channel': 'Mod5/ai1'},
            {'name': 'V001', 'channel_type': 'voltage_input', 'physical_channel': 'Mod1/ai0'},
            {'name': 'DI001', 'channel_type': 'digital_input', 'physical_channel': 'Mod3/port0/line0'},
        ]

        # Simulate the conversion logic from daq_service.py
        if isinstance(channels_list, list):
            channels_dict = {ch.get('name'): ch for ch in channels_list if ch.get('name')}
        else:
            channels_dict = channels_list

        # Verify conversion
        assert isinstance(channels_dict, dict)
        assert len(channels_dict) == 4
        assert 'TC001' in channels_dict
        assert 'TC002' in channels_dict
        assert 'V001' in channels_dict
        assert 'DI001' in channels_dict
        assert channels_dict['TC001']['channel_type'] == 'thermocouple'
        assert channels_dict['V001']['physical_channel'] == 'Mod1/ai0'

    def test_empty_list_conversion(self):
        """Empty list should convert to empty dict."""
        channels_list = []

        if isinstance(channels_list, list):
            channels_dict = {ch.get('name'): ch for ch in channels_list if ch.get('name')}
        else:
            channels_dict = channels_list

        assert isinstance(channels_dict, dict)
        assert len(channels_dict) == 0

    def test_dict_passthrough(self):
        """If already a dict, should pass through unchanged."""
        channels_dict_input = {
            'TC001': {'name': 'TC001', 'channel_type': 'thermocouple'},
        }

        if isinstance(channels_dict_input, list):
            channels_dict = {ch.get('name'): ch for ch in channels_dict_input if ch.get('name')}
        else:
            channels_dict = channels_dict_input

        assert channels_dict is channels_dict_input

    def test_channels_without_name_skipped(self):
        """Channels without a name should be skipped."""
        channels_list = [
            {'name': 'TC001', 'channel_type': 'thermocouple'},
            {'channel_type': 'voltage_input'},  # No name - should be skipped
            {'name': '', 'channel_type': 'digital_input'},  # Empty name - should be skipped
            {'name': 'V001', 'channel_type': 'voltage_input'},
        ]

        if isinstance(channels_list, list):
            channels_dict = {ch.get('name'): ch for ch in channels_list if ch.get('name')}
        else:
            channels_dict = channels_list

        assert len(channels_dict) == 2
        assert 'TC001' in channels_dict
        assert 'V001' in channels_dict

class TestCRIONodeConfigParsing:
    """Test that cRIO node can parse config correctly."""

    def test_config_full_with_dict_channels(self):
        """cRIO node should handle dict channels correctly."""
        from crio_node_v2.crio_node import NodeConfig

        config_data = {
            'node_id': 'crio-001',
            'mqtt_broker': '192.168.1.1',
            'mqtt_port': 1883,
            'channels': {
                'TC001': {
                    'name': 'TC001',
                    'channel_type': 'thermocouple',
                    'physical_channel': 'Mod5/ai0',
                    'thermocouple_type': 'K',
                },
                'V001': {
                    'name': 'V001',
                    'channel_type': 'voltage_input',
                    'physical_channel': 'Mod1/ai0',
                    'voltage_range': 10.0,
                },
            },
        }

        config = NodeConfig.from_dict(config_data)

        assert config.node_id == 'crio-001'
        assert len(config.channels) == 2
        assert 'TC001' in config.channels
        assert 'V001' in config.channels
        assert config.channels['TC001'].channel_type == 'thermocouple'
        assert config.channels['V001'].channel_type == 'voltage_input'

    def test_thermocouple_type_inference(self):
        """Thermocouple channels without explicit type should default to K."""
        from crio_node_v2.crio_node import NodeConfig

        config_data = {
            'node_id': 'crio-001',
            'mqtt_broker': '192.168.1.1',
            'channels': {
                'TC001': {
                    'name': 'TC001',
                    'channel_type': 'thermocouple',
                    'physical_channel': 'Mod5/ai0',
                    # No thermocouple_type specified
                },
            },
        }

        config = NodeConfig.from_dict(config_data)

        # Should default to 'K' type
        assert config.channels['TC001'].thermocouple_type == 'K'

class TestChannelTypeMapping:
    """Test channel type to internal type mapping."""

    def test_channel_type_internal_mapping(self):
        """All semantic channel types should map to correct internal types."""
        from crio_node_v2.channel_types import ChannelType

        # Analog inputs -> 'analog_input'
        assert ChannelType.get_internal_type('voltage_input') == 'analog_input'
        assert ChannelType.get_internal_type('current_input') == 'analog_input'
        assert ChannelType.get_internal_type('thermocouple') == 'analog_input'
        assert ChannelType.get_internal_type('rtd') == 'analog_input'
        assert ChannelType.get_internal_type('strain_input') == 'analog_input'
        assert ChannelType.get_internal_type('bridge_input') == 'analog_input'
        assert ChannelType.get_internal_type('iepe_input') == 'analog_input'
        assert ChannelType.get_internal_type('resistance_input') == 'analog_input'

        # Analog outputs -> 'analog_output'
        assert ChannelType.get_internal_type('voltage_output') == 'analog_output'
        assert ChannelType.get_internal_type('current_output') == 'analog_output'

        # Digital -> 'digital_input' / 'digital_output'
        assert ChannelType.get_internal_type('digital_input') == 'digital_input'
        assert ChannelType.get_internal_type('digital_output') == 'digital_output'

        # Counter -> 'counter_input' / 'counter_output'
        assert ChannelType.get_internal_type('counter_input') == 'counter_input'
        assert ChannelType.get_internal_type('counter_output') == 'counter_output'
        assert ChannelType.get_internal_type('frequency_input') == 'counter_input'
        assert ChannelType.get_internal_type('pulse_output') == 'counter_output'

    def test_legacy_type_mapping(self):
        """Legacy channel types should map to correct internal types."""
        from crio_node_v2.channel_types import ChannelType

        # Legacy aliases
        assert ChannelType.get_internal_type('voltage') == 'analog_input'
        assert ChannelType.get_internal_type('current') == 'analog_input'
        assert ChannelType.get_internal_type('strain') == 'analog_input'
        assert ChannelType.get_internal_type('iepe') == 'analog_input'
        assert ChannelType.get_internal_type('resistance') == 'analog_input'
        assert ChannelType.get_internal_type('counter') == 'counter_input'
        assert ChannelType.get_internal_type('analog_input') == 'analog_input'
        assert ChannelType.get_internal_type('analog_output') == 'analog_output'

    def test_module_type_mapping(self):
        """NI module numbers should map to correct channel types."""
        from crio_node_v2.channel_types import get_module_channel_type, ChannelType

        # Voltage input modules
        assert get_module_channel_type('9201') == ChannelType.VOLTAGE_INPUT
        assert get_module_channel_type('9202') == ChannelType.VOLTAGE_INPUT
        assert get_module_channel_type('9205') == ChannelType.VOLTAGE_INPUT
        assert get_module_channel_type('NI 9205') == ChannelType.VOLTAGE_INPUT

        # Current input modules
        assert get_module_channel_type('9203') == ChannelType.CURRENT_INPUT
        assert get_module_channel_type('9208') == ChannelType.CURRENT_INPUT

        # Thermocouple modules
        assert get_module_channel_type('9210') == ChannelType.THERMOCOUPLE
        assert get_module_channel_type('9211') == ChannelType.THERMOCOUPLE
        assert get_module_channel_type('9212') == ChannelType.THERMOCOUPLE
        assert get_module_channel_type('9213') == ChannelType.THERMOCOUPLE
        assert get_module_channel_type('9214') == ChannelType.THERMOCOUPLE

        # RTD modules
        assert get_module_channel_type('9216') == ChannelType.RTD
        assert get_module_channel_type('9217') == ChannelType.RTD

        # Digital modules
        assert get_module_channel_type('9421') == ChannelType.DIGITAL_INPUT
        assert get_module_channel_type('9472') == ChannelType.DIGITAL_OUTPUT
        assert get_module_channel_type('9474') == ChannelType.DIGITAL_OUTPUT

        # Analog output modules
        assert get_module_channel_type('9263') == ChannelType.VOLTAGE_OUTPUT
        assert get_module_channel_type('9265') == ChannelType.CURRENT_OUTPUT

class TestEndToEndConfigFlow:
    """Test the complete config flow from dashboard to cRIO."""

    def test_full_config_flow(self):
        """Test complete config flow: dashboard list -> DAQ dict -> cRIO parsing."""
        from crio_node_v2.crio_node import NodeConfig
        from crio_node_v2.channel_types import ChannelType

        # Step 1: Dashboard sends config with channels as list
        dashboard_payload = {
            'node_id': 'crio-001',
            'channels': [
                {
                    'name': 'TC001',
                    'channel_type': 'thermocouple',
                    'physical_channel': 'Mod5/ai0',
                    'thermocouple_type': 'K',
                },
                {
                    'name': 'TC002',
                    'channel_type': 'thermocouple',
                    'physical_channel': 'Mod5/ai1',
                },
                {
                    'name': 'V001',
                    'channel_type': 'voltage_input',
                    'physical_channel': 'Mod1/ai0',
                    'voltage_range': 10.0,
                },
                {
                    'name': 'DI001',
                    'channel_type': 'digital_input',
                    'physical_channel': 'Mod3/port0/line0',
                },
                {
                    'name': 'DO001',
                    'channel_type': 'digital_output',
                    'physical_channel': 'Mod4/port0/line0',
                },
            ],
            'scan_rate_hz': 100,
            'publish_rate_hz': 10,
        }

        # Step 2: DAQ service converts list to dict (simulating daq_service.py logic)
        channels_raw = dashboard_payload.get('channels', [])
        if isinstance(channels_raw, list):
            channels_dict = {ch.get('name'): ch for ch in channels_raw if ch.get('name')}
        else:
            channels_dict = channels_raw

        config_data = {
            'node_id': dashboard_payload.get('node_id'),
            'mqtt_broker': '192.168.1.1',
            'mqtt_port': 1883,
            'channels': channels_dict,
            'scan_rate_hz': dashboard_payload.get('scan_rate_hz', 100),
            'publish_rate_hz': dashboard_payload.get('publish_rate_hz', 10),
        }

        # Step 3: cRIO node parses the config
        config = NodeConfig.from_dict(config_data)

        # Verify the complete flow
        assert config.node_id == 'crio-001'
        assert len(config.channels) == 5

        # Check thermocouple channels
        tc001 = config.channels['TC001']
        assert tc001.channel_type == 'thermocouple'
        assert tc001.thermocouple_type == 'K'
        assert ChannelType.get_internal_type(tc001.channel_type) == 'analog_input'

        tc002 = config.channels['TC002']
        assert tc002.channel_type == 'thermocouple'
        assert tc002.thermocouple_type == 'K'  # Should default to K

        # Check voltage channel
        v001 = config.channels['V001']
        assert v001.channel_type == 'voltage_input'
        assert v001.voltage_range == 10.0
        assert ChannelType.get_internal_type(v001.channel_type) == 'analog_input'

        # Check digital channels
        di001 = config.channels['DI001']
        assert di001.channel_type == 'digital_input'
        assert ChannelType.get_internal_type(di001.channel_type) == 'digital_input'

        do001 = config.channels['DO001']
        assert do001.channel_type == 'digital_output'
        assert ChannelType.get_internal_type(do001.channel_type) == 'digital_output'

    def test_config_roundtrip_json(self):
        """Test that config can be serialized and deserialized via JSON (MQTT path)."""
        from crio_node_v2.crio_node import NodeConfig

        # Original dashboard payload
        original_payload = {
            'node_id': 'crio-001',
            'channels': [
                {'name': 'CH001', 'channel_type': 'thermocouple', 'physical_channel': 'Mod5/ai0'},
            ],
        }

        # Convert to dict (DAQ service)
        channels_raw = original_payload.get('channels', [])
        if isinstance(channels_raw, list):
            channels_dict = {ch.get('name'): ch for ch in channels_raw if ch.get('name')}
        else:
            channels_dict = channels_raw

        config_data = {
            'node_id': original_payload['node_id'],
            'mqtt_broker': '192.168.1.1',
            'channels': channels_dict,
        }

        # Serialize to JSON (MQTT publish)
        json_str = json.dumps(config_data)

        # Deserialize from JSON (MQTT receive on cRIO)
        received_data = json.loads(json_str)

        # Parse on cRIO
        config = NodeConfig.from_dict(received_data)

        assert config.node_id == 'crio-001'
        assert 'CH001' in config.channels
        assert config.channels['CH001'].channel_type == 'thermocouple'

class TestHardwareTaskGrouping:
    """Test that hardware.py groups channels correctly by internal type."""

    def test_channel_grouping_by_internal_type(self):
        """Channels should be grouped by internal type for DAQmx tasks."""
        from crio_node_v2.channel_types import ChannelType

        # Simulate channel list with various types
        channels = [
            {'name': 'TC001', 'channel_type': 'thermocouple', 'physical_channel': 'Mod5/ai0'},
            {'name': 'TC002', 'channel_type': 'thermocouple', 'physical_channel': 'Mod5/ai1'},
            {'name': 'V001', 'channel_type': 'voltage_input', 'physical_channel': 'Mod1/ai0'},
            {'name': 'I001', 'channel_type': 'current_input', 'physical_channel': 'Mod2/ai0'},
            {'name': 'DI001', 'channel_type': 'digital_input', 'physical_channel': 'Mod3/port0/line0'},
            {'name': 'DI002', 'channel_type': 'digital_input', 'physical_channel': 'Mod3/port0/line1'},
            {'name': 'DO001', 'channel_type': 'digital_output', 'physical_channel': 'Mod4/port0/line0'},
            {'name': 'AO001', 'channel_type': 'voltage_output', 'physical_channel': 'Mod6/ao0'},
        ]

        # Group by internal type (simulating hardware.py logic)
        ai_channels = []
        ao_channels = []
        di_channels = []
        do_channels = []
        ci_channels = []
        co_channels = []

        for ch in channels:
            internal_type = ChannelType.get_internal_type(ch['channel_type'])
            if internal_type == 'analog_input':
                ai_channels.append(ch)
            elif internal_type == 'analog_output':
                ao_channels.append(ch)
            elif internal_type == 'digital_input':
                di_channels.append(ch)
            elif internal_type == 'digital_output':
                do_channels.append(ch)
            elif internal_type == 'counter_input':
                ci_channels.append(ch)
            elif internal_type == 'counter_output':
                co_channels.append(ch)

        # Verify grouping
        assert len(ai_channels) == 4  # TC001, TC002, V001, I001
        assert len(ao_channels) == 1  # AO001
        assert len(di_channels) == 2  # DI001, DI002
        assert len(do_channels) == 1  # DO001
        assert len(ci_channels) == 0
        assert len(co_channels) == 0

        # Verify AI channels include all analog input types
        ai_types = {ch['channel_type'] for ch in ai_channels}
        assert 'thermocouple' in ai_types
        assert 'voltage_input' in ai_types
        assert 'current_input' in ai_types

class TestModuleGroupingAndMapping:
    """Test that channels are correctly grouped by module and data maps correctly."""

    def test_module_extraction_from_physical_channel(self):
        """Module should be correctly extracted from physical_channel."""
        test_cases = [
            ('Mod1/ai0', 'Mod1'),
            ('Mod5/ai15', 'Mod5'),
            ('Mod3/port0/line0', 'Mod3'),
            ('Mod4/port0/line7', 'Mod4'),
            ('cRIO1/Mod2/ai0', 'cRIO1'),  # Edge case - should handle device prefix
        ]

        for physical_channel, expected_module in test_cases:
            module = physical_channel.split('/')[0]
            assert module == expected_module, f"Failed for {physical_channel}"

    def test_channels_grouped_by_correct_module(self):
        """Each channel must be in the task for its actual physical module."""
        from collections import defaultdict

        # Simulate what hardware.py does
        channels = {
            'V001': {'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
            'V002': {'physical_channel': 'Mod1/ai1', 'channel_type': 'voltage_input'},
            'DI001': {'physical_channel': 'Mod3/port0/line0', 'channel_type': 'digital_input'},
            'DI002': {'physical_channel': 'Mod3/port0/line1', 'channel_type': 'digital_input'},
            'TC001': {'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
            'TC002': {'physical_channel': 'Mod5/ai1', 'channel_type': 'thermocouple'},
        }

        # Group by module (simulating hardware.py _create_tasks)
        by_module = defaultdict(list)
        for name, ch in channels.items():
            module = ch['physical_channel'].split('/')[0]
            by_module[module].append(name)

        # Verify grouping
        assert set(by_module['Mod1']) == {'V001', 'V002'}
        assert set(by_module['Mod3']) == {'DI001', 'DI002'}
        assert set(by_module['Mod5']) == {'TC001', 'TC002'}

        # CRITICAL: Mod1 channels must NOT appear in Mod3 or Mod5 groups
        assert 'V001' not in by_module['Mod3']
        assert 'V001' not in by_module['Mod5']
        assert 'DI001' not in by_module['Mod1']
        assert 'TC001' not in by_module['Mod1']

    def test_data_maps_to_correct_channel_by_index(self):
        """When reading, value[i] must map to the correct channel name."""
        # Simulate a task with channels added in order
        task_channels = ['V001', 'V002', 'V003']  # Added to task in this order

        # DAQmx returns values in the same order channels were added
        raw_values = [1.5, 2.5, 3.5]

        # Map values back to channel names
        result = {}
        for i, ch_name in enumerate(task_channels):
            result[ch_name] = raw_values[i]

        # Verify correct mapping
        assert result['V001'] == 1.5
        assert result['V002'] == 2.5
        assert result['V003'] == 3.5

    def test_channel_order_matches_physical_order(self):
        """Channels in task must be in physical channel order (ai0, ai1, ai2...)."""
        import re

        def get_channel_index(ch):
            """Extract channel index from physical_channel."""
            phys = ch.get('physical_channel', '')
            match = re.search(r'(\d+)$', phys)
            return int(match.group(1)) if match else 0

        # Channels added in random order
        channels = [
            {'name': 'V003', 'physical_channel': 'Mod1/ai2'},
            {'name': 'V001', 'physical_channel': 'Mod1/ai0'},
            {'name': 'V002', 'physical_channel': 'Mod1/ai1'},
        ]

        # Sort by physical index before adding to task
        sorted_channels = sorted(channels, key=get_channel_index)
        task_channel_names = [ch['name'] for ch in sorted_channels]

        # CRITICAL: Task channels must be in physical order
        assert task_channel_names == ['V001', 'V002', 'V003']

        # Now when DAQmx returns [ai0_val, ai1_val, ai2_val],
        # we can correctly map to V001, V002, V003
        raw_values = [10.0, 20.0, 30.0]  # From ai0, ai1, ai2
        result = {task_channel_names[i]: raw_values[i] for i in range(len(raw_values))}

        assert result['V001'] == 10.0  # ai0
        assert result['V002'] == 20.0  # ai1
        assert result['V003'] == 30.0  # ai2

    def test_all_display_sorted_by_module_number(self):
        """ALL display should show channels sorted by module number."""
        import re

        def get_module_number(ch):
            """Extract module number from physical_channel (Mod1 -> 1, Mod5 -> 5)."""
            phys = ch.get('physical_channel', '')
            match = re.search(r'Mod(\d+)', phys)
            return int(match.group(1)) if match else 999

        def get_channel_index(ch):
            """Extract channel index from physical_channel."""
            phys = ch.get('physical_channel', '')
            match = re.search(r'(\d+)$', phys)
            return int(match.group(1)) if match else 0

        # Channels from multiple modules in random order
        channels = [
            {'name': 'TC001', 'physical_channel': 'Mod5/ai0'},
            {'name': 'V001', 'physical_channel': 'Mod1/ai0'},
            {'name': 'DI001', 'physical_channel': 'Mod3/port0/line0'},
            {'name': 'DO001', 'physical_channel': 'Mod4/port0/line0'},
            {'name': 'V002', 'physical_channel': 'Mod1/ai1'},
            {'name': 'TC002', 'physical_channel': 'Mod5/ai1'},
        ]

        # Sort by module number, then by channel index
        sorted_channels = sorted(channels, key=lambda ch: (get_module_number(ch), get_channel_index(ch)))
        sorted_names = [ch['name'] for ch in sorted_channels]

        # Expected: Mod1 channels, then Mod3, then Mod4, then Mod5
        expected = ['V001', 'V002', 'DI001', 'DO001', 'TC001', 'TC002']
        assert sorted_names == expected

    def test_cross_module_data_isolation(self):
        """Data from one module must NEVER appear under another module's channels."""
        # Simulate the full read flow
        from collections import defaultdict

        # Config with channels in different modules
        config_channels = {
            'V001': {'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
            'V002': {'physical_channel': 'Mod1/ai1', 'channel_type': 'voltage_input'},
            'TC001': {'physical_channel': 'Mod5/ai0', 'channel_type': 'thermocouple'},
            'TC002': {'physical_channel': 'Mod5/ai1', 'channel_type': 'thermocouple'},
        }

        # Group by module (like hardware.py does)
        ai_by_module = defaultdict(list)
        for name, ch in config_channels.items():
            module = ch['physical_channel'].split('/')[0]
            ai_by_module[module].append(name)

        # Create task channel tracking (like _ai_channels in hardware.py)
        ai_task_channels = {}
        for module, names in ai_by_module.items():
            task_key = f"AI_{module}"
            ai_task_channels[task_key] = names

        # Simulate reading from each task
        # Mod1 task returns voltage values
        mod1_raw = [1.5, 2.5]  # V001=1.5V, V002=2.5V
        # Mod5 task returns temperature values
        mod5_raw = [25.0, 30.0]  # TC001=25°C, TC002=30°C

        result = {}

        # Read Mod1 task
        for i, ch_name in enumerate(ai_task_channels['AI_Mod1']):
            result[ch_name] = mod1_raw[i]

        # Read Mod5 task
        for i, ch_name in enumerate(ai_task_channels['AI_Mod5']):
            result[ch_name] = mod5_raw[i]

        # CRITICAL ASSERTIONS: Data must be correctly mapped
        assert result['V001'] == 1.5, "V001 should have Mod1 voltage data"
        assert result['V002'] == 2.5, "V002 should have Mod1 voltage data"
        assert result['TC001'] == 25.0, "TC001 should have Mod5 temperature data"
        assert result['TC002'] == 30.0, "TC002 should have Mod5 temperature data"

        # CRITICAL: TC channels must NOT have voltage values
        assert result['TC001'] != 1.5, "TC001 must not have Mod1 data!"
        assert result['TC001'] != 2.5, "TC001 must not have Mod1 data!"

class TestCommandRouting:
    """Test that MQTT command routing works correctly."""

    def test_topic_pattern_matching(self):
        """Command routing should match correct topic patterns."""
        # These are the topic patterns from crio_node.py
        topics = [
            'nisystem/nodes/crio-001/system/acquire/start',
            'nisystem/nodes/crio-001/system/acquire/stop',
            'nisystem/nodes/crio-001/config/full',
            'nisystem/nodes/crio-001/session/start',
            'nisystem/discovery/ping',
        ]

        def match_topic(topic: str) -> str:
            """Simulate command routing logic."""
            if '/system/' in topic:
                if 'acquire/start' in topic or topic.endswith('/start'):
                    return 'acquire_start'
                elif 'acquire/stop' in topic or topic.endswith('/stop'):
                    return 'acquire_stop'
            elif '/config/' in topic:
                if '/full' in topic:
                    return 'config_full'
            elif '/session/' in topic:
                return 'session'
            elif '/discovery/' in topic:
                return 'discovery'
            return 'unknown'

        assert match_topic(topics[0]) == 'acquire_start'
        assert match_topic(topics[1]) == 'acquire_stop'
        assert match_topic(topics[2]) == 'config_full'
        assert match_topic(topics[3]) == 'session'
        assert match_topic(topics[4]) == 'discovery'

    def test_topic_no_false_positives(self):
        """'system' in 'nisystem' should not trigger /system/ handler."""
        # This was a bug we fixed - 'system' in topic was matching 'nisystem'
        topic = 'nisystem/nodes/crio-001/config/full'

        # Wrong way (old bug)
        wrong_match = 'system' in topic  # True - but wrong!

        # Correct way (fixed)
        correct_match = '/system/' in topic  # False - correct!

        assert wrong_match == True  # This shows the bug existed
        assert correct_match == False  # This shows the fix works

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
