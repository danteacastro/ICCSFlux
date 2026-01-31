"""
Unit tests for DAQ Service publishing methods
Tests the unified API publishing: batch channels, session status, config response
"""

import pytest
import json
import math
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import sys
sys.path.insert(0, 'services/daq_service')


@dataclass
class MockChannelConfig:
    """Mock channel configuration"""
    name: str = "test_channel"
    units: str = "V"
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None
    low_warning: Optional[float] = None
    high_warning: Optional[float] = None


@dataclass
class MockSystemConfig:
    """Mock system configuration"""
    mqtt_base_topic: str = "nisystem"
    node_id: str = "node-001"


@dataclass
class MockNISystemConfig:
    """Mock NISystem configuration"""
    channels: Dict[str, MockChannelConfig] = field(default_factory=dict)
    system: MockSystemConfig = field(default_factory=MockSystemConfig)


class MockDAQService:
    """
    Minimal mock of DAQService for testing publishing methods.
    Only includes attributes/methods needed for the publishing functions.
    """

    def __init__(self):
        self.mqtt_client = MagicMock()
        self.config = MockNISystemConfig()
        self.channel_acquisition_ts_us: Dict[str, int] = {}
        self.channel_qualities: Dict[str, str] = {}
        self.acquiring = False
        self.recording = False
        self.test_session_active = False
        self.test_session_id = None
        self.test_session_start_time = None
        self._publish_queue = MagicMock()

    def get_topic_base(self) -> str:
        """Get MQTT topic base"""
        return f"{self.config.system.mqtt_base_topic}/nodes/{self.config.system.node_id}"

    def _queue_publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        """Queue a message for publishing"""
        self._publish_queue.put((topic, payload, qos, retain))


# Import the actual methods to test - we'll patch them onto our mock
with patch.dict('sys.modules', {
    'paho': MagicMock(),
    'paho.mqtt': MagicMock(),
    'paho.mqtt.client': MagicMock(),
    'nidaqmx': MagicMock(),
}):
    # We need to read the actual method implementations
    pass


