#!/usr/bin/env python3
"""
NISystem cFP Node Service

Node service for NI CompactFieldPoint (cFP-20xx) systems.
Communicates with cFP via Modbus TCP and bridges to MQTT for the DAQ service.

CompactFieldPoint is an older NI platform with:
- cFP-20xx backplanes (cFP-2010, cFP-2020, etc.)
- Various I/O modules (cFP-AI-100, cFP-AO-200, cFP-DI-300, etc.)
- Modbus TCP communication (port 502)

Usage:
    python cfp_node.py --host 192.168.1.30 --broker 192.168.1.100 --node-id cfp-001
"""

import argparse
import json
import logging
import os
import signal
import struct
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt not installed")
    print("Run: pip install paho-mqtt")
    sys.exit(1)

# Optional: pymodbus for advanced Modbus features
try:
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('cfp_node')


@dataclass
class ModbusChannel:
    """Configuration for a Modbus channel"""
    name: str
    address: int
    register_type: str = 'holding'  # holding, input, coil, discrete
    data_type: str = 'int16'  # int16, uint16, int32, uint32, float32
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ''
    writable: bool = False


@dataclass
class CFPModuleConfig:
    """Configuration for a cFP module"""
    slot: int
    module_type: str  # e.g., 'cFP-AI-110', 'cFP-AO-210', 'cFP-DI-330'
    base_address: int
    channels: List[ModbusChannel] = field(default_factory=list)


@dataclass
class CFPConfig:
    """Configuration for cFP node"""
    node_id: str = 'cfp-001'
    cfp_host: str = '192.168.1.30'
    cfp_port: int = 502
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_base_topic: str = 'nisystem'
    poll_interval: float = 1.0
    modules: List[CFPModuleConfig] = field(default_factory=list)
    timeout: float = 5.0
    retry_count: int = 3
    retry_delay: float = 1.0


