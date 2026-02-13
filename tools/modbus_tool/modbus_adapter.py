"""
Standalone Modbus adapter for the Modbus Poll Tool.
Extracted from services/daq_service/modbus_reader.py — keep in sync if decode/encode logic changes.

This module is self-contained: no dependency on the DAQ service or config_parser.
Only requires: pymodbus >= 3.0.0, pyserial >= 3.5
"""

import logging
import struct
import threading
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('ModbusTool')

# Try to import pymodbus
try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    from pymodbus.exceptions import ModbusException, ConnectionException
    from pymodbus.pdu import ExceptionResponse
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

# Try to import serial port listing
try:
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# Modbus exception code names (standard)
EXCEPTION_CODES = {
    1: "Illegal Function",
    2: "Illegal Data Address",
    3: "Illegal Data Value",
    4: "Slave Device Failure",
    5: "Acknowledge",
    6: "Slave Device Busy",
    7: "Negative Acknowledge",
    8: "Memory Parity Error",
    10: "Gateway Path Unavailable",
    11: "Gateway Target Device Failed to Respond",
}


class ModbusRegisterType(Enum):
    HOLDING = "holding"
    INPUT = "input"
    COIL = "coil"
    DISCRETE = "discrete"


class ModbusDataType(Enum):
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    BOOL = "bool"


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
    name: str
    connection_type: str  # "tcp" or "rtu"
    # TCP
    ip_address: str = ""
    port: int = 502
    # RTU
    serial_port: str = ""
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    # Common
    slave_id: int = 1
    timeout: float = 1.0
    retries: int = 3
    retry_delay: float = 0.1


class ModbusConnection:
    """Manages a single Modbus TCP or RTU connection. Thread-safe."""

    def __init__(self, config: ModbusDeviceConfig):
        if not PYMODBUS_AVAILABLE:
            raise RuntimeError("pymodbus not installed. Install with: pip install pymodbus pyserial")
        self.config = config
        self.client = None
        self.lock = threading.Lock()
        self.connected = False
        self.last_error = None
        self.error_count = 0
        self.last_successful_read = 0
        self._reconnect_attempts = 0
        self._create_client()

    def _create_client(self):
        if self.config.connection_type.lower() == "tcp":
            self.client = ModbusTcpClient(
                host=self.config.ip_address,
                port=self.config.port,
                timeout=self.config.timeout,
                retries=self.config.retries,
            )
        else:
            parity_map = {'N': 'N', 'E': 'E', 'O': 'O', 'NONE': 'N', 'EVEN': 'E', 'ODD': 'O'}
            parity = parity_map.get(self.config.parity.upper(), 'N')
            self.client = ModbusSerialClient(
                port=self.config.serial_port,
                baudrate=self.config.baudrate,
                parity=parity,
                stopbits=self.config.stopbits,
                bytesize=self.config.bytesize,
                timeout=self.config.timeout,
                retries=self.config.retries,
            )

    def connect(self) -> bool:
        with self.lock:
            try:
                if self.client.connect():
                    self.connected = True
                    self.error_count = 0
                    self._reconnect_attempts = 0
                    return True
                else:
                    self.connected = False
                    self.last_error = "Connection failed"
                    return False
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                return False

    def disconnect(self):
        with self.lock:
            try:
                if self.client:
                    self.client.close()
                self.connected = False
            except Exception:
                pass

    def reconnect(self) -> bool:
        self.disconnect()
        delay = min(self.config.retry_delay * (2 ** self._reconnect_attempts), 30.0)
        time.sleep(delay)
        success = self.connect()
        if not success:
            self._reconnect_attempts += 1
        return success

    def read_holding_registers(self, address: int, count: int, slave_id: int) -> Optional[List[int]]:
        return self._read_registers(address, count, slave_id, "holding")

    def read_input_registers(self, address: int, count: int, slave_id: int) -> Optional[List[int]]:
        return self._read_registers(address, count, slave_id, "input")

    def read_coils(self, address: int, count: int, slave_id: int) -> Optional[List[bool]]:
        with self.lock:
            if not self.connected:
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
        with self.lock:
            if not self.connected:
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
        """Write single coil (FC5)."""
        with self.lock:
            if not self.connected:
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

    def write_coils(self, address: int, values: List[bool], slave_id: int) -> bool:
        """Write multiple coils (FC15)."""
        with self.lock:
            if not self.connected:
                return False
            try:
                result = self.client.write_coils(address, values, device_id=slave_id)
                if result.isError():
                    self._handle_error(result, f"write_coils({address}, {values})")
                    return False
                return True
            except Exception as e:
                self._handle_exception(e, f"write_coils({address}, {values})")
                return False

    def write_register(self, address: int, value: int, slave_id: int) -> bool:
        """Write single register (FC6)."""
        with self.lock:
            if not self.connected:
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
        """Write multiple registers (FC16)."""
        with self.lock:
            if not self.connected:
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

    def read_device_identification(self, slave_id: int) -> Optional[Dict[str, str]]:
        """Read Device Identification (FC43/14). Returns dict of object_id -> value."""
        with self.lock:
            if not self.connected:
                return None
            try:
                from pymodbus.mei_message import ReadDeviceInformationRequest
                request = ReadDeviceInformationRequest(read_code=0x01, device_id=slave_id)
                result = self.client.execute(request)
                if result is None or result.isError():
                    return None
                info = {}
                id_names = {
                    0: "VendorName", 1: "ProductCode", 2: "MajorMinorRevision",
                    3: "VendorUrl", 4: "ProductName", 5: "ModelName",
                    6: "UserApplicationName",
                }
                for obj_id, value in result.information.items():
                    name = id_names.get(obj_id, f"Object_{obj_id}")
                    info[name] = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)
                return info
            except ImportError:
                return None
            except Exception as e:
                self._handle_exception(e, "read_device_identification")
                return None

    def _read_registers(self, address: int, count: int, slave_id: int,
                        reg_type: str) -> Optional[List[int]]:
        with self.lock:
            if not self.connected:
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

    def _handle_error(self, result, operation: str):
        self.error_count += 1
        if isinstance(result, ExceptionResponse):
            code_name = EXCEPTION_CODES.get(result.exception_code, "Unknown")
            self.last_error = f"Exception {result.exception_code} ({code_name}): {operation}"
        else:
            self.last_error = f"Modbus error: {operation}"
        logger.warning(f"{self.config.name}: {self.last_error}")

    def _handle_exception(self, e: Exception, operation: str):
        self.error_count += 1
        self.last_error = f"{operation}: {str(e)}"
        logger.error(f"{self.config.name}: {self.last_error}")
        if isinstance(e, ConnectionException):
            self.connected = False


