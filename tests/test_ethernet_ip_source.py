"""
Unit tests for EtherNet/IP Data Source
Tests Allen Bradley PLC communication via pycomm3
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

import sys
sys.path.insert(0, 'services/daq_service')

from data_source_manager import (
    DataSourceType, ConnectionState, ChannelMapping
)

# Mock pycomm3 before importing
@pytest.fixture(autouse=True)
def mock_pycomm3():
    """Mock pycomm3 library"""
    mock_tag = MagicMock()
    mock_tag.value = 100.0
    mock_tag.error = None

    with patch.dict('sys.modules', {
        'pycomm3': MagicMock(),
        'pycomm3.exceptions': MagicMock(),
    }):
        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            yield

from ethernet_ip_source import (
    PlcType, EtherNetIPConfig, EtherNetIPDataSource,
    create_ethernet_ip_source_from_config
)

class TestPlcType:
    """Test PLC type enumeration"""

    def test_plc_types(self):
        """Test PLC type values"""
        assert PlcType.CONTROLLOGIX.value == "controllogix"
        assert PlcType.COMPACTLOGIX.value == "compactlogix"
        assert PlcType.MICRO800.value == "micro800"

class TestEtherNetIPConfig:
    """Test EtherNetIPConfig dataclass"""

    def test_default_values(self):
        """Test default configuration"""
        config = EtherNetIPConfig(
            name="plc1",
            source_type=DataSourceType.ETHERNET_IP
        )
        assert config.ip_address == "192.168.1.1"
        assert config.slot == 0
        assert config.plc_type == "controllogix"
        assert config.init_tags is True
        assert config.use_batch_read is True

    def test_custom_values(self):
        """Test custom configuration"""
        config = EtherNetIPConfig(
            name="plc2",
            source_type=DataSourceType.ETHERNET_IP,
            ip_address="10.0.0.50",
            slot=2,
            plc_type="compactlogix",
            init_tags=False,
            init_program_tags=True
        )
        assert config.ip_address == "10.0.0.50"
        assert config.slot == 2
        assert config.plc_type == "compactlogix"
        assert config.init_tags is False
        assert config.init_program_tags is True

    def test_source_type_set_in_post_init(self):
        """Test source type is set correctly"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.REST_API  # Wrong type
        )
        assert config.source_type == DataSourceType.ETHERNET_IP

class TestEtherNetIPDataSource:
    """Test EtherNetIPDataSource class"""

    @pytest.fixture
    def eip_source(self):
        """Create EtherNet/IP data source"""
        config = EtherNetIPConfig(
            name="test_plc",
            source_type=DataSourceType.ETHERNET_IP,
            ip_address="192.168.1.100",
            slot=0
        )
        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            source = EtherNetIPDataSource(config)
        return source

    def test_initialization(self, eip_source):
        """Test source initialization"""
        assert eip_source.name == "test_plc"
        assert eip_source.plc is None
        assert eip_source._tag_list == []

    def test_get_connection_config(self, eip_source):
        """Test getting connection config"""
        config = eip_source.get_connection_config()

        assert config['ip_address'] == "192.168.1.100"
        assert config['slot'] == 0
        assert config['plc_type'] == "controllogix"
        assert config['use_batch_read'] is True

    @patch('ethernet_ip_source.LogixDriver')
    def test_connect_controllogix(self, mock_driver_class, eip_source):
        """Test connecting to ControlLogix"""
        mock_plc = MagicMock()
        mock_plc.tags = {}
        mock_driver_class.return_value = mock_plc

        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            result = eip_source.connect()

        assert result is True
        assert eip_source.status.state == ConnectionState.CONNECTED
        mock_plc.open.assert_called_once()
        # Check path includes slot
        mock_driver_class.assert_called_once()
        call_args = mock_driver_class.call_args[0][0]
        assert "/0" in call_args

    @patch('ethernet_ip_source.LogixDriver')
    def test_connect_failure(self, mock_driver_class, eip_source):
        """Test connection failure"""
        mock_plc = MagicMock()
        mock_plc.open.side_effect = Exception("Connection refused")
        mock_driver_class.return_value = mock_plc

        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            result = eip_source.connect()

        assert result is False
        assert eip_source.status.state == ConnectionState.ERROR
        assert "Connection refused" in eip_source.status.last_error

    @patch('ethernet_ip_source.LogixDriver')
    def test_disconnect(self, mock_driver_class, eip_source):
        """Test disconnection"""
        mock_plc = MagicMock()
        mock_driver_class.return_value = mock_plc
        eip_source.plc = mock_plc

        eip_source.disconnect()

        mock_plc.close.assert_called_once()
        assert eip_source.plc is None
        assert eip_source.status.state == ConnectionState.DISCONNECTED

