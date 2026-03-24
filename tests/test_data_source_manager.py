"""
Unit tests for DataSourceManager
Tests unified abstraction layer for multiple data backends
"""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

import sys
sys.path.insert(0, 'services/daq_service')

from data_source_manager import (
    DataSourceType, ConnectionState, DataSourceConfig, ChannelMapping,
    DataSourceStatus, DataSource, DataSourceManager, get_data_source_manager
)

class TestDataSourceType:
    """Test DataSourceType enumeration"""

    def test_enum_values(self):
        """Test all data source types are defined"""
        assert DataSourceType.MODBUS_TCP.value == "modbus_tcp"
        assert DataSourceType.MODBUS_RTU.value == "modbus_rtu"
        assert DataSourceType.REST_API.value == "rest_api"
        assert DataSourceType.OPC_UA.value == "opc_ua"
        assert DataSourceType.ETHERNET_IP.value == "ethernet_ip"
        assert DataSourceType.S7.value == "s7"

class TestConnectionState:
    """Test ConnectionState enumeration"""

    def test_enum_values(self):
        """Test all connection states are defined"""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.ERROR.value == "error"
        assert ConnectionState.DISABLED.value == "disabled"

class TestDataSourceConfig:
    """Test DataSourceConfig dataclass"""

    def test_default_values(self):
        """Test default configuration values"""
        config = DataSourceConfig(
            name="test_source",
            source_type=DataSourceType.MODBUS_TCP
        )
        assert config.enabled is True
        assert config.poll_rate_ms == 100
        assert config.timeout_s == 5.0
        assert config.retries == 3
        assert config.description == ""
        assert config.tags == []

    def test_custom_values(self):
        """Test custom configuration values"""
        config = DataSourceConfig(
            name="custom_source",
            source_type=DataSourceType.REST_API,
            enabled=False,
            poll_rate_ms=500,
            timeout_s=10.0,
            retries=5,
            description="Test description",
            tags=["production", "critical"]
        )
        assert config.name == "custom_source"
        assert config.source_type == DataSourceType.REST_API
        assert config.enabled is False
        assert config.poll_rate_ms == 500
        assert config.timeout_s == 10.0
        assert config.retries == 5
        assert config.description == "Test description"
        assert config.tags == ["production", "critical"]

class TestChannelMapping:
    """Test ChannelMapping dataclass"""

    def test_default_values(self):
        """Test default channel mapping values"""
        mapping = ChannelMapping(
            channel_name="Temperature",
            source_address="40001"
        )
        assert mapping.data_type == "float32"
        assert mapping.scale == 1.0
        assert mapping.offset == 0.0
        assert mapping.unit == ""
        assert mapping.is_output is False
        assert mapping.transform is None

    def test_custom_values(self):
        """Test custom channel mapping values"""
        mapping = ChannelMapping(
            channel_name="Pressure_PSI",
            source_address="/api/v1/pressure",
            data_type="int16",
            scale=0.1,
            offset=-14.7,
            unit="PSI",
            is_output=True,
            transform="value * 0.1 + 32"
        )
        assert mapping.channel_name == "Pressure_PSI"
        assert mapping.source_address == "/api/v1/pressure"
        assert mapping.data_type == "int16"
        assert mapping.scale == 0.1
        assert mapping.offset == -14.7
        assert mapping.unit == "PSI"
        assert mapping.is_output is True
        assert mapping.transform == "value * 0.1 + 32"

class TestDataSourceStatus:
    """Test DataSourceStatus dataclass"""

    def test_default_values(self):
        """Test default status values"""
        status = DataSourceStatus()
        assert status.state == ConnectionState.DISCONNECTED
        assert status.last_error is None
        assert status.error_count == 0
        assert status.last_successful_read == 0
        assert status.read_count == 0
        assert status.write_count == 0
        assert status.latency_ms == 0

    def test_status_modification(self):
        """Test status can be modified"""
        status = DataSourceStatus()
        status.state = ConnectionState.CONNECTED
        status.read_count = 100
        status.latency_ms = 15.5

        assert status.state == ConnectionState.CONNECTED
        assert status.read_count == 100
        assert status.latency_ms == 15.5

class MockDataSource(DataSource):
    """Mock implementation of DataSource for testing"""

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._connected = False
        self._test_values = {}

    def connect(self) -> bool:
        self._connected = True
        self.status.state = ConnectionState.CONNECTED
        return True

    def disconnect(self):
        self._connected = False
        self.status.state = ConnectionState.DISCONNECTED

    def read_all(self):
        return self._test_values.copy()

    def read_channel(self, channel_name: str):
        return self._test_values.get(channel_name)

    def write_channel(self, channel_name: str, value) -> bool:
        self._test_values[channel_name] = value
        return True

    def set_test_values(self, values):
        self._test_values = values