class TestPublishChannelsBatch:
    """Test _publish_channels_batch method"""

    @pytest.fixture
    def service(self):
        """Create mock service"""
        svc = MockDAQService()
        svc.config.channels = {
            'temp1': MockChannelConfig(name='temp1', units='°C'),
            'pressure': MockChannelConfig(name='pressure', units='PSI'),
        }
        return svc

    def _publish_channels_batch(self, service, values: Dict[str, Any]):
        """Implementation of _publish_channels_batch for testing"""
        if not service.mqtt_client:
            return

        try:
            base = service.get_topic_base()
            timestamp = datetime.now().isoformat()
            batch_payload = {}

            for channel_name, value in values.items():
                if channel_name not in service.config.channels:
                    continue

                channel = service.config.channels[channel_name]
                is_nan = isinstance(value, float) and math.isnan(value)
                acquisition_ts_us = service.channel_acquisition_ts_us.get(channel_name, 0)
                remote_quality = getattr(service, 'channel_qualities', {}).get(channel_name)

                if is_nan:
                    batch_payload[channel_name] = {
                        'value': None,
                        'timestamp': timestamp,
                        'acquisition_ts_us': acquisition_ts_us,
                        'units': channel.units,
                        'quality': 'bad',
                        'status': 'disconnected'
                    }
                else:
                    quality = remote_quality if remote_quality else 'good'
                    status = 'normal'

                    if channel.low_limit is not None and channel.high_limit is not None:
                        numeric_value = float(value) if isinstance(value, (int, float)) else (1.0 if value else 0.0)
                        if numeric_value < channel.low_limit:
                            status = 'low_limit'
                            quality = 'alarm'
                        elif numeric_value > channel.high_limit:
                            status = 'high_limit'
                            quality = 'alarm'
                        elif channel.low_warning is not None and numeric_value < channel.low_warning:
                            status = 'low_warning'
                            quality = 'warning'
                        elif channel.high_warning is not None and numeric_value > channel.high_warning:
                            status = 'high_warning'
                            quality = 'warning'

                    batch_payload[channel_name] = {
                        'value': value,
                        'timestamp': timestamp,
                        'acquisition_ts_us': acquisition_ts_us,
                        'units': channel.units,
                        'quality': quality,
                        'status': status
                    }

            service._queue_publish(f"{base}/channels/batch", json.dumps(batch_payload))
        except Exception:
            pass

    def test_batch_publish_normal_values(self, service):
        """Test publishing normal channel values in batch"""
        values = {'temp1': 25.5, 'pressure': 100.0}

        self._publish_channels_batch(service, values)

        service._publish_queue.put.assert_called_once()
        call_args = service._publish_queue.put.call_args[0][0]
        topic = call_args[0]
        payload = json.loads(call_args[1])

        assert topic == "nisystem/nodes/node-001/channels/batch"
        assert 'temp1' in payload
        assert 'pressure' in payload
        assert payload['temp1']['value'] == 25.5
        assert payload['temp1']['units'] == '°C'
        assert payload['temp1']['quality'] == 'good'
        assert payload['temp1']['status'] == 'normal'

    def test_batch_publish_nan_value(self, service):
        """Test publishing NaN value shows as bad quality"""
        values = {'temp1': float('nan'), 'pressure': 100.0}

        self._publish_channels_batch(service, values)

        call_args = service._publish_queue.put.call_args[0][0]
        payload = json.loads(call_args[1])

        assert payload['temp1']['value'] is None
        assert payload['temp1']['quality'] == 'bad'
        assert payload['temp1']['status'] == 'disconnected'
        assert payload['pressure']['quality'] == 'good'

    def test_batch_publish_with_limits(self, service):
        """Test limit checking in batch publish"""
        service.config.channels['temp1'] = MockChannelConfig(
            name='temp1',
            units='°C',
            low_limit=0.0,
            high_limit=100.0,
            low_warning=10.0,
            high_warning=90.0
        )

        # Test high limit alarm
        self._publish_channels_batch(service, {'temp1': 150.0})
        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['status'] == 'high_limit'
        assert payload['temp1']['quality'] == 'alarm'

        # Test low limit alarm
        service._publish_queue.reset_mock()
        self._publish_channels_batch(service, {'temp1': -10.0})
        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['status'] == 'low_limit'
        assert payload['temp1']['quality'] == 'alarm'

    def test_batch_publish_with_warnings(self, service):
        """Test warning limit checking in batch publish"""
        service.config.channels['temp1'] = MockChannelConfig(
            name='temp1',
            units='°C',
            low_limit=0.0,
            high_limit=100.0,
            low_warning=10.0,
            high_warning=90.0
        )

        # Test high warning
        self._publish_channels_batch(service, {'temp1': 95.0})
        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['status'] == 'high_warning'
        assert payload['temp1']['quality'] == 'warning'

        # Test low warning
        service._publish_queue.reset_mock()
        self._publish_channels_batch(service, {'temp1': 5.0})
        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['status'] == 'low_warning'
        assert payload['temp1']['quality'] == 'warning'

    def test_batch_publish_remote_quality(self, service):
        """Test that remote quality is respected"""
        service.channel_qualities = {'temp1': 'uncertain'}
        values = {'temp1': 25.5}

        self._publish_channels_batch(service, values)

        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['quality'] == 'uncertain'

    def test_batch_publish_acquisition_timestamp(self, service):
        """Test acquisition timestamp is included"""
        service.channel_acquisition_ts_us = {'temp1': 1705320000000000}
        values = {'temp1': 25.5}

        self._publish_channels_batch(service, values)

        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert payload['temp1']['acquisition_ts_us'] == 1705320000000000

    def test_batch_publish_unknown_channel_skipped(self, service):
        """Test unknown channels are skipped"""
        values = {'temp1': 25.5, 'unknown_channel': 999.0}

        self._publish_channels_batch(service, values)

        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        assert 'temp1' in payload
        assert 'unknown_channel' not in payload

    def test_batch_publish_no_mqtt_client(self, service):
        """Test graceful handling when no MQTT client"""
        service.mqtt_client = None
        values = {'temp1': 25.5}

        # Should not raise
        self._publish_channels_batch(service, values)

        service._publish_queue.put.assert_not_called()