class TestTagOperations:
    """Test tag reading/writing operations"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source with mock PLC"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP,
            use_batch_read=False
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_read_channel_success(self, connected_source):
        """Test reading channel successfully"""
        mock_result = MagicMock()
        mock_result.value = 75.5
        mock_result.error = None
        connected_source.plc.read.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="temperature",
            source_address="Program:Main.Temperature"
        ))

        result = connected_source.read_channel("temperature")

        assert result == 75.5
        connected_source.plc.read.assert_called_with("Program:Main.Temperature")

    def test_read_channel_with_scaling(self, connected_source):
        """Test reading with scaling"""
        mock_result = MagicMock()
        mock_result.value = 1000
        mock_result.error = None
        connected_source.plc.read.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="pressure",
            source_address="Pressure_Raw",
            scale=0.01,
            offset=0.0
        ))

        result = connected_source.read_channel("pressure")

        # 1000 * 0.01 = 10.0
        assert result == 10.0

    def test_read_channel_error(self, connected_source):
        """Test handling read error"""
        mock_result = MagicMock()
        mock_result.value = None
        mock_result.error = "Tag not found"
        connected_source.plc.read.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="unknown",
            source_address="NonExistent"
        ))

        result = connected_source.read_channel("unknown")

        assert result is None

    def test_read_channel_not_found(self, connected_source):
        """Test reading non-existent channel"""
        result = connected_source.read_channel("unknown")
        assert result is None

    def test_read_channel_not_connected(self, connected_source):
        """Test reading when not connected"""
        connected_source.status.state = ConnectionState.DISCONNECTED
        connected_source.add_channel(ChannelMapping(
            channel_name="temp",
            source_address="Temp"
        ))

        result = connected_source.read_channel("temp")

        assert result is None

    def test_write_channel_success(self, connected_source):
        """Test writing channel successfully"""
        mock_result = MagicMock()
        mock_result.error = None
        connected_source.plc.write.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="setpoint",
            source_address="Setpoint_Tag",
            is_output=True
        ))

        result = connected_source.write_channel("setpoint", 100.0)

        assert result is True
        connected_source.plc.write.assert_called_with("Setpoint_Tag", 100.0)

    def test_write_channel_with_scaling(self, connected_source):
        """Test writing with reverse scaling"""
        mock_result = MagicMock()
        mock_result.error = None
        connected_source.plc.write.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="output",
            source_address="Output_Raw",
            scale=0.01,
            offset=50.0,
            is_output=True
        ))

        # Write 60 -> raw = (60 - 50) / 0.01 = 1000
        result = connected_source.write_channel("output", 60.0)

        assert result is True
        call_args = connected_source.plc.write.call_args[0]
        assert call_args[1] == 1000.0

    def test_write_channel_not_writable(self, connected_source):
        """Test writing to non-writable channel"""
        connected_source.add_channel(ChannelMapping(
            channel_name="input",
            source_address="Input_Tag",
            is_output=False
        ))

        result = connected_source.write_channel("input", 100.0)

        assert result is False

    def test_write_channel_error(self, connected_source):
        """Test handling write error"""
        mock_result = MagicMock()
        mock_result.error = "Write failed"
        connected_source.plc.write.return_value = mock_result

        connected_source.add_channel(ChannelMapping(
            channel_name="output",
            source_address="Output_Tag",
            is_output=True
        ))

        result = connected_source.write_channel("output", 100.0)

        assert result is False

class TestBatchReading:
    """Test batch reading functionality"""

    @pytest.fixture
    def batch_source(self):
        """Create source with batch reading enabled"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP,
            use_batch_read=True
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_read_all_batch(self, batch_source):
        """Test batch reading multiple tags"""
        # Add multiple channels
        batch_source.add_channel(ChannelMapping(
            channel_name="temp1", source_address="Temp1"
        ))
        batch_source.add_channel(ChannelMapping(
            channel_name="temp2", source_address="Temp2"
        ))
        batch_source.add_channel(ChannelMapping(
            channel_name="temp3", source_address="Temp3"
        ))

        # Mock batch read results
        mock_results = [
            MagicMock(value=25.0, error=None),
            MagicMock(value=30.0, error=None),
            MagicMock(value=35.0, error=None)
        ]
        batch_source.plc.read.return_value = mock_results

        values = batch_source.read_all()

        # Should call read with all tags
        batch_source.plc.read.assert_called_once_with("Temp1", "Temp2", "Temp3")
        assert values["temp1"] == 25.0
        assert values["temp2"] == 30.0
        assert values["temp3"] == 35.0

    def test_read_all_single_result(self, batch_source):
        """Test handling single result (not a list)"""
        batch_source.add_channel(ChannelMapping(
            channel_name="temp", source_address="Temp"
        ))

        # Single result (not wrapped in list)
        mock_result = MagicMock(value=25.0, error=None)
        batch_source.plc.read.return_value = mock_result

        values = batch_source.read_all()

        assert values["temp"] == 25.0

