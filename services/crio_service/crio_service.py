#!/usr/bin/env python3
"""
cRIO Service
============

A service designed to run on NI cRIO-905x Linux RT systems.
Provides digital I/O handling, safety logic, and MQTT communication
with the main NISystem.

Current Features:
- Digital input monitoring (E-stops, interlocks, door switches)
- Digital output control (enable relays, safety indicators)
- Safety logic with interlock evaluation
- Watchdog monitoring of the main system
- MQTT communication with NISystem

Future Expansion:
- Analog I/O for additional measurements
- Counter/timer channels
- Custom protocols
- FPGA integration

Architecture:
    ┌─────────────────────────────────────────┐
    │            cRIO-905x (Linux RT)         │
    │  ┌─────────────────────────────────┐    │
    │  │  CRIOService                    │    │
    │  │  • DigitalIOHandler (nidaqmx)   │    │
    │  │  • SafetyLogic (interlocks)     │    │
    │  │  • MQTTClient (paho)            │    │
    │  │  • Watchdog (PC monitoring)     │    │
    │  └─────────────────────────────────┘    │
    └─────────────────────────────────────────┘
                      │ MQTT
                      ▼
    ┌─────────────────────────────────────────┐
    │         Main NISystem (Linux PC)        │
    └─────────────────────────────────────────┘

Author: NISystem Team
License: MIT
"""

import argparse
import configparser
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import paho.mqtt.client as mqtt

# Try to import nidaqmx - will fail on non-NI systems
try:
    import nidaqmx
    from nidaqmx.constants import LineGrouping
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    logging.warning("nidaqmx not available - running in simulation mode")

# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class SafetyAction(Enum):
    """Safety action types that can be triggered by digital inputs."""
    NONE = "none"
    WARN = "warn"
    STOP_ACQUISITION = "stop_acquisition"
    EMERGENCY_STOP = "emergency_stop"

class AlarmSeverity(Enum):
    """Alarm severity levels (ISA-18.2 aligned)."""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4

class SafetyState(Enum):
    """Overall safety system state."""
    NORMAL = "normal"
    WARNING = "warning"
    TRIPPED = "tripped"
    EMERGENCY = "emergency"

# =============================================================================
# CONFIGURATION DATACLASSES
# =============================================================================

@dataclass
class DigitalInputConfig:
    """Configuration for a digital input channel."""
    name: str
    physical_channel: str
    description: str = ""
    active_state: str = "low"  # "high" or "low"
    debounce_ms: int = 50
    safety_action: SafetyAction = SafetyAction.NONE
    trigger_alarm: bool = False
    alarm_severity: AlarmSeverity = AlarmSeverity.MEDIUM
    alarm_message: str = ""

@dataclass
class DigitalOutputConfig:
    """Configuration for a digital output channel."""
    name: str
    physical_channel: str
    description: str = ""
    default_state: str = "low"  # "high" or "low"
    safety_state: str = "low"  # State when safety event occurs
    allow_remote: bool = True  # Allow control from main system

@dataclass
class SafetyActionConfig:
    """Configuration for a safety action."""
    name: str
    description: str = ""
    outputs: List[str] = field(default_factory=list)
    enable_beacon: bool = False
    enable_horn: bool = False
    horn_duration_sec: float = 5.0
    notify_main_system: bool = True
    require_manual_reset: bool = False

@dataclass
class InterlockGroupConfig:
    """Configuration for an interlock group."""
    name: str
    description: str = ""
    required_inputs: List[str] = field(default_factory=list)
    controls_output: str = ""

@dataclass
class SystemConfig:
    """System-level configuration."""
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_base_topic: str = "nisystem"
    crio_id: str = "crio-001"
    crio_name: str = "cRIO Controller"
    scan_rate_hz: int = 4
    heartbeat_interval_sec: float = 1.0
    pc_watchdog_timeout_sec: float = 5.0
    pc_heartbeat_topic: str = "nisystem/heartbeat"
    safety_on_disconnect: bool = True
    log_level: str = "INFO"
    log_directory: str = "/var/log/crio_service"

@dataclass
class CRIOConfig:
    """Complete cRIO service configuration."""
    system: SystemConfig = field(default_factory=SystemConfig)
    digital_inputs: Dict[str, DigitalInputConfig] = field(default_factory=dict)
    digital_outputs: Dict[str, DigitalOutputConfig] = field(default_factory=dict)
    safety_actions: Dict[str, SafetyActionConfig] = field(default_factory=dict)
    interlock_groups: Dict[str, InterlockGroupConfig] = field(default_factory=dict)

# =============================================================================
# CONFIGURATION PARSER
# =============================================================================

