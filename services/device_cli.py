#!/usr/bin/env python3
"""
NISystem Device CLI - Interactive command-line interface for industrial devices

Supports: cRIO, cDAQ, Opto-22, cFP (CompactFieldPoint)

Provides real-time monitoring, control, and debugging capabilities via MQTT,
plus hardware discovery and diagnostics for development.

Usage:
    python device_cli.py                    # Start interactive mode
    python device_cli.py status             # Show all device status
    python device_cli.py read TC001         # Read a channel value
    python device_cli.py write DO001 1      # Write to a channel
    python device_cli.py monitor            # Live monitor all channels
    python device_cli.py ping               # Discover online nodes
    python device_cli.py scan               # Scan for hardware devices
    python device_cli.py info <node>        # Show device information
    python device_cli.py modules <node>     # List installed modules
    python device_cli.py diag <node>        # Run diagnostics
"""

import argparse
import cmd
import configparser
import json
import logging
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt not installed")
    print("Run: pip install paho-mqtt")
    sys.exit(1)

logger = logging.getLogger(__name__)

# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

def colored(text: str, color: str) -> str:
    """Apply color to text if terminal supports it"""
    if sys.platform == 'win32':
        os.system('')  # Enable ANSI on Windows
    return f"{color}{text}{Colors.ENDC}"

def success(msg: str) -> None:
    print(colored(f"  [OK] {msg}", Colors.GREEN))

def error(msg: str) -> None:
    print(colored(f"  [ERROR] {msg}", Colors.RED))

def warning(msg: str) -> None:
    print(colored(f"  [WARN] {msg}", Colors.YELLOW))

def info(msg: str) -> None:
    print(colored(f"  [INFO] {msg}", Colors.CYAN))