class TestTagList:
    """Test tag list functionality"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_parse_tag_list(self, connected_source):
        """Test parsing tag dictionary"""
        tags_dict = {
            'Temperature': {
                'data_type_name': 'REAL',
                'dim': 0,
                'tag_type': 'atomic'
            },
            'Pressure_Array': {
                'data_type_name': 'REAL',
                'dim': 10,
                'tag_type': 'atomic'
            }
        }

        result = connected_source._parse_tag_list(tags_dict)

        assert len(result) == 2
        assert any(t['name'] == 'Temperature' for t in result)
        assert any(t['name'] == 'Pressure_Array' for t in result)

    def test_get_tag_list_cached(self, connected_source):
        """Test getting cached tag list"""
        connected_source._tag_list = [
            {'name': 'Tag1', 'data_type': 'REAL'}
        ]

        result = connected_source.get_tag_list()

        assert result == connected_source._tag_list
        # Should not call PLC
        connected_source.plc.get_tag_list.assert_not_called()

    def test_get_tag_list_refresh(self, connected_source):
        """Test refreshing tag list"""
        connected_source._tag_list = [{'name': 'OldTag'}]
        connected_source.plc.get_tag_list.return_value = {
            'NewTag': {'data_type_name': 'REAL', 'dim': 0, 'tag_type': 'atomic'}
        }

        result = connected_source.get_tag_list(refresh=True)

        assert any(t['name'] == 'NewTag' for t in result)

class TestPlcInfo:
    """Test PLC info retrieval"""

    def test_get_plc_info(self):
        """Test getting PLC information"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED

        mock_info = MagicMock()
        mock_info.vendor = "Rockwell Automation"
        mock_info.product_type = "Programmable Logic Controller"
        mock_info.product_code = 55
        mock_info.revision = {'major': 33, 'minor': 11}
        mock_info.serial_number = 0x12345678
        mock_info.device_type = "1756-L83E"
        mock_info.product_name = "1756-L83E ControlLogix"

        source.plc.get_plc_info.return_value = mock_info

        info = source.get_plc_info()

        assert info['vendor'] == "Rockwell Automation"
        assert info['revision'] == "33.11"
        assert info['serial_number'] == "0x12345678"

    def test_get_plc_info_not_connected(self):
        """Test PLC info when not connected"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.status.state = ConnectionState.DISCONNECTED

        info = source.get_plc_info()

        assert info == {}

class TestDirectTagAccess:
    """Test direct tag read/write without channel mapping"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_read_tag_direct_success(self, connected_source):
        """Test direct tag read success"""
        mock_result = MagicMock()
        mock_result.value = 42.0
        mock_result.error = None
        connected_source.plc.read.return_value = mock_result

        value, error = connected_source.read_tag_direct("MyTag")

        assert value == 42.0
        assert error is None

    def test_read_tag_direct_error(self, connected_source):
        """Test direct tag read error"""
        mock_result = MagicMock()
        mock_result.value = None
        mock_result.error = "Tag not found"
        connected_source.plc.read.return_value = mock_result

        value, error = connected_source.read_tag_direct("BadTag")

        assert value is None
        assert error == "Tag not found"

    def test_read_tag_direct_not_connected(self, connected_source):
        """Test direct read when not connected"""
        connected_source.status.state = ConnectionState.DISCONNECTED

        value, error = connected_source.read_tag_direct("MyTag")

        assert value is None
        assert error == "Not connected"

    def test_write_tag_direct_success(self, connected_source):
        """Test direct tag write success"""
        mock_result = MagicMock()
        mock_result.error = None
        connected_source.plc.write.return_value = mock_result

        success, error = connected_source.write_tag_direct("MyTag", 100)

        assert success is True
        assert error is None

    def test_write_tag_direct_error(self, connected_source):
        """Test direct tag write error"""
        mock_result = MagicMock()
        mock_result.error = "Write failed"
        connected_source.plc.write.return_value = mock_result

        success, error = connected_source.write_tag_direct("MyTag", 100)

        assert success is False
        assert error == "Write failed"