def parse_config(config_path: str) -> CRIOConfig:
    """Parse the INI configuration file."""
    parser = configparser.ConfigParser()
    parser.read(config_path)

    config = CRIOConfig()

    # Parse system section
    if parser.has_section('system'):
        sys_section = parser['system']
        config.system.mqtt_broker = sys_section.get('mqtt_broker', 'localhost')
        config.system.mqtt_port = sys_section.getint('mqtt_port', 1883)
        config.system.mqtt_base_topic = sys_section.get('mqtt_base_topic', 'nisystem')
        config.system.crio_id = sys_section.get('crio_id', 'crio-001')
        config.system.crio_name = sys_section.get('crio_name', 'cRIO Controller')
        config.system.scan_rate_hz = sys_section.getint('scan_rate_hz', 4)
        config.system.heartbeat_interval_sec = sys_section.getfloat('heartbeat_interval_sec', 1.0)
        config.system.pc_watchdog_timeout_sec = sys_section.getfloat('pc_watchdog_timeout_sec', 5.0)
        config.system.pc_heartbeat_topic = sys_section.get('pc_heartbeat_topic', 'nisystem/heartbeat')
        config.system.safety_on_disconnect = sys_section.getboolean('safety_on_disconnect', True)

    if parser.has_section('service'):
        svc_section = parser['service']
        config.system.log_level = svc_section.get('log_level', 'INFO')
        config.system.log_directory = svc_section.get('log_directory', '/var/log/crio_service')

    # Parse digital inputs (sections starting with 'di:')
    for section in parser.sections():
        if section.startswith('di:'):
            name = section[3:]  # Remove 'di:' prefix
            sec = parser[section]

            # Parse safety action
            action_str = sec.get('safety_action', 'none').lower()
            try:
                safety_action = SafetyAction(action_str)
            except ValueError:
                safety_action = SafetyAction.NONE

            # Parse alarm severity
            severity_str = sec.get('alarm_severity', 'medium').lower()
            severity_map = {
                'critical': AlarmSeverity.CRITICAL,
                'high': AlarmSeverity.HIGH,
                'medium': AlarmSeverity.MEDIUM,
                'low': AlarmSeverity.LOW
            }
            alarm_severity = severity_map.get(severity_str, AlarmSeverity.MEDIUM)

            config.digital_inputs[name] = DigitalInputConfig(
                name=name,
                physical_channel=sec.get('physical_channel', ''),
                description=sec.get('description', ''),
                active_state=sec.get('active_state', 'low'),
                debounce_ms=sec.getint('debounce_ms', 50),
                safety_action=safety_action,
                trigger_alarm=sec.getboolean('trigger_alarm', False),
                alarm_severity=alarm_severity,
                alarm_message=sec.get('alarm_message', '')
            )

    # Parse digital outputs (sections starting with 'do:')
    for section in parser.sections():
        if section.startswith('do:'):
            name = section[3:]  # Remove 'do:' prefix
            sec = parser[section]

            config.digital_outputs[name] = DigitalOutputConfig(
                name=name,
                physical_channel=sec.get('physical_channel', ''),
                description=sec.get('description', ''),
                default_state=sec.get('default_state', 'low'),
                safety_state=sec.get('safety_state', 'low'),
                allow_remote=sec.getboolean('allow_remote', True)
            )

    # Parse safety actions (sections starting with 'safety_action:')
    for section in parser.sections():
        if section.startswith('safety_action:'):
            name = section[14:]  # Remove 'safety_action:' prefix
            sec = parser[section]

            outputs_str = sec.get('outputs', '')
            outputs = [o.strip() for o in outputs_str.split(',') if o.strip()]

            config.safety_actions[name] = SafetyActionConfig(
                name=name,
                description=sec.get('description', ''),
                outputs=outputs,
                enable_beacon=sec.getboolean('enable_beacon', False),
                enable_horn=sec.getboolean('enable_horn', False),
                horn_duration_sec=sec.getfloat('horn_duration_sec', 5.0),
                notify_main_system=sec.getboolean('notify_main_system', True),
                require_manual_reset=sec.getboolean('require_manual_reset', False)
            )

    # Parse interlock groups (sections starting with 'interlock_group:')
    for section in parser.sections():
        if section.startswith('interlock_group:'):
            name = section[16:]  # Remove 'interlock_group:' prefix
            sec = parser[section]

            inputs_str = sec.get('required_inputs', '')
            required_inputs = [i.strip() for i in inputs_str.split(',') if i.strip()]

            config.interlock_groups[name] = InterlockGroupConfig(
                name=name,
                description=sec.get('description', ''),
                required_inputs=required_inputs,
                controls_output=sec.get('controls_output', '')
            )

    return config

# =============================================================================
# DIGITAL I/O HANDLER
# =============================================================================

