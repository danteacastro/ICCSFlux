"""
cRIO Node V2 - Main Service Class

Simplified architecture with:
- Single main loop
- Command queue (MQTT never blocks)
- State machine for acquisition/session
- Hardware abstraction

The main loop follows the pattern:
1. Process pending commands
2. Read channels (if acquiring)
3. Check safety (single pass)
4. Publish values
"""

import json
import logging
import queue
import threading
import time
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List

from .state_machine import State, StateTransition
from .mqtt_interface import MQTTInterface, MQTTConfig
from .safety import SafetyManager, AlarmConfig, AlarmEvent, AlarmState
from .script_engine import ScriptEngine

# Use hardware.py (complete: counter, pulse, relay, module auto-detect, TC caching).
# hardware_v2 wraps daq_core but lacks counter/pulse/relay/auto-detect support.
from .hardware import HardwareInterface, HardwareConfig, create_hardware, DAQMX_AVAILABLE
from .config import ChannelConfig

logger = logging.getLogger('cRIONode')


@dataclass
class NodeConfig:
    """Complete node configuration."""
    node_id: str = "crio-001"
    device_name: str = "cRIO1"
    scan_rate_hz: float = 4.0
    publish_rate_hz: float = 4.0

    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "nisystem"

    heartbeat_interval_s: float = 5.0
    use_mock_hardware: bool = False

    # Watchdog output - toggles a digital output so external safety hardware
    # can detect the cRIO is alive. If the pulse stops, the relay trips.
    watchdog_output_channel: Optional[str] = None
    watchdog_output_rate_hz: float = 1.0
    watchdog_output_enabled: bool = False

    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeConfig':
        """Create config from dictionary."""
        channels = {}
        for name, ch_data in data.get('channels', {}).items():
            channels[name] = ChannelConfig.from_dict(name, ch_data)

        return cls(
            node_id=data.get('node_id', 'crio-001'),
            device_name=data.get('device_name', 'cRIO1'),
            scan_rate_hz=data.get('scan_rate_hz', 4.0),
            publish_rate_hz=data.get('publish_rate_hz', 4.0),
            mqtt_broker=data.get('mqtt_broker', data.get('mqtt_host', 'localhost')),
            mqtt_port=data.get('mqtt_port', 1883),
            mqtt_username=data.get('mqtt_username'),
            mqtt_password=data.get('mqtt_password'),
            mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
            heartbeat_interval_s=data.get('heartbeat_interval_s', 5.0),
            use_mock_hardware=data.get('use_mock_hardware', False),
            channels=channels
        )