class TestCreateFromConfig:
    """Test creating source from config dict"""

    def test_create_basic_source(self):
        """Test creating source from basic config"""
        config_dict = {
            'name': 'test_plc',
            'ip_address': '192.168.1.50',
            'slot': 1,
            'plc_type': 'compactlogix',
            'channels': [
                {
                    'name': 'temperature',
                    'tag_name': 'Program:Main.Temperature',
                    'scale': 1.0,
                    'unit': 'C'
                }
            ]
        }

        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            source = create_ethernet_ip_source_from_config(config_dict)

        assert source is not None
        assert source.name == 'test_plc'
        assert source.eip_config.ip_address == '192.168.1.50'
        assert source.eip_config.slot == 1
        assert 'temperature' in source.channels

    def test_create_with_output_channels(self):
        """Test creating source with output channels"""
        config_dict = {
            'name': 'test_plc',
            'ip_address': '192.168.1.50',
            'channels': [
                {
                    'name': 'setpoint',
                    'tag_name': 'Setpoint',
                    'is_output': True
                }
            ]
        }

        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            source = create_ethernet_ip_source_from_config(config_dict)

        assert source.channels['setpoint'].is_output is True

    def test_create_with_invalid_config(self):
        """Test creating with invalid config"""
        with patch('ethernet_ip_source.PYCOMM3_AVAILABLE', True):
            source = create_ethernet_ip_source_from_config(None)

        assert source is None

class TestPrograms:
    """Test program-related functionality"""

    def test_get_programs(self):
        """Test getting program list"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED

        mock_info = MagicMock()
        mock_info.programs = {'MainProgram': {}, 'SubRoutine': {}}
        source.plc.get_plc_info.return_value = mock_info

        programs = source.get_programs()

        assert 'MainProgram' in programs
        assert 'SubRoutine' in programs

    def test_get_program_tags(self):
        """Test getting program-scoped tags"""
        config = EtherNetIPConfig(
            name="test",
            source_type=DataSourceType.ETHERNET_IP
        )
        source = EtherNetIPDataSource(config)
        source.plc = MagicMock()
        source.status.state = ConnectionState.CONNECTED

        source.plc.get_tag_list.return_value = {
            'LocalVar': {'data_type_name': 'DINT', 'dim': 0, 'tag_type': 'atomic'}
        }

        tags = source.get_program_tags('MainProgram')

        source.plc.get_tag_list.assert_called_with(program='MainProgram')
        assert any(t['name'] == 'LocalVar' for t in tags)

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
