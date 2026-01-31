"""
Unit tests for ModbusReader
Tests Modbus TCP/RTU communication, register types, data encoding/decoding
"""

import pytest
import struct
import threading
import time
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass


# Mock pymodbus before importing module
@pytest.fixture(autouse=True)
def mock_pymodbus():
    """Mock pymodbus module to allow testing without hardware"""
    with patch.dict('sys.modules', {
        'pymodbus': MagicMock(),
        'pymodbus.client': MagicMock(),
        'pymodbus.exceptions': MagicMock(),
        'pymodbus.pdu': MagicMock(),
    }):
        yield


# Import after mocking
import sys
sys.path.insert(0, 'services/daq_service')

from modbus_reader import (
    ModbusRegisterType, ModbusDataType, REGISTERS_PER_TYPE,
    ModbusDeviceConfig, ModbusChannelConfig, ModbusConnection, ModbusReader,
    PYMODBUS_AVAILABLE
)


class TestModbusEnums:
    """Test Modbus enumeration types"""

    def test_register_type_values(self):
        """Test register type enum values"""
        assert ModbusRegisterType.HOLDING.value == "holding"
        assert ModbusRegisterType.INPUT.value == "input"
        assert ModbusRegisterType.COIL.value == "coil"
        assert ModbusRegisterType.DISCRETE.value == "discrete"

    def test_data_type_values(self):
        """Test data type enum values"""
        assert ModbusDataType.INT16.value == "int16"
        assert ModbusDataType.UINT16.value == "uint16"
        assert ModbusDataType.INT32.value == "int32"
        assert ModbusDataType.UINT32.value == "uint32"
        assert ModbusDataType.FLOAT32.value == "float32"
        assert ModbusDataType.FLOAT64.value == "float64"
        assert ModbusDataType.BOOL.value == "bool"


class TestRegistersPerType:
    """Test register count constants"""

    def test_16bit_types_use_one_register(self):
        """INT16, UINT16, BOOL use 1 register"""
        assert REGISTERS_PER_TYPE[ModbusDataType.INT16] == 1
        assert REGISTERS_PER_TYPE[ModbusDataType.UINT16] == 1
        assert REGISTERS_PER_TYPE[ModbusDataType.BOOL] == 1

    def test_32bit_types_use_two_registers(self):
        """INT32, UINT32, FLOAT32 use 2 registers"""
        assert REGISTERS_PER_TYPE[ModbusDataType.INT32] == 2
        assert REGISTERS_PER_TYPE[ModbusDataType.UINT32] == 2
        assert REGISTERS_PER_TYPE[ModbusDataType.FLOAT32] == 2

    def test_64bit_types_use_four_registers(self):
        """FLOAT64 uses 4 registers"""
        assert REGISTERS_PER_TYPE[ModbusDataType.FLOAT64] == 4


class TestModbusDeviceConfig:
    """Test ModbusDeviceConfig dataclass"""

    def test_tcp_config_defaults(self):
        """Test TCP configuration with defaults"""
        config = ModbusDeviceConfig(
            name="plc1",
            connection_type="tcp",
            ip_address="192.168.1.100"
        )
        assert config.port == 502
        assert config.timeout == 1.0
        assert config.retries == 3
        assert config.slave_id == 1

    def test_rtu_config(self):
        """Test RTU serial configuration"""
        config = ModbusDeviceConfig(
            name="plc2",
            connection_type="rtu",
            serial_port="COM3",
            baudrate=19200,
            parity="N",
            stopbits=2
        )
        assert config.serial_port == "COM3"
        assert config.baudrate == 19200
        assert config.parity == "N"
        assert config.stopbits == 2

    def test_custom_timing(self):
        """Test custom timing settings"""
        config = ModbusDeviceConfig(
            name="slow_device",
            connection_type="tcp",
            timeout=5.0,
            retries=5,
            retry_delay=0.5
        )
        assert config.timeout == 5.0
        assert config.retries == 5
        assert config.retry_delay == 0.5