class ModbusTCPClient:
    """Simple Modbus TCP client for cFP communication"""

    def __init__(self, host: str, port: int = 502, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None
        self.transaction_id = 0
        self.lock = threading.Lock()

    def connect(self) -> bool:
        """Connect to cFP Modbus interface"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            logger.info(f"Connected to cFP at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to cFP: {e}")
            return False

    def disconnect(self):
        """Disconnect from cFP"""
        if self.socket:
            try:
                self.socket.close()
            except OSError as e:
                logger.warning(f"Error closing cFP socket: {e}")
            self.socket = None

    def is_connected(self) -> bool:
        """Check if connected"""
        return self.socket is not None

    def _send_request(self, unit_id: int, function_code: int, data: bytes) -> Optional[bytes]:
        """Send Modbus request and receive response"""
        if not self.socket:
            return None

        with self.lock:
            self.transaction_id = (self.transaction_id + 1) % 65536

            # Build MBAP header
            # Transaction ID (2) + Protocol ID (2) + Length (2) + Unit ID (1)
            length = len(data) + 2  # data + unit_id + function_code
            header = struct.pack('>HHHB', self.transaction_id, 0, length, unit_id)
            request = header + struct.pack('B', function_code) + data

            try:
                self.socket.send(request)

                # Receive response header
                response_header = self.socket.recv(7)
                if len(response_header) < 7:
                    return None

                _, _, resp_length, _ = struct.unpack('>HHHB', response_header)

                # Receive response data
                response_data = self.socket.recv(resp_length - 1)
                return response_data

            except socket.timeout:
                logger.warning("Modbus request timed out")
                return None
            except Exception as e:
                logger.error(f"Modbus communication error: {e}")
                return None

    def read_holding_registers(self, address: int, count: int, unit_id: int = 1) -> Optional[List[int]]:
        """Read holding registers (function code 3)"""
        data = struct.pack('>HH', address, count)
        response = self._send_request(unit_id, 3, data)

        if response and len(response) >= 2:
            func_code = response[0]
            if func_code == 3:
                byte_count = response[1]
                values = []
                for i in range(2, 2 + byte_count, 2):
                    if i + 1 < len(response):
                        values.append(struct.unpack('>H', response[i:i+2])[0])
                return values
            elif func_code & 0x80:  # Error response
                error_code = response[1] if len(response) > 1 else 0
                logger.error(f"Modbus error: function={func_code & 0x7F}, error={error_code}")

        return None

    def read_input_registers(self, address: int, count: int, unit_id: int = 1) -> Optional[List[int]]:
        """Read input registers (function code 4)"""
        data = struct.pack('>HH', address, count)
        response = self._send_request(unit_id, 4, data)

        if response and len(response) >= 2:
            func_code = response[0]
            if func_code == 4:
                byte_count = response[1]
                values = []
                for i in range(2, 2 + byte_count, 2):
                    if i + 1 < len(response):
                        values.append(struct.unpack('>H', response[i:i+2])[0])
                return values

        return None

    def read_coils(self, address: int, count: int, unit_id: int = 1) -> Optional[List[bool]]:
        """Read coils (function code 1)"""
        data = struct.pack('>HH', address, count)
        response = self._send_request(unit_id, 1, data)

        if response and len(response) >= 2:
            func_code = response[0]
            if func_code == 1:
                byte_count = response[1]
                values = []
                for i in range(2, 2 + byte_count):
                    if i < len(response):
                        for bit in range(8):
                            if len(values) < count:
                                values.append(bool(response[i] & (1 << bit)))
                return values

        return None

    def read_discrete_inputs(self, address: int, count: int, unit_id: int = 1) -> Optional[List[bool]]:
        """Read discrete inputs (function code 2)"""
        data = struct.pack('>HH', address, count)
        response = self._send_request(unit_id, 2, data)

        if response and len(response) >= 2:
            func_code = response[0]
            if func_code == 2:
                byte_count = response[1]
                values = []
                for i in range(2, 2 + byte_count):
                    if i < len(response):
                        for bit in range(8):
                            if len(values) < count:
                                values.append(bool(response[i] & (1 << bit)))
                return values

        return None

    def write_single_register(self, address: int, value: int, unit_id: int = 1) -> bool:
        """Write single holding register (function code 6)"""
        data = struct.pack('>HH', address, value & 0xFFFF)
        response = self._send_request(unit_id, 6, data)

        if response and len(response) >= 1:
            return response[0] == 6

        return False

    def write_single_coil(self, address: int, value: bool, unit_id: int = 1) -> bool:
        """Write single coil (function code 5)"""
        coil_value = 0xFF00 if value else 0x0000
        data = struct.pack('>HH', address, coil_value)
        response = self._send_request(unit_id, 5, data)

        if response and len(response) >= 1:
            return response[0] == 5

        return False

    def write_multiple_registers(self, address: int, values: List[int], unit_id: int = 1) -> bool:
        """Write multiple holding registers (function code 16)"""
        count = len(values)
        byte_count = count * 2
        data = struct.pack('>HHB', address, count, byte_count)
        for v in values:
            data += struct.pack('>H', v & 0xFFFF)

        response = self._send_request(unit_id, 16, data)

        if response and len(response) >= 1:
            return response[0] == 16

        return False


class CFPNode:
    """cFP Node service - bridges cFP Modbus to MQTT"""

    def __init__(self, config: CFPConfig):
        self.config = config
        self.running = False

        # Modbus client
        self.modbus: Optional[ModbusTCPClient] = None

        # MQTT client
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_connected = False

        # Data storage
        self.channel_values: Dict[str, Any] = {}
        self.channel_qualities: Dict[str, str] = {}  # Channel quality status
        self.last_publish: Dict[str, float] = {}

        # Session state (for API compatibility with DAQ Service/cRIO)
        self.acquiring = False
        self.recording = False
        self.session_active = False
        self.session_id: Optional[str] = None

        # Threading
        self.poll_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def start(self):
        """Start the cFP node service"""
        logger.info(f"Starting cFP node: {self.config.node_id}")

        # Connect to cFP via Modbus
        self.modbus = ModbusTCPClient(
            self.config.cfp_host,
            self.config.cfp_port,
            self.config.timeout
        )

        if not self.modbus.connect():
            logger.error("Failed to connect to cFP")
            return False

        # Connect to MQTT
        if not self._connect_mqtt():
            logger.error("Failed to connect to MQTT broker")
            return False

        # Start polling
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        # Publish initial status
        self._publish_status()

        logger.info(f"cFP node {self.config.node_id} started")
        return True

    def stop(self):
        """Stop the cFP node service"""
        logger.info("Stopping cFP node...")
        self.running = False

        if self.poll_thread:
            self.poll_thread.join(timeout=5.0)

        if self.modbus:
            self.modbus.disconnect()

        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        logger.info("cFP node stopped")

    def _connect_mqtt(self) -> bool:
        """Connect to MQTT broker"""
        try:
            self.mqtt_client = mqtt.Client(client_id=f"cfp-{self.config.node_id}")
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message

            # Set last will
            will_topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/status/system"
            will_payload = json.dumps({
                'online': False,
                'node_id': self.config.node_id,
                'timestamp': datetime.now().isoformat()
            })
            self.mqtt_client.will_set(will_topic, will_payload, qos=1, retain=True)

            self.mqtt_client.connect(self.config.mqtt_broker, self.config.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()

            # Wait for connection
            for _ in range(50):
                if self.mqtt_connected:
                    return True
                time.sleep(0.1)

            return False

        except Exception as e:
            logger.error(f"MQTT connection error: {e}")
            return False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connect callback"""
        if rc == 0:
            self.mqtt_connected = True
            logger.info(f"Connected to MQTT broker at {self.config.mqtt_broker}")

            # Subscribe to command topics
            base = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}"
            topics = [
                (f"{base}/commands/#", 1),
                (f"{base}/channel/read", 1),
                (f"{base}/channel/write", 1),
                (f"{base}/config/get", 1),
                (f"{base}/config/save", 1),
                (f"{base}/config/load", 1),
                (f"{self.config.mqtt_base_topic}/discovery/ping", 1),
            ]
            for topic, qos in topics:
                client.subscribe(topic, qos)
        else:
            logger.error(f"MQTT connection failed: {rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        self.mqtt_connected = False
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly: {rc}")

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            base = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}"

            if topic == f"{self.config.mqtt_base_topic}/discovery/ping":
                self._handle_discovery()
            elif topic == f"{base}/channel/read":
                self._handle_channel_read(payload)
            elif topic == f"{base}/channel/write":
                self._handle_channel_write(payload)
            elif topic == f"{base}/config/get":
                self._handle_config_get()
            elif topic == f"{base}/config/save":
                self._handle_config_save(payload)
            elif topic == f"{base}/config/load":
                self._handle_config_load(payload)
            elif topic.startswith(f"{base}/commands/"):
                command = topic.split('/')[-1]
                self._handle_command(command, payload)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_discovery(self):
        """Handle discovery ping"""
        self._publish(f"{self.config.mqtt_base_topic}/discovery/response", {
            'node_id': self.config.node_id,
            'node_type': 'cfp',
            'online': True,
            'host': self.config.cfp_host,
            'modules': len(self.config.modules)
        })

    def _handle_channel_read(self, payload: Dict):
        """Handle channel read request"""
        channel_name = payload.get('channel', '')
        request_id = payload.get('request_id', '')

        with self.lock:
            if channel_name in self.channel_values:
                value = self.channel_values[channel_name]
                self._publish(f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channel/response", {
                    'success': True,
                    'channel': channel_name,
                    'value': value,
                    'request_id': request_id
                })
            else:
                self._publish(f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channel/response", {
                    'success': False,
                    'error': f"Channel '{channel_name}' not found",
                    'request_id': request_id
                })

    def _handle_channel_write(self, payload: Dict):
        """Handle channel write request"""
        channel_name = payload.get('channel', '')
        value = payload.get('value')
        request_id = payload.get('request_id', '')

        # Find channel configuration
        channel_config = None
        for module in self.config.modules:
            for ch in module.channels:
                if ch.name == channel_name:
                    channel_config = ch
                    break
            if channel_config:
                break

        if not channel_config:
            self._publish(f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channel/response", {
                'success': False,
                'error': f"Channel '{channel_name}' not found",
                'request_id': request_id
            })
            return

        if not channel_config.writable:
            self._publish(f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channel/response", {
                'success': False,
                'error': f"Channel '{channel_name}' is not writable",
                'request_id': request_id
            })
            return

        # Write via Modbus
        success = False
        try:
            # Apply reverse scaling
            raw_value = (value - channel_config.offset) / channel_config.scale

            if channel_config.register_type == 'coil':
                success = self.modbus.write_single_coil(channel_config.address, bool(value))
            elif channel_config.register_type == 'holding':
                success = self.modbus.write_single_register(channel_config.address, int(raw_value))

        except Exception as e:
            logger.error(f"Write error: {e}")

        self._publish(f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channel/response", {
            'success': success,
            'channel': channel_name,
            'value': value,
            'request_id': request_id
        })

    def _handle_command(self, command: str, payload: Dict):
        """Handle command messages"""
        request_id = payload.get('request_id', '')
        base = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}"

        if command == 'ping':
            self._publish(f"{base}/command/response", {
                'success': True,
                'command': 'ping',
                'request_id': request_id
            })

        elif command == 'info':
            self._publish(f"{base}/command/response", {
                'success': True,
                'info': {
                    'node_id': self.config.node_id,
                    'type': 'CompactFieldPoint',
                    'host': self.config.cfp_host,
                    'modules': len(self.config.modules),
                    'channels': sum(len(m.channels) for m in self.config.modules)
                },
                'request_id': request_id
            })

        elif command == 'modules':
            modules = []
            for m in self.config.modules:
                modules.append({
                    'slot': m.slot,
                    'type': m.module_type,
                    'channels': len(m.channels)
                })
            self._publish(f"{base}/command/response", {
                'success': True,
                'modules': modules,
                'request_id': request_id
            })

        elif command == 'modbus_read':
            address = payload.get('address', 0)
            count = payload.get('count', 1)
            values = self.modbus.read_holding_registers(address, count)
            self._publish(f"{base}/command/response", {
                'success': values is not None,
                'values': values or [],
                'request_id': request_id
            })

        elif command == 'modbus_write':
            address = payload.get('address', 0)
            value = payload.get('value', 0)
            success = self.modbus.write_single_register(address, value)
            self._publish(f"{base}/command/response", {
                'success': success,
                'request_id': request_id
            })

    def _handle_config_get(self):
        """Handle config get request - return current configuration"""
        config_data = {
            'node_id': self.config.node_id,
            'cfp_host': self.config.cfp_host,
            'cfp_port': self.config.cfp_port,
            'mqtt_broker': self.config.mqtt_broker,
            'mqtt_port': self.config.mqtt_port,
            'poll_interval': self.config.poll_interval,
            'modules': []
        }

        for module in self.config.modules:
            mod_data = {
                'slot': module.slot,
                'module_type': module.module_type,
                'base_address': module.base_address,
                'channels': []
            }
            for ch in module.channels:
                mod_data['channels'].append({
                    'name': ch.name,
                    'address': ch.address,
                    'register_type': ch.register_type,
                    'data_type': ch.data_type,
                    'scale': ch.scale,
                    'offset': ch.offset,
                    'unit': ch.unit,
                    'writable': ch.writable
                })
            config_data['modules'].append(mod_data)

        self._publish_config_response('get', True, data=config_data)

    def _handle_config_save(self, payload: Dict):
        """Handle config save request"""
        filename = payload.get('filename', 'cfp_config.json') if isinstance(payload, dict) else 'cfp_config.json'

        try:
            config_path = Path(__file__).parent / filename

            config_data = {
                'node_id': self.config.node_id,
                'cfp_host': self.config.cfp_host,
                'cfp_port': self.config.cfp_port,
                'mqtt_broker': self.config.mqtt_broker,
                'mqtt_port': self.config.mqtt_port,
                'mqtt_base_topic': self.config.mqtt_base_topic,
                'poll_interval': self.config.poll_interval,
                'modules': []
            }

            for module in self.config.modules:
                mod_data = {
                    'slot': module.slot,
                    'module_type': module.module_type,
                    'base_address': module.base_address,
                    'channels': []
                }
                for ch in module.channels:
                    mod_data['channels'].append({
                        'name': ch.name,
                        'address': ch.address,
                        'register_type': ch.register_type,
                        'data_type': ch.data_type,
                        'scale': ch.scale,
                        'offset': ch.offset,
                        'unit': ch.unit,
                        'writable': ch.writable
                    })
                config_data['modules'].append(mod_data)

            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)

            logger.info(f"Configuration saved to {config_path}")
            self._publish_config_response('save', True, data={'filename': filename})

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            self._publish_config_response('save', False, error=str(e))

    def _handle_config_load(self, payload: Dict):
        """Handle config load request"""
        filename = payload.get('filename', 'cfp_config.json') if isinstance(payload, dict) else 'cfp_config.json'

        try:
            config_path = Path(__file__).parent / filename

            if not config_path.exists():
                self._publish_config_response('load', False, error=f"File not found: {filename}")
                return

            # Load and apply new configuration
            new_config = load_config(config_path)
            self.config = new_config

            logger.info(f"Configuration loaded from {config_path}")
            self._publish_config_response('load', True, data={'filename': filename})

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._publish_config_response('load', False, error=str(e))

    def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                # Check Modbus connection
                if not self.modbus.is_connected():
                    logger.warning("Modbus disconnected, reconnecting...")
                    if not self.modbus.connect():
                        time.sleep(self.config.retry_delay)
                        continue

                # Poll all modules
                all_values = {}
                for module in self.config.modules:
                    values = self._poll_module(module)
                    all_values.update(values)

                # Update stored values
                with self.lock:
                    self.channel_values.update(all_values)

                # Publish batch update
                if all_values:
                    self._publish_channels(all_values)

                # Publish session status (unified API)
                self._publish_session_status()

                # Publish heartbeat
                self._publish_heartbeat()

            except Exception as e:
                logger.error(f"Poll error: {e}")

            time.sleep(self.config.poll_interval)

    def _poll_module(self, module: CFPModuleConfig) -> Dict[str, Any]:
        """Poll a single cFP module"""
        values = {}

        for channel in module.channels:
            try:
                raw_value = None

                if channel.register_type == 'holding':
                    result = self.modbus.read_holding_registers(channel.address, 1)
                    if result:
                        raw_value = result[0]

                elif channel.register_type == 'input':
                    result = self.modbus.read_input_registers(channel.address, 1)
                    if result:
                        raw_value = result[0]

                elif channel.register_type == 'coil':
                    result = self.modbus.read_coils(channel.address, 1)
                    if result:
                        raw_value = result[0]

                elif channel.register_type == 'discrete':
                    result = self.modbus.read_discrete_inputs(channel.address, 1)
                    if result:
                        raw_value = result[0]

                if raw_value is not None:
                    # Handle data type conversion
                    if channel.data_type == 'int16':
                        if raw_value > 32767:
                            raw_value = raw_value - 65536
                    elif channel.data_type == 'float32':
                        # Would need to read 2 registers for float32
                        pass

                    # Apply scaling
                    scaled_value = raw_value * channel.scale + channel.offset
                    values[channel.name] = scaled_value

            except Exception as e:
                logger.debug(f"Error reading {channel.name}: {e}")

        return values

    def _publish_channels(self, values: Dict[str, Any]):
        """
        Publish channel values in batch format.

        Uses unified API format matching DAQ Service and cRIO:
        {channel_name: {value, timestamp, acquisition_ts_us, units, quality, status}, ...}
        """
        topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/channels/batch"
        timestamp = datetime.now().isoformat()
        acquisition_ts_us = int(time.time() * 1_000_000)

        # Build batch payload in unified format
        batch_payload = {}
        for channel_name, value in values.items():
            # Find channel config for units
            channel_config = self._find_channel_config(channel_name)
            units = channel_config.unit if channel_config else ''

            # Get quality (default to 'good' for connected values)
            quality = self.channel_qualities.get(channel_name, 'good')
            status = 'normal'

            # Check for bad values
            if value is None:
                quality = 'bad'
                status = 'disconnected'

            batch_payload[channel_name] = {
                'value': value,
                'timestamp': timestamp,
                'acquisition_ts_us': acquisition_ts_us,
                'units': units,
                'quality': quality,
                'status': status
            }

        self._publish(topic, batch_payload)

    def _find_channel_config(self, channel_name: str) -> Optional[ModbusChannel]:
        """Find channel configuration by name"""
        for module in self.config.modules:
            for ch in module.channels:
                if ch.name == channel_name:
                    return ch
        return None

    def _publish_session_status(self):
        """
        Publish session/acquisition status.

        Uses unified API format matching DAQ Service and cRIO for frontend compatibility.
        """
        topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/session/status"
        self._publish(topic, {
            'acquiring': self.acquiring,
            'recording': self.recording,
            'session_active': self.session_active,
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat()
        })

    def _publish_config_response(self, request_type: str, success: bool,
                                   data: Optional[Dict] = None, error: Optional[str] = None):
        """
        Publish config operation response.

        Uses unified API format matching DAQ Service and cRIO for frontend compatibility.
        """
        topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/config/response"
        payload = {
            'request_type': request_type,
            'success': success,
            'timestamp': datetime.now().isoformat()
        }
        if data:
            payload['data'] = data
        if error:
            payload['error'] = error

        if self.mqtt_client and self.mqtt_connected:
            self.mqtt_client.publish(topic, json.dumps(payload), qos=1)

    def _publish_heartbeat(self):
        """Publish heartbeat"""
        topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/heartbeat"
        self._publish(topic, {
            'node_id': self.config.node_id,
            'timestamp': datetime.now().isoformat(),
            'uptime': time.time()  # Would track actual uptime
        })

    def _publish_status(self):
        """Publish node status"""
        topic = f"{self.config.mqtt_base_topic}/nodes/{self.config.node_id}/status/system"
        self._publish(topic, {
            'online': True,
            'node_id': self.config.node_id,
            'node_type': 'cfp',
            'host': self.config.cfp_host,
            'modules': len(self.config.modules),
            'timestamp': datetime.now().isoformat()
        }, retain=True)

    def _publish(self, topic: str, payload: Dict, retain: bool = False):
        """Publish MQTT message"""
        if self.mqtt_client and self.mqtt_connected:
            self.mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=retain)


