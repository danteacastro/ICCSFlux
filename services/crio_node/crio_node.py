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
from datetime import datetime
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
        AcquisitionType, Level, WatchdogAOExpirState, WatchdogCOExpirState
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
    mqtt_port: int = 1884
    mqtt_base_topic: str = 'nisystem'
    mqtt_username: str = ''
    mqtt_password: str = ''

    scan_rate_hz: float = 10.0
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
                    mqtt_port=data.get('mqtt_port', 1884),
                    mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
                    mqtt_username=data.get('mqtt_username', ''),
                    mqtt_password=data.get('mqtt_password', ''),
                    scan_rate_hz=data.get('scan_rate_hz', 10.0),
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
        """Connect to MQTT broker with retry"""
        max_retries = 5
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to MQTT broker {self.config.mqtt_broker}:{self.config.mqtt_port}...")
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
                    logger.warning("MQTT connection timeout")
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt+1} failed: {e}")

            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

        logger.error("Failed to connect to MQTT broker - running in standalone mode")
        return False

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connected callback"""
        if reason_code == 0:
            self._mqtt_connected.set()
            self.pc_connected = True
            self.last_pc_contact = time.time()

            # Subscribe to config and command topics
            base = self.get_topic_base()
            subscriptions = [
                (f"{base}/config/#", 1),      # Configuration updates
                (f"{base}/commands/#", 1),    # Output commands
                (f"{base}/script/#", 1),      # Script management
                (f"{base}/system/#", 1),      # System commands
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
        logger.warning(f"MQTT disconnected: {reason_code}")

        # Continue running - we have local config
        if self._running.is_set():
            logger.info("Continuing in standalone mode with local config")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            self.last_pc_contact = time.time()
            self.pc_connected = True

            # Route by topic
            base = self.get_topic_base()

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

            # Parse channels
            channels = {}
            for name, ch_data in payload.get('channels', {}).items():
                channels[name] = ChannelConfig(**ch_data)

            # Update config
            self.config.channels = channels
            self.config.scripts = payload.get('scripts', [])
            self.config.safe_state_outputs = payload.get('safe_state_outputs', [])

            # Save locally
            self._save_local_config()

            # Reconfigure hardware
            self._configure_hardware()

            # Publish acknowledgment
            self._publish(
                self.get_topic('config', 'response'),
                {'status': 'ok', 'channels': len(channels)}
            )

        elif topic.endswith('/channel/update'):
            # Single channel update
            channel_data = payload
            name = channel_data.get('name')
            if name:
                self.config.channels[name] = ChannelConfig(**channel_data)
                self._save_local_config()
                logger.info(f"Updated channel: {name}")

    def _handle_command_message(self, topic: str, payload: Dict[str, Any]):
        """Handle output commands from NISystem"""
        # Extract channel name from topic
        parts = topic.split('/')
        if len(parts) >= 2:
            channel_name = parts[-1]
            value = payload.get('value')

            if channel_name in self.output_tasks:
                self._write_output(channel_name, value)
                logger.debug(f"Command: {channel_name} = {value}")

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

        # Create input tasks
        if tc_channels:
            self._create_thermocouple_task(tc_channels)
        if voltage_channels:
            self._create_voltage_task(voltage_channels)
        if current_channels:
            self._create_current_task(current_channels)
        if di_channels:
            self._create_digital_input_task(di_channels)

        # Create output tasks with watchdog
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

                task.ai_channels.add_ai_thrmcpl_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=ch.name,
                    thermocouple_type=tc_type
                )
                channel_names.append(ch.name)
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
                term_config_map = {
                    'RSE': TerminalConfiguration.RSE,
                    'DIFF': TerminalConfiguration.DIFF,
                    'NRSE': TerminalConfiguration.NRSE,
                }
                term_config = term_config_map.get(ch.terminal_config.upper(), TerminalConfiguration.RSE)

                task.ai_channels.add_ai_voltage_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=ch.name,
                    terminal_config=term_config,
                    min_val=-ch.voltage_range,
                    max_val=ch.voltage_range
                )
                channel_names.append(ch.name)
                logger.info(f"Added voltage channel: {ch.name} -> {ch.physical_channel}")

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

                task.ai_channels.add_ai_current_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=ch.name,
                    min_val=0.0,
                    max_val=max_current,
                    shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
                )
                channel_names.append(ch.name)
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
                task.di_channels.add_di_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=ch.name
                )
                channel_names.append(ch.name)
                logger.info(f"Added DI channel: {ch.name} -> {ch.physical_channel}")

            self.input_tasks['digital_input'] = {
                'task': task,
                'reader': None,  # On-demand read for DI
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create DI task: {e}")

    def _create_digital_output_tasks(self, channels: List[ChannelConfig]):
        """Create digital output tasks (one per channel for independent control)"""
        for ch in channels:
            try:
                task = nidaqmx.Task(f"DO_{ch.name}")
                task.do_channels.add_do_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=ch.name
                )

                # Set initial state
                initial_state = ch.default_state
                if ch.invert:
                    initial_state = not initial_state
                task.write(initial_state)

                self.output_tasks[ch.name] = task
                self.output_values[ch.name] = 1.0 if initial_state else 0.0

                logger.info(f"Added DO channel: {ch.name} -> {ch.physical_channel} (initial={initial_state})")

            except Exception as e:
                logger.error(f"Failed to create DO task for {ch.name}: {e}")

    def _setup_watchdog(self, do_channels: List[ChannelConfig]):
        """
        Setup NI-DAQmx hardware watchdog for digital outputs.

        If the RT task stops petting the watchdog (crash, hang, etc.),
        the hardware automatically sets outputs to safe state (LOW).

        This is independent of the PC - purely hardware-level safety.
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

            # Create watchdog task
            self.watchdog_task = nidaqmx.Task('DO_Watchdog')

            # Configure watchdog expiration state (LOW = safe)
            for phys_chan in phys_channels:
                self.watchdog_task.do_channels.add_do_chan(phys_chan)

            # Set watchdog timeout
            self.watchdog_task.timing.watchdog_expir_time = self.config.watchdog_timeout

            # Start watchdog
            self.watchdog_task.start()

            logger.info(f"Hardware watchdog configured: timeout={self.config.watchdog_timeout}s, "
                       f"safe_outputs={safe_outputs}")

        except Exception as e:
            logger.error(f"Failed to setup watchdog: {e}")
            self.watchdog_task = None

    def _pet_watchdog(self):
        """
        Pet the hardware watchdog to prevent safe state trigger.
        Called in scan loop to indicate RT task is running normally.
        """
        if self.watchdog_task:
            try:
                # Clear the watchdog timer by committing the task
                self.watchdog_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
            except Exception as e:
                logger.warning(f"Watchdog pet failed: {e}")

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

                # Publish channel values
                self._publish_channel_values()

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
        """Write to a digital output channel"""
        if channel_name not in self.output_tasks:
            logger.warning(f"Output channel not found: {channel_name}")
            return False

        try:
            task = self.output_tasks[channel_name]
            ch_config = self.config.channels.get(channel_name)

            # Convert to boolean
            bool_value = bool(value) if not isinstance(value, bool) else value

            # Apply invert
            if ch_config and ch_config.invert:
                bool_value = not bool_value

            task.write(bool_value)
            self.output_values[channel_name] = 1.0 if bool_value else 0.0

            logger.debug(f"Wrote {channel_name} = {bool_value}")
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
        """Publish system status"""
        status = {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'crio',
            'node_id': self.config.node_id,
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels),
            'timestamp': datetime.utcnow().isoformat()
        }
        self._publish(self.get_topic('status', 'system'), status, retain=True)

    def _publish_channel_values(self):
        """Publish channel values to MQTT"""
        with self.values_lock:
            for name, value in self.channel_values.items():
                self._publish(
                    self.get_topic('channels', name),
                    {'value': value, 'timestamp': self.channel_timestamps.get(name, 0)}
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
                'timestamp': datetime.utcnow().isoformat(),
                'acquiring': self._acquiring.is_set(),
                'pc_connected': self.pc_connected
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

        # Setup MQTT (will retry on failure)
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

                # Check PC connection timeout (30 seconds)
                if time.time() - self.last_pc_contact > 30:
                    if self.pc_connected:
                        logger.warning("Lost contact with PC - continuing in standalone mode")
                        self.pc_connected = False
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
        help='MQTT broker address (overrides config)'
    )
    parser.add_argument(
        '--port',
        type=int,
        help='MQTT broker port (overrides config)'
    )
    parser.add_argument(
        '--node-id',
        type=str,
        help='Node ID (overrides config)'
    )

    args = parser.parse_args()

    service = CRIONodeService(config_dir=Path(args.config_dir))

    # Apply command-line overrides
    if args.broker:
        service.config.mqtt_broker = args.broker
    if args.port:
        service.config.mqtt_port = args.port
    if args.node_id:
        service.config.node_id = args.node_id

    service.run()


if __name__ == '__main__':
    main()