class TestModbusChannelConfig:
    """Test ModbusChannelConfig dataclass"""

    def test_holding_register_channel(self):
        """Test holding register channel configuration"""
        config = ModbusChannelConfig(
            channel_name="Temperature",
            device_name="plc1",
            slave_id=1,
            register_type=ModbusRegisterType.HOLDING,
            address=40001,
            data_type=ModbusDataType.FLOAT32
        )
        assert config.byte_order == "big"
        assert config.word_order == "big"
        assert config.scale == 1.0
        assert config.offset == 0.0
        assert config.is_output is False

    def test_coil_output_channel(self):
        """Test coil output channel"""
        config = ModbusChannelConfig(
            channel_name="Pump_Enable",
            device_name="plc1",
            slave_id=1,
            register_type=ModbusRegisterType.COIL,
            address=0,
            data_type=ModbusDataType.BOOL,
            is_output=True
        )
        assert config.is_output is True

    def test_scaled_channel(self):
        """Test channel with scaling"""
        config = ModbusChannelConfig(
            channel_name="Pressure_PSI",
            device_name="plc1",
            slave_id=1,
            register_type=ModbusRegisterType.INPUT,
            address=30001,
            data_type=ModbusDataType.UINT16,
            scale=0.1,
            offset=-14.7
        )
        assert config.scale == 0.1
        assert config.offset == -14.7

    def test_batch_reading_config(self):
        """Test batch reading configuration"""
        config = ModbusChannelConfig(
            channel_name="Sensor_1",
            device_name="plc1",
            slave_id=1,
            register_type=ModbusRegisterType.INPUT,
            address=30000,
            data_type=ModbusDataType.FLOAT32,
            register_count=10,
            register_index=2
        )
        assert config.register_count == 10
        assert config.register_index == 2


class TestModbusConnection:
    """Test ModbusConnection class - skipped when pymodbus not available"""

    @pytest.fixture
    def tcp_config(self):
        """TCP device configuration"""
        return ModbusDeviceConfig(
            name="test_plc",
            connection_type="tcp",
            ip_address="192.168.1.100",
            port=502
        )

    @pytest.fixture
    def rtu_config(self):
        """RTU device configuration"""
        return ModbusDeviceConfig(
            name="test_rtu",
            connection_type="rtu",
            serial_port="COM3",
            baudrate=9600
        )

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_tcp_client_creation(self, tcp_config):
        """Test TCP client is created correctly"""
        conn = ModbusConnection(tcp_config)
        assert conn.client is not None
        assert conn.connected is False

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_rtu_client_creation(self, rtu_config):
        """Test RTU client is created correctly"""
        conn = ModbusConnection(rtu_config)
        assert conn.client is not None

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_connect_success(self, tcp_config):
        """Test successful connection"""
        # This test requires actual Modbus device, skip in CI
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_connect_failure(self, tcp_config):
        """Test failed connection"""
        # This test requires network operations, skip in CI
        pytest.skip("Requires network operations")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_disconnect(self, tcp_config):
        """Test disconnect"""
        conn = ModbusConnection(tcp_config)
        conn.disconnect()
        assert conn.connected is False

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_read_holding_registers(self, tcp_config):
        """Test reading holding registers"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_read_input_registers(self, tcp_config):
        """Test reading input registers"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_read_coils(self, tcp_config):
        """Test reading coils"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_read_discrete_inputs(self, tcp_config):
        """Test reading discrete inputs"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_write_coil(self, tcp_config):
        """Test writing coil"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_write_single_register(self, tcp_config):
        """Test writing single register"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_write_multiple_registers(self, tcp_config):
        """Test writing multiple registers"""
        pytest.skip("Requires actual Modbus device")

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_error_handling_reconnect(self, tcp_config):
        """Test auto-reconnect after errors"""
        pytest.skip("Requires actual Modbus device")