def load_config(config_path: Path) -> CFPConfig:
    """Load configuration from JSON file"""
    config = CFPConfig()

    if config_path.exists():
        try:
            with open(config_path) as f:
                data = json.load(f)

            config.node_id = data.get('node_id', config.node_id)
            config.cfp_host = data.get('cfp_host', config.cfp_host)
            config.cfp_port = data.get('cfp_port', config.cfp_port)
            config.mqtt_broker = data.get('mqtt_broker', config.mqtt_broker)
            config.mqtt_port = data.get('mqtt_port', config.mqtt_port)
            config.mqtt_base_topic = data.get('mqtt_base_topic', config.mqtt_base_topic)
            config.poll_interval = data.get('poll_interval', config.poll_interval)

            # Load modules
            for mod_data in data.get('modules', []):
                channels = []
                for ch_data in mod_data.get('channels', []):
                    channels.append(ModbusChannel(
                        name=ch_data['name'],
                        address=ch_data['address'],
                        register_type=ch_data.get('register_type', 'holding'),
                        data_type=ch_data.get('data_type', 'int16'),
                        scale=ch_data.get('scale', 1.0),
                        offset=ch_data.get('offset', 0.0),
                        unit=ch_data.get('unit', ''),
                        writable=ch_data.get('writable', False)
                    ))

                config.modules.append(CFPModuleConfig(
                    slot=mod_data.get('slot', 0),
                    module_type=mod_data.get('module_type', 'Unknown'),
                    base_address=mod_data.get('base_address', 0),
                    channels=channels
                ))

            logger.info(f"Loaded configuration from {config_path}")

        except Exception as e:
            logger.error(f"Error loading config: {e}")

    return config


