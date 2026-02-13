"""
Modbus register reading for GC instruments.

Simplified from the main DAQ modbus_reader.py -- no batch optimization
since GC instruments typically have a small number of registers.

Supports:
  - Modbus TCP and RTU connections
  - Holding, input, coil, and discrete register types
  - Data types: int16, uint16, int32, uint32, float32, float64, bool
  - Linear scaling (value * scale + offset) per register
  - Auto-reconnect on connection loss
"""

import logging
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .config import ModbusSourceConfig

logger = logging.getLogger('GCNode')

# Try to import pymodbus; source will not start if unavailable.
try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    from pymodbus.exceptions import ModbusException, ConnectionException
    from pymodbus.pdu import ExceptionResponse
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    ModbusTcpClient = None
    ModbusSerialClient = None

# Number of 16-bit registers required per data type
_REGISTERS_PER_TYPE: Dict[str, int] = {
    'int16': 1,
    'uint16': 1,
    'int32': 2,
    'uint32': 2,
    'float32': 2,
    'float64': 4,
    'bool': 1,
}

# struct format codes per data type (big-endian prefix added at decode time)
_FORMAT_MAP: Dict[str, str] = {
    'int16': 'h',
    'uint16': 'H',
    'int32': 'i',
    'uint32': 'I',
    'float32': 'f',
    'float64': 'd',
}