class DigitalIOHandler:
    """
    Handles digital I/O operations via NI-DAQmx.
    Falls back to simulation mode if nidaqmx is not available.
    """

    def __init__(self, config: CRIOConfig, simulation_mode: bool = False):
        self.config = config
        self.simulation_mode = simulation_mode or not NIDAQMX_AVAILABLE
        self.logger = logging.getLogger('DigitalIOHandler')

        # Current states
        self._di_states: Dict[str, bool] = {}
        self._do_states: Dict[str, bool] = {}
        self._di_raw: Dict[str, bool] = {}

        # Debounce tracking
        self._di_last_change: Dict[str, float] = {}
        self._di_stable_state: Dict[str, bool] = {}

        # DAQmx tasks
        self._di_task = None
        self._do_task = None

        # Thread safety
        self._lock = threading.Lock()

        # Initialize states
        for name in config.digital_inputs:
            self._di_states[name] = False
            self._di_raw[name] = False
            self._di_last_change[name] = 0.0
            self._di_stable_state[name] = False

        for name, do_config in config.digital_outputs.items():
            default = do_config.default_state.lower() == 'high'
            self._do_states[name] = default

    def initialize(self) -> bool:
        """Initialize the DAQmx tasks for digital I/O."""
        if self.simulation_mode:
            self.logger.info("Running in simulation mode - no hardware access")
            return True

        try:
            # Create digital input task
            if self.config.digital_inputs:
                self._di_task = nidaqmx.Task("crio_di")
                for name, di_config in self.config.digital_inputs.items():
                    self._di_task.di_channels.add_di_chan(
                        di_config.physical_channel,
                        name_to_assign_to_lines=name,
                        line_grouping=LineGrouping.CHAN_PER_LINE
                    )
                self.logger.info(f"Created DI task with {len(self.config.digital_inputs)} channels")

            # Create digital output task
            if self.config.digital_outputs:
                self._do_task = nidaqmx.Task("crio_do")
                for name, do_config in self.config.digital_outputs.items():
                    self._do_task.do_channels.add_do_chan(
                        do_config.physical_channel,
                        name_to_assign_to_lines=name,
                        line_grouping=LineGrouping.CHAN_PER_LINE
                    )
                self.logger.info(f"Created DO task with {len(self.config.digital_outputs)} channels")

                # Set initial states
                self._write_all_outputs()

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize DAQmx tasks: {e}")
            return False

    def cleanup(self):
        """Clean up DAQmx tasks."""
        if self._di_task:
            try:
                self._di_task.close()
            except Exception:
                pass
        if self._do_task:
            try:
                self._do_task.close()
            except Exception:
                pass

    def read_inputs(self) -> Dict[str, bool]:
        """
        Read all digital inputs and apply debouncing.
        Returns dict of {input_name: is_active} where is_active considers
        the configured active_state (high/low).
        """
        current_time = time.time()

        if self.simulation_mode:
            # In simulation, just return current states
            with self._lock:
                return dict(self._di_states)

        try:
            # Read raw values from hardware
            if self._di_task:
                raw_values = self._di_task.read()
                if not isinstance(raw_values, list):
                    raw_values = [raw_values]

                input_names = list(self.config.digital_inputs.keys())

                with self._lock:
                    for i, name in enumerate(input_names):
                        if i < len(raw_values):
                            raw_value = raw_values[i]
                            self._di_raw[name] = raw_value

                            # Determine if input is "active" based on configured active_state
                            di_config = self.config.digital_inputs[name]
                            if di_config.active_state.lower() == 'high':
                                is_active = raw_value
                            else:  # active_state == 'low'
                                is_active = not raw_value

                            # Apply debouncing
                            debounce_sec = di_config.debounce_ms / 1000.0

                            if is_active != self._di_stable_state.get(name, False):
                                # State changed - check if debounce period passed
                                last_change = self._di_last_change.get(name, 0.0)
                                if current_time - last_change >= debounce_sec:
                                    self._di_stable_state[name] = is_active
                                    self._di_states[name] = is_active
                                    self._di_last_change[name] = current_time
                            else:
                                self._di_last_change[name] = current_time

            with self._lock:
                return dict(self._di_states)

        except Exception as e:
            self.logger.error(f"Error reading digital inputs: {e}")
            with self._lock:
                return dict(self._di_states)

    def set_output(self, name: str, value: bool) -> bool:
        """Set a single digital output."""
        if name not in self.config.digital_outputs:
            self.logger.warning(f"Unknown digital output: {name}")
            return False

        with self._lock:
            self._do_states[name] = value

        if not self.simulation_mode:
            return self._write_all_outputs()

        return True

    def set_outputs(self, values: Dict[str, bool]) -> bool:
        """Set multiple digital outputs at once."""
        with self._lock:
            for name, value in values.items():
                if name in self.config.digital_outputs:
                    self._do_states[name] = value

        if not self.simulation_mode:
            return self._write_all_outputs()

        return True

    def set_all_to_safety_state(self) -> bool:
        """Set all outputs to their configured safety states."""
        with self._lock:
            for name, do_config in self.config.digital_outputs.items():
                safety_value = do_config.safety_state.lower() == 'high'
                self._do_states[name] = safety_value

        if not self.simulation_mode:
            return self._write_all_outputs()

        return True

    def _write_all_outputs(self) -> bool:
        """Write all output states to hardware."""
        if not self._do_task:
            return True

        try:
            output_names = list(self.config.digital_outputs.keys())
            with self._lock:
                values = [self._do_states.get(name, False) for name in output_names]

            if len(values) == 1:
                self._do_task.write(values[0])
            else:
                self._do_task.write(values)

            return True

        except Exception as e:
            self.logger.error(f"Error writing digital outputs: {e}")
            return False

    def get_input_state(self, name: str) -> Optional[bool]:
        """Get the current state of a digital input."""
        with self._lock:
            return self._di_states.get(name)

    def get_output_state(self, name: str) -> Optional[bool]:
        """Get the current state of a digital output."""
        with self._lock:
            return self._do_states.get(name)

    def get_all_input_states(self) -> Dict[str, bool]:
        """Get all digital input states."""
        with self._lock:
            return dict(self._di_states)

    def get_all_output_states(self) -> Dict[str, bool]:
        """Get all digital output states."""
        with self._lock:
            return dict(self._do_states)

    def simulate_input(self, name: str, value: bool):
        """Simulate a digital input (for testing)."""
        if name in self._di_states:
            with self._lock:
                self._di_states[name] = value

