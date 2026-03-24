"""
CODESYS Integration Bridge for Opto22 Node

Bridges the CODESYS runtime (deterministic PLC control) and the Python
companion process on the groov EPIC via Modbus TCP on localhost:502.

Two modes of operation:
1. **Structured mode** — Uses RegisterMap to provide typed access to PID
   setpoints, interlock commands, process values, and system status.
2. **Tag map mode** — Legacy freeform tag_map dict for custom Modbus tags.

The bridge provides:
- Periodic polling of CODESYS registers (configurable rate)
- Structured read/write methods for PID, interlocks, and system commands
- Health monitoring (connection status, scan time, error rate)
- Heartbeat to CODESYS (so the PLC watchdog can detect Python failure)
- Graceful fallback: `codesys_available` property for scan loop branching

Usage (structured):
    from .codesys.register_map import RegisterMap
    rmap = RegisterMap()
    rmap.allocate_pid_loops(['Zone1_PID'])
    bridge = CODESYSBridge(register_map=rmap)
    bridge.start()
    bridge.write_pid_setpoint('Zone1_PID', 72.0)
    values = bridge.read_process_values()

Usage (tag map):
    bridge = CODESYSBridge(
        tag_map={'PID1_PV': {'register': 40001, 'type': 'float32'}}
    )
    bridge.start()
    values = bridge.get_values()
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

# Import register map (optional — structured mode only)
try:
    from .codesys.register_map import RegisterMap, HOLD_SYSTEM_CMD_BASE, SYSCMD_HEARTBEAT
    REGISTER_MAP_AVAILABLE = True
except ImportError:
    REGISTER_MAP_AVAILABLE = False

class CODESYSBridge:
    """
    Bridge between CODESYS runtime on groov EPIC and NISystem.

    Reads CODESYS-exposed Modbus registers and maps them to channel names
    that the Opto22 node publishes to MQTT. Supports both structured
    (RegisterMap) and freeform (tag_map) modes.
    """

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 502,
                 unit_id: int = 1,
                 poll_rate_hz: float = 10.0,
                 tag_map: Optional[Dict[str, Dict[str, Any]]] = None,
                 register_map: Optional['RegisterMap'] = None,
                 on_values_updated: Optional[Callable[[Dict[str, float]], None]] = None):
        """
        Args:
            host: CODESYS Modbus TCP host (usually localhost on groov EPIC)
            port: Modbus TCP port (default 502)
            unit_id: Modbus unit/slave ID
            poll_rate_hz: How often to poll CODESYS registers
            tag_map: Mapping of channel names to Modbus register definitions
                     Example: {'Temp_PV': {'register': 40001, 'type': 'float32', 'scale': 1.0}}
            register_map: Structured RegisterMap for typed PID/interlock/channel access
            on_values_updated: Callback when new values are read
        """
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._poll_interval = 1.0 / poll_rate_hz
        self._on_values_updated = on_values_updated

        # Register map (structured mode)
        self._register_map = register_map

        # Tag map: merge explicit tags with register-map-generated tags
        self._tag_map = tag_map or {}
        if self._register_map:
            generated = self._register_map.generate_tag_map()
            # Explicit tags take precedence
            merged = dict(generated)
            merged.update(self._tag_map)
            self._tag_map = merged

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
        self._consecutive_errors = 0
        self._last_scan_time_us = 0
        self._heartbeat_counter = 0

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

    @property
    def codesys_available(self) -> bool:
        """True if CODESYS is connected and responding within tolerance.

        Used by opto22_node.py scan loop to decide between CODESYS mode
        (delegate PID/interlocks to PLC) and Python fallback mode.
        """
        if not self._connected:
            return False
        # Check if we've had a successful read recently (within 5 seconds)
        if self._last_read_time == 0:
            return False
        if time.time() - self._last_read_time > 5.0:
            return False
        # Check consecutive error count (3+ errors = unhealthy)
        if self._consecutive_errors >= 3:
            return False
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': self._connected,
            'codesys_available': self.codesys_available,
            'host': self._host,
            'port': self._port,
            'tags': len(self._tag_map),
            'read_count': self._read_count,
            'error_count': self._error_count,
            'consecutive_errors': self._consecutive_errors,
            'last_read': self._last_read_time,
            'last_scan_time_us': self._last_scan_time_us,
            'heartbeat': self._heartbeat_counter,
        }

    def get_health(self) -> Dict[str, Any]:
        """Get health summary for status publishing."""
        now = time.time()
        return {
            'connected': self._connected,
            'available': self.codesys_available,
            'last_read_age_s': round(now - self._last_read_time, 2) if self._last_read_time else -1,
            'scan_time_us': self._last_scan_time_us,
            'error_rate': round(self._error_count / max(1, self._read_count), 4),
            'consecutive_errors': self._consecutive_errors,
        }

    def load_config(self, config: Dict[str, Any]):
        """Load tag mapping from config."""
        self._host = config.get('host', self._host)
        self._port = config.get('port', self._port)
        self._unit_id = config.get('unit_id', self._unit_id)
        poll_rate = config.get('poll_rate_hz', 1.0 / self._poll_interval)
        self._poll_interval = 1.0 / max(0.1, poll_rate)
        self._tag_map = config.get('tag_map', self._tag_map)

        # If register map provided in config, rebuild tag map
        rmap_data = config.get('register_map')
        if rmap_data and REGISTER_MAP_AVAILABLE:
            self._register_map = RegisterMap.from_dict(rmap_data)
            generated = self._register_map.generate_tag_map()
            merged = dict(generated)
            merged.update(self._tag_map)
            self._tag_map = merged

    # =========================================================================
    # STRUCTURED ACCESS (requires RegisterMap)
    # =========================================================================

    def write_pid_setpoint(self, loop_id: str, value: float) -> bool:
        """Write a PID setpoint to CODESYS."""
        return self.write_tag(f'{loop_id}_SP', value)

    def write_pid_tuning(self, loop_id: str, kp: float, ki: float, kd: float) -> bool:
        """Write PID tuning parameters to CODESYS."""
        ok = True
        ok = self.write_tag(f'{loop_id}_Kp', kp) and ok
        ok = self.write_tag(f'{loop_id}_Ki', ki) and ok
        ok = self.write_tag(f'{loop_id}_Kd', kd) and ok
        return ok

    def write_interlock_command(self, ilk_id: str, arm: bool = False,
                                bypass: bool = False, reset: bool = False) -> bool:
        """Write interlock commands to CODESYS via coils."""
        if not self._connected or not self._client or not self._register_map:
            return False
        regs = self._register_map.get_interlock_registers(ilk_id)
        if not regs:
            return False
        try:
            self._client.write_coil(regs.arm_coil - 1, arm, slave=self._unit_id)
            self._client.write_coil(regs.bypass_coil - 1, bypass, slave=self._unit_id)
            return True
        except Exception as e:
            logger.error(f"Failed to write interlock command {ilk_id}: {e}")
            return False

    def write_system_command(self, cmd: str, value: int) -> bool:
        """Write a system command register."""
        tag_name = f'SYS_{cmd.upper()}'
        if tag_name not in self._tag_map:
            logger.warning(f"Unknown system command: {cmd}")
            return False
        return self.write_tag(tag_name, float(value))

    def write_heartbeat(self) -> bool:
        """Increment and write the Python heartbeat counter to CODESYS.

        CODESYS watches this counter — if it stops incrementing for 5 seconds,
        the PLC applies safe state (Python companion lost).
        """
        self._heartbeat_counter = (self._heartbeat_counter + 1) % 65535
        return self.write_tag('SYS_HEARTBEAT', float(self._heartbeat_counter))

    def read_pid_outputs(self) -> Dict[str, float]:
        """Read all PID control variable outputs from CODESYS."""
        if not self._register_map:
            return {}
        results = {}
        for loop_id in self._register_map.pid_loops:
            cv = self._values.get(f'{loop_id}_CV')
            if cv is not None:
                results[loop_id] = cv
        return results

    def read_process_values(self) -> Dict[str, float]:
        """Read all channel process values from CODESYS."""
        if not self._register_map:
            return {}
        results = {}
        for name in self._register_map.channels:
            pv = self._values.get(f'{name}_PV')
            if pv is not None:
                results[name] = pv
        return results

    def read_interlock_status(self) -> Dict[str, Dict[str, Any]]:
        """Read interlock status from CODESYS.

        Returns dict: {ilk_id: {'state': int, 'trips': int, 'tripped': bool}}
        """
        if not self._register_map:
            return {}
        results = {}
        for ilk_id in self._register_map.interlocks:
            state = self._values.get(f'{ilk_id}_STATE')
            trips = self._values.get(f'{ilk_id}_TRIPS')
            if state is not None:
                results[ilk_id] = {
                    'state': int(state),
                    'trips': int(trips) if trips is not None else 0,
                    'tripped': int(state) == 2,
                }
        return results

    def read_system_status(self) -> Dict[str, Any]:
        """Read CODESYS system diagnostics."""
        scan_time = self._values.get('SYS_SCAN_TIME')
        errors = self._values.get('SYS_ERRORS')
        watchdog = self._values.get('SYS_WATCHDOG')
        if scan_time is not None:
            self._last_scan_time_us = int(scan_time)
        return {
            'scan_time_us': int(scan_time) if scan_time is not None else -1,
            'error_count': int(errors) if errors is not None else -1,
            'watchdog': int(watchdog) if watchdog is not None else -1,
        }

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
                self._consecutive_errors = 0

                if self._on_values_updated and values:
                    try:
                        self._on_values_updated(values)
                    except Exception as e:
                        logger.debug(f"Values callback error: {e}")

            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
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
        """Read a single tag from CODESYS via Modbus.

        Automatically selects holding vs input registers based on Modbus
        address convention (4xxxx = holding, 3xxxx = input).
        """
        register = tag_def.get('register', 0)
        data_type = tag_def.get('type', 'float32')

        # Determine register type and compute zero-based address
        use_input_registers = 30001 <= register < 40001
        if register >= 40001:
            address = register - 40001
        elif register >= 30001:
            address = register - 30001
        else:
            address = register

        def _read_regs(addr: int, count: int):
            if use_input_registers:
                return self._client.read_input_registers(addr, count=count, slave=self._unit_id)
            return self._client.read_holding_registers(addr, count=count, slave=self._unit_id)

        if data_type == 'float32':
            result = _read_regs(address, 2)
            if result.isError():
                return None
            raw = struct.pack('>HH', result.registers[0], result.registers[1])
            return struct.unpack('>f', raw)[0]

        elif data_type == 'int16':
            result = _read_regs(address, 1)
            if result.isError():
                return None
            val = result.registers[0]
            if val >= 0x8000:
                val -= 0x10000
            return float(val)

        elif data_type == 'uint16':
            result = _read_regs(address, 1)
            if result.isError():
                return None
            return float(result.registers[0])

        elif data_type == 'int32':
            result = _read_regs(address, 2)
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