class ModbusSource:
    """Reads GC data from Modbus TCP/RTU registers.

    Simplified from the main DAQ modbus_reader.py - no batch optimization
    since GC instruments have few registers.

    Args:
        config: ModbusSourceConfig with connection params and register map.
        on_new_data: Callback receiving {name: {value, unit}} dict.
    """

    def __init__(self, config: ModbusSourceConfig, on_new_data: Callable[[dict], None]):
        self._config = config
        self._on_new_data = on_new_data

        self._client = None
        self._connected = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

        # Reconnection state
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 30.0

        # Error tracking
        self._last_error: str = ""
        self._error_count: int = 0
        self._last_successful_read: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Modbus polling loop."""
        if not PYMODBUS_AVAILABLE:
            logger.error(
                "ModbusSource: pymodbus not installed. "
                "Install with: pip install pymodbus pyserial"
            )
            return

        if not self._config.registers:
            logger.warning("ModbusSource: No registers configured, nothing to poll")
            return

        self._stop_event.clear()

        if not self._connect():
            logger.warning(
                "ModbusSource: Initial connection failed, "
                "will retry in poll loop"
            )

        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="ModbusSource-Poll",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info(
            f"ModbusSource: Started polling "
            f"({self._config.connection_type.upper()} "
            f"{'%s:%d' % (self._config.ip_address, self._config.port) if self._config.connection_type == 'tcp' else self._config.serial_port}, "
            f"slave={self._config.slave_id}, "
            f"{len(self._config.registers)} register(s), "
            f"interval={self._config.poll_interval_s}s)"
        )

    def stop(self) -> None:
        """Stop the Modbus polling loop and disconnect."""
        self._stop_event.set()

        if self._poll_thread is not None:
            self._poll_thread.join(timeout=10.0)
            if self._poll_thread.is_alive():
                logger.warning("ModbusSource: Poll thread did not exit in time")
            self._poll_thread = None

        self._disconnect()
        logger.info("ModbusSource: Stopped")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Create and connect the Modbus client."""
        with self._lock:
            try:
                self._client = self._create_client()
                if self._client.connect():
                    self._connected = True
                    self._reconnect_attempts = 0
                    self._error_count = 0
                    logger.info("ModbusSource: Connected")
                    return True
                else:
                    self._connected = False
                    self._last_error = "Connection refused"
                    logger.warning("ModbusSource: Connection refused")
                    return False
            except Exception as e:
                self._connected = False
                self._last_error = str(e)
                logger.error(f"ModbusSource: Connection error: {e}")
                return False

    def _create_client(self):
        """Create the appropriate pymodbus client based on config."""
        if self._config.connection_type.lower() == 'tcp':
            return ModbusTcpClient(
                host=self._config.ip_address,
                port=self._config.port,
                timeout=self._config.timeout,
            )
        else:
            parity_map = {
                'N': 'N', 'E': 'E', 'O': 'O',
                'NONE': 'N', 'EVEN': 'E', 'ODD': 'O',
            }
            parity = parity_map.get(self._config.parity.upper(), 'N')
            return ModbusSerialClient(
                port=self._config.serial_port,
                baudrate=self._config.baudrate,
                parity=parity,
                stopbits=self._config.stopbits,
                bytesize=self._config.bytesize,
                timeout=self._config.timeout,
            )

    def _disconnect(self) -> None:
        """Disconnect and clean up the Modbus client."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
            self._connected = False

    def _reconnect(self) -> bool:
        """Disconnect and reconnect with exponential backoff."""
        self._disconnect()

        delay = min(
            self._config.timeout * (2 ** self._reconnect_attempts),
            self._max_reconnect_delay,
        )
        logger.info(
            f"ModbusSource: Reconnecting in {delay:.1f}s "
            f"(attempt {self._reconnect_attempts + 1})"
        )

        # Wait with stop_event check so we can exit promptly
        if self._stop_event.wait(timeout=delay):
            return False

        self._reconnect_attempts += 1
        return self._connect()

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Main polling loop: read all registers, dispatch callback, sleep."""
        while not self._stop_event.is_set():
            if not self._connected:
                if not self._reconnect():
                    continue

            data = self._read_all_registers()
            if data is not None and len(data) > 0:
                # Add metadata
                data['_source'] = 'modbus'
                data['_timestamp'] = time.time()

                try:
                    self._on_new_data(data)
                except Exception as e:
                    logger.error(f"ModbusSource: Callback error: {e}")

            self._stop_event.wait(timeout=self._config.poll_interval_s)

    def _read_all_registers(self) -> Optional[Dict[str, Any]]:
        """Read all configured registers and return decoded values.

        Returns:
            Dict of {register_name: {value: float, unit: str}} or None on
            total failure.
        """
        if not self._connected or self._client is None:
            return None

        results: Dict[str, Any] = {}

        for reg_def in self._config.registers:
            name = reg_def.get('name', f"reg_{reg_def.get('address', '?')}")
            address = int(reg_def.get('address', 0))
            reg_type = reg_def.get('register_type', 'holding').lower()
            data_type = reg_def.get('data_type', 'uint16').lower()
            scale = float(reg_def.get('scale', 1.0))
            offset = float(reg_def.get('offset', 0.0))
            unit = reg_def.get('unit', '')

            try:
                raw_value = self._read_single_register(
                    address, reg_type, data_type,
                )
                if raw_value is not None:
                    scaled_value = raw_value * scale + offset
                    results[name] = {
                        'value': scaled_value,
                        'unit': unit,
                        'raw': raw_value,
                    }
                    self._last_successful_read = time.time()
                else:
                    results[name] = {
                        'value': None,
                        'unit': unit,
                        'error': self._last_error,
                    }
            except Exception as e:
                logger.error(f"ModbusSource: Error reading register '{name}': {e}")
                results[name] = {
                    'value': None,
                    'unit': unit,
                    'error': str(e),
                }

        return results

    def _read_single_register(
        self, address: int, reg_type: str, data_type: str,
    ) -> Optional[float]:
        """Read and decode a single register (or register group).

        Args:
            address: Modbus register address (0-based).
            reg_type: One of 'holding', 'input', 'coil', 'discrete'.
            data_type: One of 'int16', 'uint16', 'int32', 'uint32',
                       'float32', 'float64', 'bool'.

        Returns:
            Decoded numeric value, or None on read error.
        """
        count = _REGISTERS_PER_TYPE.get(data_type, 1)
        slave_id = self._config.slave_id

        with self._lock:
            if not self._connected or self._client is None:
                return None

            try:
                if reg_type in ('coil', 'discrete'):
                    return self._read_bit_register(address, reg_type, slave_id)

                # Read analog registers (holding or input)
                if reg_type == 'input':
                    result = self._client.read_input_registers(
                        address, count=count, slave=slave_id,
                    )
                else:
                    result = self._client.read_holding_registers(
                        address, count=count, slave=slave_id,
                    )

                if result.isError():
                    self._handle_read_error(result, address, reg_type)
                    return None

                registers = result.registers
                self._error_count = 0
                return _decode_registers(registers, data_type)

            except ConnectionException:
                self._connected = False
                self._last_error = f"Connection lost reading {reg_type}@{address}"
                logger.warning(f"ModbusSource: {self._last_error}")
                return None
            except Exception as e:
                self._error_count += 1
                self._last_error = f"Read error {reg_type}@{address}: {e}"
                logger.error(f"ModbusSource: {self._last_error}")
                return None

    def _read_bit_register(
        self, address: int, reg_type: str, slave_id: int,
    ) -> Optional[float]:
        """Read a coil or discrete input register."""
        try:
            if reg_type == 'coil':
                result = self._client.read_coils(
                    address, count=1, slave=slave_id,
                )
            else:
                result = self._client.read_discrete_inputs(
                    address, count=1, slave=slave_id,
                )

            if result.isError():
                self._handle_read_error(result, address, reg_type)
                return None

            self._error_count = 0
            return 1.0 if result.bits[0] else 0.0

        except Exception as e:
            self._error_count += 1
            self._last_error = f"Bit read error {reg_type}@{address}: {e}"
            logger.error(f"ModbusSource: {self._last_error}")
            return None

    def _handle_read_error(self, result, address: int, reg_type: str) -> None:
        """Log a Modbus read error with exception code details."""
        self._error_count += 1
        if isinstance(result, ExceptionResponse):
            code = result.exception_code
            self._last_error = (
                f"Modbus exception {code} reading {reg_type}@{address}"
            )
        else:
            self._last_error = f"Modbus error reading {reg_type}@{address}"
        logger.warning(f"ModbusSource: {self._last_error}")

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the poll loop is currently active."""
        if self._stop_event.is_set():
            return False
        return self._poll_thread is not None and self._poll_thread.is_alive()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for diagnostics / MQTT status publishing."""
        return {
            'running': self.is_running,
            'connected': self._connected,
            'connection_type': self._config.connection_type,
            'address': (
                f"{self._config.ip_address}:{self._config.port}"
                if self._config.connection_type == 'tcp'
                else self._config.serial_port
            ),
            'slave_id': self._config.slave_id,
            'register_count': len(self._config.registers),
            'error_count': self._error_count,
            'last_error': self._last_error,
            'last_successful_read': self._last_successful_read,
            'pymodbus_available': PYMODBUS_AVAILABLE,
        }


# ======================================================================
# Module-level decode utility
# ======================================================================

def _decode_registers(registers: List[int], data_type: str) -> float:
    """Decode raw 16-bit Modbus register values to a numeric value.

    Uses big-endian byte order and big-endian word order (most common
    for industrial instruments). Based on the decode logic in
    tools/modbus_tool/modbus_adapter.py.

    Args:
        registers: List of raw 16-bit register values.
        data_type: Target data type string (e.g. 'float32', 'int16').

    Returns:
        Decoded numeric value as float.
    """
    if data_type == 'bool':
        return 1.0 if registers[0] != 0 else 0.0

    fmt_char = _FORMAT_MAP.get(data_type)
    if fmt_char is None:
        # Unknown type, return raw first register
        return float(registers[0])

    # Build raw bytes from registers (big-endian)
    raw_bytes = b''.join(reg.to_bytes(2, byteorder='big') for reg in registers)

    # Decode with big-endian prefix
    return struct.unpack(f'>{fmt_char}', raw_bytes)[0]