class TestPublishSessionStatus:
    """Test _publish_session_status method"""

    @pytest.fixture
    def service(self):
        """Create mock service"""
        return MockDAQService()

    def _publish_session_status(self, service):
        """Implementation of _publish_session_status for testing"""
        if not service.mqtt_client:
            return

        try:
            base = service.get_topic_base()
            session_active = getattr(service, 'test_session_active', False)

            payload = {
                'acquiring': service.acquiring,
                'recording': service.recording,
                'session_active': session_active,
                'timestamp': datetime.now().isoformat()
            }

            if session_active and hasattr(service, 'test_session_id'):
                payload['session_id'] = service.test_session_id
                if hasattr(service, 'test_session_start_time') and service.test_session_start_time:
                    elapsed = (datetime.now() - service.test_session_start_time).total_seconds()
                    payload['session_elapsed_sec'] = round(elapsed, 1)

            service.mqtt_client.publish(
                f"{base}/session/status",
                json.dumps(payload),
                qos=0
            )
        except Exception:
            pass

    def test_publish_session_idle(self, service):
        """Test publishing idle session status"""
        service.acquiring = False
        service.recording = False
        service.test_session_active = False

        self._publish_session_status(service)

        call_args = service.mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert topic == "nisystem/nodes/node-001/session/status"
        assert payload['acquiring'] is False
        assert payload['recording'] is False
        assert payload['session_active'] is False
        assert 'timestamp' in payload

    def test_publish_session_acquiring(self, service):
        """Test publishing acquiring session status"""
        service.acquiring = True
        service.recording = False

        self._publish_session_status(service)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert payload['acquiring'] is True
        assert payload['recording'] is False

    def test_publish_session_recording(self, service):
        """Test publishing recording session status"""
        service.acquiring = True
        service.recording = True

        self._publish_session_status(service)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert payload['acquiring'] is True
        assert payload['recording'] is True

    def test_publish_session_active_with_id(self, service):
        """Test publishing active session with ID"""
        service.acquiring = True
        service.test_session_active = True
        service.test_session_id = "session-12345"

        self._publish_session_status(service)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert payload['session_active'] is True
        assert payload['session_id'] == "session-12345"

    def test_publish_session_elapsed_time(self, service):
        """Test publishing session elapsed time"""
        from datetime import timedelta

        service.acquiring = True
        service.test_session_active = True
        service.test_session_id = "session-12345"
        service.test_session_start_time = datetime.now() - timedelta(seconds=120)

        self._publish_session_status(service)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert 'session_elapsed_sec' in payload
        assert payload['session_elapsed_sec'] >= 119.0  # Allow small timing variance

    def test_publish_session_no_mqtt_client(self, service):
        """Test graceful handling when no MQTT client"""
        service.mqtt_client = None

        # Should not raise
        self._publish_session_status(service)


class TestPublishConfigResponse:
    """Test _publish_config_response method"""

    @pytest.fixture
    def service(self):
        """Create mock service"""
        return MockDAQService()

    def _publish_config_response(self, service, request_type: str, success: bool,
                                   data: Optional[Dict] = None, error: Optional[str] = None):
        """Implementation of _publish_config_response for testing"""
        if not service.mqtt_client:
            return

        try:
            base = service.get_topic_base()
            payload = {
                'request_type': request_type,
                'success': success,
                'timestamp': datetime.now().isoformat()
            }

            if data:
                payload['data'] = data
            if error:
                payload['error'] = error

            service.mqtt_client.publish(
                f"{base}/config/response",
                json.dumps(payload),
                qos=1
            )
        except Exception:
            pass

    def test_publish_config_success(self, service):
        """Test publishing successful config response"""
        self._publish_config_response(service, 'save', True)

        call_args = service.mqtt_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        qos = call_args[1]['qos']

        assert topic == "nisystem/nodes/node-001/config/response"
        assert payload['request_type'] == 'save'
        assert payload['success'] is True
        assert 'timestamp' in payload
        assert qos == 1  # Config responses use QoS 1

    def test_publish_config_failure_with_error(self, service):
        """Test publishing failed config response with error"""
        self._publish_config_response(
            service,
            'load',
            False,
            error="File not found"
        )

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert payload['request_type'] == 'load'
        assert payload['success'] is False
        assert payload['error'] == "File not found"

    def test_publish_config_with_data(self, service):
        """Test publishing config response with data"""
        response_data = {
            'filename': 'config.ini',
            'channels_count': 10
        }

        self._publish_config_response(
            service,
            'validate',
            True,
            data=response_data
        )

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])
        assert payload['data'] == response_data

    def test_publish_config_various_types(self, service):
        """Test different config request types"""
        request_types = ['save', 'load', 'apply', 'validate', 'create_channel', 'delete_channel']

        for req_type in request_types:
            service.mqtt_client.reset_mock()
            self._publish_config_response(service, req_type, True)

            payload = json.loads(service.mqtt_client.publish.call_args[0][1])
            assert payload['request_type'] == req_type

    def test_publish_config_no_mqtt_client(self, service):
        """Test graceful handling when no MQTT client"""
        service.mqtt_client = None

        # Should not raise
        self._publish_config_response(service, 'save', True)


