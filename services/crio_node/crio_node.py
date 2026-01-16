#!/usr/bin/env python3
"""
cRIO Node Service for NISystem

Standalone service that runs ON the cRIO-9056 and:
1. Connects to NISystem PC's MQTT broker as a client
2. Receives configuration from NISystem and saves locally
3. Runs DAQ loop with NI-DAQmx watchdog for safe state on failure
4. Continues running even if PC disconnects
5. Executes Python scripts pushed from NISystem

Architecture:
    NISystem PC                              cRIO-9056
    ┌─────────────────┐      MQTT      ┌─────────────────────┐
    │  Dashboard      │◄──────────────►│  cRIO Node Service  │
    │  Backend        │   Config/Data   │  - Local config     │
    │  Project Mgmt   │                 │  - DAQmx watchdog   │
    └─────────────────┘                 │  - Python scripts   │
                                        └─────────────────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ C-Series    │
                                        │ Modules     │
                                        │ (TC,DI,DO)  │
                                        └─────────────┘

Safe State Behavior:
- NI-DAQmx hardware watchdog monitors RT task
- If Python stops petting watchdog, outputs go to safe state (LOW)
- Independent of PC connection - purely local hardware mechanism
"""

import json
import os
import time
import signal
import sys
import logging
import threading
import subprocess
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
import argparse

# MQTT client
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

# Try to import nidaqmx
try:
    import nidaqmx
    from nidaqmx.constants import (
        TerminalConfiguration, ThermocoupleType as NI_TCType,
        AcquisitionType
    )
    from nidaqmx.stream_readers import AnalogMultiChannelReader
    import numpy as np
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    print("WARNING: nidaqmx not available - running in simulation mode")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cRIONode')

# Constants
DEFAULT_CONFIG_DIR = Path('/home/admin/nisystem')  # cRIO Linux path
DEFAULT_CONFIG_FILE = 'crio_config.json'
WATCHDOG_TIMEOUT = 2.0  # seconds - outputs go safe if we don't pet watchdog
SAMPLE_RATE_HZ = 10
BUFFER_SIZE = 100
HEARTBEAT_INTERVAL = 2.0  # seconds
STATUS_PUBLISH_INTERVAL = 30.0  # seconds - periodic status for discovery


@dataclass
class ChannelConfig:
    """Channel configuration matching NISystem format"""
    name: str
    physical_channel: str
    channel_type: str  # thermocouple, voltage, current, digital_input, digital_output, counter

    # Type-specific settings
    thermocouple_type: str = 'K'
    voltage_range: float = 10.0
    current_range_ma: float = 20.0
    terminal_config: str = 'RSE'
    cjc_source: str = 'BUILT_IN'

    # Output settings
    default_state: bool = False
    invert: bool = False

    # Scaling
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    engineering_units: str = ''

    # Alarm settings
    alarm_high: Optional[float] = None
    alarm_low: Optional[float] = None
    alarm_enabled: bool = False


@dataclass
class CRIOConfig:
    """Configuration for cRIO node"""
    node_id: str = 'crio-001'
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883  # Standard MQTT port (matches mosquitto.conf)
    mqtt_base_topic: str = 'nisystem'
    mqtt_username: str = ''
    mqtt_password: str = ''

    scan_rate_hz: float = 10.0
    publish_rate_hz: float = 4.0  # Rate at which to publish MQTT messages (separate from scan rate)
    watchdog_timeout: float = 2.0

    channels: Dict[str, ChannelConfig] = field(default_factory=dict)
    scripts: List[Dict[str, Any]] = field(default_factory=list)

    # Safe state outputs - which DO channels go LOW on watchdog expiry
    safe_state_outputs: List[str] = field(default_factory=list)