def decode_registers(registers: List[int], data_type: ModbusDataType,
                     byte_order: str = "big", word_order: str = "big") -> float:
    """Decode raw 16-bit register values to a numeric value."""
    if len(registers) > 1 and word_order.lower() == "little":
        registers = list(reversed(registers))

    bo = '>' if byte_order.lower() == 'big' else '<'

    if byte_order.lower() == 'big':
        raw_bytes = b''.join(reg.to_bytes(2, 'big') for reg in registers)
    else:
        raw_bytes = b''.join(reg.to_bytes(2, 'little') for reg in registers)

    format_map = {
        ModbusDataType.INT16: f'{bo}h',
        ModbusDataType.UINT16: f'{bo}H',
        ModbusDataType.INT32: f'{bo}i',
        ModbusDataType.UINT32: f'{bo}I',
        ModbusDataType.FLOAT32: f'{bo}f',
        ModbusDataType.FLOAT64: f'{bo}d',
    }

    fmt = format_map.get(data_type)
    if fmt:
        return struct.unpack(fmt, raw_bytes)[0]
    elif data_type == ModbusDataType.BOOL:
        return 1.0 if registers[0] != 0 else 0.0
    else:
        return float(registers[0])


def encode_value(value: float, data_type: ModbusDataType,
                 byte_order: str = "big", word_order: str = "big") -> List[int]:
    """Encode a numeric value to raw 16-bit register values for writing."""
    bo = '>' if byte_order.lower() == 'big' else '<'

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

    registers = []
    for i in range(0, len(raw_bytes), 2):
        if byte_order.lower() == 'big':
            reg = int.from_bytes(raw_bytes[i:i + 2], 'big')
        else:
            reg = int.from_bytes(raw_bytes[i:i + 2], 'little')
        registers.append(reg)

    if len(registers) > 1 and word_order.lower() == "little":
        registers = list(reversed(registers))

    return registers


def list_serial_ports() -> List[Dict[str, str]]:
    """List available serial/COM ports."""
    if not SERIAL_AVAILABLE:
        return []
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "port": p.device,
            "description": p.description,
            "hwid": p.hwid,
        })
    return ports
