#!/usr/bin/env python3
"""
DAQ Service for NISystem
Main service that reads/writes NI hardware (or simulation) and publishes to MQTT
"""

import json
import time
import signal
import sys
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import asdict

import paho.mqtt.client as mqtt

from config_parser import (
    load_config, load_config_safe, validate_config, NISystemConfig, ChannelConfig, ChannelType,
    get_input_channels, get_output_channels, ConfigValidationError, ValidationResult
)
from simulator import HardwareSimulator
from scheduler import SimpleScheduler
from device_discovery import DeviceDiscovery
from recording_manager import RecordingManager, RecordingConfig
from dependency_tracker import DependencyTracker, EntityType
from scaling import apply_scaling, get_scaling_info, validate_scaling_config

# Try to import nidaqmx - if not available, we'll use simulation only
try:
    import nidaqmx
    from nidaqmx.constants import TerminalConfiguration, ThermocoupleType as NI_TCType
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    print("nidaqmx not available - simulation mode only")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DAQService')


class DAQService:
    """Main DAQ Service class"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: Optional[NISystemConfig] = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self.simulator: Optional[HardwareSimulator] = None
        self.running = False

        # System state - controllable via MQTT
        self.acquiring = False          # Is data acquisition active
        self.recording = False          # Is data recording active
        self.recording_start_time: Optional[datetime] = None
        self.recording_filename: Optional[str] = None

        # Authentication state
        self.authenticated = False
        self.auth_username: Optional[str] = None
        self.AUTH_USERNAME = "admin"
        self.AUTH_PASSWORD = "gtiadmin"

        # Channel values cache
        self.channel_values: Dict[str, Any] = {}      # Scaled engineering values
        self.channel_raw_values: Dict[str, Any] = {}  # Raw values before scaling
        self.channel_timestamps: Dict[str, float] = {}

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.publish_thread: Optional[threading.Thread] = None

        # Locks
        self.values_lock = threading.Lock()

        # Data logging
        self.log_file = None
        self.log_lock = threading.Lock()

        # Safety state
        self.safety_triggered: Dict[str, bool] = {}
        self.safety_lock = threading.Lock()  # Lock for safety_triggered dict
        self.alarms_active: Dict[str, str] = {}

        # Config backup for rollback
        self._config_backup: Optional[NISystemConfig] = None
        self._config_path_backup: Optional[str] = None

        # Loop timing for status display
        self.last_scan_dt_ms = 0.0
        self.last_publish_dt_ms = 0.0

        # Scheduler for automated start/stop
        self.scheduler: Optional[SimpleScheduler] = None

        # Device discovery
        self.device_discovery = DeviceDiscovery()

        # Recording manager
        self.recording_manager: Optional[RecordingManager] = None

        # Dependency tracker
        self.dependency_tracker: Optional[DependencyTracker] = None

        self._load_config()
        self._init_scheduler()
        self._init_recording_manager()
        self._init_dependency_tracker()

    def _load_config(self, strict: bool = True):
        """Load and validate configuration from INI file

        Args:
            strict: If True, raises exception on critical validation errors
        """
        logger.info(f"Loading configuration from {self.config_path}")

        try:
            # Use the safe loader with validation
            config, validation = load_config_safe(self.config_path, strict=strict)
            self.config = config

            # Log validation results
            if validation.warnings:
                logger.warning(f"Configuration loaded with {len(validation.warnings)} warning(s)")
            if validation.errors:
                logger.error(f"Configuration has {len(validation.errors)} error(s)")

            # Initialize simulator if in simulation mode
            if self.config.system.simulation_mode or not NIDAQMX_AVAILABLE:
                logger.info("Initializing hardware simulator")
                self.simulator = HardwareSimulator(self.config)

            # Initialize channel values
            for name, channel in self.config.channels.items():
                if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[name] = channel.default_state
                elif channel.channel_type == ChannelType.ANALOG_OUTPUT:
                    self.channel_values[name] = channel.default_value
                else:
                    self.channel_values[name] = 0.0

            logger.info(f"Loaded {len(self.config.channels)} channels")

        except FileNotFoundError as e:
            logger.error(f"Configuration file not found: {e}")
            raise
        except ConfigValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

    def _init_scheduler(self):
        """Initialize the scheduler with callbacks"""
        self.scheduler = SimpleScheduler(
            start_callback=self._scheduled_start_acquire,
            stop_callback=self._scheduled_stop_acquire,
            start_record_callback=self._scheduled_start_record,
            stop_record_callback=self._scheduled_stop_record
        )
        logger.info("Scheduler initialized")

    def _init_recording_manager(self):
        """Initialize the recording manager"""
        self.recording_manager = RecordingManager(
            default_path=self.config.system.log_directory
        )
        self.recording_manager.on_status_change = self._publish_system_status
        logger.info("Recording manager initialized")

    def _init_dependency_tracker(self):
        """Initialize the dependency tracker"""
        self.dependency_tracker = DependencyTracker(self.config)
        logger.info("Dependency tracker initialized")

    def _scheduled_start_acquire(self):
        """Callback for scheduler to start acquisition"""
        if not self.acquiring:
            self.acquiring = True
            logger.info("Scheduler started acquisition")

    def _scheduled_stop_acquire(self):
        """Callback for scheduler to stop acquisition"""
        if self.acquiring:
            self.acquiring = False
            logger.info("Scheduler stopped acquisition")

    def _scheduled_start_record(self):
        """Callback for scheduler to start recording"""
        if not self.recording:
            self.recording = True
            self.recording_start_time = datetime.now()
            self.recording_filename = f"scheduled_{self.recording_start_time.strftime('%Y%m%d_%H%M%S')}.csv"
            logger.info(f"Scheduler started recording: {self.recording_filename}")

    def _scheduled_stop_record(self):
        """Callback for scheduler to stop recording"""
        if self.recording:
            self.recording = False
            if self.log_file:
                self.log_file.close()
                self.log_file = None
            logger.info("Scheduler stopped recording")

    def _setup_mqtt(self):
        """Setup MQTT connection"""
        logger.info(f"Connecting to MQTT broker at {self.config.system.mqtt_broker}:{self.config.system.mqtt_port}")

        # Use unique client ID and paho-mqtt v2 API
        import uuid
        client_id = f"daq_service_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

        try:
            self.mqtt_client.connect(
                self.config.system.mqtt_broker,
                self.config.system.mqtt_port,
                keepalive=60
            )
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        if reason_code == 0:
            logger.info("Connected to MQTT broker")

            # Subscribe to command topics
            base = self.config.system.mqtt_base_topic
            client.subscribe(f"{base}/commands/#")
            client.subscribe(f"{base}/config/reload")
            client.subscribe(f"{base}/simulation/event")

            # Subscribe to system control topics
            client.subscribe(f"{base}/system/acquire/start")
            client.subscribe(f"{base}/system/acquire/stop")
            client.subscribe(f"{base}/system/recording/start")
            client.subscribe(f"{base}/system/recording/stop")
            client.subscribe(f"{base}/system/status/request")

            # Subscribe to authentication topics
            client.subscribe(f"{base}/auth/login")
            client.subscribe(f"{base}/auth/logout")
            client.subscribe(f"{base}/auth/status/request")

            # Subscribe to config management topics
            client.subscribe(f"{base}/config/get")
            client.subscribe(f"{base}/config/save")
            client.subscribe(f"{base}/config/load")
            client.subscribe(f"{base}/config/list")
            client.subscribe(f"{base}/config/channel/update")

            # Subscribe to schedule topics
            client.subscribe(f"{base}/schedule/set")
            client.subscribe(f"{base}/schedule/enable")
            client.subscribe(f"{base}/schedule/disable")
            client.subscribe(f"{base}/schedule/status")

            # Subscribe to discovery topics
            client.subscribe(f"{base}/discovery/scan")

            # Subscribe to recording management topics
            client.subscribe(f"{base}/recording/config")
            client.subscribe(f"{base}/recording/config/get")
            client.subscribe(f"{base}/recording/list")
            client.subscribe(f"{base}/recording/delete")
            client.subscribe(f"{base}/recording/script-values")

            # Subscribe to dependency management topics
            client.subscribe(f"{base}/dependencies/check")
            client.subscribe(f"{base}/dependencies/delete")
            client.subscribe(f"{base}/dependencies/validate")
            client.subscribe(f"{base}/dependencies/orphans")

            # Publish connection status
            self._publish_system_status()

            # Publish channel configuration
            self._publish_channel_config()

        else:
            logger.error(f"MQTT connection failed with code {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT disconnection callback"""
        logger.warning(f"Disconnected from MQTT broker (rc={reason_code})")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        topic = msg.topic
        base = self.config.system.mqtt_base_topic

        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            payload = msg.payload.decode()

        logger.debug(f"Received message on {topic}: {payload}")

        # === SYSTEM CONTROL ===
        if topic == f"{base}/system/acquire/start":
            self._handle_acquire_start()
        elif topic == f"{base}/system/acquire/stop":
            self._handle_acquire_stop()
        elif topic == f"{base}/system/recording/start":
            self._handle_recording_start(payload)
        elif topic == f"{base}/system/recording/stop":
            self._handle_recording_stop()
        elif topic == f"{base}/system/status/request":
            self._publish_system_status()

        # === AUTHENTICATION ===
        elif topic == f"{base}/auth/login":
            self._handle_auth_login(payload)
        elif topic == f"{base}/auth/logout":
            self._handle_auth_logout()
        elif topic == f"{base}/auth/status/request":
            self._publish_auth_status()

        # === CONFIG MANAGEMENT ===
        elif topic == f"{base}/config/get":
            self._handle_config_get()
        elif topic == f"{base}/config/save":
            self._handle_config_save(payload)
        elif topic == f"{base}/config/load":
            self._handle_config_load(payload)
        elif topic == f"{base}/config/list":
            self._handle_config_list()
        elif topic == f"{base}/config/channel/update":
            self._handle_channel_update(payload)

        # === SCHEDULE MANAGEMENT ===
        elif topic == f"{base}/schedule/set":
            self._handle_schedule_set(payload)
        elif topic == f"{base}/schedule/enable":
            self._handle_schedule_enable()
        elif topic == f"{base}/schedule/disable":
            self._handle_schedule_disable()
        elif topic == f"{base}/schedule/status":
            self._publish_schedule_status()

        # === DEVICE DISCOVERY ===
        elif topic == f"{base}/discovery/scan":
            self._handle_discovery_scan()

        # === RECORDING MANAGEMENT ===
        elif topic == f"{base}/recording/config":
            self._handle_recording_config(payload)
        elif topic == f"{base}/recording/config/get":
            self._handle_recording_config_get()
        elif topic == f"{base}/recording/list":
            self._handle_recording_list()
        elif topic == f"{base}/recording/delete":
            self._handle_recording_delete(payload)
        elif topic == f"{base}/recording/script-values":
            self._handle_recording_script_values(payload)

        # === DEPENDENCY MANAGEMENT ===
        elif topic == f"{base}/dependencies/check":
            self._handle_dependency_check(payload)
        elif topic == f"{base}/dependencies/delete":
            self._handle_dependency_delete(payload)
        elif topic == f"{base}/dependencies/validate":
            self._handle_dependency_validate()
        elif topic == f"{base}/dependencies/orphans":
            self._handle_dependency_orphans()

        # === CHANNEL COMMANDS ===
        elif topic.startswith(f"{base}/commands/"):
            channel_name = topic.split('/')[-1]
            self._handle_command(channel_name, payload)

        # Handle legacy config reload
        elif topic == f"{base}/config/reload":
            logger.info("Reloading configuration...")
            self._load_config()
            self._publish_channel_config()

        # Handle simulation events (for testing)
        elif topic == f"{base}/simulation/event":
            if self.simulator:
                event_type = payload.get('event') if isinstance(payload, dict) else payload
                logger.info(f"Triggering simulation event: {event_type}")
                self.simulator.trigger_event(event_type)

    def _handle_command(self, channel_name: str, payload: Any):
        """Handle a command to write to a channel"""
        if channel_name not in self.config.channels:
            logger.warning(f"Unknown channel: {channel_name}")
            return

        channel = self.config.channels[channel_name]

        # Check if this is an output channel
        if channel.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT):
            logger.warning(f"Cannot write to input channel: {channel_name}")
            return

        # Extract value from payload
        if isinstance(payload, dict):
            value = payload.get('value')
        else:
            value = payload

        # Check safety interlocks
        if channel.safety_interlock:
            if not self._check_interlock(channel.safety_interlock):
                logger.warning(f"Safety interlock prevents write to {channel_name}")
                self._publish_alarm(channel_name, f"Interlock active: {channel.safety_interlock}")
                return

        # Write the value
        logger.info(f"Writing to {channel_name}: {value}")

        if self.simulator:
            self.simulator.write_channel(channel_name, value)

        # Update cache
        with self.values_lock:
            self.channel_values[channel_name] = value
            self.channel_timestamps[channel_name] = time.time()

        # Publish acknowledgment
        self._publish_channel_value(channel_name, value)

    def _check_interlock(self, interlock_expr: str) -> bool:
        """Evaluate a safety interlock expression safely (no eval)"""
        # Safe expression parser for interlocks like "e_stop_status == true AND temp < 1100"
        try:
            # Get channel values under lock
            with self.values_lock:
                values = dict(self.channel_values)

            # Parse and evaluate safely
            return self._safe_eval_interlock(interlock_expr, values)

        except Exception as e:
            logger.error(f"Failed to evaluate interlock '{interlock_expr}': {e}")
            return False  # Fail safe - don't allow write

    def _safe_eval_interlock(self, expr: str, values: Dict[str, Any]) -> bool:
        """
        Safely evaluate an interlock expression without using eval().

        Supports:
        - Comparisons: ==, !=, <, >, <=, >=
        - Logical operators: AND, OR, NOT
        - Parentheses for grouping
        - Channel names and literal values (numbers, true/false)
        """
        import re

        # Normalize expression
        expr = expr.strip()

        # Handle parentheses recursively
        while '(' in expr:
            # Find innermost parentheses
            match = re.search(r'\(([^()]+)\)', expr)
            if match:
                inner = match.group(1)
                result = self._safe_eval_interlock(inner, values)
                expr = expr[:match.start()] + str(result).lower() + expr[match.end():]
            else:
                break

        # Handle NOT operator
        if expr.strip().upper().startswith('NOT '):
            inner = expr.strip()[4:]
            return not self._safe_eval_interlock(inner, values)

        # Handle OR (lowest precedence)
        if ' OR ' in expr.upper():
            parts = re.split(r'\s+OR\s+', expr, flags=re.IGNORECASE)
            return any(self._safe_eval_interlock(p.strip(), values) for p in parts)

        # Handle AND
        if ' AND ' in expr.upper():
            parts = re.split(r'\s+AND\s+', expr, flags=re.IGNORECASE)
            return all(self._safe_eval_interlock(p.strip(), values) for p in parts)

        # At this point we should have a simple comparison
        # Supported operators: ==, !=, <=, >=, <, >
        operators = ['==', '!=', '<=', '>=', '<', '>']
        for op in operators:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = self._resolve_value(parts[0].strip(), values)
                    right = self._resolve_value(parts[1].strip(), values)
                    return self._compare(left, right, op)

        # No operator found - treat as boolean value
        return self._resolve_value(expr.strip(), values) == True

    def _resolve_value(self, token: str, values: Dict[str, Any]) -> Any:
        """Resolve a token to its value (channel name, number, or boolean)"""
        token = token.strip()

        # Check if it's a boolean literal
        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False

        # Check for special functions
        # active_outputs() - count of DO channels that are ON
        # active_outputs(pattern) - count of DO channels matching pattern that are ON
        if token.startswith('active_outputs('):
            return self._count_active_outputs(token, values)

        # sum(ch1, ch2, ch3) - sum of channel values
        if token.startswith('sum('):
            return self._sum_channels(token, values)

        # Check if it's a number
        try:
            if '.' in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        # Must be a channel name
        if token in values:
            return values[token]

        # Unknown token - log warning and return False for safety
        logger.warning(f"Unknown token in interlock expression: '{token}'")
        return False

    def _count_active_outputs(self, token: str, values: Dict[str, Any]) -> int:
        """
        Count active (ON) digital output channels.

        Syntax:
        - active_outputs() - count all active DO channels
        - active_outputs(valve) - count active DO channels containing 'valve' in name
        - active_outputs(Valve_*) - count active DO channels matching pattern

        Returns:
            Number of digital output channels that are currently ON (value > 0.5)
        """
        import re

        # Extract pattern from function call
        match = re.match(r'active_outputs\(([^)]*)\)', token)
        if not match:
            return 0

        pattern = match.group(1).strip().strip('"\'')

        count = 0
        for name, ch in self.config.channels.items():
            # Only count digital outputs
            if ch.channel_type != ChannelType.DIGITAL_OUTPUT:
                continue

            # Check if name matches pattern (if pattern provided)
            if pattern:
                # Support simple wildcard patterns
                if '*' in pattern:
                    regex_pattern = pattern.replace('*', '.*')
                    if not re.match(regex_pattern, name, re.IGNORECASE):
                        continue
                else:
                    # Simple substring match
                    if pattern.lower() not in name.lower():
                        continue

            # Check if the output is active (ON)
            if name in values and values[name] > 0.5:
                count += 1

        return count

    def _sum_channels(self, token: str, values: Dict[str, Any]) -> float:
        """
        Sum values of specified channels.

        Syntax:
        - sum(ch1, ch2, ch3) - sum of specific channels
        - sum(Valve_*) - sum of channels matching pattern

        Returns:
            Sum of channel values
        """
        import re

        # Extract channels from function call
        match = re.match(r'sum\(([^)]+)\)', token)
        if not match:
            return 0.0

        args = match.group(1).strip()

        total = 0.0

        # Check if it's a pattern or a list
        if '*' in args:
            # Pattern matching
            pattern = args.strip().strip('"\'')
            regex_pattern = pattern.replace('*', '.*')
            for name in values:
                if re.match(regex_pattern, name, re.IGNORECASE):
                    val = values[name]
                    if isinstance(val, (int, float, bool)):
                        total += float(val)
        else:
            # List of channel names
            channels = [c.strip() for c in args.split(',')]
            for ch_name in channels:
                if ch_name in values:
                    val = values[ch_name]
                    if isinstance(val, (int, float, bool)):
                        total += float(val)

        return total

    def _compare(self, left: Any, right: Any, op: str) -> bool:
        """Safely compare two values"""
        try:
            # Convert bools to int for numeric comparison if needed
            if isinstance(left, bool) and isinstance(right, (int, float)):
                left = int(left)
            if isinstance(right, bool) and isinstance(left, (int, float)):
                right = int(right)

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
        except TypeError as e:
            logger.error(f"Type error in comparison {left} {op} {right}: {e}")
            return False
        return False

    # =========================================================================
    # SYSTEM CONTROL HANDLERS
    # =========================================================================

    def _handle_acquire_start(self):
        """Start data acquisition"""
        if self.acquiring:
            logger.info("Acquisition already running")
            return

        logger.info("Starting data acquisition")
        self.acquiring = True
        self._publish_system_status()

    def _handle_acquire_stop(self):
        """Stop data acquisition"""
        if not self.acquiring:
            logger.info("Acquisition not running")
            return

        logger.info("Stopping data acquisition")
        self.acquiring = False

        # Also stop recording if active
        if self.recording:
            self._handle_recording_stop()

        self._publish_system_status()

    def _handle_recording_start(self, payload: Any):
        """Start data recording"""
        if not self.acquiring:
            logger.warning("Cannot start recording - acquisition not running")
            self._publish_recording_response(False, "Acquisition not running")
            return

        if self.recording_manager.recording:
            logger.info("Recording already active")
            self._publish_recording_response(False, "Recording already active")
            return

        # Get optional filename from payload
        filename = None
        if isinstance(payload, dict):
            filename = payload.get('filename')

            # Also apply any config from payload
            config_updates = {k: v for k, v in payload.items() if k != 'filename'}
            if config_updates:
                self.recording_manager.configure(config_updates)

        # Start recording via manager
        if self.recording_manager.start(filename):
            self.recording = True
            self.recording_start_time = self.recording_manager.recording_start_time
            self.recording_filename = self.recording_manager.current_file.name if self.recording_manager.current_file else None
            self._publish_recording_response(True, f"Recording started: {self.recording_filename}")
            self._publish_system_status()
        else:
            self._publish_recording_response(False, "Failed to start recording")

    def _handle_recording_stop(self):
        """Stop data recording"""
        if not self.recording_manager.recording:
            logger.info("Recording not active")
            self._publish_recording_response(False, "Recording not active")
            return

        # Stop recording via manager
        if self.recording_manager.stop():
            self.recording = False
            self.recording_start_time = None
            self.recording_filename = None
            self._publish_recording_response(True, "Recording stopped")
            self._publish_system_status()
        else:
            self._publish_recording_response(False, "Failed to stop recording")

    def _handle_recording_config(self, payload: Any):
        """Update recording configuration"""
        if not isinstance(payload, dict):
            self._publish_recording_response(False, "Invalid payload")
            return

        if self.recording_manager.configure(payload):
            self._publish_recording_response(True, "Recording configuration updated")
            self._publish_recording_config()
        else:
            self._publish_recording_response(False, "Cannot change config while recording")

    def _handle_recording_config_get(self):
        """Return current recording configuration"""
        self._publish_recording_config()

    def _handle_recording_list(self):
        """List recorded files"""
        base = self.config.system.mqtt_base_topic

        files = self.recording_manager.list_files()

        self.mqtt_client.publish(
            f"{base}/recording/list/response",
            json.dumps({
                "success": True,
                "files": files,
                "count": len(files),
                "timestamp": datetime.now().isoformat()
            })
        )

    def _handle_recording_delete(self, payload: Any):
        """Delete a recorded file"""
        if not isinstance(payload, dict):
            self._publish_recording_response(False, "Invalid payload")
            return

        filename = payload.get('filename')
        if not filename:
            self._publish_recording_response(False, "No filename specified")
            return

        if self.recording_manager.delete_file(filename):
            self._publish_recording_response(True, f"Deleted: {filename}")
            # Refresh file list
            self._handle_recording_list()
        else:
            self._publish_recording_response(False, f"Failed to delete: {filename}")

    def _handle_recording_script_values(self, payload: Any):
        """Update script-computed values for recording"""
        if not isinstance(payload, dict):
            return

        # Payload should be { "values": { "script_name": value, ... } }
        values = payload.get('values', payload)
        self.recording_manager.update_script_values(values)

    def _publish_recording_response(self, success: bool, message: str):
        """Publish recording operation response"""
        base = self.config.system.mqtt_base_topic

        self.mqtt_client.publish(
            f"{base}/recording/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    def _publish_recording_config(self):
        """Publish current recording configuration"""
        base = self.config.system.mqtt_base_topic

        config = self.recording_manager.get_config()
        status = self.recording_manager.get_status()

        self.mqtt_client.publish(
            f"{base}/recording/config/current",
            json.dumps({
                "config": config,
                "status": status,
                "timestamp": datetime.now().isoformat()
            }),
            retain=True
        )

    def _publish_system_status(self):
        """Publish comprehensive system status"""
        base = self.config.system.mqtt_base_topic

        # Get recording status from manager
        rec_status = self.recording_manager.get_status() if self.recording_manager else {}

        recording_duration = rec_status.get('recording_duration', 0)
        recording_duration_str = None
        if recording_duration > 0:
            hours, remainder = divmod(int(recording_duration), 3600)
            minutes, seconds = divmod(remainder, 60)
            recording_duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        status = {
            "status": "online",
            "timestamp": datetime.now().isoformat(),
            "simulation_mode": self.config.system.simulation_mode or not NIDAQMX_AVAILABLE,
            "acquiring": self.acquiring,
            "recording": rec_status.get('recording', self.recording),
            "recording_filename": rec_status.get('recording_filename', self.recording_filename),
            "recording_duration": recording_duration_str,
            "recording_duration_seconds": recording_duration,
            "recording_start_time": rec_status.get('recording_start_time'),
            "recording_bytes": rec_status.get('recording_bytes', 0),
            "recording_samples": rec_status.get('recording_samples', 0),
            "recording_mode": rec_status.get('recording_mode', 'manual'),
            "authenticated": self.authenticated,
            "auth_user": self.auth_username,
            "scheduler_enabled": self.scheduler.enabled if self.scheduler else False,
            "scan_rate_hz": self.config.system.scan_rate_hz,
            "publish_rate_hz": self.config.system.publish_rate_hz,
            "dt_scan_ms": round(self.last_scan_dt_ms, 2),
            "dt_publish_ms": round(self.last_publish_dt_ms, 2),
            "channel_count": len(self.config.channels),
            "config_path": self.config_path
        }

        self.mqtt_client.publish(
            f"{base}/status/system",
            json.dumps(status),
            retain=True,
            qos=1  # At least once delivery for status
        )

        # Also publish to legacy topic for backwards compatibility
        self.mqtt_client.publish(
            f"{base}/status/service",
            json.dumps({
                "status": "online",
                "timestamp": datetime.now().isoformat(),
                "simulation_mode": self.config.system.simulation_mode or not NIDAQMX_AVAILABLE
            }),
            retain=True,
            qos=1  # At least once delivery for status
        )

    # =========================================================================
    # AUTHENTICATION HANDLERS
    # =========================================================================

    def _handle_auth_login(self, payload: Any):
        """Handle login request"""
        if not isinstance(payload, dict):
            self._publish_auth_status(error="Invalid login payload")
            return

        username = payload.get('username', '')
        password = payload.get('password', '')

        if username == self.AUTH_USERNAME and password == self.AUTH_PASSWORD:
            logger.info(f"User '{username}' authenticated successfully")
            self.authenticated = True
            self.auth_username = username
            self._publish_auth_status()
            self._publish_system_status()
        else:
            logger.warning(f"Failed login attempt for user '{username}'")
            self.authenticated = False
            self.auth_username = None
            self._publish_auth_status(error="Invalid credentials")

    def _handle_auth_logout(self):
        """Handle logout request"""
        logger.info(f"User '{self.auth_username}' logged out")
        self.authenticated = False
        self.auth_username = None
        self._publish_auth_status()
        self._publish_system_status()

    def _publish_auth_status(self, error: Optional[str] = None):
        """Publish authentication status"""
        base = self.config.system.mqtt_base_topic

        status = {
            "authenticated": self.authenticated,
            "username": self.auth_username,
            "timestamp": datetime.now().isoformat()
        }

        if error:
            status["error"] = error

        self.mqtt_client.publish(
            f"{base}/auth/status",
            json.dumps(status),
            retain=True
        )

    # =========================================================================
    # CONFIG MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_config_get(self):
        """Return current configuration as JSON"""
        base = self.config.system.mqtt_base_topic

        config_data = self._config_to_dict()

        self.mqtt_client.publish(
            f"{base}/config/current",
            json.dumps(config_data)
        )

    def _handle_config_save(self, payload: Any):
        """Save current configuration to file"""
        if not self.authenticated:
            logger.warning("Config save rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Config save rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before saving config")
            return

        filename = "system.ini"
        if isinstance(payload, dict):
            filename = payload.get('filename', filename)

        try:
            config_dir = Path(self.config_path).parent
            save_path = config_dir / filename

            self._save_config_to_file(save_path)
            logger.info(f"Configuration saved to {save_path}")
            self._publish_config_response(True, f"Saved to {filename}")

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            self._publish_config_response(False, str(e))

    def _handle_config_load(self, payload: Any):
        """Load configuration from file with rollback support"""
        if not self.authenticated:
            logger.warning("Config load rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Config load rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before loading config")
            return

        filename = "system.ini"
        if isinstance(payload, dict):
            filename = payload.get('filename', filename)
        elif isinstance(payload, str):
            filename = payload

        try:
            config_dir = Path(self.config_path).parent
            load_path = config_dir / filename

            if not load_path.exists():
                self._publish_config_response(False, f"File not found: {filename}")
                return

            # Backup current config for rollback
            self._config_backup = self.config
            self._config_path_backup = self.config_path

            # Try to load and validate new config
            old_path = self.config_path
            self.config_path = str(load_path)

            try:
                self._load_config(strict=True)  # Strict validation
                self._publish_channel_config()
                logger.info(f"Configuration loaded from {load_path}")
                self._publish_config_response(True, f"Loaded {filename}")
                self._publish_system_status()

                # Clear backup on success
                self._config_backup = None
                self._config_path_backup = None

            except (ConfigValidationError, FileNotFoundError) as e:
                # Rollback to previous config
                logger.error(f"Config load failed, rolling back: {e}")
                self.config_path = self._config_path_backup
                self.config = self._config_backup
                self._config_backup = None
                self._config_path_backup = None
                self._publish_config_response(False, f"Validation failed, rolled back: {e}")

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            # Attempt rollback if we have backup
            if self._config_backup and self._config_path_backup:
                self.config_path = self._config_path_backup
                self.config = self._config_backup
                self._config_backup = None
                self._config_path_backup = None
                logger.info("Rolled back to previous configuration")
            self._publish_config_response(False, str(e))

    def _handle_config_list(self):
        """List available configuration files"""
        base = self.config.system.mqtt_base_topic
        config_dir = Path(self.config_path).parent

        configs = []
        for f in config_dir.glob("*.ini"):
            configs.append({
                "filename": f.name,
                "path": str(f),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "size": f.stat().st_size,
                "active": str(f) == self.config_path
            })

        self.mqtt_client.publish(
            f"{base}/config/list/response",
            json.dumps({"configs": configs})
        )

    def _handle_channel_update(self, payload: Any):
        """Update a single channel's configuration"""
        if not self.authenticated:
            logger.warning("Channel update rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Channel update rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before updating channels")
            return

        if not isinstance(payload, dict):
            self._publish_config_response(False, "Invalid payload")
            return

        channel_name = payload.get('channel')
        if not channel_name or channel_name not in self.config.channels:
            self._publish_config_response(False, f"Unknown channel: {channel_name}")
            return

        # Get the config sub-object (for structured payloads from dashboard)
        config_data = payload.get('config', payload)

        channel = self.config.channels[channel_name]

        # Handle channel rename
        new_name = config_data.get('new_name')
        if new_name and new_name != channel_name:
            if new_name in self.config.channels:
                self._publish_config_response(False, f"Channel '{new_name}' already exists")
                return
            # Rename the channel in config
            self.config.channels[new_name] = self.config.channels.pop(channel_name)
            channel = self.config.channels[new_name]
            channel.name = new_name

            # Update channel_values cache
            if channel_name in self.channel_values:
                self.channel_values[new_name] = self.channel_values.pop(channel_name)

            # Update recording config if it references this channel
            if hasattr(self, 'recording_manager') and self.recording_manager:
                rec_config = self.recording_manager.config
                if rec_config.trigger_channel == channel_name:
                    rec_config.trigger_channel = new_name
                if channel_name in rec_config.selected_channels:
                    rec_config.selected_channels = [
                        new_name if c == channel_name else c
                        for c in rec_config.selected_channels
                    ]

            # Update safety actions that reference this channel
            for action in self.config.safety_actions:
                if hasattr(action, 'actions') and action.actions:
                    action.actions = [
                        f"{new_name}:{val.split(':')[1]}" if act.startswith(f"{channel_name}:") else act
                        for act in action.actions
                        for val in [act]  # trick to use act in condition
                    ]

            logger.info(f"Renamed channel {channel_name} to {new_name}")
            channel_name = new_name

        # Update allowed fields (check both payload and config_data for backwards compatibility)
        if 'description' in config_data:
            channel.description = config_data['description']
        if 'units' in config_data:
            channel.units = config_data['units']
        if 'low_limit' in config_data:
            channel.low_limit = config_data['low_limit']
        if 'high_limit' in config_data:
            channel.high_limit = config_data['high_limit']
        if 'low_warning' in config_data:
            channel.low_warning = config_data['low_warning']
        if 'high_warning' in config_data:
            channel.high_warning = config_data['high_warning']
        if 'log' in config_data:
            channel.log = config_data['log']

        # Scaling parameters
        if 'scale_slope' in config_data:
            channel.scale_slope = float(config_data['scale_slope'])
        if 'scale_offset' in config_data:
            channel.scale_offset = float(config_data['scale_offset'])
        if 'scale_type' in config_data:
            channel.scale_type = config_data['scale_type']

        # 4-20mA scaling parameters
        if 'four_twenty_scaling' in config_data:
            channel.four_twenty_scaling = bool(config_data['four_twenty_scaling'])
        if 'eng_units_min' in config_data:
            channel.eng_units_min = float(config_data['eng_units_min']) if config_data['eng_units_min'] is not None else None
        if 'eng_units_max' in config_data:
            channel.eng_units_max = float(config_data['eng_units_max']) if config_data['eng_units_max'] is not None else None

        # Map scaling parameters
        if 'pre_scaled_min' in config_data:
            channel.pre_scaled_min = float(config_data['pre_scaled_min']) if config_data['pre_scaled_min'] is not None else None
        if 'pre_scaled_max' in config_data:
            channel.pre_scaled_max = float(config_data['pre_scaled_max']) if config_data['pre_scaled_max'] is not None else None
        if 'scaled_min' in config_data:
            channel.scaled_min = float(config_data['scaled_min']) if config_data['scaled_min'] is not None else None
        if 'scaled_max' in config_data:
            channel.scaled_max = float(config_data['scaled_max']) if config_data['scaled_max'] is not None else None

        # Thermocouple-specific parameters
        if 'tc_type' in config_data:
            from config_parser import ThermocoupleType
            try:
                channel.thermocouple_type = ThermocoupleType(config_data['tc_type'])
            except ValueError:
                logger.warning(f"Invalid thermocouple type: {config_data['tc_type']}")
        if 'cjc_source' in config_data:
            channel.cjc_source = config_data['cjc_source']

        # Voltage input parameters
        if 'voltage_range' in config_data:
            channel.voltage_range = float(config_data['voltage_range'])

        # Current input parameters
        if 'current_range_ma' in config_data:
            channel.current_range_ma = float(config_data['current_range_ma'])

        # Digital I/O parameters
        if 'invert' in config_data:
            channel.invert = bool(config_data['invert'])
        if 'default_state' in config_data:
            channel.default_state = bool(config_data['default_state'])
        if 'default_value' in config_data:
            channel.default_value = float(config_data['default_value'])

        # Safety parameters
        if 'safety_action' in config_data:
            channel.safety_action = config_data['safety_action'] if config_data['safety_action'] else None
        if 'safety_interlock' in config_data:
            channel.safety_interlock = config_data['safety_interlock'] if config_data['safety_interlock'] else None

        # Logging parameters
        if 'log_interval_ms' in config_data:
            channel.log_interval_ms = int(config_data['log_interval_ms'])

        # Validate scaling config
        is_valid, error_msg = validate_scaling_config(channel)
        if not is_valid:
            logger.warning(f"Scaling validation warning for {channel_name}: {error_msg}")

        logger.info(f"Updated channel {channel_name} (type: {channel.channel_type.value})")
        self._publish_channel_config()
        self._publish_config_response(True, f"Updated {channel_name}")

    # =========================================================================
    # DEVICE DISCOVERY HANDLERS
    # =========================================================================

    def _handle_discovery_scan(self):
        """Handle device discovery scan request"""
        logger.info("Starting device discovery scan...")
        base = self.config.system.mqtt_base_topic

        try:
            result = self.device_discovery.scan()

            # Publish discovery result
            self.mqtt_client.publish(
                f"{base}/discovery/result",
                json.dumps(result.to_dict()),
                qos=1
            )

            logger.info(f"Discovery complete: {result.message}")

            # Also publish available channels for easy access
            channels = self.device_discovery.get_available_channels()
            self.mqtt_client.publish(
                f"{base}/discovery/channels",
                json.dumps({"channels": channels}),
                qos=1
            )

        except Exception as e:
            logger.error(f"Discovery scan failed: {e}")
            self.mqtt_client.publish(
                f"{base}/discovery/result",
                json.dumps({
                    "success": False,
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }),
                qos=1
            )

    # =========================================================================
    # DEPENDENCY MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_dependency_check(self, payload: Any):
        """
        Check dependencies before deleting an entity.

        Payload: { "type": "channel|module|chassis|safety_action", "id": "entity_name" }
        Response: DependencyInfo with cascade_deletes and dependents
        """
        base = self.config.system.mqtt_base_topic

        if not isinstance(payload, dict):
            self._publish_dependency_response(False, "Invalid payload", None)
            return

        entity_type_str = payload.get("type", "")
        entity_id = payload.get("id", "")

        if not entity_type_str or not entity_id:
            self._publish_dependency_response(False, "Missing 'type' or 'id'", None)
            return

        try:
            entity_type = EntityType(entity_type_str)
        except ValueError:
            self._publish_dependency_response(
                False,
                f"Invalid entity type: {entity_type_str}. Use: chassis, module, channel, safety_action",
                None
            )
            return

        try:
            deps = self.dependency_tracker.get_dependencies(entity_type, entity_id)

            self.mqtt_client.publish(
                f"{base}/dependencies/check/response",
                json.dumps({
                    "success": True,
                    "dependencies": deps.to_dict(),
                    "timestamp": datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"Dependency check for {entity_type_str}:{entity_id} - {deps.total_affected} affected")

        except ValueError as e:
            self._publish_dependency_response(False, str(e), None)

    def _handle_dependency_delete(self, payload: Any):
        """
        Delete an entity with specified strategy.

        Payload: {
            "type": "channel|module|chassis|safety_action",
            "id": "entity_name",
            "strategy": "delete_only" | "delete_and_cleanup"
        }
        """
        base = self.config.system.mqtt_base_topic

        if not self.authenticated:
            self._publish_dependency_response(False, "Not authenticated", None)
            return

        if self.acquiring:
            self._publish_dependency_response(False, "Stop acquisition before deleting", None)
            return

        if not isinstance(payload, dict):
            self._publish_dependency_response(False, "Invalid payload", None)
            return

        entity_type_str = payload.get("type", "")
        entity_id = payload.get("id", "")
        strategy = payload.get("strategy", "")

        if not entity_type_str or not entity_id or not strategy:
            self._publish_dependency_response(False, "Missing 'type', 'id', or 'strategy'", None)
            return

        try:
            entity_type = EntityType(entity_type_str)
        except ValueError:
            self._publish_dependency_response(
                False,
                f"Invalid entity type: {entity_type_str}",
                None
            )
            return

        if strategy not in ("delete_only", "delete_and_cleanup"):
            self._publish_dependency_response(
                False,
                f"Invalid strategy: {strategy}. Use 'delete_only' or 'delete_and_cleanup'",
                None
            )
            return

        try:
            result = self.dependency_tracker.delete_with_strategy(entity_type, entity_id, strategy)

            self.mqtt_client.publish(
                f"{base}/dependencies/delete/response",
                json.dumps({
                    "success": result.success,
                    "result": result.to_dict(),
                    "timestamp": datetime.now().isoformat()
                }),
                qos=1
            )

            if result.success:
                logger.info(f"Deleted {entity_type_str}:{entity_id} with strategy={strategy}, "
                           f"deleted={len(result.deleted)}, orphaned={len(result.orphaned)}")
                # Refresh channel config after deletion
                self._publish_channel_config()
                # Also update channel_values cache
                for ref in result.deleted:
                    if ref.entity_type == EntityType.CHANNEL and ref.entity_id in self.channel_values:
                        del self.channel_values[ref.entity_id]
            else:
                logger.error(f"Delete failed: {result.errors}")

        except Exception as e:
            logger.error(f"Delete error: {e}")
            self._publish_dependency_response(False, str(e), None)

    def _handle_dependency_validate(self):
        """Validate config and return orphans/warnings"""
        base = self.config.system.mqtt_base_topic

        validation = self.dependency_tracker.validate_config()

        self.mqtt_client.publish(
            f"{base}/dependencies/validate/response",
            json.dumps({
                "success": True,
                "validation": validation,
                "timestamp": datetime.now().isoformat()
            }),
            qos=1
        )

    def _handle_dependency_orphans(self):
        """Get list of orphaned references in config"""
        base = self.config.system.mqtt_base_topic

        orphans = self.dependency_tracker.find_orphaned_references()

        # Convert EntityRef objects to dicts
        orphans_dict = {
            entity_id: [
                {"type": ref.entity_type.value, "id": ref.entity_id, "context": ref.context}
                for ref in refs
            ]
            for entity_id, refs in orphans.items()
        }

        self.mqtt_client.publish(
            f"{base}/dependencies/orphans/response",
            json.dumps({
                "success": True,
                "orphans": orphans_dict,
                "count": sum(len(refs) for refs in orphans.values()),
                "timestamp": datetime.now().isoformat()
            }),
            qos=1
        )

    def _publish_dependency_response(self, success: bool, message: str, data: Any):
        """Publish dependency operation response"""
        base = self.config.system.mqtt_base_topic

        response = {
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        if data:
            response["data"] = data

        self.mqtt_client.publish(
            f"{base}/dependencies/response",
            json.dumps(response),
            qos=1
        )

    # =========================================================================
    # SCHEDULE HANDLERS
    # =========================================================================

    def _handle_schedule_set(self, payload: Any):
        """Set schedule parameters"""
        if not isinstance(payload, dict):
            self._publish_schedule_response(False, "Invalid payload")
            return

        try:
            self.scheduler.configure(payload)
            self._publish_schedule_response(True, "Schedule configured")
            self._publish_schedule_status()
        except ValueError as e:
            self._publish_schedule_response(False, str(e))

    def _handle_schedule_enable(self):
        """Enable the schedule"""
        self.scheduler.enable()
        self._publish_schedule_response(True, "Schedule enabled")
        self._publish_schedule_status()

    def _handle_schedule_disable(self):
        """Disable the schedule"""
        self.scheduler.disable()
        self._publish_schedule_response(True, "Schedule disabled")
        self._publish_schedule_status()

    def _publish_schedule_status(self):
        """Publish current schedule status"""
        base = self.config.system.mqtt_base_topic

        status = self.scheduler.get_status()

        self.mqtt_client.publish(
            f"{base}/schedule/status/response",
            json.dumps(status),
            retain=True
        )

    def _publish_schedule_response(self, success: bool, message: str):
        """Publish schedule operation response"""
        base = self.config.system.mqtt_base_topic

        self.mqtt_client.publish(
            f"{base}/schedule/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    def _publish_config_response(self, success: bool, message: str):
        """Publish config operation response"""
        base = self.config.system.mqtt_base_topic

        self.mqtt_client.publish(
            f"{base}/config/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    def _config_to_dict(self) -> dict:
        """Convert current config to dictionary"""
        return {
            "system": {
                "mqtt_broker": self.config.system.mqtt_broker,
                "mqtt_port": self.config.system.mqtt_port,
                "mqtt_base_topic": self.config.system.mqtt_base_topic,
                "scan_rate_hz": self.config.system.scan_rate_hz,
                "publish_rate_hz": self.config.system.publish_rate_hz,
                "simulation_mode": self.config.system.simulation_mode,
                "log_directory": self.config.system.log_directory
            },
            "channels": {
                name: {
                    "module": ch.module,
                    "physical_channel": ch.physical_channel,
                    "channel_type": ch.channel_type.value,
                    "description": ch.description,
                    "units": ch.units,
                    # Linear scaling
                    "scale_slope": ch.scale_slope,
                    "scale_offset": ch.scale_offset,
                    "scale_type": ch.scale_type,
                    # 4-20mA scaling
                    "four_twenty_scaling": ch.four_twenty_scaling,
                    "eng_units_min": ch.eng_units_min,
                    "eng_units_max": ch.eng_units_max,
                    # Map scaling
                    "pre_scaled_min": ch.pre_scaled_min,
                    "pre_scaled_max": ch.pre_scaled_max,
                    "scaled_min": ch.scaled_min,
                    "scaled_max": ch.scaled_max,
                    # Limits
                    "low_limit": ch.low_limit,
                    "high_limit": ch.high_limit,
                    "low_warning": ch.low_warning,
                    "high_warning": ch.high_warning,
                    # Logging
                    "log": ch.log,
                    "log_interval_ms": ch.log_interval_ms,
                    # Thermocouple-specific
                    "thermocouple_type": ch.thermocouple_type.value if ch.thermocouple_type else None,
                    "cjc_source": ch.cjc_source,
                    # Ranges
                    "voltage_range": ch.voltage_range,
                    "current_range_ma": ch.current_range_ma,
                    # Digital I/O
                    "invert": ch.invert,
                    "default_state": ch.default_state,
                    "default_value": ch.default_value,
                    # Safety
                    "safety_action": ch.safety_action,
                    "safety_interlock": ch.safety_interlock,
                    # Include scaling info for UI display
                    "scaling_info": get_scaling_info(ch)
                }
                for name, ch in self.config.channels.items()
            },
            "modules": {
                name: {
                    "module_type": m.module_type,
                    "chassis": m.chassis,
                    "slot": m.slot,
                    "description": m.description
                }
                for name, m in self.config.modules.items()
            },
            "chassis": {
                name: {
                    "chassis_type": c.chassis_type,
                    "description": c.description
                }
                for name, c in self.config.chassis.items()
            }
        }

    def _save_config_to_file(self, path: Path):
        """Save current configuration to INI file"""
        import configparser

        config = configparser.ConfigParser()

        # System section
        config['system'] = {
            'mqtt_broker': self.config.system.mqtt_broker,
            'mqtt_port': str(self.config.system.mqtt_port),
            'mqtt_base_topic': self.config.system.mqtt_base_topic,
            'scan_rate_hz': str(self.config.system.scan_rate_hz),
            'publish_rate_hz': str(self.config.system.publish_rate_hz),
            'simulation_mode': str(self.config.system.simulation_mode).lower(),
            'log_directory': self.config.system.log_directory
        }

        # Chassis sections
        for name, chassis in self.config.chassis.items():
            config[f'chassis:{name}'] = {
                'type': chassis.chassis_type,
                'serial': chassis.serial,
                'connection': chassis.connection,
                'description': chassis.description,
                'enabled': str(chassis.enabled).lower()
            }

        # Module sections
        for name, module in self.config.modules.items():
            config[f'module:{name}'] = {
                'type': module.module_type,
                'chassis': module.chassis,
                'slot': str(module.slot),
                'description': module.description,
                'enabled': str(module.enabled).lower()
            }

        # Channel sections
        for name, ch in self.config.channels.items():
            section = {
                'module': ch.module,
                'physical_channel': ch.physical_channel,
                'channel_type': ch.channel_type.value,
                'description': ch.description,
                'units': ch.units,
                'log': str(ch.log).lower()
            }

            # Linear scaling
            if ch.scale_slope != 1.0:
                section['scale_slope'] = str(ch.scale_slope)
            if ch.scale_offset != 0.0:
                section['scale_offset'] = str(ch.scale_offset)
            if ch.scale_type != 'none':
                section['scale_type'] = ch.scale_type

            # 4-20mA scaling
            if ch.four_twenty_scaling:
                section['four_twenty_scaling'] = 'true'
            if ch.eng_units_min is not None:
                section['eng_units_min'] = str(ch.eng_units_min)
            if ch.eng_units_max is not None:
                section['eng_units_max'] = str(ch.eng_units_max)

            # Map scaling
            if ch.pre_scaled_min is not None:
                section['pre_scaled_min'] = str(ch.pre_scaled_min)
            if ch.pre_scaled_max is not None:
                section['pre_scaled_max'] = str(ch.pre_scaled_max)
            if ch.scaled_min is not None:
                section['scaled_min'] = str(ch.scaled_min)
            if ch.scaled_max is not None:
                section['scaled_max'] = str(ch.scaled_max)

            # Limits
            if ch.low_limit is not None:
                section['low_limit'] = str(ch.low_limit)
            if ch.high_limit is not None:
                section['high_limit'] = str(ch.high_limit)
            if ch.low_warning is not None:
                section['low_warning'] = str(ch.low_warning)
            if ch.high_warning is not None:
                section['high_warning'] = str(ch.high_warning)

            # Safety
            if ch.safety_action:
                section['safety_action'] = ch.safety_action
            if ch.safety_interlock:
                section['safety_interlock'] = ch.safety_interlock

            # Thermocouple-specific
            if ch.thermocouple_type:
                section['thermocouple_type'] = ch.thermocouple_type.value
            if ch.cjc_source != 'internal':
                section['cjc_source'] = ch.cjc_source

            # Ranges (only save if not default)
            if ch.voltage_range != 10.0:
                section['voltage_range'] = str(ch.voltage_range)
            if ch.current_range_ma != 20.0:
                section['current_range_ma'] = str(ch.current_range_ma)

            # Digital I/O
            if ch.invert:
                section['invert'] = 'true'
            if ch.default_state:
                section['default_state'] = 'true'
            if ch.default_value != 0.0:
                section['default_value'] = str(ch.default_value)

            # Logging interval (only save if not default)
            if ch.log_interval_ms != 1000:
                section['log_interval_ms'] = str(ch.log_interval_ms)

            config[f'channel:{name}'] = section

        # Safety action sections
        for name, action in self.config.safety_actions.items():
            actions_str = ', '.join(f"{k}:{v}" for k, v in action.actions.items())
            config[f'safety_action:{name}'] = {
                'description': action.description,
                'actions': actions_str,
                'trigger_alarm': str(action.trigger_alarm).lower(),
                'alarm_message': action.alarm_message
            }

        with open(path, 'w') as f:
            f.write("# NISystem Configuration File\n")
            f.write(f"# Saved: {datetime.now().isoformat()}\n")
            f.write(f"# By: {self.auth_username or 'system'}\n\n")
            config.write(f)

    def _publish_channel_config(self):
        """Publish channel configuration for Node-RED to discover"""
        base = self.config.system.mqtt_base_topic

        config_data = {
            "channels": {},
            "modules": {},
            "chassis": {},
            "safety_actions": {}
        }

        for name, channel in self.config.channels.items():
            config_data["channels"][name] = {
                "name": name,
                "module": channel.module,
                "physical_channel": channel.physical_channel,
                "type": channel.channel_type.value,
                "description": channel.description,
                "units": channel.units,
                "low_limit": channel.low_limit,
                "high_limit": channel.high_limit,
                "low_warning": channel.low_warning,
                "high_warning": channel.high_warning,
                "log": channel.log
            }

        for name, module in self.config.modules.items():
            config_data["modules"][name] = {
                "name": name,
                "type": module.module_type,
                "chassis": module.chassis,
                "slot": module.slot,
                "description": module.description
            }

        for name, chassis in self.config.chassis.items():
            config_data["chassis"][name] = {
                "name": name,
                "type": chassis.chassis_type,
                "description": chassis.description
            }

        self.mqtt_client.publish(
            f"{base}/config/channels",
            json.dumps(config_data),
            retain=True
        )

        logger.info("Published channel configuration")

    def _publish_channel_value(self, channel_name: str, value: Any):
        """Publish a single channel value with scaling info for validation"""
        try:
            base = self.config.system.mqtt_base_topic
            channel = self.config.channels[channel_name]

            # Convert bool to int for comparison
            numeric_value = float(value) if isinstance(value, (int, float)) else (1.0 if value else 0.0)

            # Get raw value if available
            raw_value = self.channel_raw_values.get(channel_name)

            payload = {
                "value": value,
                "timestamp": datetime.now().isoformat(),
                "units": channel.units,
                "quality": "good",
                "status": "normal"
            }

            # Include raw value and scaling info for validation/debugging
            if raw_value is not None and raw_value != value:
                payload["raw_value"] = raw_value
                scaling_info = get_scaling_info(channel)
                payload["scaling"] = {
                    "type": scaling_info['type'],
                    "applied": scaling_info['type'] != 'none'
                }

            # Check limits and add status (only for numeric channels with limits)
            if channel.low_limit is not None and channel.high_limit is not None:
                if numeric_value < channel.low_limit:
                    payload["status"] = "low_limit"
                    payload["quality"] = "alarm"
                elif numeric_value > channel.high_limit:
                    payload["status"] = "high_limit"
                    payload["quality"] = "alarm"
                elif channel.low_warning is not None and numeric_value < channel.low_warning:
                    payload["status"] = "low_warning"
                    payload["quality"] = "warning"
                elif channel.high_warning is not None and numeric_value > channel.high_warning:
                    payload["status"] = "high_warning"
                    payload["quality"] = "warning"

            self.mqtt_client.publish(
                f"{base}/channels/{channel_name}",
                json.dumps(payload)
            )
        except Exception as e:
            logger.error(f"Error publishing {channel_name}: {e}")

    def _publish_alarm(self, source: str, message: str):
        """Publish an alarm with QoS 1 for reliable delivery"""
        base = self.config.system.mqtt_base_topic

        payload = {
            "source": source,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "acknowledged": False,
            "active": True
        }

        self.mqtt_client.publish(
            f"{base}/alarms/{source}",
            json.dumps(payload),
            retain=True,
            qos=1  # At least once delivery for alarms
        )

        # Track active alarm
        self.alarms_active[source] = message

        logger.warning(f"ALARM: {source} - {message}")

    def _clear_alarm(self, source: str):
        """Clear an alarm"""
        base = self.config.system.mqtt_base_topic

        if source in self.alarms_active:
            del self.alarms_active[source]

            # Publish cleared state
            payload = {
                "source": source,
                "message": "",
                "timestamp": datetime.now().isoformat(),
                "acknowledged": True,
                "active": False
            }

            self.mqtt_client.publish(
                f"{base}/alarms/{source}",
                json.dumps(payload),
                retain=True,
                qos=1
            )

            logger.info(f"ALARM CLEARED: {source}")

    def _check_safety(self, channel_name: str, value: Any):
        """Check safety limits and trigger actions if needed (thread-safe)"""
        channel = self.config.channels[channel_name]

        if not channel.safety_action:
            return

        triggered = False

        # Check limits
        if channel.high_limit is not None and value > channel.high_limit:
            triggered = True
        elif channel.low_limit is not None and value < channel.low_limit:
            triggered = True

        # For digital inputs, check if value indicates unsafe condition
        if channel.channel_type == ChannelType.DIGITAL_INPUT:
            expected_safe = not channel.invert  # If not inverted, True is safe
            if value != expected_safe:
                triggered = True

        # Thread-safe access to safety_triggered dict
        should_execute = False
        should_clear = False

        with self.safety_lock:
            if triggered and channel_name not in self.safety_triggered:
                self.safety_triggered[channel_name] = True
                should_execute = True
            elif not triggered and channel_name in self.safety_triggered:
                del self.safety_triggered[channel_name]
                should_clear = True

        # Execute safety action outside lock
        if should_execute:
            self._execute_safety_action(channel.safety_action, channel_name)

        # Clear alarm when condition returns to normal
        if should_clear:
            self._clear_alarm(channel_name)
            logger.info(f"Safety condition cleared for {channel_name}")

    def _execute_safety_action(self, action_name: str, trigger_source: str):
        """Execute a safety action with full logging and verification"""
        if action_name not in self.config.safety_actions:
            logger.critical(
                f"SAFETY FAILURE: Unknown safety action '{action_name}' triggered by {trigger_source}! "
                f"This is a configuration error - safety response NOT executed!"
            )
            self._publish_alarm(
                trigger_source,
                f"CRITICAL: Safety action '{action_name}' not found - NO SAFETY RESPONSE!"
            )
            return

        action = self.config.safety_actions[action_name]
        logger.warning(f"SAFETY: Executing action '{action_name}' triggered by {trigger_source}")

        # Track execution results
        executed = []
        failed = []

        # Execute the actions
        for channel_name, value in action.actions.items():
            if channel_name in self.config.channels:
                try:
                    self._handle_command(channel_name, {"value": value, "source": "safety"})
                    executed.append(f"{channel_name}={value}")
                    logger.info(f"SAFETY: Set {channel_name} = {value}")
                except Exception as e:
                    failed.append(f"{channel_name}: {e}")
                    logger.error(f"SAFETY FAILURE: Failed to set {channel_name} = {value}: {e}")
            else:
                # CRITICAL: Log missing channel - this should never happen if config is validated
                failed.append(f"{channel_name}: channel not found")
                logger.critical(
                    f"SAFETY FAILURE: Action '{action_name}' references non-existent channel "
                    f"'{channel_name}' - THIS SAFETY COMMAND WAS SKIPPED!"
                )

        # Log execution summary
        if failed:
            logger.critical(
                f"SAFETY ACTION '{action_name}' INCOMPLETE! "
                f"Executed: {len(executed)}, Failed: {len(failed)} - {failed}"
            )
            # Publish alarm about incomplete safety action
            self._publish_alarm(
                f"safety_{action_name}",
                f"CRITICAL: Safety action incomplete! Failed: {', '.join(failed)}"
            )
        else:
            logger.warning(f"SAFETY: Action '{action_name}' completed - {len(executed)} commands executed")

        # Publish alarm if configured
        if action.trigger_alarm:
            self._publish_alarm(trigger_source, action.alarm_message)

    def _scan_loop(self):
        """Main scan loop - reads all inputs at scan rate"""
        scan_interval = 1.0 / self.config.system.scan_rate_hz
        logger.info(f"Starting scan loop at {self.config.system.scan_rate_hz} Hz")

        while self.running:
            start_time = time.time()

            # Only acquire data if acquiring flag is set
            if self.acquiring:
                try:
                    if self.simulator:
                        # Read raw values from simulator
                        raw_values = self.simulator.read_all()

                        # Apply scaling and update values under lock
                        with self.values_lock:
                            for name, raw_value in raw_values.items():
                                # Apply scaling based on channel configuration
                                if name in self.config.channels:
                                    channel = self.config.channels[name]
                                    scaled_value = apply_scaling(channel, raw_value)
                                    self.channel_values[name] = scaled_value
                                    # Store raw value for diagnostics
                                    self.channel_raw_values[name] = raw_value
                                else:
                                    self.channel_values[name] = raw_value
                                self.channel_timestamps[name] = start_time

                        # Check safety OUTSIDE the lock (using scaled values)
                        for name in raw_values:
                            if name in self.channel_values:
                                self._check_safety(name, self.channel_values[name])

                    else:
                        # Read from real hardware (TODO: implement nidaqmx reads)
                        pass

                except Exception as e:
                    logger.error(f"Error in scan loop: {e}")

            # Track loop timing
            elapsed = time.time() - start_time
            self.last_scan_dt_ms = elapsed * 1000

            # Sleep for remainder of scan interval
            sleep_time = max(0, scan_interval - elapsed)
            time.sleep(sleep_time)

    def _publish_loop(self):
        """Publish loop - publishes values at publish rate"""
        publish_interval = 1.0 / self.config.system.publish_rate_hz
        logger.info(f"Starting publish loop at {self.config.system.publish_rate_hz} Hz")

        publish_count = 0
        status_publish_counter = 0

        while self.running:
            start_time = time.time()

            # Only publish if acquiring
            if self.acquiring:
                try:
                    with self.values_lock:
                        values = dict(self.channel_values)

                    if publish_count == 0:
                        logger.info(f"Publishing {len(values)} channels")

                    for name, value in values.items():
                        self._publish_channel_value(name, value)

                    # Write to recording manager if recording
                    if self.recording_manager and self.recording_manager.recording:
                        # Build channel configs dict for units
                        channel_configs = {
                            name: {
                                'units': ch.units,
                                'description': ch.description
                            }
                            for name, ch in self.config.channels.items()
                        }
                        self.recording_manager.write_sample(values, channel_configs)

                    publish_count += 1

                except Exception as e:
                    import traceback
                    logger.error(f"Error in publish loop: {e}\n{traceback.format_exc()}")

            # Publish system status periodically (every ~1 second)
            status_publish_counter += 1
            if status_publish_counter >= self.config.system.publish_rate_hz:
                self._publish_system_status()
                status_publish_counter = 0

            # Track loop timing
            elapsed = time.time() - start_time
            self.last_publish_dt_ms = elapsed * 1000

            # Sleep for remainder of publish interval
            sleep_time = max(0, publish_interval - elapsed)
            time.sleep(sleep_time)

    def _log_value(self, channel_name: str, value: Any):
        """Log a value to file"""
        if self.log_file is None:
            log_dir = Path(self.config.system.log_directory)
            log_dir.mkdir(parents=True, exist_ok=True)

            log_path = log_dir / f"data_{datetime.now().strftime('%Y%m%d')}.csv"
            file_exists = log_path.exists()

            self.log_file = open(log_path, 'a')

            if not file_exists:
                # Write header
                self.log_file.write("timestamp,channel,value,units\n")

        with self.log_lock:
            channel = self.config.channels[channel_name]
            self.log_file.write(
                f"{datetime.now().isoformat()},{channel_name},{value},{channel.units}\n"
            )
            self.log_file.flush()

    def start(self):
        """Start the DAQ service"""
        logger.info("Starting DAQ Service...")

        self.running = True

        # Setup MQTT
        self._setup_mqtt()

        # Start scan thread
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.scan_thread.start()

        # Start publish thread
        self.publish_thread = threading.Thread(target=self._publish_loop, daemon=True)
        self.publish_thread.start()

        # Start scheduler
        if self.scheduler:
            self.scheduler.start()

        logger.info("DAQ Service started")

    def stop(self):
        """Stop the DAQ service"""
        logger.info("Stopping DAQ Service...")

        self.running = False

        # Stop scheduler
        if self.scheduler:
            self.scheduler.stop()

        if self.scan_thread:
            self.scan_thread.join(timeout=2.0)

        if self.publish_thread:
            self.publish_thread.join(timeout=2.0)

        if self.mqtt_client:
            base = self.config.system.mqtt_base_topic
            self.mqtt_client.publish(f"{base}/status/service", json.dumps({
                "status": "offline",
                "timestamp": datetime.now().isoformat()
            }), retain=True)
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        if self.log_file:
            self.log_file.close()

        logger.info("DAQ Service stopped")

    def run(self):
        """Run the service (blocking)"""
        self.start()

        # Handle signals
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep running
        while self.running:
            time.sleep(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='NISystem DAQ Service')
    parser.add_argument(
        '-c', '--config',
        default=str(Path(__file__).parent.parent.parent / "config" / "system.ini"),
        help='Path to configuration file'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    service = DAQService(args.config)
    service.run()


if __name__ == "__main__":
    main()
