"""
Unit tests for Azure IoT Hub Uploader
Tests telemetry streaming to Azure IoT Hub
"""

import pytest
import json
import threading
import time
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from collections import deque

import sys
sys.path.insert(0, 'services/daq_service')


# Mock Azure IoT SDK before importing
@pytest.fixture(autouse=True)
def mock_azure_sdk():
    """Mock Azure IoT SDK"""
    mock_message = MagicMock()
    mock_client = MagicMock()

    with patch.dict('sys.modules', {
        'azure': MagicMock(),
        'azure.iot': MagicMock(),
        'azure.iot.device': MagicMock(),
        'azure.iot.device.exceptions': MagicMock(),
    }):
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            yield


from azure_iot_uploader import AzureIoTUploader, is_available


class TestIsAvailable:
    """Test availability check"""

    def test_is_available_when_sdk_installed(self):
        """Test SDK availability check"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            assert is_available() is True

    def test_is_not_available_when_sdk_missing(self):
        """Test when SDK is not installed"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', False):
            assert is_available() is False


class TestAzureIoTUploaderInit:
    """Test AzureIoTUploader initialization"""

    def test_initialization(self):
        """Test uploader initialization"""
        connection_string = "HostName=test.azure.com;DeviceId=device1;SharedAccessKey=key123"

        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(
                connection_string=connection_string,
                batch_size=5,
                batch_interval_ms=500,
                max_queue_size=5000
            )

        assert uploader._batch_size == 5
        assert uploader._batch_interval_ms == 500
        assert uploader._max_queue_size == 5000
        assert uploader.enabled is False
        assert uploader.connected is False

    def test_initialization_without_sdk(self):
        """Test initialization fails without SDK"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', False):
            with pytest.raises(RuntimeError, match="azure-iot-device package not installed"):
                AzureIoTUploader(connection_string="test")

    def test_default_values(self):
        """Test default configuration values"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="test")

        assert uploader._batch_size == 10
        assert uploader._batch_interval_ms == 1000
        assert uploader._max_queue_size == 10000


class TestChannelConfiguration:
    """Test channel configuration"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            return AzureIoTUploader(connection_string="test")

    def test_set_channels(self, uploader):
        """Test setting channels to upload"""
        channels = ['TC_01', 'TC_02', 'Pressure_01']
        uploader.set_channels(channels)

        assert uploader._channels == channels

    def test_set_channels_copies_list(self, uploader):
        """Test that channel list is copied"""
        channels = ['TC_01', 'TC_02']
        uploader.set_channels(channels)

        channels.append('TC_03')
        assert 'TC_03' not in uploader._channels


class TestStatusCallback:
    """Test status callback functionality"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            return AzureIoTUploader(connection_string="test")

    def test_set_status_callback(self, uploader):
        """Test setting status callback"""
        callback = Mock()
        uploader.set_status_callback(callback)

        assert uploader._on_status_change == callback

    def test_notify_status_calls_callback(self, uploader):
        """Test status notification"""
        callback = Mock()
        uploader.set_status_callback(callback)

        uploader._notify_status()

        callback.assert_called_once()