class TestDataSourceBase:
    """Test DataSource abstract base class"""

    @pytest.fixture
    def mock_source(self):
        """Create mock data source"""
        config = DataSourceConfig(
            name="test_source",
            source_type=DataSourceType.MODBUS_TCP
        )
        return MockDataSource(config)

    def test_source_name(self, mock_source):
        """Test source name property"""
        assert mock_source.name == "test_source"

    def test_source_type(self, mock_source):
        """Test source type property"""
        assert mock_source.source_type == DataSourceType.MODBUS_TCP

    def test_add_channel(self, mock_source):
        """Test adding channel mapping"""
        mapping = ChannelMapping(
            channel_name="temp1",
            source_address="40001"
        )
        mock_source.add_channel(mapping)

        assert "temp1" in mock_source.channels
        assert mock_source.channels["temp1"] == mapping
        assert "temp1" in mock_source.values
        assert mock_source.values["temp1"] is None

    def test_remove_channel(self, mock_source):
        """Test removing channel mapping"""
        mapping = ChannelMapping(channel_name="temp1", source_address="40001")
        mock_source.add_channel(mapping)
        mock_source.remove_channel("temp1")

        assert "temp1" not in mock_source.channels
        assert "temp1" not in mock_source.values

    def test_get_channel_names(self, mock_source):
        """Test getting channel names"""
        mock_source.add_channel(ChannelMapping(channel_name="ch1", source_address="1"))
        mock_source.add_channel(ChannelMapping(channel_name="ch2", source_address="2"))

        names = mock_source.get_channel_names()
        assert "ch1" in names
        assert "ch2" in names

    def test_add_callback(self, mock_source):
        """Test adding value callback"""
        callback = Mock()
        mock_source.add_callback(callback)

        assert callback in mock_source._callbacks

    def test_notify_callbacks(self, mock_source):
        """Test callback notification"""
        callback1 = Mock()
        callback2 = Mock()
        mock_source.add_callback(callback1)
        mock_source.add_callback(callback2)

        values = {"ch1": 100, "ch2": 200}
        mock_source._notify_callbacks(values)

        callback1.assert_called_once_with("test_source", values)
        callback2.assert_called_once_with("test_source", values)

    def test_callback_error_handling(self, mock_source):
        """Test callbacks handle errors gracefully"""
        error_callback = Mock(side_effect=Exception("Callback error"))
        good_callback = Mock()

        mock_source.add_callback(error_callback)
        mock_source.add_callback(good_callback)

        # Should not raise
        mock_source._notify_callbacks({"ch1": 100})

        # Good callback should still be called
        good_callback.assert_called_once()

    def test_get_status(self, mock_source):
        """Test get_status returns correct dictionary"""
        mock_source.status.state = ConnectionState.CONNECTED
        mock_source.status.read_count = 50
        mock_source.status.latency_ms = 12.5

        status = mock_source.get_status()

        assert status['name'] == "test_source"
        assert status['type'] == "modbus_tcp"
        assert status['state'] == "connected"
        assert status['connected'] is True
        assert status['read_count'] == 50
        assert status['latency_ms'] == 12.5

    def test_get_values(self, mock_source):
        """Test getting cached values"""
        mock_source.values = {"ch1": 100, "ch2": 200}
        values = mock_source.get_values()

        assert values == {"ch1": 100, "ch2": 200}
        # Should be a copy
        values["ch1"] = 999
        assert mock_source.values["ch1"] == 100

class TestPolling:
    """Test polling functionality"""

    @pytest.fixture
    def polling_source(self):
        """Create source for polling tests"""
        config = DataSourceConfig(
            name="poll_test",
            source_type=DataSourceType.MODBUS_TCP,
            poll_rate_ms=50
        )
        source = MockDataSource(config)
        source.set_test_values({"temp": 25.0})
        source.add_channel(ChannelMapping(channel_name="temp", source_address="1"))
        return source

    def test_start_polling(self, polling_source):
        """Test starting polling thread"""
        polling_source.connect()
        polling_source.start_polling()

        assert polling_source._running is True
        assert polling_source._poll_thread is not None
        assert polling_source._poll_thread.is_alive()

        polling_source.stop_polling()

    def test_stop_polling(self, polling_source):
        """Test stopping polling thread"""
        polling_source.connect()
        polling_source.start_polling()
        thread = polling_source._poll_thread
        polling_source.stop_polling()

        assert polling_source._running is False
        time.sleep(0.1)
        # Thread may be None after stop or should not be alive
        if thread is not None:
            assert not thread.is_alive()

    def test_polling_updates_values(self, polling_source):
        """Test that polling updates cached values"""
        callback = Mock()
        polling_source.add_callback(callback)

        polling_source.connect()
        polling_source.start_polling()

        # Wait for at least one poll cycle
        time.sleep(0.15)

        polling_source.stop_polling()

        # Callback should have been called
        assert callback.call_count > 0

    def test_double_start_polling(self, polling_source):
        """Test starting polling twice doesn't create multiple threads"""
        polling_source.connect()
        polling_source.start_polling()
        thread1 = polling_source._poll_thread

        polling_source.start_polling()
        thread2 = polling_source._poll_thread

        assert thread1 == thread2

        polling_source.stop_polling()

