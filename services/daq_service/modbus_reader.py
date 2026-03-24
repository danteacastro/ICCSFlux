"""
Modbus Reader for NISystem
Reads from Modbus TCP and RTU devices using pymodbus library
Provides the same interface as HardwareReader/HardwareSimulator for drop-in use
"""

import logging
import struct
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from config_parser import NISystemConfig, ChannelConfig, ChannelType, ChassisConfig

# Try to import pymodbus
try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    from pymodbus.exceptions import ModbusException, ConnectionException
    from pymodbus.pdu import ExceptionResponse
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

logger = logging.getLogger('ModbusReader')

class ModbusRegisterType(Enum):
    """Modbus register types"""
    HOLDING = "holding"       # Read/Write registers (function codes 3, 6, 16)
    INPUT = "input"           # Read-only registers (function code 4)
    COIL = "coil"             # Read/Write bits (function codes 1, 5, 15)
    DISCRETE = "discrete"     # Read-only bits (function code 2)

class ModbusDataType(Enum):
    """Data types for Modbus register interpretation"""
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    BOOL = "bool"

# Number of 16-bit registers needed for each data type
REGISTERS_PER_TYPE = {
    ModbusDataType.INT16: 1,
    ModbusDataType.UINT16: 1,
    ModbusDataType.INT32: 2,
    ModbusDataType.UINT32: 2,
    ModbusDataType.FLOAT32: 2,
    ModbusDataType.FLOAT64: 4,
    ModbusDataType.BOOL: 1,
}

@dataclass
class ModbusDeviceConfig:
    """Configuration for a Modbus device connection"""
    name: str
    connection_type: str  # "tcp" or "rtu"

    # TCP settings
    ip_address: str = ""
    port: int = 502

    # RTU settings (serial)
    serial_port: str = ""
    baudrate: int = 9600
    parity: str = "E"  # N=None, E=Even, O=Odd
    stopbits: int = 1
    bytesize: int = 8

    # Common settings
    slave_id: int = 1
    timeout: float = 1.0
    retries: int = 3
    retry_delay: float = 0.1

@dataclass
class ModbusChannelConfig:
    """Modbus-specific configuration for a channel"""
    channel_name: str
    device_name: str
    slave_id: int
    register_type: ModbusRegisterType
    address: int
    data_type: ModbusDataType
    byte_order: str = "big"      # "big" or "little"
    word_order: str = "big"      # For 32/64-bit values: "big" or "little"
    scale: float = 1.0
    offset: float = 0.0
    is_output: bool = False
    # Batch reading support
    register_count: Optional[int] = None  # Registers to read (None = auto from data_type)
    register_index: int = 0               # Index within batch to extract value from

