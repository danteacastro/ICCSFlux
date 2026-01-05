#!/usr/bin/env python3
"""
DAQ Service for NISystem
Main service that reads/writes NI hardware (or simulation) and publishes to MQTT
"""

import json
import os
import time
import signal
import sys
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import asdict

import paho.mqtt.client as mqtt

from config_parser import (
    load_config, load_config_safe, validate_config, NISystemConfig, ChannelConfig, ChannelType,
    get_input_channels, get_output_channels, ConfigValidationError, ValidationResult,
    SystemConfig, ThermocoupleType
)
from simulator import HardwareSimulator
from hardware_reader import HardwareReader, NIDAQMX_AVAILABLE as HW_READER_AVAILABLE

# Try to import ModbusReader
try:
    from modbus_reader import ModbusReader, PYMODBUS_AVAILABLE
except ImportError:
    PYMODBUS_AVAILABLE = False
    ModbusReader = None

# Try to import DataSourceManager (for REST API, OPC-UA, etc.)
try:
    from data_source_manager import (
        DataSourceManager, DataSourceConfig, DataSourceType,
        ChannelMapping, get_data_source_manager
    )
    from rest_reader import RestDataSource, RestSourceConfig, AuthType
    DATA_SOURCE_MANAGER_AVAILABLE = True
except ImportError as e:
    DATA_SOURCE_MANAGER_AVAILABLE = False
    logger.warning(f"DataSourceManager not available: {e}")