def main():
    parser = argparse.ArgumentParser(
        description='NISystem cFP Node Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 192.168.1.30 --broker 192.168.1.100
  %(prog)s -c /path/to/cfp_config.json
  %(prog)s --node-id cfp-plant1 --host 10.0.0.50
        """
    )

    parser.add_argument('-c', '--config', help='Path to configuration file')
    parser.add_argument('--host', help='cFP IP address')
    parser.add_argument('--port', type=int, default=502, help='cFP Modbus port (default: 502)')
    parser.add_argument('--broker', help='MQTT broker address')
    parser.add_argument('--mqtt-port', type=int, default=1883, help='MQTT port (default: 1883)')
    parser.add_argument('--node-id', help='Node ID for this cFP')
    parser.add_argument('--poll-interval', type=float, default=1.0, help='Poll interval in seconds')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration
    config_path = Path(args.config) if args.config else Path(__file__).parent / 'cfp_config.json'
    config = load_config(config_path)

    # Override with command-line arguments
    if args.host:
        config.cfp_host = args.host
    if args.port:
        config.cfp_port = args.port
    if args.broker:
        config.mqtt_broker = args.broker
    if args.mqtt_port:
        config.mqtt_port = args.mqtt_port
    if args.node_id:
        config.node_id = args.node_id
    if args.poll_interval:
        config.poll_interval = args.poll_interval

    # Environment variable overrides
    config.cfp_host = os.environ.get('CFP_HOST', config.cfp_host)
    config.mqtt_broker = os.environ.get('MQTT_BROKER', config.mqtt_broker)
    config.node_id = os.environ.get('NODE_ID', config.node_id)

    # Create and start node
    node = CFPNode(config)

    # Signal handlers
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal")
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start node
    if node.start():
        logger.info(f"cFP node {config.node_id} running. Press Ctrl+C to stop.")
        # Keep main thread alive
        while node.running:
            time.sleep(1)
    else:
        logger.error("Failed to start cFP node")
        sys.exit(1)


if __name__ == '__main__':
    main()