# =============================================================================
# SAFETY LOGIC ENGINE
# =============================================================================

class SafetyLogic:
    """
    Implements safety logic including interlock evaluation and action execution.
    """

    def __init__(self, config: CRIOConfig, io_handler: DigitalIOHandler):
        self.config = config
        self.io_handler = io_handler
        self.logger = logging.getLogger('SafetyLogic')

        # State tracking
        self.safety_state = SafetyState.NORMAL
        self.tripped_inputs: Set[str] = set()
        self.active_alarms: Dict[str, dict] = {}
        self.requires_reset = False

        # Callbacks
        self.on_safety_event: Optional[Callable[[str, dict], None]] = None
        self.on_alarm: Optional[Callable[[str, dict], None]] = None

        # Horn timer
        self._horn_off_time: Optional[float] = None

        # Thread safety
        self._lock = threading.Lock()

    def evaluate(self, input_states: Dict[str, bool]) -> List[dict]:
        """
        Evaluate safety logic based on current input states.
        Returns list of events that occurred.
        """
        events = []
        current_time = time.time()

        with self._lock:
            # Check each input for safety conditions
            for name, is_active in input_states.items():
                if name not in self.config.digital_inputs:
                    continue

                di_config = self.config.digital_inputs[name]
                was_tripped = name in self.tripped_inputs

                if is_active and not was_tripped:
                    # Input just became active - trigger safety action
                    self.tripped_inputs.add(name)

                    event = {
                        'type': 'input_triggered',
                        'input': name,
                        'description': di_config.description,
                        'action': di_config.safety_action.value,
                        'timestamp': datetime.now().isoformat()
                    }
                    events.append(event)

                    # Execute safety action
                    self._execute_safety_action(di_config.safety_action, name)

                    # Create alarm if configured
                    if di_config.trigger_alarm:
                        alarm = {
                            'id': f"crio_{name}_{int(current_time)}",
                            'source': name,
                            'severity': di_config.alarm_severity.name.lower(),
                            'message': di_config.alarm_message or f"{di_config.description} activated",
                            'timestamp': datetime.now().isoformat(),
                            'state': 'active'
                        }
                        self.active_alarms[name] = alarm

                        if self.on_alarm:
                            self.on_alarm(name, alarm)

                elif not is_active and was_tripped:
                    # Input cleared
                    action_config = self.config.safety_actions.get(
                        di_config.safety_action.value, None
                    )

                    if action_config and action_config.require_manual_reset:
                        # Keep tripped - requires manual reset
                        pass
                    else:
                        # Auto-clear
                        self.tripped_inputs.discard(name)

                        event = {
                            'type': 'input_cleared',
                            'input': name,
                            'description': di_config.description,
                            'timestamp': datetime.now().isoformat()
                        }
                        events.append(event)

                        # Clear alarm
                        if name in self.active_alarms:
                            self.active_alarms[name]['state'] = 'cleared'
                            if self.on_alarm:
                                self.on_alarm(name, self.active_alarms[name])
                            del self.active_alarms[name]

            # Check horn timer
            if self._horn_off_time and current_time >= self._horn_off_time:
                self.io_handler.set_output('alarm_horn', False)
                self._horn_off_time = None

            # Evaluate interlock groups
            self._evaluate_interlocks()

            # Update overall safety state
            self._update_safety_state()

        return events

    def _execute_safety_action(self, action: SafetyAction, source: str):
        """Execute a safety action."""
        if action == SafetyAction.NONE:
            return

        action_config = self.config.safety_actions.get(action.value)
        if not action_config:
            self.logger.warning(f"No configuration for safety action: {action.value}")
            return

        self.logger.warning(f"Executing safety action: {action.value} triggered by {source}")

        # Set outputs to safety state
        for output_name in action_config.outputs:
            if output_name in self.config.digital_outputs:
                do_config = self.config.digital_outputs[output_name]
                safety_value = do_config.safety_state.lower() == 'high'
                self.io_handler.set_output(output_name, safety_value)

        # Handle beacon
        if action_config.enable_beacon:
            self.io_handler.set_output('alarm_beacon', True)

        # Handle horn with timer
        if action_config.enable_horn:
            self.io_handler.set_output('alarm_horn', True)
            self._horn_off_time = time.time() + action_config.horn_duration_sec

        # Track if manual reset required
        if action_config.require_manual_reset:
            self.requires_reset = True

        # Notify via callback
        if self.on_safety_event and action_config.notify_main_system:
            event = {
                'type': 'safety_action',
                'action': action.value,
                'source': source,
                'outputs_affected': action_config.outputs,
                'requires_reset': action_config.require_manual_reset,
                'timestamp': datetime.now().isoformat()
            }
            self.on_safety_event(action.value, event)

    def _evaluate_interlocks(self):
        """Evaluate interlock groups and control outputs accordingly."""
        for name, group in self.config.interlock_groups.items():
            # Check if all required inputs are NOT active (i.e., safe)
            all_clear = True
            for input_name in group.required_inputs:
                if input_name in self.tripped_inputs:
                    all_clear = False
                    break

            # Control the associated output
            if group.controls_output:
                if group.controls_output in self.config.digital_outputs:
                    do_config = self.config.digital_outputs[group.controls_output]
                    if not all_clear:
                        # Interlock not satisfied - force to safety state
                        safety_value = do_config.safety_state.lower() == 'high'
                        self.io_handler.set_output(group.controls_output, safety_value)

    def _update_safety_state(self):
        """Update the overall safety state based on current conditions."""
        if not self.tripped_inputs:
            self.safety_state = SafetyState.NORMAL
        else:
            # Check severity of tripped inputs
            max_severity = AlarmSeverity.LOW
            for input_name in self.tripped_inputs:
                if input_name in self.config.digital_inputs:
                    di_config = self.config.digital_inputs[input_name]
                    if di_config.alarm_severity.value < max_severity.value:
                        max_severity = di_config.alarm_severity

            if max_severity == AlarmSeverity.CRITICAL:
                self.safety_state = SafetyState.EMERGENCY
            elif max_severity == AlarmSeverity.HIGH:
                self.safety_state = SafetyState.TRIPPED
            else:
                self.safety_state = SafetyState.WARNING

    def manual_reset(self) -> bool:
        """Perform a manual reset of the safety system."""
        with self._lock:
            # Check if all inputs are clear
            current_states = self.io_handler.get_all_input_states()
            active_inputs = [name for name, active in current_states.items() if active]

            if active_inputs:
                self.logger.warning(f"Cannot reset - inputs still active: {active_inputs}")
                return False

            # Clear tripped state
            self.tripped_inputs.clear()
            self.requires_reset = False
            self.safety_state = SafetyState.NORMAL

            # Turn off beacon and horn
            self.io_handler.set_output('alarm_beacon', False)
            self.io_handler.set_output('alarm_horn', False)

            # Clear alarms
            self.active_alarms.clear()

            self.logger.info("Safety system manually reset")
            return True

    def get_status(self) -> dict:
        """Get current safety status."""
        with self._lock:
            return {
                'state': self.safety_state.value,
                'tripped_inputs': list(self.tripped_inputs),
                'requires_reset': self.requires_reset,
                'active_alarms': list(self.active_alarms.keys()),
                'input_states': self.io_handler.get_all_input_states(),
                'output_states': self.io_handler.get_all_output_states()
            }