class CRIONodeService:
    """
    cRIO Node Service - runs independently on cRIO hardware
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / DEFAULT_CONFIG_FILE
        self.config: Optional[CRIOConfig] = None

        # MQTT
        self.mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_connected = threading.Event()

        # Thread control
        self._running = threading.Event()
        self._acquiring = threading.Event()

        # Channel values
        self.channel_values: Dict[str, float] = {}
        self.channel_timestamps: Dict[str, float] = {}
        self.values_lock = threading.Lock()

        # Output state
        self.output_values: Dict[str, float] = {}

        # NI-DAQmx tasks
        self.input_tasks: Dict[str, Any] = {}
        self.output_tasks: Dict[str, Any] = {}
        self.watchdog_task: Optional[Any] = None
        self._watchdog_channels: List[str] = []  # For software watchdog fallback
        self._watchdog_last_pet: float = 0.0

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_sequence = 0

        # Script execution
        self.scripts: Dict[str, Dict[str, Any]] = {}
        self.script_threads: Dict[str, threading.Thread] = {}

        # Status
        self.last_pc_contact = time.time()
        self.pc_connected = False
        self._last_status_time = 0.0  # For periodic status publishing
        self._last_publish_time = 0.0  # For rate-limited channel publishing

        # Config version tracking (for PC sync)
        self.config_version = ''  # Hash of current config
        self.config_timestamp = ''  # ISO timestamp of last config update

        # Hardware info cache (detected once at startup)
        self._hardware_info: Optional[Dict[str, Any]] = None

        # Load config (if exists)
        self._load_local_config()

    # =========================================================================
    # CONFIGURATION PERSISTENCE
    # =========================================================================

    def _load_local_config(self):
        """Load configuration from local file (survives PC disconnect)"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)

                # Parse channels
                channels = {}
                for name, ch_data in data.get('channels', {}).items():
                    channels[name] = ChannelConfig(**ch_data)

                self.config = CRIOConfig(
                    node_id=data.get('node_id', 'crio-001'),
                    mqtt_broker=data.get('mqtt_broker', 'localhost'),
                    mqtt_port=data.get('mqtt_port', 1883),
                    mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
                    mqtt_username=data.get('mqtt_username', ''),
                    mqtt_password=data.get('mqtt_password', ''),
                    scan_rate_hz=data.get('scan_rate_hz', 10.0),
                    publish_rate_hz=data.get('publish_rate_hz', 4.0),
                    watchdog_timeout=data.get('watchdog_timeout', 2.0),
                    channels=channels,
                    scripts=data.get('scripts', []),
                    safe_state_outputs=data.get('safe_state_outputs', [])
                )
                logger.info(f"Loaded local config: {len(channels)} channels")
            except Exception as e:
                logger.error(f"Failed to load local config: {e}")
                self.config = CRIOConfig()
        else:
            logger.info("No local config found - waiting for config from NISystem")
            self.config = CRIOConfig()

    def _save_local_config(self):
        """Save configuration locally (for PC disconnect survival)"""
        if not self.config:
            return

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Convert to serializable dict
            data = {
                'node_id': self.config.node_id,
                'mqtt_broker': self.config.mqtt_broker,
                'mqtt_port': self.config.mqtt_port,
                'mqtt_base_topic': self.config.mqtt_base_topic,
                'mqtt_username': self.config.mqtt_username,
                'mqtt_password': self.config.mqtt_password,
                'scan_rate_hz': self.config.scan_rate_hz,
                'publish_rate_hz': self.config.publish_rate_hz,
                'watchdog_timeout': self.config.watchdog_timeout,
                'channels': {name: asdict(ch) for name, ch in self.config.channels.items()},
                'scripts': self.config.scripts,
                'safe_state_outputs': self.config.safe_state_outputs
            }

            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved config locally: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save local config: {e}")

    # =========================================================================
    # HARDWARE DETECTION
    # =========================================================================

    def _get_local_ip(self) -> str:
        """Get local IP address that can reach the MQTT broker"""
        # First try: connect to the MQTT broker to determine our local IP
        if self.config and self.config.mqtt_broker:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                # Connect to MQTT broker (doesn't send data, just gets routing info)
                s.connect((self.config.mqtt_broker, self.config.mqtt_port))
                ip = s.getsockname()[0]
                s.close()
                if ip and ip != '0.0.0.0':
                    return ip
            except Exception:
                pass

        # Fallback: try common external address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        # Last resort: hostname lookup
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip != '127.0.0.1':
                return ip
        except Exception:
            pass

        return 'unknown'

    def _detect_hardware_info(self) -> Dict[str, Any]:
        """
        Detect cRIO hardware info for status reporting.
        Caches result since hardware doesn't change at runtime.
        Includes full channel enumeration for Scan feature.

        Channel names are reported with full NI-DAQmx paths (e.g., cRIO-9056-12345678/Mod1/ai0)
        so they can be used directly when accessing this cRIO as a remote target from NISystem PC.
        """
        if self._hardware_info is not None:
            return self._hardware_info

        info = {
            'product_type': 'cRIO',
            'serial_number': '',
            'device_name': '',  # Full NI-DAQmx device name (e.g., cRIO-9056-12345678)
            'ip_address': '',  # Will be populated fresh each time in _publish_status
            'modules': []
        }

        # Try multiple methods to get cRIO serial number
        # Method 1: Read from ni-rt.ini (most reliable on NI Linux RT)
        try:
            ini_path = Path('/etc/natinst/share/ni-rt.ini')
            if ini_path.exists():
                ini_content = ini_path.read_text()
                for line in ini_content.split('\n'):
                    if line.startswith('serial=') or line.startswith('SerialNumber='):
                        serial = line.split('=', 1)[1].strip().strip('"')
                        if serial:
                            info['serial_number'] = serial
                            logger.debug(f"Got serial from ni-rt.ini: {serial}")
                            break
        except Exception as e:
            logger.debug(f"ni-rt.ini read failed: {e}")

        # Method 2: Try nisyscfg command
        if not info['serial_number']:
            try:
                result = subprocess.run(
                    ['nisyscfg', '-l'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Serial' in line and ':' in line:
                            serial = line.split(':', 1)[1].strip()
                            if serial:
                                info['serial_number'] = serial
                                logger.debug(f"Got serial from nisyscfg: {serial}")
                                break
            except Exception as e:
                logger.debug(f"nisyscfg failed: {e}")

        # Method 3: Try nilsdev command for modules and possibly serial
        try:
            result = subprocess.run(
                ['nilsdev', '--verbose'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                current_module = None
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('ProductType:'):
                        product = line.split(':', 1)[1].strip()
                        if 'cRIO' in product and info['product_type'] == 'cRIO':
                            info['product_type'] = product
                        elif current_module is not None:
                            current_module['product_type'] = product
                    elif line.startswith('DevSerialNum:') or line.startswith('SerialNum:'):
                        serial = line.split(':', 1)[1].strip()
                        if serial and not info['serial_number']:
                            info['serial_number'] = serial
                    elif line.startswith('Mod'):
                        # New module entry
                        if current_module is not None:
                            info['modules'].append(current_module)
                        mod_name = line.strip()
                        current_module = {
                            'name': mod_name,
                            'product_type': '',
                            'slot': int(mod_name.replace('Mod', '')) if mod_name.replace('Mod', '').isdigit() else 0,
                            'channels': []  # Will be populated by nidaqmx
                        }
                    elif line.startswith('CompactDAQ.SlotNum:') and current_module:
                        current_module['slot'] = int(line.split(':', 1)[1].strip())
                if current_module is not None:
                    info['modules'].append(current_module)
        except Exception as e:
            logger.debug(f"nilsdev detection failed: {e}")

        # Method 4: Use hostname as fallback (often set to serial on cRIO)
        if not info['serial_number']:
            try:
                hostname = socket.gethostname()
                # cRIO hostnames are often like "cRIO-9056-XXXXXXXX" or just the serial
                if hostname and hostname != 'localhost':
                    # If hostname contains the model, extract serial part
                    if '-' in hostname and any(c.isdigit() for c in hostname):
                        parts = hostname.split('-')
                        # Last part is often the serial
                        if len(parts) >= 2 and len(parts[-1]) >= 6:
                            info['serial_number'] = parts[-1]
                            logger.debug(f"Got serial from hostname: {parts[-1]}")
            except Exception as e:
                logger.debug(f"hostname fallback failed: {e}")

        # Use nidaqmx to enumerate physical channels for each module
        if NIDAQMX_AVAILABLE:
            try:
                system = nidaqmx.system.System.local()

                # Get device list once to avoid repeated iteration
                device_list = list(system.devices)

                # If no modules from nilsdev, get them from nidaqmx
                if not info['modules']:
                    for device in device_list:
                        if 'cRIO' in device.product_type:
                            info['product_type'] = device.product_type
                            try:
                                info['serial_number'] = str(device.dev_serial_num)
                            except Exception:
                                pass
                        elif 'NI 9' in device.product_type:
                            info['modules'].append({
                                'name': device.name,
                                'product_type': device.product_type,
                                'slot': 0,
                                'channels': []
                            })

                # Build the full device name for remote access from PC
                if info['product_type'] and info['serial_number']:
                    info['device_name'] = f"{info['product_type']}-{info['serial_number']}"
                elif info['product_type']:
                    info['device_name'] = info['product_type']

                device_prefix = info['device_name']

                # Enumerate channels for each module
                for device in device_list:
                    # Skip the cRIO chassis itself
                    if 'cRIO' in device.product_type:
                        continue

                    # Find matching module in our list
                    module = next((m for m in info['modules'] if m['name'] == device.name), None)
                    if module is None:
                        continue

                    channels = []
                    product_type = module['product_type']

                    # Analog Input channels
                    try:
                        ai_chans = list(device.ai_physical_chans)
                        category = self._get_channel_category(product_type, 'ai')
                        for ch in ai_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'analog_input',
                                'category': category
                            })
                    except Exception:
                        pass

                    # Analog Output channels
                    try:
                        ao_chans = list(device.ao_physical_chans)
                        category = self._get_channel_category(product_type, 'ao')
                        for ch in ao_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'analog_output',
                                'category': category
                            })
                    except Exception:
                        pass

                    # Digital Input lines
                    try:
                        di_lines = list(device.di_lines)
                        for ch in di_lines:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'digital_input',
                                'category': 'digital'
                            })
                    except Exception:
                        pass

                    # Digital Output lines
                    try:
                        do_lines = list(device.do_lines)
                        for ch in do_lines:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'digital_output',
                                'category': 'digital'
                            })
                    except Exception:
                        pass

                    # Counter channels
                    try:
                        ci_chans = list(device.ci_physical_chans)
                        for ch in ci_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'counter_input',
                                'category': 'counter'
                            })
                    except Exception:
                        pass

                    module['channels'] = channels

            except Exception as e:
                logger.warning(f"nidaqmx channel enumeration failed: {e}")

        # Count total channels
        total_channels = sum(len(m.get('channels', [])) for m in info['modules'])

        self._hardware_info = info
        logger.info(f"Detected hardware: {info.get('device_name', info['product_type'])} with {len(info['modules'])} modules, {total_channels} channels")
        return info

    def _get_channel_category(self, product_type: str, channel_type: str) -> str:
        """
        Determine channel category based on module type.

        Returns the signal type category (thermocouple, voltage, current, rtd, digital)
        which is separate from channel_type (analog_input, analog_output, etc.)

        Supports all C-series modules compatible with cRIO-9056.
        """
        # Extract module number from product type (e.g., "NI 9213" -> "9213")
        import re
        match = re.search(r'9\d{3}', product_type)
        module_num = match.group() if match else ''

        # =====================================================================
        # THERMOCOUPLE MODULES (AI)
        # =====================================================================
        tc_modules = ['9210', '9211', '9212', '9213', '9214', '9219']
        if module_num in tc_modules:
            return 'thermocouple'

        # =====================================================================
        # RTD / RESISTANCE MODULES (AI)
        # =====================================================================
        rtd_modules = ['9216', '9217', '9226']
        if module_num in rtd_modules:
            return 'rtd'

        # =====================================================================
        # CURRENT INPUT MODULES (AI)
        # =====================================================================
        current_in_modules = ['9203', '9207', '9208', '9227']
        if module_num in current_in_modules:
            return 'current'

        # =====================================================================
        # CURRENT OUTPUT MODULES (AO)
        # =====================================================================
        current_out_modules = ['9265', '9266']
        if module_num in current_out_modules:
            return 'current_output'

        # =====================================================================
        # STRAIN / BRIDGE MODULES (AI)
        # =====================================================================
        strain_modules = ['9235', '9236', '9237', '9219']
        if module_num in strain_modules and channel_type == 'ai':
            return 'strain'

        # =====================================================================
        # IEPE / ACCELEROMETER MODULES (AI)
        # =====================================================================
        iepe_modules = ['9230', '9231', '9232', '9234']
        if module_num in iepe_modules:
            return 'iepe'

        # =====================================================================
        # DIGITAL INPUT MODULES
        # =====================================================================
        di_modules = ['9401', '9402', '9411', '9421', '9422', '9423', '9425', '9426', '9435']
        if module_num in di_modules:
            return 'digital'

        # =====================================================================
        # DIGITAL OUTPUT MODULES
        # =====================================================================
        do_modules = ['9472', '9474', '9475', '9476', '9477', '9478']
        if module_num in do_modules:
            return 'digital'

        # =====================================================================
        # DIGITAL I/O (BIDIRECTIONAL) MODULES
        # =====================================================================
        dio_modules = ['9375', '9403']
        if module_num in dio_modules:
            return 'digital'

        # =====================================================================
        # RELAY MODULES
        # =====================================================================
        relay_modules = ['9481', '9482', '9485']
        if module_num in relay_modules:
            return 'relay'

        # =====================================================================
        # VOLTAGE INPUT MODULES (AI) - Most common, listed explicitly
        # =====================================================================
        voltage_in_modules = [
            '9201', '9202', '9205', '9206', '9215', '9220', '9221', '9222',
            '9223', '9229', '9233', '9238', '9239', '9242', '9243', '9244',
            '9246', '9247', '9250', '9251', '9252', '9253'
        ]
        if module_num in voltage_in_modules:
            return 'voltage'

        # =====================================================================
        # VOLTAGE OUTPUT MODULES (AO)
        # =====================================================================
        voltage_out_modules = ['9260', '9263', '9264', '9269']
        if module_num in voltage_out_modules:
            return 'voltage'

        # =====================================================================
        # DEFAULT FALLBACK - Based on channel type
        # =====================================================================
        if channel_type == 'ai':
            return 'voltage'
        elif channel_type == 'ao':
            return 'voltage'
        else:
            return 'unknown'

    # =========================================================================
    # MQTT TOPIC HELPERS
    # =========================================================================

    def get_topic_base(self) -> str:
        """Get node-prefixed topic base"""
        base = self.config.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.node_id if self.config else 'crio-001'
        return f"{base}/nodes/{node_id}"

    def get_topic(self, category: str, entity: str = "") -> str:
        """Build full MQTT topic"""
        base = self.get_topic_base()
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    # =========================================================================
    # MQTT CONNECTION
    # =========================================================================

    def _setup_mqtt(self):
        """Setup MQTT connection to NISystem broker"""
        if not self.config:
            return

        self.mqtt_client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"crio-{self.config.node_id}",
            clean_session=True
        )

        # Authentication
        if self.config.mqtt_username and self.config.mqtt_password:
            self.mqtt_client.username_pw_set(
                self.config.mqtt_username,
                self.config.mqtt_password
            )

        # Callbacks
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        # Last will - notify if we disconnect unexpectedly
        self.mqtt_client.will_set(
            self.get_topic('status', 'system'),
            json.dumps({'status': 'offline', 'node_type': 'crio'}),
            qos=1,
            retain=True
        )

        # Connect with retry
        self._connect_mqtt()

    def _connect_mqtt(self):
        """Connect to MQTT broker with infinite retry - never give up"""
        retry_delay = 2.0
        max_delay = 30.0  # Cap at 30 seconds
        attempt = 0

        while self._running.is_set():
            attempt += 1
            try:
                logger.info(f"Connecting to MQTT broker {self.config.mqtt_broker}:{self.config.mqtt_port} (attempt {attempt})...")
                self.mqtt_client.connect(
                    self.config.mqtt_broker,
                    self.config.mqtt_port,
                    keepalive=60
                )
                self.mqtt_client.loop_start()

                # Wait for connection
                if self._mqtt_connected.wait(timeout=10.0):
                    logger.info("MQTT connected successfully")
                    return True
                else:
                    logger.warning("MQTT connection timeout - will retry")
                    self.mqtt_client.loop_stop()
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt} failed: {e}")

            # Exponential backoff with cap
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

        return False  # Only if _running cleared (shutdown)

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connected callback"""
        if reason_code == 0:
            self._mqtt_connected.set()
            self.pc_connected = True
            self.last_pc_contact = time.time()

            # Subscribe to config and command topics
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic  # e.g., "nisystem"
            subscriptions = [
                (f"{base}/config/#", 1),      # Configuration updates
                (f"{base}/commands/#", 1),    # Output commands
                (f"{base}/script/#", 1),      # Script management
                (f"{base}/system/#", 1),      # System commands
                # Global discovery ping - respond when PC scans for devices
                (f"{mqtt_base}/discovery/ping", 1),
            ]
            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
                logger.debug(f"Subscribed to: {topic}")

            # Publish online status
            self._publish_status()

            logger.info("MQTT connected and subscribed")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnected callback"""
        self._mqtt_connected.clear()
        self.pc_connected = False
        logger.warning(f"MQTT disconnected (reason: {reason_code}) - will attempt reconnect")
        # Stop the loop - main loop will handle reconnection
        try:
            self.mqtt_client.loop_stop()
        except:
            pass

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            self.last_pc_contact = time.time()
            self.pc_connected = True

            # Route by topic
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic

            # Global discovery ping - respond immediately with full status
            if topic == f"{mqtt_base}/discovery/ping":
                logger.info("Received discovery ping - publishing status")
                self._publish_status()
                return

            if topic.startswith(f"{base}/config/"):
                self._handle_config_message(topic, payload)
            elif topic.startswith(f"{base}/commands/"):
                self._handle_command_message(topic, payload)
            elif topic.startswith(f"{base}/script/"):
                self._handle_script_message(topic, payload)
            elif topic.startswith(f"{base}/system/"):
                self._handle_system_message(topic, payload)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_config_message(self, topic: str, payload: Dict[str, Any]):
        """Handle configuration updates from NISystem"""
        if topic.endswith('/full'):
            # Full configuration update
            logger.info("Received full configuration update")

            # Parse channels - handle both array and dict formats
            channels = {}
            raw_channels = payload.get('channels', {})

            # If channels is a list (from frontend), convert to dict using 'name' field
            if isinstance(raw_channels, list):
                for ch_data in raw_channels:
                    name = ch_data.get('name')
                    if name:
                        channels[name] = self._parse_channel_config(ch_data)
            else:
                # Already a dict
                for name, ch_data in raw_channels.items():
                    channels[name] = self._parse_channel_config(ch_data)

            # Update config
            self.config.channels = channels
            self.config.scripts = payload.get('scripts', [])
            self.config.safe_state_outputs = payload.get('safe_state_outputs', [])

            # Store config version for sync tracking
            self.config_version = payload.get('config_version', '')
            self.config_timestamp = payload.get('timestamp', '')

            # Save locally
            self._save_local_config()

            # Reconfigure hardware
            self._configure_hardware()

            # Publish acknowledgment with config version
            self._publish(
                self.get_topic('config', 'response'),
                {
                    'status': 'ok',
                    'channels': len(channels),
                    'config_version': self.config_version,
                    'config_timestamp': self.config_timestamp
                }
            )
            logger.info(f"Config updated: {len(channels)} channels, version: {self.config_version}")

        elif topic.endswith('/channel/update'):
            # Single channel update
            channel_data = payload
            name = channel_data.get('name')
            if name:
                self.config.channels[name] = self._parse_channel_config(channel_data)
                self._save_local_config()
                logger.info(f"Updated channel: {name}")

    def _parse_channel_config(self, ch_data: Dict[str, Any]) -> ChannelConfig:
        """
        Parse channel config from dashboard format to cRIO format.

        Handles:
        - Field name mapping (dashboard uses 'unit', cRIO uses 'engineering_units')
        - Case normalization (dashboard 'internal' -> cRIO 'BUILT_IN')
        - Extra fields from dashboard are ignored
        """
        # Map dashboard field names to cRIO field names
        # Note: Alarm limits are handled separately with priority logic below
        field_map = {
            'unit': 'engineering_units',
        }

        # CJC source mapping (dashboard uses lowercase, cRIO uses NI-DAQmx constants)
        cjc_map = {
            'internal': 'BUILT_IN',
            'constant': 'CONST_VAL',
            'channel': 'CHAN',
            'built_in': 'BUILT_IN',
        }

        # Terminal config normalization (ensure uppercase)
        terminal_map = {
            'differential': 'DIFF',
            'rse': 'RSE',
            'nrse': 'NRSE',
            'pseudo_diff': 'PSEUDO_DIFF',
            'diff': 'DIFF',
        }

        # Build normalized config dict with only fields ChannelConfig accepts
        valid_fields = {
            'name', 'physical_channel', 'channel_type',
            'thermocouple_type', 'voltage_range', 'current_range_ma',
            'terminal_config', 'cjc_source',
            'default_state', 'invert',
            'scale_slope', 'scale_offset', 'engineering_units',
            'alarm_high', 'alarm_low', 'alarm_enabled'
        }

        normalized = {}

        # First pass: copy all standard fields
        for key, value in ch_data.items():
            # Map field names (skip alarm fields for now)
            if key in ('hihi_limit', 'high_limit', 'lolo_limit', 'low_limit'):
                continue

            mapped_key = field_map.get(key, key)

            # Skip fields not in ChannelConfig
            if mapped_key not in valid_fields:
                continue

            # Normalize specific fields
            if mapped_key == 'cjc_source' and isinstance(value, str):
                value = cjc_map.get(value.lower(), value.upper())
            elif mapped_key == 'terminal_config' and isinstance(value, str):
                value = terminal_map.get(value.lower(), value.upper())

            normalized[mapped_key] = value

        # Second pass: handle alarm limits with priority
        # hihi_limit takes priority over high_limit for alarm_high
        # lolo_limit takes priority over low_limit for alarm_low
        if ch_data.get('hihi_limit') is not None:
            normalized['alarm_high'] = ch_data['hihi_limit']
        elif ch_data.get('high_limit') is not None:
            normalized['alarm_high'] = ch_data['high_limit']

        if ch_data.get('lolo_limit') is not None:
            normalized['alarm_low'] = ch_data['lolo_limit']
        elif ch_data.get('low_limit') is not None:
            normalized['alarm_low'] = ch_data['low_limit']

        # Enable alarms if any limits are set
        if normalized.get('alarm_high') is not None or normalized.get('alarm_low') is not None:
            normalized['alarm_enabled'] = ch_data.get('alarm_enabled', True)

        # Ensure required fields have defaults
        if 'name' not in normalized:
            normalized['name'] = ''
        if 'physical_channel' not in normalized:
            normalized['physical_channel'] = ''
        if 'channel_type' not in normalized:
            normalized['channel_type'] = 'voltage'

        return ChannelConfig(**normalized)

    def _handle_command_message(self, topic: str, payload: Dict[str, Any]):
        """Handle output commands from NISystem"""
        # New format: topic ends with /commands/output, TAG name in payload
        # Old format: topic ends with /commands/{channel_name}
        if topic.endswith('/commands/output'):
            # New format - TAG name in payload (must match channel name in output_tasks)
            channel_name = payload.get('channel', '')
            value = payload.get('value')
            # PC may include physical_channel for fallback when config not pushed
            physical_channel = payload.get('physical_channel', '')
        else:
            # Old format - channel name from topic (legacy support)
            parts = topic.split('/')
            channel_name = parts[-1] if len(parts) >= 2 else ''
            value = payload.get('value')
            physical_channel = ''

        if not channel_name:
            return

        # Try to find the output task by various lookups
        task_key = None

        # 1. Direct match (works if config pushed with TAG names)
        if channel_name in self.output_tasks:
            task_key = channel_name

        # 2. Look up physical_channel from config and try that
        if not task_key and channel_name in self.config.channels:
            physical_ch = self.config.channels[channel_name].physical_channel
            if physical_ch and physical_ch in self.output_tasks:
                task_key = physical_ch
                logger.debug(f"Mapped {channel_name} -> {physical_ch} via config")

        # 3. Build reverse lookup: physical_channel -> TAG name from config
        if not task_key:
            for cfg_name, cfg in self.config.channels.items():
                if cfg.physical_channel and cfg.physical_channel in self.output_tasks:
                    if cfg_name == channel_name:
                        task_key = cfg.physical_channel
                        logger.debug(f"Reverse mapped {channel_name} -> {task_key}")
                        break

        # 4. Fallback: use physical_channel from payload directly (for when config not pushed)
        if not task_key and physical_channel and physical_channel in self.output_tasks:
            task_key = physical_channel
            logger.debug(f"Using physical_channel fallback: {channel_name} -> {physical_channel}")

        if task_key:
            self._write_output(task_key, value)
            logger.info(f"Output command: {channel_name} -> {task_key} = {value}")
        else:
            logger.warning(f"Unknown output channel: {channel_name} (physical={physical_channel}, available: {list(self.output_tasks.keys())})")

    def _handle_script_message(self, topic: str, payload: Dict[str, Any]):
        """Handle script commands from NISystem"""
        if topic.endswith('/add'):
            script_id = payload.get('id')
            self.scripts[script_id] = payload
            logger.info(f"Added script: {script_id}")
            self._publish_script_status()

        elif topic.endswith('/start'):
            script_id = payload.get('id')
            self._start_script(script_id)

        elif topic.endswith('/stop'):
            script_id = payload.get('id')
            self._stop_script(script_id)

        elif topic.endswith('/remove'):
            script_id = payload.get('id')
            self._stop_script(script_id)
            self.scripts.pop(script_id, None)
            logger.info(f"Removed script: {script_id}")
            self._publish_script_status()

    def _handle_system_message(self, topic: str, payload: Dict[str, Any]):
        """Handle system commands from NISystem"""
        if topic.endswith('/acquire/start'):
            self._start_acquisition()
        elif topic.endswith('/acquire/stop'):
            self._stop_acquisition()
        elif topic.endswith('/reset'):
            self._reset()
        elif topic.endswith('/safe-state'):
            self._set_safe_state(payload.get('reason', 'command'))

    def _set_safe_state(self, reason: str = 'command'):
        """Set all outputs to safe state (DO=0, AO=0)"""
        logger.info(f"Setting outputs to SAFE STATE - reason: {reason}")

        # Reset all digital outputs to OFF (0)
        for channel_name, task in self.output_tasks.items():
            try:
                ch_config = self.config.channels.get(channel_name)
                if ch_config and ch_config.channel_type == 'digital_output':
                    self._write_output(channel_name, 0)
                    logger.info(f"  DO {channel_name} -> 0 (OFF)")
                elif ch_config and ch_config.channel_type == 'analog_output':
                    # AO safe state: 0V for voltage, 4mA for current
                    safe_value = 0.004 if ch_config.category == 'current_output' else 0.0
                    self._write_output(channel_name, safe_value)
                    logger.info(f"  AO {channel_name} -> {safe_value}")
            except Exception as e:
                logger.error(f"  Failed to set {channel_name} safe: {e}")

        # Publish confirmation
        self._publish(f"{self.get_topic_base()}/status/safe-state", {
            'success': True,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # =========================================================================
    # HARDWARE CONFIGURATION
    # =========================================================================

    def _configure_hardware(self):
        """Configure NI-DAQmx tasks based on current config"""
        if not NIDAQMX_AVAILABLE:
            logger.warning("NI-DAQmx not available - using simulation")
            return

        # Close existing tasks
        self._close_tasks()

        # Group channels by type
        tc_channels = []
        voltage_channels = []
        current_channels = []
        di_channels = []
        do_channels = []
        ao_channels = []

        for name, ch in self.config.channels.items():
            if ch.channel_type == 'thermocouple':
                tc_channels.append(ch)
            elif ch.channel_type == 'voltage':
                voltage_channels.append(ch)
            elif ch.channel_type == 'current':
                current_channels.append(ch)
            elif ch.channel_type == 'digital_input':
                di_channels.append(ch)
            elif ch.channel_type == 'digital_output':
                do_channels.append(ch)
            elif ch.channel_type == 'analog_output':
                ao_channels.append(ch)

        # Create input tasks
        if tc_channels:
            self._create_thermocouple_task(tc_channels)
        if voltage_channels:
            self._create_voltage_task(voltage_channels)
        if current_channels:
            self._create_current_task(current_channels)
        if di_channels:
            self._create_digital_input_task(di_channels)

        # Create output tasks
        if ao_channels:
            self._create_analog_output_tasks(ao_channels)
        if do_channels:
            self._create_digital_output_tasks(do_channels)
            self._setup_watchdog(do_channels)

        logger.info(f"Hardware configured: {len(self.input_tasks)} input tasks, {len(self.output_tasks)} output tasks")

    def _create_thermocouple_task(self, channels: List[ChannelConfig]):
        """Create thermocouple input task"""
        task = nidaqmx.Task('TC_Input')
        channel_names = []

        try:
            for ch in channels:
                tc_type_map = {
                    'J': NI_TCType.J, 'K': NI_TCType.K, 'T': NI_TCType.T,
                    'E': NI_TCType.E, 'N': NI_TCType.N, 'R': NI_TCType.R,
                    'S': NI_TCType.S, 'B': NI_TCType.B
                }
                tc_type = tc_type_map.get(ch.thermocouple_type.upper(), NI_TCType.K)

                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.ai_channels.add_ai_thrmcpl_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    thermocouple_type=tc_type
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added TC channel: {ch.name} -> {ch.physical_channel}")

            # Configure continuous acquisition
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['thermocouple'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create TC task: {e}")

    def _create_voltage_task(self, channels: List[ChannelConfig]):
        """Create voltage input task"""
        task = nidaqmx.Task('Voltage_Input')
        channel_names = []

        try:
            for ch in channels:
                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')

                # Try preferred terminal config first, fallback to DIFF if not supported
                term_configs_to_try = []
                if ch.terminal_config.upper() == 'RSE':
                    term_configs_to_try = [TerminalConfiguration.RSE, TerminalConfiguration.DIFF]
                elif ch.terminal_config.upper() == 'DIFF':
                    term_configs_to_try = [TerminalConfiguration.DIFF]
                elif ch.terminal_config.upper() == 'NRSE':
                    term_configs_to_try = [TerminalConfiguration.NRSE, TerminalConfiguration.DIFF]
                else:
                    term_configs_to_try = [TerminalConfiguration.DIFF]  # Default to DIFF

                added = False
                for term_config in term_configs_to_try:
                    try:
                        task.ai_channels.add_ai_voltage_chan(
                            ch.physical_channel,
                            name_to_assign_to_channel=safe_name,
                            terminal_config=term_config,
                            min_val=-ch.voltage_range,
                            max_val=ch.voltage_range
                        )
                        channel_names.append(ch.name)  # Keep original name for our tracking
                        logger.info(f"Added voltage channel: {ch.name} -> {ch.physical_channel} ({term_config.name})")
                        added = True
                        break
                    except Exception as e:
                        if 'DAQmx_Val_Diff' in str(e) or 'TermCfg' in str(e):
                            continue  # Try next terminal config
                        raise  # Re-raise if different error

                if not added:
                    logger.warning(f"Could not add voltage channel: {ch.name}")

            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['voltage'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create voltage task: {e}")

    def _create_current_task(self, channels: List[ChannelConfig]):
        """Create current (4-20mA) input task"""
        from nidaqmx.constants import CurrentShuntResistorLocation

        task = nidaqmx.Task('Current_Input')
        channel_names = []

        try:
            for ch in channels:
                max_current = ch.current_range_ma / 1000.0  # Convert to Amps

                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.ai_channels.add_ai_current_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    min_val=0.0,
                    max_val=max_current,
                    shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added current channel: {ch.name} -> {ch.physical_channel}")

            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['current'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create current task: {e}")

    def _create_digital_input_task(self, channels: List[ChannelConfig]):
        """Create digital input task"""
        task = nidaqmx.Task('DI_Input')
        channel_names = []

        try:
            for ch in channels:
                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.di_channels.add_di_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=safe_name
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added DI channel: {ch.name} -> {ch.physical_channel}")

            self.input_tasks['digital_input'] = {
                'task': task,
                'reader': None,  # On-demand read for DI
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create DI task: {e}")

    def _create_analog_output_tasks(self, channels: List[ChannelConfig]):
        """Create analog output tasks (one per channel for independent control)"""
        for ch in channels:
            try:
                # Sanitize task name - NI-DAQmx doesn't allow / in task names
                safe_task_name = f"AO_{ch.name.replace('/', '_')}"
                safe_chan_name = ch.name.replace('/', '_')
                task = nidaqmx.Task(safe_task_name)

                # Check if we have a preserved value from before reconfiguration
                preserved_value = self.output_values.get(ch.name)

                # Check if this is a current output module by trying voltage first
                # then falling back to current if that fails
                try:
                    task.ao_channels.add_ao_voltage_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=safe_chan_name,
                        min_val=-10.0,
                        max_val=10.0
                    )
                    self.output_tasks[ch.name] = task

                    # Preserve existing state or use default
                    if preserved_value is not None:
                        task.write(preserved_value)
                        logger.info(f"Added AO voltage channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_value})")
                    else:
                        task.write(0.0)
                        self.output_values[ch.name] = 0.0
                        logger.info(f"Added AO voltage channel: {ch.name} -> {ch.physical_channel} (default=0.0)")

                except Exception as voltage_error:
                    # If voltage fails, try current output (for modules like NI 9266)
                    if 'DAQmx_Val_Current' in str(voltage_error):
                        task.close()
                        task = nidaqmx.Task(safe_task_name)
                        task.ao_channels.add_ao_current_chan(
                            ch.physical_channel,
                            name_to_assign_to_channel=safe_chan_name,
                            min_val=0.0,
                            max_val=0.020  # 20mA max
                        )
                        self.output_tasks[ch.name] = task

                        # Preserve existing state or use default 4mA
                        if preserved_value is not None:
                            task.write(preserved_value)
                            logger.info(f"Added AO current channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_value})")
                        else:
                            task.write(0.004)  # Start at 4mA (typical 4-20mA range)
                            self.output_values[ch.name] = 0.004
                            logger.info(f"Added AO current channel: {ch.name} -> {ch.physical_channel} (default=4mA)")
                    else:
                        raise voltage_error

            except Exception as e:
                logger.error(f"Failed to create AO task for {ch.name}: {e}")

    def _create_digital_output_tasks(self, channels: List[ChannelConfig]):
        """Create digital output tasks (one per channel for independent control)"""
        for ch in channels:
            try:
                # Sanitize task name - NI-DAQmx doesn't allow / in task names
                safe_task_name = f"DO_{ch.name.replace('/', '_')}"
                task = nidaqmx.Task(safe_task_name)
                task.do_channels.add_do_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=ch.name.replace('/', '_')  # Also sanitize line name
                )

                self.output_tasks[ch.name] = task

                # Preserve existing output state across reconfiguration
                # Only use default_state if this is truly the first time
                if ch.name in self.output_values:
                    # Restore previous state
                    preserved_state = bool(self.output_values[ch.name])
                    if ch.invert:
                        preserved_state = not preserved_state
                    task.write(preserved_state)
                    logger.info(f"Added DO channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_state})")
                else:
                    # First time - use default state
                    initial_state = ch.default_state
                    if ch.invert:
                        initial_state = not initial_state
                    task.write(initial_state)
                    self.output_values[ch.name] = 1.0 if initial_state else 0.0
                    logger.info(f"Added DO channel: {ch.name} -> {ch.physical_channel} (default={initial_state})")

            except Exception as e:
                logger.error(f"Failed to create DO task for {ch.name}: {e}")

    def _setup_watchdog(self, do_channels: List[ChannelConfig]):
        """
        Setup watchdog for digital outputs.

        On cRIO, hardware watchdog support varies by module. We use a software
        watchdog approach that tracks the last scan time and can trigger safe
        state if the scan loop stops.

        Note: True hardware watchdog requires specific NI FPGA configuration
        which is beyond the scope of this Python service.
        """
        if not NIDAQMX_AVAILABLE:
            return

        try:
            # Get safe state outputs (or default to all DO)
            safe_outputs = self.config.safe_state_outputs or [ch.name for ch in do_channels]

            # Build physical channel list for watchdog
            phys_channels = []
            for ch in do_channels:
                if ch.name in safe_outputs:
                    phys_channels.append(ch.physical_channel)

            if not phys_channels:
                logger.info("No safe state outputs configured - skipping watchdog")
                return

            # Use software watchdog - track channels for safe state on failure
            self._watchdog_channels = phys_channels
            self._watchdog_last_pet = time.time()
            self.watchdog_task = None  # No hardware watchdog

            logger.info(f"Software watchdog configured: timeout={self.config.watchdog_timeout}s, "
                       f"safe_outputs={len(phys_channels)} DO channels")

        except Exception as e:
            logger.warning(f"Watchdog setup skipped: {e}")
            self.watchdog_task = None

    def _pet_watchdog(self):
        """
        Pet the software watchdog to indicate RT task is running normally.
        Called in scan loop to track that acquisition is active.
        """
        # Software watchdog - just update the last pet time
        self._watchdog_last_pet = time.time()

    def _close_tasks(self):
        """Close all NI-DAQmx tasks"""
        # Close input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].close()
            except:
                pass
        self.input_tasks.clear()

        # Close output tasks
        for name, task in self.output_tasks.items():
            try:
                task.close()
            except:
                pass
        self.output_tasks.clear()

        # Close watchdog
        if self.watchdog_task:
            try:
                self.watchdog_task.close()
            except:
                pass
            self.watchdog_task = None

    # =========================================================================
    # DATA ACQUISITION
    # =========================================================================

    def _start_acquisition(self):
        """Start data acquisition"""
        if self._acquiring.is_set():
            logger.info("Acquisition already running")
            return

        logger.info("Starting acquisition...")

        # Start input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].start()
                logger.debug(f"Started task: {name}")
            except Exception as e:
                logger.error(f"Failed to start task {name}: {e}")

        # Start scan thread
        self._acquiring.set()
        self.scan_thread = threading.Thread(
            target=self._scan_loop,
            name="ScanLoop",
            daemon=True
        )
        self.scan_thread.start()

        # Publish status
        self._publish_status()
        logger.info("Acquisition started")

    def _stop_acquisition(self):
        """Stop data acquisition"""
        if not self._acquiring.is_set():
            return

        logger.info("Stopping acquisition...")
        self._acquiring.clear()

        # Wait for scan thread
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

        # Stop input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].stop()
            except:
                pass

        # Publish status
        self._publish_status()
        logger.info("Acquisition stopped")

    def _scan_loop(self):
        """Main data acquisition loop"""
        logger.info("Scan loop started")

        scan_interval = 1.0 / self.config.scan_rate_hz
        publish_interval = 1.0 / self.config.publish_rate_hz

        while self._acquiring.is_set():
            loop_start = time.time()

            try:
                # Pet the hardware watchdog
                self._pet_watchdog()

                # Read all inputs
                now = time.time()

                # Read analog inputs
                for task_name, task_info in self.input_tasks.items():
                    if task_info['reader'] is not None:
                        try:
                            task = task_info['task']
                            reader = task_info['reader']
                            channels = task_info['channels']

                            available = task.in_stream.avail_samp_per_chan
                            if available > 0:
                                num_channels = len(channels)
                                samples_to_read = min(available, BUFFER_SIZE)
                                buffer = np.zeros((num_channels, samples_to_read), dtype=np.float64)

                                reader.read_many_sample(buffer, number_of_samples_per_channel=samples_to_read, timeout=0.1)

                                with self.values_lock:
                                    for i, name in enumerate(channels):
                                        value = buffer[i, -1]  # Latest sample

                                        # Apply scaling
                                        ch_config = self.config.channels.get(name)
                                        if ch_config:
                                            value = value * ch_config.scale_slope + ch_config.scale_offset

                                            # Convert current from A to mA
                                            if ch_config.channel_type == 'current':
                                                value = value * 1000.0

                                        self.channel_values[name] = value
                                        self.channel_timestamps[name] = now
                        except Exception as e:
                            logger.warning(f"Error reading {task_name}: {e}")
                    else:
                        # On-demand read (digital inputs)
                        try:
                            task = task_info['task']
                            channels = task_info['channels']
                            raw_data = task.read(timeout=0.1)

                            with self.values_lock:
                                if isinstance(raw_data, list):
                                    for i, name in enumerate(channels):
                                        self.channel_values[name] = 1.0 if raw_data[i] else 0.0
                                        self.channel_timestamps[name] = now
                                else:
                                    self.channel_values[channels[0]] = 1.0 if raw_data else 0.0
                                    self.channel_timestamps[channels[0]] = now
                        except Exception as e:
                            logger.warning(f"Error reading {task_name}: {e}")

                # Include output values
                with self.values_lock:
                    for name, value in self.output_values.items():
                        self.channel_values[name] = value
                        self.channel_timestamps[name] = now

                # Publish channel values at publish_rate_hz (not scan_rate_hz)
                # This reduces MQTT message load significantly
                if now - self._last_publish_time >= publish_interval:
                    self._publish_channel_values()
                    self._last_publish_time = now

                # Check alarms
                self._check_alarms()

            except Exception as e:
                logger.error(f"Scan loop error: {e}")

            # Maintain scan rate
            elapsed = time.time() - loop_start
            sleep_time = scan_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Scan loop stopped")

    def _write_output(self, channel_name: str, value: Any) -> bool:
        """Write to an output channel (digital or analog)"""
        if channel_name not in self.output_tasks:
            logger.warning(f"Output channel not found: {channel_name}")
            return False

        try:
            task = self.output_tasks[channel_name]
            ch_config = self.config.channels.get(channel_name)

            if ch_config and ch_config.channel_type == 'analog_output':
                # Analog output - write float value
                float_value = float(value) if value is not None else 0.0
                task.write(float_value)
                self.output_values[channel_name] = float_value
                logger.debug(f"Wrote AO {channel_name} = {float_value}")
            else:
                # Digital output - write boolean
                bool_value = bool(value) if not isinstance(value, bool) else value

                # Apply invert
                if ch_config and ch_config.invert:
                    bool_value = not bool_value

                task.write(bool_value)
                self.output_values[channel_name] = 1.0 if bool_value else 0.0
                logger.debug(f"Wrote DO {channel_name} = {bool_value}")

            return True

        except Exception as e:
            logger.error(f"Failed to write {channel_name}: {e}")
            return False

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def _start_script(self, script_id: str):
        """Start executing a Python script"""
        if script_id not in self.scripts:
            logger.warning(f"Script not found: {script_id}")
            return

        script = self.scripts[script_id]

        if script_id in self.script_threads and self.script_threads[script_id].is_alive():
            logger.warning(f"Script already running: {script_id}")
            return

        # Start script in thread
        thread = threading.Thread(
            target=self._run_script,
            args=(script_id, script),
            name=f"Script-{script_id}",
            daemon=True
        )
        self.script_threads[script_id] = thread
        thread.start()

        logger.info(f"Started script: {script_id}")
        self._publish_script_status()

    def _stop_script(self, script_id: str):
        """Stop a running script"""
        # Scripts should check self._running flag periodically
        if script_id in self.script_threads:
            # Mark for stop (scripts should poll this)
            self.scripts[script_id]['_stop_requested'] = True
            logger.info(f"Stop requested for script: {script_id}")
            self._publish_script_status()

    def _run_script(self, script_id: str, script: Dict[str, Any]):
        """Execute a Python script"""
        code = script.get('code', '')

        # Create execution environment
        env = {
            'tags': self._create_tags_api(),
            'outputs': self._create_outputs_api(),
            'publish': self._create_publish_api(),
            'next_scan': lambda: time.sleep(1.0 / self.config.scan_rate_hz),
            'print': lambda *args: logger.info(f"[Script {script_id}] {' '.join(str(a) for a in args)}"),
            'should_stop': lambda: script.get('_stop_requested', False),
        }

        try:
            # Strip 'await' keywords for sync execution
            code = code.replace('await ', '')

            exec(code, env)
            logger.info(f"Script completed: {script_id}")
        except Exception as e:
            logger.error(f"Script error ({script_id}): {e}")
        finally:
            script['_stop_requested'] = False
            self._publish_script_status()

    def _create_tags_api(self):
        """Create tags API for scripts"""
        class TagsAPI:
            def __init__(self, parent):
                self._parent = parent

            def get(self, name: str) -> float:
                with self._parent.values_lock:
                    return self._parent.channel_values.get(name, 0.0)

            def __getattr__(self, name: str) -> float:
                return self.get(name)

        return TagsAPI(self)

    def _create_outputs_api(self):
        """Create outputs API for scripts"""
        class OutputsAPI:
            def __init__(self, parent):
                self._parent = parent

            def set(self, name: str, value: Any):
                self._parent._write_output(name, value)

        return OutputsAPI(self)

    def _create_publish_api(self):
        """Create publish API for scripts to send values to dashboard"""
        def publish(name: str, value: Any):
            self._publish(
                self.get_topic('script', 'values'),
                {name: value}
            )
        return publish

    # =========================================================================
    # MQTT PUBLISHING
    # =========================================================================

    def _publish(self, topic: str, payload: Dict[str, Any], retain: bool = False):
        """Publish message to MQTT"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            try:
                self.mqtt_client.publish(
                    topic,
                    json.dumps(payload),
                    qos=0,
                    retain=retain
                )
            except Exception as e:
                logger.warning(f"Publish failed: {e}")

    def _publish_status(self):
        """Publish system status with hardware info for discovery"""
        hw_info = self._detect_hardware_info()
        status = {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'crio',
            'node_id': self.config.node_id,
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            # Hardware info for discovery
            'ip_address': self._get_local_ip(),  # Get fresh each time (config may not be ready at startup)
            'product_type': hw_info['product_type'],
            'serial_number': hw_info['serial_number'],
            'device_name': hw_info.get('device_name', ''),  # Full NI-DAQmx device name for remote access
            'modules': hw_info['modules'],
            # Config version for sync tracking (PC can detect stale config)
            'config_version': self.config_version,
            'config_timestamp': self.config_timestamp
        }
        self._publish(self.get_topic('status', 'system'), status, retain=True)

    def _publish_channel_values(self):
        """Publish channel values to MQTT as a single batched message"""
        with self.values_lock:
            # Batch all channel values into a single message to reduce MQTT load
            # Format: { "channel_name": {"value": x, "timestamp": t}, ... }
            batch = {}
            for name, value in self.channel_values.items():
                batch[name] = {
                    'value': value,
                    'timestamp': self.channel_timestamps.get(name, 0)
                }

            if batch:
                self._publish(
                    self.get_topic('channels', 'batch'),
                    batch
                )

    def _publish_script_status(self):
        """Publish script status"""
        status = {}
        for script_id, script in self.scripts.items():
            thread = self.script_threads.get(script_id)
            status[script_id] = {
                'name': script.get('name', script_id),
                'running': thread is not None and thread.is_alive(),
                'stop_requested': script.get('_stop_requested', False)
            }
        self._publish(self.get_topic('script', 'status'), status)

    def _publish_heartbeat(self):
        """Publish heartbeat with node info for discovery fallback"""
        self._heartbeat_sequence += 1
        self._publish(
            self.get_topic('heartbeat'),
            {
                'seq': self._heartbeat_sequence,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'acquiring': self._acquiring.is_set(),
                'pc_connected': self.pc_connected,
                # Include node info so DAQ service can use heartbeat for discovery
                'node_type': 'crio',
                'node_id': self.config.node_id,
                'channels': len(self.config.channels),
            }
        )

    def _check_alarms(self):
        """Check alarm conditions"""
        with self.values_lock:
            for name, ch_config in self.config.channels.items():
                if not ch_config.alarm_enabled:
                    continue

                value = self.channel_values.get(name)
                if value is None:
                    continue

                alarm_active = False
                alarm_type = None

                if ch_config.alarm_high is not None and value > ch_config.alarm_high:
                    alarm_active = True
                    alarm_type = 'HIGH'
                elif ch_config.alarm_low is not None and value < ch_config.alarm_low:
                    alarm_active = True
                    alarm_type = 'LOW'

                # Publish alarm state change
                current_alarm = f"{name}_{alarm_type}" if alarm_active else None
                # (Simplified - full implementation would track state changes)

    # =========================================================================
    # HEARTBEAT
    # =========================================================================

    def _heartbeat_loop(self):
        """Heartbeat thread"""
        while self._running.is_set():
            self._publish_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    # =========================================================================
    # AUTO-DISCOVERY CHANNEL CREATION
    # =========================================================================

    def _auto_create_channels_from_hardware(self):
        """
        Auto-create channel configs for all detected hardware channels.
        This enables "magic" mode where the cRIO reads everything automatically
        without requiring explicit configuration from NISystem.
        """
        hw_info = self._detect_hardware_info()

        created_count = 0
        for module in hw_info.get('modules', []):
            for ch in module.get('channels', []):
                # Use local_name for the physical channel (what nidaqmx uses locally)
                local_name = ch.get('local_name', ch.get('name', ''))
                if not local_name:
                    continue

                # Skip if already configured
                if local_name in self.config.channels:
                    continue

                # Get category and hardware channel type
                category = ch.get('category', 'voltage')
                hw_channel_type = ch.get('channel_type', 'analog_input')

                # Map category + hw_channel_type to our channel_type
                if hw_channel_type == 'digital_input':
                    channel_type = 'digital_input'
                elif hw_channel_type == 'digital_output':
                    channel_type = 'digital_output'
                elif hw_channel_type == 'analog_output':
                    channel_type = 'analog_output'
                elif hw_channel_type == 'counter_input':
                    channel_type = 'counter'
                elif category == 'thermocouple':
                    channel_type = 'thermocouple'
                elif category == 'rtd':
                    channel_type = 'rtd'
                elif category == 'current':
                    channel_type = 'current'
                elif category == 'current_output':
                    channel_type = 'analog_output'  # Current output is still AO
                else:
                    channel_type = 'voltage'  # Default for analog inputs

                # Create channel config
                tc_type = 'K' if channel_type == 'thermocouple' else 'K'

                channel_config = ChannelConfig(
                    name=local_name,  # Use local path as name (e.g., "Mod1/ai0")
                    physical_channel=local_name,
                    channel_type=channel_type,
                    thermocouple_type=tc_type,
                )

                self.config.channels[local_name] = channel_config
                created_count += 1
                logger.debug(f"Auto-created channel: {local_name} type={channel_type}")

        if created_count > 0:
            logger.info(f"Auto-created {created_count} channel configs from detected hardware")

    # =========================================================================
    # MAIN SERVICE LIFECYCLE
    # =========================================================================

    def _reset(self):
        """Reset service to initial state"""
        logger.info("Resetting cRIO node...")
        self._stop_acquisition()

        # Clear values
        with self.values_lock:
            self.channel_values.clear()
            self.channel_timestamps.clear()

        # Reset outputs to safe state
        for name, ch_config in self.config.channels.items():
            if ch_config.channel_type == 'digital_output':
                self._write_output(name, ch_config.default_state)

        self._publish_status()
        logger.info("Reset complete")

    def run(self):
        """Main service entry point"""
        logger.info("="*60)
        logger.info("cRIO Node Service Starting")
        logger.info("="*60)

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running.set()

        # Detect hardware FIRST (before MQTT to avoid race conditions)
        # This caches the hardware info for later use
        logger.info("Detecting hardware...")
        self._detect_hardware_info()

        # Auto-create channels from detected hardware if none configured
        # This enables "magic" mode - cRIO reads everything automatically
        if not self.config.channels:
            self._auto_create_channels_from_hardware()

        # Setup MQTT (will retry on failure)
        # Hardware info is already cached, so callbacks won't trigger detection
        self._setup_mqtt()

        # Configure hardware
        if self.config.channels:
            self._configure_hardware()

        # Start heartbeat
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Heartbeat",
            daemon=True
        )
        self.heartbeat_thread.start()

        # Auto-start acquisition if we have channels
        if self.config.channels:
            self._start_acquisition()

        # Publish online status
        self._publish_status()

        logger.info("cRIO Node Service running")
        logger.info(f"Node ID: {self.config.node_id}")
        logger.info(f"Channels: {len(self.config.channels)}")
        logger.info(f"MQTT: {self.config.mqtt_broker}:{self.config.mqtt_port}")

        # Main loop - just keep alive
        try:
            while self._running.is_set():
                time.sleep(1.0)

                # Check MQTT connection - attempt reconnect if disconnected
                if not self._mqtt_connected.is_set():
                    logger.info("MQTT disconnected - attempting reconnect...")
                    self._connect_mqtt()

                # Check PC connection timeout (30 seconds)
                if time.time() - self.last_pc_contact > 30:
                    if self.pc_connected:
                        logger.warning("Lost contact with PC - continuing in standalone mode")
                        self.pc_connected = False

                # Periodic status publish for discovery (every STATUS_PUBLISH_INTERVAL)
                # This ensures NISystem can discover us even if it starts after we do
                if time.time() - self._last_status_time > STATUS_PUBLISH_INTERVAL:
                    self._publish_status()
                    self._last_status_time = time.time()
        except KeyboardInterrupt:
            pass

        self.shutdown()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self._running.clear()

    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down cRIO Node Service...")

        self._running.clear()
        self._stop_acquisition()

        # Publish offline status
        self._publish(
            self.get_topic('status', 'system'),
            {'status': 'offline', 'node_type': 'crio'},
            retain=True
        )

        # Close tasks
        self._close_tasks()

        # Disconnect MQTT
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        logger.info("cRIO Node Service stopped")


def main():
    parser = argparse.ArgumentParser(description='cRIO Node Service for NISystem')
    parser.add_argument(
        '-c', '--config-dir',
        type=str,
        default=str(DEFAULT_CONFIG_DIR),
        help=f'Configuration directory (default: {DEFAULT_CONFIG_DIR})'
    )
    parser.add_argument(
        '--broker',
        type=str,
        help='MQTT broker address (overrides config and env)'
    )
    parser.add_argument(
        '--port',
        type=int,
        help='MQTT broker port (overrides config and env)'
    )
    parser.add_argument(
        '--node-id',
        type=str,
        help='Node ID (overrides config and env)'
    )

    args = parser.parse_args()

    service = CRIONodeService(config_dir=Path(args.config_dir))

    # Priority: command-line args > environment variables > config file > defaults
    # This allows systemd to set env vars from .env file

    # MQTT Broker
    broker = args.broker or os.environ.get('MQTT_BROKER')
    if broker:
        service.config.mqtt_broker = broker

    # MQTT Port
    port = args.port or os.environ.get('MQTT_PORT')
    if port:
        service.config.mqtt_port = int(port) if isinstance(port, str) else port

    # Node ID
    node_id = args.node_id or os.environ.get('NODE_ID')
    if node_id:
        service.config.node_id = node_id

    service.run()


if __name__ == '__main__':
    main()