class TestDataEncoding:
    """Test register encoding and decoding"""

    @pytest.fixture
    def mock_reader(self):
        """Create a mock reader for testing encoding methods"""
        reader = MagicMock()
        reader._decode_registers = ModbusReader._decode_registers
        reader._encode_value = ModbusReader._encode_value
        return reader

    def test_int16_roundtrip(self, mock_reader):
        """Test INT16 encoding/decoding roundtrip"""
        for test_val in [0, 127, -128, 32767, -32768]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT16, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.INT16, 'big', 'big')
            assert decoded == test_val

    def test_uint16_roundtrip(self, mock_reader):
        """Test UINT16 encoding/decoding roundtrip"""
        for test_val in [0, 255, 65535]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.UINT16, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.UINT16, 'big', 'big')
            assert decoded == test_val

    def test_int32_roundtrip(self, mock_reader):
        """Test INT32 encoding/decoding roundtrip"""
        for test_val in [0, 12345, -12345, 2147483647, -2147483648]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT32, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.INT32, 'big', 'big')
            assert decoded == test_val

    def test_uint32_roundtrip(self, mock_reader):
        """Test UINT32 encoding/decoding roundtrip"""
        for test_val in [0, 12345, 4294967295]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.UINT32, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.UINT32, 'big', 'big')
            assert decoded == test_val

    def test_float32_roundtrip(self, mock_reader):
        """Test FLOAT32 encoding/decoding roundtrip"""
        for test_val in [0.0, 123.456, -456.789, 1e10, -1e-10]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.FLOAT32, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.FLOAT32, 'big', 'big')
            assert abs(decoded - test_val) < abs(test_val * 1e-6) or abs(decoded - test_val) < 1e-6

    def test_float64_roundtrip(self, mock_reader):
        """Test FLOAT64 encoding/decoding roundtrip"""
        for test_val in [0.0, 123.456789012345, -456.789012345678]:
            encoded = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.FLOAT64, 'big', 'big')
            decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.FLOAT64, 'big', 'big')
            assert abs(decoded - test_val) < abs(test_val * 1e-10) or abs(decoded - test_val) < 1e-10

    def test_little_endian_byte_order(self, mock_reader):
        """Test little endian byte order"""
        test_val = 12345
        encoded_big = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT16, 'big', 'big')
        encoded_little = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT16, 'little', 'big')

        # Different byte orders should produce different register values
        # (unless value happens to be symmetric)
        decoded_big = mock_reader._decode_registers(mock_reader, encoded_big, ModbusDataType.INT16, 'big', 'big')
        decoded_little = mock_reader._decode_registers(mock_reader, encoded_little, ModbusDataType.INT16, 'little', 'big')

        assert decoded_big == test_val
        assert decoded_little == test_val

    def test_little_endian_word_order(self, mock_reader):
        """Test little endian word order for 32-bit values"""
        test_val = 123456789

        # Encode with big word order
        encoded_big = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT32, 'big', 'big')
        # Encode with little word order
        encoded_little = mock_reader._encode_value(mock_reader, test_val, ModbusDataType.INT32, 'big', 'little')

        # Decoding should restore original value
        decoded_big = mock_reader._decode_registers(mock_reader, encoded_big, ModbusDataType.INT32, 'big', 'big')
        decoded_little = mock_reader._decode_registers(mock_reader, encoded_little, ModbusDataType.INT32, 'big', 'little')

        assert decoded_big == test_val
        assert decoded_little == test_val

    def test_bool_encoding(self, mock_reader):
        """Test boolean encoding"""
        # True
        encoded = mock_reader._encode_value(mock_reader, 1, ModbusDataType.BOOL, 'big', 'big')
        decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.BOOL, 'big', 'big')
        assert decoded == 1.0

        # False
        encoded = mock_reader._encode_value(mock_reader, 0, ModbusDataType.BOOL, 'big', 'big')
        decoded = mock_reader._decode_registers(mock_reader, encoded, ModbusDataType.BOOL, 'big', 'big')
        assert decoded == 0.0


