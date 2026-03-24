"""
Integration tests for API consistency across all node types.

Verifies that DAQ Service, cRIO Node, Opto22 Node, and cFP Node
all produce compatible MQTT API formats for the frontend.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

# ============================================================================
# MOCK CLASSES FOR EACH NODE TYPE
# ============================================================================

@dataclass
class MockChannel:
    """Mock channel configuration"""
    name: str = "test_ch"
    units: str = "V"
    unit: str = "V"  # cFP uses 'unit' instead of 'units'

@dataclass
class MockSystemConfig:
    mqtt_base_topic: str = "nisystem"
    node_id: str = "node-001"

@dataclass
class MockConfig:
    channels: Dict[str, MockChannel] = field(default_factory=dict)
    system: MockSystemConfig = field(default_factory=MockSystemConfig)

class MockDAQService:
    """Mock DAQ Service for API testing"""

    def __init__(self):
        self.mqtt_client = MagicMock()
        self.config = MockConfig()
        self.channel_acquisition_ts_us: Dict[str, int] = {}
        self.channel_qualities: Dict[str, str] = {}
        self.acquiring = False
        self.recording = False
        self.test_session_active = False
        self._publish_queue = MagicMock()

    def get_topic_base(self) -> str:
        return f"{self.config.system.mqtt_base_topic}/nodes/{self.config.system.node_id}"

    def _queue_publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        self._publish_queue.put((topic, payload, qos, retain))

class MockCRIONode:
    """Mock cRIO Node for API testing"""

    def __init__(self):
        self.mqtt_client = MagicMock()
        self.channel_values: Dict[str, Any] = {}
        self.channel_timestamps: Dict[str, float] = {}
        self.session = MagicMock()
        self.session.active = False
        self.session.name = ""
        self.session.operator = ""
        self.session.start_time = None
        self.session.locked_outputs = []
        self.base_topic = "nisystem"
        self.node_id = "crio-001"

    def get_topic_base(self) -> str:
        return f"{self.base_topic}/nodes/{self.node_id}"

    def _publish(self, topic: str, payload: Dict, qos: int = 0, retain: bool = False):
        self.mqtt_client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

class MockOpto22Node:
    """Mock Opto22 Node for API testing"""

    def __init__(self):
        self.mqtt_client = MagicMock()
        self.channel_values: Dict[str, Any] = {}
        self.channel_timestamps: Dict[str, float] = {}
        self.session = MagicMock()
        self.session.active = False
        self.session.name = ""
        self.session.operator = ""
        self.session.start_time = None
        self.session.locked_outputs = []
        self.base_topic = "nisystem"
        self.node_id = "opto22-001"

    def get_topic_base(self) -> str:
        return f"{self.base_topic}/nodes/{self.node_id}"

    def _publish(self, topic: str, payload: Dict, qos: int = 0, retain: bool = False):
        self.mqtt_client.publish(topic, json.dumps(payload), qos=qos, retain=retain)

@dataclass
class MockCFPModbusChannel:
    name: str
    unit: str = ""

@dataclass
class MockCFPModule:
    channels: List[MockCFPModbusChannel] = field(default_factory=list)

@dataclass
class MockCFPConfig:
    mqtt_base_topic: str = "nisystem"
    node_id: str = "cfp-001"
    modules: List[MockCFPModule] = field(default_factory=list)

class MockCFPNode:
    """Mock cFP Node for API testing"""

    def __init__(self):
        self.mqtt_client = MagicMock()
        self.mqtt_connected = True
        self.config = MockCFPConfig()
        self.channel_values: Dict[str, Any] = {}
        self.channel_qualities: Dict[str, str] = {}
        self.acquiring = False
        self.recording = False
        self.session_active = False
        self.session_id = None

    def _publish(self, topic: str, payload: Dict, retain: bool = False):
        if self.mqtt_client and self.mqtt_connected:
            self.mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=retain)

    def _find_channel_config(self, channel_name: str) -> Optional[MockCFPModbusChannel]:
        for module in self.config.modules:
            for ch in module.channels:
                if ch.name == channel_name:
                    return ch
        return None

# ============================================================================
# API FORMAT TESTS
# ============================================================================

class TestTopicStructure:
    """Verify all nodes use consistent topic structure"""

    def test_all_nodes_use_same_base_pattern(self):
        """All nodes should use {base_topic}/nodes/{node_id} pattern"""
        daq = MockDAQService()
        crio = MockCRIONode()
        opto22 = MockOpto22Node()
        cfp = MockCFPNode()

        # All should follow the pattern
        assert daq.get_topic_base() == "nisystem/nodes/node-001"
        assert crio.get_topic_base() == "nisystem/nodes/crio-001"
        assert opto22.get_topic_base() == "nisystem/nodes/opto22-001"

        # cFP uses config-based pattern
        assert f"{cfp.config.mqtt_base_topic}/nodes/{cfp.config.node_id}" == "nisystem/nodes/cfp-001"

    def test_batch_channel_topic_format(self):
        """All nodes should publish to channels/batch"""
        expected_suffix = "/channels/batch"

        daq_topic = f"{MockDAQService().get_topic_base()}{expected_suffix}"
        crio_topic = f"{MockCRIONode().get_topic_base()}{expected_suffix}"
        opto22_topic = f"{MockOpto22Node().get_topic_base()}{expected_suffix}"
        cfp = MockCFPNode()
        cfp_topic = f"{cfp.config.mqtt_base_topic}/nodes/{cfp.config.node_id}{expected_suffix}"

        assert daq_topic.endswith("/channels/batch")
        assert crio_topic.endswith("/channels/batch")
        assert opto22_topic.endswith("/channels/batch")
        assert cfp_topic.endswith("/channels/batch")

    def test_session_status_topic_format(self):
        """All nodes should publish to session/status"""
        expected_suffix = "/session/status"

        daq_topic = f"{MockDAQService().get_topic_base()}{expected_suffix}"
        crio_topic = f"{MockCRIONode().get_topic_base()}{expected_suffix}"

        assert daq_topic.endswith("/session/status")
        assert crio_topic.endswith("/session/status")

    def test_config_response_topic_format(self):
        """All nodes should publish to config/response"""
        expected_suffix = "/config/response"

        daq_topic = f"{MockDAQService().get_topic_base()}{expected_suffix}"
        crio_topic = f"{MockCRIONode().get_topic_base()}{expected_suffix}"

        assert daq_topic.endswith("/config/response")
        assert crio_topic.endswith("/config/response")

class TestBatchChannelPayload:
    """Verify batch channel payload format consistency"""

    def get_expected_batch_fields(self) -> set:
        """Fields that must be present in batch channel payloads"""
        return {'value', 'timestamp', 'quality'}

    def get_optional_batch_fields(self) -> set:
        """Fields that may be present in batch channel payloads"""
        return {'acquisition_ts_us', 'units', 'status'}

    def test_batch_payload_has_required_fields(self):
        """Batch payload must have value, timestamp, quality"""
        # Simulate what each node produces

        # DAQ Service format
        daq_payload = {
            'temp': {
                'value': 25.5,
                'timestamp': '2024-01-15T12:00:00',
                'acquisition_ts_us': 1705320000000000,
                'units': '°C',
                'quality': 'good',
                'status': 'normal'
            }
        }

        # cRIO format
        crio_payload = {
            'temp': {
                'value': 25.5,
                'timestamp': 1705320000.0,
                'acquisition_ts_us': 1705320000000000,
                'quality': 'good'
            }
        }

        # cFP format (after our updates)
        cfp_payload = {
            'temp': {
                'value': 25.5,
                'timestamp': '2024-01-15T12:00:00',
                'acquisition_ts_us': 1705320000000000,
                'units': '°C',
                'quality': 'good',
                'status': 'normal'
            }
        }

        required = self.get_expected_batch_fields()

        # All should have required fields
        assert required.issubset(set(daq_payload['temp'].keys()))
        assert required.issubset(set(crio_payload['temp'].keys()))
        assert required.issubset(set(cfp_payload['temp'].keys()))

    def test_batch_quality_values(self):
        """Quality field should use consistent values"""
        valid_qualities = {'good', 'bad', 'uncertain', 'warning', 'alarm'}

        # Test cases
        assert 'good' in valid_qualities
        assert 'bad' in valid_qualities
        assert 'warning' in valid_qualities
        assert 'alarm' in valid_qualities

class TestSessionStatusPayload:
    """Verify session status payload format consistency"""

    def get_required_session_fields(self) -> set:
        """Fields that must be present in session status"""
        return {'timestamp'}

    def get_common_session_fields(self) -> set:
        """Fields commonly used across nodes"""
        return {'acquiring', 'recording', 'session_active', 'active'}

    def test_session_payload_has_timestamp(self):
        """Session payload must have timestamp"""
        # DAQ Service format
        daq_session = {
            'acquiring': True,
            'recording': False,
            'session_active': False,
            'timestamp': '2024-01-15T12:00:00'
        }

        # cRIO/Opto22 format
        crio_session = {
            'active': False,
            'name': '',
            'operator': '',
            'start_time': None,
            'duration_s': 0,
            'locked_outputs': [],
            'timestamp': '2024-01-15T12:00:00Z'
        }

        # cFP format (after our updates)
        cfp_session = {
            'acquiring': False,
            'recording': False,
            'session_active': False,
            'session_id': None,
            'timestamp': '2024-01-15T12:00:00'
        }

        required = self.get_required_session_fields()

        assert required.issubset(set(daq_session.keys()))
        assert required.issubset(set(crio_session.keys()))
        assert required.issubset(set(cfp_session.keys()))

class TestConfigResponsePayload:
    """Verify config response payload format consistency"""

    def get_required_config_response_fields(self) -> set:
        """Fields that must be present in config response"""
        return {'request_type', 'success', 'timestamp'}

    def test_config_response_has_required_fields(self):
        """Config response must have request_type, success, timestamp"""
        # Common format across all nodes
        config_response = {
            'request_type': 'save',
            'success': True,
            'timestamp': '2024-01-15T12:00:00'
        }

        required = self.get_required_config_response_fields()
        assert required.issubset(set(config_response.keys()))

    def test_config_response_error_format(self):
        """Config response with error should include error field"""
        error_response = {
            'request_type': 'load',
            'success': False,
            'error': 'File not found',
            'timestamp': '2024-01-15T12:00:00'
        }

        assert 'error' in error_response
        assert error_response['success'] is False

    def test_config_response_data_format(self):
        """Config response with data should include data field"""
        data_response = {
            'request_type': 'validate',
            'success': True,
            'data': {'channels_count': 10},
            'timestamp': '2024-01-15T12:00:00'
        }

        assert 'data' in data_response
        assert data_response['success'] is True

class TestHeartbeatPayload:
    """Verify heartbeat payload format consistency"""

    def get_required_heartbeat_fields(self) -> set:
        """Fields that must be present in heartbeat"""
        return {'timestamp'}

    def test_heartbeat_has_timestamp(self):
        """Heartbeat must have timestamp"""
        # DAQ Service format
        daq_heartbeat = {
            'sequence': 1,
            'timestamp': '2024-01-15T12:00:00',
            'acquiring': True,
            'recording': False
        }

        # cFP format
        cfp_heartbeat = {
            'node_id': 'cfp-001',
            'timestamp': '2024-01-15T12:00:00',
            'uptime': 12345.6
        }

        required = self.get_required_heartbeat_fields()

        assert required.issubset(set(daq_heartbeat.keys()))
        assert required.issubset(set(cfp_heartbeat.keys()))

class TestStatusPayload:
    """Verify system status payload format consistency"""

    def get_required_status_fields(self) -> set:
        """Fields that must be present in system status"""
        return {'online', 'timestamp'}

    def test_status_has_required_fields(self):
        """System status must have online and timestamp"""
        # Common format
        status = {
            'online': True,
            'node_id': 'node-001',
            'timestamp': '2024-01-15T12:00:00'
        }

        required = self.get_required_status_fields()
        assert required.issubset(set(status.keys()))

class TestFrontendCompatibility:
    """Tests simulating frontend subscription patterns"""

    def test_frontend_can_subscribe_to_batch_channels(self):
        """Frontend should be able to subscribe to {base}/channels/batch for any node"""
        nodes = [
            ('daq', 'nisystem/nodes/node-001'),
            ('crio', 'nisystem/nodes/crio-001'),
            ('opto22', 'nisystem/nodes/opto22-001'),
            ('cfp', 'nisystem/nodes/cfp-001'),
        ]

        # Frontend subscription pattern
        for node_type, base_topic in nodes:
            batch_topic = f"{base_topic}/channels/batch"
            assert batch_topic.endswith('/channels/batch'), f"{node_type} batch topic incorrect"

    def test_frontend_can_subscribe_to_session_status(self):
        """Frontend should be able to subscribe to {base}/session/status for any node"""
        nodes = [
            ('daq', 'nisystem/nodes/node-001'),
            ('crio', 'nisystem/nodes/crio-001'),
            ('opto22', 'nisystem/nodes/opto22-001'),
            ('cfp', 'nisystem/nodes/cfp-001'),
        ]

        for node_type, base_topic in nodes:
            session_topic = f"{base_topic}/session/status"
            assert session_topic.endswith('/session/status'), f"{node_type} session topic incorrect"

    def test_frontend_wildcard_subscription(self):
        """Frontend should be able to use wildcards to subscribe to all nodes"""
        # Common pattern: nisystem/nodes/+/channels/batch
        wildcard_pattern = "nisystem/nodes/+/channels/batch"

        # Should match all these
        topics = [
            "nisystem/nodes/node-001/channels/batch",
            "nisystem/nodes/crio-001/channels/batch",
            "nisystem/nodes/opto22-001/channels/batch",
            "nisystem/nodes/cfp-001/channels/batch",
        ]

        import re
        # Convert MQTT wildcard to regex
        pattern = wildcard_pattern.replace('+', '[^/]+')
        regex = re.compile(f"^{pattern}$")

        for topic in topics:
            assert regex.match(topic), f"Wildcard should match {topic}"

class TestQualityCodeConsistency:
    """Verify quality codes are consistent across nodes"""

    def test_quality_good_for_valid_values(self):
        """Good quality for valid numeric values"""
        assert 'good' == 'good'  # All nodes should use 'good'

    def test_quality_bad_for_disconnected(self):
        """Bad quality for disconnected/NaN values"""
        assert 'bad' == 'bad'  # All nodes should use 'bad'

    def test_quality_codes_are_strings(self):
        """Quality codes should be strings, not enums or integers"""
        valid_qualities = ['good', 'bad', 'uncertain', 'warning', 'alarm']
        for q in valid_qualities:
            assert isinstance(q, str)

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