from scheduler import SimpleScheduler
from sequence_manager import SequenceManager, Sequence, SequenceStep
from script_manager import ScriptManager, Script, ScriptRunMode, ScriptState
from trigger_engine import TriggerEngine
from watchdog_engine import WatchdogEngine
from device_discovery import DeviceDiscovery
from recording_manager import RecordingManager, RecordingConfig
from dependency_tracker import DependencyTracker, EntityType
from scaling import apply_scaling, get_scaling_info, validate_scaling_config
from user_variables import UserVariableManager
from alarm_manager import AlarmManager, AlarmConfig, AlarmSeverity, LatchBehavior
from audit_trail import AuditTrail, AuditEventType
from user_session import UserSessionManager, UserRole, Permission
from project_manager import ProjectManager, ProjectStatus
from archive_manager import ArchiveManager

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
        self.hardware_reader: Optional[HardwareReader] = None
        self.modbus_reader: Optional['ModbusReader'] = None
        self.data_source_manager: Optional['DataSourceManager'] = None

        # Thread-safe control flags using Events
        self._running = threading.Event()
        self._acquiring = threading.Event()
        self._shutdown_requested = threading.Event()

        # CRITICAL: Explicitly ensure acquiring starts as False
        # This prevents auto-start of data acquisition on service startup
        self._acquiring.clear()
        logger.info("Acquisition state initialized: acquiring=False (safe startup)")

        # Service start time for uptime tracking
        self._start_time: Optional[datetime] = None

        # Heartbeat state
        self._heartbeat_sequence = 0
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_interval = 2.0  # seconds

        # System state - controllable via MQTT
        self.recording = False          # Is data recording active
        self.recording_start_time: Optional[datetime] = None
        self.recording_filename: Optional[str] = None

        # Authentication state (session-based via UserSessionManager)
        self.current_session_id: Optional[str] = None
        self.current_user_role: Optional[str] = None

        # Channel values cache
        self.channel_values: Dict[str, Any] = {}      # Scaled engineering values
        self.channel_raw_values: Dict[str, Any] = {}  # Raw values before scaling
        self.channel_timestamps: Dict[str, float] = {}
        # SOE (Sequence of Events) support - microsecond precision acquisition timestamps
        self.channel_acquisition_ts_us: Dict[str, int] = {}  # Microseconds since epoch

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

        # Project state - stores FULL PATH, not just filename
        self.current_project_path: Optional[Path] = None  # Full path to current project
        self.current_project_data: Dict[str, Any] = {}  # Current project data
        self.projects_dir: Optional[Path] = None  # Default projects directory (for listing)

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

        # Sequence manager
        self.sequence_manager: Optional[SequenceManager] = None

        # Script manager (Python script execution)
        self.script_manager: Optional[ScriptManager] = None

        # Trigger engine (automation triggers)
        self.trigger_engine: Optional[TriggerEngine] = None

        # Watchdog engine (channel monitoring)
        self.watchdog_engine: Optional[WatchdogEngine] = None

        # User variable manager
        self.user_variables: Optional[UserVariableManager] = None

        # Enhanced alarm manager
        self.alarm_manager: Optional[AlarmManager] = None

        # Audit trail (21 CFR Part 11 / ALCOA+ compliance)
        self.audit_trail: Optional[AuditTrail] = None

        # User session manager (role-based access control)
        self.user_session_manager: Optional[UserSessionManager] = None

        # Project manager (backup, validation, safety locking)
        self.project_manager: Optional[ProjectManager] = None

        # Archive manager (long-term data retention)
        self.archive_manager: Optional[ArchiveManager] = None

        # Resource monitoring
        self._cpu_percent = 0.0
        self._memory_mb = 0.0
        self._resource_monitor_enabled = False
        try:
            import psutil
            self._process = psutil.Process()
            self._resource_monitor_enabled = True
        except ImportError:
            logger.warning("psutil not installed - resource monitoring disabled")
            self._process = None

        self._load_config()
        self._init_scheduler()
        self._init_recording_manager()
        self._init_dependency_tracker()
        self._init_sequence_manager()
        self._init_script_manager()
        self._init_trigger_engine()
        self._init_watchdog_engine()
        self._init_user_variables()
        self._init_alarm_manager()
        self._init_audit_trail()
        self._init_user_session_manager()
        self._init_project_manager()
        self._init_archive_manager()

    # =========================================================================
    # THREAD-SAFE PROPERTY ACCESSORS
    # =========================================================================

    @property
    def running(self) -> bool:
        """Thread-safe running state accessor"""
        return self._running.is_set()

    @running.setter
    def running(self, value: bool):
        """Thread-safe running state setter"""
        if value:
            self._running.set()
        else:
            self._running.clear()

    @property
    def acquiring(self) -> bool:
        """Thread-safe acquiring state accessor"""
        return self._acquiring.is_set()

    @acquiring.setter
    def acquiring(self, value: bool):
        """Thread-safe acquiring state setter"""
        if value:
            self._acquiring.set()
        else:
            self._acquiring.clear()

    # =========================================================================
    # MULTI-NODE TOPIC HELPERS
    # =========================================================================

    def get_topic_base(self) -> str:
        """Get the node-prefixed MQTT topic base.

        Returns topic in format: {mqtt_base_topic}/nodes/{node_id}
        Example: nisystem/nodes/node-001

        This enables multi-node support where multiple DAQ services can
        publish to the same broker with unique topic namespaces.
        """
        if not self.config:
            return "nisystem/nodes/node-001"  # Fallback
        base = self.config.system.mqtt_base_topic
        node_id = self.config.system.node_id
        return f"{base}/nodes/{node_id}"

    def get_topic(self, category: str, entity: str = "") -> str:
        """Build a full MQTT topic with node prefix.

        Args:
            category: Topic category (e.g., 'channels', 'status', 'alarms')
            entity: Optional entity name (e.g., channel name, alarm id)

        Returns:
            Full topic path: {base}/nodes/{node_id}/{category}[/{entity}]

        Example:
            get_topic('channels', 'TC001') -> 'nisystem/nodes/node-001/channels/TC001'
            get_topic('status', 'system') -> 'nisystem/nodes/node-001/status/system'
        """
        base = self.get_topic_base()
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

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

            # Initialize hardware reader or simulator
            if self.config.system.simulation_mode:
                logger.info("Simulation mode enabled - using hardware simulator")
                self.simulator = HardwareSimulator(self.config)
                self.hardware_reader = None
            elif not HW_READER_AVAILABLE:
                logger.warning("nidaqmx not available - falling back to simulator")
                self.simulator = HardwareSimulator(self.config)
                self.hardware_reader = None
            else:
                # Real hardware mode
                logger.info("Initializing hardware reader for real NI hardware")
                try:
                    self.hardware_reader = HardwareReader(self.config)
                    self.simulator = None
                    logger.info("Hardware reader initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize hardware reader: {e}")
                    logger.warning("Falling back to simulator")
                    self.hardware_reader = None
                    self.simulator = HardwareSimulator(self.config)

            # Initialize Modbus reader if we have Modbus devices configured
            self._init_modbus_reader()

            # Initialize external data sources (REST API, OPC-UA, etc.)
            self._init_data_sources()

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

    def _apply_project_config(self, project_data: Dict[str, Any]) -> bool:
        """Apply configuration from project JSON (channels, system settings)

        This replaces the need for a separate .ini file - all config is in the project JSON.

        Args:
            project_data: The loaded project JSON dict

        Returns:
            True if config was applied successfully
        """
        try:
            # Parse system settings from project
            sys_data = project_data.get("system", {})
            system = SystemConfig(
                mqtt_broker=sys_data.get("mqtt_broker", "localhost"),
                mqtt_port=int(sys_data.get("mqtt_port", 1883)),
                mqtt_base_topic=sys_data.get("mqtt_base_topic", "nisystem"),
                scan_rate_hz=min(float(sys_data.get("scan_rate_hz", 20)), 100.0),
                publish_rate_hz=min(float(sys_data.get("publish_rate_hz", 4)), 10.0),
                simulation_mode=sys_data.get("simulation_mode", False),
                log_directory=sys_data.get("log_directory", "./logs"),
                config_reload_topic=sys_data.get("config_reload_topic", "nisystem/config/reload")
            )

            # Parse channels from project
            channels_data = project_data.get("channels", {})
            channels: Dict[str, ChannelConfig] = {}

            for name, ch_data in channels_data.items():
                # Determine channel type
                ch_type_str = ch_data.get("channel_type", "voltage")
                channel_type = ChannelType(ch_type_str)

                # Parse thermocouple type if present
                tc_type = None
                if "thermocouple_type" in ch_data:
                    tc_type = ThermocoupleType(ch_data["thermocouple_type"])

                channels[name] = ChannelConfig(
                    name=name,
                    module=ch_data.get("module", ""),
                    physical_channel=ch_data.get("physical_channel", ""),
                    channel_type=channel_type,
                    description=ch_data.get("description", ""),  # For tooltips/documentation only
                    units=ch_data.get("units", ""),
                    visible=ch_data.get("visible", True),
                    group=ch_data.get("group", ""),
                    scale_slope=float(ch_data.get("scale_slope", 1.0)),
                    scale_offset=float(ch_data.get("scale_offset", 0.0)),
                    scale_type=ch_data.get("scale_type", "none"),
                    four_twenty_scaling=ch_data.get("four_twenty_scaling", False),
                    eng_units_min=float(ch_data["eng_units_min"]) if "eng_units_min" in ch_data else None,
                    eng_units_max=float(ch_data["eng_units_max"]) if "eng_units_max" in ch_data else None,
                    pre_scaled_min=float(ch_data["pre_scaled_min"]) if "pre_scaled_min" in ch_data else None,
                    pre_scaled_max=float(ch_data["pre_scaled_max"]) if "pre_scaled_max" in ch_data else None,
                    scaled_min=float(ch_data["scaled_min"]) if "scaled_min" in ch_data else None,
                    scaled_max=float(ch_data["scaled_max"]) if "scaled_max" in ch_data else None,
                    voltage_range=float(ch_data.get("voltage_range", 10.0)),
                    current_range_ma=float(ch_data.get("current_range_ma", 20.0)),
                    terminal_config=ch_data.get("terminal_config", "RSE"),
                    thermocouple_type=tc_type,
                    cjc_source=ch_data.get("cjc_source", "internal"),
                    # RTD
                    rtd_type=ch_data.get("rtd_type", "Pt100"),
                    rtd_resistance=float(ch_data.get("rtd_resistance", 100.0)),
                    rtd_wiring=ch_data.get("rtd_wiring", ch_data.get("resistance_config", "4-wire")),
                    rtd_current=float(ch_data.get("rtd_current", ch_data.get("excitation_current", 0.001))),
                    # Digital
                    invert=ch_data.get("invert", False),
                    default_state=ch_data.get("default_state", False),
                    default_value=float(ch_data.get("default_value", 0.0)),
                    # Legacy limits (for backward compatibility)
                    low_limit=float(ch_data["low_limit"]) if "low_limit" in ch_data else None,
                    high_limit=float(ch_data["high_limit"]) if "high_limit" in ch_data else None,
                    low_warning=float(ch_data["low_warning"]) if "low_warning" in ch_data else None,
                    high_warning=float(ch_data["high_warning"]) if "high_warning" in ch_data else None,
                    # ISA-18.2 Alarm Configuration
                    alarm_enabled=ch_data.get("alarm_enabled", False),
                    hihi_limit=float(ch_data["hihi_limit"]) if "hihi_limit" in ch_data else None,
                    hi_limit=float(ch_data["hi_limit"]) if "hi_limit" in ch_data else None,
                    lo_limit=float(ch_data["lo_limit"]) if "lo_limit" in ch_data else None,
                    lolo_limit=float(ch_data["lolo_limit"]) if "lolo_limit" in ch_data else None,
                    alarm_priority=ch_data.get("alarm_priority", "medium"),
                    alarm_deadband=float(ch_data.get("alarm_deadband", 1.0)),
                    alarm_delay_sec=float(ch_data.get("alarm_delay_sec", 0.0)),
                    # Safety
                    safety_action=ch_data.get("safety_action"),
                    safety_interlock=ch_data.get("safety_interlock"),
                    # Logging
                    log=ch_data.get("log", True),
                    log_interval_ms=int(ch_data.get("log_interval_ms", 1000))
                )

            # Create new config with parsed data
            # Keep existing chassis/modules/safety_actions if available
            self.config = NISystemConfig(
                system=system,
                chassis=self.config.chassis if self.config else {},
                modules=self.config.modules if self.config else {},
                channels=channels,
                safety_actions=self.config.safety_actions if self.config else {}
            )

            # Reinitialize hardware reader or simulator based on new config
            if self.config.system.simulation_mode:
                logger.info("Simulation mode enabled - using hardware simulator")
                self.simulator = HardwareSimulator(self.config)
                self.hardware_reader = None
            elif not HW_READER_AVAILABLE:
                logger.warning("nidaqmx not available - falling back to simulator")
                self.simulator = HardwareSimulator(self.config)
                self.hardware_reader = None
            else:
                # Real hardware mode
                logger.info("Initializing hardware reader for real NI hardware")
                try:
                    self.hardware_reader = HardwareReader(self.config)
                    self.simulator = None
                    logger.info("Hardware reader initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize hardware reader: {e}")
                    logger.warning("Falling back to simulator")
                    self.hardware_reader = None
                    self.simulator = HardwareSimulator(self.config)

            # Initialize channel values
            for name, channel in self.config.channels.items():
                if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[name] = channel.default_state
                elif channel.channel_type == ChannelType.ANALOG_OUTPUT:
                    self.channel_values[name] = channel.default_value
                else:
                    self.channel_values[name] = 0.0

            # Reinitialize alarm manager with new channel configs
            # This clears old alarms and creates new alarm configs from the new channels
            if self.alarm_manager:
                self.alarm_manager.clear_all(clear_configs=True)
            self._init_alarm_manager(from_project=True)

            # Load scripts from project
            # Scripts with run_mode=acquisition or session will auto-start when triggered
            if self.script_manager:
                self.script_manager.load_scripts_from_project(project_data)
                script_count = len(self.script_manager.scripts)
                if script_count > 0:
                    logger.info(f"Loaded {script_count} scripts from project")

            # Load formulas from project (calculatedParams -> formula blocks)
            if self.user_variables:
                channel_names = list(channels.keys())
                formula_count = self.user_variables.load_formulas_from_project(project_data, channel_names)
                if formula_count > 0:
                    logger.info(f"Loaded {formula_count} formulas from project")

            # Load triggers from project
            if self.trigger_engine:
                trigger_count = self.trigger_engine.load_from_project(project_data)
                if trigger_count > 0:
                    logger.info(f"Loaded {trigger_count} triggers from project")

            # Load watchdogs from project
            if self.watchdog_engine:
                watchdog_count = self.watchdog_engine.load_from_project(project_data)
                if watchdog_count > 0:
                    logger.info(f"Loaded {watchdog_count} watchdogs from project")

            logger.info(f"Applied project config: {len(channels)} channels")
            return True

        except Exception as e:
            logger.error(f"Failed to apply project config: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _init_modbus_reader(self):
        """Initialize Modbus reader if Modbus devices are configured"""
        if not PYMODBUS_AVAILABLE:
            logger.debug("pymodbus not available - Modbus support disabled")
            return

        # Check if we have any Modbus channels configured
        has_modbus_channels = any(
            ch.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
            for ch in self.config.channels.values()
        )

        # Check if we have any Modbus-type chassis (TCP or RTU connection)
        has_modbus_devices = any(
            chassis.connection.upper() in ("TCP", "RTU", "MODBUS_TCP", "MODBUS_RTU")
            for chassis in self.config.chassis.values()
            if chassis.enabled
        )

        if not has_modbus_channels and not has_modbus_devices:
            logger.debug("No Modbus devices or channels configured")
            return

        try:
            self.modbus_reader = ModbusReader(self.config)
            connection_results = self.modbus_reader.connect_all()

            connected = sum(1 for v in connection_results.values() if v)
            total = len(connection_results)
            logger.info(f"Modbus reader initialized: {connected}/{total} devices connected")

            if connected == 0 and total > 0:
                logger.warning("No Modbus devices connected - check device availability")

        except Exception as e:
            logger.error(f"Failed to initialize Modbus reader: {e}")
            self.modbus_reader = None

    def _init_data_sources(self):
        """Initialize DataSourceManager for REST API and other external data sources"""
        if not DATA_SOURCE_MANAGER_AVAILABLE:
            logger.debug("DataSourceManager not available - external data sources disabled")
            return

        try:
            self.data_source_manager = get_data_source_manager()

            # Load data sources from project config if available
            if self.current_project_data and 'data_sources' in self.current_project_data:
                for source_config in self.current_project_data['data_sources']:
                    self._add_data_source_from_config(source_config)

            # Start all data sources
            if self.data_source_manager.sources:
                self.data_source_manager.start_all()
                logger.info(f"DataSourceManager initialized with {len(self.data_source_manager.sources)} sources")
            else:
                logger.debug("No external data sources configured")

        except Exception as e:
            logger.error(f"Failed to initialize DataSourceManager: {e}")
            self.data_source_manager = None

    def _add_data_source_from_config(self, source_config: Dict[str, Any]):
        """Add a data source from project config"""
        if not self.data_source_manager:
            return

        source_type_str = source_config.get('type', '')
        name = source_config.get('name', '')

        try:
            if source_type_str == 'rest_api':
                # Create REST API data source
                connection = source_config.get('connection', {})
                config = RestSourceConfig(
                    name=name,
                    source_type=DataSourceType.REST_API,
                    enabled=source_config.get('enabled', True),
                    poll_rate_ms=source_config.get('poll_rate_ms', 100),
                    timeout_s=source_config.get('timeout_s', 5.0),
                    retries=source_config.get('retries', 3),
                    base_url=connection.get('base_url', ''),
                    auth_type=AuthType(connection.get('auth_type', 'none')),
                    username=connection.get('username', ''),
                    password=connection.get('password', ''),
                    api_key=connection.get('api_key', ''),
                    api_key_header=connection.get('api_key_header', 'X-API-Key'),
                    bearer_token=connection.get('bearer_token', ''),
                    verify_ssl=connection.get('verify_ssl', True),
                )

                # Create channel mappings
                channels = []
                for ch_config in source_config.get('channels', []):
                    channels.append(ChannelMapping(
                        channel_name=ch_config.get('name', ''),
                        source_address=ch_config.get('address', ''),
                        data_type=ch_config.get('data_type', 'float32'),
                        scale=ch_config.get('scale', 1.0),
                        offset=ch_config.get('offset', 0.0),
                        unit=ch_config.get('unit', ''),
                        is_output=ch_config.get('is_output', False),
                    ))

                self.data_source_manager.add_source(config, channels)
                logger.info(f"Added REST API data source: {name}")

            # Add other source types here (OPC-UA, EtherNet/IP, etc.)

        except Exception as e:
            logger.error(f"Failed to add data source '{name}': {e}")

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

    def _init_sequence_manager(self):
        """Initialize the sequence manager with callbacks"""
        self.sequence_manager = SequenceManager()

        # Wire up callbacks
        self.sequence_manager.on_set_output = self._sequence_set_output
        self.sequence_manager.on_start_recording = self._sequence_start_recording
        self.sequence_manager.on_stop_recording = self._sequence_stop_recording
        self.sequence_manager.on_start_acquisition = self._sequence_start_acquisition
        self.sequence_manager.on_stop_acquisition = self._sequence_stop_acquisition
        self.sequence_manager.on_get_channel_value = self._sequence_get_channel_value
        self.sequence_manager.on_sequence_event = self._sequence_event_handler
        self.sequence_manager.on_log_message = self._sequence_log_message

        logger.info("Sequence manager initialized")

    def _init_script_manager(self):
        """Initialize the script manager for Python script execution"""
        self.script_manager = ScriptManager()

        # Wire up callbacks
        self.script_manager.on_get_channel_value = self._script_get_channel_value
        self.script_manager.on_get_channel_timestamp = self._script_get_channel_timestamp
        self.script_manager.on_get_channel_names = self._script_get_channel_names
        self.script_manager.on_has_channel = self._script_has_channel
        self.script_manager.on_set_output = self._script_set_output
        self.script_manager.on_start_acquisition = self._script_start_acquisition
        self.script_manager.on_stop_acquisition = self._script_stop_acquisition
        self.script_manager.on_start_recording = self._script_start_recording
        self.script_manager.on_stop_recording = self._script_stop_recording
        self.script_manager.on_is_session_active = self._script_is_session_active
        self.script_manager.on_get_session_elapsed = self._script_get_session_elapsed
        self.script_manager.on_is_recording = self._script_is_recording
        self.script_manager.on_get_scan_rate = self._script_get_scan_rate
        self.script_manager.on_publish_value = self._script_publish_value
        self.script_manager.on_script_event = self._script_event_handler
        self.script_manager.on_script_output = self._script_output_handler

        logger.info("Script manager initialized")

    def _init_trigger_engine(self):
        """Initialize the trigger engine for automation triggers"""
        self.trigger_engine = TriggerEngine()

        # Wire up callbacks
        self.trigger_engine.set_output = self._set_output_value
        self.trigger_engine.start_recording = lambda: self.recording_manager.start_recording() if self.recording_manager else None
        self.trigger_engine.stop_recording = lambda: self.recording_manager.stop_recording() if self.recording_manager else None
        self.trigger_engine.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id) if self.sequence_manager else None
        self.trigger_engine.stop_sequence = lambda seq_id: self.sequence_manager.stop_sequence(seq_id) if self.sequence_manager else None
        self.trigger_engine.publish_notification = self._publish_trigger_notification

        logger.info("Trigger engine initialized")

    def _init_watchdog_engine(self):
        """Initialize the watchdog engine for channel monitoring"""
        self.watchdog_engine = WatchdogEngine()

        # Wire up callbacks
        self.watchdog_engine.set_output = self._set_output_value
        self.watchdog_engine.start_recording = lambda: self.recording_manager.start_recording() if self.recording_manager else None
        self.watchdog_engine.stop_recording = lambda: self.recording_manager.stop_recording() if self.recording_manager else None
        self.watchdog_engine.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id) if self.sequence_manager else None
        self.watchdog_engine.stop_sequence = lambda seq_id: self.sequence_manager.stop_sequence(seq_id) if self.sequence_manager else None
        self.watchdog_engine.publish_notification = self._publish_watchdog_notification
        self.watchdog_engine.raise_alarm = self._raise_watchdog_alarm

        logger.info("Watchdog engine initialized")

    def _publish_trigger_notification(self, event_type: str, trigger_name: str, message: str):
        """Publish trigger notification to MQTT"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/trigger/notification",
            json.dumps({
                "type": event_type,
                "trigger": trigger_name,
                "message": message,
                "timestamp": time.time()
            })
        )

    def _publish_watchdog_notification(self, event_type: str, watchdog_name: str, message: str):
        """Publish watchdog notification to MQTT"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/watchdog/notification",
            json.dumps({
                "type": event_type,
                "watchdog": watchdog_name,
                "message": message,
                "timestamp": time.time()
            })
        )

    def _raise_watchdog_alarm(self, watchdog_id: str, severity: str, message: str):
        """Raise an alarm from a watchdog"""
        if self.alarm_manager:
            # For now, just log it - could integrate with alarm_manager
            logger.warning(f"Watchdog alarm [{severity}]: {message}")
        # Also publish to MQTT
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/watchdog/alarm",
            json.dumps({
                "watchdog_id": watchdog_id,
                "severity": severity,
                "message": message,
                "timestamp": time.time()
            })
        )

    # =========================================================================
    # SCRIPT MANAGER CALLBACKS
    # =========================================================================

    def _script_get_channel_value(self, channel: str) -> float:
        """Get channel value for script"""
        return self.channel_values.get(channel, 0.0)

    def _script_get_channel_timestamp(self, channel: str) -> float:
        """Get channel timestamp for script"""
        return self.channel_timestamps.get(channel, 0.0)

    def _script_get_channel_names(self) -> list:
        """Get all channel names for script"""
        return list(self.channel_values.keys())

    def _script_has_channel(self, channel: str) -> bool:
        """Check if channel exists"""
        return channel in self.channel_values

    def _script_set_output(self, channel: str, value) -> None:
        """Set output from script"""
        if channel in self.config.channels:
            self._set_output_value(channel, value)

    def _script_start_acquisition(self) -> None:
        """Start acquisition from script"""
        if not self.acquiring:
            self.acquiring = True
            self._publish_system_status()
            if self.script_manager:
                self.script_manager.on_acquisition_start()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_start()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_start()

    def _script_stop_acquisition(self) -> None:
        """Stop acquisition from script"""
        if self.acquiring:
            self.acquiring = False
            self._publish_system_status()
            if self.script_manager:
                self.script_manager.on_acquisition_stop()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_stop()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_stop()

    def _script_start_recording(self, filename: str = None) -> None:
        """Start recording from script"""
        if self.recording_manager and not self.recording_manager.is_recording:
            self.recording_manager.start_recording(filename)

    def _script_stop_recording(self) -> None:
        """Stop recording from script"""
        if self.recording_manager and self.recording_manager.is_recording:
            self.recording_manager.stop_recording()

    def _script_is_session_active(self) -> bool:
        """Check if session is active for script"""
        if self.user_variables:
            return self.user_variables.test_session_active
        return self.acquiring

    def _script_get_session_elapsed(self) -> float:
        """Get session elapsed time for script"""
        if self.user_variables and self.user_variables.test_session_active:
            return self.user_variables.get_elapsed_time()
        return 0.0

    def _script_is_recording(self) -> bool:
        """Check if recording is active"""
        if self.recording_manager:
            return self.recording_manager.is_recording
        return False

    def _script_get_scan_rate(self) -> float:
        """Get current scan rate"""
        return getattr(self.config.system, 'scan_rate', 10.0)

    def _script_publish_value(self, script_id: str, name: str, value: float, units: str = '') -> None:
        """Publish computed value from script"""
        # Store in script-published values (py.{name} prefix)
        full_name = f"py.{name}"
        self.channel_values[full_name] = value
        self.channel_timestamps[full_name] = time.time()

        # Also record in CSV if recording
        if self.recording_manager and self.recording_manager.is_recording:
            self.recording_manager.update_script_values({name: value})

        # Publish via MQTT
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/values",
            json.dumps({name: value, "_timestamp": time.time()})
        )

    def _script_event_handler(self, event_type: str, script) -> None:
        """Handle script events"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/event",
            json.dumps({
                "event": event_type,
                "script_id": script.id,
                "script_name": script.name,
                "state": script.state.value if hasattr(script.state, 'value') else str(script.state),
                "timestamp": time.time()
            })
        )
        self._publish_script_status()

    def _script_output_handler(self, script_id: str, output_type: str, message: str) -> None:
        """Handle script output (print statements, logs)"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/output",
            json.dumps({
                "script_id": script_id,
                "type": output_type,
                "message": message,
                "timestamp": time.time()
            })
        )

    # =========================================================================
    # SCRIPT MQTT HANDLERS
    # =========================================================================

    def _handle_script_add(self, payload) -> None:
        """Add a new backend script"""
        if not self.script_manager:
            return

        if not isinstance(payload, dict):
            logger.error(f"Invalid payload for script/add: {type(payload)} - {payload}")
            return

        script_id = payload.get('id', str(uuid.uuid4()))
        name = payload.get('name', 'Untitled Script')
        code = payload.get('code', '')
        run_mode = payload.get('run_mode', 'manual')
        enabled = payload.get('enabled', True)

        # Convert run_mode string to enum
        mode_map = {
            'manual': ScriptRunMode.MANUAL,
            'acquisition': ScriptRunMode.ACQUISITION,
            'session': ScriptRunMode.SESSION
        }
        run_mode_enum = mode_map.get(run_mode, ScriptRunMode.MANUAL)

        script = Script(
            id=script_id,
            name=name,
            code=code,
            run_mode=run_mode_enum,
            enabled=enabled
        )

        self.script_manager.add_script(script)
        logger.info(f"Script added: {name} ({script_id})")
        self._publish_script_status()

        # Send response
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "add",
                "success": True,
                "script_id": script_id
            })
        )

    def _handle_script_update(self, payload: dict) -> None:
        """Update an existing backend script"""
        if not self.script_manager:
            return

        script_id = payload.get('id')
        if not script_id:
            return

        script = self.script_manager.get_script(script_id)
        if not script:
            logger.warning(f"Script not found for update: {script_id}")
            return

        # Update fields if provided
        if 'name' in payload:
            script.name = payload['name']
        if 'code' in payload:
            script.code = payload['code']
        if 'run_mode' in payload:
            mode_map = {
                'manual': ScriptRunMode.MANUAL,
                'acquisition': ScriptRunMode.ACQUISITION,
                'session': ScriptRunMode.SESSION
            }
            script.run_mode = mode_map.get(payload['run_mode'], script.run_mode)
        if 'enabled' in payload:
            script.enabled = payload['enabled']

        logger.info(f"Script updated: {script.name} ({script_id})")
        self._publish_script_status()

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "update",
                "success": True,
                "script_id": script_id
            })
        )

    def _handle_script_remove(self, payload: dict) -> None:
        """Remove a backend script"""
        if not self.script_manager:
            return

        script_id = payload.get('id')
        if not script_id:
            return

        success = self.script_manager.remove_script(script_id)
        logger.info(f"Script removed: {script_id}, success={success}")
        self._publish_script_status()

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "remove",
                "success": success,
                "script_id": script_id
            })
        )

    def _handle_script_start(self, payload: dict) -> None:
        """Start a backend script"""
        if not self.script_manager:
            return

        script_id = payload.get('id')
        if not script_id:
            return

        success = self.script_manager.start_script(script_id)
        logger.info(f"Script start requested: {script_id}, success={success}")

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "start",
                "success": success,
                "script_id": script_id
            })
        )

    def _handle_script_stop(self, payload: dict) -> None:
        """Stop a running backend script"""
        if not self.script_manager:
            return

        script_id = payload.get('id')
        if not script_id:
            return

        success = self.script_manager.stop_script(script_id)
        logger.info(f"Script stop requested: {script_id}, success={success}")

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "stop",
                "success": success,
                "script_id": script_id
            })
        )

    def _handle_script_list(self) -> None:
        """List all backend scripts"""
        self._publish_script_status()

    def _handle_script_get(self, payload: dict) -> None:
        """Get a specific script's details"""
        if not self.script_manager:
            return

        script_id = payload.get('id')
        if not script_id:
            return

        script = self.script_manager.get_script(script_id)

        base = self.get_topic_base()
        if script:
            self.mqtt_client.publish(
                f"{base}/script/details",
                json.dumps({
                    "id": script.id,
                    "name": script.name,
                    "code": script.code,
                    "run_mode": script.run_mode.value,
                    "enabled": script.enabled,
                    "state": script.state.value,
                    "error": script.error_message,
                    "started_at": script.started_at,
                    "iterations": script.iterations
                })
            )
        else:
            self.mqtt_client.publish(
                f"{base}/script/details",
                json.dumps({"error": f"Script not found: {script_id}"})
            )

    def _publish_script_status(self) -> None:
        """Publish status of all backend scripts"""
        if not self.script_manager:
            return

        scripts = []
        for script_id, script in self.script_manager.scripts.items():
            scripts.append({
                "id": script.id,
                "name": script.name,
                "run_mode": script.run_mode.value,
                "enabled": script.enabled,
                "state": script.state.value,
                "error": script.error_message,
                "started_at": script.started_at,
                "iterations": script.iterations
            })

        base = self.get_topic_base()
        payload = json.dumps({
            "scripts": scripts,
            "timestamp": time.time()
        })
        logger.info(f"Publishing script status to {base}/script/status: {len(scripts)} scripts")
        self.mqtt_client.publish(f"{base}/script/status", payload)

    def _init_user_variables(self):
        """Initialize the user variable manager with callbacks"""
        # Get data directory from config or use default
        data_dir = getattr(self.config.system, 'data_directory', 'data')

        self.user_variables = UserVariableManager(
            data_dir=data_dir,
            on_session_start=self._on_test_session_start,
            on_session_stop=self._on_test_session_stop,
            scheduler_enable=self._user_var_scheduler_enable,
            recording_start=self._user_var_recording_start,
            recording_stop=self._user_var_recording_stop,
            run_sequence=self._user_var_run_sequence,
            stop_sequence=self._user_var_stop_sequence,
        )
        logger.info("User variable manager initialized")

    def _init_alarm_manager(self, from_project: bool = False):
        """Initialize the enhanced alarm manager with ISA-18.2 compliant alarm configuration

        Args:
            from_project: If True, create alarm configs from current channels (project loaded).
                         If False, just create empty alarm manager (no project loaded yet).
        """
        data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
        self.alarm_manager = AlarmManager(
            data_dir=data_dir,
            publish_callback=self._alarm_manager_publish
        )

        # Only create alarm configs from channels when a project is explicitly loaded
        # This prevents stale alarm configs when no project is loaded
        if not from_project:
            logger.info("Alarm manager initialized (no project - no alarm configs)")
            return

        # Auto-create alarm configs from channel configs
        for name, channel in self.config.channels.items():
            # Check if config already exists
            if self.alarm_manager.get_alarm_config(f"alarm-{name}"):
                continue

            # Check for ISA-18.2 alarm configuration (preferred)
            has_isa_limits = any([channel.hihi_limit, channel.hi_limit, channel.lo_limit, channel.lolo_limit])
            # Also support legacy limits for backward compatibility
            has_legacy_limits = any([channel.high_limit, channel.low_limit, channel.high_warning, channel.low_warning])

            # Skip if no limits defined at all
            if not has_isa_limits and not has_legacy_limits:
                continue

            # Determine if alarms are enabled
            # ISA-18.2: respect alarm_enabled flag
            # Legacy: enable by default if limits are defined
            alarm_enabled = channel.alarm_enabled if has_isa_limits else has_legacy_limits

            if not alarm_enabled:
                continue  # Skip disabled alarms

            # Determine severity from alarm_priority or safety_action
            severity = AlarmSeverity.MEDIUM
            priority_map = {
                'diagnostic': AlarmSeverity.LOW,
                'low': AlarmSeverity.LOW,
                'medium': AlarmSeverity.MEDIUM,
                'high': AlarmSeverity.HIGH,
                'critical': AlarmSeverity.CRITICAL
            }
            severity = priority_map.get(channel.alarm_priority, AlarmSeverity.MEDIUM)
            # Upgrade severity if safety action is configured
            if channel.safety_action and severity.value > AlarmSeverity.HIGH.value:
                severity = AlarmSeverity.HIGH

            # Use ISA-18.2 limits if available, otherwise fall back to legacy
            high_high = channel.hihi_limit if channel.hihi_limit is not None else channel.high_limit
            high = channel.hi_limit if channel.hi_limit is not None else channel.high_warning
            low = channel.lo_limit if channel.lo_limit is not None else channel.low_warning
            low_low = channel.lolo_limit if channel.lolo_limit is not None else channel.low_limit

            # Create alarm config
            config = AlarmConfig(
                id=f"alarm-{name}",
                channel=name,
                name=name,
                description=channel.description or '',
                enabled=True,
                severity=severity,
                high_high=high_high,
                high=high,
                low=low,
                low_low=low_low,
                deadband=channel.alarm_deadband,
                on_delay_s=channel.alarm_delay_sec,
                off_delay_s=0,
                latch_behavior=LatchBehavior.AUTO_CLEAR,
                group=channel.group or '',
                actions=[channel.safety_action] if channel.safety_action else []
            )
            self.alarm_manager.add_alarm_config(config)

        logger.info(f"Alarm manager initialized with {len(self.alarm_manager.alarm_configs)} alarm configs")

    def _init_audit_trail(self):
        """Initialize the audit trail for 21 CFR Part 11 / ALCOA+ compliance"""
        try:
            data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
            audit_dir = data_dir / "audit"
            self.audit_trail = AuditTrail(
                audit_dir=audit_dir,
                node_id=getattr(self.config.system, 'node_id', 'node-001'),
                retention_days=365,
                max_file_size_mb=50.0
            )
            logger.info(f"Audit trail initialized at {audit_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize audit trail: {e}")
            self.audit_trail = None

    def _init_user_session_manager(self):
        """Initialize the user session manager for role-based access control"""
        try:
            data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
            self.user_session_manager = UserSessionManager(
                data_dir=data_dir,
                session_timeout_minutes=30,
                max_failed_attempts=5,
                lockout_duration_minutes=15
            )
            logger.info("User session manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize user session manager: {e}")
            self.user_session_manager = None

    def _init_project_manager(self):
        """Initialize the project manager with backup/validation capabilities"""
        try:
            projects_dir = self._get_projects_dir()
            self.project_manager = ProjectManager(
                projects_dir=projects_dir,
                max_backups=10,
                backup_on_save=True,
                validate_on_load=True
            )
            # Link audit trail
            if self.audit_trail:
                self.project_manager.audit_trail = self.audit_trail
            logger.info(f"Project manager initialized at {projects_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize project manager: {e}")
            self.project_manager = None

    def _init_archive_manager(self):
        """Initialize archive manager for long-term data retention"""
        try:
            # Use data directory for archives
            data_dir = Path(self.config_path).parent / 'data'
            archive_dir = data_dir / 'archives'

            self.archive_manager = ArchiveManager(
                data_dir=data_dir,
                archive_dir=archive_dir
            )

            # Link audit trail if available
            if self.audit_trail:
                self.archive_manager.audit_trail = self.audit_trail

            logger.info(f"Archive manager initialized at {archive_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize archive manager: {e}")
            self.archive_manager = None

    def _alarm_manager_publish(self, event_type: str, data: dict):
        """Callback from alarm manager to publish events"""
        if not self.mqtt_client:
            return

        base = self.get_topic_base()

        if event_type == 'alarm':
            # Publish alarm state
            self.mqtt_client.publish(
                f"{base}/alarms/active/{data.get('alarm_id', 'unknown')}",
                json.dumps(data),
                retain=True,
                qos=1
            )
        elif event_type == 'alarm_cleared':
            # Publish cleared state
            self.mqtt_client.publish(
                f"{base}/alarms/active/{data.get('alarm_id', 'unknown')}",
                json.dumps({'active': False, 'alarm_id': data.get('alarm_id')}),
                retain=True,
                qos=1
            )
        elif event_type == 'action':
            # Legacy action handler (config-defined safety actions)
            action_id = data.get('action_id')
            trigger_source = data.get('alarm_id', 'unknown')
            if action_id and action_id in self.config.safety_actions:
                self._execute_safety_action(action_id, trigger_source)
        elif event_type == 'safety_action':
            # ISA-18.2 safety action from AlarmManager
            # Publish to MQTT so frontend can execute (frontend-defined actions)
            self.mqtt_client.publish(
                f"{base}/safety/action",
                json.dumps(data),
                qos=1
            )
            logger.warning(f"SAFETY ACTION published: {data.get('action_id')} by alarm {data.get('alarm_id')}")
            # Also try backend execution for actions defined in config
            action_id = data.get('action_id')
            trigger_source = data.get('alarm_id', 'unknown')
            if action_id and action_id in self.config.safety_actions:
                self._execute_safety_action(action_id, trigger_source)

    def _on_test_session_start(self):
        """Custom callback when test session starts"""
        logger.info("Test session started - custom callback")
        self._publish_test_session_status()
        # Notify automation engines
        if self.script_manager:
            self.script_manager.on_session_start()
        if self.trigger_engine:
            self.trigger_engine.on_session_start()
        if self.watchdog_engine:
            self.watchdog_engine.on_session_start()

    def _on_test_session_stop(self):
        """Custom callback when test session stops"""
        logger.info("Test session stopped - custom callback")
        self._publish_test_session_status()
        # Notify automation engines
        if self.script_manager:
            self.script_manager.on_session_stop()
        if self.trigger_engine:
            self.trigger_engine.on_session_stop()
        if self.watchdog_engine:
            self.watchdog_engine.on_session_stop()

    def _user_var_scheduler_enable(self, enable: bool):
        """Callback for user variable manager to enable/disable scheduler"""
        if self.scheduler:
            self.scheduler.enabled = enable
            logger.info(f"Scheduler {'enabled' if enable else 'disabled'} by test session")
            self._publish_schedule_status()

    def _user_var_recording_start(self):
        """Callback for user variable manager to start recording"""
        self._start_recording()

    def _user_var_recording_stop(self):
        """Callback for user variable manager to stop recording"""
        self._stop_recording()

    def _user_var_run_sequence(self, sequence_id: str):
        """Callback for user variable manager to run a sequence"""
        if self.sequence_manager:
            self.sequence_manager.start_sequence(sequence_id, self.channel_values)

    def _user_var_stop_sequence(self):
        """Callback for user variable manager to stop running sequence"""
        if self.sequence_manager:
            self.sequence_manager.abort_current_sequence()

    def _sequence_set_output(self, channel: str, value: Any):
        """Callback for sequence to set output"""
        self._set_output_value(channel, value)

    def _set_output_value(self, channel: str, value: Any):
        """Generic callback for setting output values (used by scripts, triggers, watchdogs, sequences)"""
        if channel in self.config.channels:
            ch = self.config.channels[channel]
            if ch.channel_type in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT,
                                   ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL):
                # Route to appropriate backend
                is_modbus = ch.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
                if is_modbus and self.modbus_reader:
                    self.modbus_reader.write_channel(channel, value)
                elif self.simulator:
                    self.simulator.write_channel(channel, value)
                elif self.hardware_reader:
                    self.hardware_reader.write_channel(channel, value)
                with self.values_lock:
                    self.channel_values[channel] = value
                self._publish_channel_value(channel, value)

    def _sequence_start_recording(self, filename: Optional[str] = None):
        """Callback for sequence to start recording"""
        self._start_recording(filename)

    def _sequence_stop_recording(self):
        """Callback for sequence to stop recording"""
        self._stop_recording()

    def _sequence_start_acquisition(self):
        """Callback for sequence to start acquisition"""
        if not self.acquiring:
            self.acquiring = True
            logger.info("Sequence started acquisition")
            if self.script_manager:
                self.script_manager.on_acquisition_start()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_start()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_start()

    def _sequence_stop_acquisition(self):
        """Callback for sequence to stop acquisition"""
        if self.acquiring:
            self.acquiring = False
            logger.info("Sequence stopped acquisition")
            if self.script_manager:
                self.script_manager.on_acquisition_stop()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_stop()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_stop()

    def _sequence_get_channel_value(self, channel: str) -> Any:
        """Callback for sequence to get channel value"""
        with self.values_lock:
            return self.channel_values.get(channel)

    def _sequence_event_handler(self, event_type: str, sequence):
        """Handle sequence events and publish status"""
        base = self.get_topic_base()

        # Publish sequence status
        payload = {
            "event": event_type,
            "sequence_id": sequence.id,
            "sequence_name": sequence.name,
            "state": sequence.state.value if hasattr(sequence.state, 'value') else sequence.state,
            "current_step": sequence.current_step_index,
            "total_steps": len(sequence.steps),
            "progress": round(sequence.current_step_index / len(sequence.steps) * 100) if sequence.steps else 0,
            "timestamp": datetime.now().isoformat()
        }

        if sequence.error_message:
            payload["error"] = sequence.error_message

        self.mqtt_client.publish(
            f"{base}/sequence/status",
            json.dumps(payload)
        )

        # Also update system status
        self._publish_system_status()

    def _sequence_log_message(self, message: str):
        """Callback for sequence log messages"""
        base = self.get_topic_base()
        payload = {
            "type": "sequence_log",
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        self.mqtt_client.publish(f"{base}/sequence/log", json.dumps(payload))

    def _scheduled_start_acquire(self):
        """Callback for scheduler to start acquisition"""
        if not self.acquiring:
            self.acquiring = True
            logger.info("Scheduler started acquisition")
            if self.script_manager:
                self.script_manager.on_acquisition_start()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_start()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_start()

    def _scheduled_stop_acquire(self):
        """Callback for scheduler to stop acquisition"""
        if self.acquiring:
            self.acquiring = False
            logger.info("Scheduler stopped acquisition")
            if self.script_manager:
                self.script_manager.on_acquisition_stop()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_stop()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_stop()

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

        # MQTT Authentication (if configured)
        mqtt_user = os.environ.get('MQTT_USERNAME', getattr(self.config.system, 'mqtt_username', None))
        mqtt_pass = os.environ.get('MQTT_PASSWORD', getattr(self.config.system, 'mqtt_password', None))
        if mqtt_user and mqtt_pass:
            self.mqtt_client.username_pw_set(mqtt_user, mqtt_pass)
            logger.info(f"MQTT authentication enabled for user: {mqtt_user}")

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
            base = self.get_topic_base()
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
            client.subscribe(f"{base}/config/apply")  # Reinitialize tasks without starting acquisition
            client.subscribe(f"{base}/config/channel/update")
            client.subscribe(f"{base}/config/channel/create")
            client.subscribe(f"{base}/config/channel/delete")
            client.subscribe(f"{base}/config/channel/bulk-create")

            # Subscribe to schedule topics
            client.subscribe(f"{base}/schedule/set")
            client.subscribe(f"{base}/schedule/enable")
            client.subscribe(f"{base}/schedule/disable")
            client.subscribe(f"{base}/schedule/status")

            # Subscribe to sequence topics
            client.subscribe(f"{base}/sequence/start")
            client.subscribe(f"{base}/sequence/pause")
            client.subscribe(f"{base}/sequence/resume")
            client.subscribe(f"{base}/sequence/abort")
            client.subscribe(f"{base}/sequence/add")
            client.subscribe(f"{base}/sequence/remove")
            client.subscribe(f"{base}/sequence/list")
            client.subscribe(f"{base}/sequence/get")

            # Subscribe to discovery topics
            client.subscribe(f"{base}/discovery/scan")

            # Subscribe to alarm control topics
            client.subscribe(f"{base}/alarm/acknowledge")
            client.subscribe(f"{base}/alarm/clear")
            client.subscribe(f"{base}/alarm/reset-latched")

            # Subscribe to channel control topics
            client.subscribe(f"{base}/channel/reset")

            # Subscribe to output control topics
            client.subscribe(f"{base}/output/set")

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

            # Subscribe to project management topics
            client.subscribe(f"{base}/project/list")
            client.subscribe(f"{base}/project/load")
            client.subscribe(f"{base}/project/import")  # Import from any path
            client.subscribe(f"{base}/project/import/json")  # Import JSON directly
            client.subscribe(f"{base}/project/close")   # Close to empty state
            client.subscribe(f"{base}/project/save")
            client.subscribe(f"{base}/project/delete")
            client.subscribe(f"{base}/project/get")
            client.subscribe(f"{base}/project/get-current")

            # Subscribe to user variable/playground topics
            client.subscribe(f"{base}/variables/create")
            client.subscribe(f"{base}/variables/update")
            client.subscribe(f"{base}/variables/delete")
            client.subscribe(f"{base}/variables/set")
            client.subscribe(f"{base}/variables/reset")
            client.subscribe(f"{base}/variables/get")
            client.subscribe(f"{base}/variables/list")
            client.subscribe(f"{base}/variables/timer/start")
            client.subscribe(f"{base}/variables/timer/stop")

            # Subscribe to test session topics
            client.subscribe(f"{base}/test-session/start")
            client.subscribe(f"{base}/test-session/stop")
            client.subscribe(f"{base}/test-session/config")
            client.subscribe(f"{base}/test-session/status")

            # Subscribe to backend script execution topics
            client.subscribe(f"{base}/script/start")
            client.subscribe(f"{base}/script/stop")
            client.subscribe(f"{base}/script/add")
            client.subscribe(f"{base}/script/update")
            client.subscribe(f"{base}/script/remove")
            client.subscribe(f"{base}/script/list")
            client.subscribe(f"{base}/script/get")
            client.subscribe(f"{base}/script/status")

            # Subscribe to notebook topics
            client.subscribe(f"{base}/notebook/save")
            client.subscribe(f"{base}/notebook/load")

            # Subscribe to chassis/device management topics (Modbus)
            client.subscribe(f"{base}/chassis/add")
            client.subscribe(f"{base}/chassis/update")
            client.subscribe(f"{base}/chassis/delete")
            client.subscribe(f"{base}/chassis/test")

            # Subscribe to data source management topics (REST API, OPC-UA, etc.)
            client.subscribe(f"{base}/datasource/add")
            client.subscribe(f"{base}/datasource/update")
            client.subscribe(f"{base}/datasource/delete")
            client.subscribe(f"{base}/datasource/test")
            client.subscribe(f"{base}/datasource/list")

            # Subscribe to user management topics (admin only)
            client.subscribe(f"{base}/users/list")
            client.subscribe(f"{base}/users/create")
            client.subscribe(f"{base}/users/update")
            client.subscribe(f"{base}/users/delete")
            client.subscribe(f"{base}/users/sessions")

            # Subscribe to audit trail topics
            client.subscribe(f"{base}/audit/query")
            client.subscribe(f"{base}/audit/export")

            # Subscribe to archive management topics
            client.subscribe(f"{base}/archive/list")
            client.subscribe(f"{base}/archive/retrieve")
            client.subscribe(f"{base}/archive/verify")

            # Publish connection status
            self._publish_system_status()

            # Publish channel configuration
            self._publish_channel_config()

            # Publish user variable configuration
            self._publish_user_variables_config()
            self._publish_test_session_status()
            # Publish formula blocks
            self._publish_formula_blocks_config()

        else:
            logger.error(f"MQTT connection failed with code {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT disconnection callback"""
        logger.warning(f"Disconnected from MQTT broker (rc={reason_code})")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        topic = msg.topic
        base = self.get_topic_base()

        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode failed for {topic}: {e}")
            payload = msg.payload.decode()

        logger.debug(f"Received message on {topic}: {payload}")

        # Extract request_id from payload if present (for command acknowledgment)
        request_id = None
        if isinstance(payload, dict):
            request_id = payload.get('request_id')

        # === SYSTEM CONTROL ===
        if topic == f"{base}/system/acquire/start":
            self._handle_acquire_start(request_id)
        elif topic == f"{base}/system/acquire/stop":
            self._handle_acquire_stop(request_id)
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
            self._handle_auth_logout(payload)
        elif topic == f"{base}/auth/status/request":
            self._publish_auth_status()

        # === USER MANAGEMENT (Admin only) ===
        elif topic == f"{base}/users/list":
            self._handle_users_list(payload)
        elif topic == f"{base}/users/create":
            self._handle_users_create(payload)
        elif topic == f"{base}/users/update":
            self._handle_users_update(payload)
        elif topic == f"{base}/users/delete":
            self._handle_users_delete(payload)
        elif topic == f"{base}/users/sessions":
            self._handle_users_sessions(payload)

        # === AUDIT TRAIL ===
        elif topic == f"{base}/audit/query":
            self._handle_audit_query(payload)
        elif topic == f"{base}/audit/export":
            self._handle_audit_export(payload)

        # === ARCHIVE MANAGEMENT ===
        elif topic == f"{base}/archive/list":
            self._handle_archive_list(payload)
        elif topic == f"{base}/archive/retrieve":
            self._handle_archive_retrieve(payload)
        elif topic == f"{base}/archive/verify":
            self._handle_archive_verify(payload)

        # === CONFIG MANAGEMENT ===
        elif topic == f"{base}/config/get":
            self._handle_config_get()
        elif topic == f"{base}/config/save":
            self._handle_config_save(payload)
        elif topic == f"{base}/config/load":
            self._handle_config_load(payload)
        elif topic == f"{base}/config/list":
            self._handle_config_list()
        elif topic == f"{base}/config/apply":
            self._handle_config_apply(payload)
        elif topic == f"{base}/config/channel/update":
            self._handle_channel_update(payload)
        elif topic == f"{base}/config/channel/create":
            self._handle_channel_create(payload)
        elif topic == f"{base}/config/channel/delete":
            self._handle_channel_delete(payload)
        elif topic == f"{base}/config/channel/bulk-create":
            self._handle_channel_bulk_create(payload)

        # === SCHEDULE MANAGEMENT ===
        elif topic == f"{base}/schedule/set":
            self._handle_schedule_set(payload)
        elif topic == f"{base}/schedule/enable":
            self._handle_schedule_enable()
        elif topic == f"{base}/schedule/disable":
            self._handle_schedule_disable()
        elif topic == f"{base}/schedule/status":
            self._publish_schedule_status()

        # === SEQUENCE CONTROL ===
        elif topic == f"{base}/sequence/start":
            self._handle_sequence_start(payload)
        elif topic == f"{base}/sequence/pause":
            self._handle_sequence_pause(payload)
        elif topic == f"{base}/sequence/resume":
            self._handle_sequence_resume(payload)
        elif topic == f"{base}/sequence/abort":
            self._handle_sequence_abort(payload)
        elif topic == f"{base}/sequence/add":
            self._handle_sequence_add(payload)
        elif topic == f"{base}/sequence/remove":
            self._handle_sequence_remove(payload)
        elif topic == f"{base}/sequence/list":
            self._handle_sequence_list()
        elif topic == f"{base}/sequence/get":
            self._handle_sequence_get(payload)

        # === DEVICE DISCOVERY ===
        elif topic == f"{base}/discovery/scan":
            self._handle_discovery_scan()

        # === ALARM CONTROL ===
        elif topic == f"{base}/alarm/acknowledge":
            self._handle_alarm_acknowledge(payload)
        elif topic == f"{base}/alarm/clear":
            self._handle_alarm_clear(payload)
        elif topic == f"{base}/alarm/reset-latched":
            self._handle_alarm_reset_latched()
        elif topic == f"{base}/alarm/reset":
            self._handle_alarm_reset(payload)
        elif topic == f"{base}/alarm/shelve":
            self._handle_alarm_shelve(payload)
        elif topic == f"{base}/alarm/unshelve":
            self._handle_alarm_unshelve(payload)

        # === CHANNEL CONTROL ===
        elif topic == f"{base}/channel/reset":
            self._handle_channel_reset(payload)

        # === OUTPUT CONTROL ===
        elif topic == f"{base}/output/set":
            self._handle_output_set(payload)

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

        # === PROJECT FILE MANAGEMENT ===
        elif topic == f"{base}/project/list":
            self._handle_project_list()
        elif topic == f"{base}/project/load":
            self._handle_project_load(payload)
        elif topic == f"{base}/project/save":
            self._handle_project_save(payload)
        elif topic == f"{base}/project/delete":
            self._handle_project_delete(payload)
        elif topic == f"{base}/project/get":
            self._handle_project_get()
        elif topic == f"{base}/project/get-current":
            self._handle_project_get_current()
        elif topic == f"{base}/project/import":
            self._handle_project_import(payload)
        elif topic == f"{base}/project/import/json":
            self._handle_project_import_json(payload)
        elif topic == f"{base}/project/close":
            self._handle_project_close(payload)

        # === USER VARIABLES / PLAYGROUND ===
        elif topic == f"{base}/variables/create":
            self._handle_variable_create(payload)
        elif topic == f"{base}/variables/update":
            self._handle_variable_update(payload)
        elif topic == f"{base}/variables/delete":
            self._handle_variable_delete(payload)
        elif topic == f"{base}/variables/set":
            self._handle_variable_set(payload)
        elif topic == f"{base}/variables/reset":
            self._handle_variable_reset(payload)
        elif topic == f"{base}/variables/get":
            self._handle_variable_get(payload)
        elif topic == f"{base}/variables/list":
            self._handle_variable_list()
        elif topic == f"{base}/variables/timer/start":
            self._handle_timer_start(payload)
        elif topic == f"{base}/variables/timer/stop":
            self._handle_timer_stop(payload)

        # === TEST SESSION ===
        elif topic == f"{base}/test-session/start":
            self._handle_test_session_start(payload)
        elif topic == f"{base}/test-session/stop":
            self._handle_test_session_stop()
        elif topic == f"{base}/test-session/config":
            self._handle_test_session_config(payload)
        elif topic == f"{base}/test-session/status":
            self._publish_test_session_status()

        # === BACKEND SCRIPT EXECUTION ===
        elif topic == f"{base}/script/start":
            self._handle_script_start(payload)
        elif topic == f"{base}/script/stop":
            self._handle_script_stop(payload)
        elif topic == f"{base}/script/add":
            self._handle_script_add(payload)
        elif topic == f"{base}/script/update":
            self._handle_script_update(payload)
        elif topic == f"{base}/script/remove":
            self._handle_script_remove(payload)
        elif topic == f"{base}/script/list":
            self._handle_script_list()
        elif topic == f"{base}/script/get":
            self._handle_script_get(payload)
        # NOTE: Do NOT handle script/status here - it's our own outbound topic
        # Handling it would cause an infinite publish loop

        # === NOTEBOOK ===
        elif topic == f"{base}/notebook/save":
            self._handle_notebook_save(payload)
        elif topic == f"{base}/notebook/load":
            self._handle_notebook_load(payload)

        # === FORMULA BLOCKS ===
        elif topic == f"{base}/formulas/create":
            self._handle_formula_create(payload)
        elif topic == f"{base}/formulas/update":
            self._handle_formula_update(payload)
        elif topic == f"{base}/formulas/delete":
            self._handle_formula_delete(payload)
        elif topic == f"{base}/formulas/list":
            self._publish_formula_blocks_config()

        # === CHASSIS/DEVICE MANAGEMENT (Modbus) ===
        elif topic == f"{base}/chassis/add":
            self._handle_chassis_add(payload)
        elif topic == f"{base}/chassis/update":
            self._handle_chassis_update(payload)
        elif topic == f"{base}/chassis/delete":
            self._handle_chassis_delete(payload)
        elif topic == f"{base}/chassis/test":
            self._handle_chassis_test(payload)

        # === DATA SOURCE MANAGEMENT (REST API, OPC-UA, etc.) ===
        elif topic == f"{base}/datasource/add":
            self._handle_datasource_add(payload)
        elif topic == f"{base}/datasource/update":
            self._handle_datasource_update(payload)
        elif topic == f"{base}/datasource/delete":
            self._handle_datasource_delete(payload)
        elif topic == f"{base}/datasource/test":
            self._handle_datasource_test(payload)
        elif topic == f"{base}/datasource/list":
            self._handle_datasource_list()

        # === CHANNEL COMMANDS ===
        elif topic.startswith(f"{base}/commands/"):
            channel_name = topic.split('/')[-1]
            self._handle_command(channel_name, payload)

        # Handle legacy config reload
        elif topic == f"{base}/config/reload":
            logger.info("Reloading configuration...")
            # If a project is loaded, reload it instead of system.ini
            if self.current_project_path and self.current_project_path.exists():
                logger.info(f"Reloading project: {self.current_project_path.name}")
                self._load_project_from_path(self.current_project_path, publish=False)
            else:
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

        # Determine which backend handles this channel
        channel = self.config.channels.get(channel_name)
        is_modbus = channel and channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)

        if is_modbus and self.modbus_reader:
            self.modbus_reader.write_channel(channel_name, value)
        elif self.simulator:
            self.simulator.write_channel(channel_name, value)
        elif self.hardware_reader:
            self.hardware_reader.write_channel(channel_name, value)

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

    def _handle_acquire_start(self, request_id: Optional[str] = None):
        """Start data acquisition with command acknowledgment and state validation"""
        try:
            # STATE VALIDATION: Check current state
            logger.info(f"[STATE MACHINE] Acquisition start requested (current state: acquiring={self.acquiring})")

            if self.acquiring:
                logger.warning("[STATE MACHINE] Acquisition start rejected - already running")
                self._publish_command_ack("acquire/start", request_id, False, "Already acquiring")
                return

            # STATE TRANSITION: stopped → starting
            logger.info("[STATE MACHINE] Transitioning: stopped → starting")

            # Only reload from system.ini if no project is loaded
            # If a project is loaded, its config is already applied and should not be overwritten
            if self.current_project_path:
                logger.info(f"Using project config: {self.current_project_path.name} ({len(self.config.channels)} channels)")
            else:
                # No project loaded - reload from system.ini to pick up any changes
                logger.info("No project loaded - reloading configuration from system.ini...")
                self._load_config()
            self._publish_channel_config()

            # STATE TRANSITION: starting → acquiring
            logger.info("[STATE MACHINE] Transitioning: starting → acquiring")
            self.acquiring = True
            logger.info(f"[STATE MACHINE] Acquisition started successfully (acquiring={self.acquiring})")

            # Notify automation engines
            if self.script_manager:
                self.script_manager.on_acquisition_start()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_start()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_start()

            # IEC 61511: Lock safety configuration during acquisition
            if self.project_manager:
                self.project_manager.lock_safety_config("Acquisition running")

            # Audit trail: Log acquisition start
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.SESSION_START,
                    user=self.auth_username or "system",
                    description="Data acquisition started",
                    details={"channels": len(self.config.channels) if self.config else 0}
                )

            self._publish_system_status()
            self._publish_command_ack("acquire/start", request_id, True)

        except Exception as e:
            logger.error(f"[STATE MACHINE] Error starting acquisition: {e}", exc_info=True)
            # STATE ROLLBACK: Ensure we're in stopped state on error
            self.acquiring = False
            # Unlock safety config on failure
            if self.project_manager:
                self.project_manager.unlock_safety_config()
            logger.error(f"[STATE MACHINE] Rolled back to stopped state (acquiring={self.acquiring})")
            self._publish_command_ack("acquire/start", request_id, False, str(e))

    def _handle_acquire_stop(self, request_id: Optional[str] = None):
        """Stop data acquisition with command acknowledgment and state validation"""
        try:
            # STATE VALIDATION: Check current state
            logger.info(f"[STATE MACHINE] Acquisition stop requested (current state: acquiring={self.acquiring}, recording={self.recording})")

            if not self.acquiring:
                logger.warning("[STATE MACHINE] Acquisition stop rejected - not running")
                self._publish_command_ack("acquire/stop", request_id, False, "Not acquiring")
                return

            # STATE TRANSITION: acquiring → stopping
            logger.info("[STATE MACHINE] Transitioning: acquiring → stopping")

            # First stop recording if active (cascade stop)
            if self.recording:
                logger.info("[STATE MACHINE] Cascading stop to recording")
                self._handle_recording_stop()

            # STATE TRANSITION: stopping → stopped
            logger.info("[STATE MACHINE] Transitioning: stopping → stopped")
            self.acquiring = False
            logger.info(f"[STATE MACHINE] Acquisition stopped successfully (acquiring={self.acquiring})")

            # Notify automation engines
            if self.script_manager:
                self.script_manager.on_acquisition_stop()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_stop()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_stop()

            # IEC 61511: Unlock safety configuration after acquisition stops
            if self.project_manager:
                self.project_manager.unlock_safety_config()

            # Audit trail: Log acquisition stop
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.SESSION_END,
                    user=self.auth_username or "system",
                    description="Data acquisition stopped"
                )

            self._publish_system_status()
            self._publish_command_ack("acquire/stop", request_id, True)

        except Exception as e:
            logger.error(f"[STATE MACHINE] Error stopping acquisition: {e}", exc_info=True)
            self._publish_command_ack("acquire/stop", request_id, False, str(e))

    def _handle_recording_start(self, payload: Any):
        """Start data recording with state validation"""
        # STATE VALIDATION: Check prerequisites
        logger.info(f"[STATE MACHINE] Recording start requested (acquiring={self.acquiring}, recording={self.recording})")

        if not self.acquiring:
            logger.error("[STATE MACHINE] Recording start rejected - acquisition not running (PREREQUISITE FAILED)")
            self._publish_recording_response(False, "Acquisition must be running to start recording")
            return

        if self.recording_manager.recording:
            logger.warning("[STATE MACHINE] Recording start rejected - already recording")
            self._publish_recording_response(False, "Recording already active")
            return

        # STATE TRANSITION: idle → starting
        logger.info("[STATE MACHINE] Recording transitioning: idle → starting")

        # Get optional filename from payload
        filename = None
        if isinstance(payload, dict):
            filename = payload.get('filename')

            # Also apply any config from payload
            config_updates = {k: v for k, v in payload.items() if k != 'filename'}
            if config_updates:
                logger.info(f"[STATE MACHINE] Applying recording config updates: {list(config_updates.keys())}")
                self.recording_manager.configure(config_updates)

        # STATE TRANSITION: starting → recording
        if self.recording_manager.start(filename):
            self.recording = True
            self.recording_start_time = self.recording_manager.recording_start_time
            self.recording_filename = self.recording_manager.current_file.name if self.recording_manager.current_file else None
            logger.info(f"[STATE MACHINE] Recording started successfully (file: {self.recording_filename})")
            self._publish_recording_response(True, f"Recording started: {self.recording_filename}")
            self._publish_system_status()
        else:
            logger.error("[STATE MACHINE] Recording start failed - manager returned False")
            self._publish_recording_response(False, "Failed to start recording")

    def _handle_recording_stop(self):
        """Stop data recording with state validation"""
        # STATE VALIDATION: Check current state
        logger.info(f"[STATE MACHINE] Recording stop requested (recording={self.recording})")

        if not self.recording_manager.recording:
            logger.warning("[STATE MACHINE] Recording stop rejected - not recording")
            self._publish_recording_response(False, "Recording not active")
            return

        # STATE TRANSITION: recording → stopping
        logger.info("[STATE MACHINE] Recording transitioning: recording → stopping")
        filename_for_log = self.recording_filename

        # STATE TRANSITION: stopping → idle
        if self.recording_manager.stop():
            self.recording = False
            self.recording_start_time = None
            self.recording_filename = None
            logger.info(f"[STATE MACHINE] Recording stopped successfully (file: {filename_for_log})")
            self._publish_recording_response(True, "Recording stopped")
            self._publish_system_status()
        else:
            logger.error("[STATE MACHINE] Recording stop failed - manager returned False")
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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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

    # =========================================================================
    # HEARTBEAT AND COMMAND ACKNOWLEDGMENT
    # =========================================================================

    def _heartbeat_loop(self):
        """Heartbeat loop - publishes health status periodically"""
        logger.info(f"Starting heartbeat loop at {1/self._heartbeat_interval:.1f} Hz")

        while not self._shutdown_requested.wait(timeout=self._heartbeat_interval):
            if not self._running.is_set():
                continue

            try:
                self._heartbeat_sequence += 1
                uptime = 0.0
                if self._start_time:
                    uptime = (datetime.now() - self._start_time).total_seconds()

                base = self.get_topic_base()
                payload = {
                    "sequence": self._heartbeat_sequence,
                    "timestamp": datetime.now().isoformat(),
                    "acquiring": self.acquiring,
                    "recording": self.recording,
                    "thread_health": {
                        "scan": self.scan_thread.is_alive() if self.scan_thread else False,
                        "publish": self.publish_thread.is_alive() if self.publish_thread else False,
                        "heartbeat": True  # Obviously true if we're running
                    },
                    "uptime_seconds": round(uptime, 1),
                    "scan_rate_actual_hz": round(1000 / max(self.last_scan_dt_ms, 0.1), 1) if self.last_scan_dt_ms > 0 else 0,
                    "publish_rate_actual_hz": round(1000 / max(self.last_publish_dt_ms, 0.1), 1) if self.last_publish_dt_ms > 0 else 0
                }

                self.mqtt_client.publish(
                    f"{base}/heartbeat",
                    json.dumps(payload),
                    qos=1
                )

            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

        logger.info("Heartbeat loop stopped")

    def _publish_command_ack(self, command: str, request_id: Optional[str],
                              success: bool, error: Optional[str] = None):
        """Publish command acknowledgment to dashboard"""
        if not self.mqtt_client:
            return

        base = self.get_topic_base()
        payload = {
            "command": command,
            "request_id": request_id,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        if error:
            payload["error"] = error

        self.mqtt_client.publish(
            f"{base}/command/ack",
            json.dumps(payload),
            qos=1
        )

    def _publish_system_status(self):
        """Publish comprehensive system status with resource monitoring"""
        base = self.get_topic_base()

        # Update resource monitoring
        if self._resource_monitor_enabled and self._process:
            try:
                self._cpu_percent = self._process.cpu_percent(interval=None)
                mem_info = self._process.memory_info()
                self._memory_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
            except Exception as e:
                logger.warning(f"Resource monitoring error: {e}")

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
            # Multi-node identification
            "node_id": self.config.system.node_id,
            "node_name": self.config.system.node_name,
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
            "config_path": self.config_path,
            # Sequence status
            "sequences_active": self._get_active_sequence_count(),
            "sequences_total": len(self.sequence_manager.sequences) if self.sequence_manager else 0,
            # Resource monitoring
            "cpu_percent": round(self._cpu_percent, 1) if self._resource_monitor_enabled else None,
            "memory_mb": round(self._memory_mb, 1) if self._resource_monitor_enabled else None,
            "resource_monitoring": self._resource_monitor_enabled
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
    # AUTHENTICATION HANDLERS (Session-based with UserSessionManager)
    # =========================================================================

    @property
    def authenticated(self) -> bool:
        """Check if current session is valid"""
        if not self.current_session_id or not self.user_session_manager:
            return False
        session = self.user_session_manager.validate_session(self.current_session_id)
        return session is not None

    @property
    def auth_username(self) -> Optional[str]:
        """Get current authenticated username"""
        if not self.current_session_id or not self.user_session_manager:
            return None
        session = self.user_session_manager.validate_session(self.current_session_id)
        return session.username if session else None

    def _has_permission(self, permission: Permission) -> bool:
        """Check if current session has a specific permission"""
        if not self.current_session_id or not self.user_session_manager:
            return False
        return self.user_session_manager.has_permission(self.current_session_id, permission)

    def _handle_auth_login(self, payload: Any):
        """Handle login request using UserSessionManager"""
        if not isinstance(payload, dict):
            self._publish_auth_status(error="Invalid login payload")
            return

        if not self.user_session_manager:
            self._publish_auth_status(error="User session manager not initialized")
            return

        username = payload.get('username', '')
        password = payload.get('password', '')
        source_ip = payload.get('source_ip', 'dashboard')

        # Use UserSessionManager for proper authentication
        session = self.user_session_manager.authenticate(
            username=username,
            password=password,
            source_ip=source_ip,
            user_agent="NISystem Dashboard"
        )

        if session:
            logger.info(f"User '{username}' authenticated (role: {session.role.value})")
            self.current_session_id = session.session_id
            self.current_user_role = session.role.value

            # Log to audit trail
            if self.audit_trail:
                self.audit_trail.log_event(
                    AuditEventType.USER_LOGIN,
                    username=username,
                    details={"role": session.role.value, "source_ip": source_ip}
                )

            self._publish_auth_status()
            self._publish_system_status()
        else:
            logger.warning(f"Failed login attempt for user '{username}'")
            self.current_session_id = None
            self.current_user_role = None

            # Log failed attempt to audit trail
            if self.audit_trail:
                self.audit_trail.log_event(
                    AuditEventType.USER_LOGIN_FAILED,
                    username=username,
                    details={"source_ip": source_ip}
                )

            self._publish_auth_status(error="Invalid credentials")

    def _handle_auth_logout(self, payload: Any = None):
        """Handle logout request"""
        username = self.auth_username
        if self.current_session_id and self.user_session_manager:
            self.user_session_manager.logout(self.current_session_id)

            # Log to audit trail
            if self.audit_trail and username:
                self.audit_trail.log_event(
                    AuditEventType.USER_LOGOUT,
                    username=username
                )

        logger.info(f"User '{username}' logged out")
        self.current_session_id = None
        self.current_user_role = None
        self._publish_auth_status()
        self._publish_system_status()

    def _publish_auth_status(self, error: Optional[str] = None):
        """Publish authentication status with role information"""
        base = self.get_topic_base()

        # Get user info if authenticated
        user_info = None
        permissions = []
        if self.current_session_id and self.user_session_manager:
            session = self.user_session_manager.validate_session(self.current_session_id)
            if session:
                user_info = self.user_session_manager.get_user_info(session.username)
                # Get permissions for this role
                from user_session import ROLE_PERMISSIONS, UserRole
                role = UserRole(session.role.value) if isinstance(session.role, UserRole) else session.role
                role_perms = ROLE_PERMISSIONS.get(role, set())
                permissions = [p.value for p in role_perms]

        status = {
            "authenticated": self.authenticated,
            "username": self.auth_username,
            "role": self.current_user_role,
            "permissions": permissions,
            "display_name": user_info.get('display_name') if user_info else None,
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
    # USER MANAGEMENT HANDLERS (Admin only)
    # =========================================================================

    def _handle_users_list(self, payload: Any = None):
        """List all users (admin only)"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.MANAGE_USERS):
            self.mqtt_client.publish(
                f"{base}/users/list/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if self.user_session_manager:
            users = self.user_session_manager.list_users()
            self.mqtt_client.publish(
                f"{base}/users/list/response",
                json.dumps({"success": True, "users": users})
            )
        else:
            self.mqtt_client.publish(
                f"{base}/users/list/response",
                json.dumps({"success": False, "error": "User manager not available"})
            )

    def _handle_users_create(self, payload: Any):
        """Create a new user (admin only)"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.MANAGE_USERS):
            self.mqtt_client.publish(
                f"{base}/users/create/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(
                f"{base}/users/create/response",
                json.dumps({"success": False, "error": "Invalid payload"})
            )
            return

        username = payload.get('username')
        password = payload.get('password')
        role = payload.get('role', 'operator')
        display_name = payload.get('display_name', '')
        email = payload.get('email', '')

        if not username or not password:
            self.mqtt_client.publish(
                f"{base}/users/create/response",
                json.dumps({"success": False, "error": "Username and password required"})
            )
            return

        if self.user_session_manager:
            from user_session import UserRole
            try:
                user_role = UserRole(role)
            except ValueError:
                user_role = UserRole.OPERATOR

            user = self.user_session_manager.create_user(
                username=username,
                password=password,
                role=user_role,
                display_name=display_name,
                email=email
            )

            if user:
                # Log to audit trail
                if self.audit_trail:
                    self.audit_trail.log_event(
                        AuditEventType.CONFIG_CHANGE,
                        username=self.auth_username,
                        details={"action": "user_created", "new_user": username, "role": role}
                    )

                self.mqtt_client.publish(
                    f"{base}/users/create/response",
                    json.dumps({"success": True, "message": f"User '{username}' created"})
                )
            else:
                self.mqtt_client.publish(
                    f"{base}/users/create/response",
                    json.dumps({"success": False, "error": f"User '{username}' already exists"})
                )

    def _handle_users_update(self, payload: Any):
        """Update a user (admin only)"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.MANAGE_USERS):
            self.mqtt_client.publish(
                f"{base}/users/update/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(
                f"{base}/users/update/response",
                json.dumps({"success": False, "error": "Invalid payload"})
            )
            return

        username = payload.get('username')
        if not username:
            self.mqtt_client.publish(
                f"{base}/users/update/response",
                json.dumps({"success": False, "error": "Username required"})
            )
            return

        # Build update kwargs
        update_fields = {}
        if 'password' in payload:
            update_fields['password'] = payload['password']
        if 'role' in payload:
            update_fields['role'] = payload['role']
        if 'display_name' in payload:
            update_fields['display_name'] = payload['display_name']
        if 'email' in payload:
            update_fields['email'] = payload['email']
        if 'enabled' in payload:
            update_fields['enabled'] = payload['enabled']

        if self.user_session_manager and update_fields:
            success = self.user_session_manager.update_user(username, **update_fields)

            if success:
                # Log to audit trail
                if self.audit_trail:
                    self.audit_trail.log_event(
                        AuditEventType.CONFIG_CHANGE,
                        username=self.auth_username,
                        details={"action": "user_updated", "target_user": username, "fields": list(update_fields.keys())}
                    )

                self.mqtt_client.publish(
                    f"{base}/users/update/response",
                    json.dumps({"success": True, "message": f"User '{username}' updated"})
                )
            else:
                self.mqtt_client.publish(
                    f"{base}/users/update/response",
                    json.dumps({"success": False, "error": f"User '{username}' not found"})
                )

    def _handle_users_delete(self, payload: Any):
        """Delete a user (admin only)"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.MANAGE_USERS):
            self.mqtt_client.publish(
                f"{base}/users/delete/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(
                f"{base}/users/delete/response",
                json.dumps({"success": False, "error": "Invalid payload"})
            )
            return

        username = payload.get('username')
        if not username:
            self.mqtt_client.publish(
                f"{base}/users/delete/response",
                json.dumps({"success": False, "error": "Username required"})
            )
            return

        # Prevent self-deletion
        if username == self.auth_username:
            self.mqtt_client.publish(
                f"{base}/users/delete/response",
                json.dumps({"success": False, "error": "Cannot delete your own account"})
            )
            return

        if self.user_session_manager:
            success = self.user_session_manager.delete_user(username)

            if success:
                # Log to audit trail
                if self.audit_trail:
                    self.audit_trail.log_event(
                        AuditEventType.CONFIG_CHANGE,
                        username=self.auth_username,
                        details={"action": "user_deleted", "deleted_user": username}
                    )

                self.mqtt_client.publish(
                    f"{base}/users/delete/response",
                    json.dumps({"success": True, "message": f"User '{username}' deleted"})
                )
            else:
                self.mqtt_client.publish(
                    f"{base}/users/delete/response",
                    json.dumps({"success": False, "error": f"User '{username}' not found"})
                )

    def _handle_users_sessions(self, payload: Any = None):
        """Get active sessions (admin only)"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.MANAGE_USERS):
            self.mqtt_client.publish(
                f"{base}/users/sessions/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if self.user_session_manager:
            sessions = self.user_session_manager.get_active_sessions()
            self.mqtt_client.publish(
                f"{base}/users/sessions/response",
                json.dumps({"success": True, "sessions": sessions})
            )

    # =========================================================================
    # AUDIT TRAIL HANDLERS
    # =========================================================================

    def _handle_audit_query(self, payload: Any):
        """Query audit trail events"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.VIEW_AUDIT):
            self.mqtt_client.publish(
                f"{base}/audit/query/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not self.audit_trail:
            self.mqtt_client.publish(
                f"{base}/audit/query/response",
                json.dumps({"success": False, "error": "Audit trail not available"})
            )
            return

        # Parse query parameters
        if not isinstance(payload, dict):
            payload = {}

        start_time = payload.get('start_time')
        end_time = payload.get('end_time')
        event_types = payload.get('event_types')
        username = payload.get('username')
        limit = payload.get('limit', 100)

        # Convert event types to enum if provided
        event_type_enums = None
        if event_types:
            event_type_enums = []
            for et in event_types:
                try:
                    event_type_enums.append(AuditEventType(et))
                except ValueError:
                    pass

        events = self.audit_trail.query_events(
            start_time=datetime.fromisoformat(start_time) if start_time else None,
            end_time=datetime.fromisoformat(end_time) if end_time else None,
            event_types=event_type_enums,
            username=username,
            limit=limit
        )

        self.mqtt_client.publish(
            f"{base}/audit/query/response",
            json.dumps({
                "success": True,
                "events": [e.to_dict() for e in events],
                "count": len(events)
            })
        )

    def _handle_audit_export(self, payload: Any):
        """Export audit trail to file"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.EXPORT_AUDIT):
            self.mqtt_client.publish(
                f"{base}/audit/export/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not self.audit_trail:
            self.mqtt_client.publish(
                f"{base}/audit/export/response",
                json.dumps({"success": False, "error": "Audit trail not available"})
            )
            return

        if not isinstance(payload, dict):
            payload = {}

        format_type = payload.get('format', 'json')
        start_time = payload.get('start_time')
        end_time = payload.get('end_time')

        try:
            filepath = self.audit_trail.export_events(
                format=format_type,
                start_time=datetime.fromisoformat(start_time) if start_time else None,
                end_time=datetime.fromisoformat(end_time) if end_time else None
            )

            self.mqtt_client.publish(
                f"{base}/audit/export/response",
                json.dumps({"success": True, "filepath": str(filepath)})
            )
        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/audit/export/response",
                json.dumps({"success": False, "error": str(e)})
            )

    # =========================================================================
    # ARCHIVE MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_archive_list(self, payload: Any):
        """List archived files"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.VIEW_AUDIT):
            self.mqtt_client.publish(
                f"{base}/archive/list/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not self.archive_manager:
            self.mqtt_client.publish(
                f"{base}/archive/list/response",
                json.dumps({"success": False, "error": "Archive manager not available"})
            )
            return

        if not isinstance(payload, dict):
            payload = {}

        content_type = payload.get('content_type')
        start_date = payload.get('start_date')
        end_date = payload.get('end_date')
        limit = payload.get('limit', 100)

        try:
            entries = self.archive_manager.list_archives(
                content_type=content_type,
                start_date=datetime.fromisoformat(start_date).date() if start_date else None,
                end_date=datetime.fromisoformat(end_date).date() if end_date else None,
                limit=limit
            )

            self.mqtt_client.publish(
                f"{base}/archive/list/response",
                json.dumps({
                    "success": True,
                    "archives": [e.to_dict() for e in entries],
                    "count": len(entries)
                })
            )
        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/archive/list/response",
                json.dumps({"success": False, "error": str(e)})
            )

    def _handle_archive_retrieve(self, payload: Any):
        """Retrieve an archived file"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.VIEW_AUDIT):
            self.mqtt_client.publish(
                f"{base}/archive/retrieve/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not self.archive_manager:
            self.mqtt_client.publish(
                f"{base}/archive/retrieve/response",
                json.dumps({"success": False, "error": "Archive manager not available"})
            )
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(
                f"{base}/archive/retrieve/response",
                json.dumps({"success": False, "error": "Invalid payload"})
            )
            return

        archive_id = payload.get('archive_id')
        if not archive_id:
            self.mqtt_client.publish(
                f"{base}/archive/retrieve/response",
                json.dumps({"success": False, "error": "Archive ID required"})
            )
            return

        try:
            retrieved_path = self.archive_manager.retrieve_archive(archive_id)

            if retrieved_path:
                self.mqtt_client.publish(
                    f"{base}/archive/retrieve/response",
                    json.dumps({
                        "success": True,
                        "filepath": str(retrieved_path),
                        "archive_id": archive_id
                    })
                )
            else:
                self.mqtt_client.publish(
                    f"{base}/archive/retrieve/response",
                    json.dumps({"success": False, "error": "Archive not found"})
                )
        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/archive/retrieve/response",
                json.dumps({"success": False, "error": str(e)})
            )

    def _handle_archive_verify(self, payload: Any):
        """Verify archive integrity"""
        base = self.get_topic_base()

        if not self._has_permission(Permission.VIEW_AUDIT):
            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({"success": False, "error": "Permission denied"})
            )
            return

        if not self.archive_manager:
            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({"success": False, "error": "Archive manager not available"})
            )
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({"success": False, "error": "Invalid payload"})
            )
            return

        archive_id = payload.get('archive_id')
        if not archive_id:
            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({"success": False, "error": "Archive ID required"})
            )
            return

        try:
            is_valid, message = self.archive_manager.verify_archive(archive_id)

            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({
                    "success": True,
                    "archive_id": archive_id,
                    "is_valid": is_valid,
                    "message": message
                })
            )
        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/archive/verify/response",
                json.dumps({"success": False, "error": str(e)})
            )

    # =========================================================================
    # CONFIG MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_config_get(self):
        """Return current configuration as JSON"""
        base = self.get_topic_base()

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
        base = self.get_topic_base()
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

    def _handle_config_apply(self, payload: Any):
        """Apply configuration changes - reinitialize hardware tasks without starting acquisition.

        This is the preferred way to apply config changes during development:
        1. Saves current config to disk
        2. Reloads config and reinitializes hardware readers
        3. Does NOT start acquisition (user must explicitly start)

        Payload options:
            restart_acquisition: bool (default False) - if True, restart acquisition after apply
        """
        base = self.get_topic_base()

        try:
            logger.info("Applying configuration changes...")

            # Parse options
            restart_acq = False
            if isinstance(payload, dict):
                restart_acq = payload.get('restart_acquisition', False)

            # Stop acquisition if running
            was_acquiring = self.acquiring
            if was_acquiring:
                logger.info("Stopping acquisition to apply config changes")
                self._stop_acquire()

            # Reload config (reinitializes hardware reader)
            # If a project is loaded, reload it instead of system.ini
            if self.current_project_path and self.current_project_path.exists():
                logger.info(f"Reloading project config: {self.current_project_path.name}")
                self._load_project_from_path(self.current_project_path, publish=False)
            else:
                self._load_config()

            # Publish updated channel config to frontend
            self._publish_channel_config()

            # Publish status update
            self._publish_status()

            # Optionally restart acquisition
            if restart_acq and was_acquiring:
                logger.info("Restarting acquisition after config apply")
                self._start_acquire()

            logger.info("Configuration applied successfully")
            self._publish_config_response(True, "Configuration applied - hardware tasks reinitialized")

        except Exception as e:
            logger.error(f"Failed to apply configuration: {e}")
            self._publish_config_response(False, f"Apply failed: {str(e)}")

    # =========================================================================
    # PROJECT FILE MANAGEMENT
    # =========================================================================

    def _get_projects_dir(self) -> Path:
        """Get or create the default projects directory (config/projects/)"""
        if self.projects_dir is None:
            config_dir = Path(self.config_path).parent
            self.projects_dir = config_dir / "projects"
            self.projects_dir.mkdir(parents=True, exist_ok=True)
        return self.projects_dir

    def _get_settings_path(self) -> Path:
        """Get path to settings file that stores last project path etc."""
        config_dir = Path(self.config_path).parent
        return config_dir / "nisystem_settings.json"

    def _save_last_project_path(self, project_path: Optional[Path]):
        """Save the last loaded project path to settings"""
        settings_path = self._get_settings_path()
        try:
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)

            # Always store absolute path to avoid working directory issues
            settings["last_project_path"] = str(project_path.resolve()) if project_path else None

            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
            logger.info(f"Saved last project path: {project_path}")
        except Exception as e:
            logger.warning(f"Could not save settings: {e}")

    def _load_last_project_path(self) -> Optional[Path]:
        """Load the last project path from settings"""
        settings_path = self._get_settings_path()
        try:
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                path_str = settings.get("last_project_path")
                if path_str:
                    return Path(path_str)
        except Exception as e:
            logger.warning(f"Could not load settings: {e}")
        return None

    def _try_load_last_project(self):
        """Try to load the last project on startup, fail gracefully to empty state

        Priority:
        1. Last used project (from settings file)
        2. Default project (from system.ini default_project setting)
        3. Empty state
        """
        # First try the last used project
        last_path = self._load_last_project_path()
        if last_path and last_path.exists():
            logger.info(f"Auto-loading last project: {last_path}")
            self._load_project_from_path(last_path, publish=False)
            return
        elif last_path:
            logger.warning(f"Last project not found: {last_path}")
            self._save_last_project_path(None)  # Clear invalid path

        # Fallback to default_project from system.ini
        if self.config and self.config.system.default_project:
            default_path = Path(self.config.system.default_project)
            if default_path.exists():
                logger.info(f"Loading default project from system.ini: {default_path}")
                self._load_project_from_path(default_path, publish=False)
                return
            else:
                logger.warning(f"Default project not found: {default_path}")

        # No project to load - clear alarm state to start fresh
        # Alarms are per-project, so with no project there should be no alarms
        if self.alarm_manager:
            self.alarm_manager.clear_all(clear_configs=True)

        logger.info("No project configured - starting with empty state")

    def _handle_project_list(self):
        """List available project files from default projects directory"""
        base = self.get_topic_base()
        projects_dir = self._get_projects_dir()

        projects = []
        current_name = self.current_project_path.name if self.current_project_path else None

        for f in projects_dir.glob("*.json"):
            try:
                with open(f, 'r') as fp:
                    data = json.load(fp)
                projects.append({
                    "filename": f.name,
                    "path": str(f),  # Full path for import
                    "name": data.get("name", f.stem),
                    "config": data.get("config", ""),
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "created": data.get("created", ""),
                    "active": f.name == current_name
                })
            except Exception as e:
                logger.warning(f"Could not read project file {f}: {e}")
                projects.append({
                    "filename": f.name,
                    "path": str(f),
                    "name": f.stem,
                    "config": "",
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "created": "",
                    "active": f.name == current_name,
                    "error": str(e)
                })

        self.mqtt_client.publish(
            f"{base}/project/list/response",
            json.dumps({"projects": projects})
        )

    def _load_project_from_path(self, project_path: Path, publish: bool = True) -> bool:
        """Core function to load a project from any path

        Supports two formats:
        1. New format: Project JSON contains embedded 'channels' and 'system' sections
        2. Legacy format: Project JSON contains 'config' field pointing to separate .ini file
        """
        base = self.get_topic_base()

        if not project_path.exists():
            if publish:
                self._publish_project_response(False, f"Project not found: {project_path}")
            return False

        try:
            with open(project_path, 'r') as f:
                project_data = json.load(f)

            # Validate project structure using project manager if available
            if self.project_manager and self.project_manager.validate_on_load:
                validation = self.project_manager.validate_project(project_data)
                if not validation.valid:
                    error_msg = "; ".join(validation.errors)
                    logger.warning(f"Project validation failed: {error_msg}")
                    if publish:
                        self._publish_project_response(False, f"Validation failed: {error_msg}")
                    return False

                # Log warnings but continue
                if validation.warnings:
                    for warning in validation.warnings:
                        logger.warning(f"Project load warning: {warning}")

            # Basic type check (fallback if no project manager)
            if project_data.get("type") != "nisystem-project":
                if publish:
                    self._publish_project_response(False, "Invalid project file format - missing 'type: nisystem-project'")
                return False

            # Check if acquisition is running - need to stop before changing config
            if self._acquiring.is_set():
                if publish:
                    self._publish_project_response(False, "Stop acquisition before loading project")
                return False

            # Check for new format (embedded channels) vs legacy format (separate .ini)
            has_embedded_channels = "channels" in project_data and project_data["channels"]

            if has_embedded_channels:
                # New format: Apply channels and system settings from project JSON
                logger.info(f"Loading project with embedded config: {len(project_data['channels'])} channels")
                if not self._apply_project_config(project_data):
                    if publish:
                        self._publish_project_response(False, "Failed to apply project configuration")
                    return False
            else:
                # Legacy format: Check if we need to switch config files
                project_config = project_data.get("config", "")
                if project_config and project_config != Path(self.config_path).name:
                    config_dir = Path(self.config_path).parent
                    new_config_path = config_dir / project_config

                    if new_config_path.exists():
                        self._handle_config_load({"filename": project_config})
                    else:
                        logger.warning(f"Project config {project_config} not found, using current config")

            # Store project data with FULL PATH
            self.current_project_path = project_path
            self.current_project_data = project_data

            # Update project manager state
            if self.project_manager:
                self.project_manager.current_path = project_path
                self.project_manager.current_data = project_data

            # Persist the path for next startup
            self._save_last_project_path(project_path)

            # Publish channel config so frontend gets updated channel list
            self._publish_channel_config()

            logger.info(f"Loaded project: {project_path}")

            # Audit trail: Log project load
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.PROJECT_LOAD,
                    user=self.auth_username or "system",
                    description=f"Project loaded: {project_path.name}",
                    details={
                        "path": str(project_path),
                        "version": project_data.get("version"),
                        "channels": len(project_data.get("channels", []))
                    }
                )

            if publish:
                self.mqtt_client.publish(
                    f"{base}/project/loaded",
                    json.dumps({
                        "success": True,
                        "filename": project_path.name,
                        "path": str(project_path),
                        "project": project_data
                    })
                )
            return True

        except json.JSONDecodeError as e:
            if publish:
                self._publish_project_response(False, f"Invalid JSON in project file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading project: {e}")
            if publish:
                self._publish_project_response(False, str(e))
            return False

    def _handle_project_load(self, payload: Any):
        """Load a project file - supports both filename (from default dir) and full path"""
        # Extract filename or path from payload
        filename = None
        full_path = None

        if isinstance(payload, dict):
            filename = payload.get("filename")
            full_path = payload.get("path")  # Full path takes priority
        elif isinstance(payload, str):
            # Could be filename or full path
            if '/' in payload or '\\' in payload:
                full_path = payload
            else:
                filename = payload

        # Determine the actual path to load
        if full_path:
            project_path = Path(full_path)
        elif filename:
            projects_dir = self._get_projects_dir()
            project_path = projects_dir / filename
        else:
            self._publish_project_response(False, "No filename or path provided")
            return

        self._load_project_from_path(project_path)

    def _handle_project_import(self, payload: Any):
        """Import a project from any location (USB, OneDrive, etc.)"""
        if isinstance(payload, dict):
            full_path = payload.get("path")
        elif isinstance(payload, str):
            full_path = payload
        else:
            self._publish_project_response(False, "Invalid payload - need 'path' to import")
            return

        if not full_path:
            self._publish_project_response(False, "No path provided for import")
            return

        project_path = Path(full_path)
        self._load_project_from_path(project_path)

    def _handle_project_import_json(self, payload: Any):
        """Import a project directly from JSON object (no file path needed)

        Used when frontend loads a project file and sends the parsed JSON.
        """
        if not isinstance(payload, dict):
            self._publish_project_response(False, "Invalid payload - expected JSON object")
            return

        # Validate project structure
        if payload.get("type") != "nisystem-project":
            self._publish_project_response(False, "Invalid project - missing 'type: nisystem-project'")
            return

        # Check if acquisition is running
        if self._acquiring.is_set():
            self._publish_project_response(False, "Cannot import project while acquisition is running")
            return

        try:
            # Apply the project configuration
            if self._apply_project_config(payload):
                self.current_project_data = payload
                self.current_project_path = None  # No file path - imported directly

                self._publish_channel_config()

                project_name = payload.get("name", "Imported Project")
                logger.info(f"Imported project from JSON: {project_name}")
                self._publish_project_response(True, f"Project '{project_name}' imported successfully")
            else:
                self._publish_project_response(False, "Failed to apply project configuration")
        except Exception as e:
            logger.error(f"Error importing project JSON: {e}")
            self._publish_project_response(False, str(e))

    def _handle_project_close(self, payload: Any):
        """Close current project and clear to empty state"""
        base = self.get_topic_base()

        self.current_project_path = None
        self.current_project_data = {}
        self._save_last_project_path(None)  # Clear persisted path

        # Clear alarm state - alarms are per-project, not global
        if self.alarm_manager:
            self.alarm_manager.clear_all(clear_configs=True)

        logger.info("Project closed - now in empty state")

        self.mqtt_client.publish(
            f"{base}/project/closed",
            json.dumps({"success": True, "message": "Project closed"})
        )

    def _handle_project_save(self, payload: Any):
        """Save project to file - saves to current path or specified path"""
        base = self.get_topic_base()

        if not isinstance(payload, dict):
            self._publish_project_response(False, "Invalid payload")
            return

        project_data = payload.get("data", {})
        save_path = payload.get("path")  # Optional full path
        filename = payload.get("filename")
        save_reason = payload.get("reason", "")  # Optional reason for audit

        # Determine where to save
        if save_path:
            project_path = Path(save_path)
        elif filename:
            # Ensure .json extension
            if not filename.endswith(".json"):
                filename += ".json"
            projects_dir = self._get_projects_dir()
            project_path = projects_dir / filename
        elif self.current_project_path:
            # Save to current project location
            project_path = self.current_project_path
        else:
            self._publish_project_response(False, "No save location specified")
            return

        # Add metadata
        project_data["type"] = "nisystem-project"
        project_data["version"] = "1.0"
        project_data["config"] = Path(self.config_path).name

        if not project_data.get("created"):
            project_data["created"] = datetime.now().isoformat()

        # Use project manager for backup, validation, and save
        if self.project_manager:
            status, message = self.project_manager.save_project(
                project_path=project_path,
                data=project_data,
                user=self.auth_username or "system",
                reason=save_reason
            )

            if status == ProjectStatus.SUCCESS:
                self.current_project_path = project_path
                self.current_project_data = project_data
                self._save_last_project_path(project_path)
                logger.info(f"Saved project: {project_path}")
                self._publish_project_response(True, message)
            elif status == ProjectStatus.VALIDATION_ERROR:
                logger.warning(f"Project validation failed: {message}")
                self._publish_project_response(False, f"Validation error: {message}")
            else:
                logger.error(f"Error saving project: {message}")
                self._publish_project_response(False, message)
        else:
            # Fallback if project manager not available
            try:
                project_path.parent.mkdir(parents=True, exist_ok=True)
                project_data["modified"] = datetime.now().isoformat()

                with open(project_path, 'w') as f:
                    json.dump(project_data, f, indent=2)

                self.current_project_path = project_path
                self.current_project_data = project_data
                self._save_last_project_path(project_path)

                logger.info(f"Saved project: {project_path}")
                self._publish_project_response(True, f"Project saved: {project_path.name}")

            except Exception as e:
                logger.error(f"Error saving project: {e}")
                self._publish_project_response(False, str(e))

    def _handle_project_delete(self, payload: Any):
        """Delete a project file"""
        delete_path = None
        if isinstance(payload, dict):
            delete_path = payload.get("path") or payload.get("filename")
        elif isinstance(payload, str):
            delete_path = payload

        if not delete_path:
            self._publish_project_response(False, "No path or filename provided")
            return

        # If just filename, look in default projects dir
        if '/' not in delete_path and '\\' not in delete_path:
            projects_dir = self._get_projects_dir()
            project_path = projects_dir / delete_path
        else:
            project_path = Path(delete_path)

        if not project_path.exists():
            self._publish_project_response(False, f"Project not found: {project_path}")
            return

        try:
            project_path.unlink()

            # Clear current project if it was the deleted one
            if self.current_project_path and self.current_project_path == project_path:
                self.current_project_path = None
                self.current_project_data = {}
                self._save_last_project_path(None)

            logger.info(f"Deleted project: {project_path}")
            self._publish_project_response(True, f"Project deleted: {project_path.name}")

        except Exception as e:
            logger.error(f"Error deleting project: {e}")
            self._publish_project_response(False, str(e))

    def _handle_project_get(self):
        """Get the current project data"""
        base = self.get_topic_base()

        self.mqtt_client.publish(
            f"{base}/project/current",
            json.dumps({
                "filename": self.current_project_path.name if self.current_project_path else None,
                "path": str(self.current_project_path) if self.current_project_path else None,
                "project": self.current_project_data if self.current_project_path else None
            })
        )

    def _handle_project_get_current(self):
        """Alias for _handle_project_get"""
        self._handle_project_get()

    # =========================================================================
    # NOTEBOOK HANDLERS
    # =========================================================================

    def _get_notebook_path(self) -> Path:
        """Get the path to the notebook file"""
        logs_dir = Path(self.config_path).parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir / "notebook.json"

    def _handle_notebook_save(self, payload: Any):
        """Save notebook data to file"""
        base = self.get_topic_base()

        if not isinstance(payload, dict):
            logger.warning("Invalid notebook save payload")
            return

        data = payload.get("data", {})
        notebook_path = self._get_notebook_path()

        try:
            with open(notebook_path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved notebook to {notebook_path}")
            self.mqtt_client.publish(f"{base}/notebook/saved", json.dumps({
                "success": True,
                "filename": str(notebook_path)
            }))

        except Exception as e:
            logger.error(f"Error saving notebook: {e}")
            self.mqtt_client.publish(f"{base}/notebook/saved", json.dumps({
                "success": False,
                "error": str(e)
            }))

    def _handle_notebook_load(self, payload: Any):
        """Load notebook data from file"""
        base = self.get_topic_base()
        notebook_path = self._get_notebook_path()

        try:
            if notebook_path.exists():
                with open(notebook_path, 'r') as f:
                    data = json.load(f)

                logger.info(f"Loaded notebook from {notebook_path}")
                self.mqtt_client.publish(f"{base}/notebook/loaded", json.dumps({
                    "success": True,
                    "data": data
                }))
            else:
                # No file yet - that's OK
                self.mqtt_client.publish(f"{base}/notebook/loaded", json.dumps({
                    "success": True,
                    "data": None
                }))

        except Exception as e:
            logger.error(f"Error loading notebook: {e}")
            self.mqtt_client.publish(f"{base}/notebook/loaded", json.dumps({
                "success": False,
                "error": str(e)
            }))

    # =========================================================================
    # CHASSIS/DEVICE MANAGEMENT HANDLERS (Modbus)
    # =========================================================================

    def _publish_chassis_response(self, success: bool, message: str):
        """Publish response to chassis management commands"""
        base = self.get_topic_base()
        self.mqtt_client.publish(f"{base}/chassis/response", json.dumps({
            "success": success,
            "message": message
        }))

    def _handle_chassis_add(self, payload: Any):
        """Add a new chassis/device (e.g., Modbus TCP/RTU device)"""
        if not isinstance(payload, dict):
            self._publish_chassis_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_chassis_response(False, "Missing device name")
            return

        # Check if chassis already exists
        if name in self.config.chassis:
            self._publish_chassis_response(False, f"Chassis '{name}' already exists")
            return

        try:
            from config_parser import ChassisConfig

            # Determine chassis type based on connection
            connection = payload.get('connection', 'TCP').upper()
            if connection in ('TCP', 'MODBUS_TCP'):
                chassis_type = 'modbus_tcp'
            elif connection in ('RTU', 'MODBUS_RTU'):
                chassis_type = 'modbus_rtu'
            else:
                chassis_type = payload.get('type', 'modbus_device')

            # Create chassis config from payload
            chassis = ChassisConfig(
                name=name,
                chassis_type=chassis_type,
                serial=payload.get('serial', ''),
                connection=connection,
                ip_address=payload.get('ip_address', ''),
                enabled=payload.get('enabled', True),
                modbus_port=int(payload.get('modbus_port', 502)),
                modbus_baudrate=int(payload.get('modbus_baudrate', 9600)),
                modbus_parity=payload.get('modbus_parity', 'E'),
                modbus_stopbits=int(payload.get('modbus_stopbits', 1)),
                modbus_bytesize=int(payload.get('modbus_bytesize', 8)),
                modbus_timeout=float(payload.get('modbus_timeout', 1.0)),
                modbus_retries=int(payload.get('modbus_retries', 3))
            )

            # Add to config
            self.config.chassis[name] = chassis
            logger.info(f"Added chassis: {name} ({chassis.connection})")

            # Re-initialize modbus reader if needed
            if chassis.connection.upper() in ('TCP', 'RTU', 'MODBUS_TCP', 'MODBUS_RTU'):
                self._init_modbus_reader()

            # Publish updated config
            self._publish_channel_config()
            self._publish_chassis_response(True, f"Added device: {name}")

        except Exception as e:
            logger.error(f"Failed to add chassis: {e}")
            self._publish_chassis_response(False, str(e))

    def _handle_chassis_update(self, payload: Any):
        """Update an existing chassis/device configuration"""
        if not isinstance(payload, dict):
            self._publish_chassis_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_chassis_response(False, "Missing device name")
            return

        if name not in self.config.chassis:
            self._publish_chassis_response(False, f"Chassis '{name}' not found")
            return

        try:
            chassis = self.config.chassis[name]

            # Update fields if provided
            if 'connection' in payload:
                chassis.connection = payload['connection']
            if 'ip_address' in payload:
                chassis.ip_address = payload['ip_address']
            if 'serial' in payload:
                chassis.serial = payload['serial']
            if 'enabled' in payload:
                chassis.enabled = payload['enabled']
            if 'modbus_port' in payload:
                chassis.modbus_port = int(payload['modbus_port'])
            if 'modbus_baudrate' in payload:
                chassis.modbus_baudrate = int(payload['modbus_baudrate'])
            if 'modbus_parity' in payload:
                chassis.modbus_parity = payload['modbus_parity']
            if 'modbus_stopbits' in payload:
                chassis.modbus_stopbits = int(payload['modbus_stopbits'])
            if 'modbus_bytesize' in payload:
                chassis.modbus_bytesize = int(payload['modbus_bytesize'])
            if 'modbus_timeout' in payload:
                chassis.modbus_timeout = float(payload['modbus_timeout'])
            if 'modbus_retries' in payload:
                chassis.modbus_retries = int(payload['modbus_retries'])

            logger.info(f"Updated chassis: {name}")

            # Re-initialize modbus reader
            if chassis.connection.upper() in ('TCP', 'RTU', 'MODBUS_TCP', 'MODBUS_RTU'):
                self._init_modbus_reader()

            # Publish updated config
            self._publish_channel_config()
            self._publish_chassis_response(True, f"Updated device: {name}")

        except Exception as e:
            logger.error(f"Failed to update chassis: {e}")
            self._publish_chassis_response(False, str(e))

    def _handle_chassis_delete(self, payload: Any):
        """Delete a chassis/device"""
        if not isinstance(payload, dict):
            self._publish_chassis_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_chassis_response(False, "Missing device name")
            return

        if name not in self.config.chassis:
            self._publish_chassis_response(False, f"Chassis '{name}' not found")
            return

        try:
            # Check for channels using this chassis
            channels_using = []
            for ch_name, ch in self.config.channels.items():
                module = self.config.modules.get(ch.module)
                if module and module.chassis == name:
                    channels_using.append(ch_name)

            if channels_using:
                self._publish_chassis_response(False,
                    f"Cannot delete: channels depend on this device: {', '.join(channels_using[:5])}")
                return

            # Remove chassis
            del self.config.chassis[name]
            logger.info(f"Deleted chassis: {name}")

            # Re-initialize modbus reader
            self._init_modbus_reader()

            # Publish updated config
            self._publish_channel_config()
            self._publish_chassis_response(True, f"Deleted device: {name}")

        except Exception as e:
            logger.error(f"Failed to delete chassis: {e}")
            self._publish_chassis_response(False, str(e))

    def _handle_chassis_test(self, payload: Any):
        """Test connection to a chassis/device"""
        if not isinstance(payload, dict):
            self._publish_chassis_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_chassis_response(False, "Missing device name")
            return

        if name not in self.config.chassis:
            self._publish_chassis_response(False, f"Chassis '{name}' not found")
            return

        try:
            chassis = self.config.chassis[name]

            # Check if it's a Modbus device
            if chassis.connection.upper() not in ('TCP', 'RTU', 'MODBUS_TCP', 'MODBUS_RTU'):
                self._publish_chassis_response(False, "Only Modbus devices can be tested")
                return

            # Test connection via modbus_reader
            if self.modbus_reader and name in self.modbus_reader.connections:
                conn = self.modbus_reader.connections[name]
                if conn.connect():
                    self._publish_chassis_response(True, f"Connection to {name} successful")
                else:
                    self._publish_chassis_response(False,
                        f"Connection to {name} failed: {conn.last_error or 'Unknown error'}")
            else:
                self._publish_chassis_response(False, f"No connection configured for {name}")

        except Exception as e:
            logger.error(f"Failed to test chassis: {e}")
            self._publish_chassis_response(False, str(e))

    def _publish_modbus_status(self):
        """Publish Modbus connection status"""
        base = self.get_topic_base()
        status = {}

        if self.modbus_reader:
            status = self.modbus_reader.get_connection_status()

        self.mqtt_client.publish(f"{base}/modbus/status", json.dumps(status))

    # =========================================================================
    # DATA SOURCE MANAGEMENT (REST API, OPC-UA, etc.)
    # =========================================================================

    def _handle_datasource_add(self, payload: Any):
        """Add a new data source (REST API, OPC-UA, etc.)"""
        if not DATA_SOURCE_MANAGER_AVAILABLE:
            self._publish_datasource_response(False, "DataSourceManager not available")
            return

        if not isinstance(payload, dict):
            self._publish_datasource_response(False, "Invalid payload")
            return

        try:
            source_config = {
                'name': payload.get('name'),
                'type': payload.get('type', 'rest_api'),
                'enabled': payload.get('enabled', True),
                'poll_rate_ms': payload.get('poll_rate_ms', 100),
                'timeout_s': payload.get('timeout_s', 5.0),
                'retries': payload.get('retries', 3),
                'connection': payload.get('connection', {}),
                'channels': payload.get('channels', []),
            }

            self._add_data_source_from_config(source_config)

            # Start the new source
            if self.data_source_manager:
                source = self.data_source_manager.get_source(source_config['name'])
                if source and source.config.enabled:
                    if source.connect():
                        from data_source_manager import ConnectionState
                        source.status.state = ConnectionState.CONNECTED
                    source.start_polling()

            self._publish_datasource_response(True, f"Data source '{source_config['name']}' added")
            self._publish_datasource_status()

        except Exception as e:
            logger.error(f"Failed to add data source: {e}")
            self._publish_datasource_response(False, str(e))

    def _handle_datasource_update(self, payload: Any):
        """Update an existing data source"""
        if not DATA_SOURCE_MANAGER_AVAILABLE or not self.data_source_manager:
            self._publish_datasource_response(False, "DataSourceManager not available")
            return

        if not isinstance(payload, dict):
            self._publish_datasource_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_datasource_response(False, "Missing source name")
            return

        try:
            # Remove old source and re-add with new config
            self.data_source_manager.remove_source(name)

            source_config = {
                'name': name,
                'type': payload.get('type', 'rest_api'),
                'enabled': payload.get('enabled', True),
                'poll_rate_ms': payload.get('poll_rate_ms', 100),
                'timeout_s': payload.get('timeout_s', 5.0),
                'retries': payload.get('retries', 3),
                'connection': payload.get('connection', {}),
                'channels': payload.get('channels', []),
            }

            self._add_data_source_from_config(source_config)

            # Start the updated source
            source = self.data_source_manager.get_source(name)
            if source and source.config.enabled:
                if source.connect():
                    from data_source_manager import ConnectionState
                    source.status.state = ConnectionState.CONNECTED
                source.start_polling()

            self._publish_datasource_response(True, f"Data source '{name}' updated")
            self._publish_datasource_status()

        except Exception as e:
            logger.error(f"Failed to update data source: {e}")
            self._publish_datasource_response(False, str(e))

    def _handle_datasource_delete(self, payload: Any):
        """Delete a data source"""
        if not DATA_SOURCE_MANAGER_AVAILABLE or not self.data_source_manager:
            self._publish_datasource_response(False, "DataSourceManager not available")
            return

        if not isinstance(payload, dict):
            self._publish_datasource_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_datasource_response(False, "Missing source name")
            return

        try:
            self.data_source_manager.remove_source(name)
            self._publish_datasource_response(True, f"Data source '{name}' deleted")
            self._publish_datasource_status()

        except Exception as e:
            logger.error(f"Failed to delete data source: {e}")
            self._publish_datasource_response(False, str(e))

    def _handle_datasource_test(self, payload: Any):
        """Test connection to a data source"""
        if not DATA_SOURCE_MANAGER_AVAILABLE or not self.data_source_manager:
            self._publish_datasource_response(False, "DataSourceManager not available")
            return

        if not isinstance(payload, dict):
            self._publish_datasource_response(False, "Invalid payload")
            return

        name = payload.get('name')
        if not name:
            self._publish_datasource_response(False, "Missing source name")
            return

        source = self.data_source_manager.get_source(name)
        if not source:
            self._publish_datasource_response(False, f"Data source '{name}' not found")
            return

        try:
            if source.connect():
                self._publish_datasource_response(True, f"Connection to '{name}' successful")
            else:
                self._publish_datasource_response(False,
                    f"Connection to '{name}' failed: {source.status.last_error or 'Unknown error'}")

        except Exception as e:
            logger.error(f"Failed to test data source: {e}")
            self._publish_datasource_response(False, str(e))

    def _handle_datasource_list(self):
        """List all data sources and their status"""
        self._publish_datasource_status()

    def _publish_datasource_response(self, success: bool, message: str):
        """Publish response to data source operations"""
        base = self.get_topic_base()
        self.mqtt_client.publish(f"{base}/datasource/response", json.dumps({
            'success': success,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }))

    def _publish_datasource_status(self):
        """Publish data source status and channel info"""
        base = self.get_topic_base()
        status = {}
        channels = {}

        if self.data_source_manager:
            status = self.data_source_manager.get_all_status()
            channels = self.data_source_manager.get_all_channels()

        self.mqtt_client.publish(f"{base}/datasource/status", json.dumps({
            'sources': status,
            'channels': channels,
            'available_types': DataSourceManager.get_available_types() if DATA_SOURCE_MANAGER_AVAILABLE else []
        }))

    # =========================================================================
    # USER VARIABLES / PLAYGROUND HANDLERS
    # =========================================================================

    def _handle_variable_create(self, payload: Dict[str, Any]):
        """Create a new user variable"""
        if not isinstance(payload, dict):
            self._publish_variable_response(False, "Invalid payload")
            return

        try:
            var = self.user_variables.create_variable(payload)
            self._publish_variable_response(True, f"Created variable: {var.name}")
            self._publish_user_variables_config()
            self._publish_user_variables_values()
        except Exception as e:
            logger.error(f"Failed to create variable: {e}")
            self._publish_variable_response(False, str(e))

    def _handle_variable_update(self, payload: Dict[str, Any]):
        """Update an existing user variable"""
        if not isinstance(payload, dict):
            self._publish_variable_response(False, "Invalid payload")
            return

        var_id = payload.get('id')
        if not var_id:
            self._publish_variable_response(False, "Missing variable ID")
            return

        try:
            var = self.user_variables.update_variable(var_id, payload)
            if var:
                self._publish_variable_response(True, f"Updated variable: {var.name}")
                self._publish_user_variables_config()
            else:
                self._publish_variable_response(False, f"Variable not found: {var_id}")
        except Exception as e:
            logger.error(f"Failed to update variable: {e}")
            self._publish_variable_response(False, str(e))

    def _handle_variable_delete(self, payload: Dict[str, Any]):
        """Delete a user variable"""
        var_id = payload.get('id') if isinstance(payload, dict) else payload
        if not var_id:
            self._publish_variable_response(False, "Missing variable ID")
            return

        if self.user_variables.delete_variable(var_id):
            self._publish_variable_response(True, f"Deleted variable: {var_id}")
            self._publish_user_variables_config()
        else:
            self._publish_variable_response(False, f"Variable not found: {var_id}")

    def _handle_variable_set(self, payload: Dict[str, Any]):
        """Manually set a variable's value"""
        if not isinstance(payload, dict):
            self._publish_variable_response(False, "Invalid payload")
            return

        var_id = payload.get('id')
        value = payload.get('value')

        if not var_id or value is None:
            self._publish_variable_response(False, "Missing variable ID or value")
            return

        try:
            value = float(value)
            if self.user_variables.set_variable_value(var_id, value):
                self._publish_variable_response(True, f"Set variable value")
                self._publish_user_variables_values()
            else:
                self._publish_variable_response(False, f"Variable not found: {var_id}")
        except ValueError:
            self._publish_variable_response(False, "Invalid value - must be numeric")

    def _handle_variable_reset(self, payload: Dict[str, Any]):
        """Reset variable(s) to zero"""
        if isinstance(payload, dict):
            var_id = payload.get('id')
            var_ids = payload.get('ids', [])
        else:
            var_id = payload
            var_ids = []

        if var_id:
            # Reset single variable
            if self.user_variables.reset_variable(var_id):
                self._publish_variable_response(True, f"Reset variable: {var_id}")
            else:
                self._publish_variable_response(False, f"Variable not found: {var_id}")
        elif var_ids:
            # Reset multiple variables
            self.user_variables.reset_all_variables(var_ids)
            self._publish_variable_response(True, f"Reset {len(var_ids)} variables")
        else:
            # Reset all variables
            self.user_variables.reset_all_variables()
            self._publish_variable_response(True, "Reset all variables")

        self._publish_user_variables_values()

    def _handle_variable_get(self, payload: Dict[str, Any]):
        """Get a specific variable's config and value"""
        var_id = payload.get('id') if isinstance(payload, dict) else payload
        if not var_id:
            self._publish_variable_response(False, "Missing variable ID")
            return

        var = self.user_variables.get_variable(var_id)
        if var:
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/variables/get/response",
                json.dumps(var.to_dict())
            )
        else:
            self._publish_variable_response(False, f"Variable not found: {var_id}")

    def _handle_variable_list(self):
        """List all user variables"""
        self._publish_user_variables_config()
        self._publish_user_variables_values()

    def _handle_timer_start(self, payload: Dict[str, Any]):
        """Start a timer variable"""
        var_id = payload.get('id') if isinstance(payload, dict) else payload
        if not var_id:
            self._publish_variable_response(False, "Missing variable ID")
            return

        if self.user_variables.start_timer(var_id):
            self._publish_variable_response(True, f"Started timer: {var_id}")
        else:
            self._publish_variable_response(False, f"Failed to start timer: {var_id}")

    def _handle_timer_stop(self, payload: Dict[str, Any]):
        """Stop a timer variable"""
        var_id = payload.get('id') if isinstance(payload, dict) else payload
        if not var_id:
            self._publish_variable_response(False, "Missing variable ID")
            return

        if self.user_variables.stop_timer(var_id):
            self._publish_variable_response(True, f"Stopped timer: {var_id}")
            self._publish_user_variables_values()
        else:
            self._publish_variable_response(False, f"Failed to stop timer: {var_id}")

    def _publish_variable_response(self, success: bool, message: str):
        """Publish variable operation response"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/variables/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    def _publish_user_variables_config(self):
        """Publish user variable configurations"""
        if not self.user_variables:
            return
        base = self.get_topic_base()
        config = self.user_variables.get_config_dict()
        self.mqtt_client.publish(
            f"{base}/variables/config",
            json.dumps(config),
            retain=True
        )

    def _publish_user_variables_values(self):
        """Publish current user variable values"""
        if not self.user_variables:
            return
        base = self.get_topic_base()
        values = self.user_variables.get_values_dict()
        self.mqtt_client.publish(
            f"{base}/variables/values",
            json.dumps(values),
            retain=True
        )

    # =========================================================================
    # TEST SESSION HANDLERS
    # =========================================================================

    def _handle_test_session_start(self, payload: Dict[str, Any]):
        """Start a test session with safety interlock validation"""
        started_by = payload.get('started_by', 'user') if isinstance(payload, dict) else 'user'

        # Get alarm counts for safety interlock validation
        latched_count = 0
        active_count = 0
        if self.alarm_manager:
            counts = self.alarm_manager.get_alarm_counts()
            # 'returned' = condition cleared but latched (awaiting reset)
            # 'active' = condition present and unacknowledged
            latched_count = counts.get('returned', 0)
            active_count = counts.get('active', 0)

        # Get latch requirements from session config (persistent settings)
        session_config = self.user_variables.get_session_config() if self.user_variables else {}
        config_require_latch = session_config.get('require_latch_armed', False)
        config_require_no_active = session_config.get('require_no_active_alarms', False)

        # Payload can override session config (for one-time bypass or enforcement)
        require_no_latched = payload.get('require_no_latched', config_require_latch) if isinstance(payload, dict) else config_require_latch
        require_no_active = payload.get('require_no_active', config_require_no_active) if isinstance(payload, dict) else config_require_no_active

        result = self.user_variables.start_session(
            acquiring=self.acquiring,
            started_by=started_by,
            latched_alarm_count=latched_count,
            active_alarm_count=active_count,
            require_no_latched=require_no_latched,
            require_no_active=require_no_active
        )

        if result.get('success'):
            self._publish_variable_response(True, "Test session started")
            self._publish_test_session_status()
            self._publish_user_variables_values()
        else:
            self._publish_variable_response(False, result.get('error', 'Failed to start session'))

    def _handle_test_session_stop(self):
        """Stop the test session"""
        result = self.user_variables.stop_session()

        if result.get('success'):
            self._publish_variable_response(True, "Test session stopped")
            self._publish_test_session_status()
            self._publish_user_variables_values()
        else:
            self._publish_variable_response(False, result.get('error', 'Failed to stop session'))

    def _handle_test_session_config(self, payload: Dict[str, Any]):
        """Update test session configuration"""
        if not isinstance(payload, dict):
            self._publish_variable_response(False, "Invalid payload")
            return

        try:
            self.user_variables.update_session_config(payload)
            self._publish_variable_response(True, "Updated test session config")
            self._publish_test_session_status()
        except Exception as e:
            logger.error(f"Failed to update session config: {e}")
            self._publish_variable_response(False, str(e))

    def _publish_test_session_status(self):
        """Publish test session status"""
        if not self.user_variables:
            return
        base = self.get_topic_base()
        status = self.user_variables.get_session_status()
        self.mqtt_client.publish(
            f"{base}/test-session/status",
            json.dumps(status),
            retain=True
        )

    # =========================================================================
    # FORMULA BLOCK HANDLERS
    # =========================================================================

    def _handle_formula_create(self, payload: Dict[str, Any]):
        """Create a new formula block"""
        if not isinstance(payload, dict):
            self._publish_formula_response(False, "Invalid payload")
            return

        # Get channel names for validation
        channel_names = list(self.config.channels.keys())

        result = self.user_variables.create_formula_block(payload, channel_names)

        if result.get('success'):
            self._publish_formula_response(True, f"Created formula block with outputs: {result.get('outputs', [])}")
            self._publish_formula_blocks_config()
        else:
            self._publish_formula_response(False, result.get('error', 'Failed to create formula block'))

    def _handle_formula_update(self, payload: Dict[str, Any]):
        """Update an existing formula block"""
        if not isinstance(payload, dict):
            self._publish_formula_response(False, "Invalid payload")
            return

        block_id = payload.get('id')
        if not block_id:
            self._publish_formula_response(False, "Block ID required")
            return

        # Get channel names for validation
        channel_names = list(self.config.channels.keys())

        result = self.user_variables.update_formula_block(block_id, payload, channel_names)

        if result.get('success'):
            self._publish_formula_response(True, "Updated formula block")
            self._publish_formula_blocks_config()
        else:
            self._publish_formula_response(False, result.get('error', 'Failed to update formula block'))

    def _handle_formula_delete(self, payload: Dict[str, Any]):
        """Delete a formula block"""
        if not isinstance(payload, dict):
            self._publish_formula_response(False, "Invalid payload")
            return

        block_id = payload.get('id')
        if not block_id:
            self._publish_formula_response(False, "Block ID required")
            return

        if self.user_variables.delete_formula_block(block_id):
            self._publish_formula_response(True, "Deleted formula block")
            self._publish_formula_blocks_config()
        else:
            self._publish_formula_response(False, "Formula block not found")

    def _publish_formula_blocks_config(self):
        """Publish formula blocks configuration"""
        if not self.user_variables:
            return
        base = self.get_topic_base()
        blocks = self.user_variables.get_formula_blocks_dict()
        self.mqtt_client.publish(
            f"{base}/formulas/config",
            json.dumps(blocks),
            retain=True
        )

    def _publish_formula_blocks_values(self):
        """Publish formula blocks computed values"""
        if not self.user_variables:
            return
        base = self.get_topic_base()
        values = self.user_variables.get_formula_values_dict()
        self.mqtt_client.publish(
            f"{base}/formulas/values",
            json.dumps(values),
            retain=True
        )

    def _publish_formula_response(self, success: bool, message: str):
        """Publish formula block operation response"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/formulas/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    def _publish_project_response(self, success: bool, message: str):
        """Publish project operation response"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/project/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
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

        # IEC 61511: Check if safety-related fields are being modified during acquisition
        if self.project_manager:
            safety_fields = ['safety_action', 'safety_interlock']
            for field in safety_fields:
                if field in config_data:
                    allowed, reason = self.project_manager.check_safety_modification(field)
                    if not allowed:
                        logger.warning(f"Safety config modification rejected: {reason}")
                        self._publish_config_response(False, reason)
                        return

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

        # Visibility
        if 'visible' in config_data:
            channel.visible = bool(config_data['visible'])

        # Group
        if 'group' in config_data:
            channel.group = config_data['group']

        # Terminal configuration (for analog inputs)
        if 'terminal_config' in config_data:
            channel.terminal_config = config_data['terminal_config']

        # RTD-specific parameters
        if 'rtd_type' in config_data:
            channel.rtd_type = config_data['rtd_type']
        if 'rtd_resistance' in config_data:
            channel.rtd_resistance = float(config_data['rtd_resistance'])
        if 'rtd_wiring' in config_data:
            channel.rtd_wiring = config_data['rtd_wiring']
        if 'rtd_current' in config_data:
            channel.rtd_current = float(config_data['rtd_current'])

        # Strain gauge-specific parameters
        if 'strain_config' in config_data:
            channel.strain_config = config_data['strain_config']
        if 'strain_excitation_voltage' in config_data:
            channel.strain_excitation_voltage = float(config_data['strain_excitation_voltage'])
        if 'strain_gage_factor' in config_data:
            channel.strain_gage_factor = float(config_data['strain_gage_factor'])
        if 'strain_resistance' in config_data:
            channel.strain_resistance = float(config_data['strain_resistance'])

        # IEPE-specific parameters
        if 'iepe_sensitivity' in config_data:
            channel.iepe_sensitivity = float(config_data['iepe_sensitivity'])
        if 'iepe_current' in config_data:
            channel.iepe_current = float(config_data['iepe_current'])
        if 'iepe_coupling' in config_data:
            channel.iepe_coupling = config_data['iepe_coupling']

        # Resistance-specific parameters
        if 'resistance_range' in config_data:
            channel.resistance_range = float(config_data['resistance_range'])
        if 'resistance_wiring' in config_data:
            channel.resistance_wiring = config_data['resistance_wiring']

        # Counter-specific parameters
        if 'counter_mode' in config_data:
            channel.counter_mode = config_data['counter_mode']
        if 'pulses_per_unit' in config_data:
            channel.pulses_per_unit = float(config_data['pulses_per_unit'])
        if 'counter_edge' in config_data:
            channel.counter_edge = config_data['counter_edge']
        if 'counter_reset_on_read' in config_data:
            channel.counter_reset_on_read = bool(config_data['counter_reset_on_read'])
        if 'counter_min_freq' in config_data:
            channel.counter_min_freq = float(config_data['counter_min_freq'])
        if 'counter_max_freq' in config_data:
            channel.counter_max_freq = float(config_data['counter_max_freq'])

        # Validate scaling config
        is_valid, error_msg = validate_scaling_config(channel)
        if not is_valid:
            logger.warning(f"Scaling validation warning for {channel_name}: {error_msg}")

        logger.info(f"Updated channel {channel_name} (type: {channel.channel_type.value})")

        # Audit trail: Log channel configuration change
        if self.audit_trail:
            self.audit_trail.log_config_change(
                config_type="channel",
                config_id=channel_name,
                user=self.auth_username or "system",
                previous_value=None,  # Could capture old values if needed
                new_value=config_data,
                reason=config_data.get('reason', '')
            )

        self._publish_channel_config()
        self._publish_config_response(True, f"Updated {channel_name}")

    def _handle_channel_create(self, payload: Any):
        """Create a new channel at runtime"""
        if not self.authenticated:
            logger.warning("Channel create rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Channel create rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before creating channels")
            return

        if not isinstance(payload, dict):
            self._publish_config_response(False, "Invalid payload")
            return

        channel_name = payload.get('name')
        if not channel_name:
            self._publish_config_response(False, "Channel name is required")
            return

        if channel_name in self.config.channels:
            self._publish_config_response(False, f"Channel '{channel_name}' already exists")
            return

        # Get channel configuration from payload
        config_data = payload.get('config', payload)

        try:
            # Parse channel type
            channel_type_str = config_data.get('channel_type', 'voltage')
            channel_type = ChannelType(channel_type_str)

            # Parse thermocouple type if applicable
            tc_type = None
            if 'thermocouple_type' in config_data:
                from config_parser import ThermocoupleType
                tc_type = ThermocoupleType(config_data['thermocouple_type'])

            # Create the channel config
            channel = ChannelConfig(
                name=channel_name,
                module=config_data.get('module', ''),
                physical_channel=config_data.get('physical_channel', ''),
                channel_type=channel_type,
                description=config_data.get('description', ''),
                units=config_data.get('units', ''),
                visible=config_data.get('visible', True),
                group=config_data.get('group', ''),
                scale_slope=float(config_data.get('scale_slope', 1.0)),
                scale_offset=float(config_data.get('scale_offset', 0.0)),
                scale_type=config_data.get('scale_type', 'none'),
                four_twenty_scaling=bool(config_data.get('four_twenty_scaling', False)),
                eng_units_min=float(config_data['eng_units_min']) if config_data.get('eng_units_min') is not None else None,
                eng_units_max=float(config_data['eng_units_max']) if config_data.get('eng_units_max') is not None else None,
                pre_scaled_min=float(config_data['pre_scaled_min']) if config_data.get('pre_scaled_min') is not None else None,
                pre_scaled_max=float(config_data['pre_scaled_max']) if config_data.get('pre_scaled_max') is not None else None,
                scaled_min=float(config_data['scaled_min']) if config_data.get('scaled_min') is not None else None,
                scaled_max=float(config_data['scaled_max']) if config_data.get('scaled_max') is not None else None,
                voltage_range=float(config_data.get('voltage_range', 10.0)),
                current_range_ma=float(config_data.get('current_range_ma', 20.0)),
                thermocouple_type=tc_type,
                cjc_source=config_data.get('cjc_source', 'internal'),
                counter_mode=config_data.get('counter_mode', 'frequency'),
                pulses_per_unit=float(config_data.get('pulses_per_unit', 1.0)),
                counter_edge=config_data.get('counter_edge', 'rising'),
                counter_reset_on_read=bool(config_data.get('counter_reset_on_read', False)),
                invert=bool(config_data.get('invert', False)),
                default_state=bool(config_data.get('default_state', False)),
                default_value=float(config_data.get('default_value', 0.0)),
                low_limit=float(config_data['low_limit']) if config_data.get('low_limit') is not None else None,
                high_limit=float(config_data['high_limit']) if config_data.get('high_limit') is not None else None,
                low_warning=float(config_data['low_warning']) if config_data.get('low_warning') is not None else None,
                high_warning=float(config_data['high_warning']) if config_data.get('high_warning') is not None else None,
                safety_action=config_data.get('safety_action'),
                safety_interlock=config_data.get('safety_interlock'),
                log=bool(config_data.get('log', True)),
                log_interval_ms=int(config_data.get('log_interval_ms', 1000))
            )

            # Add to config
            self.config.channels[channel_name] = channel

            # Initialize channel value
            if channel_type == ChannelType.DIGITAL_OUTPUT:
                self.channel_values[channel_name] = channel.default_state
            elif channel_type == ChannelType.ANALOG_OUTPUT:
                self.channel_values[channel_name] = channel.default_value
            else:
                self.channel_values[channel_name] = 0.0

            # Update simulator if running
            if self.simulator:
                self.simulator.add_channel(channel)

            # Update dependency tracker
            if self.dependency_tracker:
                self.dependency_tracker.refresh(self.config)

            logger.info(f"Created channel {channel_name} (type: {channel_type.value})")
            self._publish_channel_config()
            self._publish_config_response(True, f"Created channel {channel_name}")

        except Exception as e:
            logger.error(f"Failed to create channel {channel_name}: {e}")
            self._publish_config_response(False, f"Failed to create channel: {e}")

    def _handle_channel_delete(self, payload: Any):
        """Delete a channel"""
        if not self.authenticated:
            logger.warning("Channel delete rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Channel delete rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before deleting channels")
            return

        if not isinstance(payload, dict):
            self._publish_config_response(False, "Invalid payload")
            return

        channel_name = payload.get('name') or payload.get('channel')
        if not channel_name:
            self._publish_config_response(False, "Channel name is required")
            return

        if channel_name not in self.config.channels:
            self._publish_config_response(False, f"Channel '{channel_name}' not found")
            return

        # Check dependencies using dependency tracker
        if self.dependency_tracker:
            deps = self.dependency_tracker.get_dependencies(EntityType.CHANNEL, channel_name)
            if deps.dependents and not payload.get('force', False):
                # Return dependency info so frontend can show confirmation
                self.mqtt_client.publish(
                    f"{self.get_topic_base()}/config/channel/delete/confirm",
                    json.dumps({
                        "channel": channel_name,
                        "dependencies": deps.to_dict(),
                        "message": f"Channel has {deps.total_affected} dependents. Set force=true to delete anyway.",
                        "timestamp": datetime.now().isoformat()
                    })
                )
                return

        # Delete the channel
        del self.config.channels[channel_name]

        # Remove from channel values
        if channel_name in self.channel_values:
            del self.channel_values[channel_name]
        if channel_name in self.channel_raw_values:
            del self.channel_raw_values[channel_name]
        if channel_name in self.channel_timestamps:
            del self.channel_timestamps[channel_name]

        # Update simulator
        if self.simulator:
            self.simulator.remove_channel(channel_name)

        # Update dependency tracker
        if self.dependency_tracker:
            self.dependency_tracker.refresh(self.config)

        # Notify about deleted channel so frontend can clean up widgets
        self.mqtt_client.publish(
            f"{self.get_topic_base()}/config/channel/deleted",
            json.dumps({
                "channel": channel_name,
                "timestamp": datetime.now().isoformat()
            }),
            retain=False
        )

        logger.info(f"Deleted channel {channel_name}")
        self._publish_channel_config()
        self._publish_config_response(True, f"Deleted channel {channel_name}")

    def _handle_channel_bulk_create(self, payload: Any):
        """Create multiple channels at once (from discovery)"""
        if not self.authenticated:
            logger.warning("Bulk channel create rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        if self.acquiring:
            logger.warning("Bulk channel create rejected - acquisition running")
            self._publish_config_response(False, "Stop acquisition before creating channels")
            return

        if not isinstance(payload, dict):
            self._publish_config_response(False, "Invalid payload")
            return

        channels = payload.get('channels', [])
        if not channels:
            self._publish_config_response(False, "No channels specified")
            return

        created = []
        failed = []

        for ch_config in channels:
            channel_name = ch_config.get('name')
            if not channel_name:
                failed.append({"name": "unnamed", "error": "Name is required"})
                continue

            if channel_name in self.config.channels:
                failed.append({"name": channel_name, "error": "Already exists"})
                continue

            try:
                # Use same logic as single create
                channel_type_str = ch_config.get('channel_type', 'voltage')
                channel_type = ChannelType(channel_type_str)

                tc_type = None
                if 'thermocouple_type' in ch_config:
                    from config_parser import ThermocoupleType
                    tc_type = ThermocoupleType(ch_config['thermocouple_type'])

                channel = ChannelConfig(
                    name=channel_name,
                    module=ch_config.get('module', ''),
                    physical_channel=ch_config.get('physical_channel', ''),
                    channel_type=channel_type,
                    description=ch_config.get('description', ''),
                    units=ch_config.get('units', ''),
                    visible=ch_config.get('visible', True),
                    group=ch_config.get('group', ''),
                    thermocouple_type=tc_type,
                    log=ch_config.get('log', True)
                )

                self.config.channels[channel_name] = channel

                # Initialize value
                if channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[channel_name] = channel.default_state
                elif channel_type == ChannelType.ANALOG_OUTPUT:
                    self.channel_values[channel_name] = channel.default_value
                else:
                    self.channel_values[channel_name] = 0.0

                if self.simulator:
                    self.simulator.add_channel(channel)

                created.append(channel_name)

            except Exception as e:
                failed.append({"name": channel_name, "error": str(e)})

        # Update dependency tracker once at the end
        if self.dependency_tracker and created:
            self.dependency_tracker.refresh(self.config)

        logger.info(f"Bulk create: {len(created)} created, {len(failed)} failed")
        self._publish_channel_config()

        self.mqtt_client.publish(
            f"{self.get_topic_base()}/config/channel/bulk-create/response",
            json.dumps({
                "success": len(failed) == 0,
                "created": created,
                "failed": failed,
                "message": f"Created {len(created)} channels" + (f", {len(failed)} failed" if failed else ""),
                "timestamp": datetime.now().isoformat()
            })
        )

    # =========================================================================
    # DEVICE DISCOVERY HANDLERS
    # =========================================================================

    def _handle_discovery_scan(self):
        """Handle device discovery scan request"""
        logger.info("Starting device discovery scan...")
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

        status = self.scheduler.get_status()

        self.mqtt_client.publish(
            f"{base}/schedule/status/response",
            json.dumps(status),
            retain=True
        )

    def _publish_schedule_response(self, success: bool, message: str):
        """Publish schedule operation response"""
        base = self.get_topic_base()

        self.mqtt_client.publish(
            f"{base}/schedule/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        )

    # =========================================================================
    # SEQUENCE HANDLERS
    # =========================================================================

    def _handle_sequence_start(self, payload: Any):
        """Start a sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload - expected object with sequenceId")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        if self.sequence_manager.start_sequence(sequence_id):
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' started")
            self._publish_sequence_status()
        else:
            self._publish_sequence_response(False, f"Failed to start sequence '{sequence_id}'")

    def _handle_sequence_pause(self, payload: Any):
        """Pause a running sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        if self.sequence_manager.pause_sequence(sequence_id):
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' paused")
            self._publish_sequence_status()
        else:
            self._publish_sequence_response(False, f"Failed to pause sequence '{sequence_id}'")

    def _handle_sequence_resume(self, payload: Any):
        """Resume a paused sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        if self.sequence_manager.resume_sequence(sequence_id):
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' resumed")
            self._publish_sequence_status()
        else:
            self._publish_sequence_response(False, f"Failed to resume sequence '{sequence_id}'")

    def _handle_sequence_abort(self, payload: Any):
        """Abort a running sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        if self.sequence_manager.abort_sequence(sequence_id):
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' aborted")
            self._publish_sequence_status()
        else:
            self._publish_sequence_response(False, f"Failed to abort sequence '{sequence_id}'")

    def _handle_sequence_add(self, payload: Any):
        """Add a new sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload - expected sequence definition")
            return

        try:
            from sequence_manager import Sequence, SequenceStep

            sequence_id = payload.get('id') or payload.get('sequenceId')
            if not sequence_id:
                self._publish_sequence_response(False, "Missing sequence id")
                return

            name = payload.get('name', sequence_id)
            description = payload.get('description', '')
            steps_data = payload.get('steps', [])

            # Convert steps data to SequenceStep objects using from_dict
            steps = []
            for i, step_data in enumerate(steps_data):
                # Map frontend field names to backend field names
                mapped_data = {
                    'type': step_data.get('type', 'setOutput'),
                    'label': step_data.get('label') or step_data.get('id') or step_data.get('description') or f"Step {i+1}",
                    'channel': step_data.get('channel'),
                    'value': step_data.get('value'),
                    'duration_ms': int(step_data.get('duration', 0) * 1000) if step_data.get('duration') else step_data.get('duration_ms'),
                    'condition_channel': step_data.get('conditionChannel') or step_data.get('condition_channel'),
                    'condition_operator': step_data.get('conditionOperator') or step_data.get('condition_operator'),
                    'condition_value': step_data.get('conditionValue') or step_data.get('condition_value'),
                    'condition_timeout_ms': step_data.get('conditionTimeout') or step_data.get('condition_timeout_ms'),
                    'recording_filename': step_data.get('filename') or step_data.get('recording_filename'),
                    'message': step_data.get('message'),
                    'loop_count': step_data.get('loopCount') or step_data.get('loop_count'),
                    'loop_id': step_data.get('loopId') or step_data.get('loop_id'),
                    'sequence_id': step_data.get('sequenceId') or step_data.get('sequence_id'),
                }
                # Remove None values
                mapped_data = {k: v for k, v in mapped_data.items() if v is not None}
                step = SequenceStep.from_dict(mapped_data)
                steps.append(step)

            sequence = Sequence(
                id=sequence_id,
                name=name,
                description=description,
                steps=steps
            )

            self.sequence_manager.add_sequence(sequence)
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' added")
            self._publish_sequence_list()
        except Exception as e:
            logger.error(f"Error adding sequence: {e}")
            self._publish_sequence_response(False, f"Error adding sequence: {str(e)}")

    def _handle_sequence_remove(self, payload: Any):
        """Remove a sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id') or payload.get('id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        if self.sequence_manager.remove_sequence(sequence_id):
            self._publish_sequence_response(True, f"Sequence '{sequence_id}' removed")
            self._publish_sequence_list()
        else:
            self._publish_sequence_response(False, f"Sequence '{sequence_id}' not found")

    def _handle_sequence_list(self):
        """List all sequences"""
        self._publish_sequence_list()

    def _handle_sequence_get(self, payload: Any):
        """Get details of a specific sequence"""
        if not self.sequence_manager:
            self._publish_sequence_response(False, "Sequence manager not initialized")
            return

        if not isinstance(payload, dict):
            self._publish_sequence_response(False, "Invalid payload")
            return

        sequence_id = payload.get('sequenceId') or payload.get('sequence_id') or payload.get('id')
        if not sequence_id:
            self._publish_sequence_response(False, "Missing sequenceId")
            return

        sequence = self.sequence_manager.get_sequence(sequence_id)
        if sequence:
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/sequence/details",
                json.dumps({
                    "success": True,
                    "sequence": self._sequence_to_dict(sequence),
                    "timestamp": datetime.now().isoformat()
                }),
                qos=1
            )
        else:
            self._publish_sequence_response(False, f"Sequence '{sequence_id}' not found")

    def _publish_sequence_response(self, success: bool, message: str):
        """Publish sequence operation response"""
        base = self.get_topic_base()

        self.mqtt_client.publish(
            f"{base}/sequence/response",
            json.dumps({
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }),
            qos=1
        )

    def _publish_sequence_status(self):
        """Publish current sequence status"""
        if not self.sequence_manager:
            return

        base = self.get_topic_base()

        # Get status of all sequences
        sequences_status = {}
        for seq_id, sequence in self.sequence_manager.sequences.items():
            sequences_status[seq_id] = {
                "state": sequence.state.value,
                "current_step": sequence.current_step_index,
                "total_steps": len(sequence.steps),
                "error": sequence.error_message
            }

        self.mqtt_client.publish(
            f"{base}/sequence/status",
            json.dumps({
                "sequences": sequences_status,
                "timestamp": datetime.now().isoformat()
            }),
            retain=True
        )

    def _publish_sequence_list(self):
        """Publish list of all sequences"""
        if not self.sequence_manager:
            return

        base = self.get_topic_base()

        sequences = []
        for seq_id, sequence in self.sequence_manager.sequences.items():
            sequences.append(self._sequence_to_dict(sequence))

        self.mqtt_client.publish(
            f"{base}/sequence/list/response",
            json.dumps({
                "success": True,
                "sequences": sequences,
                "count": len(sequences),
                "timestamp": datetime.now().isoformat()
            }),
            qos=1
        )

    def _sequence_to_dict(self, sequence) -> dict:
        """Convert a Sequence object to a dictionary"""
        return {
            "id": sequence.id,
            "name": sequence.name,
            "description": sequence.description,
            "state": sequence.state.value,
            "current_step": sequence.current_step_index,
            "steps": [step.to_dict() for step in sequence.steps],
            "error": sequence.error_message
        }

    def _get_active_sequence_count(self) -> int:
        """Get count of sequences that are running or paused"""
        if not self.sequence_manager:
            return 0
        from sequence_manager import SequenceState
        return sum(
            1 for seq in self.sequence_manager.sequences.values()
            if seq.state in (SequenceState.RUNNING, SequenceState.PAUSED)
        )

    def _publish_config_response(self, success: bool, message: str):
        """Publish config operation response"""
        base = self.get_topic_base()

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

            # Visibility (only save if not default)
            if not ch.visible:
                section['visible'] = 'false'

            # Group (only save if set)
            if ch.group:
                section['group'] = ch.group

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

            # Terminal configuration (only save if not default)
            if ch.terminal_config != 'RSE':
                section['terminal_config'] = ch.terminal_config

            # RTD-specific (only save if not default)
            if ch.rtd_type != 'Pt100':
                section['rtd_type'] = ch.rtd_type
            if ch.rtd_resistance != 100.0:
                section['rtd_resistance'] = str(ch.rtd_resistance)
            if ch.rtd_wiring != '4-wire':
                section['rtd_wiring'] = ch.rtd_wiring
            if ch.rtd_current != 0.001:
                section['rtd_current'] = str(ch.rtd_current)

            # Strain gauge-specific (only save if not default)
            if ch.strain_config != 'full-bridge':
                section['strain_config'] = ch.strain_config
            if ch.strain_excitation_voltage != 2.5:
                section['strain_excitation_voltage'] = str(ch.strain_excitation_voltage)
            if ch.strain_gage_factor != 2.0:
                section['strain_gage_factor'] = str(ch.strain_gage_factor)
            if ch.strain_resistance != 350.0:
                section['strain_resistance'] = str(ch.strain_resistance)

            # IEPE-specific (only save if not default)
            if ch.iepe_sensitivity != 100.0:
                section['iepe_sensitivity'] = str(ch.iepe_sensitivity)
            if ch.iepe_current != 0.004:
                section['iepe_current'] = str(ch.iepe_current)
            if ch.iepe_coupling != 'AC':
                section['iepe_coupling'] = ch.iepe_coupling

            # Resistance-specific (only save if not default)
            if ch.resistance_range != 1000.0:
                section['resistance_range'] = str(ch.resistance_range)
            if ch.resistance_wiring != '4-wire':
                section['resistance_wiring'] = ch.resistance_wiring

            # Counter-specific (only save if not default)
            if ch.counter_mode != 'frequency':
                section['counter_mode'] = ch.counter_mode
            if ch.pulses_per_unit != 1.0:
                section['pulses_per_unit'] = str(ch.pulses_per_unit)
            if ch.counter_edge != 'rising':
                section['counter_edge'] = ch.counter_edge
            if ch.counter_reset_on_read:
                section['counter_reset_on_read'] = 'true'
            if ch.counter_min_freq != 0.1:
                section['counter_min_freq'] = str(ch.counter_min_freq)
            if ch.counter_max_freq != 1000.0:
                section['counter_max_freq'] = str(ch.counter_max_freq)

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
        base = self.get_topic_base()

        config_data = {
            "channels": {},
            "modules": {},
            "chassis": {},
            "safety_actions": {}
        }

        for name, channel in self.config.channels.items():
            # display_name removed - use name (TAG) everywhere per ISA-5.1
            config_data["channels"][name] = {
                "name": name,  # TAG is the only identifier
                "module": channel.module,
                "physical_channel": channel.physical_channel,
                "type": channel.channel_type.value,
                "channel_type": channel.channel_type.value,
                "description": channel.description,  # For tooltips/documentation only
                "units": channel.units,
                "visible": channel.visible,
                "group": channel.group or channel.module or "Ungrouped",
                "low_limit": channel.low_limit,
                "high_limit": channel.high_limit,
                "low_warning": channel.low_warning,
                "high_warning": channel.high_warning,
                "log": channel.log,
                # Include all config for frontend editing
                "scale_type": channel.scale_type,
                "scale_slope": channel.scale_slope,
                "scale_offset": channel.scale_offset,
                "four_twenty_scaling": channel.four_twenty_scaling,
                "eng_units_min": channel.eng_units_min,
                "eng_units_max": channel.eng_units_max,
                "pre_scaled_min": channel.pre_scaled_min,
                "pre_scaled_max": channel.pre_scaled_max,
                "scaled_min": channel.scaled_min,
                "scaled_max": channel.scaled_max,
                "invert": channel.invert,
                "default_state": channel.default_state,
                "default_value": channel.default_value,
                "safety_action": channel.safety_action,
                "safety_interlock": channel.safety_interlock,
                "thermocouple_type": channel.thermocouple_type.value if channel.thermocouple_type else None,
                "cjc_source": channel.cjc_source,
                "voltage_range": channel.voltage_range,
                "current_range_ma": channel.current_range_ma,
                "log_interval_ms": channel.log_interval_ms
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
                "description": chassis.description,
                "connection": chassis.connection,
                "enabled": chassis.enabled,
                "ip_address": chassis.ip_address,
                "serial": chassis.serial,
                "modbus_port": chassis.modbus_port,
                "modbus_baudrate": chassis.modbus_baudrate,
                "modbus_parity": chassis.modbus_parity,
                "modbus_stopbits": chassis.modbus_stopbits,
                "modbus_bytesize": chassis.modbus_bytesize,
                "modbus_timeout": chassis.modbus_timeout,
                "modbus_retries": chassis.modbus_retries
            }

        self.mqtt_client.publish(
            f"{base}/config/channels",
            json.dumps(config_data),
            retain=True
        )

        logger.info("Published channel configuration")

    def _publish_channel_value(self, channel_name: str, value: Any):
        """Publish a single channel value with scaling info for validation"""
        import math
        try:
            base = self.get_topic_base()
            channel = self.config.channels[channel_name]

            # Check for NaN values (indicates hardware not connected or read failure)
            is_nan = False
            if isinstance(value, float) and math.isnan(value):
                is_nan = True

            # Convert bool to int for comparison
            if is_nan:
                numeric_value = None
            else:
                numeric_value = float(value) if isinstance(value, (int, float)) else (1.0 if value else 0.0)

            # Get raw value if available
            raw_value = self.channel_raw_values.get(channel_name)

            # Get SOE acquisition timestamp (microseconds since epoch)
            acquisition_ts_us = self.channel_acquisition_ts_us.get(channel_name, 0)

            # Handle NaN - JSON doesn't support NaN, so use null and set quality to "bad"
            if is_nan:
                payload = {
                    "value": None,  # JSON null
                    "value_string": "NaN",  # Human readable
                    "timestamp": datetime.now().isoformat(),
                    "acquisition_ts_us": acquisition_ts_us,  # SOE: microsecond precision
                    "units": channel.units,
                    "quality": "bad",
                    "status": "disconnected"
                }
            else:
                payload = {
                    "value": value,
                    "timestamp": datetime.now().isoformat(),
                    "acquisition_ts_us": acquisition_ts_us,  # SOE: microsecond precision
                    "units": channel.units,
                    "quality": "good",
                    "status": "normal"
                }

            # Include raw value and scaling info for validation/debugging
            if raw_value is not None and raw_value != value and not is_nan:
                payload["raw_value"] = raw_value
                scaling_info = get_scaling_info(channel)
                payload["scaling"] = {
                    "type": scaling_info['type'],
                    "applied": scaling_info['type'] != 'none'
                }

            # Check limits and add status (only for numeric channels with limits, skip NaN)
            if not is_nan and channel.low_limit is not None and channel.high_limit is not None:
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
        base = self.get_topic_base()

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
        base = self.get_topic_base()

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

    def _handle_alarm_acknowledge(self, payload: Any):
        """Handle alarm acknowledgment from frontend"""
        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarmId') or payload.get('alarm_id')
        user = payload.get('user', 'Unknown')
        if alarm_id:
            logger.info(f"Alarm acknowledged: {alarm_id} by {user}")
            # Use enhanced alarm manager if available
            if self.alarm_manager:
                self.alarm_manager.acknowledge_alarm(alarm_id, user)
            # Legacy: track in alarms_active (frontend handles display state)

    def _handle_alarm_clear(self, payload: Any):
        """Handle alarm clear from frontend"""
        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarmId') or payload.get('alarm_id')
        if alarm_id:
            # Try to clear by alarm ID
            self._clear_alarm(alarm_id)
            logger.info(f"Alarm clear requested: {alarm_id}")

    def _handle_alarm_reset_latched(self):
        """Reset all latched alarms"""
        logger.info("Reset all latched alarms requested")
        # Use enhanced alarm manager if available
        if self.alarm_manager:
            count = self.alarm_manager.reset_all_latched('User')
            logger.info(f"Reset {count} latched alarms via alarm manager")
        # Legacy: Clear all active alarms
        sources_to_clear = list(self.alarms_active.keys())
        for source in sources_to_clear:
            self._clear_alarm(source)
        logger.info(f"Cleared {len(sources_to_clear)} legacy latched alarms")

    def _handle_alarm_reset(self, payload: Any):
        """Reset (force clear) a specific latched alarm"""
        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarm_id')
        user = payload.get('user', 'Unknown')
        if alarm_id and self.alarm_manager:
            self.alarm_manager.reset_alarm(alarm_id, user)
            logger.info(f"Alarm reset: {alarm_id} by {user}")

    def _handle_alarm_shelve(self, payload: Any):
        """Shelve (temporarily suppress) an alarm"""
        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarm_id')
        user = payload.get('user', 'Unknown')
        reason = payload.get('reason', '')
        duration_s = payload.get('duration_s', 3600)
        if alarm_id and self.alarm_manager:
            self.alarm_manager.shelve_alarm(alarm_id, user, reason, duration_s)
            logger.info(f"Alarm shelved: {alarm_id} by {user} for {duration_s}s")

    def _handle_alarm_unshelve(self, payload: Any):
        """Unshelve an alarm"""
        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarm_id')
        user = payload.get('user', 'Unknown')
        if alarm_id and self.alarm_manager:
            self.alarm_manager.unshelve_alarm(alarm_id, user)
            logger.info(f"Alarm unshelved: {alarm_id} by {user}")

    def _publish_output_response(self, success: bool, channel: str = None,
                                   value: Any = None, error: str = None):
        """Publish response to output/set command"""
        base = self.get_topic_base()
        response = {"success": success}
        if channel is not None:
            response["channel"] = channel
        if value is not None:
            response["value"] = value
        if error is not None:
            response["error"] = error
        self.mqtt_client.publish(f"{base}/output/response", json.dumps(response))

    def _handle_output_set(self, payload: Any):
        """Handle output/set command - set digital or analog output value

        Payload format:
        {
            "channel": "SV1",      # Channel name
            "value": true/false    # For digital, or numeric for analog
        }

        Response published to nisystem/output/response:
        {
            "channel": "SV1",
            "value": true,
            "success": true/false,
            "error": "optional error message"
        }
        """
        # Parse payload
        if not isinstance(payload, dict):
            self._publish_output_response(False, error="Invalid payload format - expected JSON object")
            return

        channel_name = payload.get('channel')
        value = payload.get('value')

        if not channel_name:
            self._publish_output_response(False, error="Missing 'channel' in payload")
            return

        if value is None:
            self._publish_output_response(False, channel=channel_name, error="Missing 'value' in payload")
            return

        # Check if channel exists
        if channel_name not in self.config.channels:
            self._publish_output_response(False, channel=channel_name,
                                          error=f"Unknown channel: {channel_name}")
            return

        channel = self.config.channels[channel_name]

        # Check if this is an output channel
        if channel.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT):
            self._publish_output_response(False, channel=channel_name,
                                          error=f"Channel {channel_name} is not an output channel (type: {channel.channel_type.value})")
            return

        # Check safety interlocks
        if channel.safety_interlock:
            if not self._check_interlock(channel.safety_interlock):
                logger.warning(f"Safety interlock prevents write to {channel_name}")
                self._publish_output_response(False, channel=channel_name, value=value,
                                              error=f"Safety interlock active: {channel.safety_interlock}")
                return

        # Write the value
        logger.info(f"Setting output {channel_name} = {value}")

        try:
            # Determine which backend handles this channel
            is_modbus = channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)

            if is_modbus and self.modbus_reader:
                self.modbus_reader.write_channel(channel_name, value)
            elif self.simulator:
                self.simulator.write_channel(channel_name, value)
            elif self.hardware_reader:
                self.hardware_reader.write_channel(channel_name, value)

            # Update cache
            with self.values_lock:
                self.channel_values[channel_name] = value
                self.channel_timestamps[channel_name] = time.time()

            # Publish acknowledgment
            self._publish_channel_value(channel_name, value)

            # Publish success response
            self._publish_output_response(True, channel=channel_name, value=value)

            logger.info(f"Output {channel_name} set to {value}")

        except Exception as e:
            logger.error(f"Failed to set output {channel_name}: {e}")
            self._publish_output_response(False, channel=channel_name, value=value, error=str(e))

    def _handle_channel_reset(self, payload: Any):
        """Reset a channel value (e.g., counter to zero)"""
        channel_name = payload.get('channel') if isinstance(payload, dict) else None
        if not channel_name:
            logger.warning("Channel reset requested but no channel specified")
            return

        if channel_name not in self.config.channels:
            logger.warning(f"Channel reset requested for unknown channel: {channel_name}")
            return

        channel = self.config.channels[channel_name]

        # Check if this is a counter channel
        if channel.channel_type == ChannelType.COUNTER:
            logger.info(f"Resetting counter channel: {channel_name}")

            # Reset in simulator if running
            if self.simulator:
                self.simulator.reset_counter(channel_name)

            # Reset in hardware if available
            if self.hardware_reader:
                self.hardware_reader.reset_counter(channel_name)

            # Reset cached value
            with self.values_lock:
                self.channel_values[channel_name] = 0
                self.channel_timestamps[channel_name] = time.time()

            # Publish the reset value
            self._publish_channel_value(channel_name, 0)
            logger.info(f"Counter {channel_name} reset to 0")
        else:
            logger.warning(f"Channel reset not supported for channel type: {channel.channel_type}")

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
            # SOE: Capture high-precision acquisition timestamp (microseconds since epoch)
            acquisition_ts_us = time.time_ns() // 1000

            # Only acquire data if acquiring flag is set
            if self.acquiring:
                try:
                    # Read raw values from all available sources
                    raw_values = {}

                    # Read from simulator or NI hardware
                    if self.simulator:
                        raw_values.update(self.simulator.read_all())
                    elif self.hardware_reader:
                        raw_values.update(self.hardware_reader.read_all())

                    # Read from Modbus devices (if configured)
                    if self.modbus_reader:
                        modbus_values = self.modbus_reader.read_all()
                        raw_values.update(modbus_values)

                    # Read from external data sources (REST API, OPC-UA, etc.)
                    if self.data_source_manager:
                        data_source_values = self.data_source_manager.get_all_values()
                        raw_values.update(data_source_values)

                    # Apply scaling and update values under lock
                    with self.values_lock:
                        for name, raw_value in raw_values.items():
                            # Apply scaling based on channel configuration
                            if name in self.config.channels:
                                channel = self.config.channels[name]
                                # Don't apply scaling to output channels - they store engineering units directly
                                if channel.channel_type in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT):
                                    self.channel_values[name] = raw_value
                                else:
                                    scaled_value = apply_scaling(channel, raw_value)
                                    self.channel_values[name] = scaled_value
                                    # Store raw value for diagnostics
                                    self.channel_raw_values[name] = raw_value
                            else:
                                self.channel_values[name] = raw_value
                            self.channel_timestamps[name] = start_time
                            # SOE: Store high-precision acquisition timestamp
                            self.channel_acquisition_ts_us[name] = acquisition_ts_us

                    # Check safety OUTSIDE the lock (using scaled values)
                    for name in raw_values:
                        if name in self.channel_values:
                            self._check_safety(name, self.channel_values[name])

                            # Also process through enhanced alarm manager
                            if self.alarm_manager:
                                try:
                                    self.alarm_manager.process_value(name, self.channel_values[name])
                                except Exception as e:
                                    logger.debug(f"Alarm manager error for {name}: {e}")

                    # Process user variables (accumulators, timers, stats, etc.)
                    if self.user_variables:
                        self.user_variables.process_scan(self.channel_values)
                        # Process formula blocks (must be after process_scan so user vars are updated)
                        self.user_variables.process_formula_blocks(self.channel_values)

                    # Process automation triggers
                    if self.trigger_engine:
                        self.trigger_engine.process_scan(self.channel_values)

                    # Process watchdogs (channel health monitoring)
                    if self.watchdog_engine:
                        self.watchdog_engine.process_scan(self.channel_values, self.channel_timestamps)

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
                # Publish user variable values and formula block values (at 1 Hz, not full publish rate)
                if self.user_variables:
                    self._publish_user_variables_values()
                    self._publish_formula_blocks_values()
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

        # Record start time for uptime tracking
        self._start_time = datetime.now()

        # Clear shutdown flag, set running flag
        self._shutdown_requested.clear()
        self.running = True

        # Setup MQTT
        self._setup_mqtt()

        # Start scan thread
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True, name="scan")
        self.scan_thread.start()

        # Start publish thread
        self.publish_thread = threading.Thread(target=self._publish_loop, daemon=True, name="publish")
        self.publish_thread.start()

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat")
        self.heartbeat_thread.start()

        # Start scheduler
        if self.scheduler:
            self.scheduler.start()

        logger.info("DAQ Service started")

        # Try to load last project (if one was saved)
        self._try_load_last_project()

    def stop(self):
        """Stop the DAQ service gracefully"""
        logger.info("Initiating graceful shutdown...")

        # Signal shutdown to all threads
        self._shutdown_requested.set()
        self.running = False

        # Stop acquiring first to prevent new data
        self.acquiring = False

        # Publish shutting_down status
        if self.mqtt_client:
            base = self.get_topic_base()
            self.mqtt_client.publish(f"{base}/status/system", json.dumps({
                "status": "shutting_down",
                "timestamp": datetime.now().isoformat(),
                "node_id": self.config.system.node_id if self.config else "node-001",
                "node_name": self.config.system.node_name if self.config else "Default Node"
            }), retain=True, qos=1)

        # Stop scheduler
        if self.scheduler:
            logger.info("Stopping scheduler...")
            self.scheduler.stop()

        # Stop recording and flush buffer
        if self.recording_manager and self.recording_manager.recording:
            logger.info("Flushing recording buffer...")
            self.recording_manager.stop()

        # Save alarm manager state
        if self.alarm_manager:
            logger.info("Saving alarm manager state...")
            self.alarm_manager.save_all()

        # Join threads with reasonable timeouts
        shutdown_timeout = 5.0  # seconds per thread
        for thread_name, thread in [
            ("heartbeat", self.heartbeat_thread),
            ("scan", self.scan_thread),
            ("publish", self.publish_thread),
        ]:
            if thread and thread.is_alive():
                logger.info(f"Waiting for {thread_name} thread...")
                thread.join(timeout=shutdown_timeout)
                if thread.is_alive():
                    logger.warning(f"{thread_name} thread did not stop gracefully")

        # Close hardware (with retry for busy resources)
        if self.hardware_reader:
            for attempt in range(3):
                try:
                    logger.info("Closing hardware reader...")
                    self.hardware_reader.close()
                    self.hardware_reader = None
                    break
                except Exception as e:
                    logger.warning(f"Hardware close attempt {attempt+1} failed: {e}")
                    time.sleep(0.5)

        # Close Modbus connections
        if self.modbus_reader:
            try:
                logger.info("Closing Modbus reader...")
                self.modbus_reader.close()
                self.modbus_reader = None
            except Exception as e:
                logger.warning(f"Error closing Modbus reader: {e}")

        # Close external data sources
        if self.data_source_manager:
            try:
                logger.info("Closing data source manager...")
                self.data_source_manager.stop_all()
                self.data_source_manager = None
            except Exception as e:
                logger.warning(f"Error closing data source manager: {e}")

        # Final status and disconnect MQTT
        if self.mqtt_client:
            base = self.get_topic_base()
            self.mqtt_client.publish(f"{base}/status/service", json.dumps({
                "status": "offline",
                "timestamp": datetime.now().isoformat()
            }), retain=True, qos=1)
            # Give MQTT time to send the message
            time.sleep(0.2)
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        # Close log file
        if self.log_file:
            self.log_file.flush()
            self.log_file.close()
            self.log_file = None

        logger.info("DAQ Service stopped cleanly")

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
    import sys

    # Import single instance guard
    launcher_path = Path(__file__).parent.parent.parent / "launcher"
    sys.path.insert(0, str(launcher_path))
    from single_instance import SingleInstance

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
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force start by killing existing instance'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Enforce single instance
    instance = SingleInstance("NISystemDAQService")
    if not instance.acquire():
        if args.force:
            logger.warning("Another DAQ service instance detected. Force mode enabled - attempting cleanup...")
            # Try to kill stale instance
            try:
                import psutil
                current_pid = os.getpid()
                killed = False
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.pid == current_pid:
                            continue
                        cmdline = proc.info.get('cmdline') or []
                        if any('daq_service.py' in str(arg) for arg in cmdline):
                            logger.warning(f"Killing stale DAQ service process (PID: {proc.pid})")
                            proc.kill()
                            proc.wait(timeout=5)
                            killed = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                        pass

                if killed:
                    import time
                    time.sleep(2)  # Wait for cleanup
                    # Try to acquire again
                    if not instance.acquire():
                        logger.error("ERROR: Could not acquire lock even after cleanup.")
                        sys.exit(1)
                else:
                    logger.error("ERROR: No stale process found to kill.")
                    sys.exit(1)
            except ImportError:
                logger.error("ERROR: psutil not installed. Cannot use --force mode.")
                logger.error("       Install with: pip install psutil")
                sys.exit(1)
        else:
            logger.error("ERROR: Another instance of DAQ Service is already running.")
            logger.error("       Use --force to kill existing instance and start new one.")
            sys.exit(1)

    logger.info("=" * 80)
    logger.info("DAQ Service Single Instance Lock Acquired")
    logger.info("=" * 80)

    service = DAQService(args.config)
    service.run()


if __name__ == "__main__":
    main()