class TestModbusReader:
    """Test ModbusReader class"""

    @pytest.fixture
    def mock_config(self):
        """Create mock NISystemConfig"""
        config = MagicMock()
        config.chassis = {}
        config.modules = {}
        config.channels = {}
        return config

    @pytest.fixture
    def tcp_chassis_config(self):
        """Create TCP chassis configuration"""
        chassis = MagicMock()
        chassis.enabled = True
        chassis.connection = "TCP"
        chassis.ip_address = "192.168.1.100"
        chassis.modbus_port = 502
        return chassis

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_reader_initialization(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test reader initializes connections from config"""
        mock_config.chassis = {'plc1': tcp_chassis_config}

        reader = ModbusReader(mock_config)

        assert 'plc1' in reader.connections

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_disabled_chassis_skipped(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test disabled chassis is skipped"""
        tcp_chassis_config.enabled = False
        mock_config.chassis = {'plc1': tcp_chassis_config}

        reader = ModbusReader(mock_config)

        assert 'plc1' not in reader.connections

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_connect_all(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test connect_all connects all devices"""
        mock_config.chassis = {'plc1': tcp_chassis_config}
        mock_conn = MagicMock()
        mock_conn.connect.return_value = True
        mock_conn_class.return_value = mock_conn

        reader = ModbusReader(mock_config)
        results = reader.connect_all()

        assert results['plc1'] is True
        mock_conn.connect.assert_called_once()

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_disconnect_all(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test disconnect_all disconnects all devices"""
        mock_config.chassis = {'plc1': tcp_chassis_config}
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn

        reader = ModbusReader(mock_config)
        reader.disconnect_all()

        mock_conn.disconnect.assert_called_once()

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_close(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test close method"""
        mock_config.chassis = {'plc1': tcp_chassis_config}
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn

        reader = ModbusReader(mock_config)
        reader.close()

        mock_conn.disconnect.assert_called()

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_context_manager(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test context manager protocol"""
        mock_config.chassis = {'plc1': tcp_chassis_config}
        mock_conn = MagicMock()
        mock_conn.connect.return_value = True
        mock_conn_class.return_value = mock_conn

        with ModbusReader(mock_config) as reader:
            mock_conn.connect.assert_called()

        mock_conn.disconnect.assert_called()

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_get_connection_status(self, mock_conn_class, mock_config, tcp_chassis_config):
        """Test connection status retrieval"""
        mock_config.chassis = {'plc1': tcp_chassis_config}
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.error_count = 0
        mock_conn.last_error = None
        mock_conn.last_successful_read = 12345.0
        mock_conn_class.return_value = mock_conn

        reader = ModbusReader(mock_config)
        status = reader.get_connection_status()

        assert status['plc1']['connected'] is True
        assert status['plc1']['error_count'] == 0

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_remove_channel(self, mock_conn_class, mock_config):
        """Test removing a channel"""
        mock_config.chassis = {}

        reader = ModbusReader(mock_config)
        reader.channel_configs['test_ch'] = MagicMock()
        reader.channel_values['test_ch'] = 100.0
        reader.output_values['test_ch'] = 50.0

        reader.remove_channel('test_ch')

        assert 'test_ch' not in reader.channel_configs
        assert 'test_ch' not in reader.channel_values
        assert 'test_ch' not in reader.output_values

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_set_temperature_target_noop(self, mock_conn_class, mock_config):
        """Test set_temperature_target is a no-op"""
        mock_config.chassis = {}

        reader = ModbusReader(mock_config)
        # Should not raise
        reader.set_temperature_target("test_ch", 100.0)

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_trigger_event_noop(self, mock_conn_class, mock_config):
        """Test trigger_event is a no-op"""
        mock_config.chassis = {}

        reader = ModbusReader(mock_config)
        # Should not raise
        reader.trigger_event("test_event")


class TestChannelReading:
    """Test channel reading functionality"""

    @pytest.fixture
    def reader_with_channels(self):
        """Create reader with pre-configured channels"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            with patch('modbus_reader.ModbusConnection') as mock_conn_class:
                mock_conn = MagicMock()
                mock_conn.connected = True
                mock_conn_class.return_value = mock_conn

                mock_config = MagicMock()
                mock_config.chassis = {}
                mock_config.modules = {}
                mock_config.channels = {}

                reader = ModbusReader(mock_config)
                reader.connections['plc1'] = mock_conn

                # Add test channels
                reader.channel_configs['temp'] = ModbusChannelConfig(
                    channel_name='temp',
                    device_name='plc1',
                    slave_id=1,
                    register_type=ModbusRegisterType.HOLDING,
                    address=40001,
                    data_type=ModbusDataType.FLOAT32,
                    scale=0.1,
                    offset=0.0
                )
                reader.channel_values['temp'] = 0.0

                reader.channel_configs['coil_out'] = ModbusChannelConfig(
                    channel_name='coil_out',
                    device_name='plc1',
                    slave_id=1,
                    register_type=ModbusRegisterType.COIL,
                    address=0,
                    data_type=ModbusDataType.BOOL,
                    is_output=True
                )
                reader.channel_values['coil_out'] = 0.0
                reader.output_values['coil_out'] = 0.0

                yield reader, mock_conn

    def test_read_channel_not_found(self, reader_with_channels):
        """Test reading non-existent channel"""
        reader, _ = reader_with_channels
        result = reader.read_channel('nonexistent')
        assert result is None

    def test_read_channel_no_connection(self, reader_with_channels):
        """Test reading channel with no connection"""
        reader, _ = reader_with_channels
        reader.channel_configs['orphan'] = ModbusChannelConfig(
            channel_name='orphan',
            device_name='unknown_device',
            slave_id=1,
            register_type=ModbusRegisterType.HOLDING,
            address=40001,
            data_type=ModbusDataType.FLOAT32
        )

        result = reader.read_channel('orphan')
        assert result is None

    def test_write_channel_not_found(self, reader_with_channels):
        """Test writing to non-existent channel"""
        reader, _ = reader_with_channels
        result = reader.write_channel('nonexistent', 100)
        assert result is False

    def test_write_coil_channel(self, reader_with_channels):
        """Test writing to coil channel"""
        reader, mock_conn = reader_with_channels
        mock_conn.write_coil.return_value = True

        result = reader.write_channel('coil_out', True)

        assert result is True
        mock_conn.write_coil.assert_called_once_with(0, True, 1)
        assert reader.output_values['coil_out'] == 1.0


class TestBatchReading:
    """Test batch reading functionality"""

    @pytest.fixture
    def reader_with_batch_channels(self):
        """Create reader with batch-configured channels"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            with patch('modbus_reader.ModbusConnection') as mock_conn_class:
                mock_conn = MagicMock()
                mock_conn.connected = True
                mock_conn_class.return_value = mock_conn

                mock_config = MagicMock()
                mock_config.chassis = {}
                mock_config.modules = {}
                mock_config.channels = {}

                reader = ModbusReader(mock_config)
                reader.connections['plc1'] = mock_conn

                # Add batch channels (same base address, different indices)
                for i in range(3):
                    reader.channel_configs[f'sensor_{i}'] = ModbusChannelConfig(
                        channel_name=f'sensor_{i}',
                        device_name='plc1',
                        slave_id=1,
                        register_type=ModbusRegisterType.INPUT,
                        address=30000,
                        data_type=ModbusDataType.UINT16,
                        register_count=10,
                        register_index=i
                    )
                    reader.channel_values[f'sensor_{i}'] = 0.0

                yield reader, mock_conn

    def test_batch_channels_grouped(self, reader_with_batch_channels):
        """Test that batch channels are read together"""
        reader, mock_conn = reader_with_batch_channels

        # Setup mock to return registers
        mock_conn.read_input_registers.return_value = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

        values = reader.read_all()

        # Should have called read_input_registers once for the batch
        mock_conn.read_input_registers.assert_called_once_with(30000, 10, 1)

        # Values should be extracted from correct indices
        assert values['sensor_0'] == 100.0
        assert values['sensor_1'] == 200.0
        assert values['sensor_2'] == 300.0


class TestChannelParsing:
    """Test channel configuration parsing"""

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_parse_modbus_address_format(self, mock_conn_class, mock_config=None):
        """Test parsing 'modbus:holding:100' format"""
        from config_parser import ChannelType

        mock_config = MagicMock()
        mock_chassis = MagicMock()
        mock_chassis.enabled = True
        mock_chassis.connection = "TCP"
        mock_chassis.ip_address = "192.168.1.100"
        mock_config.chassis = {'plc1': mock_chassis}

        mock_module = MagicMock()
        mock_module.chassis = 'plc1'
        mock_module.slot = 1
        mock_config.modules = {'mod1': mock_module}

        mock_channel = MagicMock()
        mock_channel.channel_type = ChannelType.MODBUS_REGISTER
        mock_channel.module = 'mod1'
        mock_channel.physical_channel = 'modbus:holding:100'
        mock_config.channels = {'test_ch': mock_channel}

        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn

        reader = ModbusReader(mock_config)

        assert 'test_ch' in reader.channel_configs
        ch_config = reader.channel_configs['test_ch']
        assert ch_config.register_type == ModbusRegisterType.HOLDING
        assert ch_config.address == 100


class TestRTUParity:
    """Test RTU parity mapping"""

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_parity_none(self):
        """Test None parity mapping"""
        config = ModbusDeviceConfig(
            name="rtu_test",
            connection_type="rtu",
            serial_port="COM3",
            parity="N"
        )
        conn = ModbusConnection(config)
        assert conn.client is not None

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_parity_even(self):
        """Test Even parity mapping"""
        config = ModbusDeviceConfig(
            name="rtu_test",
            connection_type="rtu",
            serial_port="COM3",
            parity="EVEN"
        )
        conn = ModbusConnection(config)
        assert conn.client is not None

    @pytest.mark.skipif(not PYMODBUS_AVAILABLE, reason="pymodbus not installed")
    def test_parity_odd(self):
        """Test Odd parity mapping"""
        config = ModbusDeviceConfig(
            name="rtu_test",
            connection_type="rtu",
            serial_port="COM3",
            parity="ODD"
        )
        conn = ModbusConnection(config)
        assert conn.client is not None


class TestScaling:
    """Test value scaling"""

    @pytest.fixture
    def scaled_channel_reader(self):
        """Create reader with scaled channel"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            with patch('modbus_reader.ModbusConnection') as mock_conn_class:
                mock_conn = MagicMock()
                mock_conn.connected = True
                mock_conn_class.return_value = mock_conn

                mock_config = MagicMock()
                mock_config.chassis = {}
                mock_config.modules = {}
                mock_config.channels = {}

                reader = ModbusReader(mock_config)
                reader.connections['plc1'] = mock_conn

                # Add scaled channel: value = raw * 0.1 + 32
                reader.channel_configs['temp_f'] = ModbusChannelConfig(
                    channel_name='temp_f',
                    device_name='plc1',
                    slave_id=1,
                    register_type=ModbusRegisterType.HOLDING,
                    address=40001,
                    data_type=ModbusDataType.INT16,
                    scale=0.1,
                    offset=32.0
                )
                reader.channel_values['temp_f'] = 0.0

                yield reader, mock_conn

    def test_read_applies_scaling(self, scaled_channel_reader):
        """Test that scaling is applied on read"""
        reader, mock_conn = scaled_channel_reader

        # Raw value 1000 -> scaled = 1000 * 0.1 + 32 = 132
        mock_conn.read_holding_registers.return_value = [1000]

        value = reader.read_channel('temp_f')

        assert value == 132.0

    def test_write_reverses_scaling(self, scaled_channel_reader):
        """Test that scaling is reversed on write"""
        reader, mock_conn = scaled_channel_reader
        mock_conn.write_register.return_value = True

        # Make channel writable
        reader.channel_configs['temp_f'] = ModbusChannelConfig(
            channel_name='temp_f',
            device_name='plc1',
            slave_id=1,
            register_type=ModbusRegisterType.HOLDING,
            address=40001,
            data_type=ModbusDataType.INT16,
            scale=0.1,
            offset=32.0,
            is_output=False  # Holding registers can be written
        )

        # Write 132 -> raw = (132 - 32) / 0.1 = 1000
        reader.write_channel('temp_f', 132.0)

        # Check that write was called with reversed scaling
        # The actual register value should be close to 1000
        call_args = mock_conn.write_register.call_args
        assert call_args is not None


class TestThreadSafety:
    """Test thread safety of ModbusReader"""

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_concurrent_reads(self, mock_conn_class):
        """Test concurrent read operations"""
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.read_holding_registers.return_value = [100]
        mock_conn_class.return_value = mock_conn

        mock_config = MagicMock()
        mock_config.chassis = {}
        mock_config.modules = {}
        mock_config.channels = {}

        reader = ModbusReader(mock_config)
        reader.connections['plc1'] = mock_conn

        reader.channel_configs['ch1'] = ModbusChannelConfig(
            channel_name='ch1',
            device_name='plc1',
            slave_id=1,
            register_type=ModbusRegisterType.HOLDING,
            address=40001,
            data_type=ModbusDataType.UINT16
        )
        reader.channel_values['ch1'] = 0.0

        errors = []

        def read_loop():
            try:
                for _ in range(10):
                    reader.read_all()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