class TestAutoReconnect:
    """Test auto-reconnect functionality"""

    def test_try_reconnect_success(self):
        """Test successful reconnection"""
        config = DataSourceConfig(
            name="reconnect_test",
            source_type=DataSourceType.MODBUS_TCP,
            retries=3
        )
        source = MockDataSource(config)

        source.status.state = ConnectionState.ERROR
        source._try_reconnect()

        assert source.status.state == ConnectionState.CONNECTED
        assert source.status.error_count == 0

    def test_reconnect_after_errors(self):
        """Test reconnect triggered after error threshold"""
        config = DataSourceConfig(
            name="error_test",
            source_type=DataSourceType.MODBUS_TCP,
            retries=3
        )
        source = MockDataSource(config)
        source.status.error_count = 3
        source.status.state = ConnectionState.ERROR

        source._try_reconnect()

        assert source.status.state == ConnectionState.CONNECTED

class TestDataSourceManager:
    """Test DataSourceManager class"""

    @pytest.fixture
    def manager(self):
        """Create fresh manager instance"""
        # Clear any existing registrations
        DataSourceManager._source_types.clear()
        DataSourceManager.register_source_type(DataSourceType.MODBUS_TCP, MockDataSource)
        return DataSourceManager()

    def test_register_source_type(self):
        """Test registering source type"""
        DataSourceManager._source_types.clear()
        DataSourceManager.register_source_type(DataSourceType.REST_API, MockDataSource)

        assert DataSourceType.REST_API in DataSourceManager._source_types
        assert DataSourceManager._source_types[DataSourceType.REST_API] == MockDataSource

    def test_get_available_types(self, manager):
        """Test getting available types"""
        types = manager.get_available_types()
        assert "modbus_tcp" in types

    def test_add_source(self, manager):
        """Test adding a data source"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.MODBUS_TCP
        )
        channels = [
            ChannelMapping(channel_name="temp", source_address="40001")
        ]

        source = manager.add_source(config, channels)

        assert source is not None
        assert "plc1" in manager.sources
        assert "temp" in source.channels

    def test_add_duplicate_source(self, manager):
        """Test adding duplicate source returns None"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.MODBUS_TCP
        )
        manager.add_source(config)
        result = manager.add_source(config)

        assert result is None

    def test_add_source_unknown_type(self, manager):
        """Test adding source with unknown type"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.S7  # Not registered
        )
        result = manager.add_source(config)

        assert result is None

    def test_remove_source(self, manager):
        """Test removing a data source"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.MODBUS_TCP
        )
        channels = [ChannelMapping(channel_name="temp", source_address="40001")]
        manager.add_source(config, channels)

        manager.remove_source("plc1")

        assert "plc1" not in manager.sources

    def test_get_source(self, manager):
        """Test getting a source by name"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.MODBUS_TCP
        )
        manager.add_source(config)

        source = manager.get_source("plc1")
        assert source is not None
        assert source.name == "plc1"

        # Non-existent source
        assert manager.get_source("unknown") is None

    def test_start_all(self, manager):
        """Test starting all sources"""
        config1 = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        config2 = DataSourceConfig(name="plc2", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config1)
        manager.add_source(config2)

        manager.start_all()

        for source in manager.sources.values():
            assert source.status.state == ConnectionState.CONNECTED

        manager.stop_all()

    def test_start_disabled_source(self, manager):
        """Test disabled sources are not started"""
        config = DataSourceConfig(
            name="disabled_plc",
            source_type=DataSourceType.MODBUS_TCP,
            enabled=False
        )
        manager.add_source(config)
        manager.start_all()

        source = manager.get_source("disabled_plc")
        assert source.status.state != ConnectionState.CONNECTED

    def test_stop_all(self, manager):
        """Test stopping all sources"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config)
        manager.start_all()
        manager.stop_all()

        for source in manager.sources.values():
            assert source.status.state == ConnectionState.DISCONNECTED

    def test_value_callback_aggregation(self, manager):
        """Test value callbacks aggregate from sources"""
        callback = Mock()
        manager.add_value_callback(callback)

        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        source = manager.add_source(config)

        # Simulate source sending values
        values = {"temp": 25.0}
        manager._on_source_values("plc1", values)

        callback.assert_called_once_with(values)
        assert manager._all_values == values

    def test_get_all_values(self, manager):
        """Test getting all values"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config)

        manager._on_source_values("plc1", {"temp": 25.0})
        manager._on_source_values("plc1", {"pressure": 100.5})

        values = manager.get_all_values()
        assert values["temp"] == 25.0
        assert values["pressure"] == 100.5

    def test_read_channel(self, manager):
        """Test reading a channel value"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        source = manager.add_source(config, [
            ChannelMapping(channel_name="temp", source_address="40001")
        ])
        source.set_test_values({"temp": 30.0})

        # From cache
        manager._all_values["temp"] = 25.0
        value = manager.read_channel("temp")
        assert value == 25.0

        # Direct read (no cache)
        manager._all_values.clear()
        value = manager.read_channel("temp")
        assert value == 30.0

    def test_write_channel(self, manager):
        """Test writing to a channel"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        source = manager.add_source(config, [
            ChannelMapping(channel_name="output1", source_address="40001", is_output=True)
        ])

        result = manager.write_channel("output1", 100.0)
        assert result is True
        assert source._test_values["output1"] == 100.0

    def test_write_channel_not_writable(self, manager):
        """Test writing to non-writable channel"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config, [
            ChannelMapping(channel_name="input1", source_address="30001", is_output=False)
        ])

        result = manager.write_channel("input1", 100.0)
        assert result is False

    def test_write_channel_not_found(self, manager):
        """Test writing to non-existent channel"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config)

        result = manager.write_channel("unknown", 100.0)
        assert result is False

    def test_get_all_status(self, manager):
        """Test getting status of all sources"""
        config1 = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        config2 = DataSourceConfig(name="plc2", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config1)
        manager.add_source(config2)

        status = manager.get_all_status()

        assert "plc1" in status
        assert "plc2" in status
        assert "name" in status["plc1"]

    def test_get_all_channels(self, manager):
        """Test getting info about all channels"""
        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config, [
            ChannelMapping(channel_name="temp", source_address="40001", unit="C"),
            ChannelMapping(channel_name="pressure", source_address="40002", unit="PSI")
        ])

        channels = manager.get_all_channels()

        assert "temp" in channels
        assert channels["temp"]["source"] == "plc1"
        assert channels["temp"]["unit"] == "C"
        assert "pressure" in channels

    def test_to_config(self, manager):
        """Test exporting configuration"""
        config = DataSourceConfig(
            name="plc1",
            source_type=DataSourceType.MODBUS_TCP,
            poll_rate_ms=200,
            description="Test PLC"
        )
        manager.add_source(config, [
            ChannelMapping(channel_name="temp", source_address="40001", unit="C", scale=0.1)
        ])

        export = manager.to_config()

        assert "data_sources" in export
        assert len(export["data_sources"]) == 1
        assert export["data_sources"][0]["name"] == "plc1"
        assert len(export["data_sources"][0]["channels"]) == 1

class TestSingleton:
    """Test singleton pattern for manager"""

    def test_get_data_source_manager(self):
        """Test getting singleton instance"""
        # Reset singleton
        import data_source_manager
        data_source_manager._manager_instance = None

        manager1 = get_data_source_manager()
        manager2 = get_data_source_manager()

        assert manager1 is manager2

class TestThreadSafety:
    """Test thread safety of manager"""

    def test_concurrent_value_updates(self):
        """Test concurrent value updates"""
        DataSourceManager._source_types.clear()
        DataSourceManager.register_source_type(DataSourceType.MODBUS_TCP, MockDataSource)
        manager = DataSourceManager()

        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config)

        errors = []

        def update_values(source_name, value_prefix):
            try:
                for i in range(100):
                    manager._on_source_values(source_name, {f"{value_prefix}_{i}": i})
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=update_values, args=("plc1", "a")),
            threading.Thread(target=update_values, args=("plc1", "b")),
            threading.Thread(target=update_values, args=("plc1", "c"))
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes"""
        DataSourceManager._source_types.clear()
        DataSourceManager.register_source_type(DataSourceType.MODBUS_TCP, MockDataSource)
        manager = DataSourceManager()

        config = DataSourceConfig(name="plc1", source_type=DataSourceType.MODBUS_TCP)
        manager.add_source(config, [
            ChannelMapping(channel_name="ch1", source_address="1", is_output=True)
        ])

        errors = []

        def read_loop():
            try:
                for _ in range(100):
                    manager.get_all_values()
                    manager.read_channel("ch1")
            except Exception as e:
                errors.append(e)

        def write_loop():
            try:
                for i in range(100):
                    manager.write_channel("ch1", i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=read_loop),
            threading.Thread(target=read_loop),
            threading.Thread(target=write_loop)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