class ModbusConnection:
    """Manages a single Modbus TCP or RTU connection"""

    def __init__(self, config: ModbusDeviceConfig):
        self.config = config
        self.client = None
        self.lock = threading.RLock()
        self.connected = False
        self.last_error = None
        self.error_count = 0
        self.last_successful_read = 0

        self._create_client()

    def _create_client(self):
        """Create the appropriate Modbus client based on connection type"""
        if self.config.connection_type.lower() == "tcp":
            # pymodbus 3.x API
            self.client = ModbusTcpClient(
                host=self.config.ip_address,
                port=self.config.port,
                timeout=self.config.timeout,
                retries=self.config.retries
            )
            logger.info(f"Created Modbus TCP client for {self.config.name}: "
                       f"{self.config.ip_address}:{self.config.port}")
        else:
            # RTU (serial) connection - pymodbus 3.x API
            parity_map = {'N': 'N', 'E': 'E', 'O': 'O', 'NONE': 'N', 'EVEN': 'E', 'ODD': 'O'}
            parity = parity_map.get(self.config.parity.upper(), 'N')

            self.client = ModbusSerialClient(
                port=self.config.serial_port,
                baudrate=self.config.baudrate,
                parity=parity,
                stopbits=self.config.stopbits,
                bytesize=self.config.bytesize,
                timeout=self.config.timeout,
                retries=self.config.retries
            )
            logger.info(f"Created Modbus RTU client for {self.config.name}: "
                       f"{self.config.serial_port} @ {self.config.baudrate} baud")

    def connect(self) -> bool:
        """Establish connection to the Modbus device"""
        with self.lock:
            try:
                if self.client.connect():
                    self.connected = True
                    self.error_count = 0
                    logger.info(f"Connected to Modbus device: {self.config.name}")
                    return True
                else:
                    self.connected = False
                    self.last_error = "Connection failed"
                    logger.error(f"Failed to connect to Modbus device: {self.config.name}")
                    return False
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                logger.error(f"Connection error for {self.config.name}: {e}")
                return False

    def disconnect(self):
        """Close the Modbus connection"""
        with self.lock:
            try:
                if self.client:
                    self.client.close()
                self.connected = False
                logger.info(f"Disconnected from Modbus device: {self.config.name}")
            except Exception as e:
                logger.error(f"Error disconnecting from {self.config.name}: {e}")

    _reconnect_attempts: int = 0

    def reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff"""
        self.disconnect()
        # Exponential backoff: base_delay * 2^attempts, capped at 30s
        delay = min(self.config.retry_delay * (2 ** self._reconnect_attempts), 30.0)
        logger.info(f"Modbus reconnect to {self.config.name}: attempt {self._reconnect_attempts + 1}, waiting {delay:.1f}s")
        time.sleep(delay)
        success = self.connect()
        if success:
            self._reconnect_attempts = 0
        else:
            self._reconnect_attempts += 1
        return success

    def read_holding_registers(self, address: int, count: int, slave_id: int) -> Optional[List[int]]:
        """Read holding registers (function code 3)"""
        return self._read_registers(address, count, slave_id, "holding")

    def read_input_registers(self, address: int, count: int, slave_id: int) -> Optional[List[int]]:
        """Read input registers (function code 4)"""
        return self._read_registers(address, count, slave_id, "input")

    def read_coils(self, address: int, count: int, slave_id: int) -> Optional[List[bool]]:
        """Read coils (function code 1)"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return None

            try:
                result = self.client.read_coils(address, count=count, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"read_coils({address}, {count})")
                    return None
                self.last_successful_read = time.time()
                self.error_count = 0
                return result.bits[:count]
            except Exception as e:
                self._handle_exception(e, f"read_coils({address}, {count})")
                return None

    def read_discrete_inputs(self, address: int, count: int, slave_id: int) -> Optional[List[bool]]:
        """Read discrete inputs (function code 2)"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return None

            try:
                result = self.client.read_discrete_inputs(address, count=count, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"read_discrete_inputs({address}, {count})")
                    return None
                self.last_successful_read = time.time()
                self.error_count = 0
                return result.bits[:count]
            except Exception as e:
                self._handle_exception(e, f"read_discrete_inputs({address}, {count})")
                return None

    def write_coil(self, address: int, value: bool, slave_id: int) -> bool:
        """Write single coil (function code 5)"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return False

            try:
                result = self.client.write_coil(address, value, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"write_coil({address}, {value})")
                    return False
                return True
            except Exception as e:
                self._handle_exception(e, f"write_coil({address}, {value})")
                return False

    def write_register(self, address: int, value: int, slave_id: int) -> bool:
        """Write single holding register (function code 6)"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return False

            try:
                result = self.client.write_register(address, value, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"write_register({address}, {value})")
                    return False
                return True
            except Exception as e:
                self._handle_exception(e, f"write_register({address}, {value})")
                return False

    def write_registers(self, address: int, values: List[int], slave_id: int) -> bool:
        """Write multiple holding registers (function code 16)"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return False

            try:
                result = self.client.write_registers(address, values, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"write_registers({address}, {values})")
                    return False
                return True
            except Exception as e:
                self._handle_exception(e, f"write_registers({address}, {values})")
                return False

    def _read_registers(self, address: int, count: int, slave_id: int,
                        reg_type: str) -> Optional[List[int]]:
        """Internal method to read registers"""
        with self.lock:
            if not self.connected:
                if not self.connect():
                    return None

            try:
                if reg_type == "holding":
                    result = self.client.read_holding_registers(address, count=count, device_id=slave_id)
                else:
                    result = self.client.read_input_registers(address, count=count, device_id=slave_id)

                if result.isError():
                    self._handle_error(result, f"read_{reg_type}_registers({address}, {count})")
                    return None

                self.last_successful_read = time.time()
                self.error_count = 0
                return result.registers

            except Exception as e:
                self._handle_exception(e, f"read_{reg_type}_registers({address}, {count})")
                return None

    # Modbus exception code descriptions (standard protocol)
    EXCEPTION_CODES = {
        1: 'ILLEGAL_FUNCTION',
        2: 'ILLEGAL_DATA_ADDRESS',
        3: 'ILLEGAL_DATA_VALUE',
        4: 'SLAVE_DEVICE_FAILURE',
        5: 'ACKNOWLEDGE',
        6: 'SLAVE_DEVICE_BUSY',
        8: 'MEMORY_PARITY_ERROR',
        10: 'GATEWAY_PATH_UNAVAILABLE',
        11: 'GATEWAY_TARGET_FAILED',
    }

    def _handle_error(self, result, operation: str):
        """Handle Modbus error response with detailed exception codes"""
        self.error_count += 1
        if isinstance(result, ExceptionResponse):
            code = result.exception_code
            code_name = self.EXCEPTION_CODES.get(code, f'UNKNOWN_{code}')
            self.last_error = f"{code_name} (code {code}): {operation}"
        else:
            self.last_error = f"Modbus error: {operation}"
        logger.warning(f"{self.config.name}: {self.last_error}")

        # Attempt reconnect after multiple errors
        if self.error_count >= 3:
            logger.warning(f"{self.config.name}: Multiple errors, attempting reconnect")
            self.reconnect()

    def _handle_exception(self, e: Exception, operation: str):
        """Handle Python exception during Modbus operation"""
        self.error_count += 1
        if isinstance(e, ConnectionException):
            self.last_error = f"CONNECTION_LOST: {operation}"
            self.connected = False
            logger.warning(f"{self.config.name}: Connection lost, will retry on next read")
        else:
            self.last_error = f"EXCEPTION: {operation}: {str(e)}"
        logger.error(f"{self.config.name}: {self.last_error}")