class DeviceMonitor:
    """MQTT-based device monitor for NISystem nodes"""

    def __init__(self, broker: str = 'localhost', port: int = 1883, base_topic: str = 'nisystem'):
        self.broker = broker
        self.port = port
        self.base_topic = base_topic
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.lock = threading.Lock()

        # Data stores
        self.nodes: Dict[str, Dict[str, Any]] = {}  # node_id -> status info
        self.channels: Dict[str, Dict[str, Any]] = {}  # channel_name -> value info
        self.last_heartbeat: Dict[str, datetime] = {}  # node_id -> last heartbeat time

        # Callbacks
        self.on_channel_update: Optional[callable] = None
        self.on_node_status: Optional[callable] = None

        # Response handling
        self.pending_responses: Dict[str, threading.Event] = {}
        self.response_data: Dict[str, Any] = {}

    def connect(self) -> bool:
        """Connect to MQTT broker"""
        try:
            self.client = mqtt.Client(client_id=f"device-cli-{os.getpid()}")
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            # Wait for connection
            for _ in range(30):  # 3 second timeout
                if self.connected:
                    return True
                time.sleep(0.1)

            return False

        except Exception as e:
            error(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connect callback"""
        if rc == 0:
            self.connected = True
            # Subscribe to all node topics
            subscriptions = [
                (f"{self.base_topic}/nodes/+/status/#", 1),
                (f"{self.base_topic}/nodes/+/heartbeat", 1),
                (f"{self.base_topic}/nodes/+/channels/#", 1),
                (f"{self.base_topic}/nodes/+/alarms/#", 1),
                (f"{self.base_topic}/nodes/+/safety/#", 1),
                (f"{self.base_topic}/nodes/+/channel/response", 1),
                (f"{self.base_topic}/discovery/response", 1),
                (f"{self.base_topic}/output/response", 1),
                # DAQ service topics
                (f"{self.base_topic}/daq/channels/#", 1),
                (f"{self.base_topic}/daq/status", 1),
            ]
            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
        else:
            error(f"Connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        self.connected = False
        if rc != 0:
            warning("Unexpected disconnection, attempting reconnect...")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            # Parse topic structure
            parts = topic.split('/')

            # Handle node topics: nisystem/nodes/{node_id}/...
            if len(parts) >= 4 and parts[1] == 'nodes':
                node_id = parts[2]
                category = parts[3] if len(parts) > 3 else ''

                with self.lock:
                    if node_id not in self.nodes:
                        self.nodes[node_id] = {'id': node_id, 'online': False}

                if category == 'heartbeat':
                    self._handle_heartbeat(node_id, payload)
                elif category == 'status':
                    self._handle_status(node_id, parts[4] if len(parts) > 4 else '', payload)
                elif category == 'channels':
                    self._handle_channels(node_id, parts[4] if len(parts) > 4 else '', payload)
                elif category == 'channel' and len(parts) > 4 and parts[4] == 'response':
                    self._handle_channel_response(node_id, payload)
                elif category == 'alarms':
                    self._handle_alarms(node_id, payload)
                elif category == 'safety':
                    self._handle_safety(node_id, payload)

            # Handle DAQ topics
            elif len(parts) >= 3 and parts[1] == 'daq':
                if parts[2] == 'channels':
                    self._handle_daq_channels(payload)
                elif parts[2] == 'status':
                    self._handle_daq_status(payload)

            # Handle discovery response
            elif topic == f"{self.base_topic}/discovery/response":
                self._handle_discovery(payload)

            # Handle output response
            elif topic == f"{self.base_topic}/output/response":
                self._handle_output_response(payload)

        except json.JSONDecodeError:
            pass  # Ignore non-JSON messages
        except Exception as e:
            pass  # Silently handle errors in callback

    def _handle_heartbeat(self, node_id: str, payload: Dict):
        """Handle heartbeat message"""
        with self.lock:
            self.last_heartbeat[node_id] = datetime.now()
            self.nodes[node_id]['online'] = True
            self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
            if 'uptime' in payload:
                self.nodes[node_id]['uptime'] = payload['uptime']

    def _handle_status(self, node_id: str, status_type: str, payload: Dict):
        """Handle status message"""
        with self.lock:
            self.nodes[node_id]['online'] = True
            self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
            if status_type == 'system':
                self.nodes[node_id].update(payload)
            elif status_type:
                self.nodes[node_id][f'status_{status_type}'] = payload

        if self.on_node_status:
            self.on_node_status(node_id, status_type, payload)

    def _handle_channels(self, node_id: str, channel_type: str, payload: Dict):
        """Handle channel data"""
        with self.lock:
            if channel_type == 'batch':
                # Batch update
                for name, value in payload.get('values', {}).items():
                    self.channels[name] = {
                        'value': value,
                        'node': node_id,
                        'timestamp': datetime.now().isoformat()
                    }
            else:
                # Single channel
                name = payload.get('name', channel_type)
                self.channels[name] = {
                    'value': payload.get('value'),
                    'node': node_id,
                    'timestamp': datetime.now().isoformat(),
                    **payload
                }

        if self.on_channel_update:
            self.on_channel_update(node_id, channel_type, payload)

    def _handle_channel_response(self, node_id: str, payload: Dict):
        """Handle channel read/write response"""
        request_id = payload.get('request_id', '')
        if request_id and request_id in self.pending_responses:
            self.response_data[request_id] = payload
            self.pending_responses[request_id].set()

    def _handle_alarms(self, node_id: str, payload: Dict):
        """Handle alarm messages"""
        with self.lock:
            if 'alarms' not in self.nodes.get(node_id, {}):
                self.nodes[node_id]['alarms'] = []
            self.nodes[node_id]['alarms'] = payload.get('active', [])

    def _handle_safety(self, node_id: str, payload: Dict):
        """Handle safety status"""
        with self.lock:
            self.nodes[node_id]['safety'] = payload

    def _handle_daq_channels(self, payload: Dict):
        """Handle DAQ service channel updates"""
        with self.lock:
            for name, data in payload.items():
                if isinstance(data, dict):
                    self.channels[name] = {
                        'value': data.get('value'),
                        'node': 'daq',
                        'timestamp': datetime.now().isoformat(),
                        **data
                    }

    def _handle_daq_status(self, payload: Dict):
        """Handle DAQ service status"""
        with self.lock:
            self.nodes['daq'] = {
                'id': 'daq',
                'online': True,
                'last_seen': datetime.now().isoformat(),
                **payload
            }

    def _handle_discovery(self, payload: Dict):
        """Handle discovery response"""
        node_id = payload.get('node_id', '')
        if node_id:
            with self.lock:
                self.nodes[node_id] = {
                    'id': node_id,
                    'online': True,
                    'last_seen': datetime.now().isoformat(),
                    **payload
                }

    def _handle_output_response(self, payload: Dict):
        """Handle output write response"""
        request_id = payload.get('request_id', '')
        if request_id and request_id in self.pending_responses:
            self.response_data[request_id] = payload
            self.pending_responses[request_id].set()

    def ping_nodes(self, timeout: float = 2.0) -> Dict[str, bool]:
        """Send discovery ping and wait for responses"""
        # Clear existing discovery data
        initial_nodes = set(self.nodes.keys())

        # Send discovery ping
        self.client.publish(
            f"{self.base_topic}/discovery/ping",
            json.dumps({'timestamp': time.time()}),
            qos=1
        )

        # Wait for responses
        time.sleep(timeout)

        # Return discovered nodes
        with self.lock:
            return {
                node_id: data.get('online', False)
                for node_id, data in self.nodes.items()
            }

    def read_channel(self, channel: str, node_id: str = None, timeout: float = 5.0) -> Optional[Any]:
        """Read a channel value"""
        # First check if we have a cached value
        with self.lock:
            if channel in self.channels:
                return self.channels[channel].get('value')

        # If node specified, send read request
        if node_id:
            request_id = f"read-{time.time()}"
            event = threading.Event()
            self.pending_responses[request_id] = event

            self.client.publish(
                f"{self.base_topic}/nodes/{node_id}/channel/read",
                json.dumps({
                    'channel': channel,
                    'request_id': request_id
                }),
                qos=1
            )

            if event.wait(timeout):
                response = self.response_data.pop(request_id, {})
                del self.pending_responses[request_id]
                if response.get('success'):
                    return response.get('value')
                else:
                    error(response.get('error', 'Unknown error'))
            else:
                del self.pending_responses[request_id]
                warning("Read request timed out")

        return None

    def write_channel(self, channel: str, value: Any, node_id: str = None, timeout: float = 5.0) -> bool:
        """Write a value to a channel"""
        request_id = f"write-{time.time()}"
        event = threading.Event()
        self.pending_responses[request_id] = event

        # Determine topic
        if node_id:
            topic = f"{self.base_topic}/nodes/{node_id}/channel/write"
        else:
            topic = f"{self.base_topic}/output/set"

        self.client.publish(
            topic,
            json.dumps({
                'channel': channel,
                'value': value,
                'request_id': request_id
            }),
            qos=1
        )

        if event.wait(timeout):
            response = self.response_data.pop(request_id, {})
            del self.pending_responses[request_id]
            return response.get('success', False)
        else:
            del self.pending_responses[request_id]
            warning("Write request timed out")
            return False

    def get_nodes(self) -> Dict[str, Dict]:
        """Get all known nodes"""
        with self.lock:
            return dict(self.nodes)

    def get_channels(self) -> Dict[str, Dict]:
        """Get all known channels"""
        with self.lock:
            return dict(self.channels)

    def is_node_online(self, node_id: str, timeout_seconds: float = 30.0) -> bool:
        """Check if node is online based on heartbeat"""
        with self.lock:
            if node_id not in self.last_heartbeat:
                return False
            elapsed = (datetime.now() - self.last_heartbeat[node_id]).total_seconds()
            return elapsed < timeout_seconds

    def send_command(self, node_id: str, command: str, payload: Dict = None, timeout: float = 5.0) -> Optional[Dict]:
        """Send a command to a node and wait for response"""
        request_id = f"cmd-{time.time()}"
        event = threading.Event()
        self.pending_responses[request_id] = event

        # Subscribe to response topic temporarily
        response_topic = f"{self.base_topic}/nodes/{node_id}/command/response"

        def on_response(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode())
                if data.get('request_id') == request_id:
                    self.response_data[request_id] = data
                    event.set()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse command response from {msg.topic}: {e}")
            except Exception as e:
                logger.error(f"Error processing command response from {msg.topic}: {e}")

        self.client.message_callback_add(response_topic, on_response)
        self.client.subscribe(response_topic, qos=1)

        # Send command
        cmd_payload = {
            'command': command,
            'request_id': request_id,
            **(payload or {})
        }
        self.client.publish(
            f"{self.base_topic}/nodes/{node_id}/commands/{command}",
            json.dumps(cmd_payload),
            qos=1
        )

        # Wait for response
        result = None
        if event.wait(timeout):
            result = self.response_data.pop(request_id, None)

        # Cleanup
        del self.pending_responses[request_id]
        self.client.message_callback_remove(response_topic)
        self.client.unsubscribe(response_topic)

        return result

class HardwareScanner:
    """Hardware discovery and diagnostics for NI and industrial devices"""

    # Known device ports
    CRIO_SSH_PORT = 22
    CRIO_HTTP_PORT = 80
    OPTO22_HTTP_PORT = 443
    OPTO22_REST_PORT = 22001
    CFP_PORT = 502  # Modbus
    MODBUS_PORT = 502

    # NI device identification
    NI_VENDOR_ID = 0x3923

    def __init__(self):
        self.discovered_devices: List[Dict] = []
        self.local_ni_devices: List[Dict] = []

    def scan_network(self, subnet: str = None, timeout: float = 1.0) -> List[Dict]:
        """Scan network for industrial devices"""
        if subnet is None:
            subnet = self._get_local_subnet()

        if not subnet:
            return []

        devices = []

        # Parse subnet (e.g., "192.168.1.0/24" or "192.168.1")
        if '/' in subnet:
            base_ip = subnet.split('/')[0]
            base_parts = base_ip.split('.')[:3]
        else:
            base_parts = subnet.split('.')[:3]

        base = '.'.join(base_parts)

        print(f"  Scanning {base}.1-254...")

        # Parallel scan
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {}
            for i in range(1, 255):
                ip = f"{base}.{i}"
                futures[executor.submit(self._probe_host, ip, timeout)] = ip

            for future in as_completed(futures):
                result = future.result()
                if result:
                    devices.append(result)
                    # Print as discovered
                    dev_type = result.get('type', 'Unknown')
                    ip = result.get('ip', '?')
                    print(f"    Found: {colored(dev_type, Colors.GREEN)} at {ip}")

        self.discovered_devices = devices
        return devices

    def _get_local_subnet(self) -> Optional[str]:
        """Get local network subnet"""
        try:
            # Get local IP by connecting to a remote address (doesn't actually connect)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except OSError as e:
            logger.debug(f"Could not determine local subnet: {e}")
            return None

    def _probe_host(self, ip: str, timeout: float) -> Optional[Dict]:
        """Probe a single host for known device types"""
        device = {'ip': ip, 'type': 'Unknown', 'ports': []}

        # Quick ping first
        if not self._ping(ip, timeout):
            return None

        # Check for cRIO (SSH + HTTP with NI signature)
        if self._check_port(ip, self.CRIO_SSH_PORT, timeout):
            device['ports'].append(22)
            # Try to identify as cRIO
            if self._check_port(ip, self.CRIO_HTTP_PORT, timeout):
                device['ports'].append(80)
                if self._is_ni_device(ip, timeout):
                    device['type'] = 'cRIO'
                    device['model'] = self._get_ni_model(ip)
                    return device

        # Check for Opto22 (HTTPS + REST API)
        if self._check_port(ip, self.OPTO22_HTTP_PORT, timeout):
            device['ports'].append(443)
            if self._check_port(ip, self.OPTO22_REST_PORT, timeout):
                device['ports'].append(22001)
                device['type'] = 'Opto22'
                return device

        # Check for Modbus devices (cFP, generic PLCs)
        if self._check_port(ip, self.MODBUS_PORT, timeout):
            device['ports'].append(502)
            device['type'] = 'Modbus Device'
            # Try to identify cFP
            if self._is_cfp_device(ip, timeout):
                device['type'] = 'cFP'
            return device

        # Generic device with open ports
        if device['ports']:
            return device

        return None

    def _ping(self, ip: str, timeout: float) -> bool:
        """Quick ping check"""
        try:
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['ping', '-n', '1', '-w', str(int(timeout * 1000)), ip],
                    capture_output=True,
                    timeout=timeout + 1
                )
            else:
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', str(int(timeout)), ip],
                    capture_output=True,
                    timeout=timeout + 1
                )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Ping failed for {ip}: {e}")
            return False

    def _check_port(self, ip: str, port: int, timeout: float) -> bool:
        """Check if a port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except OSError as e:
            logger.debug(f"Port check failed for {ip}:{port}: {e}")
            return False

    def _is_ni_device(self, ip: str, timeout: float) -> bool:
        """Check if device is an NI device via HTTP"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, 80))
            sock.send(b"GET / HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
            response = sock.recv(1024).decode('utf-8', errors='ignore')
            sock.close()
            return 'National Instruments' in response or 'NI-' in response or 'LabVIEW' in response
        except OSError as e:
            logger.debug(f"NI device check failed for {ip}: {e}")
            return False

    def _get_ni_model(self, ip: str) -> str:
        """Try to get NI device model"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((ip, 80))
            sock.send(b"GET /nisysapi/device HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
            response = sock.recv(4096).decode('utf-8', errors='ignore')
            sock.close()

            # Try to parse model from response
            if 'cRIO-' in response:
                match = re.search(r'cRIO-\d+', response)
                if match:
                    return match.group(0)
            return 'cRIO (unknown model)'
        except OSError as e:
            logger.debug(f"Could not retrieve NI model from {ip}: {e}")
            return 'cRIO'

    def _is_cfp_device(self, ip: str, timeout: float) -> bool:
        """Check if Modbus device is a cFP"""
        # cFP devices respond to specific Modbus function codes
        # This is a simplified check - real implementation would send Modbus query
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, 502))

            # Modbus read device identification (function code 43)
            # Transaction ID (2) + Protocol ID (2) + Length (2) + Unit ID (1) + Function (1) + MEI type (1) + Read code (1) + Object ID (1)
            query = struct.pack('>HHHBBBBB', 1, 0, 5, 1, 43, 14, 1, 0)
            sock.send(query)
            response = sock.recv(256)
            sock.close()

            # Check for NI vendor identification in response
            return b'National' in response or b'NI' in response
        except OSError as e:
            logger.debug(f"cFP device check failed for {ip}: {e}")
            return False

    def scan_local_ni_hardware(self) -> List[Dict]:
        """Scan for local NI hardware using NI-DAQmx"""
        devices = []

        # Try NI-DAQmx Python API
        try:
            import nidaqmx
            from nidaqmx.system import System

            system = System.local()

            for device in system.devices:
                dev_info = {
                    'name': device.name,
                    'type': 'cDAQ' if 'cDAQ' in device.product_type else device.product_type,
                    'product_type': device.product_type,
                    'serial': str(device.serial_num) if device.serial_num else 'N/A',
                    'ai_channels': len(device.ai_physical_chans),
                    'ao_channels': len(device.ao_physical_chans),
                    'di_lines': len(device.di_lines),
                    'do_lines': len(device.do_lines),
                    'ci_channels': len(device.ci_physical_chans),
                    'co_channels': len(device.co_physical_chans),
                }

                # Get modules for cDAQ chassis
                if hasattr(device, 'chassis_module_devices'):
                    dev_info['modules'] = []
                    for mod in device.chassis_module_devices:
                        dev_info['modules'].append({
                            'name': mod.name,
                            'type': mod.product_type
                        })

                devices.append(dev_info)

        except ImportError:
            # NI-DAQmx not installed, try alternative methods
            pass
        except Exception as e:
            warning(f"Error scanning NI hardware: {e}")

        # Try nisyscfg (NI System Configuration)
        if not devices:
            devices = self._scan_nisyscfg()

        self.local_ni_devices = devices
        return devices

    def _scan_nisyscfg(self) -> List[Dict]:
        """Scan using NI System Configuration (nisyscfg)"""
        devices = []

        # Try to run NIMax equivalent command
        try:
            # On Windows, try to query NI hardware via WMI or registry
            if sys.platform == 'win32':
                import winreg

                ni_key_path = r"SOFTWARE\National Instruments\NI-DAQmx\Devices"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ni_key_path) as key:
                        i = 0
                        while True:
                            try:
                                device_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, device_name) as dev_key:
                                    try:
                                        product_type = winreg.QueryValueEx(dev_key, "ProductType")[0]
                                    except OSError:
                                        product_type = "Unknown"

                                    devices.append({
                                        'name': device_name,
                                        'type': 'cDAQ' if 'cDAQ' in product_type else product_type,
                                        'product_type': product_type,
                                    })
                                i += 1
                            except OSError:
                                break
                except FileNotFoundError:
                    pass
        except ImportError:
            pass

        return devices

    def get_device_info(self, ip_or_name: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Get detailed information about a device"""
        info = {
            'address': ip_or_name,
            'reachable': False,
            'type': 'Unknown',
            'details': {}
        }

        # Check if it's a local NI device name
        for dev in self.local_ni_devices:
            if dev.get('name') == ip_or_name:
                info['reachable'] = True
                info['type'] = dev.get('type', 'NI Device')
                info['details'] = dev
                return info

        # Try as IP address
        if self._ping(ip_or_name, timeout):
            info['reachable'] = True

            # Probe for device type
            probe_result = self._probe_host(ip_or_name, timeout)
            if probe_result:
                info['type'] = probe_result.get('type', 'Unknown')
                info['details'] = probe_result

        return info

    def run_diagnostics(self, node_id: str, monitor: 'DeviceMonitor') -> Dict[str, Any]:
        """Run diagnostics on a node via MQTT"""
        results = {
            'node_id': node_id,
            'timestamp': datetime.now().isoformat(),
            'tests': {}
        }

        # Test 1: Ping/connectivity
        print("  [1/5] Testing connectivity...")
        nodes = monitor.get_nodes()
        if node_id in nodes and nodes[node_id].get('online'):
            results['tests']['connectivity'] = {'status': 'PASS', 'message': 'Node online'}
        else:
            results['tests']['connectivity'] = {'status': 'FAIL', 'message': 'Node not responding'}
            return results

        # Test 2: Heartbeat timing
        print("  [2/5] Checking heartbeat...")
        if node_id in monitor.last_heartbeat:
            elapsed = (datetime.now() - monitor.last_heartbeat[node_id]).total_seconds()
            if elapsed < 10:
                results['tests']['heartbeat'] = {'status': 'PASS', 'message': f'Last heartbeat {elapsed:.1f}s ago'}
            else:
                results['tests']['heartbeat'] = {'status': 'WARN', 'message': f'Heartbeat delayed ({elapsed:.1f}s)'}
        else:
            results['tests']['heartbeat'] = {'status': 'WARN', 'message': 'No heartbeat received'}

        # Test 3: Channel data flow
        print("  [3/5] Testing channel data...")
        channels = monitor.get_channels()
        node_channels = [ch for ch, data in channels.items() if data.get('node') == node_id]
        if node_channels:
            results['tests']['channels'] = {'status': 'PASS', 'message': f'{len(node_channels)} channels active'}
        else:
            results['tests']['channels'] = {'status': 'WARN', 'message': 'No channel data received'}

        # Test 4: Command response
        print("  [4/5] Testing command response...")
        response = monitor.send_command(node_id, 'ping', timeout=3.0)
        if response:
            results['tests']['commands'] = {'status': 'PASS', 'message': 'Command response OK'}
        else:
            results['tests']['commands'] = {'status': 'WARN', 'message': 'No command response (may be normal)'}

        # Test 5: Safety system
        print("  [5/5] Checking safety system...")
        node_data = nodes.get(node_id, {})
        if 'safety' in node_data:
            safety = node_data['safety']
            if safety.get('safe_state'):
                results['tests']['safety'] = {'status': 'WARN', 'message': 'Safety system TRIPPED'}
            else:
                results['tests']['safety'] = {'status': 'PASS', 'message': 'Safety system OK'}
        else:
            results['tests']['safety'] = {'status': 'INFO', 'message': 'No safety data available'}

        return results

class DeviceCLI(cmd.Cmd):
    """Interactive command-line interface for NISystem devices"""

    intro = colored("""
============================================
   NISystem Device CLI
============================================
   Supports: cRIO, cDAQ, Opto-22, cFP

Type 'help' for available commands.
Type 'quit' or 'exit' to leave.

""", Colors.CYAN)

    prompt = colored('device> ', Colors.GREEN)

    def __init__(self, monitor: DeviceMonitor):
        super().__init__()
        self.monitor = monitor
        self.scanner = HardwareScanner()
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None

    def do_status(self, arg):
        """Show status of all nodes or a specific node
        Usage: status [node_id]"""
        nodes = self.monitor.get_nodes()

        if arg:
            # Show specific node
            if arg in nodes:
                self._print_node_status(arg, nodes[arg])
            else:
                error(f"Node '{arg}' not found")
        else:
            # Show all nodes
            if not nodes:
                warning("No nodes discovered. Try 'ping' first.")
                return

            print(f"\n{colored('Discovered Nodes:', Colors.BOLD)}")
            print("-" * 60)
            for node_id, data in sorted(nodes.items()):
                self._print_node_status(node_id, data)

    def _print_node_status(self, node_id: str, data: Dict):
        """Print status for a single node"""
        online = data.get('online', False)
        status_color = Colors.GREEN if online else Colors.RED
        status_text = "ONLINE" if online else "OFFLINE"

        print(f"\n  {colored(node_id, Colors.BOLD)}: {colored(status_text, status_color)}")

        if 'last_seen' in data:
            print(f"    Last seen: {data['last_seen']}")
        if 'uptime' in data:
            print(f"    Uptime: {data['uptime']}s")
        if 'node_type' in data:
            print(f"    Type: {data['node_type']}")
        if 'version' in data:
            print(f"    Version: {data['version']}")
        if 'safety' in data:
            safety = data['safety']
            safe_state = safety.get('safe_state', False)
            print(f"    Safety: {colored('TRIPPED', Colors.RED) if safe_state else colored('OK', Colors.GREEN)}")

    def do_ping(self, arg):
        """Discover online nodes
        Usage: ping"""
        print("\nDiscovering nodes...")
        nodes = self.monitor.ping_nodes(timeout=3.0)

        if not nodes:
            warning("No nodes responded to discovery ping")
            return

        print(f"\n{colored('Discovered Nodes:', Colors.BOLD)}")
        for node_id, online in sorted(nodes.items()):
            status = colored("ONLINE", Colors.GREEN) if online else colored("OFFLINE", Colors.RED)
            print(f"  {node_id}: {status}")

    def do_channels(self, arg):
        """List all channels or filter by pattern
        Usage: channels [filter]
        Example: channels TC  (show channels containing 'TC')"""
        channels = self.monitor.get_channels()

        if not channels:
            warning("No channel data received yet. Wait for updates or try 'ping'.")
            return

        # Filter if pattern provided
        if arg:
            channels = {k: v for k, v in channels.items() if arg.lower() in k.lower()}

        if not channels:
            warning(f"No channels matching '{arg}'")
            return

        print(f"\n{colored('Channels:', Colors.BOLD)} ({len(channels)} total)")
        print("-" * 70)
        print(f"  {'Name':<25} {'Value':<15} {'Node':<15} {'Updated'}")
        print("-" * 70)

        for name, data in sorted(channels.items()):
            value = data.get('value', 'N/A')
            if isinstance(value, float):
                value = f"{value:.4f}"
            node = data.get('node', '?')
            ts = data.get('timestamp', '')
            if ts:
                ts = ts.split('T')[1][:8] if 'T' in ts else ts
            print(f"  {name:<25} {str(value):<15} {node:<15} {ts}")

    def do_read(self, arg):
        """Read a channel value
        Usage: read <channel> [node_id]
        Example: read TC001
        Example: read TC001 crio-001"""
        args = arg.split()
        if not args:
            error("Usage: read <channel> [node_id]")
            return

        channel = args[0]
        node_id = args[1] if len(args) > 1 else None

        value = self.monitor.read_channel(channel, node_id)

        if value is not None:
            if isinstance(value, float):
                print(f"  {channel} = {colored(f'{value:.4f}', Colors.CYAN)}")
            else:
                print(f"  {channel} = {colored(str(value), Colors.CYAN)}")
        else:
            # Try cache
            channels = self.monitor.get_channels()
            if channel in channels:
                value = channels[channel].get('value')
                print(f"  {channel} = {colored(str(value), Colors.CYAN)} (cached)")
            else:
                warning(f"Channel '{channel}' not found")

    def do_write(self, arg):
        """Write a value to a channel
        Usage: write <channel> <value> [node_id]
        Example: write DO001 1
        Example: write Setpoint1 75.5 crio-001"""
        args = arg.split()
        if len(args) < 2:
            error("Usage: write <channel> <value> [node_id]")
            return

        channel = args[0]
        value_str = args[1]
        node_id = args[2] if len(args) > 2 else None

        # Parse value
        try:
            if value_str.lower() in ('true', 'on', '1'):
                value = True
            elif value_str.lower() in ('false', 'off', '0'):
                value = False
            elif '.' in value_str:
                value = float(value_str)
            else:
                value = int(value_str)
        except ValueError:
            value = value_str

        print(f"  Writing {channel} = {value}...")

        if self.monitor.write_channel(channel, value, node_id):
            success(f"Write successful: {channel} = {value}")
        else:
            error("Write failed or timed out")

    def do_monitor(self, arg):
        """Start/stop live monitoring of channels
        Usage: monitor [start|stop] [filter]
        Example: monitor start TC
        Example: monitor stop"""
        args = arg.split()
        action = args[0] if args else 'start'
        pattern = args[1] if len(args) > 1 else ''

        if action == 'stop':
            self.monitoring = False
            print("  Monitoring stopped")
            return

        if action == 'start':
            self.monitoring = True
            print(f"  {colored('Live monitoring started', Colors.GREEN)} (press Enter to stop)")
            if pattern:
                print(f"  Filter: {pattern}")

            # Set up callback
            def on_update(node_id, category, payload):
                if not self.monitoring:
                    return

                ts = datetime.now().strftime('%H:%M:%S')

                if category == 'batch':
                    for name, value in payload.get('values', {}).items():
                        if pattern and pattern.lower() not in name.lower():
                            continue
                        if isinstance(value, float):
                            print(f"  [{ts}] {name:<20} = {value:.4f}")
                        else:
                            print(f"  [{ts}] {name:<20} = {value}")
                else:
                    name = payload.get('name', category)
                    if pattern and pattern.lower() not in name.lower():
                        return
                    value = payload.get('value')
                    if isinstance(value, float):
                        print(f"  [{ts}] {name:<20} = {value:.4f}")
                    else:
                        print(f"  [{ts}] {name:<20} = {value}")

            self.monitor.on_channel_update = on_update

            # Wait for user to press Enter
            try:
                input()
            except KeyboardInterrupt:
                pass

            self.monitoring = False
            self.monitor.on_channel_update = None
            print("  Monitoring stopped")

    def do_nodes(self, arg):
        """List all discovered nodes (alias for status)
        Usage: nodes"""
        self.do_status(arg)

    def do_alarms(self, arg):
        """Show active alarms for all nodes or a specific node
        Usage: alarms [node_id]"""
        nodes = self.monitor.get_nodes()

        has_alarms = False
        for node_id, data in sorted(nodes.items()):
            if arg and node_id != arg:
                continue

            alarms = data.get('alarms', [])
            if alarms:
                has_alarms = True
                print(f"\n  {colored(node_id, Colors.BOLD)}:")
                for alarm in alarms:
                    print(f"    {colored('[ALARM]', Colors.RED)} {alarm}")

        if not has_alarms:
            success("No active alarms")

    def do_safety(self, arg):
        """Show safety status for all nodes or a specific node
        Usage: safety [node_id]"""
        nodes = self.monitor.get_nodes()

        for node_id, data in sorted(nodes.items()):
            if arg and node_id != arg:
                continue

            safety = data.get('safety', {})
            if safety:
                print(f"\n  {colored(node_id, Colors.BOLD)}:")
                safe_state = safety.get('safe_state', False)
                status = colored('TRIPPED', Colors.RED) if safe_state else colored('OK', Colors.GREEN)
                print(f"    Status: {status}")

                if 'interlocks' in safety:
                    print(f"    Interlocks:")
                    for name, tripped in safety['interlocks'].items():
                        state = colored('TRIPPED', Colors.RED) if tripped else colored('OK', Colors.GREEN)
                        print(f"      {name}: {state}")

    # ==================== Hardware Discovery ====================

    def do_scan(self, arg):
        """Scan for hardware devices on network or locally
        Usage: scan [network|local|all] [subnet]
        Examples:
            scan                    # Scan local + current subnet
            scan network            # Scan current network subnet
            scan local              # Scan local NI hardware (cDAQ, etc.)
            scan network 192.168.1  # Scan specific subnet
            scan all                # Scan both local and network"""
        args = arg.split()
        scan_type = args[0] if args else 'all'
        subnet = args[1] if len(args) > 1 else None

        print(f"\n{colored('Hardware Discovery', Colors.BOLD)}")
        print("=" * 50)

        if scan_type in ('local', 'all'):
            print(f"\n{colored('Local NI Hardware:', Colors.CYAN)}")
            print("-" * 40)
            devices = self.scanner.scan_local_ni_hardware()
            if devices:
                for dev in devices:
                    print(f"  {colored(dev['name'], Colors.GREEN)}: {dev.get('product_type', dev.get('type', 'Unknown'))}")
                    if 'serial' in dev:
                        print(f"    Serial: {dev['serial']}")
                    if 'ai_channels' in dev:
                        print(f"    AI: {dev['ai_channels']}, AO: {dev['ao_channels']}, DI: {dev['di_lines']}, DO: {dev['do_lines']}")
                    if 'modules' in dev:
                        print(f"    Modules:")
                        for mod in dev['modules']:
                            print(f"      - {mod['name']}: {mod['type']}")
            else:
                warning("No local NI hardware found (NI-DAQmx may not be installed)")

        if scan_type in ('network', 'all'):
            print(f"\n{colored('Network Devices:', Colors.CYAN)}")
            print("-" * 40)
            devices = self.scanner.scan_network(subnet)
            if devices:
                print(f"\n  Found {len(devices)} device(s):")
                for dev in devices:
                    dev_type = dev.get('type', 'Unknown')
                    color = Colors.GREEN if dev_type != 'Unknown' else Colors.YELLOW
                    print(f"    {colored(dev['ip'], color)}: {dev_type}")
                    if 'model' in dev:
                        print(f"      Model: {dev['model']}")
                    if dev.get('ports'):
                        print(f"      Ports: {', '.join(map(str, dev['ports']))}")
            else:
                warning("No network devices found")

    def do_info(self, arg):
        """Show detailed information about a device
        Usage: info <node_id_or_ip>
        Examples:
            info crio-001           # Info via MQTT
            info 192.168.1.20       # Info via network probe
            info Dev1               # Info for local NI device"""
        if not arg:
            error("Usage: info <node_id_or_ip>")
            return

        print(f"\n{colored(f'Device Information: {arg}', Colors.BOLD)}")
        print("=" * 50)

        # First check MQTT nodes
        nodes = self.monitor.get_nodes()
        if arg in nodes:
            data = nodes[arg]
            print(f"\n  {colored('MQTT Node Status:', Colors.CYAN)}")
            self._print_node_status(arg, data)

            # Request extended info from node
            print(f"\n  {colored('Requesting extended info...', Colors.DIM)}")
            response = self.monitor.send_command(arg, 'info', timeout=3.0)
            if response and response.get('success'):
                print(f"\n  {colored('Device Details:', Colors.CYAN)}")
                details = response.get('info', response)
                for key, value in details.items():
                    if key not in ('success', 'request_id'):
                        print(f"    {key}: {value}")
        else:
            # Try hardware scanner
            info = self.scanner.get_device_info(arg)
            if info['reachable']:
                print(f"\n  Type: {colored(info['type'], Colors.GREEN)}")
                print(f"  Reachable: Yes")
                if info['details']:
                    for key, value in info['details'].items():
                        if key not in ('ip', 'type'):
                            print(f"  {key}: {value}")
            else:
                warning(f"Device '{arg}' not found or not reachable")

    def do_modules(self, arg):
        """List modules installed in a device (cRIO, cDAQ chassis)
        Usage: modules <node_id_or_device>
        Examples:
            modules crio-001        # List cRIO modules via MQTT
            modules cDAQ1           # List local cDAQ chassis modules"""
        if not arg:
            error("Usage: modules <node_id_or_device>")
            return

        print(f"\n{colored(f'Modules: {arg}', Colors.BOLD)}")
        print("=" * 50)

        # Check local devices first
        for dev in self.scanner.local_ni_devices:
            if dev.get('name') == arg:
                if 'modules' in dev:
                    for i, mod in enumerate(dev['modules'], 1):
                        print(f"  Slot {i}: {colored(mod['name'], Colors.GREEN)} - {mod['type']}")
                else:
                    info("Device has no module slots (not a chassis)")
                return

        # Try MQTT node
        nodes = self.monitor.get_nodes()
        if arg in nodes:
            print("  Requesting module list from node...")
            response = self.monitor.send_command(arg, 'modules', timeout=3.0)
            if response and response.get('success'):
                modules = response.get('modules', [])
                if modules:
                    for mod in modules:
                        slot = mod.get('slot', '?')
                        name = mod.get('name', 'Unknown')
                        mod_type = mod.get('type', '')
                        print(f"  Slot {slot}: {colored(name, Colors.GREEN)} - {mod_type}")
                else:
                    info("No modules reported")
            else:
                # Fall back to status data
                data = nodes[arg]
                if 'modules' in data:
                    for mod in data['modules']:
                        print(f"  {mod}")
                else:
                    warning("Module information not available")
        else:
            warning(f"Device '{arg}' not found. Try 'scan local' first.")

    def do_diag(self, arg):
        """Run diagnostics on a node
        Usage: diag <node_id>
        Example: diag crio-001"""
        if not arg:
            error("Usage: diag <node_id>")
            return

        print(f"\n{colored(f'Running Diagnostics: {arg}', Colors.BOLD)}")
        print("=" * 50)

        results = self.scanner.run_diagnostics(arg, self.monitor)

        print(f"\n{colored('Results:', Colors.BOLD)}")
        print("-" * 40)

        all_pass = True
        for test_name, result in results['tests'].items():
            status = result['status']
            message = result['message']

            if status == 'PASS':
                status_str = colored('[PASS]', Colors.GREEN)
            elif status == 'FAIL':
                status_str = colored('[FAIL]', Colors.RED)
                all_pass = False
            elif status == 'WARN':
                status_str = colored('[WARN]', Colors.YELLOW)
            else:
                status_str = colored('[INFO]', Colors.CYAN)

            print(f"  {status_str} {test_name}: {message}")

        print()
        if all_pass:
            success("All diagnostics passed")
        else:
            warning("Some diagnostics failed or have warnings")

    def do_test(self, arg):
        """Test a specific output channel (toggle test)
        Usage: test <channel> [count] [delay_ms]
        Examples:
            test DO001              # Toggle once
            test DO001 5            # Toggle 5 times
            test DO001 3 500        # Toggle 3 times, 500ms delay"""
        args = arg.split()
        if not args:
            error("Usage: test <channel> [count] [delay_ms]")
            return

        channel = args[0]
        count = int(args[1]) if len(args) > 1 else 1
        delay = int(args[2]) / 1000.0 if len(args) > 2 else 0.5

        print(f"\n  Testing {channel}: {count} toggle(s), {delay*1000:.0f}ms delay")
        warning("This will toggle the output. Press Ctrl+C to abort.")

        try:
            time.sleep(1)  # Give user time to abort

            for i in range(count):
                print(f"    [{i+1}/{count}] ON...", end='', flush=True)
                self.monitor.write_channel(channel, True)
                time.sleep(delay)

                print(" OFF...", end='', flush=True)
                self.monitor.write_channel(channel, False)
                time.sleep(delay)

                print(" done")

            success(f"Toggle test complete for {channel}")

        except KeyboardInterrupt:
            print("\n  Aborted!")
            # Ensure output is off
            self.monitor.write_channel(channel, False)
            warning(f"Ensured {channel} is OFF")

    def do_registers(self, arg):
        """Read/write raw registers (Modbus) for debugging
        Usage: registers <node_id> read <address> [count]
               registers <node_id> write <address> <value>
        Examples:
            registers crio-001 read 40001       # Read holding register
            registers crio-001 read 40001 10    # Read 10 registers
            registers crio-001 write 40001 100  # Write value to register"""
        args = arg.split()
        if len(args) < 3:
            error("Usage: registers <node_id> read|write <address> [value|count]")
            return

        node_id = args[0]
        operation = args[1]
        address = int(args[2])

        if operation == 'read':
            count = int(args[3]) if len(args) > 3 else 1
            print(f"\n  Reading {count} register(s) from {address}...")

            response = self.monitor.send_command(node_id, 'modbus_read', {
                'address': address,
                'count': count
            }, timeout=5.0)

            if response and response.get('success'):
                values = response.get('values', [])
                print(f"\n  {colored('Register Values:', Colors.CYAN)}")
                for i, val in enumerate(values):
                    addr = address + i
                    print(f"    {addr}: {val} (0x{val:04X})")
            else:
                error(response.get('error', 'Read failed') if response else 'No response')

        elif operation == 'write':
            if len(args) < 4:
                error("Usage: registers <node_id> write <address> <value>")
                return

            value = int(args[3])
            print(f"\n  Writing {value} to register {address}...")

            response = self.monitor.send_command(node_id, 'modbus_write', {
                'address': address,
                'value': value
            }, timeout=5.0)

            if response and response.get('success'):
                success(f"Wrote {value} to register {address}")
            else:
                error(response.get('error', 'Write failed') if response else 'No response')

        else:
            error("Operation must be 'read' or 'write'")

    def do_firmware(self, arg):
        """Show firmware/software versions for a device
        Usage: firmware <node_id>"""
        if not arg:
            error("Usage: firmware <node_id>")
            return

        print(f"\n{colored(f'Firmware Info: {arg}', Colors.BOLD)}")
        print("=" * 50)

        nodes = self.monitor.get_nodes()
        if arg in nodes:
            data = nodes[arg]
            if 'version' in data:
                print(f"  Node Software: {data['version']}")
            if 'firmware' in data:
                print(f"  Firmware: {data['firmware']}")
            if 'os_version' in data:
                print(f"  OS: {data['os_version']}")

            # Request extended firmware info
            response = self.monitor.send_command(arg, 'firmware', timeout=3.0)
            if response and response.get('success'):
                for key, value in response.items():
                    if key not in ('success', 'request_id'):
                        print(f"  {key}: {value}")
        else:
            warning(f"Node '{arg}' not found")

    def do_reboot(self, arg):
        """Reboot a device (requires confirmation)
        Usage: reboot <node_id>"""
        if not arg:
            error("Usage: reboot <node_id>")
            return

        warning(f"This will reboot {arg}!")
        confirm = input("  Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("  Aborted")
            return

        print(f"  Sending reboot command to {arg}...")
        response = self.monitor.send_command(arg, 'reboot', timeout=5.0)
        if response and response.get('success'):
            success(f"Reboot command sent to {arg}")
        else:
            error("Reboot command failed or not acknowledged")

    # ==================== End Hardware Discovery ====================

    def do_raw(self, arg):
        """Send raw MQTT message
        Usage: raw <topic> <json_payload>
        Example: raw nisystem/discovery/ping {}"""
        args = arg.split(maxsplit=1)
        if len(args) < 2:
            error("Usage: raw <topic> <json_payload>")
            return

        topic = args[0]
        try:
            payload = json.loads(args[1])
        except json.JSONDecodeError as e:
            error(f"Invalid JSON: {e}")
            return

        self.monitor.client.publish(topic, json.dumps(payload), qos=1)
        success(f"Published to {topic}")

    def do_subscribe(self, arg):
        """Subscribe to additional MQTT topics and show messages
        Usage: subscribe <topic>
        Example: subscribe nisystem/nodes/+/safety/#"""
        if not arg:
            error("Usage: subscribe <topic>")
            return

        print(f"  Subscribing to {arg} (press Enter to stop)")

        messages = []

        def on_message(client, userdata, msg):
            ts = datetime.now().strftime('%H:%M:%S')
            try:
                payload = json.loads(msg.payload.decode())
                messages.append(f"[{ts}] {msg.topic}:\n{json.dumps(payload, indent=2)}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                messages.append(f"[{ts}] {msg.topic}: {msg.payload.decode(errors='replace')}")

        # Temporarily add handler
        original_handler = self.monitor.client.on_message
        self.monitor.client.message_callback_add(arg, on_message)
        self.monitor.client.subscribe(arg, qos=1)

        try:
            while True:
                if messages:
                    print(messages.pop(0))
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.monitor.client.message_callback_remove(arg)
            self.monitor.client.unsubscribe(arg)

        print("\n  Unsubscribed")

    def do_quit(self, arg):
        """Exit the CLI"""
        print("Goodbye!")
        return True

    def do_exit(self, arg):
        """Exit the CLI"""
        return self.do_quit(arg)

    def do_clear(self, arg):
        """Clear the screen"""
        os.system('cls' if sys.platform == 'win32' else 'clear')

    def emptyline(self):
        """Do nothing on empty line"""
        pass

    def default(self, line):
        """Handle unknown commands"""
        error(f"Unknown command: {line}")
        print("  Type 'help' for available commands")

def load_config() -> Dict[str, Any]:
    """Load configuration from system.ini or node_deploy.json"""
    config = {
        'broker': 'localhost',
        'port': 1883,
        'base_topic': 'nisystem'
    }

    script_dir = Path(__file__).parent

    # Try node_deploy.json first
    deploy_config = script_dir / 'node_deploy.json'
    if deploy_config.exists():
        try:
            with open(deploy_config) as f:
                data = json.load(f)
                config['broker'] = data.get('mqtt_broker', config['broker'])
                config['port'] = data.get('mqtt_port', config['port'])
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config from {deploy_config}: {e}")

    # Try system.ini
    system_ini = script_dir.parent / 'config' / 'system.ini'
    if system_ini.exists():
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(system_ini)
            if 'mqtt' in cp:
                config['broker'] = cp['mqtt'].get('broker', config['broker'])
                config['port'] = cp['mqtt'].getint('port', config['port'])
            if 'system' in cp:
                config['base_topic'] = cp['system'].get('mqtt_base_topic', config['base_topic'])
        except (configparser.Error, OSError) as e:
            logger.warning(f"Failed to load config from {system_ini}: {e}")

    return config

def main():
    parser = argparse.ArgumentParser(
        description='NISystem Device CLI - Interactive interface for cRIO and Opto22',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands (interactive mode):
  status [node]      Show node status
  ping               Discover online nodes
  channels [filter]  List channels
  read <ch> [node]   Read channel value
  write <ch> <val>   Write to channel
  monitor [filter]   Live monitor channels
  alarms [node]      Show active alarms
  safety [node]      Show safety status
  quit               Exit

Examples:
  %(prog)s                    Start interactive mode
  %(prog)s --broker 192.168.1.100 ping
  %(prog)s read TC001
  %(prog)s write DO001 1
        """
    )

    parser.add_argument('--broker', '-b', help='MQTT broker address')
    parser.add_argument('--port', '-p', type=int, help='MQTT broker port')
    parser.add_argument('--topic', '-t', help='Base MQTT topic (default: nisystem)')
    parser.add_argument('command', nargs='?', help='Command to run (or interactive if omitted)')
    parser.add_argument('args', nargs='*', help='Command arguments')

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Override with command-line args
    if args.broker:
        config['broker'] = args.broker
    if args.port:
        config['port'] = args.port
    if args.topic:
        config['base_topic'] = args.topic

    # Create monitor
    monitor = DeviceMonitor(
        broker=config['broker'],
        port=config['port'],
        base_topic=config['base_topic']
    )

    # Connect
    print(f"Connecting to MQTT broker at {config['broker']}:{config['port']}...")
    if not monitor.connect():
        error(f"Failed to connect to MQTT broker at {config['broker']}:{config['port']}")
        sys.exit(1)

    success(f"Connected to {config['broker']}:{config['port']}")

    try:
        if args.command:
            # Single command mode
            cli = DeviceCLI(monitor)

            # Wait a moment for subscriptions to settle
            time.sleep(0.5)

            # Build command string
            cmd_line = args.command
            if args.args:
                cmd_line += ' ' + ' '.join(args.args)

            # Execute command
            cli.onecmd(cmd_line)
        else:
            # Interactive mode
            # Wait for initial data
            time.sleep(1.0)

            cli = DeviceCLI(monitor)
            cli.cmdloop()

    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        monitor.disconnect()

if __name__ == '__main__':
    main()