# =============================================================================
# MAIN SERVICE CLASS
# =============================================================================

class CRIOService:
    """
    Main cRIO Service class.
    Orchestrates I/O handling, safety logic, and MQTT communication.
    """

    def __init__(self, config_path: str, simulation_mode: bool = False):
        self.config_path = config_path
        self.simulation_mode = simulation_mode

        # Parse configuration
        self.config = parse_config(config_path)

        # Setup logging
        self._setup_logging()
        self.logger = logging.getLogger('CRIOService')
        self.logger.info(f"Initializing cRIO Service: {self.config.system.crio_name}")

        # Components
        self.io_handler = DigitalIOHandler(self.config, simulation_mode)
        self.safety_logic = SafetyLogic(self.config, self.io_handler)

        # Wire up callbacks
        self.safety_logic.on_safety_event = self._on_safety_event
        self.safety_logic.on_alarm = self._on_alarm

        # MQTT client
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_connected = threading.Event()

        # PC watchdog
        self.last_pc_heartbeat = time.time()
        self.pc_watchdog_tripped = False

        # Service state
        self.running = threading.Event()
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None

        # Statistics
        self.stats = {
            'scan_count': 0,
            'events_processed': 0,
            'mqtt_messages_sent': 0,
            'mqtt_messages_received': 0,
            'start_time': None
        }

        # TAG name -> physical channel mapping (pushed from main DAQ service)
        self.tag_to_physical: Dict[str, dict] = {}
        self.config_version: str = ''

    def _setup_logging(self):
        """Configure logging."""
        log_level = getattr(logging, self.config.system.log_level.upper(), logging.INFO)

        # Create log directory if it doesn't exist
        log_dir = Path(self.config.system.log_directory)
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                log_dir = Path('.')  # Fall back to current directory

        # Configure logging with rotation (10MB max, keep 3 backups)
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                RotatingFileHandler(
                    log_dir / 'crio_service.log',
                    maxBytes=10*1024*1024,  # 10 MB
                    backupCount=3
                )
            ]
        )

    def _setup_mqtt(self):
        """Set up MQTT client and connect to broker."""
        client_id = f"crio_service_{self.config.system.crio_id}_{uuid.uuid4().hex[:8]}"

        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id
        )

        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        # Set last will - if we disconnect unexpectedly, notify the system
        base = self.config.system.mqtt_base_topic
        will_payload = json.dumps({
            'crio_id': self.config.system.crio_id,
            'status': 'offline',
            'timestamp': datetime.now().isoformat()
        })
        self.mqtt_client.will_set(
            f"{base}/crio/status",
            payload=will_payload,
            qos=1,
            retain=True
        )

        try:
            self.mqtt_client.connect(
                self.config.system.mqtt_broker,
                self.config.system.mqtt_port,
                keepalive=60
            )
            self.mqtt_client.loop_start()
            self.logger.info(f"Connecting to MQTT broker at {self.config.system.mqtt_broker}:{self.config.system.mqtt_port}")
        except Exception as e:
            self.logger.error(f"Failed to connect to MQTT broker: {e}")

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """Handle MQTT connection."""
        if reason_code == 0:
            self.logger.info("Connected to MQTT broker")
            self.mqtt_connected.set()

            base = self.config.system.mqtt_base_topic

            # Subscribe to topics
            crio_id = self.config.system.crio_id
            subscriptions = [
                (f"{base}/crio/commands/#", 1),
                (f"{base}/crio/do/set", 1),
                (f"{base}/crio/reset", 1),
                (f"{base}/crio/status/request", 1),
                (self.config.system.pc_heartbeat_topic, 1),
                # Config push from main DAQ service (for project import/load)
                (f"{base}/nodes/{crio_id}/config/full", 1),
            ]

            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
                self.logger.debug(f"Subscribed to: {topic}")

            # Publish online status
            self._publish_status()
        else:
            self.logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Handle MQTT disconnection."""
        self.logger.warning(f"Disconnected from MQTT broker: {reason_code}")
        self.mqtt_connected.clear()

        # Trigger safety if configured
        if self.config.system.safety_on_disconnect and self.running.is_set():
            self.logger.warning("MQTT disconnected - triggering safety action")
            self.io_handler.set_all_to_safety_state()

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        self.stats['mqtt_messages_received'] += 1

        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            base = self.config.system.mqtt_base_topic

            # PC heartbeat - update watchdog
            if topic == self.config.system.pc_heartbeat_topic:
                self.last_pc_heartbeat = time.time()
                if self.pc_watchdog_tripped:
                    self.logger.info("PC heartbeat restored")
                    self.pc_watchdog_tripped = False
                return

            # Parse JSON payload
            try:
                data = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                data = {}

            # Handle commands
            if topic == f"{base}/crio/do/set":
                self._handle_do_set(data)

            elif topic == f"{base}/crio/reset":
                self._handle_reset(data)

            elif topic == f"{base}/crio/status/request":
                self._publish_status()

            elif topic.startswith(f"{base}/crio/commands/"):
                command = topic.split('/')[-1]
                self._handle_command(command, data)

            # Config push from main DAQ service (project import/load)
            elif topic == f"{base}/nodes/{self.config.system.crio_id}/config/full":
                self._handle_config_push(data)

        except Exception as e:
            self.logger.error(f"Error processing MQTT message: {e}")

    def _handle_do_set(self, data: dict):
        """Handle digital output set command."""
        request_id = data.get('request_id', '')

        for output_name, value in data.items():
            if output_name in ['request_id', 'timestamp']:
                continue

            if output_name not in self.config.digital_outputs:
                continue

            do_config = self.config.digital_outputs[output_name]
            if not do_config.allow_remote:
                self.logger.warning(f"Remote control not allowed for output: {output_name}")
                continue

            # Don't allow setting outputs if safety is tripped
            if self.safety_logic.safety_state in [SafetyState.TRIPPED, SafetyState.EMERGENCY]:
                self.logger.warning(f"Cannot set output {output_name} - safety tripped")
                continue

            self.io_handler.set_output(output_name, bool(value))
            self.logger.info(f"Set output {output_name} = {value}")

        # Send acknowledgment
        self._publish_ack(request_id, True, "Output(s) set")

    def _handle_reset(self, data: dict):
        """Handle safety reset command."""
        request_id = data.get('request_id', '')

        success = self.safety_logic.manual_reset()

        if success:
            self._publish_ack(request_id, True, "Safety system reset")
            self._publish_status()
        else:
            self._publish_ack(request_id, False, "Cannot reset - inputs still active")

    def _handle_command(self, command: str, data: dict):
        """Handle generic commands."""
        request_id = data.get('request_id', '')

        if command == 'simulate_input':
            # For testing - simulate an input
            input_name = data.get('input')
            value = data.get('value', True)
            if input_name:
                self.io_handler.simulate_input(input_name, value)
                self._publish_ack(request_id, True, f"Simulated {input_name} = {value}")
        else:
            self._publish_ack(request_id, False, f"Unknown command: {command}")

    def _handle_config_push(self, data: dict):
        """Handle config push from main DAQ service.

        This is called when a project is imported/loaded and the DAQ service
        pushes the TAG name -> physical channel mappings to this cRIO.

        Args:
            data: Config data containing:
                - channels: List of channel configs with name, physical_channel, channel_type
                - scripts: Python scripts (not yet implemented)
                - safe_state_outputs: DO channels for safe state
                - config_version: Hash for version tracking
        """
        base = self.config.system.mqtt_base_topic
        crio_id = self.config.system.crio_id

        try:
            channels = data.get('channels', [])
            config_version = data.get('config_version', '')

            # Store TAG name -> physical channel mapping
            # This allows us to receive commands by TAG name and map to physical channels
            self.tag_to_physical = {}
            for ch in channels:
                tag_name = ch.get('name', '')
                physical_ch = ch.get('physical_channel', '')
                if tag_name and physical_ch:
                    self.tag_to_physical[tag_name] = {
                        'physical_channel': physical_ch,
                        'channel_type': ch.get('channel_type', ''),
                        'default_state': ch.get('default_state', False),
                        'invert': ch.get('invert', False),
                    }

            self.logger.info(f"Received config push: {len(channels)} channels (version: {config_version})")

            # Store config version for reporting in status
            self.config_version = config_version

            # Send ACK response to DAQ service
            self._mqtt_publish(
                f"{base}/nodes/{crio_id}/config/response",
                {
                    'status': 'ok',
                    'channels': len(channels),
                    'config_version': config_version,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
                }
            )

            # Re-publish status with updated config version
            self._publish_status()

        except Exception as e:
            self.logger.error(f"Failed to apply config push: {e}")
            self._mqtt_publish(
                f"{base}/nodes/{crio_id}/config/response",
                {
                    'status': 'error',
                    'error': str(e),
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
                }
            )

    def _on_safety_event(self, action: str, event: dict):
        """Callback when a safety event occurs."""
        base = self.config.system.mqtt_base_topic

        self._mqtt_publish(
            f"{base}/crio/events/safety",
            event
        )

        # Also publish to main system's alarm topic
        self._mqtt_publish(
            f"{base}/alarms/crio_{event.get('source', 'unknown')}",
            {
                'state': 'active',
                'severity': 'critical',
                'message': f"cRIO: {action} triggered by {event.get('source')}",
                'source': f"crio:{self.config.system.crio_id}",
                'timestamp': event.get('timestamp')
            }
        )

    def _on_alarm(self, name: str, alarm: dict):
        """Callback when an alarm state changes."""
        base = self.config.system.mqtt_base_topic

        self._mqtt_publish(
            f"{base}/crio/alarms/{name}",
            alarm
        )

    def _publish_status(self):
        """Publish current status to MQTT."""
        base = self.config.system.mqtt_base_topic

        status = self.safety_logic.get_status()
        status.update({
            'crio_id': self.config.system.crio_id,
            'crio_name': self.config.system.crio_name,
            'online': True,
            'simulation_mode': self.simulation_mode,
            'pc_watchdog_ok': not self.pc_watchdog_tripped,
            'uptime_sec': time.time() - self.stats['start_time'] if self.stats['start_time'] else 0,
            'scan_count': self.stats['scan_count'],
            'config_version': self.config_version,  # For sync verification with main DAQ
            'channels': len(self.tag_to_physical),  # Number of configured TAG mappings
            'timestamp': datetime.now().isoformat()
        })

        self._mqtt_publish(f"{base}/crio/status", status, retain=True)

    def _publish_ack(self, request_id: str, success: bool, message: str):
        """Publish command acknowledgment."""
        base = self.config.system.mqtt_base_topic

        self._mqtt_publish(
            f"{base}/crio/command/ack",
            {
                'request_id': request_id,
                'success': success,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
        )

    def _mqtt_publish(self, topic: str, payload: dict, retain: bool = False):
        """Publish a message to MQTT."""
        if self.mqtt_client and self.mqtt_connected.is_set():
            try:
                self.mqtt_client.publish(
                    topic,
                    json.dumps(payload),
                    qos=1,
                    retain=retain
                )
                self.stats['mqtt_messages_sent'] += 1
            except Exception as e:
                self.logger.error(f"Failed to publish to {topic}: {e}")

    def _scan_loop(self):
        """Main scan loop - reads inputs and evaluates safety logic."""
        scan_interval = 1.0 / self.config.system.scan_rate_hz

        while self.running.is_set():
            loop_start = time.time()

            try:
                # Read all digital inputs
                input_states = self.io_handler.read_inputs()

                # Evaluate safety logic
                events = self.safety_logic.evaluate(input_states)

                # Process any events
                for event in events:
                    self.stats['events_processed'] += 1
                    self.logger.info(f"Event: {event}")

                # Check PC watchdog
                self._check_pc_watchdog()

                self.stats['scan_count'] += 1

            except Exception as e:
                self.logger.error(f"Error in scan loop: {e}")

            # Maintain scan rate
            elapsed = time.time() - loop_start
            sleep_time = scan_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _check_pc_watchdog(self):
        """Check if PC heartbeat has timed out."""
        if not self.config.system.safety_on_disconnect:
            return

        elapsed = time.time() - self.last_pc_heartbeat

        if elapsed > self.config.system.pc_watchdog_timeout_sec:
            if not self.pc_watchdog_tripped:
                self.logger.warning(f"PC watchdog timeout ({elapsed:.1f}s) - triggering safety")
                self.pc_watchdog_tripped = True

                # Set all outputs to safety state
                self.io_handler.set_all_to_safety_state()

                # Publish event
                base = self.config.system.mqtt_base_topic
                self._mqtt_publish(
                    f"{base}/crio/events/watchdog",
                    {
                        'type': 'pc_watchdog_timeout',
                        'timeout_sec': self.config.system.pc_watchdog_timeout_sec,
                        'elapsed_sec': elapsed,
                        'timestamp': datetime.now().isoformat()
                    }
                )

    def _heartbeat_loop(self):
        """Publish periodic heartbeat."""
        while self.running.is_set():
            base = self.config.system.mqtt_base_topic

            self._mqtt_publish(
                f"{base}/crio/heartbeat",
                {
                    'crio_id': self.config.system.crio_id,
                    'state': self.safety_logic.safety_state.value,
                    'timestamp': datetime.now().isoformat()
                }
            )

            # Also publish full status periodically
            self._publish_status()

            time.sleep(self.config.system.heartbeat_interval_sec)

    def start(self):
        """Start the service."""
        self.logger.info("Starting cRIO Service...")
        self.stats['start_time'] = time.time()

        # Initialize I/O
        if not self.io_handler.initialize():
            self.logger.error("Failed to initialize I/O handler")
            return False

        # Connect to MQTT
        self._setup_mqtt()

        # Wait for MQTT connection (with timeout)
        if not self.mqtt_connected.wait(timeout=10.0):
            self.logger.warning("MQTT connection timeout - continuing anyway")

        # Start threads
        self.running.set()

        self.scan_thread = threading.Thread(target=self._scan_loop, name="scan_loop")
        self.scan_thread.daemon = True
        self.scan_thread.start()

        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="heartbeat_loop")
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()

        self.logger.info(f"cRIO Service started - scanning at {self.config.system.scan_rate_hz} Hz")
        return True

    def stop(self):
        """Stop the service gracefully."""
        self.logger.info("Stopping cRIO Service...")

        # Signal threads to stop
        self.running.clear()

        # Wait for threads
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2.0)

        # Set outputs to safe state
        self.io_handler.set_all_to_safety_state()

        # Publish offline status
        if self.mqtt_client:
            base = self.config.system.mqtt_base_topic
            self._mqtt_publish(
                f"{base}/crio/status",
                {
                    'crio_id': self.config.system.crio_id,
                    'online': False,
                    'timestamp': datetime.now().isoformat()
                },
                retain=True
            )
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        # Cleanup I/O
        self.io_handler.cleanup()

        self.logger.info("cRIO Service stopped")

    def run(self):
        """Run the service (blocking)."""
        if not self.start():
            return

        # Setup signal handlers
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep running
        try:
            while self.running.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='cRIO Service - Digital I/O and safety for NISystem'
    )
    parser.add_argument(
        '-c', '--config',
        default='config/crio_service.ini',
        help='Path to configuration file'
    )
    parser.add_argument(
        '-s', '--simulation',
        action='store_true',
        help='Run in simulation mode (no hardware)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)

    # Create and run service
    service = CRIOService(args.config, simulation_mode=args.simulation)
    service.run()

if __name__ == '__main__':
    main()