class TestDataPush:
    """Test data push functionality"""

    @pytest.fixture
    def uploader(self):
        """Create uploader with channels"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="test")
            uploader.set_channels(['temp1', 'temp2'])
            uploader._enabled = True
            return uploader

    def test_push_data_disabled(self):
        """Test push_data when disabled"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="test")
            uploader.set_channels(['temp'])
            # Not enabled

            uploader.push_data({'temp': 25.0})

            assert len(uploader._queue) == 0

    def test_push_data_no_channels(self):
        """Test push_data with no channels configured"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="test")
            uploader._enabled = True
            # No channels set

            uploader.push_data({'temp': 25.0})

            assert len(uploader._queue) == 0

    def test_push_data_filters_channels(self, uploader):
        """Test that only configured channels are queued"""
        uploader.push_data({
            'temp1': 25.0,
            'temp2': 30.0,
            'other': 100.0  # Not in channels list
        })

        assert len(uploader._queue) == 1
        data_point = uploader._queue[0]
        assert 'temp1' in data_point['values']
        assert 'temp2' in data_point['values']
        assert 'other' not in data_point['values']

    def test_push_data_filters_nan(self, uploader):
        """Test that NaN values are filtered"""
        uploader.push_data({
            'temp1': 25.0,
            'temp2': float('nan')  # Should be filtered
        })

        data_point = uploader._queue[0]
        assert 'temp1' in data_point['values']
        assert 'temp2' not in data_point['values']

    def test_push_data_only_numeric(self, uploader):
        """Test that only numeric values are included"""
        uploader.push_data({
            'temp1': 25.0,
            'temp2': "string_value"  # Should be filtered
        })

        data_point = uploader._queue[0]
        assert 'temp1' in data_point['values']
        assert 'temp2' not in data_point['values']

    def test_push_data_with_timestamp(self, uploader):
        """Test push_data with custom timestamp"""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        uploader.push_data({'temp1': 25.0}, timestamp=ts)

        data_point = uploader._queue[0]
        assert data_point['timestamp'] == ts.isoformat()

    def test_queue_max_size(self, uploader):
        """Test queue respects max size"""
        uploader._max_queue_size = 5
        uploader._queue = deque(maxlen=5)

        # Push more than max
        for i in range(10):
            uploader.push_data({'temp1': i})

        assert len(uploader._queue) == 5
        # Oldest should be dropped
        assert uploader._queue[0]['values']['temp1'] == 5.0


class TestBatchSending:
    """Test batch sending functionality"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(
                connection_string="HostName=test.azure.com;DeviceId=device1;SharedAccessKey=key",
                batch_size=3
            )
            uploader._client = MagicMock()
            return uploader

    def test_send_batch_success(self, uploader):
        """Test successful batch send"""
        batch = [
            {'timestamp': '2024-01-15T12:00:00', 'values': {'temp': 25.0}},
            {'timestamp': '2024-01-15T12:00:01', 'values': {'temp': 26.0}}
        ]

        # Mock the Message class at module level since SDK isn't installed
        mock_message_class = MagicMock()
        with patch.object(uploader, '_client') as mock_client:
            # Inject a mock Message into the module's global namespace temporarily
            import azure_iot_uploader
            original_message = getattr(azure_iot_uploader, 'Message', None)
            azure_iot_uploader.Message = mock_message_class
            try:
                result = uploader._send_batch(batch)
            finally:
                if original_message is not None:
                    azure_iot_uploader.Message = original_message
                elif hasattr(azure_iot_uploader, 'Message'):
                    delattr(azure_iot_uploader, 'Message')

        assert result is True
        assert uploader._stats['messages_sent'] == 1
        assert uploader._stats['samples_sent'] == 2

    def test_send_batch_empty(self, uploader):
        """Test sending empty batch"""
        result = uploader._send_batch([])
        assert result is False

    def test_send_batch_no_client(self, uploader):
        """Test sending without client"""
        uploader._client = None
        batch = [{'timestamp': '2024-01-15T12:00:00', 'values': {'temp': 25.0}}]

        result = uploader._send_batch(batch)

        assert result is False


class TestDeviceIdExtraction:
    """Test device ID extraction from connection string"""

    def test_extract_device_id(self):
        """Test extracting device ID"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(
                connection_string="HostName=hub.azure.com;DeviceId=my-device-123;SharedAccessKey=abc"
            )

        device_id = uploader._get_device_id()
        assert device_id == "my-device-123"

    def test_extract_device_id_malformed(self):
        """Test extracting device ID from malformed string"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="invalid_string")

        device_id = uploader._get_device_id()
        assert device_id == "unknown"


class TestStartStop:
    """Test start/stop functionality"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            return AzureIoTUploader(
                connection_string="HostName=hub.azure.com;DeviceId=device1;SharedAccessKey=key"
            )

    def test_start_no_connection_string(self):
        """Test start without connection string"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="")

        result = uploader.start()

        assert result is False
        assert uploader._running is False

    def test_start_already_running(self, uploader):
        """Test start when already running"""
        uploader._running = True

        result = uploader.start()

        assert result is True  # Returns True if already running

    def test_start_success(self, uploader):
        """Test successful start"""
        import azure_iot_uploader
        mock_client_class = MagicMock()
        mock_client = MagicMock()
        mock_client_class.create_from_connection_string.return_value = mock_client

        # Inject mock IoTHubDeviceClient
        original = getattr(azure_iot_uploader, 'IoTHubDeviceClient', None)
        azure_iot_uploader.IoTHubDeviceClient = mock_client_class
        try:
            result = uploader.start()

            assert result is True
            assert uploader._running is True
            assert uploader._enabled is True
            mock_client.connect.assert_called_once()

            uploader.stop()
        finally:
            if original is not None:
                azure_iot_uploader.IoTHubDeviceClient = original
            elif hasattr(azure_iot_uploader, 'IoTHubDeviceClient'):
                delattr(azure_iot_uploader, 'IoTHubDeviceClient')

    def test_start_connection_failure(self, uploader):
        """Test start with connection failure"""
        import azure_iot_uploader
        mock_client_class = MagicMock()
        mock_client_class.create_from_connection_string.side_effect = Exception("Connection failed")

        original = getattr(azure_iot_uploader, 'IoTHubDeviceClient', None)
        azure_iot_uploader.IoTHubDeviceClient = mock_client_class
        try:
            result = uploader.start()

            assert result is False
            assert uploader._stats['last_error'] is not None
        finally:
            if original is not None:
                azure_iot_uploader.IoTHubDeviceClient = original
            elif hasattr(azure_iot_uploader, 'IoTHubDeviceClient'):
                delattr(azure_iot_uploader, 'IoTHubDeviceClient')

    def test_stop_not_running(self, uploader):
        """Test stop when not running"""
        uploader._running = False
        # Should not raise
        uploader.stop()

    def test_stop_running(self, uploader):
        """Test stop when running"""
        import azure_iot_uploader
        mock_client_class = MagicMock()
        mock_client = MagicMock()
        mock_client_class.create_from_connection_string.return_value = mock_client

        original = getattr(azure_iot_uploader, 'IoTHubDeviceClient', None)
        azure_iot_uploader.IoTHubDeviceClient = mock_client_class
        try:
            uploader.start()
            uploader.stop()

            assert uploader._running is False
            assert uploader._enabled is False
            mock_client.disconnect.assert_called_once()
        finally:
            if original is not None:
                azure_iot_uploader.IoTHubDeviceClient = original
            elif hasattr(azure_iot_uploader, 'IoTHubDeviceClient'):
                delattr(azure_iot_uploader, 'IoTHubDeviceClient')
        mock_client.disconnect.assert_called_once()


