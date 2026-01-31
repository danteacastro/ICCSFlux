"""
Unit tests for cFP Node Service

Tests the cFP node's unified API publishing, config handlers, and Modbus operations.
Validates API consistency with DAQ Service and cRIO nodes.
"""

import pytest
import json
import time
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import tempfile
import sys

# Add cfp_node to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'services' / 'cfp_node'))

from cfp_node import (
    CFPNode, CFPConfig, CFPModuleConfig, ModbusChannel, ModbusTCPClient
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def basic_config():
    """Create a basic cFP configuration"""
    return CFPConfig(
        node_id='cfp-test',
        cfp_host='192.168.1.30',
        cfp_port=502,
        mqtt_broker='localhost',
        mqtt_port=1883,
        mqtt_base_topic='nisystem',
        poll_interval=1.0,
        modules=[
            CFPModuleConfig(
                slot=1,
                module_type='cFP-AI-110',
                base_address=0,
                channels=[
                    ModbusChannel(name='temp1', address=0, unit='°C', scale=0.1),
                    ModbusChannel(name='temp2', address=1, unit='°C', scale=0.1),
                ]
            ),
            CFPModuleConfig(
                slot=2,
                module_type='cFP-AO-210',
                base_address=100,
                channels=[
                    ModbusChannel(name='output1', address=100, unit='V', writable=True),
                ]
            ),
        ]
    )


@pytest.fixture
def cfp_node(basic_config):
    """Create a cFP node with mocked MQTT and Modbus"""
    node = CFPNode(basic_config)
    node.mqtt_client = MagicMock()
    node.mqtt_connected = True
    node.modbus = MagicMock()
    return node


# ============================================================================
# TEST: PUBLISH CHANNELS (BATCH FORMAT)
# ============================================================================

class TestPublishChannelsBatch:
    """Test _publish_channels method for unified batch format"""

    def test_publish_channels_batch_format(self, cfp_node):
        """Test channels are published in batch format"""
        values = {'temp1': 25.5, 'temp2': 30.0}

        cfp_node._publish_channels(values)

        cfp_node.mqtt_client.publish.assert_called_once()
        call_args = cfp_node.mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert topic == "nisystem/nodes/cfp-test/channels/batch"
        assert 'temp1' in payload
        assert 'temp2' in payload

    def test_batch_payload_has_required_fields(self, cfp_node):
        """Test batch payload has all required fields for frontend"""
        values = {'temp1': 25.5}

        cfp_node._publish_channels(values)

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        channel_data = payload['temp1']

        # Required fields matching DAQ Service/cRIO format
        assert 'value' in channel_data
        assert 'timestamp' in channel_data
        assert 'acquisition_ts_us' in channel_data
        assert 'units' in channel_data
        assert 'quality' in channel_data
        assert 'status' in channel_data

    def test_batch_payload_values(self, cfp_node):
        """Test batch payload contains correct values"""
        values = {'temp1': 25.5}

        cfp_node._publish_channels(values)

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        channel_data = payload['temp1']

        assert channel_data['value'] == 25.5
        assert channel_data['units'] == '°C'
        assert channel_data['quality'] == 'good'
        assert channel_data['status'] == 'normal'
        assert channel_data['acquisition_ts_us'] > 0

    def test_batch_null_value_shows_bad_quality(self, cfp_node):
        """Test None values show as bad quality"""
        values = {'temp1': None}

        cfp_node._publish_channels(values)

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        channel_data = payload['temp1']

        assert channel_data['value'] is None
        assert channel_data['quality'] == 'bad'
        assert channel_data['status'] == 'disconnected'

    def test_batch_respects_channel_quality(self, cfp_node):
        """Test batch respects stored channel quality"""
        cfp_node.channel_qualities = {'temp1': 'uncertain'}
        values = {'temp1': 25.5}

        cfp_node._publish_channels(values)

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['temp1']['quality'] == 'uncertain'

    def test_batch_no_publish_without_connection(self, cfp_node):
        """Test no publish when MQTT not connected"""
        cfp_node.mqtt_connected = False
        values = {'temp1': 25.5}

        cfp_node._publish_channels(values)

        cfp_node.mqtt_client.publish.assert_not_called()


# ============================================================================
# TEST: PUBLISH SESSION STATUS
# ============================================================================

class TestPublishSessionStatus:
    """Test _publish_session_status method"""

    def test_publish_session_status_topic(self, cfp_node):
        """Test session status published to correct topic"""
        cfp_node._publish_session_status()

        call_args = cfp_node.mqtt_client.publish.call_args
        topic = call_args[0][0]

        assert topic == "nisystem/nodes/cfp-test/session/status"

    def test_publish_session_status_fields(self, cfp_node):
        """Test session status has all required fields"""
        cfp_node.acquiring = True
        cfp_node.recording = False
        cfp_node.session_active = True
        cfp_node.session_id = "session-123"

        cfp_node._publish_session_status()

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert payload['acquiring'] is True
        assert payload['recording'] is False
        assert payload['session_active'] is True
        assert payload['session_id'] == "session-123"
        assert 'timestamp' in payload

    def test_publish_session_idle(self, cfp_node):
        """Test publishing idle session status"""
        cfp_node.acquiring = False
        cfp_node.recording = False
        cfp_node.session_active = False
        cfp_node.session_id = None

        cfp_node._publish_session_status()

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert payload['acquiring'] is False
        assert payload['recording'] is False
        assert payload['session_active'] is False
        assert payload['session_id'] is None


# ============================================================================
# TEST: PUBLISH CONFIG RESPONSE
# ============================================================================

class TestPublishConfigResponse:
    """Test _publish_config_response method"""

    def test_publish_config_response_topic(self, cfp_node):
        """Test config response published to correct topic"""
        cfp_node._publish_config_response('get', True)

        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        assert topic == "nisystem/nodes/cfp-test/config/response"

    def test_publish_config_response_success(self, cfp_node):
        """Test successful config response"""
        cfp_node._publish_config_response('save', True, data={'filename': 'test.json'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert payload['request_type'] == 'save'
        assert payload['success'] is True
        assert payload['data'] == {'filename': 'test.json'}
        assert 'timestamp' in payload

    def test_publish_config_response_failure(self, cfp_node):
        """Test failed config response with error"""
        cfp_node._publish_config_response('load', False, error='File not found')

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert payload['request_type'] == 'load'
        assert payload['success'] is False
        assert payload['error'] == 'File not found'

    def test_publish_config_response_qos1(self, cfp_node):
        """Test config response uses QoS 1"""
        cfp_node._publish_config_response('get', True)

        call_args = cfp_node.mqtt_client.publish.call_args
        # The publish is called with positional args: (topic, payload, qos=1)
        assert call_args[1].get('qos', 1) == 1


# ============================================================================
# TEST: CONFIG HANDLERS
# ============================================================================

class TestConfigHandlers:
    """Test config request handlers"""

    def test_handle_config_get(self, cfp_node):
        """Test config get handler returns configuration"""
        cfp_node._handle_config_get()

        cfp_node.mqtt_client.publish.assert_called_once()
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert payload['request_type'] == 'get'
        assert payload['success'] is True
        assert 'data' in payload

        data = payload['data']
        assert data['node_id'] == 'cfp-test'
        assert data['cfp_host'] == '192.168.1.30'
        assert len(data['modules']) == 2

    def test_handle_config_get_includes_channels(self, cfp_node):
        """Test config get includes channel details"""
        cfp_node._handle_config_get()

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        modules = payload['data']['modules']

        assert len(modules[0]['channels']) == 2
        assert modules[0]['channels'][0]['name'] == 'temp1'
        assert modules[0]['channels'][0]['unit'] == '°C'

    def test_handle_config_save(self, cfp_node):
        """Test config save handler"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the path resolution
            with patch.object(Path, 'parent', Path(tmpdir)):
                cfp_node._handle_config_save({'filename': 'test_config.json'})

        cfp_node.mqtt_client.publish.assert_called()
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['request_type'] == 'save'

    def test_handle_config_load_not_found(self, cfp_node):
        """Test config load handler with missing file"""
        cfp_node._handle_config_load({'filename': 'nonexistent.json'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['request_type'] == 'load'
        assert payload['success'] is False
        assert 'not found' in payload['error'].lower()


# ============================================================================
# TEST: COMMAND HANDLERS
# ============================================================================

class TestCommandHandlers:
    """Test command handlers"""

    def test_handle_command_ping(self, cfp_node):
        """Test ping command response"""
        cfp_node._handle_command('ping', {'request_id': 'req-123'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True
        assert payload['command'] == 'ping'
        assert payload['request_id'] == 'req-123'

    def test_handle_command_info(self, cfp_node):
        """Test info command response"""
        cfp_node._handle_command('info', {'request_id': 'req-456'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True
        assert 'info' in payload

        info = payload['info']
        assert info['node_id'] == 'cfp-test'
        assert info['type'] == 'CompactFieldPoint'
        assert info['modules'] == 2
        assert info['channels'] == 3

    def test_handle_command_modules(self, cfp_node):
        """Test modules command response"""
        cfp_node._handle_command('modules', {})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True
        assert len(payload['modules']) == 2
        assert payload['modules'][0]['type'] == 'cFP-AI-110'

    def test_handle_command_modbus_read(self, cfp_node):
        """Test modbus_read command"""
        cfp_node.modbus.read_holding_registers.return_value = [1234]

        cfp_node._handle_command('modbus_read', {'address': 0, 'count': 1})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True
        assert payload['values'] == [1234]

    def test_handle_command_modbus_write(self, cfp_node):
        """Test modbus_write command"""
        cfp_node.modbus.write_single_register.return_value = True

        cfp_node._handle_command('modbus_write', {'address': 100, 'value': 500})

        cfp_node.modbus.write_single_register.assert_called_once_with(100, 500)
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True


# ============================================================================
# TEST: CHANNEL OPERATIONS
# ============================================================================

class TestChannelOperations:
    """Test channel read/write operations"""

    def test_handle_channel_read_found(self, cfp_node):
        """Test reading existing channel value"""
        cfp_node.channel_values = {'temp1': 25.5}

        cfp_node._handle_channel_read({'channel': 'temp1', 'request_id': 'req-1'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True
        assert payload['channel'] == 'temp1'
        assert payload['value'] == 25.5

    def test_handle_channel_read_not_found(self, cfp_node):
        """Test reading nonexistent channel"""
        cfp_node._handle_channel_read({'channel': 'unknown', 'request_id': 'req-1'})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is False
        assert 'not found' in payload['error'].lower()

    def test_handle_channel_write_success(self, cfp_node):
        """Test writing to writable channel"""
        cfp_node.modbus.write_single_register.return_value = True

        cfp_node._handle_channel_write({
            'channel': 'output1',
            'value': 5.0,
            'request_id': 'req-1'
        })

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is True

    def test_handle_channel_write_not_writable(self, cfp_node):
        """Test writing to read-only channel"""
        cfp_node._handle_channel_write({
            'channel': 'temp1',  # Not writable
            'value': 5.0,
            'request_id': 'req-1'
        })

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['success'] is False
        assert 'not writable' in payload['error'].lower()


# ============================================================================
# TEST: FIND CHANNEL CONFIG
# ============================================================================

class TestFindChannelConfig:
    """Test _find_channel_config helper"""

    def test_find_existing_channel(self, cfp_node):
        """Test finding existing channel configuration"""
        result = cfp_node._find_channel_config('temp1')

        assert result is not None
        assert result.name == 'temp1'
        assert result.unit == '°C'

    def test_find_channel_in_second_module(self, cfp_node):
        """Test finding channel in second module"""
        result = cfp_node._find_channel_config('output1')

        assert result is not None
        assert result.name == 'output1'
        assert result.writable is True

    def test_find_nonexistent_channel(self, cfp_node):
        """Test finding nonexistent channel returns None"""
        result = cfp_node._find_channel_config('unknown')

        assert result is None


# ============================================================================
# TEST: TOPIC FORMAT CONSISTENCY
# ============================================================================

class TestTopicFormatConsistency:
    """Test MQTT topic format matches DAQ Service/cRIO pattern"""

    def test_batch_topic_format(self, cfp_node):
        """Test batch channel topic format"""
        cfp_node._publish_channels({'temp1': 25.5})

        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        assert topic == "nisystem/nodes/cfp-test/channels/batch"

    def test_session_status_topic_format(self, cfp_node):
        """Test session status topic format"""
        cfp_node._publish_session_status()

        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        assert topic == "nisystem/nodes/cfp-test/session/status"

    def test_config_response_topic_format(self, cfp_node):
        """Test config response topic format"""
        cfp_node._publish_config_response('test', True)

        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        assert topic == "nisystem/nodes/cfp-test/config/response"

    def test_custom_base_topic(self, basic_config):
        """Test custom base topic is used"""
        basic_config.mqtt_base_topic = "factory/nisystem"
        node = CFPNode(basic_config)
        node.mqtt_client = MagicMock()
        node.mqtt_connected = True

        node._publish_channels({'temp1': 25.5})

        topic = node.mqtt_client.publish.call_args[0][0]
        assert topic == "factory/nisystem/nodes/cfp-test/channels/batch"


# ============================================================================
# TEST: MODBUS TCP CLIENT
# ============================================================================

class TestModbusTCPClient:
    """Test Modbus TCP client functionality"""

    def test_client_initialization(self):
        """Test client initializes with correct parameters"""
        client = ModbusTCPClient('192.168.1.30', 502, 5.0)

        assert client.host == '192.168.1.30'
        assert client.port == 502
        assert client.timeout == 5.0
        assert client.socket is None
        assert client.transaction_id == 0

    def test_client_not_connected_initially(self):
        """Test client is not connected initially"""
        client = ModbusTCPClient('192.168.1.30')

        assert client.is_connected() is False

    def test_disconnect_handles_none_socket(self):
        """Test disconnect handles None socket gracefully"""
        client = ModbusTCPClient('192.168.1.30')
        client.socket = None

        # Should not raise
        client.disconnect()

        assert client.socket is None


# ============================================================================
# TEST: DISCOVERY
# ============================================================================

class TestDiscovery:
    """Test discovery handling"""

    def test_handle_discovery(self, cfp_node):
        """Test discovery response"""
        cfp_node._handle_discovery()

        cfp_node.mqtt_client.publish.assert_called_once()
        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert topic == "nisystem/discovery/response"
        assert payload['node_id'] == 'cfp-test'
        assert payload['node_type'] == 'cfp'
        assert payload['online'] is True
        assert payload['modules'] == 2


# ============================================================================
# TEST: HEARTBEAT
# ============================================================================

class TestHeartbeat:
    """Test heartbeat publishing"""

    def test_publish_heartbeat(self, cfp_node):
        """Test heartbeat message"""
        cfp_node._publish_heartbeat()

        cfp_node.mqtt_client.publish.assert_called_once()
        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert topic == "nisystem/nodes/cfp-test/heartbeat"
        assert payload['node_id'] == 'cfp-test'
        assert 'timestamp' in payload
        assert 'uptime' in payload


# ============================================================================
# TEST: STATUS
# ============================================================================

class TestStatus:
    """Test status publishing"""

    def test_publish_status(self, cfp_node):
        """Test system status message"""
        cfp_node._publish_status()

        cfp_node.mqtt_client.publish.assert_called_once()
        topic = cfp_node.mqtt_client.publish.call_args[0][0]
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        assert topic == "nisystem/nodes/cfp-test/status/system"
        assert payload['online'] is True
        assert payload['node_id'] == 'cfp-test'
        assert payload['node_type'] == 'cfp'
        assert payload['modules'] == 2

    def test_publish_status_retained(self, cfp_node):
        """Test status message is retained"""
        cfp_node._publish_status()

        call_args = cfp_node.mqtt_client.publish.call_args
        assert call_args[1].get('retain') is True


# ============================================================================
# TEST: API COMPATIBILITY
# ============================================================================

class TestAPICompatibility:
    """Test API compatibility with DAQ Service and cRIO"""

    def test_batch_payload_matches_daq_format(self, cfp_node):
        """Test batch payload matches DAQ Service format"""
        cfp_node._publish_channels({'temp1': 25.5})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        channel = payload['temp1']

        # DAQ Service format requirements
        required_fields = {'value', 'timestamp', 'acquisition_ts_us', 'units', 'quality', 'status'}
        assert required_fields.issubset(set(channel.keys()))

    def test_session_status_matches_daq_format(self, cfp_node):
        """Test session status matches DAQ Service format"""
        cfp_node._publish_session_status()

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        # DAQ Service format requirements
        required_fields = {'acquiring', 'recording', 'session_active', 'timestamp'}
        assert required_fields.issubset(set(payload.keys()))

    def test_config_response_matches_daq_format(self, cfp_node):
        """Test config response matches DAQ Service format"""
        cfp_node._publish_config_response('test', True)

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])

        # DAQ Service format requirements
        required_fields = {'request_type', 'success', 'timestamp'}
        assert required_fields.issubset(set(payload.keys()))

    def test_quality_codes_are_strings(self, cfp_node):
        """Test quality codes are strings, not enums"""
        cfp_node._publish_channels({'temp1': 25.5})

        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert isinstance(payload['temp1']['quality'], str)

    def test_valid_quality_codes(self, cfp_node):
        """Test quality codes are valid values"""
        valid_codes = {'good', 'bad', 'uncertain', 'warning', 'alarm'}

        cfp_node._publish_channels({'temp1': 25.5})
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['temp1']['quality'] in valid_codes

        cfp_node.mqtt_client.reset_mock()
        cfp_node._publish_channels({'temp1': None})
        payload = json.loads(cfp_node.mqtt_client.publish.call_args[0][1])
        assert payload['temp1']['quality'] in valid_codes


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
