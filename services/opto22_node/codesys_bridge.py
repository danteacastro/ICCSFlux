"""
CODESYS Integration Bridge for Opto22 Node

Reads CODESYS variables from groov EPIC via Modbus TCP and maps them
to NISystem channels. This enables deterministic PID and other real-time
control logic to run in CODESYS while our Python node handles:
- Data integration with NISystem MQTT
- Script execution and safety evaluation
- Alarm management and audit trail

Connection methods (in priority order):
1. Modbus TCP (CODESYS exposes variables as Modbus registers)
2. OPC-UA (if CODESYS OPC-UA server is enabled)

Usage:
    bridge = CODESYSBridge(
        host='localhost',  # groov EPIC runs CODESYS locally
        tag_map={'PID1_PV': {'register': 40001, 'type': 'float32'},
                 'PID1_CV': {'register': 40003, 'type': 'float32'}}
    )
    bridge.start()
    values = bridge.get_values()  # {'PID1_PV': 72.3, 'PID1_CV': 45.1}
"""

import logging
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger('Opto22Node.CODESYS')

# Try to import pymodbus for Modbus TCP
try:
    from pymodbus.client import ModbusTcpClient
    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False


class CODESYSBridge:
    """
    Bridge between CODESYS runtime on groov EPIC and NISystem.

    Reads CODESYS-exposed Modbus registers and maps them to channel names
    that the Opto22 node publishes to MQTT.
    """

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 502,
                 unit_id: int = 1,
                 poll_rate_hz: float = 10.0,
                 tag_map: Optional[Dict[str, Dict[str, Any]]] = None,
                 on_values_updated: Optional[Callable[[Dict[str, float]], None]] = None):
        """
        Args:
            host: CODESYS Modbus TCP host (usually localhost on groov EPIC)
            port: Modbus TCP port (default 502)
            unit_id: Modbus unit/slave ID
            poll_rate_hz: How often to poll CODESYS registers
            tag_map: Mapping of channel names to Modbus register definitions
                     Example: {'Temp_PV': {'register': 40001, 'type': 'float32', 'scale': 1.0}}
            on_values_updated: Callback when new values are read
        """
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._poll_interval = 1.0 / poll_rate_hz
        self._tag_map = tag_map or {}
        self._on_values_updated = on_values_updated

        self._client: Optional[ModbusTcpClient] = None
        self._connected = False
        self._running = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Latest values
        self._values: Dict[str, float] = {}
        self._timestamps: Dict[str, float] = {}

        # Statistics
        self._read_count = 0
        self._error_count = 0
        self._last_read_time = 0.0

    def start(self):
        """Start the polling loop."""
        if not MODBUS_AVAILABLE:
            logger.error("pymodbus not available — install with: pip install pymodbus")
            return

        self._running.set()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="CODESYS-Poll", daemon=True
        )
        self._poll_thread.start()
        logger.info(f"CODESYS bridge started: {self._host}:{self._port} "
                     f"polling {len(self._tag_map)} tags at {1/self._poll_interval:.1f} Hz")

    def stop(self):
        """Stop the polling loop."""
        self._running.clear()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3.0)
        self._disconnect()
        logger.info("CODESYS bridge stopped")

    def get_values(self) -> Dict[str, float]:
        """Get latest CODESYS tag values."""
        with self._lock:
            return dict(self._values)

    def get_timestamps(self) -> Dict[str, float]:
        """Get timestamps of latest reads."""
        with self._lock:
            return dict(self._timestamps)

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': self._connected,
            'host': self._host,
            'port': self._port,
            'tags': len(self._tag_map),
            'read_count': self._read_count,
            'error_count': self._error_count,
            'last_read': self._last_read_time,
        }

    def load_config(self, config: Dict[str, Any]):
        """Load tag mapping from config."""
        self._host = config.get('host', self._host)
        self._port = config.get('port', self._port)
        self._unit_id = config.get('unit_id', self._unit_id)
        poll_rate = config.get('poll_rate_hz', 1.0 / self._poll_interval)
        self._poll_interval = 1.0 / max(0.1, poll_rate)
        self._tag_map = config.get('tag_map', self._tag_map)

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _connect(self) -> bool:
        """Connect to CODESYS Modbus TCP server."""
        if self._connected:
            return True
        try:
            self._client = ModbusTcpClient(self._host, port=self._port, timeout=3.0)
            if self._client.connect():
                self._connected = True
                logger.info(f"Connected to CODESYS at {self._host}:{self._port}")
                return True
            else:
                logger.warning(f"Failed to connect to CODESYS at {self._host}:{self._port}")
                return False
        except Exception as e:
            logger.warning(f"CODESYS connection error: {e}")
            return False

    def _disconnect(self):
        """Disconnect from CODESYS."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._connected = False
        self._client = None

    def _poll_loop(self):
        """Main polling loop — reads CODESYS registers periodically."""
        reconnect_delay = 2.0

        while self._running.is_set():
            loop_start = time.time()

            if not self._connected:
                if not self._connect():
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 1.5, 30.0)
                    continue
                reconnect_delay = 2.0

            try:
                values = self._read_all_tags()
                now = time.time()

                with self._lock:
                    self._values.update(values)
                    for name in values:
                        self._timestamps[name] = now

                self._read_count += 1
                self._last_read_time = now

                if self._on_values_updated and values:
                    try:
                        self._on_values_updated(values)
                    except Exception as e:
                        logger.debug(f"Values callback error: {e}")

            except Exception as e:
                self._error_count += 1
                logger.warning(f"CODESYS read error: {e}")
                self._disconnect()

            elapsed = time.time() - loop_start
            sleep_time = self._poll_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _read_all_tags(self) -> Dict[str, float]:
        """Read all configured tags from CODESYS."""
        values = {}
        if not self._client:
            return values

        for tag_name, tag_def in self._tag_map.items():
            try:
                value = self._read_tag(tag_def)
                if value is not None:
                    scale = tag_def.get('scale', 1.0)
                    offset = tag_def.get('offset', 0.0)
                    values[tag_name] = value * scale + offset
            except Exception as e:
                logger.debug(f"Failed to read tag {tag_name}: {e}")

        return values

    def _read_tag(self, tag_def: Dict[str, Any]) -> Optional[float]:
        """Read a single tag from CODESYS via Modbus."""
        register = tag_def.get('register', 0)
        data_type = tag_def.get('type', 'float32')

        # Convert Modbus address convention (40001 = holding register 0)
        if register >= 40001:
            address = register - 40001
        elif register >= 30001:
            address = register - 30001
        else:
            address = register

        if data_type == 'float32':
            result = self._client.read_holding_registers(
                address, count=2, slave=self._unit_id
            )
            if result.isError():
                return None
            # Combine two 16-bit registers into float32
            raw = struct.pack('>HH', result.registers[0], result.registers[1])
            return struct.unpack('>f', raw)[0]

        elif data_type == 'int16':
            result = self._client.read_holding_registers(
                address, count=1, slave=self._unit_id
            )
            if result.isError():
                return None
            val = result.registers[0]
            # Handle signed
            if val >= 0x8000:
                val -= 0x10000
            return float(val)

        elif data_type == 'uint16':
            result = self._client.read_holding_registers(
                address, count=1, slave=self._unit_id
            )
            if result.isError():
                return None
            return float(result.registers[0])

        elif data_type == 'int32':
            result = self._client.read_holding_registers(
                address, count=2, slave=self._unit_id
            )
            if result.isError():
                return None
            raw = struct.pack('>HH', result.registers[0], result.registers[1])
            return float(struct.unpack('>i', raw)[0])

        elif data_type == 'bool':
            result = self._client.read_coils(
                address, count=1, slave=self._unit_id
            )
            if result.isError():
                return None
            return 1.0 if result.bits[0] else 0.0

        else:
            logger.warning(f"Unknown data type: {data_type}")
            return None

    def write_tag(self, tag_name: str, value: float) -> bool:
        """Write a value to a CODESYS tag via Modbus."""
        if not self._connected or not self._client:
            return False

        tag_def = self._tag_map.get(tag_name)
        if not tag_def:
            logger.warning(f"Unknown tag: {tag_name}")
            return False

        if not tag_def.get('writable', False):
            logger.warning(f"Tag {tag_name} is not writable")
            return False

        register = tag_def.get('register', 0)
        data_type = tag_def.get('type', 'float32')

        # Reverse scale
        scale = tag_def.get('scale', 1.0)
        offset = tag_def.get('offset', 0.0)
        raw_value = (value - offset) / scale if scale != 0 else value

        if register >= 40001:
            address = register - 40001
        else:
            address = register

        try:
            if data_type == 'float32':
                raw = struct.pack('>f', raw_value)
                regs = struct.unpack('>HH', raw)
                self._client.write_registers(address, list(regs), slave=self._unit_id)
                return True
            elif data_type in ('int16', 'uint16'):
                self._client.write_register(address, int(raw_value), slave=self._unit_id)
                return True
            elif data_type == 'bool':
                self._client.write_coil(address, bool(raw_value > 0.5), slave=self._unit_id)
                return True
        except Exception as e:
            logger.error(f"Failed to write tag {tag_name}: {e}")
            return False

        return False