class TestConfiguration:
    """Test configuration methods"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            return AzureIoTUploader(
                connection_string="test",
                batch_size=10,
                batch_interval_ms=1000
            )

    def test_get_config(self, uploader):
        """Test getting configuration"""
        uploader.set_channels(['temp1', 'temp2'])
        uploader._enabled = True

        config = uploader.get_config()

        assert config['enabled'] is True
        assert config['channels'] == ['temp1', 'temp2']
        assert config['batch_size'] == 10
        assert config['batch_interval_ms'] == 1000
        assert config['has_connection_string'] is True

    def test_get_config_no_connection_string(self):
        """Test config when no connection string"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="")

        config = uploader.get_config()
        assert config['has_connection_string'] is False

    def test_update_config_channels(self, uploader):
        """Test updating channels"""
        uploader.update_config(channels=['new_ch1', 'new_ch2'])

        assert uploader._channels == ['new_ch1', 'new_ch2']

    def test_update_config_batch_size(self, uploader):
        """Test updating batch size"""
        uploader.update_config(batch_size=20)

        assert uploader._batch_size == 20

    def test_update_config_batch_size_min(self, uploader):
        """Test batch size minimum"""
        uploader.update_config(batch_size=0)

        assert uploader._batch_size == 1  # Minimum is 1

    def test_update_config_interval(self, uploader):
        """Test updating batch interval"""
        uploader.update_config(batch_interval_ms=2000)

        assert uploader._batch_interval_ms == 2000

    def test_update_config_interval_min(self, uploader):
        """Test batch interval minimum"""
        uploader.update_config(batch_interval_ms=50)

        assert uploader._batch_interval_ms == 100  # Minimum is 100


class TestStatistics:
    """Test statistics tracking"""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            return AzureIoTUploader(connection_string="test")

    def test_initial_stats(self, uploader):
        """Test initial statistics"""
        stats = uploader.stats

        assert stats['messages_sent'] == 0
        assert stats['messages_failed'] == 0
        assert stats['samples_sent'] == 0
        assert stats['samples_dropped'] == 0
        assert stats['last_send_time'] is None
        assert stats['last_error'] is None
        assert stats['connected'] is False

    def test_stats_returns_copy(self, uploader):
        """Test stats returns a copy"""
        stats1 = uploader.stats
        stats1['messages_sent'] = 999

        stats2 = uploader.stats
        assert stats2['messages_sent'] == 0


class TestReconnection:
    """Test reconnection functionality"""

    @pytest.fixture
    def uploader(self):
        """Create uploader with mock client"""
        with patch('azure_iot_uploader.AZURE_IOT_AVAILABLE', True):
            uploader = AzureIoTUploader(connection_string="test")
            uploader._client = MagicMock()
            return uploader

    def test_try_reconnect_success(self, uploader):
        """Test successful reconnection"""
        uploader._stats['connected'] = False

        result = uploader._try_reconnect()

        assert result is True
        assert uploader._stats['connected'] is True
        uploader._client.connect.assert_called_once()

    def test_try_reconnect_no_client(self, uploader):
        """Test reconnect without client"""
        uploader._client = None

        result = uploader._try_reconnect()

        assert result is False

    def test_try_reconnect_failure(self, uploader):
        """Test reconnection failure"""
        uploader._client.connect.side_effect = Exception("Network error")

        result = uploader._try_reconnect()

        assert result is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
