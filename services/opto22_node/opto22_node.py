#!/usr/bin/env python3
"""
Opto22 Node Service for NISystem

Standalone service that runs ON the groov EPIC/RIO and:
1. Connects to NISystem PC's MQTT broker as a client
2. Receives configuration from NISystem and saves locally
3. Reads/writes I/O via local REST API
4. Continues running even if PC disconnects
5. Executes Python scripts pushed from NISystem

Architecture:
    NISystem PC                              groov EPIC/RIO
    ┌─────────────────┐      MQTT      ┌─────────────────────┐
    │  Dashboard      │◄──────────────►│  Opto22 Node Service│
    │  Backend        │   Config/Data   │  - Local config     │
    │  Project Mgmt   │                 │  - REST API I/O     │
    └─────────────────┘                 │  - Python scripts   │
                                        └─────────────────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ I/O Modules │
                                        │ (AI,AO,DI,DO)│
                                        └─────────────┘

Safe State Behavior:
- Software watchdog monitors scan loop
- If scan loop stops, outputs go to safe state
- PAC Control on groov EPIC provides additional hardware-level safety
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
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import argparse

# MQTT client
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

# HTTP client for REST API
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("WARNING: requests not available - install with: pip install requests")

# Try to import numpy for script support
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Opto22Node')

# Constants
DEFAULT_CONFIG_DIR = Path('/home/dev/nisystem')  # groov EPIC Linux path
DEFAULT_CONFIG_FILE = 'opto22_config.json'
WATCHDOG_TIMEOUT = 2.0  # seconds - outputs go safe if we don't pet watchdog
SAMPLE_RATE_HZ = 10
BUFFER_SIZE = 100
HEARTBEAT_INTERVAL = 2.0  # seconds
STATUS_PUBLISH_INTERVAL = 30.0  # seconds - periodic status for discovery

# Opto22 REST API endpoints (local)
OPTO22_API_BASE = "https://localhost"
OPTO22_ANALOG_INPUTS = "/api/v1/device/strategy/ios/analogInputs"
OPTO22_ANALOG_OUTPUTS = "/api/v1/device/strategy/ios/analogOutputs"
OPTO22_DIGITAL_INPUTS = "/api/v1/device/strategy/ios/digitalInputs"
OPTO22_DIGITAL_OUTPUTS = "/api/v1/device/strategy/ios/digitalOutputs"
OPTO22_SYSTEM_INFO = "/api/v1/device/info"
OPTO22_STRATEGY_VARS = "/api/v1/device/strategy/vars"


class AlarmState(Enum):
    """ISA-18.2 alarm states - evaluated locally on Opto22"""
    NORMAL = "normal"
    HI = "hi"           # Warning high
    HIHI = "hihi"       # Critical high (triggers safety action)
    LO = "lo"           # Warning low
    LOLO = "lolo"       # Critical low (triggers safety action)


@dataclass
class ChannelConfig:
    """Channel configuration matching NISystem format"""
    name: str
    physical_channel: str  # Opto22 path: module_index/channel_index
    channel_type: str  # analog_input, analog_output, digital_input, digital_output

    # Opto22-specific settings
    module_index: int = 0
    channel_index: int = 0

    # Output settings
    default_state: float = 0.0
    invert: bool = False

    # Scaling
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    engineering_units: str = ''

    # ISA-18.2 Alarm Configuration (matches PC daq_service)
    alarm_enabled: bool = False
    hihi_limit: Optional[float] = None       # Critical high (triggers safety action)
    hi_limit: Optional[float] = None         # Warning high
    lo_limit: Optional[float] = None         # Warning low
    lolo_limit: Optional[float] = None       # Critical low (triggers safety action)
    alarm_priority: str = 'medium'           # low, medium, high, critical
    alarm_deadband: float = 0.0              # Hysteresis to prevent alarm chatter
    alarm_delay_sec: float = 0.0             # Delay before alarm triggers

    # Safety settings (for autonomous operation)
    safety_action: Optional[str] = None      # Name of safety action to trigger on limit violation
    safety_interlock: Optional[str] = None   # Boolean expression that must be True for writes
    expected_state: Optional[bool] = None    # For digital inputs - expected safe state


@dataclass
class SafetyActionConfig:
    """
    Safety action configuration for autonomous Opto22 operation.

    When triggered, sets specified outputs to safe values.
    This runs locally on Opto22 without PC involvement.
    """
    name: str
    description: str = ""
    actions: Dict[str, Any] = field(default_factory=dict)  # channel_name -> safe_value
    trigger_alarm: bool = False
    alarm_message: str = ""


@dataclass
class SessionState:
    """
    Session state for autonomous operation.

    Tracks test session state locally on Opto22 so it continues
    even if PC disconnects.
    """
    active: bool = False
    start_time: Optional[float] = None
    name: str = ""
    operator: str = ""
    locked_outputs: List[str] = field(default_factory=list)  # Outputs locked during session
    timeout_minutes: float = 0  # Auto-stop after N minutes (0 = no timeout)


@dataclass
class Opto22Config:
    """Configuration for Opto22 node"""
    node_id: str = 'opto22-001'
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_base_topic: str = 'nisystem'
    mqtt_username: str = ''
    mqtt_password: str = ''

    # Opto22 REST API settings
    api_key: str = ''  # groov API key for authentication
    verify_ssl: bool = False  # Self-signed cert on localhost

    scan_rate_hz: float = 10.0
    publish_rate_hz: float = 4.0  # Rate at which to publish MQTT messages
    watchdog_timeout: float = 2.0

    channels: Dict[str, ChannelConfig] = field(default_factory=dict)
    scripts: List[Dict[str, Any]] = field(default_factory=list)
    safety_actions: Dict[str, SafetyActionConfig] = field(default_factory=dict)

    # Safe state outputs - which DO channels go LOW on watchdog expiry
    safe_state_outputs: List[str] = field(default_factory=list)


class Opto22NodeService:
    """
    Opto22 Node Service - runs independently on groov EPIC/RIO hardware
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / DEFAULT_CONFIG_FILE
        self.config: Optional[Opto22Config] = None

        # HTTP session for REST API
        self._http_session: Optional[requests.Session] = None

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

        # Watchdog
        self._watchdog_last_pet: float = 0.0
        self._watchdog_triggered: bool = False

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.watchdog_monitor_thread: Optional[threading.Thread] = None
        self._heartbeat_sequence = 0

        # Script execution
        self.scripts: Dict[str, Dict[str, Any]] = {}
        self.script_threads: Dict[str, threading.Thread] = {}

        # Safety state tracking (for autonomous operation)
        self.safety_triggered: Dict[str, bool] = {}  # channel_name -> triggered state
        self.safety_lock = threading.Lock()

        # Alarm state tracking (ISA-18.2 - evaluated locally on Opto22)
        self.alarm_states: Dict[str, AlarmState] = {}  # channel_name -> current alarm state
        self.alarm_lock = threading.Lock()

        # Session state (for autonomous operation)
        self.session = SessionState()

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
    # REST API ACCESS
    # =========================================================================

    def _create_http_session(self):
        """Create HTTP session for Opto22 REST API."""
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available")
            return

        self._http_session = requests.Session()
        self._http_session.verify = self.config.verify_ssl if self.config else False

        # Set API key header if configured
        if self.config and self.config.api_key:
            self._http_session.headers['apiKey'] = self.config.api_key

        self._http_session.headers['Content-Type'] = 'application/json'
        self._http_session.headers['Accept'] = 'application/json'

    def _api_get(self, endpoint: str) -> Optional[Any]:
        """Make GET request to Opto22 REST API."""
        if not self._http_session:
            self._create_http_session()

        try:
            url = f"{OPTO22_API_BASE}{endpoint}"
            response = self._http_session.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"API GET {endpoint} failed: {e}")
            return None

    def _api_put(self, endpoint: str, value: Any) -> bool:
        """Make PUT request to Opto22 REST API."""
        if not self._http_session:
            self._create_http_session()

        try:
            url = f"{OPTO22_API_BASE}{endpoint}"
            response = self._http_session.put(url, json=value, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"API PUT {endpoint} failed: {e}")
            return False

    def _read_channel_value(self, ch_config: ChannelConfig) -> Optional[float]:
        """Read a single channel via REST API."""
        if ch_config.channel_type == 'analog_input':
            endpoint = f"{OPTO22_ANALOG_INPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
        elif ch_config.channel_type == 'analog_output':
            endpoint = f"{OPTO22_ANALOG_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
        elif ch_config.channel_type == 'digital_input':
            endpoint = f"{OPTO22_DIGITAL_INPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
        elif ch_config.channel_type == 'digital_output':
            endpoint = f"{OPTO22_DIGITAL_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
        else:
            return None

        result = self._api_get(endpoint)
        if result is not None:
            try:
                raw_value = float(result) if not isinstance(result, bool) else (1.0 if result else 0.0)
                scaled = raw_value * ch_config.scale_slope + ch_config.scale_offset
                return scaled
            except (ValueError, TypeError):
                return None
        return None

    def _write_channel_value(self, ch_config: ChannelConfig, value: float) -> bool:
        """Write a value to an output channel via REST API."""
        # Reverse scaling
        if ch_config.scale_slope != 0:
            raw_value = (value - ch_config.scale_offset) / ch_config.scale_slope
        else:
            raw_value = value

        # Apply invert for digital outputs
        if ch_config.channel_type == 'digital_output':
            bool_value = raw_value > 0.5
            if ch_config.invert:
                bool_value = not bool_value
            endpoint = f"{OPTO22_DIGITAL_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
            return self._api_put(endpoint, bool_value)
        elif ch_config.channel_type == 'analog_output':
            endpoint = f"{OPTO22_ANALOG_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
            return self._api_put(endpoint, raw_value)
        return False

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

                # Parse safety actions
                safety_actions = {}
                for name, action_data in data.get('safety_actions', {}).items():
                    safety_actions[name] = SafetyActionConfig(**action_data)

                self.config = Opto22Config(
                    node_id=data.get('node_id', 'opto22-001'),
                    mqtt_broker=data.get('mqtt_broker', 'localhost'),
                    mqtt_port=data.get('mqtt_port', 1883),
                    mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
                    mqtt_username=data.get('mqtt_username', ''),
                    mqtt_password=data.get('mqtt_password', ''),
                    api_key=data.get('api_key', ''),
                    verify_ssl=data.get('verify_ssl', False),
                    scan_rate_hz=data.get('scan_rate_hz', 10.0),
                    publish_rate_hz=data.get('publish_rate_hz', 4.0),
                    watchdog_timeout=data.get('watchdog_timeout', 2.0),
                    channels=channels,
                    scripts=data.get('scripts', []),
                    safety_actions=safety_actions,
                    safe_state_outputs=data.get('safe_state_outputs', [])
                )
                logger.info(f"Loaded local config: {len(channels)} channels, "
                           f"{len(safety_actions)} safety actions")
            except Exception as e:
                logger.error(f"Failed to load local config: {e}")
                self.config = Opto22Config()
        else:
            logger.info("No local config found - waiting for config from NISystem")
            self.config = Opto22Config()

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
                'api_key': self.config.api_key,
                'verify_ssl': self.config.verify_ssl,
                'scan_rate_hz': self.config.scan_rate_hz,
                'publish_rate_hz': self.config.publish_rate_hz,
                'watchdog_timeout': self.config.watchdog_timeout,
                'channels': {name: asdict(ch) for name, ch in self.config.channels.items()},
                'scripts': self.config.scripts,
                'safety_actions': {name: asdict(action) for name, action in self.config.safety_actions.items()},
                'safe_state_outputs': self.config.safe_state_outputs
            }

            # Atomic write: write to temp file, then rename
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            temp_file.replace(self.config_file)
            logger.info(f"Saved config locally: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save local config: {e}")

    def _calculate_config_hash(self) -> str:
        """Calculate a hash of the current configuration for version tracking"""
        if not self.config:
            return ""

        config_data = {
            'channels': {name: asdict(ch) for name, ch in sorted(self.config.channels.items())},
            'safety_actions': {name: asdict(action) for name, action in sorted(self.config.safety_actions.items())},
            'watchdog_timeout': self.config.watchdog_timeout,
            'safe_state_outputs': sorted(self.config.safe_state_outputs)
        }

        config_json = json.dumps(config_data, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()

    def _validate_config(self) -> List[str]:
        """Validate configuration and return list of warnings/errors."""
        errors = []

        if not self.config:
            return ["No configuration loaded"]

        # Check safety action references
        for ch_name, ch_config in self.config.channels.items():
            if ch_config.safety_action:
                if ch_config.safety_action not in self.config.safety_actions:
                    errors.append(f"Channel '{ch_name}' references non-existent "
                                 f"safety action '{ch_config.safety_action}'")

        # Check safety action target channels exist
        for action_name, action in self.config.safety_actions.items():
            for target_ch in action.actions.keys():
                if target_ch not in self.config.channels:
                    errors.append(f"Safety action '{action_name}' targets "
                                 f"non-existent channel '{target_ch}'")
                else:
                    target_config = self.config.channels[target_ch]
                    if target_config.channel_type not in ('digital_output', 'analog_output'):
                        errors.append(f"Safety action '{action_name}' targets "
                                     f"non-output channel '{target_ch}'")

        return errors

    # =========================================================================
    # HARDWARE DETECTION
    # =========================================================================

    def _get_local_ip(self) -> str:
        """Get local IP address that can reach the MQTT broker"""
        if self.config and self.config.mqtt_broker:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                s.connect((self.config.mqtt_broker, self.config.mqtt_port))
                ip = s.getsockname()[0]
                s.close()
                if ip and ip != '0.0.0.0':
                    return ip
            except Exception:
                pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        return 'unknown'

    def _detect_hardware_info(self) -> Dict[str, Any]:
        """Detect groov EPIC/RIO hardware info for status reporting."""
        if self._hardware_info is not None:
            return self._hardware_info

        info = {
            'product_type': 'groov EPIC/RIO',
            'serial_number': '',
            'firmware_version': '',
            'device_name': '',
            'ip_address': '',
            'modules': []
        }

        # Try to get system info from REST API
        sys_info = self._api_get(OPTO22_SYSTEM_INFO)
        if sys_info:
            info['product_type'] = sys_info.get('productType', 'groov EPIC/RIO')
            info['serial_number'] = sys_info.get('serialNumber', '')
            info['firmware_version'] = sys_info.get('firmwareVersion', '')
            info['device_name'] = f"{info['product_type']}-{info['serial_number']}" if info['serial_number'] else info['product_type']

        # Enumerate I/O modules
        for io_type, endpoint, ch_type in [
            ('analogInputs', OPTO22_ANALOG_INPUTS, 'analog_input'),
            ('analogOutputs', OPTO22_ANALOG_OUTPUTS, 'analog_output'),
            ('digitalInputs', OPTO22_DIGITAL_INPUTS, 'digital_input'),
            ('digitalOutputs', OPTO22_DIGITAL_OUTPUTS, 'digital_output')
        ]:
            modules = self._api_get(endpoint)
            if modules and isinstance(modules, list):
                for i, mod in enumerate(modules):
                    if isinstance(mod, dict):
                        channels = []
                        mod_channels = mod.get('channels', [])
                        for j, ch in enumerate(mod_channels if isinstance(mod_channels, list) else []):
                            channels.append({
                                'name': f"{io_type}/{i}/ch{j}",
                                'display_name': ch.get('name', f"ch{j}") if isinstance(ch, dict) else f"ch{j}",
                                'channel_type': ch_type,
                                'module_index': i,
                                'channel_index': j
                            })

                        info['modules'].append({
                            'index': i,
                            'type': io_type,
                            'name': mod.get('name', f'{io_type}_{i}'),
                            'channel_count': len(channels),
                            'channels': channels
                        })

        # Count total channels
        total_channels = sum(len(m.get('channels', [])) for m in info['modules'])
        logger.info(f"Detected hardware: {info.get('device_name', info['product_type'])} with {len(info['modules'])} modules, {total_channels} channels")

        self._hardware_info = info
        return info

    # =========================================================================
    # MQTT TOPIC HELPERS
    # =========================================================================

    def get_topic_base(self) -> str:
        """Get node-prefixed topic base"""
        base = self.config.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.node_id if self.config else 'opto22-001'
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
            client_id=f"opto22-{self.config.node_id}",
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
            json.dumps({'status': 'offline', 'node_type': 'opto22'}),
            qos=1,
            retain=True
        )

        # Connect with retry
        self._connect_mqtt()

    def _connect_mqtt(self):
        """Connect to MQTT broker with infinite retry - never give up"""
        retry_delay = 2.0
        max_delay = 30.0
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

                if self._mqtt_connected.wait(timeout=10.0):
                    logger.info("MQTT connected successfully")
                    return True
                else:
                    logger.warning("MQTT connection timeout - will retry")
                    self.mqtt_client.loop_stop()
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt} failed: {e}")

            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

        return False

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connected callback"""
        if reason_code == 0:
            self._mqtt_connected.set()
            self.pc_connected = True
            self.last_pc_contact = time.time()

            # Subscribe to config and command topics
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic
            subscriptions = [
                (f"{base}/config/#", 1),
                (f"{base}/commands/#", 1),
                (f"{base}/script/#", 1),
                (f"{base}/system/#", 1),
                (f"{base}/safety/#", 1),
                (f"{base}/session/#", 1),
                (f"{mqtt_base}/discovery/ping", 1),
            ]
            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
                logger.debug(f"Subscribed to: {topic}")

            self._publish_status()
            logger.info("MQTT connected and subscribed")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnected callback"""
        self._mqtt_connected.clear()
        self.pc_connected = False
        logger.warning(f"MQTT disconnected (reason: {reason_code}) - will attempt reconnect")
        try:
            self.mqtt_client.loop_stop()
        except Exception as e:
            logger.debug(f"Error stopping MQTT loop on disconnect: {e}")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            self.last_pc_contact = time.time()
            self.pc_connected = True

            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic

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
            elif topic.startswith(f"{base}/safety/"):
                self._handle_safety_message(topic, payload)
            elif topic.startswith(f"{base}/session/"):
                self._handle_session_message(topic, payload)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_config_message(self, topic: str, payload: Dict[str, Any]):
        """Handle configuration updates from NISystem"""
        if topic.endswith('/full'):
            logger.info("Received full configuration update")

            try:
                # Parse channels
                channels = {}
                raw_channels = payload.get('channels', {})

                if isinstance(raw_channels, list):
                    for ch_data in raw_channels:
                        name = ch_data.get('name')
                        if name:
                            channels[name] = self._parse_channel_config(ch_data)
                else:
                    for name, ch_data in raw_channels.items():
                        channels[name] = self._parse_channel_config(ch_data)

                # Parse safety actions
                safety_actions = {}
                raw_safety = payload.get('safety_actions', {})
                for name, action_data in raw_safety.items():
                    safety_actions[name] = SafetyActionConfig(
                        name=name,
                        description=action_data.get('description', ''),
                        actions=action_data.get('actions', {}),
                        trigger_alarm=action_data.get('trigger_alarm', False),
                        alarm_message=action_data.get('alarm_message', '')
                    )

                # Update config
                self.config.channels = channels
                self.config.scripts = payload.get('scripts', [])
                self.config.safety_actions = safety_actions
                self.config.safe_state_outputs = payload.get('safe_state_outputs', [])
                self.config.watchdog_timeout = payload.get('watchdog_timeout', self.config.watchdog_timeout)

                # Calculate config hash
                config_hash = self._calculate_config_hash()
                self.config_version = config_hash
                self.config_timestamp = datetime.now(timezone.utc).isoformat()

                # Validate
                validation_errors = self._validate_config()
                if validation_errors:
                    for error in validation_errors:
                        logger.warning(f"Config validation: {error}")

                # Save locally
                self._save_local_config()

                # Clear safety triggered state
                with self.safety_lock:
                    self.safety_triggered.clear()

                # Publish acknowledgment
                self._publish(
                    self.get_topic('config', 'response'),
                    {
                        'status': 'ok',
                        'channels': len(channels),
                        'safety_actions': len(safety_actions),
                        'config_hash': config_hash,
                        'config_timestamp': self.config_timestamp,
                        'validation_warnings': validation_errors
                    }
                )
                logger.info(f"Config updated: {len(channels)} channels, "
                           f"{len(safety_actions)} safety actions, hash: {config_hash[:8]}...")

                # Auto-start acquisition
                if channels and not self._acquiring.is_set():
                    logger.info("Config received - auto-starting acquisition (Opto22 is PLC)")
                    self._start_acquisition()

            except Exception as e:
                logger.error(f"Config update failed: {e}")
                self._publish(
                    self.get_topic('config', 'response'),
                    {
                        'status': 'error',
                        'error': str(e),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                )

    def _parse_channel_config(self, ch_data: Dict[str, Any]) -> ChannelConfig:
        """Parse channel config from PC format to Opto22 format."""
        field_map = {
            'unit': 'engineering_units',
        }

        valid_fields = {
            'name', 'physical_channel', 'channel_type',
            'module_index', 'channel_index',
            'default_state', 'invert',
            'scale_slope', 'scale_offset', 'engineering_units',
            'alarm_enabled', 'hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit',
            'alarm_priority', 'alarm_deadband', 'alarm_delay_sec',
            'safety_action', 'safety_interlock', 'expected_state',
        }

        normalized = {}

        for key, value in ch_data.items():
            mapped_key = field_map.get(key, key)
            if mapped_key not in valid_fields:
                continue
            if value is None:
                continue
            normalized[mapped_key] = value

        # Parse physical_channel to extract module_index and channel_index
        phys_ch = normalized.get('physical_channel', '')
        if '/' in phys_ch:
            parts = phys_ch.split('/')
            try:
                normalized['module_index'] = int(parts[0]) if parts[0].isdigit() else 0
                normalized['channel_index'] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            except (ValueError, IndexError):
                pass

        # Enable alarms if any limits are set
        has_limits = any(normalized.get(f) is not None for f in ['hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit'])
        if has_limits and 'alarm_enabled' not in normalized:
            normalized['alarm_enabled'] = True

        # Ensure required fields
        if 'name' not in normalized:
            normalized['name'] = ''
        if 'physical_channel' not in normalized:
            normalized['physical_channel'] = ''
        if 'channel_type' not in normalized:
            normalized['channel_type'] = 'analog_input'

        return ChannelConfig(**normalized)

    def _handle_command_message(self, topic: str, payload: Dict[str, Any]):
        """Handle output commands from NISystem"""
        if topic.endswith('/commands/output'):
            channel_name = payload.get('channel', '')
            value = payload.get('value')
        else:
            parts = topic.split('/')
            channel_name = parts[-1] if len(parts) >= 2 else ''
            value = payload.get('value')

        if not channel_name:
            return

        if channel_name not in self.config.channels:
            logger.warning(f"Unknown output channel: {channel_name}")
            return

        ch_config = self.config.channels[channel_name]

        # Check session lock
        if self.session.active and channel_name in self.session.locked_outputs:
            logger.warning(f"SESSION LOCKS output {channel_name} - manual write blocked")
            self._publish(f"{self.get_topic_base()}/session/blocked", {
                'channel': channel_name,
                'requested_value': value,
                'reason': 'session_locked',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            return

        # Check interlock
        if ch_config.safety_interlock:
            if not self._check_interlock(ch_config.safety_interlock):
                logger.warning(f"INTERLOCK BLOCKS write to {channel_name}: {ch_config.safety_interlock}")
                self._publish_interlock_blocked(channel_name, ch_config.safety_interlock, value)
                return

        self._write_output(channel_name, value)
        logger.info(f"Output command: {channel_name} = {value}")

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

    def _handle_safety_message(self, topic: str, payload: Dict[str, Any]):
        """Handle safety-related MQTT commands"""
        if topic.endswith('/trigger'):
            self._handle_safety_trigger(payload)
        elif topic.endswith('/clear'):
            channel = payload.get('channel')
            if channel:
                with self.safety_lock:
                    if channel in self.safety_triggered:
                        del self.safety_triggered[channel]
                        logger.info(f"Cleared safety trigger state for {channel}")

    def _handle_session_message(self, topic: str, payload: Dict[str, Any]):
        """Handle session commands from NISystem"""
        if topic.endswith('/start'):
            self._start_session(payload)
        elif topic.endswith('/stop'):
            self._stop_session(payload.get('reason', 'command'))
        elif topic.endswith('/ping'):
            self.last_pc_contact = time.time()
            self._publish_session_status()

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def _start_session(self, payload: Dict[str, Any]):
        """Start a test session"""
        if self.session.active:
            logger.warning("Session already active - ignoring start command")
            return

        self.session.active = True
        self.session.start_time = time.time()
        self.session.name = payload.get('name', '')
        self.session.operator = payload.get('operator', '')
        self.session.locked_outputs = payload.get('locked_outputs', [])
        self.session.timeout_minutes = payload.get('timeout_minutes', 0)

        logger.info(f"SESSION STARTED: {self.session.name} by {self.session.operator}")
        logger.info(f"  Locked outputs: {self.session.locked_outputs}")

        self._publish_session_status()

    def _stop_session(self, reason: str = 'command'):
        """Stop the current session"""
        if not self.session.active:
            return

        duration = time.time() - (self.session.start_time or time.time())
        logger.info(f"SESSION STOPPED: {self.session.name} after {duration:.1f}s (reason: {reason})")

        self.session.active = False
        self.session.locked_outputs = []
        self.session.start_time = None

        self._publish_session_status()

    def _publish_session_status(self):
        """Publish session state"""
        self._publish(f"{self.get_topic_base()}/session/status", {
            'active': self.session.active,
            'name': self.session.name,
            'operator': self.session.operator,
            'start_time': self.session.start_time,
            'duration_s': time.time() - self.session.start_time if self.session.start_time else 0,
            'locked_outputs': self.session.locked_outputs,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _check_session_timeout(self):
        """Check if session has timed out (PC disconnect protection)"""
        if not self.session.active:
            return

        if self.session.timeout_minutes > 0 and self.session.start_time:
            elapsed = time.time() - self.session.start_time
            if elapsed > self.session.timeout_minutes * 60:
                logger.warning(f"Session timeout after {elapsed/60:.1f} minutes")
                self._stop_session('timeout')

    # =========================================================================
    # SAFETY SYSTEM
    # =========================================================================

    def _set_safe_state(self, reason: str = 'command'):
        """Set all outputs to safe state"""
        logger.info(f"Setting outputs to SAFE STATE - reason: {reason}")

        for channel_name, ch_config in self.config.channels.items():
            try:
                if ch_config.channel_type == 'digital_output':
                    self._write_output(channel_name, 0, source='safety')
                    logger.info(f"  DO {channel_name} -> 0 (OFF)")
                elif ch_config.channel_type == 'analog_output':
                    self._write_output(channel_name, 0.0, source='safety')
                    logger.info(f"  AO {channel_name} -> 0.0")
            except Exception as e:
                logger.error(f"  Failed to set {channel_name} safe: {e}")

        self._publish(f"{self.get_topic_base()}/status/safe-state", {
            'success': True,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _execute_safety_action(self, action_name: str, trigger_source: str):
        """Execute a named safety action"""
        if not self.config or action_name not in self.config.safety_actions:
            logger.critical(f"SAFETY FAILURE: Unknown safety action '{action_name}' "
                          f"triggered by {trigger_source}")
            return

        action = self.config.safety_actions[action_name]
        logger.warning(f"SAFETY: Executing action '{action_name}' triggered by {trigger_source}")

        executed = []
        failed = []

        for channel_name, safe_value in action.actions.items():
            if channel_name in self.config.channels:
                try:
                    success = self._write_output(channel_name, safe_value, source='safety')
                    if success:
                        executed.append(f"{channel_name}={safe_value}")
                        logger.info(f"  SAFETY: {channel_name} -> {safe_value}")
                    else:
                        failed.append(f"{channel_name}: write failed")
                except Exception as e:
                    failed.append(f"{channel_name}: {e}")
                    logger.error(f"  SAFETY FAILURE: {channel_name}: {e}")
            else:
                failed.append(f"{channel_name}: not found")
                logger.critical(f"  SAFETY FAILURE: Action references non-existent channel '{channel_name}'")

        if failed:
            logger.critical(f"SAFETY ACTION '{action_name}' INCOMPLETE! Failed: {failed}")

        self._publish(f"{self.get_topic_base()}/safety/triggered", {
            'action': action_name,
            'trigger_source': trigger_source,
            'executed': executed,
            'failed': failed,
            'success': len(failed) == 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

        if action.trigger_alarm and action.alarm_message:
            self._publish(f"{self.get_topic_base()}/alarms/active", {
                'channel': trigger_source,
                'type': 'SAFETY',
                'message': action.alarm_message,
                'action': action_name,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

    def _handle_safety_trigger(self, payload: Dict[str, Any]):
        """Handle manual safety trigger command from MQTT"""
        action_name = payload.get('action')
        reason = payload.get('reason', 'manual_command')

        if not action_name:
            logger.warning("Safety trigger received without action name")
            return

        logger.info(f"Manual safety trigger: {action_name} (reason: {reason})")
        self._execute_safety_action(action_name, f"manual:{reason}")

    def _check_safety_limits(self, channel_name: str, value: float):
        """Check ISA-18.2 safety limits and trigger action if needed."""
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.safety_action:
            return

        triggered = False
        trigger_reason = ""

        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            triggered = True
            trigger_reason = f"HIHI: {value:.2f} >= {ch_config.hihi_limit}"
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            triggered = True
            trigger_reason = f"LOLO: {value:.2f} <= {ch_config.lolo_limit}"

        if ch_config.channel_type == 'digital_input' and ch_config.expected_state is not None:
            actual_state = bool(value)
            if actual_state != ch_config.expected_state:
                triggered = True
                trigger_reason = f"DI unexpected: {actual_state} != expected {ch_config.expected_state}"

        with self.safety_lock:
            was_triggered = self.safety_triggered.get(channel_name, False)

            if triggered and not was_triggered:
                self.safety_triggered[channel_name] = True
                logger.warning(f"SAFETY LIMIT VIOLATION: {channel_name} - {trigger_reason}")
                self._execute_safety_action(ch_config.safety_action, channel_name)

            elif not triggered and was_triggered:
                del self.safety_triggered[channel_name]
                logger.info(f"Safety condition cleared: {channel_name}")
                self._publish(f"{self.get_topic_base()}/safety/cleared", {
                    'channel': channel_name,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })

    def _check_alarms(self, channel_name: str, value: float):
        """Evaluate ISA-18.2 alarms and publish alarm events."""
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.alarm_enabled:
            return

        deadband = ch_config.alarm_deadband if ch_config.alarm_deadband else 0.0

        new_state = AlarmState.NORMAL

        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            new_state = AlarmState.HIHI
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            new_state = AlarmState.LOLO
        elif ch_config.hi_limit is not None and value >= ch_config.hi_limit:
            new_state = AlarmState.HI
        elif ch_config.lo_limit is not None and value <= ch_config.lo_limit:
            new_state = AlarmState.LO

        with self.alarm_lock:
            prev_state = self.alarm_states.get(channel_name, AlarmState.NORMAL)

            if new_state != prev_state:
                if new_state == AlarmState.NORMAL and deadband > 0:
                    if prev_state in (AlarmState.HI, AlarmState.HIHI):
                        threshold = ch_config.hi_limit or ch_config.hihi_limit
                        if threshold and value > (threshold - deadband):
                            return
                    elif prev_state in (AlarmState.LO, AlarmState.LOLO):
                        threshold = ch_config.lo_limit or ch_config.lolo_limit
                        if threshold and value < (threshold + deadband):
                            return

                self.alarm_states[channel_name] = new_state
                self._publish_alarm_event(channel_name, prev_state, new_state, value)

                if new_state == AlarmState.NORMAL:
                    logger.info(f"ALARM CLEARED: {channel_name}")
                else:
                    severity = "CRITICAL" if new_state in (AlarmState.HIHI, AlarmState.LOLO) else "WARNING"
                    logger.warning(f"ALARM {severity}: {channel_name} - {new_state.value} at {value:.2f}")

    def _publish_alarm_event(self, channel: str, prev_state: AlarmState, new_state: AlarmState, value: float):
        """Publish alarm state change event"""
        ch_config = self.config.channels.get(channel)

        event = {
            'channel': channel,
            'previous_state': prev_state.value,
            'state': new_state.value,
            'value': value,
            'priority': ch_config.alarm_priority if ch_config else 'medium',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'node_id': self.config.node_id
        }

        if ch_config:
            if new_state == AlarmState.HIHI:
                event['limit'] = ch_config.hihi_limit
            elif new_state == AlarmState.HI:
                event['limit'] = ch_config.hi_limit
            elif new_state == AlarmState.LO:
                event['limit'] = ch_config.lo_limit
            elif new_state == AlarmState.LOLO:
                event['limit'] = ch_config.lolo_limit

        self._publish(f"{self.get_topic_base()}/alarms/event", event)

    # =========================================================================
    # INTERLOCK LOGIC
    # =========================================================================

    def _check_interlock(self, interlock_expr: str) -> bool:
        """Evaluate a safety interlock expression safely."""
        if not interlock_expr:
            return True

        try:
            with self.values_lock:
                values = dict(self.channel_values)

            return self._safe_eval_interlock(interlock_expr.strip(), values)

        except Exception as e:
            logger.error(f"Interlock evaluation failed: {e}")
            return False

    def _safe_eval_interlock(self, expr: str, values: Dict[str, float]) -> bool:
        """Recursive descent parser for interlock expressions."""
        expr = expr.strip()

        if expr.startswith('(') and expr.endswith(')'):
            depth = 0
            for i, c in enumerate(expr):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                if depth == 0 and i == len(expr) - 1:
                    return self._safe_eval_interlock(expr[1:-1], values)
                elif depth == 0 and i < len(expr) - 1:
                    break

        or_parts = self._split_by_operator(expr, ' OR ')
        if len(or_parts) > 1:
            return any(self._safe_eval_interlock(part, values) for part in or_parts)

        and_parts = self._split_by_operator(expr, ' AND ')
        if len(and_parts) > 1:
            return all(self._safe_eval_interlock(part, values) for part in and_parts)

        if expr.upper().startswith('NOT '):
            return not self._safe_eval_interlock(expr[4:], values)

        for op in ['<=', '>=', '!=', '==', '<', '>']:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = self._resolve_value(parts[0].strip(), values)
                    right = self._resolve_value(parts[1].strip(), values)

                    if op == '==':
                        return left == right
                    elif op == '!=':
                        return left != right
                    elif op == '<':
                        return left < right
                    elif op == '>':
                        return left > right
                    elif op == '<=':
                        return left <= right
                    elif op == '>=':
                        return left >= right

        value = self._resolve_value(expr, values)
        return bool(value)

    def _split_by_operator(self, expr: str, op: str) -> List[str]:
        """Split expression by operator, respecting parentheses"""
        parts = []
        depth = 0
        current = ""

        i = 0
        while i < len(expr):
            c = expr[i]

            if c == '(':
                depth += 1
                current += c
            elif c == ')':
                depth -= 1
                current += c
            elif depth == 0 and expr[i:].upper().startswith(op):
                parts.append(current.strip())
                current = ""
                i += len(op) - 1
            else:
                current += c
            i += 1

        if current.strip():
            parts.append(current.strip())

        return parts if len(parts) > 1 else [expr]

    def _resolve_value(self, token: str, values: Dict[str, float]) -> Any:
        """Resolve a token to its value"""
        token = token.strip()

        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False

        try:
            if '.' in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        if token in values:
            return values[token]

        logger.warning(f"Interlock: unknown token '{token}' - treating as False")
        return False

    def _publish_interlock_blocked(self, channel_name: str, interlock_expr: str, requested_value: Any):
        """Publish event when a write is blocked by interlock"""
        self._publish(f"{self.get_topic_base()}/interlock/blocked", {
            'channel': channel_name,
            'interlock': interlock_expr,
            'requested_value': requested_value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # =========================================================================
    # WATCHDOG
    # =========================================================================

    def _pet_watchdog(self):
        """Pet the software watchdog"""
        self._watchdog_last_pet = time.time()
        self._watchdog_triggered = False

    def _check_watchdog_timeout(self) -> bool:
        """Check if watchdog has expired"""
        if not self.config or self.config.watchdog_timeout <= 0:
            return False

        if self._watchdog_last_pet == 0:
            return False

        elapsed = time.time() - self._watchdog_last_pet

        if elapsed > self.config.watchdog_timeout:
            if not self._watchdog_triggered:
                logger.critical(
                    f"WATCHDOG TIMEOUT: {elapsed:.1f}s > {self.config.watchdog_timeout}s - "
                    f"TRIGGERING SAFE STATE"
                )
                self._watchdog_triggered = True
                self._set_safe_state("watchdog_timeout")

                self._publish(f"{self.get_topic_base()}/safety/watchdog", {
                    'event': 'timeout',
                    'elapsed_s': elapsed,
                    'timeout_s': self.config.watchdog_timeout,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return True

        return False

    def _watchdog_monitor_loop(self):
        """Independent watchdog monitor thread"""
        logger.info("Watchdog monitor thread started")

        check_interval = max(0.25, (self.config.watchdog_timeout / 4) if self.config else 0.5)

        while self._running.is_set():
            try:
                if self._acquiring.is_set():
                    self._check_watchdog_timeout()
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")

            time.sleep(check_interval)

        logger.info("Watchdog monitor thread stopped")

    # =========================================================================
    # DATA ACQUISITION
    # =========================================================================

    def _start_acquisition(self):
        """Start data acquisition"""
        if self._acquiring.is_set():
            logger.info("Acquisition already running")
            return

        logger.info("Starting acquisition...")
        self._acquiring.set()

        self.scan_thread = threading.Thread(
            target=self._scan_loop,
            name="ScanLoop",
            daemon=True
        )
        self.scan_thread.start()

        self._publish_status()
        logger.info("Acquisition started")

    def _stop_acquisition(self):
        """Stop data acquisition"""
        if not self._acquiring.is_set():
            return

        logger.info("Stopping acquisition...")
        self._acquiring.clear()

        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

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
                self._pet_watchdog()

                now = time.time()

                # Read all channels via REST API
                for channel_name, ch_config in self.config.channels.items():
                    try:
                        value = self._read_channel_value(ch_config)
                        if value is not None:
                            with self.values_lock:
                                self.channel_values[channel_name] = value
                                self.channel_timestamps[channel_name] = now
                    except Exception as e:
                        logger.warning(f"Error reading {channel_name}: {e}")

                # Include output values
                with self.values_lock:
                    for name, value in self.output_values.items():
                        self.channel_values[name] = value
                        self.channel_timestamps[name] = now

                # Publish at publish_rate_hz
                if now - self._last_publish_time >= publish_interval:
                    self._publish_channel_values()
                    self._last_publish_time = now

                # Check alarms and safety limits
                with self.values_lock:
                    values_snapshot = dict(self.channel_values)

                for ch_name, ch_value in values_snapshot.items():
                    try:
                        self._check_alarms(ch_name, ch_value)
                        self._check_safety_limits(ch_name, ch_value)
                    except Exception as e:
                        logger.error(f"Alarm/safety check error for {ch_name}: {e}")

            except Exception as e:
                logger.error(f"Scan loop error: {e}")

            elapsed = time.time() - loop_start
            sleep_time = scan_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Scan loop stopped")

    def _write_output(self, channel_name: str, value: Any, source: str = 'manual') -> bool:
        """Write to an output channel"""
        if channel_name not in self.config.channels:
            logger.warning(f"Output channel not found: {channel_name}")
            return False

        ch_config = self.config.channels[channel_name]

        if source != 'safety' and self.session.active and channel_name in self.session.locked_outputs:
            logger.warning(f"Write blocked - channel '{channel_name}' is session-locked")
            return False

        try:
            float_value = float(value) if value is not None else 0.0
            success = self._write_channel_value(ch_config, float_value)

            if success:
                self.output_values[channel_name] = float_value
                logger.debug(f"Wrote {channel_name} = {float_value}")

            return success

        except Exception as e:
            logger.error(f"Failed to write {channel_name}: {e}")
            return False

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def _start_script(self, script_id: str, max_runtime_seconds: float = 300.0):
        """Start executing a Python script with timeout"""
        if script_id not in self.scripts:
            logger.warning(f"Script not found: {script_id}")
            return

        script = self.scripts[script_id]

        if script_id in self.script_threads and self.script_threads[script_id].is_alive():
            logger.warning(f"Script already running: {script_id}")
            return

        script['_start_time'] = time.time()
        script['_max_runtime'] = max_runtime_seconds

        thread = threading.Thread(
            target=self._run_script,
            args=(script_id, script),
            name=f"Script-{script_id}",
            daemon=True
        )
        self.script_threads[script_id] = thread
        thread.start()

        monitor = threading.Thread(
            target=self._monitor_script_timeout,
            args=(script_id, max_runtime_seconds),
            name=f"ScriptMonitor-{script_id}",
            daemon=True
        )
        monitor.start()

        logger.info(f"Started script: {script_id} (max runtime: {max_runtime_seconds}s)")

    def _monitor_script_timeout(self, script_id: str, timeout_seconds: float):
        """Monitor script for timeout"""
        start_time = time.time()
        check_interval = 1.0

        while script_id in self.script_threads:
            thread = self.script_threads.get(script_id)
            if not thread or not thread.is_alive():
                return

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"SCRIPT TIMEOUT: {script_id} exceeded {timeout_seconds}s - forcing stop")
                if script_id in self.scripts:
                    self.scripts[script_id]['_stop_requested'] = True
                    self.scripts[script_id]['_timeout_exceeded'] = True

                time.sleep(2.0)

                if thread.is_alive():
                    logger.error(f"Script {script_id} did not respond to stop request after timeout")
                    self._publish(f"{self.get_topic_base()}/scripts/error", {
                        'script_id': script_id,
                        'error': f'Script timeout after {timeout_seconds}s - not responding to stop',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                return

            time.sleep(check_interval)
        self._publish_script_status()

    def _stop_script(self, script_id: str):
        """Stop a running script"""
        if script_id in self.script_threads:
            self.scripts[script_id]['_stop_requested'] = True
            logger.info(f"Stop requested for script: {script_id}")
            self._publish_script_status()

    def _run_script(self, script_id: str, script: Dict[str, Any]):
        """Execute a Python script with enhanced environment"""
        code = script.get('code', '')

        def wait_for(seconds: float) -> bool:
            """Sleep for given seconds, respecting stop request."""
            interval = 0.1
            elapsed = 0.0
            while elapsed < seconds:
                if script.get('_stop_requested', False):
                    return True
                time.sleep(min(interval, seconds - elapsed))
                elapsed += interval
            return False

        def wait_until(condition_fn, timeout: float = 60.0) -> bool:
            """Wait until condition returns True."""
            start = time.time()
            while time.time() - start < timeout:
                if script.get('_stop_requested', False):
                    return False
                if condition_fn():
                    return True
                time.sleep(0.1)
            return False

        env = {
            'tags': self._create_tags_api(),
            'outputs': self._create_outputs_api(),
            'publish': self._create_publish_api(),
            'session': self._create_session_api(),

            'next_scan': lambda: time.sleep(1.0 / self.config.scan_rate_hz),
            'wait_for': wait_for,
            'wait_until': wait_until,
            'should_stop': lambda: script.get('_stop_requested', False),

            'time': time,
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            'numpy': np if NUMPY_AVAILABLE else None,
            'np': np if NUMPY_AVAILABLE else None,

            'abs': abs,
            'all': all,
            'any': any,
            'bool': bool,
            'dict': dict,
            'enumerate': enumerate,
            'filter': filter,
            'float': float,
            'int': int,
            'len': len,
            'list': list,
            'map': map,
            'max': max,
            'min': min,
            'print': lambda *args: logger.info(f"[Script {script_id}] {' '.join(str(a) for a in args)}"),
            'range': range,
            'round': round,
            'set': set,
            'sorted': sorted,
            'str': str,
            'sum': sum,
            'tuple': tuple,
            'zip': zip,

            'trigger_safe_state': lambda reason='script': self._set_safe_state(reason),
            'execute_safety_action': lambda action, source='script': self._execute_safety_action(action, source),
            'check_interlock': self._check_interlock,

            '__builtins__': {},
        }

        try:
            code = code.replace('await ', '')
            exec(code, env, env)
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

            def set(self, name: str, value: Any) -> bool:
                return self._parent._write_output(name, value, source='script')

            def is_locked(self, name: str) -> bool:
                return self._parent.session.active and name in self._parent.session.locked_outputs

        return OutputsAPI(self)

    def _create_publish_api(self):
        """Create publish API for scripts"""
        def publish(name: str, value: Any):
            self._publish(
                self.get_topic('script', 'values'),
                {name: value}
            )
        return publish

    def _create_session_api(self):
        """Create session API for scripts"""
        class SessionAPI:
            def __init__(self, parent):
                self._parent = parent

            @property
            def active(self) -> bool:
                return self._parent.session.active

            @property
            def name(self) -> str:
                return self._parent.session.name

            @property
            def operator(self) -> str:
                return self._parent.session.operator

            @property
            def duration(self) -> float:
                if self._parent.session.start_time:
                    return time.time() - self._parent.session.start_time
                return 0.0

            def is_output_locked(self, channel: str) -> bool:
                return channel in self._parent.session.locked_outputs

        return SessionAPI(self)

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
        """Publish system status with hardware info"""
        hw_info = self._detect_hardware_info()
        status = {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'opto22',
            'node_id': self.config.node_id,
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ip_address': self._get_local_ip(),
            'product_type': hw_info['product_type'],
            'serial_number': hw_info['serial_number'],
            'firmware_version': hw_info.get('firmware_version', ''),
            'device_name': hw_info.get('device_name', ''),
            'modules': hw_info['modules'],
            'config_version': self.config_version,
            'config_timestamp': self.config_timestamp
        }
        self._publish(self.get_topic('status', 'system'), status, retain=True)

    def _publish_channel_values(self):
        """Publish channel values as batched message"""
        with self.values_lock:
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
        """Publish heartbeat"""
        self._heartbeat_sequence += 1
        self._publish(
            self.get_topic('heartbeat'),
            {
                'seq': self._heartbeat_sequence,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'acquiring': self._acquiring.is_set(),
                'pc_connected': self.pc_connected,
                'node_type': 'opto22',
                'node_id': self.config.node_id,
                'channels': len(self.config.channels),
            }
        )

    # =========================================================================
    # HEARTBEAT
    # =========================================================================

    def _heartbeat_loop(self):
        """Heartbeat thread"""
        while self._running.is_set():
            self._publish_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    # =========================================================================
    # AUTO-DISCOVERY
    # =========================================================================

    def _auto_create_channels_from_hardware(self):
        """Auto-create channel configs for all detected hardware channels."""
        hw_info = self._detect_hardware_info()

        created_count = 0
        for module in hw_info.get('modules', []):
            for ch in module.get('channels', []):
                ch_name = ch.get('name', '')
                if not ch_name:
                    continue

                if ch_name in self.config.channels:
                    continue

                channel_config = ChannelConfig(
                    name=ch_name,
                    physical_channel=f"{ch.get('module_index', 0)}/{ch.get('channel_index', 0)}",
                    channel_type=ch.get('channel_type', 'analog_input'),
                    module_index=ch.get('module_index', 0),
                    channel_index=ch.get('channel_index', 0),
                )

                self.config.channels[ch_name] = channel_config
                created_count += 1
                logger.debug(f"Auto-created channel: {ch_name} type={ch.get('channel_type')}")

        if created_count > 0:
            logger.info(f"Auto-created {created_count} channel configs from detected hardware")

    # =========================================================================
    # MAIN SERVICE LIFECYCLE
    # =========================================================================

    def _reset(self):
        """Reset service to initial state"""
        logger.info("Resetting Opto22 node...")
        self._stop_acquisition()

        with self.values_lock:
            self.channel_values.clear()
            self.channel_timestamps.clear()

        for name, ch_config in self.config.channels.items():
            if ch_config.channel_type in ('digital_output', 'analog_output'):
                self._write_output(name, ch_config.default_state)

        self._publish_status()
        logger.info("Reset complete")

    def run(self):
        """Main service entry point"""
        logger.info("="*60)
        logger.info("Opto22 Node Service Starting")
        logger.info("="*60)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running.set()

        # Create HTTP session for REST API
        self._create_http_session()

        # Detect hardware
        logger.info("Detecting hardware...")
        self._detect_hardware_info()

        # Auto-create channels if none configured
        if not self.config.channels:
            self._auto_create_channels_from_hardware()

        # Setup MQTT
        self._setup_mqtt()

        # Start heartbeat
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Heartbeat",
            daemon=True
        )
        self.heartbeat_thread.start()

        # Start watchdog monitor
        self.watchdog_monitor_thread = threading.Thread(
            target=self._watchdog_monitor_loop,
            name="WatchdogMonitor",
            daemon=True
        )
        self.watchdog_monitor_thread.start()

        # Auto-start acquisition if we have channels
        if self.config.channels:
            self._start_acquisition()

        self._publish_status()

        logger.info("Opto22 Node Service running")
        logger.info(f"Node ID: {self.config.node_id}")
        logger.info(f"Channels: {len(self.config.channels)}")
        logger.info(f"MQTT: {self.config.mqtt_broker}:{self.config.mqtt_port}")

        # Main loop
        try:
            while self._running.is_set():
                time.sleep(1.0)

                if not self._mqtt_connected.is_set():
                    logger.info("MQTT disconnected - attempting reconnect...")
                    self._connect_mqtt()

                if time.time() - self.last_pc_contact > 30:
                    if self.pc_connected:
                        logger.warning("Lost contact with PC - continuing in standalone mode")
                        self.pc_connected = False

                self._check_session_timeout()

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
        logger.info("Shutting down Opto22 Node Service...")

        self._running.clear()
        self._stop_acquisition()

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            logger.debug("Waiting for heartbeat thread to stop...")
            self.heartbeat_thread.join(timeout=3.0)

        if self.watchdog_monitor_thread and self.watchdog_monitor_thread.is_alive():
            logger.debug("Waiting for watchdog monitor thread to stop...")
            self.watchdog_monitor_thread.join(timeout=3.0)

        self._publish(
            self.get_topic('status', 'system'),
            {'status': 'offline', 'node_type': 'opto22'},
            retain=True
        )

        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        if self._http_session:
            self._http_session.close()

        logger.info("Opto22 Node Service stopped")


def main():
    parser = argparse.ArgumentParser(description='Opto22 Node Service for NISystem')
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
    parser.add_argument(
        '--api-key',
        type=str,
        help='groov API key (overrides config and env)'
    )

    args = parser.parse_args()

    service = Opto22NodeService(config_dir=Path(args.config_dir))

    # Priority: command-line args > environment variables > config file
    broker = args.broker or os.environ.get('MQTT_BROKER')
    if broker:
        service.config.mqtt_broker = broker

    port = args.port or os.environ.get('MQTT_PORT')
    if port:
        service.config.mqtt_port = int(port) if isinstance(port, str) else port

    node_id = args.node_id or os.environ.get('NODE_ID')
    if node_id:
        service.config.node_id = node_id

    api_key = args.api_key or os.environ.get('API_KEY')
    if api_key:
        service.config.api_key = api_key

    service.run()


if __name__ == '__main__':
    main()