class ModbusReader:
    """
    Reads from Modbus TCP and RTU devices.
    Provides the same interface as HardwareReader/HardwareSimulator.
    """

    def __init__(self, config: NISystemConfig):
        if not PYMODBUS_AVAILABLE:
            raise RuntimeError("pymodbus library not available - cannot use ModbusReader")

        self.config = config
        self.connections: Dict[str, ModbusConnection] = {}
        self.channel_configs: Dict[str, ModbusChannelConfig] = {}
        self.channel_values: Dict[str, float] = {}
        self.output_values: Dict[str, float] = {}
        self.lock = threading.Lock()

        # Background polling state
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_running = False
        self._latest_values: Dict[str, float] = {}
        self._latest_lock = threading.Lock()
        self._last_poll_duration = 0.0

        self._initialize_connections()
        self._initialize_channels()

    def _initialize_connections(self):
        """Create connections for each Modbus chassis/device"""
        for name, chassis in self.config.chassis.items():
            if not chassis.enabled:
                continue

            conn_type = chassis.connection.upper()
            if conn_type not in ("TCP", "RTU", "MODBUS_TCP", "MODBUS_RTU"):
                continue

            # Determine connection type
            is_tcp = conn_type in ("TCP", "MODBUS_TCP")

            device_config = ModbusDeviceConfig(
                name=name,
                connection_type="tcp" if is_tcp else "rtu",
                # TCP settings
                ip_address=chassis.ip_address if is_tcp else "",
                port=getattr(chassis, 'modbus_port', 502),
                # RTU settings - serial is the COM port (e.g., "COM3" or "/dev/ttyUSB0")
                serial_port=chassis.serial if not is_tcp else "",
                baudrate=getattr(chassis, 'modbus_baudrate', 9600),
                parity=getattr(chassis, 'modbus_parity', 'E'),
                stopbits=getattr(chassis, 'modbus_stopbits', 1),
                bytesize=getattr(chassis, 'modbus_bytesize', 8),
                # Common settings
                timeout=getattr(chassis, 'modbus_timeout', 1.0),
                retries=getattr(chassis, 'modbus_retries', 3),
                slave_id=1  # Default, overridden per-module
            )

            try:
                connection = ModbusConnection(device_config)
                self.connections[name] = connection
                if is_tcp:
                    logger.info(f"Initialized Modbus TCP connection: {name} -> {chassis.ip_address}:{device_config.port}")
                else:
                    logger.info(f"Initialized Modbus RTU connection: {name} -> {chassis.serial} @ {device_config.baudrate} baud")
            except Exception as e:
                logger.error(f"Failed to initialize Modbus connection {name}: {e}")

    @staticmethod
    def _is_output_channel(channel: ChannelConfig, reg_type: 'ModbusRegisterType') -> bool:
        """Determine if a channel is an output (writable) Modbus channel.

        Handles both traditional Modbus channels (channel_type == MODBUS_COIL)
        and CFP channels that use real signal types (digital_output, voltage_output,
        current_output) transported over Modbus.
        """
        # Traditional Modbus coil outputs
        if channel.channel_type == ChannelType.MODBUS_COIL and reg_type == ModbusRegisterType.COIL:
            return True
        # CFP channels with output signal types transported via Modbus
        is_cfp = getattr(channel, 'source_type', '') == 'cfp'
        if is_cfp and channel.channel_type in (
            ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT
        ):
            return True
        # Traditional Modbus holding register outputs (writable registers)
        if channel.channel_type == ChannelType.MODBUS_REGISTER and reg_type == ModbusRegisterType.HOLDING:
            # Holding registers can be read/write — mark as output if explicitly configured
            return getattr(channel, 'modbus_is_output', False)
        return False

    def _initialize_channels(self):
        """Parse channel configurations for Modbus channels"""
        for name, channel in self.config.channels.items():
            # Check if this is a Modbus channel (explicit type or CFP source)
            is_modbus_type = channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
            is_cfp = getattr(channel, 'source_type', '') == 'cfp'
            if not is_modbus_type and not is_cfp:
                continue

            # Get module and chassis
            module = self.config.modules.get(channel.module)
            if not module:
                logger.warning(f"Module not found for Modbus channel {name}")
                continue

            chassis_name = module.chassis
            if chassis_name not in self.connections:
                logger.warning(f"No Modbus connection for chassis {chassis_name}")
                continue

            # Parse physical_channel to get register info
            # Format: "modbus:holding:100" or "modbus:coil:50"
            try:
                parts = channel.physical_channel.split(':')
                if len(parts) >= 3 and parts[0].lower() == 'modbus':
                    reg_type_str = parts[1].lower()
                    address = int(parts[2])
                else:
                    # Fallback: assume holding register at address in physical_channel
                    reg_type_str = getattr(channel, 'modbus_register_type', 'holding')
                    address = getattr(channel, 'modbus_address', int(channel.physical_channel))
            except (ValueError, AttributeError):
                logger.error(f"Invalid Modbus channel config for {name}: {channel.physical_channel}")
                continue

            # Map register type
            reg_type_map = {
                'holding': ModbusRegisterType.HOLDING,
                'input': ModbusRegisterType.INPUT,
                'coil': ModbusRegisterType.COIL,
                'discrete': ModbusRegisterType.DISCRETE,
            }
            reg_type = reg_type_map.get(reg_type_str, ModbusRegisterType.HOLDING)

            # Get data type
            data_type_str = getattr(channel, 'modbus_data_type', 'float32')
            data_type_map = {
                'int16': ModbusDataType.INT16,
                'uint16': ModbusDataType.UINT16,
                'int32': ModbusDataType.INT32,
                'uint32': ModbusDataType.UINT32,
                'float32': ModbusDataType.FLOAT32,
                'float64': ModbusDataType.FLOAT64,
                'bool': ModbusDataType.BOOL,
            }
            data_type = data_type_map.get(data_type_str.lower(), ModbusDataType.FLOAT32)

            # Get slave ID: explicit channel config > device default (1)
            # Never fall back to module.slot — slot is chassis position, not Modbus unit ID
            explicit_slave_id = getattr(channel, 'modbus_slave_id', None)
            if explicit_slave_id is not None:
                slave_id = explicit_slave_id
            else:
                slave_id = 1
                logger.debug(f"Channel {name}: no explicit modbus_slave_id, using default 1")

            # Batch reading config
            register_count = getattr(channel, 'modbus_register_count', None)
            register_index = getattr(channel, 'modbus_register_index', 0)

            # Create channel config
            modbus_config = ModbusChannelConfig(
                channel_name=name,
                device_name=chassis_name,
                slave_id=slave_id,
                register_type=reg_type,
                address=address,
                data_type=data_type,
                byte_order=getattr(channel, 'modbus_byte_order', 'big'),
                word_order=getattr(channel, 'modbus_word_order', 'big'),
                scale=getattr(channel, 'modbus_scale', 1.0),
                offset=getattr(channel, 'modbus_offset', 0.0),
                is_output=self._is_output_channel(channel, reg_type),
                register_count=register_count,
                register_index=register_index
            )

            self.channel_configs[name] = modbus_config
            self.channel_values[name] = 0.0

            if modbus_config.is_output:
                self.output_values[name] = 0.0

            logger.info(f"Configured Modbus channel: {name} -> {chassis_name}/{reg_type_str}:{address}")

    def connect_all(self) -> Dict[str, bool]:
        """Connect to all Modbus devices"""
        results = {}
        for name, connection in self.connections.items():
            results[name] = connection.connect()
        return results

    def disconnect_all(self):
        """Disconnect from all Modbus devices"""
        for connection in self.connections.values():
            connection.disconnect()

    def start_polling(self):
        """Start background polling thread. Modbus reads run asynchronously
        so they don't block the main scan loop."""
        if self._poll_thread and self._poll_thread.is_alive():
            return  # Already running

        self._poll_running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="ModbusPoller",
            daemon=True
        )
        self._poll_thread.start()
        logger.info("Modbus background polling started")

    def stop_polling(self):
        """Stop background polling thread."""
        self._poll_running = False
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
            logger.info("Modbus background polling stopped")
        self._poll_thread = None

    def _poll_loop(self):
        """Background thread: continuously reads all Modbus channels.
        Polls as fast as the serial/TCP links allow — no artificial rate cap.
        RTU at 9600 baud naturally limits to ~1-2 Hz, TCP to ~5-10 Hz."""
        while self._poll_running:
            start = time.time()
            try:
                live_values = self.read_all()
                with self._latest_lock:
                    self._latest_values = live_values
            except Exception as e:
                logger.error(f"Modbus poll error: {e}")
                time.sleep(1.0)  # Back off on error to avoid spin

            self._last_poll_duration = time.time() - start

    def get_latest_values(self) -> Dict[str, float]:
        """Return the most recent values from background polling.
        Non-blocking — just returns whatever was last read.
        Channels with failed reads are excluded (triggers COMM_FAIL)."""
        with self._latest_lock:
            return self._latest_values.copy()

    def read_channel(self, channel_name: str) -> Optional[float]:
        """Read a single Modbus channel value"""
        if channel_name not in self.channel_configs:
            return None

        config = self.channel_configs[channel_name]
        connection = self.connections.get(config.device_name)
        if not connection:
            return None

        value = self._read_channel_value(connection, config)
        if value is not None:
            self.channel_values[channel_name] = value

        return value

    def read_all(self) -> Dict[str, float]:
        """
        Read all Modbus channels and return raw values.
        This matches the HardwareReader.read_all() interface.

        Supports batch reading: channels with the same device/slave/register_type
        and register_count are read together in a single Modbus transaction.

        Channels whose reads fail are EXCLUDED from the return dict so that
        the DAQ service's COMM_FAIL alarm mechanism can detect offline devices.
        """
        with self.lock:
            # Track which channels were successfully read this cycle
            live_values: Dict[str, float] = {}

            # Group channels for batch reading
            # Key: (device_name, slave_id, register_type, address, register_count)
            batch_groups: Dict[tuple, List[ModbusChannelConfig]] = {}
            individual_channels: List[ModbusChannelConfig] = []

            for name, config in self.channel_configs.items():
                if config.register_count is not None and config.register_count > 0:
                    # Batch mode: group by device/slave/type/address/count
                    key = (config.device_name, config.slave_id, config.register_type,
                           config.address, config.register_count)
                    if key not in batch_groups:
                        batch_groups[key] = []
                    batch_groups[key].append(config)
                else:
                    # Individual mode
                    individual_channels.append(config)

            # Read batch groups
            for key, channels in batch_groups.items():
                device_name, slave_id, reg_type, address, count = key
                connection = self.connections.get(device_name)
                if not connection:
                    continue

                # Read the batch
                registers = self._read_register_batch(connection, reg_type, address, count, slave_id)
                if registers is None:
                    continue

                # Extract each channel's value from the batch
                for config in channels:
                    value = self._extract_value_from_batch(registers, config)
                    if value is not None:
                        self.channel_values[config.channel_name] = value
                        live_values[config.channel_name] = value

            # Read individual channels
            for config in individual_channels:
                connection = self.connections.get(config.device_name)
                if not connection:
                    continue

                value = self._read_channel_value(connection, config)
                if value is not None:
                    self.channel_values[config.channel_name] = value
                    live_values[config.channel_name] = value

            return live_values

    def _read_register_batch(self, connection: ModbusConnection,
                              reg_type: ModbusRegisterType,
                              address: int, count: int, slave_id: int) -> Optional[List[int]]:
        """Read a batch of registers in a single Modbus transaction."""
        try:
            if reg_type == ModbusRegisterType.INPUT:
                return connection.read_input_registers(address, count, slave_id)
            elif reg_type == ModbusRegisterType.HOLDING:
                return connection.read_holding_registers(address, count, slave_id)
            else:
                logger.warning(f"Batch read not supported for {reg_type.value}")
                return None
        except Exception as e:
            logger.error(f"Error reading register batch at {address}: {e}")
            return None

    def _extract_value_from_batch(self, registers: List[int],
                                   config: ModbusChannelConfig) -> Optional[float]:
        """Extract a single channel's value from a batch of registers."""
        try:
            # Get the number of registers needed for this data type
            regs_needed = REGISTERS_PER_TYPE.get(config.data_type, 1)

            # Extract the registers for this channel
            start_idx = config.register_index
            end_idx = start_idx + regs_needed

            if end_idx > len(registers):
                logger.error(f"Register index {start_idx}+{regs_needed} exceeds batch size "
                           f"{len(registers)} for {config.channel_name}")
                return None

            channel_regs = registers[start_idx:end_idx]

            # Decode the value
            raw_value = self._decode_registers(channel_regs, config.data_type,
                                               config.byte_order, config.word_order)

            # Apply scaling: value = raw * scale + offset
            scaled_value = raw_value * config.scale + config.offset
            return scaled_value

        except Exception as e:
            logger.error(f"Error extracting value for {config.channel_name}: {e}")
            return None

    def _read_channel_value(self, connection: ModbusConnection,
                            config: ModbusChannelConfig) -> Optional[float]:
        """Read and decode a single channel value from Modbus device"""
        try:
            if config.register_type == ModbusRegisterType.COIL:
                bits = connection.read_coils(config.address, 1, config.slave_id)
                if bits is None:
                    return None
                return 1.0 if bits[0] else 0.0

            elif config.register_type == ModbusRegisterType.DISCRETE:
                bits = connection.read_discrete_inputs(config.address, 1, config.slave_id)
                if bits is None:
                    return None
                return 1.0 if bits[0] else 0.0

            else:
                # Register read (holding or input)
                count = REGISTERS_PER_TYPE.get(config.data_type, 1)

                if config.register_type == ModbusRegisterType.INPUT:
                    registers = connection.read_input_registers(
                        config.address, count, config.slave_id
                    )
                else:
                    registers = connection.read_holding_registers(
                        config.address, count, config.slave_id
                    )

                if registers is None:
                    return None

                # Decode the value
                raw_value = self._decode_registers(registers, config.data_type,
                                                   config.byte_order, config.word_order)

                # Apply scaling: value = raw * scale + offset
                scaled_value = raw_value * config.scale + config.offset
                return scaled_value

        except Exception as e:
            logger.error(f"Error reading Modbus channel {config.channel_name}: {e}")
            return None

    def _decode_registers(self, registers: List[int], data_type: ModbusDataType,
                          byte_order: str, word_order: str) -> float:
        """Decode register values to appropriate data type"""
        # Handle word order for multi-register values
        if len(registers) > 1 and word_order.lower() == "little":
            registers = list(reversed(registers))

        # Determine byte order prefix for struct
        bo = '>' if byte_order.lower() == 'big' else '<'

        # Convert registers to bytes
        if byte_order.lower() == 'big':
            raw_bytes = b''.join(reg.to_bytes(2, 'big') for reg in registers)
        else:
            raw_bytes = b''.join(reg.to_bytes(2, 'little') for reg in registers)

        # Decode based on data type
        if data_type == ModbusDataType.INT16:
            return struct.unpack(f'{bo}h', raw_bytes)[0]
        elif data_type == ModbusDataType.UINT16:
            return struct.unpack(f'{bo}H', raw_bytes)[0]
        elif data_type == ModbusDataType.INT32:
            return struct.unpack(f'{bo}i', raw_bytes)[0]
        elif data_type == ModbusDataType.UINT32:
            return struct.unpack(f'{bo}I', raw_bytes)[0]
        elif data_type == ModbusDataType.FLOAT32:
            return struct.unpack(f'{bo}f', raw_bytes)[0]
        elif data_type == ModbusDataType.FLOAT64:
            return struct.unpack(f'{bo}d', raw_bytes)[0]
        elif data_type == ModbusDataType.BOOL:
            return 1.0 if registers[0] != 0 else 0.0
        else:
            return float(registers[0])

    def _encode_value(self, value: float, data_type: ModbusDataType,
                      byte_order: str, word_order: str) -> List[int]:
        """Encode a value to register values for writing"""
        bo = '>' if byte_order.lower() == 'big' else '<'

        # Pack value to bytes
        if data_type == ModbusDataType.INT16:
            raw_bytes = struct.pack(f'{bo}h', int(value))
        elif data_type == ModbusDataType.UINT16:
            raw_bytes = struct.pack(f'{bo}H', int(value))
        elif data_type == ModbusDataType.INT32:
            raw_bytes = struct.pack(f'{bo}i', int(value))
        elif data_type == ModbusDataType.UINT32:
            raw_bytes = struct.pack(f'{bo}I', int(value))
        elif data_type == ModbusDataType.FLOAT32:
            raw_bytes = struct.pack(f'{bo}f', value)
        elif data_type == ModbusDataType.FLOAT64:
            raw_bytes = struct.pack(f'{bo}d', value)
        else:
            raw_bytes = struct.pack(f'{bo}H', int(value))

        # Convert bytes to registers
        registers = []
        for i in range(0, len(raw_bytes), 2):
            if byte_order.lower() == 'big':
                reg = int.from_bytes(raw_bytes[i:i+2], 'big')
            else:
                reg = int.from_bytes(raw_bytes[i:i+2], 'little')
            registers.append(reg)

        # Handle word order
        if len(registers) > 1 and word_order.lower() == "little":
            registers = list(reversed(registers))

        return registers

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """
        Write a value to a Modbus output channel.
        Matches HardwareReader.write_channel() interface.
        """
        if channel_name not in self.channel_configs:
            logger.warning(f"Channel {channel_name} not found")
            return False

        config = self.channel_configs[channel_name]
        connection = self.connections.get(config.device_name)
        if not connection:
            logger.warning(f"No connection for channel {channel_name}")
            return False

        try:
            if config.register_type == ModbusRegisterType.COIL:
                # Write coil
                bool_value = bool(value) if not isinstance(value, bool) else value
                success = connection.write_coil(config.address, bool_value, config.slave_id)
                if success:
                    self.output_values[channel_name] = 1.0 if bool_value else 0.0
                    self.channel_values[channel_name] = self.output_values[channel_name]
                return success

            elif config.register_type == ModbusRegisterType.HOLDING:
                # Reverse the scaling: raw = (value - offset) / scale
                if config.scale != 0:
                    raw_value = (float(value) - config.offset) / config.scale
                else:
                    raw_value = float(value)

                # Bounds check: prevent overflow for integer data types
                DATA_TYPE_BOUNDS = {
                    ModbusDataType.INT16: (-32768, 32767),
                    ModbusDataType.UINT16: (0, 65535),
                    ModbusDataType.INT32: (-2147483648, 2147483647),
                    ModbusDataType.UINT32: (0, 4294967295),
                }
                bounds = DATA_TYPE_BOUNDS.get(config.data_type)
                if bounds is not None:
                    lo, hi = bounds
                    if raw_value < lo or raw_value > hi:
                        logger.error(
                            f"Write overflow for {channel_name}: raw value {raw_value} "
                            f"exceeds {config.data_type.value} range [{lo}, {hi}]"
                        )
                        return False
                    raw_value = int(raw_value)

                # Encode and write
                registers = self._encode_value(raw_value, config.data_type,
                                               config.byte_order, config.word_order)

                if len(registers) == 1:
                    success = connection.write_register(config.address, registers[0], config.slave_id)
                else:
                    success = connection.write_registers(config.address, registers, config.slave_id)

                if success:
                    self.output_values[channel_name] = float(value)
                    self.channel_values[channel_name] = float(value)
                return success

            else:
                logger.warning(f"Cannot write to {config.register_type.value} register type")
                return False

        except Exception as e:
            logger.error(f"Error writing to Modbus channel {channel_name}: {e}")
            return False

    def set_temperature_target(self, channel_name: str, target: float):
        """
        For compatibility with simulator interface.
        Modbus doesn't have temperature targets - this is a no-op.
        """
        pass

    def add_channel(self, channel: ChannelConfig):
        """Add a new Modbus channel dynamically without requiring service restart."""
        is_modbus_type = channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
        is_cfp = getattr(channel, 'source_type', '') == 'cfp'
        if not is_modbus_type and not is_cfp:
            return  # Not a Modbus channel, ignore

        name = channel.name

        # Get module and chassis
        module = self.config.modules.get(channel.module)
        if not module:
            logger.warning(f"add_channel: module not found for {name}")
            return

        chassis_name = module.chassis
        if chassis_name not in self.connections:
            logger.warning(f"add_channel: no Modbus connection for chassis {chassis_name}")
            return

        # Parse physical_channel for register info
        try:
            parts = channel.physical_channel.split(':')
            if len(parts) >= 3 and parts[0].lower() == 'modbus':
                reg_type_str = parts[1].lower()
                address = int(parts[2])
            else:
                reg_type_str = getattr(channel, 'modbus_register_type', 'holding')
                address = getattr(channel, 'modbus_address', int(channel.physical_channel))
        except (ValueError, AttributeError):
            logger.error(f"add_channel: invalid config for {name}: {channel.physical_channel}")
            return

        reg_type_map = {
            'holding': ModbusRegisterType.HOLDING,
            'input': ModbusRegisterType.INPUT,
            'coil': ModbusRegisterType.COIL,
            'discrete': ModbusRegisterType.DISCRETE,
        }
        reg_type = reg_type_map.get(reg_type_str, ModbusRegisterType.HOLDING)

        data_type_str = getattr(channel, 'modbus_data_type', 'float32')
        data_type_map = {
            'int16': ModbusDataType.INT16, 'uint16': ModbusDataType.UINT16,
            'int32': ModbusDataType.INT32, 'uint32': ModbusDataType.UINT32,
            'float32': ModbusDataType.FLOAT32, 'float64': ModbusDataType.FLOAT64,
            'bool': ModbusDataType.BOOL,
        }
        data_type = data_type_map.get(data_type_str.lower(), ModbusDataType.FLOAT32)

        explicit_slave_id = getattr(channel, 'modbus_slave_id', None)
        slave_id = explicit_slave_id if explicit_slave_id is not None else 1

        modbus_config = ModbusChannelConfig(
            channel_name=name,
            device_name=chassis_name,
            slave_id=slave_id,
            register_type=reg_type,
            address=address,
            data_type=data_type,
            byte_order=getattr(channel, 'modbus_byte_order', 'big'),
            word_order=getattr(channel, 'modbus_word_order', 'big'),
            scale=getattr(channel, 'modbus_scale', 1.0),
            offset=getattr(channel, 'modbus_offset', 0.0),
            is_output=self._is_output_channel(channel, reg_type),
            register_count=getattr(channel, 'modbus_register_count', None),
            register_index=getattr(channel, 'modbus_register_index', 0)
        )

        with self.lock:
            self.channel_configs[name] = modbus_config
            self.channel_values[name] = 0.0
            if modbus_config.is_output:
                self.output_values[name] = 0.0

        logger.info(f"Dynamically added Modbus channel: {name} -> {chassis_name}/{reg_type_str}:{address}")

    def remove_channel(self, channel_name: str):
        """Remove a channel dynamically (thread-safe)."""
        with self.lock:
            if channel_name in self.channel_configs:
                del self.channel_configs[channel_name]
            if channel_name in self.channel_values:
                del self.channel_values[channel_name]
            if channel_name in self.output_values:
                del self.output_values[channel_name]

    def trigger_event(self, event_type: str):
        """
        For compatibility with simulator interface.
        Modbus doesn't have simulated events - this is a no-op.
        """
        pass

    def close(self):
        """Stop polling and close all Modbus connections"""
        logger.info("Closing Modbus reader...")
        self.stop_polling()
        self.disconnect_all()
        logger.info("Modbus reader closed")

    def get_connection_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all Modbus connections with detailed error info"""
        status = {}
        for name, conn in self.connections.items():
            entry: Dict[str, Any] = {
                'connected': conn.connected,
                'error_count': conn.error_count,
                'last_error': conn.last_error,
                'last_successful_read': conn.last_successful_read,
            }
            # Parse structured error type from last_error for frontend display
            if conn.last_error:
                error = conn.last_error
                if error.startswith('CONNECTION_LOST'):
                    entry['error_type'] = 'connection'
                elif error.startswith('EXCEPTION'):
                    entry['error_type'] = 'exception'
                elif any(error.startswith(code_name) for code_name in conn.EXCEPTION_CODES.values()):
                    entry['error_type'] = 'modbus_exception'
                else:
                    entry['error_type'] = 'unknown'
            status[name] = entry
        return status

    def __enter__(self):
        self.connect_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

# Test code
if __name__ == "__main__":
    import sys
    from pathlib import Path

    if not PYMODBUS_AVAILABLE:
        print("pymodbus not available - cannot test ModbusReader")
        print("Install with: pip install pymodbus")
        sys.exit(1)

    # Simple test with mock configuration
    print("ModbusReader module loaded successfully")
    print("pymodbus version available")

    # Test data type encoding/decoding
    reader = type('MockReader', (), {
        '_decode_registers': ModbusReader._decode_registers,
        '_encode_value': ModbusReader._encode_value,
    })()

    # Test float32
    test_val = 123.456
    encoded = reader._encode_value(None, test_val, ModbusDataType.FLOAT32, 'big', 'big')
    decoded = reader._decode_registers(None, encoded, ModbusDataType.FLOAT32, 'big', 'big')
    print(f"Float32 roundtrip: {test_val} -> {encoded} -> {decoded:.3f}")

    # Test int32
    test_val = -12345
    encoded = reader._encode_value(None, test_val, ModbusDataType.INT32, 'big', 'big')
    decoded = reader._decode_registers(None, encoded, ModbusDataType.INT32, 'big', 'big')
    print(f"Int32 roundtrip: {test_val} -> {encoded} -> {decoded}")