@dataclass
class Command:
    """Queued command from MQTT."""
    topic: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class CRIONodeV2:
    """
    Simplified cRIO Node Service.

    Design principles:
    - Single main loop handles everything
    - Command queue - MQTT callbacks never block
    - State machine for acquisition/session
    - Hardware abstraction for testability
    """

    def __init__(self, config: NodeConfig):
        self.config = config

        # State machine
        self.state = StateTransition(State.IDLE)

        # Register state transition callbacks
        self.state.on_enter(State.ACQUIRING, self._on_enter_acquiring)
        self.state.on_exit(State.ACQUIRING, self._on_exit_acquiring)
        self.state.on_enter(State.SESSION, self._on_enter_session)
        self.state.on_exit(State.SESSION, self._on_exit_session)
        self.state.on_enter(State.IDLE, self._on_enter_idle)

        # Command queue - thread-safe, bounded
        self.command_queue: queue.Queue[Command] = queue.Queue(maxsize=1000)

        # Channel values
        self.channel_values: Dict[str, Dict[str, Any]] = {}
        self.output_values: Dict[str, float] = {}
        self.values_lock = threading.Lock()

        # Initialize output values from config defaults
        for name, ch in config.channels.items():
            if 'output' in ch.channel_type:
                self.output_values[name] = ch.default_value

        # Hardware interface
        hw_config = HardwareConfig(
            device_name=config.device_name,
            scan_rate_hz=config.scan_rate_hz,
            channels=config.channels
        )
        self.hardware = create_hardware(hw_config, config.use_mock_hardware)

        # MQTT interface
        mqtt_config = MQTTConfig(
            broker_host=config.mqtt_broker,
            broker_port=config.mqtt_port,
            username=config.mqtt_username,
            password=config.mqtt_password,
            client_id=config.node_id,
            base_topic=config.mqtt_base_topic,
            node_id=config.node_id
        )
        self.mqtt = MQTTInterface(mqtt_config)
        self.mqtt.on_message = self._enqueue_command
        self.mqtt.on_connection_change = self._on_mqtt_connection_change

        # Control flags
        self._shutdown = threading.Event()
        self._main_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Timing
        self._last_publish_time = 0.0
        self._last_heartbeat_time = 0.0
        self._publish_interval = 1.0 / config.publish_rate_hz
        self._scan_interval = 1.0 / config.scan_rate_hz

        logger.info(f"[CONFIG] scan_rate_hz={config.scan_rate_hz}, publish_rate_hz={config.publish_rate_hz}")

        # Config version (for DAQ sync)
        self.config_version = 0

        # Cached status data (modules/IP don't change at runtime)
        self._cached_modules = None
        self._cached_ip = None
        self.config_timestamp: Optional[str] = None

        # Safety manager (owns alarms)
        self.safety = SafetyManager()
        self.safety.on_alarm = self._on_alarm_event
        self.safety.on_action = self._on_safety_action
        self._configure_safety_from_channels()

        # Script engine
        self.script_engine = ScriptEngine(self)

        # Watchdog output toggle state
        self._watchdog_output_state = False
        self._watchdog_output_last_toggle = 0.0

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> bool:
        """Start the cRIO node service."""
        logger.info(f"Starting cRIO Node V2: {self.config.node_id}")

        # Connect MQTT
        if not self.mqtt.connect():
            logger.error("Failed to connect MQTT")
            return False

        # Wait for connection
        if not self.mqtt.wait_for_connection(timeout=10.0):
            logger.error("MQTT connection timeout")
            return False

        # Set up subscriptions
        self.mqtt.setup_standard_subscriptions()

        # Publish initial status
        self._publish_status()

        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Heartbeat",
            daemon=True
        )
        self._heartbeat_thread.start()

        # Start main loop thread
        self._main_thread = threading.Thread(
            target=self._main_loop,
            name="MainLoop",
            daemon=True
        )
        self._main_thread.start()

        logger.info("cRIO Node V2 started")
        return True

    def stop(self):
        """Stop the cRIO node service."""
        logger.info("Stopping cRIO Node V2...")

        # Stop all running scripts
        self.script_engine.stop_all()

        self._shutdown.set()

        # Transition to IDLE (stops hardware)
        self.state.to(State.IDLE)

        # Wait for threads
        if self._main_thread and self._main_thread.is_alive():
            self._main_thread.join(timeout=2.0)

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)

        # Disconnect MQTT
        self.mqtt.disconnect()

        logger.info("cRIO Node V2 stopped")

    def run(self):
        """Run service (blocking until shutdown)."""
        if not self.start():
            return

        try:
            while not self._shutdown.is_set():
                self._shutdown.wait(1.0)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self.stop()

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def _main_loop(self):
        """
        Main loop - the heart of the service.

        Pattern:
        1. Process all pending commands
        2. Read channels (if acquiring)
        3. Check safety (single pass)
        4. Publish values (rate-limited)
        """
        logger.info("Main loop started")
        _loop_count = 0

        _consecutive_errors = 0

        while not self._shutdown.is_set():
            loop_start = time.time()

            try:
                # 1. PROCESS ALL PENDING COMMANDS
                self._process_commands()

                # 2. READ CHANNELS (if acquiring)
                t_read_start = time.time()
                if self.state.is_acquiring:
                    self._read_channels()
                t_read_end = time.time()

                # 3. CHECK SAFETY (single pass)
                if self.state.is_acquiring:
                    self._check_safety()
                t_safety_end = time.time()

                # 4. WATCHDOG OUTPUT TOGGLE (if configured)
                if self.state.is_acquiring:
                    self._toggle_watchdog_output()

                # 5. PUBLISH VALUES (rate-limited)
                now = time.time()
                published = False
                if self.state.is_acquiring and (now - self._last_publish_time) >= self._publish_interval:
                    self._publish_values()
                    # Advance by interval (not now) to maintain steady cadence
                    # despite sleep jitter. Reset if we fell behind by >1 interval.
                    self._last_publish_time += self._publish_interval
                    if now - self._last_publish_time > self._publish_interval:
                        self._last_publish_time = now
                    published = True
                t_pub_end = time.time()

                _consecutive_errors = 0

            except Exception as e:
                _consecutive_errors += 1
                logger.error(f"[LOOP] Error in main loop: {e}", exc_info=(_consecutive_errors <= 3))
                # Avoid spamming logs on repeated failures
                if _consecutive_errors >= 10:
                    logger.critical(f"[LOOP] {_consecutive_errors} consecutive errors — stopping acquisition")
                    self.state.to(State.IDLE)
                    self._publish_status()
                    _consecutive_errors = 0
                # Set timing defaults so sleep still works after error
                t_read_end = t_read_start = t_safety_end = t_pub_end = time.time()
                published = False

        logger.info("Main loop stopped")

    def _heartbeat_loop(self):
        """Heartbeat loop - publish status periodically."""
        while not self._shutdown.is_set():
            self._publish_heartbeat()
            self._shutdown.wait(self.config.heartbeat_interval_s)

    # =========================================================================
    # COMMAND PROCESSING
    # =========================================================================

    def _enqueue_command(self, topic: str, payload: Dict[str, Any]):
        """
        MQTT callback - enqueue command for processing.
        IMPORTANT: This runs in paho's thread - must be non-blocking!
        """
        try:
            self.command_queue.put_nowait(Command(topic=topic, payload=payload))
        except queue.Full:
            logger.error("Command queue full! Dropping message")

    def _process_commands(self):
        """Process all queued commands."""
        while True:
            try:
                cmd = self.command_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_command(cmd.topic, cmd.payload)

    def _handle_command(self, topic: str, payload: Dict[str, Any]):
        """Route command to appropriate handler."""
        logger.info(f"[CMD] Received command: {topic}")
        logger.debug(f"[CMD] Payload: {payload}")

        # Extract command type from topic
        # Topics: {base}/nodes/{node_id}/{category}/{action}
        parts = topic.split('/')

        if '/system/' in topic:
            if 'acquire/start' in topic or topic.endswith('/start'):
                self._cmd_acquire_start(payload)
            elif 'acquire/stop' in topic or topic.endswith('/stop'):
                self._cmd_acquire_stop(payload)

        elif '/session/' in topic:
            if topic.endswith('/start'):
                self._cmd_session_start(payload)
            elif topic.endswith('/stop'):
                self._cmd_session_stop(payload)

        elif '/commands/' in topic:
            if '/output' in topic:
                self._cmd_write_output(payload)

        elif '/alarm/' in topic or '/alarms/' in topic:
            if '/ack' in topic or '/acknowledge' in topic:
                self._cmd_alarm_ack(payload)

        elif '/script/' in topic:
            self.script_engine.handle_command(topic, payload)

        elif '/config/' in topic:
            if '/full' in topic:
                self._cmd_config_full(payload)

        elif 'discovery/ping' in topic:
            self._publish_status()

    def _cmd_acquire_start(self, payload: Dict[str, Any]):
        """Handle acquire/start command."""
        logger.info("Command: acquire/start")
        request_id = payload.get('request_id', '')

        if self.state.state == State.IDLE:
            success = self.state.to(State.ACQUIRING)
            self._publish_system_command_ack('acquire/start', success, request_id=request_id)
        elif self.state.is_acquiring:
            # Already acquiring - success but no-op
            self._publish_system_command_ack('acquire/start', True,
                                              reason='Already acquiring', request_id=request_id)
        else:
            self._publish_system_command_ack('acquire/start', False,
                                              reason='Invalid state', request_id=request_id)

        self._publish_status()

    def _cmd_acquire_stop(self, payload: Dict[str, Any]):
        """Handle acquire/stop command."""
        logger.info("Command: acquire/stop")
        request_id = payload.get('request_id', '')

        if self.state.is_acquiring:
            success = self.state.to(State.IDLE)
            self._publish_system_command_ack('acquire/stop', success, request_id=request_id)
        else:
            self._publish_system_command_ack('acquire/stop', True,
                                              reason='Not acquiring', request_id=request_id)

        self._publish_status()

    def _cmd_session_start(self, payload: Dict[str, Any]):
        """Handle session/start command."""
        logger.info(f"Command: session/start - {payload}")
        request_id = payload.get('request_id', '')

        # Check pre-conditions: must be acquiring, check alarm requirements
        if self.state.state != State.ACQUIRING:
            self._publish_system_command_ack('session/start', False,
                                              reason='Must be acquiring to start session',
                                              request_id=request_id)
            return

        # Check alarm requirements if specified
        require_no_active = payload.get('require_no_active', False)
        require_no_latched = payload.get('require_no_latched', False)

        if require_no_active or require_no_latched:
            counts = self.safety.get_alarm_counts()
            if require_no_active and counts['active'] > 0:
                self._publish_system_command_ack('session/start', False,
                                                  reason=f"Active alarms present ({counts['active']})",
                                                  request_id=request_id)
                return
            if require_no_latched and counts['total'] > 0:
                self._publish_system_command_ack('session/start', False,
                                                  reason=f"Latched alarms present ({counts['total']})",
                                                  request_id=request_id)
                return

        success = self.state.to(State.SESSION, payload)
        self._publish_system_command_ack('session/start', success, request_id=request_id)
        self._publish_session_status()

    def _cmd_session_stop(self, payload: Dict[str, Any]):
        """Handle session/stop command."""
        logger.info("Command: session/stop")
        request_id = payload.get('request_id', '')

        if self.state.state == State.SESSION:
            success = self.state.to(State.ACQUIRING)
            self._publish_system_command_ack('session/stop', success, request_id=request_id)
        else:
            self._publish_system_command_ack('session/stop', True,
                                              reason='No active session', request_id=request_id)

        self._publish_session_status()

    def _cmd_write_output(self, payload: Dict[str, Any]):
        """Handle output write command."""
        channel = payload.get('channel', '')
        value = payload.get('value')

        if not channel or value is None:
            logger.warning(f"Invalid output command: {payload}")
            self._publish_command_ack(channel, False, "Missing channel or value")
            return

        # Check session lock
        if self.state.is_output_locked(channel):
            logger.warning(f"Output {channel} locked by session")
            self._publish_command_ack(channel, False, "Output locked by session")
            return

        # Write to hardware
        success = self.hardware.write_output(channel, value)

        if success:
            with self.values_lock:
                self.output_values[channel] = value
            logger.info(f"Output: {channel} = {value}")

        self._publish_command_ack(channel, success)

        # Publish updated value immediately
        if success:
            self._publish_single_channel(channel, value, 'output')

    def _cmd_alarm_ack(self, payload: Dict[str, Any]):
        """Handle alarm acknowledgment command."""
        channel = payload.get('channel', '')
        request_id = payload.get('request_id', '')

        if not channel:
            logger.warning("Alarm ack: missing channel")
            return

        logger.info(f"Command: alarm/ack - {channel}")
        success = self.acknowledge_alarm(channel)

        # Publish acknowledgment response
        self.mqtt.publish("alarms/ack/response", {
            'success': success,
            'channel': channel,
            'request_id': request_id,
            'timestamp': datetime.now().isoformat()
        })

    def _cmd_config_full(self, payload: Dict[str, Any]):
        """Handle full config push from DAQ."""
        logger.info("Command: config/full")

        # Update scan/publish rates if provided
        rate_changed = False
        if 'scan_rate_hz' in payload:
            new_rate = float(payload['scan_rate_hz'])
            if new_rate != self.config.scan_rate_hz:
                logger.info(f"Scan rate updated: {self.config.scan_rate_hz} Hz -> {new_rate} Hz")
                self.config.scan_rate_hz = new_rate
                self._scan_interval = 1.0 / new_rate
                # Update hardware config
                if self.hardware:
                    self.hardware.config.scan_rate_hz = new_rate
                rate_changed = True

        if 'publish_rate_hz' in payload:
            new_rate = float(payload['publish_rate_hz'])
            if new_rate != self.config.publish_rate_hz:
                logger.info(f"Publish rate updated: {self.config.publish_rate_hz} Hz -> {new_rate} Hz")
                self.config.publish_rate_hz = new_rate
                self._publish_interval = 1.0 / new_rate

        channels_data = payload.get('channels', {})

        # Handle both list and dict formats (backwards compatibility)
        if isinstance(channels_data, list):
            # Convert list to dict keyed by 'name' field
            channels_data = {ch.get('name'): ch for ch in channels_data if ch.get('name')}
            logger.debug(f"Converted channels list to dict: {len(channels_data)} channels")

        # Track if we need to reconfigure hardware
        was_acquiring = self.state.is_acquiring

        # Full config push replaces ALL channels (not merge)
        # This prevents duplicate physical channels when channel names differ
        old_channels = set(self.config.channels.keys())
        new_channels = set(channels_data.keys())
        channels_changed = old_channels != new_channels

        # Clear existing channels and replace with new ones
        self.config.channels.clear()

        # CRITICAL: Also clear channel_values to remove stale channel names
        # Otherwise old channels from startup config keep getting published
        with self.values_lock:
            self.channel_values.clear()

        for name, ch_data in channels_data.items():
            channel_type = ch_data.get('channel_type', 'analog_input')
            # Default thermocouple_type to 'K' for thermocouple channels if not specified
            tc_type = ch_data.get('thermocouple_type')
            if channel_type == 'thermocouple' and not tc_type:
                tc_type = 'K'

            self.config.channels[name] = ChannelConfig(
                name=name,
                physical_channel=ch_data.get('physical_channel', ''),
                channel_type=channel_type,
                # Scaling — linear
                scale_slope=ch_data.get('scale_slope', 1.0),
                scale_offset=ch_data.get('scale_offset', 0.0),
                scale_type=ch_data.get('scale_type', 'none'),
                # Scaling — 4-20mA
                four_twenty_scaling=ch_data.get('four_twenty_scaling', False),
                eng_units_min=float(ch_data['eng_units_min']) if ch_data.get('eng_units_min') is not None else None,
                eng_units_max=float(ch_data['eng_units_max']) if ch_data.get('eng_units_max') is not None else None,
                # Scaling — map
                pre_scaled_min=float(ch_data['pre_scaled_min']) if ch_data.get('pre_scaled_min') is not None else None,
                pre_scaled_max=float(ch_data['pre_scaled_max']) if ch_data.get('pre_scaled_max') is not None else None,
                scaled_min=float(ch_data['scaled_min']) if ch_data.get('scaled_min') is not None else None,
                scaled_max=float(ch_data['scaled_max']) if ch_data.get('scaled_max') is not None else None,
                # Hardware
                invert=ch_data.get('invert', False),
                default_value=ch_data.get('default_value', 0.0),
                thermocouple_type=tc_type,
                voltage_range=ch_data.get('voltage_range', 10.0),
                current_range_ma=ch_data.get('current_range_ma', 20.0),
                # Alarm configuration
                hihi_limit=ch_data.get('hihi_limit'),
                hi_limit=ch_data.get('hi_limit'),
                lo_limit=ch_data.get('lo_limit'),
                lolo_limit=ch_data.get('lolo_limit'),
                alarm_enabled=ch_data.get('alarm_enabled', False),
                alarm_deadband=ch_data.get('alarm_deadband', 0.0),
                alarm_delay_sec=ch_data.get('alarm_delay_sec', 0.0),
                # Resistance measurement
                resistance_range=ch_data.get('resistance_range', 1000.0),
                resistance_wiring=ch_data.get('resistance_wiring', '4-wire'),
                # Counter input
                counter_mode=ch_data.get('counter_mode', 'frequency'),
                counter_edge=ch_data.get('counter_edge', 'rising'),
                counter_min_freq=ch_data.get('counter_min_freq', 0.1),
                counter_max_freq=ch_data.get('counter_max_freq', 1000.0),
                # Pulse/counter output
                pulse_frequency=ch_data.get('pulse_frequency', 1000.0),
                pulse_duty_cycle=ch_data.get('pulse_duty_cycle', 50.0),
                pulse_idle_state=ch_data.get('pulse_idle_state', 'LOW'),
                # Relay
                relay_type=ch_data.get('relay_type', 'none'),
                momentary_pulse_ms=ch_data.get('momentary_pulse_ms', 0),
                safety_action=ch_data.get('safety_action')
            )

        # Update watchdog output config if provided
        wd = payload.get('watchdog_output')
        if wd and isinstance(wd, dict):
            self.config.watchdog_output_enabled = wd.get('enabled', False)
            self.config.watchdog_output_channel = wd.get('channel') or None
            self.config.watchdog_output_rate_hz = float(wd.get('rate_hz', 1.0))
            logger.info(f"Watchdog output: enabled={self.config.watchdog_output_enabled}, "
                        f"channel={self.config.watchdog_output_channel}, "
                        f"rate={self.config.watchdog_output_rate_hz} Hz")

        # Reconfigure safety manager with new alarm settings
        self.safety.clear_all()
        self._configure_safety_from_channels()

        # Update config version - echo from payload if provided (hash from DAQ service)
        # This ensures DAQ and cRIO agree on config version for validation
        if 'config_version' in payload:
            self.config_version = payload['config_version']
        else:
            # Fallback: increment local counter for backwards compatibility
            self.config_version = str(int(self.config_version or 0) + 1)
        self.config_timestamp = datetime.now().isoformat()

        # If acquiring and config changed, restart hardware to pick up new config
        if was_acquiring and (channels_changed or rate_changed):
            reason = "channels" if channels_changed else "scan rate"
            logger.info(f"Config changed ({reason}) while acquiring - restarting hardware")
            self.hardware.stop()
            self.hardware.start()

        # Save config to disk so it persists across restarts
        self._save_config_to_disk()

        # Acknowledge config receipt
        self._publish_config_response(True, "Config applied")

        logger.info(f"Config updated: {len(channels_data)} channels, version {self.config_version}")

    def _save_config_to_disk(self):
        """
        Save current config to disk for persistence.

        This ensures config pushed via MQTT persists across cRIO restarts.
        Config is saved to /home/admin/nisystem/crio_config.json
        """
        config_path = '/home/admin/nisystem/crio_config.json'

        try:
            # Build channel configs as dict - use getattr for all optional fields
            channels_dict = {}
            for name, ch in self.config.channels.items():
                channels_dict[name] = {
                    'name': getattr(ch, 'name', name),
                    'physical_channel': getattr(ch, 'physical_channel', ''),
                    'channel_type': getattr(ch, 'channel_type', 'voltage_input'),
                    'thermocouple_type': getattr(ch, 'thermocouple_type', 'K'),
                    'voltage_range': getattr(ch, 'voltage_range', 10.0),
                    'current_range_ma': getattr(ch, 'current_range_ma', 20.0),
                    'terminal_config': getattr(ch, 'terminal_config', 'RSE'),
                    'cjc_source': getattr(ch, 'cjc_source', 'BUILT_IN'),
                    'default_state': getattr(ch, 'default_state', False),
                    'invert': getattr(ch, 'invert', False),
                    'scale_slope': getattr(ch, 'scale_slope', 1.0),
                    'scale_offset': getattr(ch, 'scale_offset', 0.0),
                    'scale_type': getattr(ch, 'scale_type', 'none'),
                    'engineering_units': getattr(ch, 'engineering_units', ''),
                    'four_twenty_scaling': getattr(ch, 'four_twenty_scaling', False),
                    'eng_units_min': getattr(ch, 'eng_units_min', None),
                    'eng_units_max': getattr(ch, 'eng_units_max', None),
                    'pre_scaled_min': getattr(ch, 'pre_scaled_min', None),
                    'pre_scaled_max': getattr(ch, 'pre_scaled_max', None),
                    'scaled_min': getattr(ch, 'scaled_min', None),
                    'scaled_max': getattr(ch, 'scaled_max', None),
                    'alarm_enabled': getattr(ch, 'alarm_enabled', False),
                    'hihi_limit': getattr(ch, 'hihi_limit', None),
                    'hi_limit': getattr(ch, 'hi_limit', None),
                    'lo_limit': getattr(ch, 'lo_limit', None),
                    'lolo_limit': getattr(ch, 'lolo_limit', None),
                    'alarm_priority': getattr(ch, 'alarm_priority', 'medium'),
                    'alarm_deadband': getattr(ch, 'alarm_deadband', 0.0),
                    'alarm_delay_sec': getattr(ch, 'alarm_delay_sec', 0.0),
                    'alarm_high': getattr(ch, 'alarm_high', None),
                    'alarm_low': getattr(ch, 'alarm_low', None),
                    'safety_action': getattr(ch, 'safety_action', None),
                    'safety_interlock': getattr(ch, 'safety_interlock', None),
                    'expected_state': getattr(ch, 'expected_state', True)
                }

            # Build full config
            config_data = {
                'node_id': self.config.node_id,
                'mqtt_broker': self.config.mqtt_broker,
                'mqtt_port': self.config.mqtt_port,
                'mqtt_base_topic': self.config.mqtt_base_topic,
                'mqtt_username': getattr(self.config, 'mqtt_username', '') or '',
                'mqtt_password': getattr(self.config, 'mqtt_password', '') or '',
                'scan_rate_hz': self.config.scan_rate_hz,
                'publish_rate_hz': self.config.publish_rate_hz,
                'watchdog_timeout': getattr(self.config, 'watchdog_timeout', 2.0),
                'channels': channels_dict
            }

            # Write to file
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)

            logger.info(f"[CONFIG_PERSIST] Saved {len(channels_dict)} channels to {config_path}")

        except Exception as e:
            logger.error(f"[CONFIG_PERSIST] Failed to save config to disk: {e}")

    # =========================================================================
    # CHANNEL READING
    # =========================================================================

    def _read_channels(self):
        """Read all input channels from hardware."""
        readings = self.hardware.read_all()

        with self.values_lock:
            for channel, (value, timestamp) in readings.items():
                self.channel_values[channel] = {
                    'value': value,
                    'timestamp': timestamp,
                    'quality': 'good'
                }

    # =========================================================================
    # SAFETY & ALARMS (cRIO owns all alarm/safety state)
    # =========================================================================

    def _configure_safety_from_channels(self):
        """Configure SafetyManager from channel configs."""
        for name, ch in self.config.channels.items():
            if not getattr(ch, 'alarm_enabled', False):
                continue

            config = AlarmConfig(
                channel=name,
                enabled=True,
                hihi_limit=getattr(ch, 'hihi_limit', None),
                hi_limit=getattr(ch, 'hi_limit', None),
                lo_limit=getattr(ch, 'lo_limit', None),
                lolo_limit=getattr(ch, 'lolo_limit', None),
                deadband=getattr(ch, 'alarm_deadband', 0.0),
                delay_seconds=getattr(ch, 'alarm_delay_sec', 0.0),
                safety_action=getattr(ch, 'safety_action', None)
            )
            self.safety.configure(name, config)
            logger.debug(f"Configured alarm for {name}")

    def _check_safety(self):
        """
        Single-pass safety check using SafetyManager.
        Also checks session timeout.
        """
        # Get current values
        with self.values_lock:
            values_snapshot = {ch: data.get('value', 0)
                              for ch, data in self.channel_values.items()}

        # Check alarms (SafetyManager handles state, actions, callbacks)
        self.safety.check_all(values_snapshot)

    def _on_alarm_event(self, event: AlarmEvent):
        """Callback when alarm state changes."""
        logger.warning(f"Alarm {event.alarm_type.upper()}: {event.channel} = {event.value:.2f} "
                      f"(limit: {event.limit})")

        # Publish alarm event
        self.mqtt.publish("alarms/event", {
            'channel': event.channel,
            'alarm_type': event.alarm_type,
            'value': event.value,
            'limit': event.limit,
            'severity': event.severity.name,
            'state': event.state.name,
            'timestamp': datetime.now().isoformat()
        })

        # Publish updated alarm summary
        self._publish_alarm_status()

    def _on_safety_action(self, channel: str, action: str, value: float):
        """Callback when safety action triggered."""
        logger.warning(f"Safety action: {channel} -> {value} (from {action})")

        # Execute output write
        success = self.hardware.write_output(channel, value)

        if success:
            with self.values_lock:
                self.output_values[channel] = value

        # Publish safety action event
        self.mqtt.publish("safety/action", {
            'target_channel': channel,
            'value': value,
            'action': action,
            'success': success,
            'timestamp': datetime.now().isoformat()
        })

    def _publish_alarm_status(self):
        """Publish current alarm summary."""
        counts = self.safety.get_alarm_counts()
        active_alarms = self.safety.get_active_alarms()

        self.mqtt.publish("alarms/status", {
            'counts': counts,
            'active': active_alarms,
            'timestamp': datetime.now().isoformat()
        }, retain=True)

    def acknowledge_alarm(self, channel: str) -> bool:
        """Acknowledge an alarm."""
        success = self.safety.acknowledge(channel)
        if success:
            self._publish_alarm_status()
        return success

    # =========================================================================
    # WATCHDOG OUTPUT
    # =========================================================================

    def _toggle_watchdog_output(self):
        """Toggle watchdog output at configured rate for external safety relay monitoring."""
        if not self.config.watchdog_output_enabled or not self.config.watchdog_output_channel:
            return

        now = time.time()
        toggle_interval = 0.5 / self.config.watchdog_output_rate_hz  # half-period
        if now - self._watchdog_output_last_toggle < toggle_interval:
            return

        self._watchdog_output_state = not self._watchdog_output_state
        value = 1.0 if self._watchdog_output_state else 0.0
        self.hardware.write_output(self.config.watchdog_output_channel, value)
        self._watchdog_output_last_toggle = now

    def _stop_watchdog_output(self):
        """Force watchdog output LOW (external relay will detect loss of pulse)."""
        if self.config.watchdog_output_enabled and self.config.watchdog_output_channel:
            self.hardware.write_output(self.config.watchdog_output_channel, 0.0)
            self._watchdog_output_state = False
            logger.info(f"Watchdog output {self.config.watchdog_output_channel} set LOW")

    # =========================================================================
    # MQTT PUBLISHING
    # =========================================================================

    def _publish_values(self):
        """Publish all channel values as a batch."""
        with self.values_lock:
            batch = dict(self.channel_values)

            # Include output values
            for ch, val in self.output_values.items():
                batch[ch] = {
                    'value': val,
                    'timestamp': time.time(),
                    'quality': 'good',
                    'type': 'output'
                }

        self.mqtt.publish("channels/batch", batch)

    def _publish_single_channel(self, channel: str, value: float, ch_type: str = 'input'):
        """Publish single channel value."""
        self.mqtt.publish(f"channels/{channel}", {
            'value': value,
            'timestamp': time.time(),
            'quality': 'good',
            'type': ch_type
        })

    def _publish_status(self):
        """Publish system status."""
        # Cache modules and IP - they don't change at runtime
        if self._cached_modules is None:
            self._cached_modules = self._get_modules()
        if self._cached_ip is None:
            self._cached_ip = self._get_local_ip()

        status = {
            'status': 'online',
            'node_type': 'crio',
            'node_id': self.config.node_id,
            'acquiring': self.state.is_acquiring,
            'session_active': self.state.is_session_active,
            'channels': len(self.config.channels),
            'timestamp': datetime.now().isoformat(),
            'ip_address': self._cached_ip,
            'modules': self._cached_modules,
            'module_count': len(self._cached_modules),
            'config_version': self.config_version,
            'config_timestamp': self.config_timestamp
        }

        self.mqtt.publish("status/system", status, retain=True)

    def _publish_heartbeat(self):
        """Publish heartbeat for discovery."""
        heartbeat = {
            'node_type': 'crio',
            'node_id': self.config.node_id,
            'status': 'online',
            'acquiring': self.state.is_acquiring,
            'timestamp': datetime.now().isoformat()
        }

        self.mqtt.publish("heartbeat", heartbeat)

    def _publish_session_status(self):
        """Publish session status."""
        status = self.state.get_status()
        status['timestamp'] = datetime.now().isoformat()

        self.mqtt.publish("session/status", status)

    def _publish_command_ack(self, channel: str, success: bool, error: str = None):
        """Publish command acknowledgment for output writes."""
        ack = {
            'success': success,
            'command': 'output',
            'channel': channel,
            'timestamp': datetime.now().isoformat()
        }
        if error:
            ack['error'] = error

        self.mqtt.publish("command/ack", ack)

    def _publish_system_command_ack(self, command: str, success: bool,
                                     reason: str = None, request_id: str = None):
        """Publish command acknowledgment for system commands (acquire, session)."""
        ack = {
            'success': success,
            'command': command,
            'node_id': self.config.node_id,
            'state': self.state.state.name,
            'acquiring': self.state.is_acquiring,
            'session_active': self.state.is_session_active,
            'timestamp': datetime.now().isoformat()
        }
        if reason:
            ack['reason'] = reason
        if request_id:
            ack['request_id'] = request_id

        self.mqtt.publish("command/ack", ack, qos=1)
        logger.debug(f"Command ACK: {command} success={success}")

    def _publish_config_response(self, success: bool, message: str):
        """Publish config operation response (ACK for DAQ service)."""
        response = {
            'status': 'success' if success else 'error',
            'success': success,  # Keep for backwards compatibility
            'message': message,
            'channels': len(self.config.channels),
            'config_version': self.config_version,
            'timestamp': datetime.now().isoformat()
        }

        self.mqtt.publish("config/response", response, qos=1)
        logger.info(f"Config response published: status={response['status']}, channels={response['channels']}")

    # =========================================================================
    # STATE TRANSITION CALLBACKS
    # =========================================================================

    def _on_enter_acquiring(self, old_state, new_state, payload):
        """Called when entering ACQUIRING state."""
        logger.info("Starting hardware acquisition")
        self.hardware.start()
        # Auto-start acquisition-mode scripts
        self.script_engine.auto_start('acquisition')

    def _on_exit_acquiring(self, old_state, new_state, payload):
        """Called when exiting ACQUIRING state (to IDLE only)."""
        if new_state == State.IDLE:
            # Auto-stop acquisition-mode scripts
            self.script_engine.auto_stop('acquisition')
            logger.info("Stopping hardware acquisition")
            self.hardware.stop()

    def _on_enter_session(self, old_state, new_state, payload):
        """Called when entering SESSION state."""
        logger.info("Session started")
        # Auto-start session-mode scripts
        self.script_engine.auto_start('session')

    def _on_exit_session(self, old_state, new_state, payload):
        """Called when exiting SESSION state."""
        # Auto-stop session-mode scripts
        self.script_engine.auto_stop('session')
        logger.info("Session ended")

    def _on_enter_idle(self, old_state, new_state, payload):
        """Called when entering IDLE state."""
        # Stop watchdog output (external relay detects loss of pulse)
        self._stop_watchdog_output()
        # Ensure outputs are at safe state
        self.hardware.set_safe_state()

    def _on_mqtt_connection_change(self, connected: bool):
        """Handle MQTT connection state change."""
        if connected:
            logger.info("MQTT reconnected")
            self._publish_status()
        else:
            logger.warning("MQTT disconnected")

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _get_local_ip(self) -> str:
        """Get local IP address by connecting to the MQTT broker."""
        try:
            # Use the MQTT broker address to determine which interface reaches it
            broker = self.config.mqtt_broker
            port = self.config.mqtt_port
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((broker, port))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_modules(self) -> List[Dict[str, Any]]:
        """Enumerate hardware modules on the cRIO with channel information."""
        import re
        import subprocess
        modules = []
        slot_map = {}  # name -> slot number from nilsdev

        try:
            # First, try nilsdev to get proper slot numbers
            try:
                result = subprocess.run(
                    ['nilsdev', '--verbose'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    current_mod_name = None
                    for line in result.stdout.split('\n'):
                        line = line.strip()
                        if line.startswith('Mod'):
                            current_mod_name = line.strip()
                            # Extract slot from name (e.g., "Mod1" -> 1)
                            slot_num = int(current_mod_name.replace('Mod', '')) if current_mod_name.replace('Mod', '').isdigit() else 0
                            slot_map[current_mod_name] = slot_num
                        elif line.startswith('CompactDAQ.SlotNum:') and current_mod_name:
                            slot_map[current_mod_name] = int(line.split(':', 1)[1].strip())
            except Exception as e:
                logger.debug(f"nilsdev failed: {e}")

            # Now enumerate with nidaqmx
            if DAQMX_AVAILABLE:
                import nidaqmx.system
                system = nidaqmx.system.System.local()

                for device in system.devices:
                    product_type = getattr(device, 'product_type', 'Unknown')

                    # Skip the cRIO chassis - it's not a module
                    if 'cRIO' in product_type:
                        continue

                    # Only include NI 9xxx C-series modules
                    if 'NI 9' not in product_type:
                        continue

                    # Get slot number from nilsdev map or default to 0
                    slot = slot_map.get(device.name, 0)

                    # Build channel list - use category as channel_type for dashboard display
                    # Dashboard maps: voltage->VI, current->CI, thermocouple->TC, etc.
                    channels = []
                    try:
                        for ch in device.ai_physical_chans:
                            ch_type = self._get_channel_category(product_type, 'ai')
                            channels.append({
                                'name': str(ch.name),
                                'physical_channel': str(ch.name),
                                'channel_type': ch_type
                            })
                    except Exception:
                        pass

                    try:
                        for ch in device.ao_physical_chans:
                            ch_type = self._get_channel_category(product_type, 'ao')
                            channels.append({
                                'name': str(ch.name),
                                'physical_channel': str(ch.name),
                                'channel_type': ch_type
                            })
                    except Exception:
                        pass

                    try:
                        for ch in device.di_lines:
                            channels.append({
                                'name': str(ch.name),
                                'physical_channel': str(ch.name),
                                'channel_type': 'digital_input'
                            })
                    except Exception:
                        pass

                    try:
                        for ch in device.do_lines:
                            channels.append({
                                'name': str(ch.name),
                                'physical_channel': str(ch.name),
                                'channel_type': 'digital_output'
                            })
                    except Exception:
                        pass

                    modules.append({
                        'name': device.name,
                        'product_type': product_type,
                        'slot': slot,
                        'channels': channels,
                        'channel_count': len(channels)
                    })

                # Sort modules by slot number
                modules.sort(key=lambda m: m.get('slot', 0))

            else:
                # Mock mode - report configured channels as "modules"
                module_names = set()
                for ch in self.config.channels.values():
                    if '/' in ch.physical_channel:
                        module_names.add(ch.physical_channel.split('/')[0])
                for i, mod in enumerate(sorted(module_names)):
                    modules.append({
                        'name': mod,
                        'product_type': 'Configured',
                        'slot': i + 1,
                        'channels': [],
                        'channel_count': 0
                    })

        except Exception as e:
            logger.warning(f"Error enumerating modules: {e}")

        return modules

    def _get_channel_category(self, product_type: str, channel_type: str) -> str:
        """Determine channel type based on module type.

        Returns full type names that match dashboard CSS classes.
        Dashboard formatChannelType() converts to abbreviations for display.
        """
        import re
        match = re.search(r'9\d{3}', product_type)
        module_num = match.group() if match else ''

        # Thermocouple modules
        if module_num in ['9210', '9211', '9212', '9213', '9214', '9219']:
            return 'thermocouple'

        # RTD modules
        if module_num in ['9216', '9217', '9226']:
            return 'rtd'

        # Current input modules
        if module_num in ['9203', '9207', '9208', '9227']:
            return 'current'

        # Current output modules
        if module_num in ['9265', '9266']:
            return 'current_output'

        # Voltage input modules
        if module_num in ['9201', '9202', '9205', '9206', '9215', '9220', '9221', '9229', '9239']:
            return 'voltage'

        # Voltage output modules
        if module_num in ['9260', '9263', '9264', '9269']:
            return 'voltage_output'

        # Digital input modules
        if module_num in ['9401', '9402', '9411', '9421', '9422', '9423', '9425', '9426', '9435']:
            return 'digital_input'

        # Digital output modules
        if module_num in ['9472', '9474', '9475', '9476', '9477', '9478']:
            return 'digital_output'

        # Default based on channel type
        return 'voltage' if channel_type == 'ai' else 'voltage_output'


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """Main entry point for cRIO Node V2."""
    import argparse

    parser = argparse.ArgumentParser(description='cRIO Node V2 Service')
    parser.add_argument('--config', '-c', help='Configuration file (JSON)')
    parser.add_argument('--mock', action='store_true', help='Use mock hardware')
    parser.add_argument('--broker', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--node-id', default='crio-001', help='Node ID')
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load config
    if args.config:
        with open(args.config) as f:
            config_data = json.load(f)
        config = NodeConfig.from_dict(config_data)
    else:
        config = NodeConfig(
            node_id=args.node_id,
            mqtt_broker=args.broker,
            mqtt_port=args.port,
            use_mock_hardware=args.mock
        )

    # Override mock setting from command line
    if args.mock:
        config.use_mock_hardware = True

    # Run service
    node = CRIONodeV2(config)
    node.run()


if __name__ == '__main__':
    main()