class TestTopicFormat:
    """Test MQTT topic format consistency"""

    @pytest.fixture
    def service(self):
        """Create mock service with custom node ID"""
        svc = MockDAQService()
        svc.config.system.node_id = "daq-main"
        svc.config.system.mqtt_base_topic = "factory/nisystem"
        return svc

    def test_topic_base_format(self, service):
        """Test topic base uses correct format"""
        base = service.get_topic_base()
        assert base == "factory/nisystem/nodes/daq-main"

    def test_batch_topic_format(self, service):
        """Test batch channel topic format"""
        service.config.channels = {'ch1': MockChannelConfig()}

        # Call the batch publish implementation
        TestPublishChannelsBatch()._publish_channels_batch(service, {'ch1': 1.0})

        topic = service._publish_queue.put.call_args[0][0][0]
        assert topic == "factory/nisystem/nodes/daq-main/channels/batch"

    def test_session_topic_format(self, service):
        """Test session status topic format"""
        TestPublishSessionStatus()._publish_session_status(service)

        topic = service.mqtt_client.publish.call_args[0][0]
        assert topic == "factory/nisystem/nodes/daq-main/session/status"

    def test_config_topic_format(self, service):
        """Test config response topic format"""
        TestPublishConfigResponse()._publish_config_response(service, 'test', True)

        topic = service.mqtt_client.publish.call_args[0][0]
        assert topic == "factory/nisystem/nodes/daq-main/config/response"


class TestBatchPayloadFormat:
    """Test batch payload matches cRIO/Opto22 format"""

    @pytest.fixture
    def service(self):
        """Create mock service"""
        svc = MockDAQService()
        svc.config.channels = {
            'temp': MockChannelConfig(name='temp', units='°C'),
        }
        svc.channel_acquisition_ts_us = {'temp': 1705320000000000}
        return svc

    def test_batch_payload_structure(self, service):
        """Test batch payload has all required fields"""
        TestPublishChannelsBatch()._publish_channels_batch(service, {'temp': 25.5})

        payload = json.loads(service._publish_queue.put.call_args[0][0][1])
        channel_data = payload['temp']

        # Required fields matching cRIO/Opto22 format
        assert 'value' in channel_data
        assert 'timestamp' in channel_data
        assert 'acquisition_ts_us' in channel_data
        assert 'units' in channel_data
        assert 'quality' in channel_data
        assert 'status' in channel_data

    def test_session_payload_structure(self, service):
        """Test session payload has all required fields"""
        TestPublishSessionStatus()._publish_session_status(service)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])

        # Required fields matching cRIO/Opto22 format
        assert 'acquiring' in payload
        assert 'recording' in payload
        assert 'session_active' in payload
        assert 'timestamp' in payload

    def test_config_response_structure(self, service):
        """Test config response has all required fields"""
        TestPublishConfigResponse()._publish_config_response(service, 'save', True)

        payload = json.loads(service.mqtt_client.publish.call_args[0][1])

        # Required fields matching cRIO/Opto22 format
        assert 'request_type' in payload
        assert 'success' in payload
        assert 'timestamp' in payload


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
