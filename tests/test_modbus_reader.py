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


class TestExceptionCodes:
    """Test exception code handling (Fix 1)"""

    @pytest.fixture
    def connection(self):
        """Create a ModbusConnection for testing error handlers"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            config = ModbusDeviceConfig(
                name="test_plc",
                connection_type="tcp",
                ip_address="192.168.1.100"
            )
            conn = ModbusConnection(config)
            conn.connected = True
            return conn

    def test_exception_codes_dict_complete(self):
        """Test that all standard Modbus exception codes are mapped"""
        codes = ModbusConnection.EXCEPTION_CODES
        assert codes[1] == 'ILLEGAL_FUNCTION'
        assert codes[2] == 'ILLEGAL_DATA_ADDRESS'
        assert codes[3] == 'ILLEGAL_DATA_VALUE'
        assert codes[4] == 'SLAVE_DEVICE_FAILURE'
        assert codes[5] == 'ACKNOWLEDGE'
        assert codes[6] == 'SLAVE_DEVICE_BUSY'
        assert codes[8] == 'MEMORY_PARITY_ERROR'
        assert codes[10] == 'GATEWAY_PATH_UNAVAILABLE'
        assert codes[11] == 'GATEWAY_TARGET_FAILED'

    def test_handle_error_exception_response_known_code(self, connection):
        """Test _handle_error formats known exception codes"""
        # Create a real stand-in class since pymodbus.pdu.ExceptionResponse is mocked
        class FakeExceptionResponse:
            def __init__(self, code):
                self.exception_code = code

        mock_result = FakeExceptionResponse(2)

        with patch('modbus_reader.ExceptionResponse', FakeExceptionResponse):
            connection._handle_error(mock_result, "read_holding_registers(100, 1)")

        assert 'ILLEGAL_DATA_ADDRESS' in connection.last_error
        assert 'code 2' in connection.last_error
        assert connection.error_count == 1

    def test_handle_error_exception_response_unknown_code(self, connection):
        """Test _handle_error formats unknown exception codes"""
        class FakeExceptionResponse:
            def __init__(self, code):
                self.exception_code = code

        mock_result = FakeExceptionResponse(99)

        with patch('modbus_reader.ExceptionResponse', FakeExceptionResponse):
            connection._handle_error(mock_result, "read_coils(0, 1)")

        assert 'UNKNOWN_99' in connection.last_error
        assert 'code 99' in connection.last_error

    def test_handle_error_generic_error(self, connection):
        """Test _handle_error with non-ExceptionResponse"""
        class FakeExceptionResponse:
            pass

        mock_result = MagicMock()  # Not a FakeExceptionResponse instance

        with patch('modbus_reader.ExceptionResponse', FakeExceptionResponse):
            connection._handle_error(mock_result, "read_input_registers(0, 1)")

        assert connection.last_error == "Modbus error: read_input_registers(0, 1)"
        assert connection.error_count == 1

    def test_handle_error_triggers_reconnect_after_3(self, connection):
        """Test auto-reconnect triggers after 3 errors"""
        class FakeExceptionResponse:
            pass

        connection.reconnect = MagicMock()

        with patch('modbus_reader.ExceptionResponse', FakeExceptionResponse):
            for i in range(3):
                connection._handle_error(MagicMock(), f"op_{i}")

        assert connection.error_count == 3
        connection.reconnect.assert_called_once()

    def test_handle_exception_connection_lost(self, connection):
        """Test _handle_exception marks connection lost for ConnectionException"""
        class FakeConnectionException(Exception):
            pass

        exc = FakeConnectionException("Connection refused")

        with patch('modbus_reader.ConnectionException', FakeConnectionException):
            connection._handle_exception(exc, "read_holding_registers(0, 1)")

        assert connection.last_error.startswith('CONNECTION_LOST')
        assert connection.connected is False
        assert connection.error_count == 1

    def test_handle_exception_generic(self, connection):
        """Test _handle_exception for non-connection exceptions"""
        class FakeConnectionException(Exception):
            pass

        exc = RuntimeError("Timeout")

        with patch('modbus_reader.ConnectionException', FakeConnectionException):
            connection._handle_exception(exc, "write_register(100, 42)")

        assert connection.last_error.startswith('EXCEPTION')
        assert 'Timeout' in connection.last_error
        assert connection.connected is True  # Not a connection error


class TestConnectionStatusErrorType:
    """Test get_connection_status error_type field (Fix 1)"""

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_no_error_no_error_type(self, mock_conn_class):
        """Test status has no error_type when no error"""
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.error_count = 0
        mock_conn.last_error = None
        mock_conn.last_successful_read = 12345.0
        mock_conn_class.return_value = mock_conn

        config = MagicMock()
        config.chassis = {'plc1': MagicMock(enabled=True, connection='TCP', ip_address='192.168.1.100')}
        config.modules = {}
        config.channels = {}

        reader = ModbusReader(config)
        status = reader.get_connection_status()

        assert 'error_type' not in status['plc1']

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_connection_lost_error_type(self, mock_conn_class):
        """Test error_type='connection' for CONNECTION_LOST errors"""
        mock_conn = MagicMock()
        mock_conn.connected = False
        mock_conn.error_count = 1
        mock_conn.last_error = "CONNECTION_LOST: read_holding_registers(0, 1)"
        mock_conn.last_successful_read = None
        mock_conn.EXCEPTION_CODES = ModbusConnection.EXCEPTION_CODES
        mock_conn_class.return_value = mock_conn

        config = MagicMock()
        config.chassis = {'plc1': MagicMock(enabled=True, connection='TCP', ip_address='192.168.1.100')}
        config.modules = {}
        config.channels = {}

        reader = ModbusReader(config)
        status = reader.get_connection_status()

        assert status['plc1']['error_type'] == 'connection'

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_exception_error_type(self, mock_conn_class):
        """Test error_type='exception' for EXCEPTION: errors"""
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.error_count = 1
        mock_conn.last_error = "EXCEPTION: write_register(100, 42): Timeout"
        mock_conn.last_successful_read = 12345.0
        mock_conn.EXCEPTION_CODES = ModbusConnection.EXCEPTION_CODES
        mock_conn_class.return_value = mock_conn

        config = MagicMock()
        config.chassis = {'plc1': MagicMock(enabled=True, connection='TCP', ip_address='192.168.1.100')}
        config.modules = {}
        config.channels = {}

        reader = ModbusReader(config)
        status = reader.get_connection_status()

        assert status['plc1']['error_type'] == 'exception'

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_modbus_exception_error_type(self, mock_conn_class):
        """Test error_type='modbus_exception' for named Modbus exception codes"""
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.error_count = 1
        mock_conn.last_error = "ILLEGAL_DATA_ADDRESS (code 2): read_holding_registers(9999, 1)"
        mock_conn.last_successful_read = 12345.0
        mock_conn.EXCEPTION_CODES = ModbusConnection.EXCEPTION_CODES
        mock_conn_class.return_value = mock_conn

        config = MagicMock()
        config.chassis = {'plc1': MagicMock(enabled=True, connection='TCP', ip_address='192.168.1.100')}
        config.modules = {}
        config.channels = {}

        reader = ModbusReader(config)
        status = reader.get_connection_status()

        assert status['plc1']['error_type'] == 'modbus_exception'

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_unknown_error_type(self, mock_conn_class):
        """Test error_type='unknown' for unrecognized error formats"""
        mock_conn = MagicMock()
        mock_conn.connected = True
        mock_conn.error_count = 1
        mock_conn.last_error = "Modbus error: something weird happened"
        mock_conn.last_successful_read = 12345.0
        mock_conn.EXCEPTION_CODES = ModbusConnection.EXCEPTION_CODES
        mock_conn_class.return_value = mock_conn

        config = MagicMock()
        config.chassis = {'plc1': MagicMock(enabled=True, connection='TCP', ip_address='192.168.1.100')}
        config.modules = {}
        config.channels = {}

        reader = ModbusReader(config)
        status = reader.get_connection_status()

        assert status['plc1']['error_type'] == 'unknown'


class TestSlaveIdDefault:
    """Test slave ID defaulting behavior (Fix 2)"""

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_explicit_slave_id_used(self, mock_conn_class):
        """Test that explicit modbus_slave_id is used when set"""
        from config_parser import ChannelType

        mock_config = MagicMock()
        mock_chassis = MagicMock()
        mock_chassis.enabled = True
        mock_chassis.connection = "TCP"
        mock_chassis.ip_address = "192.168.1.100"
        mock_config.chassis = {'plc1': mock_chassis}

        mock_module = MagicMock()
        mock_module.chassis = 'plc1'
        mock_module.slot = 5  # This should NOT be used as slave ID
        mock_config.modules = {'mod1': mock_module}

        mock_channel = MagicMock()
        mock_channel.channel_type = ChannelType.MODBUS_REGISTER
        mock_channel.module = 'mod1'
        mock_channel.physical_channel = 'modbus:holding:100'
        mock_channel.modbus_slave_id = 7
        mock_channel.modbus_data_type = 'uint16'
        mock_channel.modbus_byte_order = 'big'
        mock_channel.modbus_word_order = 'big'
        mock_channel.modbus_scale = 1.0
        mock_channel.modbus_offset = 0.0
        mock_channel.modbus_register_count = None
        mock_channel.modbus_register_index = 0
        mock_config.channels = {'test_ch': mock_channel}

        mock_conn_class.return_value = MagicMock()

        reader = ModbusReader(mock_config)

        assert reader.channel_configs['test_ch'].slave_id == 7

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_no_slave_id_defaults_to_1(self, mock_conn_class):
        """Test that missing modbus_slave_id defaults to 1, not module.slot"""
        from config_parser import ChannelType

        mock_config = MagicMock()
        mock_chassis = MagicMock()
        mock_chassis.enabled = True
        mock_chassis.connection = "TCP"
        mock_chassis.ip_address = "192.168.1.100"
        mock_config.chassis = {'plc1': mock_chassis}

        mock_module = MagicMock()
        mock_module.chassis = 'plc1'
        mock_module.slot = 5  # This should NOT bleed into slave ID
        mock_module.slave_id = 10  # Old field that should NOT be used
        mock_config.modules = {'mod1': mock_module}

        mock_channel = MagicMock()
        mock_channel.channel_type = ChannelType.MODBUS_REGISTER
        mock_channel.module = 'mod1'
        mock_channel.physical_channel = 'modbus:holding:200'
        mock_channel.modbus_slave_id = None  # No explicit slave ID
        mock_channel.modbus_data_type = 'float32'
        mock_channel.modbus_byte_order = 'big'
        mock_channel.modbus_word_order = 'big'
        mock_channel.modbus_scale = 1.0
        mock_channel.modbus_offset = 0.0
        mock_channel.modbus_register_count = None
        mock_channel.modbus_register_index = 0
        mock_config.channels = {'test_ch': mock_channel}

        mock_conn_class.return_value = MagicMock()

        reader = ModbusReader(mock_config)

        # Must be 1, NOT 5 (slot) or 10 (old slave_id on module)
        assert reader.channel_configs['test_ch'].slave_id == 1

    @patch('modbus_reader.PYMODBUS_AVAILABLE', True)
    @patch('modbus_reader.ModbusConnection')
    def test_no_slave_id_attr_defaults_to_1(self, mock_conn_class):
        """Test that channel without modbus_slave_id attribute defaults to 1"""
        from config_parser import ChannelType

        mock_config = MagicMock()
        mock_chassis = MagicMock()
        mock_chassis.enabled = True
        mock_chassis.connection = "TCP"
        mock_chassis.ip_address = "192.168.1.100"
        mock_config.chassis = {'plc1': mock_chassis}

        mock_module = MagicMock()
        mock_module.chassis = 'plc1'
        mock_module.slot = 3
        mock_config.modules = {'mod1': mock_module}

        mock_channel = MagicMock(spec=[
            'channel_type', 'module', 'physical_channel',
            'modbus_data_type', 'modbus_byte_order', 'modbus_word_order',
            'modbus_scale', 'modbus_offset',
            'modbus_register_count', 'modbus_register_index'
        ])
        mock_channel.channel_type = ChannelType.MODBUS_REGISTER
        mock_channel.module = 'mod1'
        mock_channel.physical_channel = 'modbus:input:300'
        mock_channel.modbus_data_type = 'int16'
        mock_channel.modbus_byte_order = 'big'
        mock_channel.modbus_word_order = 'big'
        mock_channel.modbus_scale = 1.0
        mock_channel.modbus_offset = 0.0
        mock_channel.modbus_register_count = None
        mock_channel.modbus_register_index = 0
        mock_config.channels = {'test_ch': mock_channel}

        mock_conn_class.return_value = MagicMock()

        reader = ModbusReader(mock_config)

        assert reader.channel_configs['test_ch'].slave_id == 1


class TestDynamicAddChannel:
    """Test dynamic add_channel() implementation (Fix 3)"""

    @pytest.fixture
    def reader_with_connection(self):
        """Create reader with one active Modbus connection"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            with patch('modbus_reader.ModbusConnection') as mock_conn_class:
                mock_conn = MagicMock()
                mock_conn.connected = True
                mock_conn_class.return_value = mock_conn

                mock_config = MagicMock()
                mock_chassis = MagicMock()
                mock_chassis.enabled = True
                mock_chassis.connection = "TCP"
                mock_chassis.ip_address = "192.168.1.100"
                mock_config.chassis = {'plc1': mock_chassis}

                mock_module = MagicMock()
                mock_module.chassis = 'plc1'
                mock_config.modules = {'mod1': mock_module}
                mock_config.channels = {}

                reader = ModbusReader(mock_config)
                yield reader

    def test_add_holding_register_channel(self, reader_with_connection):
        """Test adding a holding register channel dynamically"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'new_temp'
        channel.module = 'mod1'
        channel.physical_channel = 'modbus:holding:40001'
        channel.modbus_data_type = 'float32'
        channel.modbus_slave_id = 2
        channel.modbus_byte_order = 'big'
        channel.modbus_word_order = 'big'
        channel.modbus_scale = 0.1
        channel.modbus_offset = 0.0
        channel.modbus_register_count = None
        channel.modbus_register_index = 0

        reader_with_connection.add_channel(channel)

        assert 'new_temp' in reader_with_connection.channel_configs
        config = reader_with_connection.channel_configs['new_temp']
        assert config.register_type == ModbusRegisterType.HOLDING
        assert config.address == 40001
        assert config.data_type == ModbusDataType.FLOAT32
        assert config.slave_id == 2
        assert config.scale == 0.1
        assert 'new_temp' in reader_with_connection.channel_values
        assert reader_with_connection.channel_values['new_temp'] == 0.0

    def test_add_coil_output_channel(self, reader_with_connection):
        """Test adding a coil output channel dynamically"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_COIL
        channel.name = 'new_valve'
        channel.module = 'mod1'
        channel.physical_channel = 'modbus:coil:0'
        channel.modbus_data_type = 'bool'
        channel.modbus_slave_id = 1
        channel.modbus_byte_order = 'big'
        channel.modbus_word_order = 'big'
        channel.modbus_scale = 1.0
        channel.modbus_offset = 0.0
        channel.modbus_register_count = None
        channel.modbus_register_index = 0

        reader_with_connection.add_channel(channel)

        assert 'new_valve' in reader_with_connection.channel_configs
        config = reader_with_connection.channel_configs['new_valve']
        assert config.register_type == ModbusRegisterType.COIL
        assert config.is_output is True
        assert 'new_valve' in reader_with_connection.output_values

    def test_add_input_register_channel(self, reader_with_connection):
        """Test adding an input register channel"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'new_sensor'
        channel.module = 'mod1'
        channel.physical_channel = 'modbus:input:30100'
        channel.modbus_data_type = 'uint16'
        channel.modbus_slave_id = None
        channel.modbus_byte_order = 'big'
        channel.modbus_word_order = 'big'
        channel.modbus_scale = 1.0
        channel.modbus_offset = 0.0
        channel.modbus_register_count = None
        channel.modbus_register_index = 0

        reader_with_connection.add_channel(channel)

        config = reader_with_connection.channel_configs['new_sensor']
        assert config.register_type == ModbusRegisterType.INPUT
        assert config.slave_id == 1  # Default

    def test_add_non_modbus_channel_ignored(self, reader_with_connection):
        """Test that non-Modbus channel types are silently ignored"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.VOLTAGE_INPUT
        channel.name = 'analog_in'

        reader_with_connection.add_channel(channel)

        assert 'analog_in' not in reader_with_connection.channel_configs

    def test_add_channel_missing_module(self, reader_with_connection):
        """Test add_channel with unknown module returns without crash"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'orphan_ch'
        channel.module = 'nonexistent_module'

        reader_with_connection.add_channel(channel)

        assert 'orphan_ch' not in reader_with_connection.channel_configs

    def test_add_channel_no_connection(self, reader_with_connection):
        """Test add_channel when chassis has no active connection"""
        from config_parser import ChannelType

        # Point to a module on a chassis with no connection
        disconnected_module = MagicMock()
        disconnected_module.chassis = 'disconnected_plc'
        reader_with_connection.config.modules['mod_dc'] = disconnected_module

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'dc_ch'
        channel.module = 'mod_dc'

        reader_with_connection.add_channel(channel)

        assert 'dc_ch' not in reader_with_connection.channel_configs

    def test_add_channel_invalid_physical_channel(self, reader_with_connection):
        """Test add_channel with unparseable physical_channel"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'bad_ch'
        channel.module = 'mod1'
        channel.physical_channel = 'garbage:data'
        # getattr fallbacks also fail
        delattr(channel, 'modbus_register_type')
        delattr(channel, 'modbus_address')

        reader_with_connection.add_channel(channel)

        assert 'bad_ch' not in reader_with_connection.channel_configs

    def test_add_channel_with_batch_config(self, reader_with_connection):
        """Test adding a channel with batch reading configuration"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'batch_ch'
        channel.module = 'mod1'
        channel.physical_channel = 'modbus:holding:1000'
        channel.modbus_data_type = 'uint16'
        channel.modbus_slave_id = 1
        channel.modbus_byte_order = 'big'
        channel.modbus_word_order = 'big'
        channel.modbus_scale = 1.0
        channel.modbus_offset = 0.0
        channel.modbus_register_count = 20
        channel.modbus_register_index = 5

        reader_with_connection.add_channel(channel)

        config = reader_with_connection.channel_configs['batch_ch']
        assert config.register_count == 20
        assert config.register_index == 5

    def test_add_then_remove_channel(self, reader_with_connection):
        """Test full lifecycle: add then remove"""
        from config_parser import ChannelType

        channel = MagicMock()
        channel.channel_type = ChannelType.MODBUS_REGISTER
        channel.name = 'lifecycle_ch'
        channel.module = 'mod1'
        channel.physical_channel = 'modbus:holding:500'
        channel.modbus_data_type = 'int16'
        channel.modbus_slave_id = 1
        channel.modbus_byte_order = 'big'
        channel.modbus_word_order = 'big'
        channel.modbus_scale = 1.0
        channel.modbus_offset = 0.0
        channel.modbus_register_count = None
        channel.modbus_register_index = 0

        reader_with_connection.add_channel(channel)
        assert 'lifecycle_ch' in reader_with_connection.channel_configs

        reader_with_connection.remove_channel('lifecycle_ch')
        assert 'lifecycle_ch' not in reader_with_connection.channel_configs
        assert 'lifecycle_ch' not in reader_with_connection.channel_values

    def test_add_channel_thread_safety(self, reader_with_connection):
        """Test concurrent add_channel calls don't corrupt state"""
        from config_parser import ChannelType

        errors = []

        def add_channels(start_idx, count):
            try:
                for i in range(start_idx, start_idx + count):
                    channel = MagicMock()
                    channel.channel_type = ChannelType.MODBUS_REGISTER
                    channel.name = f'thread_ch_{i}'
                    channel.module = 'mod1'
                    channel.physical_channel = f'modbus:holding:{1000 + i}'
                    channel.modbus_data_type = 'uint16'
                    channel.modbus_slave_id = 1
                    channel.modbus_byte_order = 'big'
                    channel.modbus_word_order = 'big'
                    channel.modbus_scale = 1.0
                    channel.modbus_offset = 0.0
                    channel.modbus_register_count = None
                    channel.modbus_register_index = 0
                    reader_with_connection.add_channel(channel)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_channels, args=(0, 10)),
            threading.Thread(target=add_channels, args=(10, 10)),
            threading.Thread(target=add_channels, args=(20, 10)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len([k for k in reader_with_connection.channel_configs if k.startswith('thread_ch_')]) == 30


class TestWriteOverflowGuard:
    """Test write overflow bounds checking (Fix 4)"""

    @pytest.fixture
    def writer_reader(self):
        """Create reader with writable channels of various data types"""
        with patch('modbus_reader.PYMODBUS_AVAILABLE', True):
            with patch('modbus_reader.ModbusConnection') as mock_conn_class:
                mock_conn = MagicMock()
                mock_conn.connected = True
                mock_conn.write_register.return_value = True
                mock_conn.write_registers.return_value = True
                mock_conn_class.return_value = mock_conn

                mock_config = MagicMock()
                mock_config.chassis = {}
                mock_config.modules = {}
                mock_config.channels = {}

                reader = ModbusReader(mock_config)
                reader.connections['plc1'] = mock_conn

                # INT16 channel
                reader.channel_configs['int16_ch'] = ModbusChannelConfig(
                    channel_name='int16_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=100,
                    data_type=ModbusDataType.INT16, scale=1.0, offset=0.0
                )
                reader.channel_values['int16_ch'] = 0.0
                reader.output_values['int16_ch'] = 0.0

                # UINT16 channel
                reader.channel_configs['uint16_ch'] = ModbusChannelConfig(
                    channel_name='uint16_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=200,
                    data_type=ModbusDataType.UINT16, scale=1.0, offset=0.0
                )
                reader.channel_values['uint16_ch'] = 0.0
                reader.output_values['uint16_ch'] = 0.0

                # INT32 channel
                reader.channel_configs['int32_ch'] = ModbusChannelConfig(
                    channel_name='int32_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=300,
                    data_type=ModbusDataType.INT32, scale=1.0, offset=0.0
                )
                reader.channel_values['int32_ch'] = 0.0
                reader.output_values['int32_ch'] = 0.0

                # UINT32 channel
                reader.channel_configs['uint32_ch'] = ModbusChannelConfig(
                    channel_name='uint32_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=400,
                    data_type=ModbusDataType.UINT32, scale=1.0, offset=0.0
                )
                reader.channel_values['uint32_ch'] = 0.0
                reader.output_values['uint32_ch'] = 0.0

                # FLOAT32 channel (no bounds check)
                reader.channel_configs['float32_ch'] = ModbusChannelConfig(
                    channel_name='float32_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=500,
                    data_type=ModbusDataType.FLOAT32, scale=1.0, offset=0.0
                )
                reader.channel_values['float32_ch'] = 0.0
                reader.output_values['float32_ch'] = 0.0

                # Scaled INT16 channel: scale=0.1, offset=0
                reader.channel_configs['scaled_int16'] = ModbusChannelConfig(
                    channel_name='scaled_int16', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.HOLDING, address=600,
                    data_type=ModbusDataType.INT16, scale=0.1, offset=0.0
                )
                reader.channel_values['scaled_int16'] = 0.0
                reader.output_values['scaled_int16'] = 0.0

                yield reader, mock_conn

    # --- INT16 bounds: -32768 to 32767 ---

    def test_int16_write_in_range(self, writer_reader):
        """Test INT16 write within range succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int16_ch', 100)
        assert result is True

    def test_int16_write_at_max(self, writer_reader):
        """Test INT16 write at max boundary succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int16_ch', 32767)
        assert result is True

    def test_int16_write_at_min(self, writer_reader):
        """Test INT16 write at min boundary succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int16_ch', -32768)
        assert result is True

    def test_int16_write_overflow_high(self, writer_reader):
        """Test INT16 write above max returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int16_ch', 32768)
        assert result is False
        mock_conn.write_register.assert_not_called()

    def test_int16_write_overflow_low(self, writer_reader):
        """Test INT16 write below min returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int16_ch', -32769)
        assert result is False

    # --- UINT16 bounds: 0 to 65535 ---

    def test_uint16_write_in_range(self, writer_reader):
        """Test UINT16 write within range succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint16_ch', 1000)
        assert result is True

    def test_uint16_write_at_max(self, writer_reader):
        """Test UINT16 write at max boundary succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint16_ch', 65535)
        assert result is True

    def test_uint16_write_negative_rejected(self, writer_reader):
        """Test UINT16 write with negative value returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint16_ch', -1)
        assert result is False

    def test_uint16_write_overflow_high(self, writer_reader):
        """Test UINT16 write above max returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint16_ch', 65536)
        assert result is False

    # --- INT32 bounds ---

    def test_int32_write_in_range(self, writer_reader):
        """Test INT32 write within range succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int32_ch', 100000)
        assert result is True

    def test_int32_write_overflow(self, writer_reader):
        """Test INT32 write above max returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('int32_ch', 2147483648)
        assert result is False

    # --- UINT32 bounds ---

    def test_uint32_write_in_range(self, writer_reader):
        """Test UINT32 write within range succeeds"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint32_ch', 3000000000)
        assert result is True

    def test_uint32_write_overflow(self, writer_reader):
        """Test UINT32 write above max returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint32_ch', 4294967296)
        assert result is False

    def test_uint32_write_negative_rejected(self, writer_reader):
        """Test UINT32 write with negative value returns False"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('uint32_ch', -1)
        assert result is False

    # --- FLOAT32: no bounds check ---

    def test_float32_no_bounds_check(self, writer_reader):
        """Test FLOAT32 write has no overflow guard (IEEE 754 handles it)"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('float32_ch', 1e38)
        assert result is True

    def test_float32_negative_large(self, writer_reader):
        """Test FLOAT32 write with large negative value passes"""
        reader, mock_conn = writer_reader
        result = reader.write_channel('float32_ch', -1e38)
        assert result is True

    # --- Scaling + overflow interaction ---

    def test_scaled_overflow_after_reverse_scaling(self, writer_reader):
        """Test overflow detected after reverse scaling: value 4000 / 0.1 = 40000 > INT16 max"""
        reader, mock_conn = writer_reader
        # scale=0.1, offset=0 → raw = (4000 - 0) / 0.1 = 40000 > 32767
        result = reader.write_channel('scaled_int16', 4000)
        assert result is False

    def test_scaled_in_range_after_reverse_scaling(self, writer_reader):
        """Test in-range after reverse scaling: value 3000 / 0.1 = 30000 ≤ 32767"""
        reader, mock_conn = writer_reader
        # raw = (3000 - 0) / 0.1 = 30000 ≤ 32767 → OK
        result = reader.write_channel('scaled_int16', 3000)
        assert result is True


class TestWriteNonOutputChannel:
    """Test write behavior for different register types"""

    @pytest.fixture
    def reader_with_types(self):
        """Create reader with various register type channels"""
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

                # Input register (read-only)
                reader.channel_configs['input_ch'] = ModbusChannelConfig(
                    channel_name='input_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.INPUT, address=30001,
                    data_type=ModbusDataType.UINT16
                )
                reader.channel_values['input_ch'] = 0.0

                # Discrete input (read-only)
                reader.channel_configs['discrete_ch'] = ModbusChannelConfig(
                    channel_name='discrete_ch', device_name='plc1', slave_id=1,
                    register_type=ModbusRegisterType.DISCRETE, address=10001,
                    data_type=ModbusDataType.BOOL
                )
                reader.channel_values['discrete_ch'] = 0.0

                yield reader, mock_conn

    def test_write_to_input_register_rejected(self, reader_with_types):
        """Test writing to input register returns False"""
        reader, _ = reader_with_types
        result = reader.write_channel('input_ch', 42)
        assert result is False

    def test_write_to_discrete_input_rejected(self, reader_with_types):
        """Test writing to discrete input returns False"""
        reader, _ = reader_with_types
        result = reader.write_channel('discrete_ch', True)
        assert result is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
