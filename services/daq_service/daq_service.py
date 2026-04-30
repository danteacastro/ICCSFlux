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
import queue
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import asdict

import paho.mqtt.client as mqtt

from config_parser import (
    load_config, load_config_safe, validate_config, NISystemConfig, ChannelConfig, ChannelType,
    get_input_channels, get_output_channels, ConfigValidationError, ValidationResult,
    SystemConfig, ThermocoupleType, HardwareSource, ProjectMode, DataViewerConfig,
    get_crio_channels, get_local_daq_channels, get_modbus_channels, get_hardware_source_summary
)
from simulator import HardwareSimulator
try:
    from process_simulator import ProcessSimulator
    PROCESS_SIMULATOR_AVAILABLE = True
except ImportError:
    try:
        # Try tools/ directory (when running from project root)
        _tools_dir = str(Path(__file__).parent.parent.parent / "tools")
        if _tools_dir not in sys.path:
            sys.path.insert(0, _tools_dir)
        from process_simulator import ProcessSimulator
        PROCESS_SIMULATOR_AVAILABLE = True
    except ImportError:
        PROCESS_SIMULATOR_AVAILABLE = False
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
    print(f"DataSourceManager not available: {e}")  # logger not yet defined

from scheduler import SimpleScheduler
from sequence_manager import SequenceManager, Sequence, SequenceStep
from script_manager import ScriptManager, Script, ScriptRunMode, ScriptState
from trigger_engine import TriggerEngine
from watchdog_engine import WatchdogEngine
from device_discovery import DeviceDiscovery
from recording_manager import RecordingManager, RecordingConfig, PostgreSQLWriter
from historian import Historian
from dependency_tracker import DependencyTracker, EntityType
from scaling import apply_scaling, reverse_scaling, get_scaling_info, validate_scaling_config, is_valid_value, validate_and_clamp
from user_variables import UserVariableManager
from alarm_manager import AlarmManager, AlarmConfig, AlarmSeverity, LatchBehavior
from notification_manager import NotificationManager
from safety_manager import SafetyManager, Interlock, InterlockCondition, InterlockControl, SafeStateConfig
from audit_trail import AuditTrail, AuditEventType
from user_session import UserSessionManager, UserRole, Permission
from project_manager import ProjectManager, ProjectStatus
from archive_manager import ArchiveManager
from pid_engine import PIDEngine, PIDLoop, PIDMode
from state_machine import DAQStateMachine, DAQState
from acquisition_events import AcquisitionEventPipeline, AcquisitionEvent
from project_context import ProjectContext
# Note: Azure IoT Hub streaming is handled by external azure_uploader_service.py
# which runs in a separate Python environment (paho-mqtt 1.x for Azure SDK compatibility)

# Try to import nidaqmx - if not available, we'll use simulation only
try:
    import nidaqmx
    from nidaqmx.constants import TerminalConfiguration, ThermocoupleType as NI_TCType
    NIDAQMX_AVAILABLE = True
except Exception:
    NIDAQMX_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DAQService')

class TokenBucketRateLimiter:
    """Simple token bucket rate limiter for MQTT command topics.

    Allows burst up to `capacity` tokens, refills at `rate` tokens/second.
    Thread-safe via GIL (float operations are atomic in CPython).
    """

    def __init__(self, rate: float = 10.0, capacity: float = 20.0):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_check = time.time()

    def allow(self) -> bool:
        """Check if a request should be allowed. Consumes one token."""
        now = time.time()
        elapsed = now - self._last_check
        self._last_check = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

class ScanTimingStats:
    """Lightweight scan loop timing statistics.

    Tracks min/max/mean cycle time, jitter (stddev), and overrun count
    over a rolling window. Resets when acquisition stops.
    """

    def __init__(self, target_ms: float, window_size: int = 200):
        self.target_ms = target_ms
        self._window_size = window_size
        self.reset()

    def reset(self):
        self._samples: list = []
        self.overruns = 0
        self.total_scans = 0

    def record(self, dt_ms: float):
        self.total_scans += 1
        self._samples.append(dt_ms)
        if len(self._samples) > self._window_size:
            self._samples.pop(0)
        if dt_ms > self.target_ms * 1.5:
            self.overruns += 1

    @property
    def min_ms(self) -> float:
        return min(self._samples) if self._samples else 0.0

    @property
    def max_ms(self) -> float:
        return max(self._samples) if self._samples else 0.0

    @property
    def mean_ms(self) -> float:
        return sum(self._samples) / len(self._samples) if self._samples else 0.0

    @property
    def jitter_ms(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        mean = self.mean_ms
        variance = sum((s - mean) ** 2 for s in self._samples) / len(self._samples)
        return variance ** 0.5

    @property
    def actual_rate_hz(self) -> float:
        mean = self.mean_ms
        return 1000.0 / mean if mean > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            'target_ms': round(self.target_ms, 2),
            'actual_ms': round(self.mean_ms, 2),
            'min_ms': round(self.min_ms, 2),
            'max_ms': round(self.max_ms, 2),
            'jitter_ms': round(self.jitter_ms, 3),
            'actual_rate_hz': round(self.actual_rate_hz, 2),
            'overruns': self.overruns,
            'total_scans': self.total_scans,
        }

class MqttLogHandler(logging.Handler):
    """Logging handler that buffers log records for MQTT streaming.

    Captures log records into a thread-safe ring buffer (deque).
    The publish loop drains the buffer periodically and publishes
    entries to MQTT for the dashboard Log Viewer tab.
    """

    def __init__(self, maxlen: int = 500):
        super().__init__()
        self._buffer: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(timespec='milliseconds'),
                'level': record.levelname,
                'logger': record.name,
                'message': self.format(record),
            }
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def drain(self) -> list:
        """Drain all buffered entries. Returns list and clears buffer."""
        with self._lock:
            entries = list(self._buffer)
            self._buffer.clear()
        return entries

    def get_recent(self, count: int = 200, level: str = None) -> list:
        """Get recent entries, optionally filtered by minimum level."""
        with self._lock:
            entries = list(self._buffer)
        if level:
            level_num = getattr(logging, level.upper(), logging.DEBUG)
            entries = [e for e in entries if getattr(logging, e['level'], 0) >= level_num]
        return entries[-count:]

class SecurityMonitor:
    """Security Compliance SC.L2-3.13.1 / SI.L2-3.14.6: MQTT anomaly detection and security monitoring."""

    def __init__(self, max_command_rate: int = 200, max_failed_logins: int = 10):
        self.enabled = False  # Off by default; AdminTab Security toggles this
        self.max_command_rate = max_command_rate  # per minute per session
        self.max_failed_logins = max_failed_logins  # per minute total
        self._command_counts: Dict[str, List[float]] = {}  # session_id -> [timestamps]
        self._failed_logins: List[float] = []
        self._permission_denied_count = 0
        self._unknown_topic_count = 0
        self._anomalies: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def record_command(self, session_id: str, topic: str) -> bool:
        """Record a command and check for flood. Returns True if anomaly detected."""
        if not self.enabled:
            return False
        now = time.time()
        with self._lock:
            if session_id not in self._command_counts:
                self._command_counts[session_id] = []
            timestamps = self._command_counts[session_id]
            timestamps.append(now)
            # Prune older than 60s
            cutoff = now - 60
            self._command_counts[session_id] = [t for t in timestamps if t > cutoff]

            if len(self._command_counts[session_id]) > self.max_command_rate:
                self._record_anomaly('command_flood',
                    f'Session {session_id}: {len(self._command_counts[session_id])} commands/min '
                    f'(limit: {self.max_command_rate})')
                return True  # is anomaly
        return False

    def record_failed_login(self) -> bool:
        """Record a failed login attempt. Returns True if brute-force threshold exceeded."""
        if not self.enabled:
            return False
        now = time.time()
        with self._lock:
            self._failed_logins.append(now)
            cutoff = now - 60
            self._failed_logins = [t for t in self._failed_logins if t > cutoff]

            if len(self._failed_logins) > self.max_failed_logins:
                self._record_anomaly('brute_force',
                    f'{len(self._failed_logins)} failed logins/min (limit: {self.max_failed_logins})')
                return True
        return False

    def record_permission_denied(self):
        with self._lock:
            self._permission_denied_count += 1

    def record_unknown_topic(self, topic: str):
        with self._lock:
            self._unknown_topic_count += 1
            if self._unknown_topic_count <= 5:  # Only log first few
                self._record_anomaly('unknown_topic', f'Command to unrecognized topic: {topic}')

    def _record_anomaly(self, anomaly_type: str, description: str):
        self._anomalies.append({
            'type': anomaly_type,
            'description': description,
            'timestamp': datetime.now().isoformat()
        })
        logger.warning(f"[SECURITY] Anomaly detected: {description}")

    def get_summary(self) -> Dict[str, Any]:
        """Get security summary for publishing."""
        with self._lock:
            now = time.time()
            cutoff = now - 60
            total_commands = sum(
                len([t for t in ts if t > cutoff])
                for ts in self._command_counts.values()
            )
            recent_failed = len([t for t in self._failed_logins if t > cutoff])

            summary = {
                'timestamp': datetime.now().isoformat(),
                'commands_per_minute': total_commands,
                'active_sessions': len(self._command_counts),
                'failed_logins_per_minute': recent_failed,
                'permission_denied_total': self._permission_denied_count,
                'unknown_topic_total': self._unknown_topic_count,
                'recent_anomalies': self._anomalies[-10:],  # Last 10
                'anomaly_count': len(self._anomalies),
            }
            return summary

    def get_and_clear_anomalies(self) -> List[Dict[str, Any]]:
        """Get new anomalies and clear them."""
        with self._lock:
            anomalies = self._anomalies[:]
            self._anomalies.clear()
            return anomalies

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
        self._shutdown_requested = threading.Event()

        # State machine for acquisition lifecycle (replaces _acquiring Event + acquisition_state string)
        self._state_machine = DAQStateMachine(DAQState.STOPPED)
        # Legacy: _stop_command_time removed — state sync now uses dedicated /state topic
        logger.info("Acquisition state initialized: STOPPED (safe startup)")

        # Command queue: decouples MQTT callback thread from message processing
        # Critical commands (acquire, recording, session, safe-state) use per-topic
        # callbacks and bypass this queue. All other messages go through here.
        self._command_queue: queue.Queue = queue.Queue(maxsize=5000)
        self._command_thread: Optional[threading.Thread] = None

        # Rate limiters for command topics (prevent message flood)
        # Critical commands (acquire/stop/safe-state) bypass these via message_callback_add
        self._rate_limiters: Dict[str, TokenBucketRateLimiter] = {
            'output': TokenBucketRateLimiter(rate=50.0, capacity=100.0),
            'script': TokenBucketRateLimiter(rate=5.0, capacity=10.0),
            'config': TokenBucketRateLimiter(rate=2.0, capacity=5.0),
            'alarm': TokenBucketRateLimiter(rate=10.0, capacity=20.0),
            'interlock': TokenBucketRateLimiter(rate=10.0, capacity=20.0),
            'auth': TokenBucketRateLimiter(rate=5.0, capacity=10.0),
            'discovery': TokenBucketRateLimiter(rate=1.0, capacity=3.0),
            'sequence': TokenBucketRateLimiter(rate=5.0, capacity=10.0),
            'schedule': TokenBucketRateLimiter(rate=2.0, capacity=5.0),
            'pid': TokenBucketRateLimiter(rate=10.0, capacity=20.0),
            'station': TokenBucketRateLimiter(rate=2.0, capacity=5.0),
        }
        self._rate_limit_warn_times: Dict[str, float] = {}
        # Global fallback limiter for any topic not matching a specific prefix
        self._global_rate_limiter = TokenBucketRateLimiter(rate=20.0, capacity=40.0)

        # Service start time for uptime tracking
        self._start_time: Optional[datetime] = None

        # Heartbeat state
        self._heartbeat_sequence = 0
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_interval = 2.0  # seconds

        # MQTT connection tracking (None=never connected, True=connected, False=disconnected)
        self._mqtt_connected: Optional[bool] = None
        self._mqtt_auth_failures: int = 0

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
        # Units for script-published py.* values, populated by _script_publish_value
        # so the historian and other consumers know what units the script declared.
        self._published_units: Dict[str, str] = {}  # py.NAME -> units string
        # SOE (Sequence of Events) support - microsecond precision acquisition timestamps
        self.channel_acquisition_ts_us: Dict[str, int] = {}  # Microseconds since epoch
        # Rate-limited warning/log flags (bounded dicts, not dynamic setattr)
        self._logged_open_tc: set = set()           # Channels with open TC already logged
        self._stale_warn_times: Dict[str, float] = {}  # Channel -> last stale warning time

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.publish_thread: Optional[threading.Thread] = None

        # Locks
        self.values_lock = threading.Lock()
        # Output write serialization lock — prevents output writes from racing
        # when triggers, scripts, MQTT commands, watchdogs, and safe-state all
        # try to write at the same time. Without this, write order is non-
        # deterministic which is a safety hazard for valves/relays.
        self.output_write_lock = threading.Lock()
        self.state_lock = threading.Lock()  # Protects acquiring/recording state transitions

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

        # Multi-project station management
        self.active_projects: Dict[str, ProjectContext] = {}
        self._next_color_index = 0
        self._station_state_path = Path('config/station_state.json')
        self._station_configs_dir = Path('config/stations')
        self._system_mode = 'standalone'  # 'standalone' or 'station'

        # Loop timing for status display
        self.last_scan_dt_ms = 0.0
        self.last_publish_dt_ms = 0.0
        self._scan_timing = ScanTimingStats(target_ms=0.0)  # Updated when config loaded

        # Scheduler for automated start/stop
        self.scheduler: Optional[SimpleScheduler] = None

        # Device discovery
        self.device_discovery = DeviceDiscovery()

        # cRIO config push tracking for retry logic (non-blocking)
        self._pending_crio_pushes: Dict[str, Dict[str, Any]] = {}  # node_id -> {config, attempts, timestamp}
        self._crio_push_lock = threading.Lock()
        self._crio_config_versions: Dict[str, str] = {}  # node_id -> expected config hash
        self._previous_project_node_ids: set = set()  # node IDs from last loaded project
        self._CRIO_CONFIG_TIMEOUT = 15.0  # seconds — 96ch over TLS needs ~5-6s
        self._CRIO_CONFIG_MAX_RETRIES = 3
        # Synchronous config push waiting (for START command - must wait for ACK)
        self._crio_config_ack_events: Dict[str, threading.Event] = {}  # node_id -> Event
        # Synchronous stop waiting (for STOP command - wait for cRIO to confirm)
        self._crio_stop_ack_events: Dict[str, threading.Event] = {}  # node_id -> Event
        # Debounced config push (for bulk create/update/delete - coalesces rapid calls)
        self._crio_push_debounce_timer: Optional[threading.Timer] = None
        self._crio_push_debounce_delay = 0.5  # 500ms debounce

        # Opto22 config push tracking (mirrors cRIO pattern)
        self._opto22_config_versions: Dict[str, str] = {}  # node_id -> expected config hash

        # CFP config push tracking (mirrors cRIO/Opto22 pattern)
        self._cfp_config_versions: Dict[str, str] = {}  # node_id -> expected config hash

        # Non-blocking MQTT publish queue (prevents scan loop blocking on slow broker)
        self._publish_queue: queue.Queue[Tuple[str, str, int, bool]] = queue.Queue(maxsize=10000)
        self._publish_thread: Optional[threading.Thread] = None
        self._publish_queue_drops = 0  # Track dropped messages due to full queue

        # Recording manager
        self.recording_manager: Optional[RecordingManager] = None

        # Dependency tracker
        self.dependency_tracker: Optional[DependencyTracker] = None

        # Sequence manager
        self.sequence_manager: Optional[SequenceManager] = None

        # Script manager (Python script execution)
        self.script_manager: Optional[ScriptManager] = None

        # Interactive console (IPython-like REPL) - persistent namespace
        self._console_namespace: Optional[Dict[str, Any]] = None

        # Trigger engine (automation triggers)
        self.trigger_engine: Optional[TriggerEngine] = None

        # Watchdog engine (channel monitoring)
        self.watchdog_engine: Optional[WatchdogEngine] = None

        # User variable manager
        self.user_variables: Optional[UserVariableManager] = None

        # Enhanced alarm manager
        self.alarm_manager: Optional[AlarmManager] = None

        # Notification manager (Twilio SMS + Email)
        self.notification_manager: Optional[NotificationManager] = None

        # Backend safety manager (interlocks, latch, trip actions)
        self.safety_manager: Optional[SafetyManager] = None

        # Audit trail (21 CFR Part 11 / ALCOA+ compliance)
        self.audit_trail: Optional[AuditTrail] = None

        # User session manager (role-based access control)
        self.user_session_manager: Optional[UserSessionManager] = None

        self.security_monitor = SecurityMonitor()

        # Project manager (backup, validation, safety locking)
        self.project_manager: Optional[ProjectManager] = None

        # Archive manager (long-term data retention)
        self.archive_manager: Optional[ArchiveManager] = None

        # PID control engine
        self.pid_engine: Optional[PIDEngine] = None

        # Acquisition event pipeline (structured lifecycle event tracking)
        self._acq_events: Optional[AcquisitionEventPipeline] = None

        # Scan loop health tracking
        self._scan_consecutive_errors = 0
        self._scan_total_errors = 0
        self._scan_loop_healthy = True
        self._last_successful_scan_time = 0.0

        # Safety evaluation health tracking
        self._safety_eval_failures = 0
        self._last_safety_eval_time = 0.0

        # Historian error tracking
        self._historian_error_count = 0

        # Health publishing
        self._last_health_publish_time = 0.0

        # Note: Azure IoT Hub streaming is handled by external azure_uploader_service
        # Config is stored in self.config.system.azure_iot and used when recording starts

        # Resource monitoring
        self._cpu_percent = 0.0
        self._memory_mb = 0.0
        self._disk_percent = 0.0
        self._disk_used_gb = 0.0
        self._disk_total_gb = 0.0
        self._resource_monitor_enabled = False
        self._psutil = None  # Store psutil module reference for disk_usage
        try:
            import psutil
            self._psutil = psutil
            self._process = psutil.Process()
            self._resource_monitor_enabled = True
        except ImportError:
            logger.warning("psutil not installed - resource monitoring disabled")
            self._process = None

        # MQTT log streaming handler (captures log records for dashboard Log Viewer)
        self._log_handler = MqttLogHandler(maxlen=500)
        self._log_handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(self._log_handler)
        self._log_publish_counter = 0

        self._load_config()
        self._init_scheduler()
        self._init_recording_manager()
        self._init_historian()
        self._init_dependency_tracker()
        self._init_sequence_manager()
        self._init_script_manager()
        self._init_trigger_engine()
        self._init_watchdog_engine()
        self._init_user_variables()
        self._init_alarm_manager()
        self._init_notification_manager()
        self._init_safety_manager()
        self._init_audit_trail()
        self._init_user_session_manager()
        self._init_project_manager()
        self._init_archive_manager()
        self._init_pid_engine()
        self._init_azure_uploader()

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
        """Thread-safe acquiring state accessor (reads from state machine)"""
        return self._state_machine.is_acquiring

    @property
    def acquisition_state(self) -> str:
        """Current acquisition state as string (reads from state machine)"""
        return self._state_machine.acquisition_state

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
                self.simulator = self._create_simulator()
                self.hardware_reader = None
            elif not HW_READER_AVAILABLE:
                logger.error(
                    "NI-DAQmx driver not installed — running in SIMULATION MODE. "
                    "Install NI-DAQmx to use real hardware: https://ni.com/downloads"
                )
                self.simulator = self._create_simulator()
                self.hardware_reader = None
                # Set flag so frontend shows the SIM MODE banner
                self.config.system.simulation_mode = True
            else:
                # Real hardware mode
                logger.info("Initializing hardware reader for real NI hardware")
                try:
                    self.hardware_reader = HardwareReader(self.config)
                    self.simulator = None
                    logger.info("Hardware reader initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize hardware reader: {e}")
                    logger.warning(
                        "Falling back to SIMULATION MODE — check hardware connection"
                    )
                    self.hardware_reader = None
                    self.simulator = self._create_simulator()
                    # Set flag so frontend shows the SIM MODE banner
                    self.config.system.simulation_mode = True

            # Initialize Modbus reader if we have Modbus devices configured
            self._init_modbus_reader()

            # Initialize external data sources (REST API, OPC-UA, etc.)
            self._init_data_sources()

            # Initialize channel values
            for name, channel in self.config.channels.items():
                if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[name] = channel.default_state
                elif channel.channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT):
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

    def _apply_project_config(self, project_data: Dict[str, Any]) -> tuple[bool, str]:
        """Apply configuration from project JSON (channels, system settings)

        This replaces the need for a separate .ini file - all config is in the project JSON.

        Args:
            project_data: The loaded project JSON dict

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        try:
            # Parse system settings from project
            sys_data = project_data.get("system", {})

            # Parse project mode (cdaq = PC is PLC, crio = cRIO is PLC)
            mode_str = sys_data.get("project_mode", "cdaq").lower()
            try:
                project_mode = ProjectMode(mode_str)
            except ValueError:
                logger.warning(f"Unknown project_mode '{mode_str}', defaulting to 'cdaq'")
                project_mode = ProjectMode.CDAQ

            # Fall back to current config (from system.ini) for fields not in project JSON
            cur = self.config.system if self.config else SystemConfig()

            system = SystemConfig(
                mqtt_broker=sys_data.get("mqtt_broker", "localhost"),
                mqtt_port=int(sys_data.get("mqtt_port", 1883)),
                mqtt_base_topic=sys_data.get("mqtt_base_topic", "nisystem"),
                scan_rate_hz=min(float(sys_data.get("scan_rate_hz", 4)), 100.0),
                publish_rate_hz=min(float(sys_data.get("publish_rate_hz", 4)), 10.0),
                simulation_mode=sys_data.get("simulation_mode", False),
                log_directory=sys_data.get("log_directory", "./logs"),
                config_reload_topic=sys_data.get("config_reload_topic", "nisystem/config/reload"),
                project_mode=project_mode,
                # Preserve infrastructure fields from system.ini
                node_id=cur.node_id,
                node_name=cur.node_name,
                default_project=cur.default_project,
                # Per-project operational settings (fall back to system.ini defaults)
                log_level=sys_data.get("log_level", cur.log_level),
                log_max_file_size_mb=int(sys_data.get("log_max_file_size_mb", cur.log_max_file_size_mb)),
                log_backup_count=int(sys_data.get("log_backup_count", cur.log_backup_count)),
                service_heartbeat_interval_sec=float(sys_data.get("service_heartbeat_interval_sec", cur.service_heartbeat_interval_sec)),
                service_health_timeout_sec=float(sys_data.get("service_health_timeout_sec", cur.service_health_timeout_sec)),
                service_shutdown_timeout_sec=float(sys_data.get("service_shutdown_timeout_sec", cur.service_shutdown_timeout_sec)),
                service_command_ack_timeout_sec=float(sys_data.get("service_command_ack_timeout_sec", cur.service_command_ack_timeout_sec)),
                dataviewer_retention_days=int(sys_data.get("dataviewer_retention_days", cur.dataviewer_retention_days)),
            )

            # Parse channels from project
            channels_data = project_data.get("channels", {})
            channels: Dict[str, ChannelConfig] = {}

            for name, ch_data in channels_data.items():
                # Determine channel type
                ch_type_str = ch_data.get("channel_type", "voltage")
                channel_type = ChannelType(ch_type_str)

                # Parse thermocouple type if present and not None
                tc_type = None
                if ch_data.get("thermocouple_type"):
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
                    eng_units_min=float(ch_data["eng_units_min"]) if ch_data.get("eng_units_min") is not None else None,
                    eng_units_max=float(ch_data["eng_units_max"]) if ch_data.get("eng_units_max") is not None else None,
                    pre_scaled_min=float(ch_data["pre_scaled_min"]) if ch_data.get("pre_scaled_min") is not None else None,
                    pre_scaled_max=float(ch_data["pre_scaled_max"]) if ch_data.get("pre_scaled_max") is not None else None,
                    scaled_min=float(ch_data["scaled_min"]) if ch_data.get("scaled_min") is not None else None,
                    scaled_max=float(ch_data["scaled_max"]) if ch_data.get("scaled_max") is not None else None,
                    voltage_range=float(ch_data.get("voltage_range", 10.0)),
                    current_range_ma=float(ch_data.get("current_range_ma", 20.0)),
                    terminal_config=ch_data.get("terminal_config", "differential"),
                    thermocouple_type=tc_type,
                    cjc_source=ch_data.get("cjc_source", "internal"),
                    cjc_value=float(ch_data.get("cjc_value", 25.0)),
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
                    low_limit=float(ch_data["low_limit"]) if ch_data.get("low_limit") is not None else None,
                    high_limit=float(ch_data["high_limit"]) if ch_data.get("high_limit") is not None else None,
                    low_warning=float(ch_data["low_warning"]) if ch_data.get("low_warning") is not None else None,
                    high_warning=float(ch_data["high_warning"]) if ch_data.get("high_warning") is not None else None,
                    # ISA-18.2 Alarm Configuration
                    alarm_enabled=ch_data.get("alarm_enabled", False),
                    hihi_limit=float(ch_data["hihi_limit"]) if ch_data.get("hihi_limit") is not None else None,
                    hi_limit=float(ch_data["hi_limit"]) if ch_data.get("hi_limit") is not None else None,
                    lo_limit=float(ch_data["lo_limit"]) if ch_data.get("lo_limit") is not None else None,
                    lolo_limit=float(ch_data["lolo_limit"]) if ch_data.get("lolo_limit") is not None else None,
                    alarm_priority=ch_data.get("alarm_priority", "medium"),
                    alarm_deadband=float(ch_data.get("alarm_deadband", 1.0)),
                    alarm_delay_sec=float(ch_data.get("alarm_delay_sec", 0.0)),
                    # Digital Input Alarm
                    digital_alarm_enabled=ch_data.get("digital_alarm_enabled", False),
                    digital_expected_state=ch_data.get("digital_expected_state", "HIGH"),
                    digital_debounce_ms=int(ch_data.get("digital_debounce_ms", 100)),
                    digital_invert=ch_data.get("digital_invert", False),
                    # Safety
                    safety_action=ch_data.get("safety_action"),
                    safety_interlock=ch_data.get("safety_interlock"),
                    # Logging
                    log=ch_data.get("log", True),
                    log_interval_ms=int(ch_data.get("log_interval_ms", 1000)),
                    # Multi-node / cRIO support
                    # Accept both node_id and source_node_id for frontend/backend compatibility
                    source_type=ch_data.get("source_type", "local"),
                    source_node_id=ch_data.get("source_node_id") or ch_data.get("node_id", "")
                )

            # Create new config with parsed data
            # Keep existing chassis/modules/safety_actions if available
            self.config = NISystemConfig(
                system=system,
                dataviewer=self.config.dataviewer if self.config else DataViewerConfig(),
                chassis=self.config.chassis if self.config else {},
                modules=self.config.modules if self.config else {},
                channels=channels,
                safety_actions=self.config.safety_actions if self.config else {}
            )

            # Reinitialize hardware reader or simulator based on new config
            if self.config.system.simulation_mode:
                logger.info("Simulation mode enabled - using hardware simulator")
                self.simulator = self._create_simulator()
                self.hardware_reader = None
            elif not HW_READER_AVAILABLE:
                logger.error(
                    "NI-DAQmx driver not installed — running in SIMULATION MODE. "
                    "Install NI-DAQmx to use real hardware: https://ni.com/downloads"
                )
                self.simulator = self._create_simulator()
                self.hardware_reader = None
                self.config.system.simulation_mode = True
            else:
                # Real hardware mode
                logger.info("Initializing hardware reader for real NI hardware")
                try:
                    self.hardware_reader = HardwareReader(self.config)
                    self.simulator = None
                    logger.info("Hardware reader initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize hardware reader: {e}")
                    logger.warning(
                        "Falling back to SIMULATION MODE — check hardware connection"
                    )
                    self.hardware_reader = None
                    self.simulator = self._create_simulator()
                    self.config.system.simulation_mode = True

            # Initialize channel values (clear stale entries from previous project)
            old_names = set(self.channel_values.keys())
            new_names = set(self.config.channels.keys())
            for stale in old_names - new_names:
                del self.channel_values[stale]
                self.channel_timestamps.pop(stale, None)
                self.channel_acquisition_ts_us.pop(stale, None)
                self.channel_qualities.pop(stale, None)
            for name, channel in self.config.channels.items():
                if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[name] = channel.default_state
                elif channel.channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT):
                    self.channel_values[name] = channel.default_value
                else:
                    self.channel_values[name] = 0.0

            # Reinitialize Modbus reader for new project's devices
            self._init_modbus_reader()

            # Clear retained MQTT messages for nodes no longer in this project
            new_node_ids = {ch.source_node_id for ch in self.config.channels.values()
                           if ch.source_node_id}
            self._clear_stale_node_retained_messages(new_node_ids)

            # Reinitialize alarm manager with new channel configs
            # This clears old alarms and creates new alarm configs from the new channels
            # IMPORTANT: Clear MQTT retained messages BEFORE clearing alarm manager
            self._publish_alarms_cleared(reason="project_loaded")
            if self.alarm_manager:
                self.alarm_manager.clear_all(clear_configs=True)
            self._init_alarm_manager(from_project=True)

            # Load alarm flood detection settings from project safety config
            safety_data = project_data.get('safety', {})
            flood_cfg = safety_data.get('alarmFlood')
            if flood_cfg and isinstance(flood_cfg, dict) and self.alarm_manager:
                self.alarm_manager.configure_flood(
                    threshold=flood_cfg.get('threshold', 10),
                    window_s=flood_cfg.get('window_s', 60.0)
                )

            # Clear and reload safety manager interlocks from project
            if self.safety_manager:
                self.safety_manager.clear_all()
                # Load interlocks from project if present
                interlocks_data = project_data.get('interlocks', [])
                for interlock_data in interlocks_data:
                    interlock = Interlock.from_dict(interlock_data)
                    self.safety_manager.add_interlock(interlock, 'project_load')
                # Load safe state config from project if present
                safe_state_data = project_data.get('safeStateConfig')
                if safe_state_data:
                    self.safety_manager.update_safe_state_config(safe_state_data)
                logger.info(f"Loaded {len(interlocks_data)} interlocks from project")

            # Load scripts from project
            # Scripts with run_mode=acquisition or session will auto-start when triggered
            if self.script_manager:
                self.script_manager.load_scripts_from_project(project_data)
                script_count = len(self.script_manager.scripts)
                if script_count > 0:
                    logger.info(f"Loaded {script_count} scripts from project")

            # Load user variables and formulas from project
            if self.user_variables:
                var_count = self.user_variables.load_variables_from_project(project_data)
                if var_count > 0:
                    logger.info(f"Loaded {var_count} user variables from project")
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

            # Load PID loops from project
            if self.pid_engine:
                pid_data = project_data.get('pidLoops', {})
                if pid_data:
                    self.pid_engine.load_config(pid_data)
                    loop_count = len(self.pid_engine.loops)
                    if loop_count > 0:
                        logger.info(f"Loaded {loop_count} PID loops from project")

            logger.info(f"Applied project config: {len(channels)} channels")

            # Push cRIO channel config to all online cRIO nodes
            # This ensures cRIO has TAG name -> physical channel mappings
            self._push_config_to_all_crios()

            return True, ""

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to apply project config: {error_msg}")
            import traceback
            traceback.print_exc()
            return False, error_msg

    def _create_simulator(self) -> HardwareSimulator:
        """Create the appropriate simulator — ProcessSimulator if process models are configured."""
        model_configs = None
        if hasattr(self, 'current_project_data') and self.current_project_data:
            sim_section = self.current_project_data.get('simulation', {})
            model_configs = sim_section.get('processModels')

        if model_configs and PROCESS_SIMULATOR_AVAILABLE:
            logger.info(f"Using ProcessSimulator with {len(model_configs)} process model(s)")
            return ProcessSimulator(self.config, model_configs=model_configs)

        return HardwareSimulator(self.config)

    def _init_modbus_reader(self):
        """Initialize Modbus reader if Modbus devices are configured"""
        if not PYMODBUS_AVAILABLE:
            logger.debug("pymodbus not available - Modbus support disabled")
            return

        # Check if we have any Modbus channels configured (explicit type or CFP source)
        has_modbus_channels = any(
            ch.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
            or getattr(ch, 'source_type', '') == 'cfp'
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
            # Close existing reader before creating a new one to avoid leaked connections
            if self.modbus_reader:
                try:
                    self.modbus_reader.close()
                except Exception as e:
                    logger.warning(f"Error closing old Modbus reader: {e}")

            self.modbus_reader = ModbusReader(self.config)
            connection_results = self.modbus_reader.connect_all()

            connected = sum(1 for v in connection_results.values() if v)
            total = len(connection_results)
            logger.info(f"Modbus reader initialized: {connected}/{total} devices connected")

            # Start background polling — Modbus reads asynchronously from the scan loop
            self.modbus_reader.start_polling()

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

        # Stage 2: wire chunk-recording hooks. When recording starts we
        # subscribe a chunk callback on HardwareReader so every hw sample
        # reaches the recording layer (vs. the old scan-rate path that
        # discarded ~99% of samples). When recording stops, we unsubscribe
        # so the producer thread returns to zero-overhead steady state.
        self._chunk_recording_active = False
        self.recording_manager._on_record_start = self._enable_chunk_recording
        self.recording_manager._on_record_stop = self._disable_chunk_recording

        logger.info("Recording manager initialized")

    def _enable_chunk_recording(self):
        """Hook fired when recording_manager.start() succeeds.

        Subscribes the HardwareReader chunk callback so every hardware
        sample reaches the recording layer at hw rate, not scan rate.
        Falls back to the legacy scan-rate write_sample path if the
        reader doesn't support chunk callbacks (e.g. simulator).
        """
        if self.hardware_reader is None or not hasattr(self.hardware_reader, 'set_chunk_callback'):
            return
        try:
            self.hardware_reader.set_chunk_callback(self._on_chunk)
            self._chunk_recording_active = True
            logger.info("Chunk recording enabled — hw-rate sample retention active")
        except Exception as e:
            logger.warning(f"Could not enable chunk recording: {e}")

    def _disable_chunk_recording(self):
        """Hook fired when recording_manager.stop() succeeds.

        Unsubscribes the chunk callback so the producer returns to the
        zero-overhead steady state (no per-read copy, no callback cost).
        """
        if self.hardware_reader is not None and hasattr(self.hardware_reader, 'set_chunk_callback'):
            try:
                self.hardware_reader.set_chunk_callback(None)
            except Exception as e:
                logger.warning(f"Could not unsubscribe chunk callback: {e}")
        self._chunk_recording_active = False
        logger.info("Chunk recording disabled")

    def _on_chunk(self, task_name, channel_names, samples, t0, rate, channel_types):
        """HardwareReader -> RecordingManager bridge for hw-rate recording.

        Called from the reader thread once per successful read with a full
        chunk of samples for one task. Builds extra_row_values (sys.* + uv.*
        + fx.* + other-task cached values) at chunk-emit time and forwards
        the chunk to RecordingManager.write_chunk for per-sample row writing.

        Best-effort: any exception is logged but does NOT propagate, because
        an exception here would surface in the reader thread's catch-all and
        could trip the recovery counter. The reader is more important than
        a single chunk of recording.
        """
        try:
            rm = self.recording_manager
            if rm is None or not rm.recording:
                return

            chunk_set = set(channel_names)

            # Snapshot other-task hardware values from the reader cache.
            # Held lock is fine-grained — copy out and release.
            other_hw: Dict[str, Any] = {}
            try:
                with self.hardware_reader.lock:
                    for n, v in self.hardware_reader.latest_values.items():
                        if n not in chunk_set:
                            other_hw[n] = v
            except Exception:
                pass  # cache best-effort; chunk channels still get written

            # sys.* metadata (mirrors scan-loop layout)
            extras: Dict[str, Any] = {
                'sys.acquiring': 1.0 if self.acquiring else 0.0,
                'sys.session_active': 1.0 if getattr(self, 'session_active', False) else 0.0,
                'sys.recording': 1.0,  # we only fire while recording
            }

            # uv.* and fx.* — only the variables flagged log=True, matching
            # the scan-loop behavior so chunk-mode CSVs have the same columns
            # as scan-mode CSVs.
            if self.user_variables:
                try:
                    for var in self.user_variables.get_all_variables():
                        if not getattr(var, 'log', False):
                            continue
                        extras[f"uv.{var.name}"] = var.value
                    for _block_id, outputs in self.user_variables.get_formula_values_dict().items():
                        for out_name, out_value in outputs.items():
                            extras[f"fx.{out_name}"] = out_value
                except Exception:
                    pass  # uv/fx best-effort

            # Merge other-task HW values (chunk channels remain authoritative
            # since they're set later inside write_chunk per-sample).
            for n, v in other_hw.items():
                extras[n] = v

            # Build channel_configs (units + description) for header generation.
            channel_configs: Dict[str, Any] = {
                name: {'units': ch.units, 'description': ch.description}
                for name, ch in self.config.channels.items()
            }
            channel_configs['sys.acquiring'] = {'units': 'bool', 'description': 'Acquisition active'}
            channel_configs['sys.session_active'] = {'units': 'bool', 'description': 'Test session active'}
            channel_configs['sys.recording'] = {'units': 'bool', 'description': 'Recording active'}
            if self.user_variables:
                try:
                    for var in self.user_variables.get_all_variables():
                        if not getattr(var, 'log', False):
                            continue
                        channel_configs[f"uv.{var.name}"] = {
                            'units': var.units,
                            'description': var.description or var.variable_type,
                        }
                    for block_id, outputs in self.user_variables.get_formula_values_dict().items():
                        block = self.user_variables.formula_blocks.get(block_id)
                        for out_name in outputs:
                            units = ''
                            if block and out_name in block.outputs:
                                units = block.outputs[out_name].get('units', '')
                            channel_configs[f"fx.{out_name}"] = {
                                'units': units,
                                'description': f'Formula: {out_name}',
                            }
                except Exception:
                    pass

            rm.write_chunk(
                task_name=task_name,
                channel_names=channel_names,
                samples=samples,
                t0_epoch=t0,
                rate_hz=rate,
                channel_configs=channel_configs,
                extra_row_values=extras,
            )
        except Exception as e:
            logger.warning(f"_on_chunk error on {task_name}: {e}")

    def _init_historian(self):
        """Initialize the SQLite historian for continuous background data recording."""
        try:
            db_dir = os.path.join(self.config.system.log_directory, 'historian')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, 'historian.db')
            retention = self.config.dataviewer.retention_days
            self.historian = Historian(db_path, retention_days=retention)
            self.historian.prune()
        except Exception as e:
            logger.error(f"Historian initialization failed: {e}")
            self.historian = None

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
        data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
        self.script_manager = ScriptManager(data_dir=data_dir)

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

        # Share the console namespace with scripts - unified Python environment
        # Variables defined in console are accessible in scripts and vice versa
        self.script_manager.on_get_shared_namespace = self._get_console_namespace

        # User variables API (vars.* in scripts)
        self.script_manager.on_get_variable_value = self._script_get_variable_value
        self.script_manager.on_set_variable_value = self._script_set_variable_value
        self.script_manager.on_reset_variable = self._script_reset_variable
        self.script_manager.on_get_variable_names = self._script_get_variable_names
        self.script_manager.on_has_variable = self._script_has_variable

        # PID API (pid.* in scripts)
        self.script_manager.on_get_pid_status = self._script_get_pid_status
        self.script_manager.on_set_pid_setpoint = self._script_set_pid_setpoint
        self.script_manager.on_set_pid_mode = self._script_set_pid_mode
        self.script_manager.on_set_pid_output = self._script_set_pid_output
        self.script_manager.on_set_pid_enabled = self._script_set_pid_enabled
        self.script_manager.on_set_pid_tuning = self._script_set_pid_tuning
        self.script_manager.on_get_pid_loop_ids = self._script_get_pid_loop_ids
        self.script_manager.on_has_pid_loop = self._script_has_pid_loop

        logger.info("Script manager initialized")

    def _init_trigger_engine(self):
        """Initialize the trigger engine for automation triggers"""
        self.trigger_engine = TriggerEngine()

        # Wire up callbacks
        self.trigger_engine.set_output = self._set_output_value
        self.trigger_engine.start_recording = lambda: self.recording_manager.start() if self.recording_manager else None
        self.trigger_engine.stop_recording = lambda: self.recording_manager.stop() if self.recording_manager else None
        self.trigger_engine.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id) if self.sequence_manager else None
        self.trigger_engine.stop_sequence = lambda seq_id: self.sequence_manager.stop_sequence(seq_id) if self.sequence_manager else None
        self.trigger_engine.publish_notification = self._publish_trigger_notification

        logger.info("Trigger engine initialized")

    def _init_watchdog_engine(self):
        """Initialize the watchdog engine for channel monitoring"""
        self.watchdog_engine = WatchdogEngine()

        # Wire up callbacks
        self.watchdog_engine.set_output = self._set_output_value
        self.watchdog_engine.start_recording = lambda: self.recording_manager.start() if self.recording_manager else None
        self.watchdog_engine.stop_recording = lambda: self.recording_manager.stop() if self.recording_manager else None
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

    def _script_set_output(self, channel: str, value) -> bool:
        """Set output from script. Returns True if command was accepted.

        Scripts are subject to safety interlock checks - if an interlock blocks
        the output channel, the command will be rejected and return False.
        """
        if channel not in self.config.channels:
            return False
        ch = self.config.channels[channel]
        if ch.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                                   ChannelType.COUNTER_OUTPUT, ChannelType.PULSE_OUTPUT,
                                   ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL):
            return False

        # Check safety interlocks - scripts must respect interlock blocks
        if self.safety_manager:
            block_result = self.safety_manager.is_output_blocked(channel)
            if block_result.get('blocked', False):
                blocked_by = block_result.get('blockedBy', [])
                interlock_names = [b.get('name', 'Unknown') for b in blocked_by]
                logger.warning(f"Script output blocked by interlock: {channel} = {value} (blocked by: {', '.join(interlock_names)})")
                return False

        try:
            self._set_output_value(channel, value)
            return True
        except Exception as e:
            logger.error(f"Script set_output failed for {channel}: {e}")
            return False

    def _script_start_acquisition(self) -> None:
        """Start acquisition from script"""
        if not self._state_machine.to(DAQState.RUNNING):
            return  # Already running or invalid transition
        self._publish_system_status()
        if self.script_manager:
            self.script_manager.on_acquisition_start()
            self._publish_script_status()  # Update UI with started scripts
        if self.trigger_engine:
            self.trigger_engine.on_acquisition_start()
        if self.watchdog_engine:
            self.watchdog_engine.on_acquisition_start()

    def _script_stop_acquisition(self) -> None:
        """Stop acquisition from script"""
        if not self._state_machine.to(DAQState.STOPPED):
            return  # Already stopped or invalid transition
        self._publish_system_status()
        if self.script_manager:
            self.script_manager.on_acquisition_stop()
            self._publish_script_status()  # Update UI with stopped scripts
        if self.trigger_engine:
            self.trigger_engine.on_acquisition_stop()
        if self.watchdog_engine:
            self.watchdog_engine.on_acquisition_stop()

    def _script_start_recording(self, filename: str = None) -> None:
        """Start recording from script"""
        if self.recording_manager and not self.recording_manager.recording:
            self.recording_manager.start(filename)

    def _script_stop_recording(self) -> None:
        """Stop recording from script"""
        if self.recording_manager and self.recording_manager.recording:
            self.recording_manager.stop()

    def _script_is_session_active(self) -> bool:
        """Check if session is active for script"""
        if self.user_variables:
            return self.user_variables.session.active
        return self.acquiring

    def _script_get_session_elapsed(self) -> float:
        """Get session elapsed time for script"""
        if self.user_variables and self.user_variables.session.active:
            return self.user_variables.get_elapsed_time()
        return 0.0

    def _script_is_recording(self) -> bool:
        """Check if recording is active"""
        if self.recording_manager:
            return self.recording_manager.recording
        return False

    def _script_get_scan_rate(self) -> float:
        """Get current scan rate"""
        return getattr(self.config.system, 'scan_rate', 10.0)

    # User Variables API for scripts (vars.* namespace)
    def _script_get_variable_value(self, name: str):
        """Get user variable value by name for script.

        Returns float for numeric variables, str for string variables.
        """
        if not self.user_variables:
            return 0.0
        # Find variable by name (not id)
        for var in self.user_variables.variables.values():
            if var.name == name:
                # Return appropriate value based on data type
                if var.data_type == 'string' or var.variable_type == 'string':
                    return var.string_value
                return var.value
        return 0.0

    def _script_set_variable_value(self, name: str, value) -> bool:
        """Set user variable value by name for script.

        Accepts float for numeric variables, str for string variables.
        """
        if not self.user_variables:
            return False
        # Find variable by name
        for var in self.user_variables.variables.values():
            if var.name == name:
                return self.user_variables.set_variable_value(var.id, value)
        return False

    def _script_reset_variable(self, name: str) -> bool:
        """Reset user variable by name for script"""
        if not self.user_variables:
            return False
        # Find variable by name
        for var in self.user_variables.variables.values():
            if var.name == name:
                return self.user_variables.reset_variable(var.id)
        return False

    def _script_get_variable_names(self) -> list:
        """Get all user variable names for script"""
        if not self.user_variables:
            return []
        return [var.name for var in self.user_variables.variables.values()]

    def _script_has_variable(self, name: str) -> bool:
        """Check if user variable exists by name"""
        if not self.user_variables:
            return False
        return any(var.name == name for var in self.user_variables.variables.values())

    # PID API callbacks for scripts
    def _script_get_pid_status(self, loop_id: str) -> Optional[dict]:
        """Get PID loop status for script"""
        if not self.pid_engine:
            return None
        loop = self.pid_engine.get_loop(loop_id)
        if loop:
            return loop.to_status_dict()
        return None

    def _script_set_pid_setpoint(self, loop_id: str, value: float) -> bool:
        """Set PID loop setpoint from script"""
        if not self.pid_engine:
            return False
        return self.pid_engine.set_setpoint(loop_id, value)

    def _script_set_pid_mode(self, loop_id: str, mode: str) -> bool:
        """Set PID loop mode from script"""
        if not self.pid_engine:
            return False
        return self.pid_engine.set_mode(loop_id, mode)

    def _script_set_pid_output(self, loop_id: str, value: float) -> bool:
        """Set PID loop manual output from script"""
        if not self.pid_engine:
            return False
        return self.pid_engine.set_manual_output(loop_id, value)

    def _script_set_pid_enabled(self, loop_id: str, enabled: bool) -> bool:
        """Enable/disable PID loop from script"""
        if not self.pid_engine:
            return False
        return self.pid_engine.update_loop(loop_id, {'enabled': enabled})

    def _script_set_pid_tuning(self, loop_id: str, kp: float, ki: float, kd: float) -> bool:
        """Set PID tuning parameters from script"""
        if not self.pid_engine:
            return False
        return self.pid_engine.set_tuning(loop_id, kp, ki, kd)

    def _script_get_pid_loop_ids(self) -> list:
        """Get all PID loop IDs for script"""
        if not self.pid_engine:
            return []
        return list(self.pid_engine.loops.keys())

    def _script_has_pid_loop(self, loop_id: str) -> bool:
        """Check if PID loop exists"""
        if not self.pid_engine:
            return False
        return loop_id in self.pid_engine.loops

    def _script_publish_value(self, script_id: str, name: str, value: float, units: str = '') -> None:
        """Publish computed value from script"""
        # Store in script-published values (py.{name} prefix)
        full_name = f"py.{name}"
        self.channel_values[full_name] = value
        self.channel_timestamps[full_name] = time.time()
        # Track units so historian/recording can report them correctly
        if units:
            self._published_units[full_name] = units

        # Also record in CSV if recording
        if self.recording_manager and self.recording_manager.recording:
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

    # Maximum allowed script code size (256 KB)
    MAX_SCRIPT_CODE_BYTES = 256 * 1024

    def _handle_script_add(self, payload) -> None:
        """Add a new backend script"""
        if not isinstance(payload, dict):
            logger.error(f"Invalid payload for script/add: {type(payload)} - {payload}")
            return

        script_id = payload.get('id', str(uuid.uuid4()))
        name = payload.get('name', 'Untitled Script')
        code = payload.get('code', '')
        run_mode = payload.get('run_mode', 'manual')
        enabled = payload.get('enabled', True)

        # Validate payload sizes
        if len(str(code)) > self.MAX_SCRIPT_CODE_BYTES:
            logger.error(f"Script code exceeds {self.MAX_SCRIPT_CODE_BYTES} byte limit ({len(str(code))} bytes)")
            return
        if len(str(name)) > 256:
            logger.error(f"Script name exceeds 256 char limit")
            return

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script add to cRIO: {name}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/add"
                crio_payload = {
                    'id': script_id,
                    'name': name,
                    'code': code,
                    'run_mode': run_mode,
                    'enabled': enabled
                }
                self.mqtt_client.publish(crio_topic, json.dumps(crio_payload), qos=1)
                logger.info(f"[SCRIPT] Forwarded add to cRIO {node.node_id}")
            # Send response
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "add", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally (PC runs scripts)
        if not self.script_manager:
            return

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
        script_id = payload.get('id')
        if not script_id:
            return

        # Validate code size if code is being updated
        code = payload.get('code')
        if code is not None and len(str(code)) > self.MAX_SCRIPT_CODE_BYTES:
            logger.error(f"Script code exceeds {self.MAX_SCRIPT_CODE_BYTES} byte limit ({len(str(code))} bytes)")
            return

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script update to cRIO: {script_id}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/update"
                self.mqtt_client.publish(crio_topic, json.dumps(payload), qos=1)
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "update", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally
        if not self.script_manager:
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

    def _handle_script_reload(self, payload: dict) -> None:
        """Hot-reload a script without stopping acquisition.

        This allows live code updates while keeping the script's persisted state.
        If the script uses persist()/restore() for state management, that state
        survives the reload.

        Payload:
            id: Script ID to reload
            code: Optional new code (if omitted, reloads existing code)
        """
        script_id = payload.get('id')
        if not script_id:
            logger.warning("[SCRIPT RELOAD] Missing script ID")
            return

        new_code = payload.get('code')  # Optional

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script reload to cRIO: {script_id}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/reload"
                self.mqtt_client.publish(crio_topic, json.dumps(payload), qos=1)
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "reload", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally
        if not self.script_manager:
            logger.warning("[SCRIPT RELOAD] Script manager not available")
            return

        success = self.script_manager.reload_script(script_id, new_code)

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "reload",
                "success": success,
                "script_id": script_id,
                "message": "Script hot-reloaded" if success else "Hot-reload failed"
            })
        )

        if success:
            self._publish_script_status()

    def _handle_script_remove(self, payload: dict) -> None:
        """Remove a backend script"""
        script_id = payload.get('id')
        if not script_id:
            return

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script remove to cRIO: {script_id}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/remove"
                self.mqtt_client.publish(crio_topic, json.dumps({'id': script_id}), qos=1)
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "remove", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally
        if not self.script_manager:
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

    def _handle_script_clear_all(self, payload: Any) -> None:
        """Clear ALL backend scripts - used when loading a project to prevent duplicates"""
        if not self.script_manager:
            return

        # Stop all running scripts and clear the script dictionary
        self.script_manager.stop_all_scripts()
        count = len(self.script_manager.scripts)
        self.script_manager.scripts.clear()
        self.script_manager.runtimes.clear()

        logger.info(f"Cleared all {count} scripts from backend")
        self._publish_script_status()

        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/response",
            json.dumps({
                "action": "clear-all",
                "success": True,
                "cleared_count": count
            })
        )

    def _handle_script_start(self, payload: dict) -> None:
        """Start a backend script"""
        script_id = payload.get('id')
        if not script_id:
            return

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script start to cRIO: {script_id}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/start"
                self.mqtt_client.publish(crio_topic, json.dumps({'id': script_id}), qos=1)
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "start", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally
        if not self.script_manager:
            return

        success = self.script_manager.start_script(script_id)
        logger.info(f"Script start requested: {script_id}, success={success}")

        # Publish status immediately so UI updates
        self._publish_script_status()

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
        script_id = payload.get('id')
        if not script_id:
            return

        # In CRIO mode, forward to cRIO - scripts run on cRIO
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info(f"[SCRIPT] CRIO mode - forwarding script stop to cRIO: {script_id}")
            mqtt_base = self.config.system.mqtt_base_topic
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/script/stop"
                self.mqtt_client.publish(crio_topic, json.dumps({'id': script_id}), qos=1)
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/script/response",
                json.dumps({"action": "stop", "success": True, "script_id": script_id})
            )
            return

        # CDAQ mode - handle locally
        if not self.script_manager:
            return

        success = self.script_manager.stop_script(script_id)
        logger.info(f"Script stop requested: {script_id}, success={success}")

        # Publish status immediately so UI updates
        self._publish_script_status()

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
                "code": script.code,  # Include code so frontend can display it
                "description": getattr(script, 'description', ''),
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

    # =========================================================================
    # INTERACTIVE CONSOLE (IPython-like REPL with Persistent Namespace)
    # =========================================================================

    # Names that are part of the base API (not user-defined variables)
    _CONSOLE_BUILTINS = {
        # Core API
        'tags', 'outputs', 'session',
        # Standard library
        'time', 'math', 'datetime', 'json', 'statistics', 're',
        # Scientific computing
        'np', 'numpy', 'scipy',
        # Math functions
        'abs', 'min', 'max', 'sum', 'round', 'pow',
        'sin', 'cos', 'tan', 'sqrt', 'log', 'log10', 'pi', 'e',
        # Built-ins
        'print', 'len', 'range', 'list', 'dict', 'tuple', 'set',
        'str', 'int', 'float', 'bool', 'True', 'False', 'None',
        'sorted', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
        'isinstance', 'type', 'dir', 'help', 'getattr', 'setattr', 'hasattr',
        '__builtins__', '__name__', '__doc__',
        # Script helper classes (available in unified namespace)
        'RateCalculator', 'Accumulator', 'EdgeDetector', 'RollingStats', 'Scheduler',
        # Unit conversion functions
        'F_to_C', 'C_to_F', 'GPM_to_LPM', 'LPM_to_GPM', 'PSI_to_bar', 'bar_to_PSI',
        'gal_to_L', 'L_to_gal', 'BTU_to_kJ', 'kJ_to_BTU', 'lb_to_kg', 'kg_to_lb',
        # Time utility functions
        'now', 'now_ms', 'now_iso', 'time_of_day', 'elapsed_since', 'format_timestamp',
        # Script-specific functions (added when scripts run)
        'publish', 'next_scan', 'wait_for', 'wait_until', 'persist', 'restore',
    }

    def _get_console_namespace(self) -> dict:
        """Get or create the persistent console namespace."""
        if self._console_namespace is None:
            self._console_namespace = self._build_console_namespace()
        return self._console_namespace

    def _handle_console_execute(self, payload: dict) -> None:
        """Execute a single Python command from the interactive console widget.

        This provides an IPython-like REPL experience with:
        - Persistent namespace (variables survive between commands)
        - Magic commands (%who, %whos, %reset, %time)
        - Access to tags, outputs, session API
        """
        code = payload.get('code', '').strip()
        if not code:
            return

        base = self.get_topic_base()
        result = {'success': False, 'output': '', 'result': '', 'error': ''}

        # Handle magic commands
        if code.startswith('%'):
            result = self._handle_magic_command(code)
            self.mqtt_client.publish(f"{base}/console/result", json.dumps(result))
            return

        try:
            import io
            import contextlib

            # Capture stdout
            stdout_capture = io.StringIO()

            # Get persistent namespace
            namespace = self._get_console_namespace()

            # Execute with stdout capture
            with contextlib.redirect_stdout(stdout_capture):
                # Try to eval first (for expressions that return a value)
                try:
                    compiled = compile(code, '<console>', 'eval')
                    exec_result = eval(compiled, namespace)
                    result['result'] = repr(exec_result) if exec_result is not None else ''
                except SyntaxError:
                    # Fall back to exec for statements
                    compiled = compile(code, '<console>', 'exec')
                    exec(compiled, namespace)
                    result['result'] = ''

            result['output'] = stdout_capture.getvalue()
            result['success'] = True

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False
            logger.debug(f"Console error: {e}")

        # Publish result
        self.mqtt_client.publish(f"{base}/console/result", json.dumps(result))

    def _handle_magic_command(self, code: str) -> dict:
        """Handle IPython-like magic commands."""
        result = {'success': True, 'output': '', 'result': '', 'error': ''}

        parts = code.split(None, 1)
        magic = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''

        try:
            if magic == '%who':
                # List user-defined variable names
                namespace = self._get_console_namespace()
                user_vars = [k for k in namespace.keys() if k not in self._CONSOLE_BUILTINS]
                if user_vars:
                    result['output'] = '  '.join(sorted(user_vars)) + '\n'
                else:
                    result['output'] = 'No user-defined variables.\n'

            elif magic == '%whos':
                # Detailed variable list with types and values
                namespace = self._get_console_namespace()
                user_vars = {k: v for k, v in namespace.items() if k not in self._CONSOLE_BUILTINS}
                if user_vars:
                    lines = ['Variable     Type        Value']
                    lines.append('-' * 50)
                    for name, value in sorted(user_vars.items()):
                        type_name = type(value).__name__
                        # Truncate long values
                        val_str = repr(value)
                        if len(val_str) > 30:
                            val_str = val_str[:27] + '...'
                        lines.append(f'{name:<12} {type_name:<10} {val_str}')
                    result['output'] = '\n'.join(lines) + '\n'
                else:
                    result['output'] = 'No user-defined variables.\n'

            elif magic == '%reset':
                # Reset namespace (clear user variables)
                self._console_namespace = None
                result['output'] = 'Namespace reset. All user variables cleared.\n'

            elif magic == '%time':
                # Time a single statement
                if not args:
                    result['error'] = 'Usage: %time <statement>'
                    result['success'] = False
                else:
                    import time as time_module
                    import io
                    import contextlib

                    namespace = self._get_console_namespace()
                    stdout_capture = io.StringIO()

                    start = time_module.perf_counter()
                    with contextlib.redirect_stdout(stdout_capture):
                        try:
                            compiled = compile(args, '<console>', 'eval')
                            exec_result = eval(compiled, namespace)
                        except SyntaxError:
                            compiled = compile(args, '<console>', 'exec')
                            exec(compiled, namespace)
                            exec_result = None
                    elapsed = time_module.perf_counter() - start

                    output = stdout_capture.getvalue()
                    if output:
                        result['output'] = output

                    # Format timing
                    if elapsed < 0.001:
                        time_str = f'{elapsed * 1000000:.1f} us'
                    elif elapsed < 1:
                        time_str = f'{elapsed * 1000:.2f} ms'
                    else:
                        time_str = f'{elapsed:.3f} s'

                    result['result'] = f'Wall time: {time_str}'
                    if exec_result is not None:
                        result['result'] += f'\nResult: {repr(exec_result)}'

            elif magic == '%vars':
                # Alias for %whos
                return self._handle_magic_command('%whos')

            elif magic == '%store':
                # Persist variables across sessions (like Spyder)
                result = self._handle_store_command(args)

            elif magic == '%help':
                # Show available magic commands
                help_text = """Available magic commands:
  %who     - List user-defined variable names
  %whos    - Detailed variable list (name, type, value)
  %vars    - Alias for %whos
  %reset   - Clear all user-defined variables
  %time    - Time execution of a statement
  %store   - Persist variables across sessions
             %store          - List stored variables
             %store x y      - Store variables x and y
             %store -r       - Restore all stored variables
             %store -r x     - Restore variable x
             %store -d x     - Delete stored variable x
             %store -z       - Clear all stored variables
  %help    - Show this help message

Available APIs:
  tags     - Read channel values: tags.Temperature or tags['Temperature']
  outputs  - Set outputs: outputs.set('Relay1', True)
  session  - Session state: session.active, session.recording, session.elapsed

Helper classes:
  RateCalculator, Accumulator, EdgeDetector, RollingStats, Scheduler

Unit conversions:
  F_to_C, C_to_F, GPM_to_LPM, LPM_to_GPM, PSI_to_bar, bar_to_PSI, etc.
"""
                result['output'] = help_text

            else:
                result['error'] = f"Unknown magic command: {magic}\nType %help for available commands."
                result['success'] = False

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False

        return result

    def _handle_store_command(self, args: str) -> dict:
        """Handle %store magic command for persisting variables.

        Like Spyder's %store:
        - %store          - List stored variables
        - %store x y      - Store variables x and y
        - %store -r       - Restore all stored variables
        - %store -r x     - Restore variable x
        - %store -d x     - Delete stored variable x
        - %store -z       - Clear all stored variables
        """
        import pickle
        import base64
        from pathlib import Path

        result = {'success': True, 'output': '', 'result': '', 'error': ''}

        # Storage file location
        data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
        store_file = data_dir / 'console_store.json'

        # Load existing stored data
        stored_data = {}
        if store_file.exists():
            try:
                with open(store_file, 'r') as f:
                    stored_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load stored variables: {e}")

        def save_store():
            """Save stored data to file"""
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                with open(store_file, 'w') as f:
                    json.dump(stored_data, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save stored variables: {e}")

        def serialize_value(value):
            """Serialize a Python value to storable format"""
            # Try JSON first for simple types
            try:
                json.dumps(value)
                return {'type': 'json', 'data': value}
            except (TypeError, ValueError):
                pass

            # Fall back to pickle for complex types (numpy arrays, etc.)
            try:
                pickled = pickle.dumps(value)
                return {'type': 'pickle', 'data': base64.b64encode(pickled).decode('ascii')}
            except Exception as e:
                raise ValueError(f"Cannot serialize: {e}")

        def deserialize_value(stored):
            """Deserialize a stored value back to Python"""
            if stored['type'] == 'json':
                return stored['data']
            elif stored['type'] == 'pickle':
                pickled = base64.b64decode(stored['data'])
                return pickle.loads(pickled)
            else:
                raise ValueError(f"Unknown storage type: {stored['type']}")

        args_parts = args.split()
        namespace = self._get_console_namespace()

        try:
            if not args_parts:
                # List stored variables
                if not stored_data:
                    result['output'] = 'No stored variables.\n'
                else:
                    lines = ['Stored variables:']
                    for name, info in sorted(stored_data.items()):
                        type_hint = info.get('type_hint', 'unknown')
                        lines.append(f'  {name} ({type_hint})')
                    result['output'] = '\n'.join(lines) + '\n'

            elif args_parts[0] == '-r':
                # Restore variables
                var_names = args_parts[1:] if len(args_parts) > 1 else list(stored_data.keys())

                if not var_names:
                    result['output'] = 'No stored variables to restore.\n'
                else:
                    restored = []
                    for name in var_names:
                        if name in stored_data:
                            try:
                                value = deserialize_value(stored_data[name])
                                namespace[name] = value
                                restored.append(name)
                            except Exception as e:
                                result['output'] += f"Failed to restore '{name}': {e}\n"
                        else:
                            result['output'] += f"Variable '{name}' not found in store.\n"

                    if restored:
                        result['output'] += f"Restored: {', '.join(restored)}\n"

            elif args_parts[0] == '-d':
                # Delete stored variables
                if len(args_parts) < 2:
                    result['error'] = 'Usage: %store -d <varname>'
                    result['success'] = False
                else:
                    deleted = []
                    for name in args_parts[1:]:
                        if name in stored_data:
                            del stored_data[name]
                            deleted.append(name)
                        else:
                            result['output'] += f"Variable '{name}' not in store.\n"

                    if deleted:
                        save_store()
                        result['output'] += f"Deleted from store: {', '.join(deleted)}\n"

            elif args_parts[0] == '-z':
                # Clear all stored variables
                count = len(stored_data)
                stored_data.clear()
                save_store()
                result['output'] = f'Cleared {count} stored variable(s).\n'

            else:
                # Store variables
                stored = []
                for name in args_parts:
                    if name.startswith('-'):
                        result['error'] = f"Unknown option: {name}"
                        result['success'] = False
                        return result

                    if name not in namespace:
                        result['output'] += f"Variable '{name}' not found in namespace.\n"
                        continue

                    if name in self._CONSOLE_BUILTINS:
                        result['output'] += f"Cannot store built-in '{name}'.\n"
                        continue

                    try:
                        value = namespace[name]
                        stored_data[name] = serialize_value(value)
                        stored_data[name]['type_hint'] = type(value).__name__
                        stored.append(name)
                    except ValueError as e:
                        result['output'] += f"Cannot store '{name}': {e}\n"

                if stored:
                    save_store()
                    result['output'] += f"Stored: {', '.join(stored)}\n"

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False

        return result

    def _handle_console_variables(self, payload: dict) -> None:
        """Return list of variables in the console namespace for Variable Explorer."""
        base = self.get_topic_base()

        try:
            namespace = self._get_console_namespace()
            variables = []

            for name, value in namespace.items():
                if name in self._CONSOLE_BUILTINS:
                    continue  # Skip built-ins

                var_info = {
                    'name': name,
                    'type': type(value).__name__,
                    'value': None,
                    'size': None,
                    'shape': None,
                    'dtype': None,
                }

                # Handle different types
                try:
                    # NumPy arrays
                    if hasattr(value, 'shape') and hasattr(value, 'dtype'):
                        var_info['shape'] = list(value.shape)
                        var_info['dtype'] = str(value.dtype)
                        var_info['size'] = value.nbytes if hasattr(value, 'nbytes') else None
                        # Show small arrays, summarize large ones
                        if value.size <= 10:
                            var_info['value'] = value.tolist()
                        else:
                            var_info['value'] = f'array({value.shape}, dtype={value.dtype})'
                    # Lists/tuples
                    elif isinstance(value, (list, tuple)):
                        var_info['size'] = len(value)
                        if len(value) <= 10:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = f'{type(value).__name__}[{len(value)} items]'
                    # Dicts
                    elif isinstance(value, dict):
                        var_info['size'] = len(value)
                        if len(value) <= 5:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = f'dict({len(value)} keys)'
                    # Strings
                    elif isinstance(value, str):
                        var_info['size'] = len(value)
                        if len(value) <= 50:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = repr(value[:47] + '...')
                    # Numbers and other simple types
                    else:
                        var_info['value'] = repr(value)
                        if len(str(var_info['value'])) > 100:
                            var_info['value'] = str(var_info['value'])[:97] + '...'
                except Exception:
                    var_info['value'] = '<error reading value>'

                variables.append(var_info)

            # Sort by name
            variables.sort(key=lambda v: v['name'])

            self.mqtt_client.publish(
                f"{base}/console/variables/result",
                json.dumps({'success': True, 'variables': variables})
            )

        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/console/variables/result",
                json.dumps({'success': False, 'error': str(e), 'variables': []})
            )

    def _handle_console_complete(self, payload: dict) -> None:
        """Provide tab completion suggestions for console input."""
        base = self.get_topic_base()
        text = payload.get('text', '')
        cursor_pos = payload.get('cursor_pos', len(text))

        try:
            completions = []

            # Get the word being completed
            # Find start of current word (go back until whitespace or operator)
            word_start = cursor_pos
            while word_start > 0 and text[word_start - 1] not in ' \t\n.([{=+-*/%<>!&|^~,':
                word_start -= 1
            partial = text[word_start:cursor_pos]

            # Check if we're completing an attribute (after a dot)
            if word_start > 0 and text[word_start - 1] == '.':
                # Find the object name before the dot
                obj_end = word_start - 1
                obj_start = obj_end
                while obj_start > 0 and text[obj_start - 1] not in ' \t\n([{=+-*/%<>!&|^~,':
                    obj_start -= 1
                obj_name = text[obj_start:obj_end]

                # Get the object from namespace
                namespace = self._get_console_namespace()
                if obj_name in namespace:
                    obj = namespace[obj_name]
                    # Get attributes that match partial
                    for attr in dir(obj):
                        if not attr.startswith('_') and attr.lower().startswith(partial.lower()):
                            completions.append({
                                'text': attr,
                                'type': 'attribute',
                                'start': word_start,
                                'end': cursor_pos
                            })
            else:
                # Complete from namespace
                namespace = self._get_console_namespace()
                for name in namespace.keys():
                    if name.lower().startswith(partial.lower()) and not name.startswith('_'):
                        comp_type = 'variable'
                        if callable(namespace[name]):
                            comp_type = 'function'
                        elif name in ('tags', 'outputs', 'session'):
                            comp_type = 'api'
                        completions.append({
                            'text': name,
                            'type': comp_type,
                            'start': word_start,
                            'end': cursor_pos
                        })

                # Add Python keywords
                keywords = ['if', 'else', 'elif', 'for', 'while', 'try', 'except',
                           'finally', 'with', 'def', 'class', 'return', 'yield',
                           'import', 'from', 'as', 'lambda', 'and', 'or', 'not',
                           'in', 'is', 'True', 'False', 'None', 'pass', 'break',
                           'continue', 'raise', 'assert', 'del', 'global', 'nonlocal']
                for kw in keywords:
                    if kw.lower().startswith(partial.lower()):
                        completions.append({
                            'text': kw,
                            'type': 'keyword',
                            'start': word_start,
                            'end': cursor_pos
                        })

            # Sort and limit completions
            completions.sort(key=lambda c: c['text'].lower())
            completions = completions[:50]  # Limit to 50 suggestions

            self.mqtt_client.publish(
                f"{base}/console/complete/result",
                json.dumps({'success': True, 'completions': completions})
            )

        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/console/complete/result",
                json.dumps({'success': False, 'error': str(e), 'completions': []})
            )

    def _handle_console_reset(self, payload: dict) -> None:
        """Reset the console namespace."""
        base = self.get_topic_base()
        self._console_namespace = None
        self.mqtt_client.publish(
            f"{base}/console/result",
            json.dumps({
                'success': True,
                'output': 'Namespace reset. All user variables cleared.\n',
                'result': '',
                'error': ''
            })
        )

    def _build_console_namespace(self) -> dict:
        """Build the initial namespace for console commands."""
        import math
        from datetime import datetime

        # Simple tags accessor
        class TagsAPI:
            def __init__(self, service):
                self._service = service

            def __getattr__(self, name: str):
                return self._service.get_channel_value(name)

            def __getitem__(self, name: str):
                return self._service.get_channel_value(name)

            def keys(self):
                return list(self._service.channel_configs.keys())

            def values(self):
                return [self._service.get_channel_value(k) for k in self.keys()]

            def items(self):
                return [(k, self._service.get_channel_value(k)) for k in self.keys()]

            def get(self, name: str, default=0.0):
                try:
                    return self._service.get_channel_value(name)
                except (KeyError, ValueError):
                    return default

            def __repr__(self):
                return f'<TagsAPI: {len(self.keys())} channels>'

        # Simple outputs accessor
        class OutputsAPI:
            def __init__(self, service):
                self._service = service

            def set(self, channel: str, value):
                self._service.set_output(channel, value)

            def __setitem__(self, name: str, value):
                self.set(name, value)

            def __repr__(self):
                return '<OutputsAPI: outputs.set(channel, value)>'

        # Simple session accessor
        class SessionAPI:
            def __init__(self, service):
                self._service = service

            @property
            def active(self):
                return self._service.session_active

            @property
            def recording(self):
                return self._service.is_recording

            @property
            def acquiring(self):
                return self._service.is_acquiring

            @property
            def elapsed(self):
                return self._service.session_elapsed

            def __repr__(self):
                return f'<SessionAPI: active={self.active}, recording={self.recording}>'

        namespace = {
            # SECURITY: Restrict __builtins__ to prevent access to __import__,
            # open(), exec(), eval(), compile() etc. via the default builtins module.
            # Only explicitly listed functions are available in the console.
            '__builtins__': {},

            # API
            'tags': TagsAPI(self),
            'outputs': OutputsAPI(self),
            'session': SessionAPI(self),

            # Standard library (pre-imported — no __import__ available)
            'time': __import__('time'),
            'math': math,
            'datetime': datetime,
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            # Math functions (commonly used)
            'abs': abs, 'min': min, 'max': max, 'sum': sum,
            'round': round, 'pow': pow,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10,
            'pi': math.pi, 'e': math.e,

            # Built-ins (safe subset only — no getattr/setattr/type to prevent sandbox escape)
            'print': print,
            'len': len, 'range': range, 'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
            'str': str, 'int': int, 'float': float, 'bool': bool,
            'True': True, 'False': False, 'None': None,
            'sorted': sorted, 'enumerate': enumerate, 'zip': zip,
            'map': map, 'filter': filter, 'any': any, 'all': all,
            'isinstance': isinstance,
        }

        # Try to add numpy and scipy if available
        try:
            import numpy as np
            namespace['np'] = np
            namespace['numpy'] = np
        except ImportError:
            pass

        try:
            import scipy
            namespace['scipy'] = scipy
        except ImportError:
            pass

        # Import script helper classes and utilities for unified environment
        # These are also available in scripts, making the namespace consistent
        from .script_manager import (
            RateCalculator, Accumulator, EdgeDetector, RollingStats, Scheduler,
            F_to_C, C_to_F, GPM_to_LPM, LPM_to_GPM, PSI_to_bar, bar_to_PSI,
            gal_to_L, L_to_gal, BTU_to_kJ, kJ_to_BTU, lb_to_kg, kg_to_lb,
            now, now_ms, now_iso, time_of_day, elapsed_since, format_timestamp
        )

        # Add script helper classes
        namespace.update({
            'RateCalculator': RateCalculator,
            'Accumulator': Accumulator,
            'EdgeDetector': EdgeDetector,
            'RollingStats': RollingStats,
            'Scheduler': Scheduler,
        })

        # Add unit conversion functions
        namespace.update({
            'F_to_C': F_to_C,
            'C_to_F': C_to_F,
            'GPM_to_LPM': GPM_to_LPM,
            'LPM_to_GPM': LPM_to_GPM,
            'PSI_to_bar': PSI_to_bar,
            'bar_to_PSI': bar_to_PSI,
            'gal_to_L': gal_to_L,
            'L_to_gal': L_to_gal,
            'BTU_to_kJ': BTU_to_kJ,
            'kJ_to_BTU': kJ_to_BTU,
            'lb_to_kg': lb_to_kg,
            'kg_to_lb': kg_to_lb,
        })

        # Add time utility functions
        namespace.update({
            'now': now,
            'now_ms': now_ms,
            'now_iso': now_iso,
            'time_of_day': time_of_day,
            'elapsed_since': elapsed_since,
            'format_timestamp': format_timestamp,
        })

        return namespace

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
            # Clear any persisted configs from previous projects — alarms are per-project
            self.alarm_manager.clear_all(clear_configs=True)
            logger.info("Alarm manager initialized (no project - cleared stale alarm configs)")
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

    def _init_notification_manager(self):
        """Initialize the notification manager for Twilio SMS + Email alarm notifications."""
        data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
        self.notification_manager = NotificationManager(
            data_dir=data_dir,
            publish_callback=self._notification_publish,
        )
        logger.info("Notification manager initialized")

    def _notification_publish(self, event_type: str, data: dict):
        """Callback from notification manager to publish status/error events."""
        if not self.mqtt_client:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/notifications/{event_type}",
            json.dumps(data),
            qos=1
        )

    def _init_safety_manager(self):
        """Initialize the backend safety manager for interlock evaluation and latch control.

        The safety manager runs all interlock logic on the backend, making the
        frontend display-only for safety-critical functions. This ensures safety
        logic continues even if the browser tab closes.
        """
        data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))

        # Stale threshold for remote node values (cRIO/Opto22): if no update
        # received within this window, the value is considered stale and safety
        # evaluation treats it as unavailable (fails safe).
        STALE_REMOTE_VALUE_SECONDS = 30.0

        def get_channel_value(channel: str) -> Optional[float]:
            """Get current value of a channel, returning None for stale remote values.
            Excludes legacy Modbus channels — Modbus is not a safety-rated protocol.
            CFP channels (source_type='cfp') are included since they represent typed I/O."""
            with self.values_lock:
                val = self.channel_values.get(channel)
                if val is not None:
                    ch_config = self.config.channels.get(channel) if self.config else None
                    # Legacy Modbus channels excluded from safety (not safety-rated protocol)
                    # CFP channels with real signal types ARE included
                    if ch_config and ch_config.is_modbus and getattr(ch_config, 'source_type', '') != 'cfp':
                        return None
                    # Check staleness for remote node channels
                    if ch_config and ch_config.is_remote_node:
                        ts = self.channel_timestamps.get(channel, 0)
                        age = time.time() - ts if ts > 0 else 0
                        if ts > 0 and age > STALE_REMOTE_VALUE_SECONDS:
                            # Rate-limit the warning to once per 30s per channel
                            last_warn = self._stale_warn_times.get(channel, 0)
                            if (time.time() - last_warn) > 30:
                                self._stale_warn_times[channel] = time.time()
                                logger.warning(f"[SAFETY] Stale remote value for {channel} "
                                               f"(age={age:.0f}s > {STALE_REMOTE_VALUE_SECONDS}s) "
                                               f"— interlock will fail safe")
                            return None
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return None
            return None

        def get_channel_type(channel: str) -> Optional[str]:
            """Get channel type"""
            if self.config and channel in self.config.channels:
                return self.config.channels[channel].channel_type.value
            return None

        def get_all_channels() -> Dict[str, Any]:
            """Get all channel configs as dicts"""
            if not self.config:
                return {}
            return {
                name: {'channel_type': ch.channel_type.value}
                for name, ch in self.config.channels.items()
            }

        def set_output(channel: str, value: Any):
            """Set output value via MQTT command"""
            self._handle_output_set({
                'channel': channel,
                'value': value,
                'source': 'safety_manager'
            })

        def stop_session():
            """Stop the test session"""
            self._stop_session()

        def get_system_state() -> Dict[str, Any]:
            """Get current system state"""
            return {
                'status': 'online' if self.running else 'offline',
                'acquiring': self.acquiring,
                'recording': self.recording
            }

        def get_alarm_state() -> Dict[str, Any]:
            """Get current alarm state including per-alarm details for safety evaluation"""
            if self.alarm_manager:
                counts = self.alarm_manager.get_alarm_counts()
                # Include per-alarm data for alarm_active/alarm_state condition types
                active_alarms = {}
                for alarm in self.alarm_manager.get_active_alarms():
                    active_alarms[alarm.alarm_id] = {
                        'state': alarm.state.value,
                        'channel': alarm.channel,
                        'severity': alarm.severity.name.lower()
                    }
                    # Also index by channel name for frontend compatibility
                    active_alarms[alarm.channel] = active_alarms[alarm.alarm_id]
                return {
                    'active_count': counts.get('active', 0),
                    'active_alarms': active_alarms
                }
            return {'active_count': 0, 'active_alarms': {}}

        def trigger_safe_state(reason: str):
            """Send atomic safe-state to all cRIO nodes"""
            self._forward_safe_state_to_crio(reason)

        self.safety_manager = SafetyManager(
            data_dir=data_dir,
            get_channel_value=get_channel_value,
            get_channel_type=get_channel_type,
            get_all_channels=get_all_channels,
            publish_callback=self._safety_manager_publish,
            set_output_callback=set_output,
            stop_session_callback=stop_session,
            get_system_state=get_system_state,
            get_alarm_state=get_alarm_state,
            trigger_safe_state_callback=trigger_safe_state
        )

        self.safety_manager.node_id = getattr(self.config.system, 'node_id', 'node-001')
        logger.info("Safety manager initialized")

    def _safety_manager_publish(self, topic: str, data: Any, **kwargs):
        """Callback from safety manager to publish MQTT messages"""
        if not self.mqtt_client:
            return

        base = self.get_topic_base()
        retain = kwargs.get('retain', False)
        try:
            if isinstance(data, dict):
                payload = json.dumps(data)
            else:
                payload = str(data)
            full_topic = f"{base}/{topic}"
            self.mqtt_client.publish(full_topic, payload, qos=1, retain=retain)
            # Write trip events to historian for DMZ relay
            if self.historian and topic in ('safety/trip', 'safety/action'):
                try:
                    self.historian.write_event(
                        int(time.time() * 1000), topic.replace('/', '_'),
                        full_topic, payload)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error publishing safety event: {e}")

    def _update_channel_alarm_config(self, channel_name: str, channel: 'ChannelConfig'):
        """Update or create alarm config for a channel after runtime config change.

        Called when channel alarm settings are modified via the Configuration tab.
        Updates the AlarmManager's config for this channel.
        """
        if not self.alarm_manager:
            return

        alarm_id = f"alarm-{channel_name}"

        # Check for ISA-18.2 alarm configuration
        has_isa_limits = any([
            getattr(channel, 'hihi_limit', None),
            getattr(channel, 'hi_limit', None),
            getattr(channel, 'lo_limit', None),
            getattr(channel, 'lolo_limit', None)
        ])

        # Legacy limits
        has_legacy_limits = any([
            getattr(channel, 'high_limit', None),
            getattr(channel, 'low_limit', None),
            getattr(channel, 'high_warning', None),
            getattr(channel, 'low_warning', None)
        ])

        # Determine if alarms should be enabled
        alarm_enabled = getattr(channel, 'alarm_enabled', False) if has_isa_limits else has_legacy_limits

        # Remove existing alarm config if alarms disabled or no limits
        if not alarm_enabled or (not has_isa_limits and not has_legacy_limits):
            existing = self.alarm_manager.get_alarm_config(alarm_id)
            if existing:
                self.alarm_manager.remove_alarm_config(alarm_id)
                logger.info(f"Removed alarm config for {channel_name} (disabled or no limits)")
            return

        # Determine severity
        priority_map = {
            'diagnostic': AlarmSeverity.LOW,
            'low': AlarmSeverity.LOW,
            'medium': AlarmSeverity.MEDIUM,
            'high': AlarmSeverity.HIGH,
            'critical': AlarmSeverity.CRITICAL
        }
        severity = priority_map.get(getattr(channel, 'alarm_priority', 'medium'), AlarmSeverity.MEDIUM)
        if getattr(channel, 'safety_action', None) and severity.value > AlarmSeverity.HIGH.value:
            severity = AlarmSeverity.HIGH

        # Use ISA-18.2 limits if available, otherwise fall back to legacy
        high_high = getattr(channel, 'hihi_limit', None) or getattr(channel, 'high_limit', None)
        high = getattr(channel, 'hi_limit', None) or getattr(channel, 'high_warning', None)
        low = getattr(channel, 'lo_limit', None) or getattr(channel, 'low_warning', None)
        low_low = getattr(channel, 'lolo_limit', None) or getattr(channel, 'low_limit', None)

        # Create or update alarm config
        config = AlarmConfig(
            id=alarm_id,
            channel=channel_name,
            name=channel_name,
            description=getattr(channel, 'description', '') or '',
            enabled=True,
            severity=severity,
            high_high=high_high,
            high=high,
            low=low,
            low_low=low_low,
            deadband=getattr(channel, 'alarm_deadband', 0),
            on_delay_s=getattr(channel, 'alarm_delay_sec', 0),
            off_delay_s=0,
            latch_behavior=LatchBehavior.AUTO_CLEAR,
            group=getattr(channel, 'group', '') or '',
            actions=[channel.safety_action] if getattr(channel, 'safety_action', None) else []
        )

        # Add or update config (add_alarm_config handles both cases)
        self.alarm_manager.add_alarm_config(config)
        logger.info(f"Updated alarm config for {channel_name}")

    def _init_audit_trail(self):
        """Initialize the audit trail for 21 CFR Part 11 / ALCOA+ compliance"""
        try:
            data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
            audit_dir = data_dir / "audit"
            def _audit_witness(payload):
                """Publish audit witness digest to MQTT for external verification"""
                if self.mqtt_client and self.mqtt_client.is_connected():
                    topic = f"{self.get_topic_base()}/audit/witness"
                    self.mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=False)

            self.audit_trail = AuditTrail(
                audit_dir=audit_dir,
                node_id=getattr(self.config.system, 'node_id', 'node-001'),
                retention_days=365,
                max_file_size_mb=50.0,
                witness_callback=_audit_witness
            )
            # Verify integrity of existing audit trail on startup
            is_valid, errors, entries_checked = self.audit_trail.verify_integrity()
            if is_valid:
                logger.info(f"Audit trail initialized at {audit_dir} "
                           f"(integrity verified: {entries_checked} entries)")
            else:
                logger.warning(f"Audit trail integrity check FAILED at {audit_dir}: "
                              f"{len(errors)} error(s) in {entries_checked} entries")
                for err in errors[:5]:  # Log first 5 errors
                    logger.warning(f"  Audit integrity: {err}")

                if self.mqtt_client and self.mqtt_client.is_connected():
                    self.mqtt_client.publish(
                        f"{self.get_topic_base()}/audit/integrity_failure",
                        json.dumps({'errors': errors[:10], 'entries_checked': entries_checked}),
                        qos=1
                    )
        except Exception as e:
            logger.error(f"Failed to initialize audit trail: {e}")
            self.audit_trail = None

        # Wire audit trail to safety manager for 21 CFR Part 11 interlock tracking
        if self.safety_manager and self.audit_trail:
            self.safety_manager._audit_trail = self.audit_trail

    def _init_user_session_manager(self):
        """Initialize the user session manager for role-based access control"""
        try:
            data_dir = Path(getattr(self.config.system, 'data_directory', 'data'))
            self.user_session_manager = UserSessionManager(
                data_dir=data_dir,
                session_timeout_minutes=30,  # Security Compliance AC.L2-3.1.10: lock after 30 min inactivity
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

    def _init_pid_engine(self):
        """Initialize PID control engine"""
        try:
            self.pid_engine = PIDEngine(
                on_set_output=self._set_output_value
            )
            # Set callback for publishing status via MQTT
            self.pid_engine.set_status_callback(self._publish_pid_status)
            logger.info("PID engine initialized")
        except Exception as e:
            logger.error(f"Failed to initialize PID engine: {e}")
            self.pid_engine = None

    def _publish_pid_status(self, loop_id: str, status: Dict[str, Any]):
        """Publish PID loop status via MQTT"""
        if not self.mqtt_client:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/pid/loop/{loop_id}/status",
            json.dumps(status),
            retain=True
        )

    def _init_azure_uploader(self):
        """Check Azure IoT Hub configuration (external service handles streaming)"""
        # Azure uploader now runs as a separate service (azure_uploader_service.py)
        # It subscribes to channel topics and receives start/stop commands via MQTT
        # This method just logs the current config status

        azure_config = self._get_azure_config()
        if azure_config:
            logger.info(f"Azure IoT Hub configured: {len(azure_config.get('channels', []))} channels")
            logger.info("Azure streaming will start when recording starts")
        else:
            logger.info("Azure IoT Hub not configured (can be configured in Data tab)")

    def _publish_azure_status(self, status: Dict[str, Any]):
        """Publish Azure IoT uploader status via MQTT"""
        if not self.mqtt_client:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/azure/status",
            json.dumps(status),
            retain=True
        )

    def _get_azure_config(self) -> Optional[Dict[str, Any]]:
        """Get Azure IoT config from project or system config"""
        azure_config = getattr(self.config.system, 'azure_iot', None)
        if not azure_config:
            return None
        conn_str = azure_config.get('connection_string', '')
        if not conn_str or not conn_str.startswith('HostName='):
            return None
        return {
            'connection_string': conn_str,
            'channels': azure_config.get('channels', []),
            'batch_size': azure_config.get('batch_size', 10),
            'batch_interval_ms': azure_config.get('batch_interval_ms', 1000),
            'node_id': self.config.system.node_id,
        }

    def _publish_azure_command(self, action: str, config: Optional[Dict] = None):
        """Publish command to Azure uploader service"""
        if not self.mqtt_client:
            return
        cmd = {'action': action}
        if config:
            cmd['config'] = config
        # Publish to fixed topic (not node-specific, Azure uploader is system-wide)
        self.mqtt_client.publish(
            'nisystem/azure/command',
            json.dumps(cmd)
        )
        logger.info(f"Published Azure command: {action}")

    def _alarm_manager_publish(self, event_type: str, data: dict):
        """Callback from alarm manager to publish events"""
        if not self.mqtt_client:
            return

        base = self.get_topic_base()

        if event_type == 'alarm':
            # Publish alarm state
            topic = f"{base}/alarms/active/{data.get('alarm_id', 'unknown')}"
            payload_json = json.dumps(data)
            self.mqtt_client.publish(topic, payload_json, retain=True, qos=1)
            # Write to historian for DMZ relay
            if self.historian:
                try:
                    self.historian.write_event(
                        int(time.time() * 1000), 'alarm', topic, payload_json)
                except Exception:
                    pass
            # Forward to notification manager with group enrichment
            if self.notification_manager:
                enriched = dict(data)
                alarm_cfg = self.alarm_manager.get_alarm_config(data.get('alarm_id', '')) if self.alarm_manager else None
                if alarm_cfg:
                    enriched['group'] = alarm_cfg.group
                self.notification_manager.on_alarm_event('triggered', enriched)
        elif event_type == 'alarm_cleared':
            # Publish cleared state
            topic = f"{base}/alarms/active/{data.get('alarm_id', 'unknown')}"
            cleared_payload = json.dumps({'active': False, 'alarm_id': data.get('alarm_id')})
            self.mqtt_client.publish(topic, cleared_payload, retain=True, qos=1)
            # Write to historian for DMZ relay
            if self.historian:
                try:
                    self.historian.write_event(
                        int(time.time() * 1000), 'alarm_cleared', topic, cleared_payload)
                except Exception:
                    pass
            # Forward to notification manager
            if self.notification_manager:
                enriched = dict(data)
                alarm_cfg = self.alarm_manager.get_alarm_config(data.get('alarm_id', '')) if self.alarm_manager else None
                if alarm_cfg:
                    enriched['group'] = alarm_cfg.group
                    enriched['severity'] = alarm_cfg.severity.name
                    enriched['name'] = alarm_cfg.name
                    enriched['channel'] = alarm_cfg.channel
                self.notification_manager.on_alarm_event('cleared', enriched)
        elif event_type == 'alarm_flood':
            # Forward alarm flood to notification manager
            if self.notification_manager:
                self.notification_manager.on_alarm_event('alarm_flood', data)
        elif event_type == 'action':
            # Legacy action handler (config-defined safety actions)
            action_id = data.get('action_id')
            trigger_source = data.get('alarm_id', 'unknown')
            if action_id and action_id in self.config.safety_actions:
                self._execute_safety_action(action_id, trigger_source)
        elif event_type == 'safety_action':
            # ISA-18.2 safety action from AlarmManager
            # Publish to MQTT so frontend can execute (frontend-defined actions)
            topic = f"{base}/safety/action"
            payload_json = json.dumps(data)
            self.mqtt_client.publish(topic, payload_json, qos=1)
            logger.warning(f"SAFETY ACTION published: {data.get('action_id')} by alarm {data.get('alarm_id')}")
            # Write to historian for DMZ relay
            if self.historian:
                try:
                    self.historian.write_event(
                        int(time.time() * 1000), 'safety_action', topic, payload_json)
                except Exception:
                    pass
            # Also try backend execution for actions defined in config
            action_id = data.get('action_id')
            trigger_source = data.get('alarm_id', 'unknown')
            if action_id and action_id in self.config.safety_actions:
                self._execute_safety_action(action_id, trigger_source)

    def _on_test_session_start(self):
        """Custom callback when test session starts"""
        logger.info("[SESSION] Test session started - executing callbacks")
        self._publish_test_session_status()
        # Notify automation engines
        if self.script_manager:
            session_scripts = [s for s in self.script_manager.scripts.values()
                             if s.enabled and s.run_mode == ScriptRunMode.SESSION]
            logger.info(f"[SESSION] Script manager has {len(session_scripts)} enabled session scripts to start")
            self.script_manager.on_session_start()
            self._publish_script_status()  # Update UI with started scripts
        else:
            logger.warning("[SESSION] No script manager available!")
        if self.trigger_engine:
            self.trigger_engine.on_session_start()
        if self.watchdog_engine:
            self.watchdog_engine.on_session_start()
        logger.info("[SESSION] Test session start callbacks complete")

    def _on_test_session_stop(self):
        """Custom callback when test session stops"""
        logger.info("[SESSION] Test session stopped - executing callbacks")
        self._publish_test_session_status()
        # Notify automation engines
        if self.script_manager:
            running_session_scripts = [s for s in self.script_manager.scripts.values()
                                       if s.run_mode == ScriptRunMode.SESSION and
                                       self.script_manager.is_script_running(s.id)]
            logger.info(f"[SESSION] Stopping {len(running_session_scripts)} running session scripts")
            self.script_manager.on_session_stop()
            self._publish_script_status()  # Update UI with stopped scripts
            # Clear controlled outputs tracking - outputs are now unlocked for manual control
            self.script_manager.clear_controlled_outputs()
        else:
            logger.warning("[SESSION] No script manager available!")
        if self.trigger_engine:
            self.trigger_engine.on_session_stop()
        if self.watchdog_engine:
            self.watchdog_engine.on_session_stop()
        logger.info("[SESSION] Test session stop callbacks complete")

    def _user_var_scheduler_enable(self, enable: bool):
        """Callback for user variable manager to enable/disable scheduler"""
        if self.scheduler:
            self.scheduler.enabled = enable
            logger.info(f"Scheduler {'enabled' if enable else 'disabled'} by test session")
            self._publish_schedule_status()

    def _user_var_recording_start(self):
        """Callback for user variable manager to start recording"""
        if self.recording_manager and not self.recording:
            self._handle_recording_start({})

    def _user_var_recording_stop(self):
        """Callback for user variable manager to stop recording"""
        if self.recording_manager and self.recording:
            self._handle_recording_stop()

    def _user_var_run_sequence(self, sequence_id: str):
        """Callback for user variable manager to run a sequence"""
        if self.sequence_manager:
            self.sequence_manager.start_sequence(sequence_id, self.channel_values)

    def _user_var_stop_sequence(self):
        """Callback for user variable manager to stop running sequence"""
        if self.sequence_manager:
            running = self.sequence_manager.get_running_sequence()
            if running:
                self.sequence_manager.abort_sequence(running.id)

    def _sequence_set_output(self, channel: str, value: Any):
        """Callback for sequence to set output"""
        self._set_output_value(channel, value)

    def _set_output_value(self, channel: str, value: Any, bypass_interlock: bool = False):
        """Generic callback for setting output values (used by scripts, triggers, watchdogs, sequences, safe-state).

        Serializes all output writes via output_write_lock so concurrent writers
        (scripts + MQTT commands + watchdog + safe-state) cannot interleave and
        produce wrong actuation order.

        ALSO checks safety interlocks before writing — previously only the MQTT
        command path checked these, so triggers/watchdogs/scripts could bypass
        safety locks. The bypass_interlock flag is for safe-state itself, which
        must always be able to drive outputs to their safe value.
        """
        if channel not in self.config.channels:
            return

        ch = self.config.channels[channel]
        if ch.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                                   ChannelType.COUNTER_OUTPUT, ChannelType.PULSE_OUTPUT,
                                   ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL):
            return

        # Validate value type for analog outputs — non-numeric values would
        # crash hardware_reader.write_channel() with float() error.
        if ch.channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                               ChannelType.MODBUS_REGISTER):
            if not isinstance(value, (int, float, bool)):
                logger.warning(f"[OUTPUT] Cannot write non-numeric value {value!r} to analog output {channel}")
                return

        # SAFETY: Check interlocks (skipped for safe-state which IS the response
        # to interlock trips). Without this, triggers/watchdogs/scripts could
        # write to an output that an active interlock has locked — defeating
        # the safety system.
        if not bypass_interlock and getattr(self, 'safety_manager', None) is not None:
            try:
                block_result = self.safety_manager.is_output_blocked(channel)
                if isinstance(block_result, dict) and block_result.get('blocked', False):
                    reason = block_result.get('reason', 'safety interlock')
                    logger.warning(f"[OUTPUT] Blocked write to {channel}: {reason}")
                    return
            except Exception as e:
                # Don't block the write if interlock check itself fails
                logger.debug(f"[OUTPUT] Interlock check failed for {channel}: {e}")

        # Serialize the entire write so two threads can't interleave reads/writes
        # of channel_values OR send out-of-order commands to the same hardware.
        with self.output_write_lock:
            self._set_output_value_locked(channel, value, ch)

    def _set_output_value_locked(self, channel: str, value: Any, ch):
        """Inner output write — must be called with output_write_lock held."""
        # Use centralized hardware source detection from ChannelConfig
        is_crio_channel = ch.is_crio
        is_modbus = ch.is_modbus
        physical_channel = ch.physical_channel

        # Runtime fallback: if channel is loaded in local hardware reader, it's not cRIO
        if is_crio_channel and self.hardware_reader and channel in self.hardware_reader.output_tasks:
            is_crio_channel = False
            logger.debug(f"[OUTPUT] {channel} detected as local (in hardware_reader.output_tasks)")

        # Route to appropriate backend
        if is_crio_channel:
            # Route to cRIO via MQTT
            mqtt_base = self.config.system.mqtt_base_topic
            crio_topic = f"{mqtt_base}/nodes/crio-001/commands/output"
            # Include physical_channel for fallback when config not pushed to cRIO
            crio_payload = {'channel': channel, 'value': value, 'physical_channel': physical_channel}
            self.mqtt_client.publish(crio_topic, json.dumps(crio_payload), qos=1)
            logger.debug(f"[OUTPUT] Routed {channel} ({physical_channel}) to cRIO via MQTT")
            # DON'T update channel_values here - wait for cRIO to report back
        elif is_modbus and self.modbus_reader:
            self.modbus_reader.write_channel(channel, value)
            with self.values_lock:
                self.channel_values[channel] = value
            self._publish_channel_value(channel, value)
        elif self.simulator:
            self.simulator.write_channel(channel, value)
            with self.values_lock:
                self.channel_values[channel] = value
            self._publish_channel_value(channel, value)
        elif self.hardware_reader:
            result = self.hardware_reader.write_channel(channel, value)
            if result:
                with self.values_lock:
                    self.channel_values[channel] = value
                self._publish_channel_value(channel, value)

    def _sequence_start_recording(self, filename: Optional[str] = None):
        """Callback for sequence to start recording"""
        if self.recording_manager and not self.recording_manager.recording:
            self.recording_manager.start(filename)

    def _sequence_stop_recording(self):
        """Callback for sequence to stop recording"""
        if self.recording_manager and self.recording_manager.recording:
            self.recording_manager.stop()

    def _sequence_start_acquisition(self):
        """Callback for sequence to start acquisition"""
        if not self._state_machine.to(DAQState.RUNNING):
            return  # Already running or invalid transition
        logger.info("Sequence started acquisition")
        if self.script_manager:
            self.script_manager.on_acquisition_start()
            self._publish_script_status()  # Update UI with started scripts
        if self.trigger_engine:
            self.trigger_engine.on_acquisition_start()
        if self.watchdog_engine:
            self.watchdog_engine.on_acquisition_start()

    def _sequence_stop_acquisition(self):
        """Callback for sequence to stop acquisition"""
        if not self._state_machine.to(DAQState.STOPPED):
            return  # Already stopped or invalid transition
        logger.info("Sequence stopped acquisition")
        if self.script_manager:
            self.script_manager.on_acquisition_stop()
            self._publish_script_status()  # Update UI with stopped scripts
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
        if not self._state_machine.to(DAQState.RUNNING):
            return  # Already running or invalid transition
        logger.info("Scheduler started acquisition")
        if self.script_manager:
            self.script_manager.on_acquisition_start()
            self._publish_script_status()  # Update UI with started scripts
        if self.trigger_engine:
            self.trigger_engine.on_acquisition_start()
        if self.watchdog_engine:
            self.watchdog_engine.on_acquisition_start()

    def _scheduled_stop_acquire(self):
        """Callback for scheduler to stop acquisition"""
        if not self._state_machine.to(DAQState.STOPPED):
            return  # Already stopped or invalid transition
        logger.info("Scheduler stopped acquisition")
        if self.script_manager:
            self.script_manager.on_acquisition_stop()
            self._publish_script_status()  # Update UI with stopped scripts
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
        """Setup MQTT connection via TCP (native MQTT protocol).

        The DAQ service uses TCP transport (port 1883) for maximum throughput.
        The browser dashboard uses WebSocket (port 9002) because browsers require it.
        The MQTT broker routes messages between transports transparently.
        """
        mqtt_port = self.config.system.mqtt_port  # 1883 from system.ini
        logger.info(f"Connecting to MQTT broker at {self.config.system.mqtt_broker}:{mqtt_port} (TCP)")

        # Use unique client ID and paho-mqtt v2 API with TCP transport
        import uuid
        client_id = f"daq_service_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

        # Register per-topic callbacks for critical commands.
        # These run INDEPENDENTLY of _on_mqtt_message - they cannot be
        # blocked or crashed by other message processing. Industrial safety
        # requirement: start/stop/session must always be responsive.
        base = self.get_topic_base()
        self.mqtt_client.message_callback_add(
            f"{base}/system/acquire/start", self._on_critical_acquire_start)
        self.mqtt_client.message_callback_add(
            f"{base}/system/acquire/stop", self._on_critical_acquire_stop)
        self.mqtt_client.message_callback_add(
            f"{base}/system/recording/start", self._on_critical_recording_start)
        self.mqtt_client.message_callback_add(
            f"{base}/system/recording/stop", self._on_critical_recording_stop)
        self.mqtt_client.message_callback_add(
            f"{base}/test-session/start", self._on_critical_session_start)
        self.mqtt_client.message_callback_add(
            f"{base}/test-session/stop", self._on_critical_session_stop)
        self.mqtt_client.message_callback_add(
            f"{base}/system/status/request", self._on_critical_status_request)
        self.mqtt_client.message_callback_add(
            f"{base}/system/safe-state", self._on_critical_safe_state)

        # Per-project critical commands (station management)
        mqtt_base = self.config.system.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.system.node_id if self.config else 'node-001'
        station_base = f"{mqtt_base}/nodes/{node_id}"
        self.mqtt_client.message_callback_add(
            f"{station_base}/projects/+/acquire/start", self._on_project_acquire_start)
        self.mqtt_client.message_callback_add(
            f"{station_base}/projects/+/acquire/stop", self._on_project_acquire_stop)
        self.mqtt_client.message_callback_add(
            f"{station_base}/projects/+/recording/start", self._on_project_recording_start)
        self.mqtt_client.message_callback_add(
            f"{station_base}/projects/+/recording/stop", self._on_project_recording_stop)

        # MQTT Authentication — check env vars, config, then auto-generated credential file
        mqtt_user = os.environ.get('MQTT_USERNAME', getattr(self.config.system, 'mqtt_username', None))
        mqtt_pass = os.environ.get('MQTT_PASSWORD', getattr(self.config.system, 'mqtt_password', None))
        if not mqtt_user or not mqtt_pass:
            # Fallback: read from auto-generated credential file (zero-config)
            cred_file = os.path.join('config', 'mqtt_credentials.json')
            if os.path.exists(cred_file):
                try:
                    import json as _json
                    with open(cred_file) as _f:
                        _creds = _json.load(_f)
                    mqtt_user = _creds.get('backend', {}).get('username')
                    mqtt_pass = _creds.get('backend', {}).get('password')
                except Exception as e:
                    logger.warning(f"Could not read MQTT credentials from {cred_file}: {e}")
        if mqtt_user and mqtt_pass:
            self.mqtt_client.username_pw_set(mqtt_user.strip(), mqtt_pass.strip())
            logger.info(f"MQTT authentication enabled for user: {mqtt_user.strip()}")

        # Optional TLS for broker connection (e.g., when connecting to remote broker)
        tls_ca = os.environ.get('MQTT_TLS_CA')
        if tls_ca and os.path.exists(tls_ca):
            import ssl
            self.mqtt_client.tls_set(ca_certs=tls_ca)
            logger.info(f"MQTT TLS enabled with CA: {tls_ca}")

        # Last Will & Testament — broker publishes this if DAQ service
        # disconnects unexpectedly (crash, network loss, keepalive timeout)
        self.mqtt_client.will_set(
            f"{base}/status/system",
            json.dumps({"status": "offline", "reason": "unexpected_disconnect"}),
            qos=1,
            retain=True
        )

        try:
            self.mqtt_client.connect(
                self.config.system.mqtt_broker,
                mqtt_port,
                keepalive=60
            )
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        if reason_code == 0:
            if self._mqtt_connected is False:
                logger.info("Reconnected to MQTT broker (was disconnected)")
            else:
                logger.info("Connected to MQTT broker")
            self._mqtt_connected = True
            self._mqtt_auth_failures = 0

            # Initialize acquisition event pipeline (after MQTT connected)
            if self._acq_events is None:
                self._acq_events = AcquisitionEventPipeline(self.mqtt_client, self.get_topic_base())
            else:
                self._acq_events.update_topic_base(self.get_topic_base())

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
            client.subscribe(f"{base}/system/safe-state")

            # Subscribe to authentication topics (exact match for this node)
            auth_topics = [
                f"{base}/auth/login",
                f"{base}/auth/logout",
                f"{base}/auth/unlock",
                f"{base}/auth/status/request"
            ]
            for topic in auth_topics:
                result = client.subscribe(topic)
                logger.info(f"[AUTH] Subscribed to {topic} (result: {result})")

            # Subscribe to config management topics
            client.subscribe(f"{base}/config/get")
            client.subscribe(f"{base}/config/save")
            client.subscribe(f"{base}/config/load")
            client.subscribe(f"{base}/config/list")
            client.subscribe(f"{base}/config/apply")  # Reinitialize tasks without starting acquisition
            client.subscribe(f"{base}/config/system/update")  # Update scan/publish rates at runtime
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
            client.subscribe(f"{base}/recording/read")
            client.subscribe(f"{base}/recording/read-range")
            client.subscribe(f"{base}/recording/file-info")
            client.subscribe(f"{base}/recording/db-test")

            # Subscribe to historian topics
            client.subscribe(f"{base}/historian/query")
            client.subscribe(f"{base}/historian/tags")
            client.subscribe(f"{base}/historian/export")
            client.subscribe(f"{base}/historian/stats")

            # Subscribe to log viewer topics
            client.subscribe(f"{base}/logs/query")

            # Subscribe to Azure IoT Hub topics
            client.subscribe(f"{base}/azure/config")
            client.subscribe(f"{base}/azure/config/get")
            client.subscribe(f"{base}/azure/start")
            client.subscribe(f"{base}/azure/stop")
            client.subscribe(f"{base}/azure/status/get")

            # Subscribe to dependency management topics
            client.subscribe(f"{base}/dependencies/check")
            client.subscribe(f"{base}/dependencies/delete")
            client.subscribe(f"{base}/dependencies/validate")
            client.subscribe(f"{base}/dependencies/orphans")

            # Subscribe to project management topics
            client.subscribe(f"{base}/project/list")
            client.subscribe(f"{base}/project/load")
            client.subscribe(f"{base}/project/load-last")  # Load last used project from settings
            client.subscribe(f"{base}/project/import")  # Import from any path
            client.subscribe(f"{base}/project/import/json")  # Import JSON directly
            client.subscribe(f"{base}/project/close")   # Close to empty state
            client.subscribe(f"{base}/project/save")
            client.subscribe(f"{base}/project/delete")
            client.subscribe(f"{base}/project/get")
            client.subscribe(f"{base}/project/get-current")

            # Multi-instance management
            client.subscribe(f"{base}/system/create-instance")

            # Station management (multi-project concurrent support)
            client.subscribe(f"{base}/station/load")       # Load project into station
            client.subscribe(f"{base}/station/unload")     # Unload project from station
            client.subscribe(f"{base}/station/list")       # List loaded projects
            client.subscribe(f"{base}/station/status")     # Get station status
            client.subscribe(f"{base}/station/config/save")    # Save current station as config
            client.subscribe(f"{base}/station/config/load")    # Load a station config
            client.subscribe(f"{base}/station/config/list")    # List saved station configs
            client.subscribe(f"{base}/station/config/delete")  # Delete a station config
            client.subscribe(f"{base}/system/mode")      # Switch system mode
            # Per-project commands via wildcard
            client.subscribe(f"{base}/projects/+/acquire/start")
            client.subscribe(f"{base}/projects/+/acquire/stop")
            client.subscribe(f"{base}/projects/+/recording/start")
            client.subscribe(f"{base}/projects/+/recording/stop")
            client.subscribe(f"{base}/projects/+/commands/#")

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
            # NOTE: Do NOT subscribe to test-session/status - it's our outbound topic
            # Subscribing + handling creates an infinite publish loop

            # Subscribe to backend script execution topics
            client.subscribe(f"{base}/script/start")
            client.subscribe(f"{base}/script/stop")
            client.subscribe(f"{base}/script/add")
            client.subscribe(f"{base}/script/update")
            client.subscribe(f"{base}/script/remove")
            client.subscribe(f"{base}/script/clear-all")  # Clear all scripts (project load)
            client.subscribe(f"{base}/script/list")
            client.subscribe(f"{base}/script/get")
            client.subscribe(f"{base}/script/status")

            # Subscribe to interactive console topics (IPython-like REPL)
            client.subscribe(f"{base}/console/execute")
            client.subscribe(f"{base}/console/variables")  # List namespace variables
            client.subscribe(f"{base}/console/complete")   # Tab completion
            client.subscribe(f"{base}/console/reset")      # Reset namespace

            # Subscribe to notebook topics
            client.subscribe(f"{base}/notebook/save")
            client.subscribe(f"{base}/notebook/load")

            # Subscribe to chassis/device management topics (Modbus)
            client.subscribe(f"{base}/chassis/add")
            client.subscribe(f"{base}/chassis/update")
            client.subscribe(f"{base}/chassis/delete")
            client.subscribe(f"{base}/chassis/test")
            client.subscribe(f"{base}/modbus/write_register")
            client.subscribe(f"{base}/modbus/write")  # Generic write with verification

            # Subscribe to cRIO node status messages (wildcard for all nodes)
            # This allows us to discover and track remote cRIO nodes
            mqtt_base = self.config.system.mqtt_base_topic
            client.subscribe(f"{mqtt_base}/nodes/+/status/system")
            client.subscribe(f"{mqtt_base}/nodes/+/status/offline")
            # Also subscribe to heartbeats for fallback discovery
            client.subscribe(f"{mqtt_base}/nodes/+/heartbeat")
            # Subscribe to cRIO channel values (for remote channel data)
            client.subscribe(f"{mqtt_base}/nodes/+/channels/#")
            # Subscribe to cRIO config response (ACK for config pushes)
            client.subscribe(f"{mqtt_base}/nodes/+/config/response")
            # Subscribe to cRIO session status (for CRIO mode - cRIO is source of truth)
            client.subscribe(f"{mqtt_base}/nodes/+/session/status")
            # Subscribe to cRIO script status (for CRIO mode - scripts run on cRIO)
            client.subscribe(f"{mqtt_base}/nodes/+/script/status")
            # Subscribe to cRIO alarm events (for CRIO mode - alarms evaluated on cRIO)
            client.subscribe(f"{mqtt_base}/nodes/+/alarm/event")
            # Subscribe to cRIO alarm status (for CRIO mode - alarm counts/active alarms)
            client.subscribe(f"{mqtt_base}/nodes/+/alarm/status")
            # Subscribe to cRIO command acknowledgments (for CRIO mode - explicit ACKs)
            client.subscribe(f"{mqtt_base}/nodes/+/command/ack")
            # Subscribe to cRIO state transitions (QoS 1, retained — reliable state tracking)
            client.subscribe(f"{mqtt_base}/nodes/+/state")

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

            # Subscribe to notification management topics
            client.subscribe(f"{base}/notifications/config/update")
            client.subscribe(f"{base}/notifications/config/get")
            client.subscribe(f"{base}/notifications/test")

            # Subscribe to safety/interlock management topics
            client.subscribe(f"{base}/safety/latch/arm")
            client.subscribe(f"{base}/safety/latch/disarm")
            client.subscribe(f"{base}/safety/trip/reset")
            client.subscribe(f"{base}/safety/status/request")
            client.subscribe(f"{base}/safety/config/update")
            client.subscribe(f"{base}/interlocks/add")
            client.subscribe(f"{base}/interlocks/update")
            client.subscribe(f"{base}/interlocks/remove")
            client.subscribe(f"{base}/interlocks/bypass")
            client.subscribe(f"{base}/interlocks/sync")
            client.subscribe(f"{base}/interlocks/list")
            client.subscribe(f"{base}/interlocks/acknowledge_trip")
            client.subscribe(f"{base}/alarms/config/sync")
            # Channel cascade: when a channel/uv./py. ref is deleted in
            # ConfigurationTab, prune the matching alarm + interlock configs
            # so we don't leave orphaned safety state pointing at nothing.
            client.subscribe(f"{base}/safety/alarm/delete")
            client.subscribe(f"{base}/safety/interlock/delete")

            # Subscribe to PID control topics
            client.subscribe(f"{base}/pid/loops")
            client.subscribe(f"{base}/pid/loop/+/config")
            client.subscribe(f"{base}/pid/loop/+/setpoint")
            client.subscribe(f"{base}/pid/loop/+/mode")
            client.subscribe(f"{base}/pid/loop/+/output")
            client.subscribe(f"{base}/pid/loop/+/tuning")
            client.subscribe(f"{base}/pid/add")
            client.subscribe(f"{base}/pid/remove")

            # Clear stale retained command messages that could trigger unintended actions
            for cmd_topic in ['system/acquire/start', 'system/acquire/stop',
                              'system/recording/start', 'system/recording/stop',
                              'test-session/start', 'test-session/stop',
                              'system/safe-state']:
                client.publish(f"{base}/{cmd_topic}", b'', retain=True)
            logger.info("Cleared stale retained command messages")

            # Publish connection status
            self._publish_system_status()

            # Publish channel configuration
            self._publish_channel_config()

            # Publish user variable configuration
            self._publish_user_variables_config()
            self._publish_test_session_status()
            # Publish formula blocks
            self._publish_formula_blocks_config()

            # Send initial discovery ping to find any connected cRIO nodes
            # This ensures we discover cRIOs that connected before DAQ started
            self._send_crio_discovery_ping()
            logger.info("Sent initial cRIO discovery ping on MQTT connect")

        else:
            rc_str = str(reason_code)
            # Detect auth failures specifically (MQTT 3.1.1 code 5, MQTT 5 code 134/135)
            is_auth_fail = 'not authorized' in rc_str.lower() or 'bad user' in rc_str.lower()
            if is_auth_fail:
                self._mqtt_auth_failures += 1
                if self._mqtt_auth_failures == 1:
                    logger.error(f"MQTT AUTH FAILED: Broker rejected credentials (rc={rc_str})")
                    logger.error("MQTT AUTH FAILED: Check that config/mqtt_credentials.json and config/mosquitto_passwd are in sync")
                    logger.error("MQTT AUTH FAILED: Fix: delete config/mqtt_credentials.json and restart to regenerate")
                elif self._mqtt_auth_failures == 3:
                    logger.critical(f"MQTT AUTH FAILED {self._mqtt_auth_failures} times — credentials are invalid. "
                                    f"All MQTT communication is down. Dashboard, recording commands, and remote nodes cannot connect. "
                                    f"Delete config/mqtt_credentials.json and restart.")
                elif self._mqtt_auth_failures % 10 == 0:
                    logger.critical(f"MQTT AUTH STILL FAILING after {self._mqtt_auth_failures} attempts — service is running without MQTT")
            else:
                logger.error(f"MQTT connection failed with code {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT disconnection callback"""
        self._mqtt_connected = False
        if reason_code == 0:
            logger.info("Disconnected from MQTT broker (clean)")
        else:
            logger.warning(f"Disconnected from MQTT broker unexpectedly (rc={reason_code})")

    # =========================================================================
    # CRITICAL COMMAND CALLBACKS (per-topic, isolated from main handler)
    #
    # These are registered via message_callback_add() and run INSTEAD OF
    # _on_mqtt_message for their specific topics. They cannot be blocked
    # or crashed by failures in the main message handler.
    # =========================================================================

    # Maximum accepted MQTT payload size (256 KB)
    MAX_PAYLOAD_SIZE = 262144

    def _parse_critical_payload(self, msg):
        """Parse payload for critical command callbacks.
        Returns (payload, request_id) or (None, None) if the message should
        be ignored (e.g. empty retained message clear).
        """
        if not msg.payload:
            return None, None  # Empty payload (b'') = retained message clear, ignore
        if len(msg.payload) > self.MAX_PAYLOAD_SIZE:
            logger.warning(f"[MQTT] Oversized critical payload on {msg.topic}: {len(msg.payload)} bytes, dropping")
            return None, None
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        # Note: {} is a valid payload (dashboard sends it for start/stop).
        # Only skip truly empty bytes (handled above).
        request_id = payload.get('request_id') if isinstance(payload, dict) else None
        return payload, request_id

    def _on_critical_acquire_start(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return  # Empty/stale retained message
            logger.info(f"[CRITICAL] acquire/start received (request_id={request_id})")
            self._handle_acquire_start(request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] acquire/start handler failed: {e}", exc_info=True)

    def _on_critical_acquire_stop(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            force = payload.get('force', False) if isinstance(payload, dict) else False
            logger.info(f"[CRITICAL] acquire/stop received (request_id={request_id}, force={force})")
            self._handle_acquire_stop(request_id, force=force)
        except Exception as e:
            logger.error(f"[CRITICAL] acquire/stop handler failed: {e}", exc_info=True)

    def _on_critical_recording_start(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            logger.info(f"[CRITICAL] recording/start received (request_id={request_id})")
            self._handle_recording_start(payload, request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] recording/start handler failed: {e}", exc_info=True)

    def _on_critical_recording_stop(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            logger.info(f"[CRITICAL] recording/stop received (request_id={request_id})")
            self._handle_recording_stop(request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] recording/stop handler failed: {e}", exc_info=True)

    def _on_critical_session_start(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            logger.info(f"[CRITICAL] test-session/start received (request_id={request_id})")
            self._handle_test_session_start(payload, request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] test-session/start handler failed: {e}", exc_info=True)

    def _on_critical_session_stop(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            logger.info(f"[CRITICAL] test-session/stop received (request_id={request_id})")
            self._handle_test_session_stop(request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] test-session/stop handler failed: {e}", exc_info=True)

    def _on_critical_status_request(self, client, userdata, msg):
        try:
            logger.info(f"[CRITICAL] status/request received")
            self._publish_system_status()
        except Exception as e:
            logger.error(f"[CRITICAL] status/request handler failed: {e}", exc_info=True)

    def _on_critical_safe_state(self, client, userdata, msg):
        try:
            payload, request_id = self._parse_critical_payload(msg)
            if payload is None:
                return
            logger.info(f"[CRITICAL] safe-state received (request_id={request_id})")
            self._handle_safe_state(payload, request_id)
        except Exception as e:
            logger.error(f"[CRITICAL] safe-state handler failed: {e}", exc_info=True)

    # =========================================================================
    # MAIN MESSAGE HANDLER (fallback for non-critical topics)
    # =========================================================================

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT callback - MUST be non-blocking. Just enqueue for processing.

        This runs in paho's network thread. Any blocking here delays ALL MQTT
        processing including critical per-topic callbacks. We just copy the
        topic and payload into the command queue and return immediately.

        Critical commands (acquire, recording, session, safe-state) are handled
        by per-topic callbacks registered via message_callback_add() and never
        reach this handler.
        """
        if msg.payload and len(msg.payload) > self.MAX_PAYLOAD_SIZE:
            logger.warning(f"[MQTT] Oversized payload on {msg.topic}: {len(msg.payload)} bytes, dropping")
            return

        # Rate limit check for command topics (per-prefix, then global fallback)
        matched = False
        for prefix, limiter in self._rate_limiters.items():
            if f'/{prefix}/' in msg.topic or msg.topic.endswith(f'/{prefix}'):
                matched = True
                if not limiter.allow():
                    now = time.time()
                    last_warn = self._rate_limit_warn_times.get(prefix, 0)
                    if now - last_warn > 5.0:
                        logger.warning(f"[RATE LIMIT] {prefix} commands rate-limited (>{limiter.rate}/s)")
                        self._rate_limit_warn_times[prefix] = now
                    return
                break
        if not matched and not self._global_rate_limiter.allow():
            now = time.time()
            last_warn = self._rate_limit_warn_times.get('_global', 0)
            if now - last_warn > 5.0:
                logger.warning(f"[RATE LIMIT] Global command rate limit reached (>{self._global_rate_limiter.rate}/s)")
                self._rate_limit_warn_times['_global'] = now
            return

        try:
            self._command_queue.put_nowait((msg.topic, msg.payload))
        except queue.Full:
            logger.error(f"[MQTT] Command queue full, dropping message on {msg.topic}")

    def _command_processing_loop(self):
        """Dedicated thread for processing MQTT commands.

        Drains the command queue and routes messages to handlers.
        Isolated from paho's network thread - a slow handler here cannot
        block critical command callbacks or MQTT keepalives.
        """
        while self.running:
            try:
                topic, raw_payload = self._command_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Parse payload
            try:
                payload = json.loads(raw_payload.decode()) if raw_payload else {}
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode failed for {topic}: {e}")
                try:
                    payload = raw_payload.decode()
                except UnicodeDecodeError:
                    continue
            except UnicodeDecodeError:
                continue
            except Exception:
                continue

            # Route to handler with error isolation
            try:
                base = self.get_topic_base()
                request_id = payload.get('request_id') if isinstance(payload, dict) else None
                self._route_message(topic, base, payload, request_id)
            except Exception as e:
                logger.error(f"[CMD] Handler error for {topic}: {e}", exc_info=True)

    # Centralized permission map: topic suffix -> required Permission
    # Topics not in this map are either:
    #   - Read-only (status/list/get) which are allowed for all authenticated users
    #   - Already have inline permission checks (acquire start/stop, recording start/stop, safe-state)
    #   - Auth endpoints (login/logout) which are pre-auth
    _TOPIC_PERMISSIONS = {
        # Safety & Interlocks (Supervisor+)
        'safety/latch/arm': Permission.MODIFY_SAFETY,
        'safety/latch/disarm': Permission.MODIFY_SAFETY,
        'safety/trip/reset': Permission.MODIFY_SAFETY,
        'safety/config/update': Permission.MODIFY_SAFETY,
        'interlocks/add': Permission.MODIFY_SAFETY,
        'interlocks/update': Permission.MODIFY_SAFETY,
        'interlocks/remove': Permission.MODIFY_SAFETY,
        'interlocks/bypass': Permission.BYPASS_SAFETY_LOCK,
        'interlocks/sync': Permission.MODIFY_SAFETY,
        'interlocks/acknowledge_trip': Permission.ACK_ALARMS,
        'alarms/config/sync': Permission.MODIFY_SAFETY,
        'safety/alarm/delete': Permission.MODIFY_SAFETY,
        'safety/interlock/delete': Permission.MODIFY_SAFETY,
        # Alarm operations (Operator+)
        'alarm/acknowledge': Permission.ACK_ALARMS,
        'alarm/clear': Permission.RESET_ALARMS,
        'alarm/reset-latched': Permission.RESET_ALARMS,
        'alarm/reset': Permission.RESET_ALARMS,
        'alarm/shelve': Permission.SHELVE_ALARMS,
        'alarm/unshelve': Permission.SHELVE_ALARMS,
        # Script management (Supervisor+)
        'scripts/add': Permission.MODIFY_CHANNELS,
        'scripts/update': Permission.MODIFY_CHANNELS,
        'scripts/reload': Permission.MODIFY_CHANNELS,
        'scripts/remove': Permission.MODIFY_CHANNELS,
        'scripts/clear-all': Permission.MODIFY_CHANNELS,
        'scripts/start': Permission.CONTROL_OUTPUTS,
        'scripts/stop': Permission.CONTROL_OUTPUTS,
        # Console (Supervisor+)
        'console/execute': Permission.MODIFY_CHANNELS,
        'console/reset': Permission.MODIFY_CHANNELS,
        # Config management (Supervisor+)
        'config/save': Permission.SAVE_PROJECT,
        'config/load': Permission.LOAD_PROJECT,
        'config/apply': Permission.MODIFY_CHANNELS,
        'config/system/update': Permission.MODIFY_SYSTEM,
        'config/channel/update': Permission.MODIFY_CHANNELS,
        'config/channel/create': Permission.MODIFY_CHANNELS,
        'config/channel/delete': Permission.MODIFY_CHANNELS,
        'config/channel/bulk-create': Permission.MODIFY_CHANNELS,
        # Discovery (Operator+)
        'discovery/scan': Permission.MODIFY_CHANNELS,
        # Output control (Operator+)
        'output/set': Permission.CONTROL_OUTPUTS,
        'channel/reset': Permission.CONTROL_OUTPUTS,
        # Recording config (Operator+)
        'recording/config': Permission.MODIFY_RECORDING,
        'recording/delete': Permission.MODIFY_RECORDING,
        # Notification config (Supervisor+)
        'notifications/config': Permission.MODIFY_SYSTEM,
        'notifications/test': Permission.MODIFY_SYSTEM,
        # Azure config (Supervisor+)
        'azure/config': Permission.MODIFY_SYSTEM,
        'azure/start': Permission.MODIFY_SYSTEM,
        'azure/stop': Permission.MODIFY_SYSTEM,
        # Project management
        'project/import': Permission.LOAD_PROJECT,
        'project/import-json': Permission.LOAD_PROJECT,
        'project/close': Permission.LOAD_PROJECT,
        'project/delete': Permission.SAVE_PROJECT,
        'project/autosave': Permission.SAVE_PROJECT,
        'project/autosave/discard': Permission.SAVE_PROJECT,
        # PID control (Operator+ for setpoints, Supervisor+ for config)
        'pid/add': Permission.MODIFY_CHANNELS,
        'pid/remove': Permission.MODIFY_CHANNELS,
        # Sequence control (Operator+)
        'sequence/start': Permission.CONTROL_OUTPUTS,
        'sequence/pause': Permission.CONTROL_OUTPUTS,
        'sequence/resume': Permission.CONTROL_OUTPUTS,
        'sequence/abort': Permission.CONTROL_OUTPUTS,
        'sequence/add': Permission.MODIFY_CHANNELS,
        'sequence/remove': Permission.MODIFY_CHANNELS,
        # Schedule (Operator+)
        'schedule/set': Permission.CONTROL_OUTPUTS,
        'schedule/enable': Permission.CONTROL_OUTPUTS,
        'schedule/disable': Permission.CONTROL_OUTPUTS,
        # Variables (Operator+)
        'variables/create': Permission.CONTROL_OUTPUTS,
        'variables/update': Permission.CONTROL_OUTPUTS,
        'variables/delete': Permission.CONTROL_OUTPUTS,
        'variables/set': Permission.CONTROL_OUTPUTS,
        'variables/reset': Permission.CONTROL_OUTPUTS,
        'variables/reset-all': Permission.CONTROL_OUTPUTS,
        'timer/start': Permission.CONTROL_OUTPUTS,
        'timer/stop': Permission.CONTROL_OUTPUTS,
        # Formulas (Supervisor+)
        'formulas/create': Permission.MODIFY_CHANNELS,
        'formulas/update': Permission.MODIFY_CHANNELS,
        'formulas/delete': Permission.MODIFY_CHANNELS,
        # User management (Admin)
        'users/create': Permission.MANAGE_USERS,
        'users/update': Permission.MANAGE_USERS,
        'users/delete': Permission.MANAGE_USERS,
        # Chassis/datasource management (Supervisor+)
        'chassis/add': Permission.MODIFY_CHANNELS,
        'chassis/update': Permission.MODIFY_CHANNELS,
        'chassis/delete': Permission.MODIFY_CHANNELS,
        'datasource/add': Permission.MODIFY_CHANNELS,
        'datasource/update': Permission.MODIFY_CHANNELS,
        'datasource/delete': Permission.MODIFY_CHANNELS,
        # Modbus write (Operator+)
        'modbus/write_register': Permission.CONTROL_OUTPUTS,
        'modbus/write': Permission.CONTROL_OUTPUTS,
        # Notebook (Operator+)
        'notebook/save': Permission.SAVE_PROJECT,
        # cRIO config push (Supervisor+)
        'crio/push-config': Permission.MODIFY_CHANNELS,
    }

    def _route_message(self, topic: str, base: str, payload, request_id):
        """Route MQTT message to appropriate handler.

        Critical commands are primarily handled by per-topic callbacks
        (message_callback_add). However, as a safety fallback, this method
        also handles them in case the per-topic callback didn't intercept.

        Centralized permission enforcement: checks _TOPIC_PERMISSIONS map
        before routing to handler. This provides defense-in-depth even if
        individual handlers forget to check permissions.
        """

        if self.security_monitor:
            session_id = self.current_session_id or 'anonymous'
            self.security_monitor.record_command(session_id, topic)

        # === CENTRALIZED PERMISSION CHECK ===
        # Strip base prefix to get the topic suffix for permission lookup
        topic_suffix = topic[len(base) + 1:] if topic.startswith(base + '/') else topic.rsplit('/', 1)[-1] if '/' in topic else topic
        # Check for exact match first, then handle PID loop topics (dynamic path)
        required_perm = self._TOPIC_PERMISSIONS.get(topic_suffix)
        if required_perm is None and topic_suffix.startswith('pid/loop/'):
            # PID loop sub-commands: pid/loop/{id}/setpoint, /mode, /output, /tuning, /config
            pid_action = topic_suffix.rsplit('/', 1)[-1] if '/' in topic_suffix else ''
            if pid_action in ('setpoint', 'mode', 'output'):
                required_perm = Permission.CONTROL_OUTPUTS
            elif pid_action in ('config', 'tuning'):
                required_perm = Permission.MODIFY_CHANNELS
        if required_perm is not None:
            if not self._has_permission(required_perm):
                logger.warning(f"[SECURITY] Permission denied for {topic_suffix} (requires {required_perm.value})")
                if self.security_monitor:
                    self.security_monitor.record_permission_denied()
                return

        # === CRITICAL COMMAND FALLBACK ===
        # These are normally intercepted by message_callback_add() and never
        # reach the queue. But if they do (e.g., paho routing edge case),
        # handle them here rather than silently dropping them.
        if topic == f"{base}/system/acquire/start":
            if not payload:
                return  # Empty retained clear
            logger.info(f"[CMD-FALLBACK] acquire/start via queue (request_id={request_id})")
            self._handle_acquire_start(request_id)
            return
        elif topic == f"{base}/system/acquire/stop":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] acquire/stop via queue (request_id={request_id})")
            self._handle_acquire_stop(request_id)
            return
        elif topic == f"{base}/system/recording/start":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] recording/start via queue")
            rid = payload.get('request_id') if isinstance(payload, dict) else None
            self._handle_recording_start(payload, rid)
            return
        elif topic == f"{base}/system/recording/stop":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] recording/stop via queue")
            rid = payload.get('request_id') if isinstance(payload, dict) else None
            self._handle_recording_stop(rid)
            return
        elif topic == f"{base}/test-session/start":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] test-session/start via queue")
            rid = payload.get('request_id') if isinstance(payload, dict) else None
            self._handle_test_session_start(payload, rid)
            return
        elif topic == f"{base}/test-session/stop":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] test-session/stop via queue")
            rid = payload.get('request_id') if isinstance(payload, dict) else None
            self._handle_test_session_stop(rid)
            return
        elif topic == f"{base}/system/status/request":
            logger.info(f"[CMD-FALLBACK] status/request via queue")
            self._publish_system_status()
            return
        elif topic == f"{base}/system/safe-state":
            if not payload:
                return
            logger.info(f"[CMD-FALLBACK] safe-state via queue")
            fallback_request_id = payload.get('request_id') if isinstance(payload, dict) else None
            self._handle_safe_state(payload, fallback_request_id)
            return

        # === STATION MANAGEMENT (Multi-Project) ===
        if topic == f"{base}/station/load":
            self._handle_station_load(payload)
            return
        elif topic == f"{base}/station/unload":
            self._handle_station_unload(payload)
            return
        elif topic == f"{base}/station/list" or topic == f"{base}/station/status":
            self._handle_station_list(payload)
            return
        elif topic == f"{base}/station/config/save":
            self._handle_station_config_save(payload)
            return
        elif topic == f"{base}/station/config/load":
            self._handle_station_config_load(payload)
            return
        elif topic == f"{base}/station/config/list":
            self._handle_station_config_list(payload)
            return
        elif topic == f"{base}/station/config/delete":
            self._handle_station_config_delete(payload)
            return
        elif topic == f"{base}/system/mode":
            self._handle_mode_switch(payload)
            return
        # Per-project commands routed via wildcard (projects/+/commands/...)
        elif '/projects/' in topic and '/commands/' in topic:
            self._route_project_command(topic, payload, request_id)
            return

        # === AUTHENTICATION (accepts from any node via wildcard subscription) ===
        if topic.endswith('/auth/login'):
            logger.info(f"[AUTH] Received auth/login message on {topic}")
            self._handle_auth_login(payload)
        elif topic.endswith('/auth/logout'):
            logger.info(f"[AUTH] Received auth/logout message on {topic}")
            self._handle_auth_logout(payload)
        elif topic.endswith('/auth/unlock'):
            logger.info(f"[AUTH] Received auth/unlock message on {topic}")
            self._handle_auth_unlock(payload)
        elif topic.endswith('/auth/status/request'):
            logger.info(f"[AUTH] Received auth/status/request message on {topic}")
            self._publish_auth_status()

        # === USER MANAGEMENT (Admin only, accepts from any node) ===
        elif topic.endswith('/users/list'):
            self._handle_users_list(payload)
        elif topic.endswith('/users/create'):
            self._handle_users_create(payload)
        elif topic.endswith('/users/update'):
            self._handle_users_update(payload)
        elif topic.endswith('/users/delete'):
            self._handle_users_delete(payload)
        elif topic.endswith('/users/sessions'):
            self._handle_users_sessions(payload)

        # === AUDIT TRAIL (accepts from any node) ===
        elif topic.endswith('/audit/query'):
            self._handle_audit_query(payload)
        elif topic.endswith('/audit/export'):
            self._handle_audit_export(payload)

        # === ARCHIVE MANAGEMENT (accepts from any node) ===
        elif topic.endswith('/archive/list'):
            self._handle_archive_list(payload)
        elif topic.endswith('/archive/retrieve'):
            self._handle_archive_retrieve(payload)
        elif topic.endswith('/archive/verify'):
            self._handle_archive_verify(payload)

        elif topic.endswith('/settings/security'):
            self._handle_security_settings(payload)

        # === SAFETY / INTERLOCK MANAGEMENT ===
        elif topic == f"{base}/safety/latch/arm":
            self._handle_safety_latch_arm(payload)
        elif topic == f"{base}/safety/latch/disarm":
            self._handle_safety_latch_disarm(payload)
        elif topic == f"{base}/safety/trip/reset":
            self._handle_safety_trip_reset(payload)
        elif topic == f"{base}/safety/status/request":
            self._handle_safety_status_request()
        elif topic == f"{base}/safety/config/update":
            self._handle_safety_config_update(payload)
        elif topic == f"{base}/interlocks/add":
            self._handle_interlock_add(payload)
        elif topic == f"{base}/interlocks/update":
            self._handle_interlock_update(payload)
        elif topic == f"{base}/interlocks/remove":
            self._handle_interlock_remove(payload)
        elif topic == f"{base}/interlocks/bypass":
            self._handle_interlock_bypass(payload)
        elif topic == f"{base}/interlocks/sync":
            self._handle_interlock_sync(payload)
        elif topic == f"{base}/interlocks/list":
            self._handle_interlocks_list()
        elif topic == f"{base}/interlocks/acknowledge_trip":
            self._handle_interlock_acknowledge_trip(payload)
        elif topic == f"{base}/alarms/config/sync":
            self._handle_alarm_config_sync(payload)
        elif topic == f"{base}/safety/alarm/delete":
            self._handle_safety_alarm_delete(payload)
        elif topic == f"{base}/safety/interlock/delete":
            self._handle_safety_interlock_delete(payload)

        # === PID CONTROL ===
        elif topic == f"{base}/pid/loops":
            self._handle_pid_list_loops()
        elif topic == f"{base}/pid/add":
            self._handle_pid_add_loop(payload)
        elif topic == f"{base}/pid/remove":
            self._handle_pid_remove_loop(payload)
        elif topic.startswith(f"{base}/pid/loop/") and topic.endswith("/config"):
            loop_id = topic.split('/')[-2]
            self._handle_pid_loop_config(loop_id, payload)
        elif topic.startswith(f"{base}/pid/loop/") and topic.endswith("/setpoint"):
            loop_id = topic.split('/')[-2]
            self._handle_pid_loop_setpoint(loop_id, payload)
        elif topic.startswith(f"{base}/pid/loop/") and topic.endswith("/mode"):
            loop_id = topic.split('/')[-2]
            self._handle_pid_loop_mode(loop_id, payload)
        elif topic.startswith(f"{base}/pid/loop/") and topic.endswith("/output"):
            loop_id = topic.split('/')[-2]
            self._handle_pid_loop_output(loop_id, payload)
        elif topic.startswith(f"{base}/pid/loop/") and topic.endswith("/tuning"):
            loop_id = topic.split('/')[-2]
            self._handle_pid_loop_tuning(loop_id, payload)

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
        elif topic == f"{base}/config/system/update":
            self._handle_config_system_update(payload)
        elif topic == f"{base}/config/channel/update":
            self._handle_channel_update(payload)
        elif topic == f"{base}/config/channel/create":
            self._handle_channel_create(payload)
        elif topic == f"{base}/config/channel/delete":
            self._handle_channel_delete(payload)
        elif topic == f"{base}/config/channel/bulk-create":
            self._handle_channel_bulk_create(payload)

        # === CRIO NODE MANAGEMENT ===
        elif topic == f"{base}/crio/push-config":
            self._handle_crio_push_config_request(payload)
        elif topic == f"{base}/crio/list":
            self._handle_crio_list_request()

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
            self._handle_discovery_scan(payload)

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
        elif topic == f"{base}/recording/read":
            self._handle_recording_read(payload)
        elif topic == f"{base}/recording/read-range":
            self._handle_recording_read_range(payload)
        elif topic == f"{base}/recording/file-info":
            self._handle_recording_file_info(payload)
        elif topic == f"{base}/recording/db-test":
            self._handle_recording_db_test(payload)

        # === HISTORIAN ===
        elif topic == f"{base}/historian/query":
            self._handle_historian_query(payload)
        elif topic == f"{base}/historian/tags":
            self._handle_historian_tags()
        elif topic == f"{base}/historian/export":
            self._handle_historian_export(payload)
        elif topic == f"{base}/historian/stats":
            self._handle_historian_stats()

        # === LOG VIEWER ===
        elif topic == f"{base}/logs/query":
            self._handle_logs_query(payload)

        # === AZURE IOT HUB ===
        elif topic == f"{base}/azure/config":
            self._handle_azure_config(payload)
        elif topic == f"{base}/azure/config/get":
            self._handle_azure_config_get()
        elif topic == f"{base}/azure/start":
            self._handle_azure_start(payload)
        elif topic == f"{base}/azure/stop":
            self._handle_azure_stop()
        elif topic == f"{base}/azure/status/get":
            self._handle_azure_status_get()

        # === NOTIFICATION MANAGEMENT ===
        elif topic == f"{base}/notifications/config/update":
            self._handle_notifications_config_update(payload)
        elif topic == f"{base}/notifications/config/get":
            self._handle_notifications_config_get()
        elif topic == f"{base}/notifications/test":
            self._handle_notifications_test(payload)

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
        elif topic == f"{base}/project/load-last":
            self._handle_project_load_last()
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
        elif topic == f"{base}/project/autosave":
            self._handle_project_autosave(payload)
        elif topic == f"{base}/project/autosave/discard":
            self._handle_project_autosave_discard()
        elif topic == f"{base}/project/autosave/check":
            self._handle_project_autosave_check()

        # === MULTI-INSTANCE MANAGEMENT ===
        elif topic == f"{base}/system/create-instance":
            self._handle_create_instance(payload)

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
        # test-session/start and test-session/stop are handled by critical callbacks
        elif topic == f"{base}/test-session/config":
            self._handle_test_session_config(payload)
        # NOTE: Do NOT handle test-session/status here - it's our own outbound topic
        # Handling it causes an infinite publish loop (same pattern as script/status)

        # === BACKEND SCRIPT EXECUTION ===
        elif topic == f"{base}/script/start":
            self._handle_script_start(payload)
        elif topic == f"{base}/script/stop":
            self._handle_script_stop(payload)
        elif topic == f"{base}/script/add":
            self._handle_script_add(payload)
        elif topic == f"{base}/script/update":
            self._handle_script_update(payload)
        elif topic == f"{base}/script/reload":
            self._handle_script_reload(payload)
        elif topic == f"{base}/script/remove":
            self._handle_script_remove(payload)
        elif topic == f"{base}/script/clear-all":
            self._handle_script_clear_all(payload)
        elif topic == f"{base}/script/list":
            self._handle_script_list()
        elif topic == f"{base}/script/get":
            self._handle_script_get(payload)
        # NOTE: Do NOT handle script/status here - it's our own outbound topic
        # Handling it would cause an infinite publish loop

        # === INTERACTIVE CONSOLE (IPython-like) ===
        elif topic == f"{base}/console/execute":
            self._handle_console_execute(payload)
        elif topic == f"{base}/console/variables":
            self._handle_console_variables(payload)
        elif topic == f"{base}/console/complete":
            self._handle_console_complete(payload)
        elif topic == f"{base}/console/reset":
            self._handle_console_reset(payload)

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
        elif topic == f"{base}/modbus/write_register" or topic == f"{base}/modbus/write":
            self._handle_modbus_write_register(payload)

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

        # === CRIO NODE STATUS (from remote cRIO nodes) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/status/system
        # Note: mqtt_base is different from base - base is node-specific
        elif "/nodes/" in topic and "/status/" in topic and "node_type" in str(payload):
            self._handle_crio_node_status(topic, payload)

        # === CRIO NODE HEARTBEAT (fallback discovery) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/heartbeat
        elif "/nodes/" in topic and "/heartbeat" in topic and "node_type" in str(payload):
            self._handle_crio_heartbeat(topic, payload)

        # === CRIO NODE CHANNEL VALUES ===
        # Pattern: {mqtt_base}/nodes/{node_id}/channels/{channel_name}
        # Receives real-time values from cRIO nodes for remote channels
        elif "/nodes/" in topic and "/channels/" in topic:
            self._handle_crio_channel_value(topic, payload)

        # === CRIO CONFIG RESPONSE (ACK from cRIO nodes) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/config/response
        elif "/nodes/" in topic and "/config/response" in topic:
            self._handle_crio_config_response(topic, payload)

        # === CRIO SESSION STATUS (for CRIO mode - cRIO is source of truth) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/session/status
        elif "/nodes/" in topic and "/session/status" in topic:
            self._handle_crio_session_status(topic, payload)

        # === CRIO SCRIPT STATUS (for CRIO mode - scripts run on cRIO) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/script/status
        elif "/nodes/" in topic and "/script/status" in topic:
            self._handle_crio_script_status(topic, payload)

        # === CRIO ALARM EVENTS (for CRIO mode - alarms evaluated on cRIO) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/alarm/event
        elif "/nodes/" in topic and "/alarm/event" in topic:
            self._handle_crio_alarm_event(topic, payload)

        # === CRIO ALARM STATUS (for CRIO mode - alarm counts/active alarms) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/alarm/status
        elif "/nodes/" in topic and "/alarm/status" in topic:
            self._handle_crio_alarm_status(topic, payload)

        # === CRIO COMMAND ACKS (for CRIO mode - explicit command acknowledgments) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/command/ack
        elif "/nodes/" in topic and "/command/ack" in topic:
            self._handle_crio_command_ack(topic, payload)

        # === NODE STATE TRANSITIONS (QoS 1 retained — reliable state tracking) ===
        # Pattern: {mqtt_base}/nodes/{node_id}/state
        elif "/nodes/" in topic and topic.endswith("/state"):
            self._handle_node_state_change(topic, payload)

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
        if channel.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                                        ChannelType.COUNTER_OUTPUT, ChannelType.PULSE_OUTPUT):
            logger.warning(f"Cannot write to input channel: {channel_name}")
            return

        # Extract value from payload
        if isinstance(payload, dict):
            value = payload.get('value')
        else:
            value = payload

        # Check if this is a cRIO channel in CRIO project mode
        # In CRIO mode, cRIO handles interlocks/safety - PC just forwards commands
        is_crio_channel = channel.is_crio
        is_crio_mode = self.config.system.project_mode == ProjectMode.CRIO
        crio_owns_channel = is_crio_channel and is_crio_mode

        # Check safety interlocks (only in CDAQ mode or for non-cRIO channels)
        # In CRIO mode, cRIO evaluates interlocks locally
        if channel.safety_interlock and not crio_owns_channel:
            if not self._check_interlock(channel.safety_interlock):
                logger.warning(f"Safety interlock prevents write to {channel_name}")
                self._publish_alarm(channel_name, f"Interlock active: {channel.safety_interlock}")
                return

        # Check session lockout - only lock outputs actively controlled by session scripts
        # Other outputs remain manually controllable during sessions
        source = payload.get('source') if isinstance(payload, dict) else None
        force = payload.get('force', False) if isinstance(payload, dict) else False

        # Only block if:
        # 1. Session is active
        # 2. Channel is marked lock_during_session=True OR actively controlled by a script
        # 3. Command is NOT from script/automation (internal sources)
        # 4. Force flag is not set
        if self.user_variables and self.user_variables.session.active:
            # Check if channel is explicitly marked for session lockout (default: False)
            lock_during_session = getattr(channel, 'lock_during_session', False)

            # Check if script manager is actively controlling this channel
            script_controlled = (
                self.script_manager and
                channel_name in self.script_manager.get_controlled_outputs()
            )

            # Allow internal sources (scripts, triggers, watchdogs, sequences, safety_action)
            internal_sources = {'script', 'trigger', 'watchdog', 'sequence', 'safety_action', 'automation'}

            if (lock_during_session or script_controlled) and source not in internal_sources and not force:
                logger.warning(f"Session lockout prevents manual write to {channel_name} (controlled by session)")
                # Publish rejection notification
                base = self.get_topic_base()
                self.mqtt_client.publish(
                    f"{base}/output/rejected",
                    json.dumps({
                        'channel': channel_name,
                        'reason': 'session_controlled',
                        'message': f'Cannot change {channel_name} - controlled by active session script',
                        'value': value
                    })
                )
                return

        # Write the value
        logger.info(f"Writing to {channel_name}: {value}")

        # Determine which backend handles this channel
        channel = self.config.channels.get(channel_name)
        is_modbus = channel and (channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL)
                                 or getattr(channel, 'source_type', '') == 'cfp')

        # Use centralized hardware source detection from ChannelConfig
        # This uses the HardwareSource enum and channel properties for clear cRIO vs cDAQ distinction
        is_crio_channel = channel.is_crio
        physical_channel = channel.physical_channel

        # Runtime fallback: if channel is loaded in local hardware reader, it's not cRIO
        if is_crio_channel and self.hardware_reader and channel_name in self.hardware_reader.output_tasks:
            is_crio_channel = False
            logger.debug(f"[OUTPUT] {channel_name} overridden to local (found in hardware_reader.output_tasks)")

        # Debug: Log output routing decision with hardware source
        hw_source = channel.hardware_source.value
        logger.info(f"[OUTPUT] {channel_name}: source={hw_source}, is_crio={is_crio_channel}, is_modbus={is_modbus}, "
                   f"hw_reader={self.hardware_reader is not None}, simulator={self.simulator is not None}")

        if is_crio_channel:
            # Route to cRIO via MQTT - publish to cRIO's command topic
            # cRIO subscribes to: nisystem/nodes/{node_id}/commands/#
            # Send TAG name since cRIO output_tasks are keyed by TAG name after config push
            # Include physical_channel for fallback when config not pushed to cRIO
            mqtt_base = self.config.system.mqtt_base_topic
            # Use channel's source_node_id to route to the correct cRIO (not hardcoded!)
            crio_node_id = channel.source_node_id or 'crio-001'
            crio_topic = f"{mqtt_base}/nodes/{crio_node_id}/commands/output"
            crio_payload = {
                'channel': channel_name,  # TAG name
                'value': value,
                'physical_channel': physical_channel  # Fallback for when config not pushed
            }
            logger.info(f"[OUTPUT] Routing {channel_name} ({physical_channel}) to cRIO {crio_node_id} via MQTT: {crio_topic}")
            self.mqtt_client.publish(crio_topic, json.dumps(crio_payload), qos=1)
        elif is_modbus and self.modbus_reader:
            logger.info(f"[OUTPUT] Routing {channel_name} to Modbus")
            self.modbus_reader.write_channel(channel_name, value)
        elif self.hardware_reader and not self.config.system.simulation_mode:
            # Real hardware - prioritize over simulator when not in simulation mode
            logger.info(f"[OUTPUT] Routing {channel_name} to HardwareReader (real NI hardware)")
            result = self.hardware_reader.write_channel(channel_name, value)
            logger.info(f"[OUTPUT] HardwareReader.write_channel returned: {result}")
        elif self.simulator:
            # Simulation mode fallback
            logger.info(f"[OUTPUT] Routing {channel_name} to Simulator (fallback)")
            self.simulator.write_channel(channel_name, value)
        else:
            logger.error(f"[OUTPUT] No backend available for {channel_name}!")

        # Update cache and publish acknowledgment
        # In CRIO mode for cRIO channels, DON'T update local cache - wait for cRIO to report back
        # cRIO is the source of truth for its channels
        if is_crio_channel and self.config.system.project_mode == ProjectMode.CRIO:
            logger.debug(f"[OUTPUT] {channel_name} sent to cRIO - waiting for cRIO to report back")
            # Don't update local cache or publish - cRIO will publish value when it confirms
        else:
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
        _start_time = time.time()
        flow_id = request_id or str(uuid.uuid4())[:8]
        if self._acq_events:
            self._acq_events.start_flow(flow_id)
            self._acq_events.emit(AcquisitionEvent.START_REQUESTED, {'request_id': request_id})
        try:
            # PERMISSION CHECK
            if not self._has_permission(Permission.START_ACQUISITION):
                logger.warning("[SECURITY] Acquisition start denied - insufficient permissions")
                self._publish_command_ack("acquire/start", request_id, False, "Permission denied")
                if self._acq_events:
                    self._acq_events.emit(AcquisitionEvent.START_REJECTED, {'reason': 'permission_denied'}, severity='warning')
                return
            logger.info(f"[TIMING] Permission check: {(time.time()-_start_time)*1000:.1f}ms")

            # STATE TRANSITION: stopped → initializing (atomic via state machine)
            logger.info(f"[STATE] Acquisition start requested (current: {self._state_machine.state.name})")
            if not self._state_machine.to(DAQState.INITIALIZING):
                logger.warning(f"[STATE] Acquisition start rejected (state={self._state_machine.state.name})")
                self._publish_command_ack("acquire/start", request_id, False, "Already acquiring")
                if self._acq_events:
                    self._acq_events.emit(AcquisitionEvent.START_REJECTED, {'reason': 'already_acquiring', 'state': self._state_machine.state.name}, severity='warning')
                return
            if self._acq_events:
                self._acq_events.emit(AcquisitionEvent.START_STATE_TRANSITION, {'new_state': 'INITIALIZING'})
            # (Legacy _stop_command_time removed — state sync uses /state topic)
            logger.info(f"[TIMING] State update: {(time.time()-_start_time)*1000:.1f}ms")
            self._publish_system_status(skip_resource_monitoring=True)  # Fast UI feedback: show INITIALIZING

            # Only reload from system.ini if no project is loaded
            # If a project is loaded (from file OR imported from JSON), its config is already applied
            if self.current_project_path:
                logger.info(f"Using project config: {self.current_project_path.name} ({len(self.config.channels)} channels)")
            elif self.current_project_data:
                # Project was imported from JSON (no file path, but has project data)
                project_name = self.current_project_data.get("name", "Imported Project")
                logger.info(f"Using imported project config: {project_name} ({len(self.config.channels)} channels)")
            elif self.config.channels:
                # No project but channels exist (from bulk create or manual config)
                # Keep the existing channels - don't reload from system.ini
                logger.info(f"No project loaded - using existing {len(self.config.channels)} channels")
            else:
                # No project and no channels - reload from system.ini
                logger.info("No project or channels - reloading configuration from system.ini...")
                self._load_config()
            logger.info(f"[TIMING] Config check: {(time.time()-_start_time)*1000:.1f}ms")
            self._publish_channel_config()
            self._publish_channel_claims()
            logger.info(f"[TIMING] Channel config publish: {(time.time()-_start_time)*1000:.1f}ms")

            # Reset scan timing stats for fresh metrics
            self._scan_timing.target_ms = (1000.0 / self.config.system.scan_rate_hz)
            self._scan_timing.reset()

            # STATE TRANSITION: initializing → running
            self._state_machine.to(DAQState.RUNNING)
            logger.info(f"[STATE] Acquisition started successfully (state={self._state_machine.state.name})")

            # Industrial-grade: Capture initial output states from hardware
            # This ensures displayed values match actual hardware state from the start
            if self.hardware_reader and not self.config.system.simulation_mode:
                try:
                    initial_outputs = self.hardware_reader.refresh_output_states()
                    if initial_outputs:
                        with self.values_lock:
                            for ch_name, actual_val in initial_outputs.items():
                                self.channel_values[ch_name] = actual_val
                        logger.info(f"[STATE MACHINE] Captured initial output states: {list(initial_outputs.keys())}")
                except Exception as e:
                    logger.warning(f"[STATE MACHINE] Failed to capture initial output states: {e}")
            logger.info(f"[TIMING] Hardware init: {(time.time()-_start_time)*1000:.1f}ms")

            # Notify automation engines
            if self.script_manager:
                self.script_manager.on_acquisition_start()
                self._publish_script_status()  # Update UI with started scripts
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_start()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_start()
            logger.info(f"[TIMING] Engines notified: {(time.time()-_start_time)*1000:.1f}ms")

            # IEC 61511: Lock safety configuration during acquisition
            if self.project_manager:
                self.project_manager.lock_safety_config("Acquisition running")

            # Audit trail: Log acquisition start
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.ACQUISITION_STARTED,
                    user=self.auth_username or "system",
                    description="Data acquisition started",
                    details={"channels": len(self.config.channels) if self.config else 0}
                )
            logger.info(f"[TIMING] Audit logged: {(time.time()-_start_time)*1000:.1f}ms")

            # Auto-start recording if configured (unattended weekend operation)
            if (self.recording_manager
                    and self.recording_manager.config.auto_start_on_acquire
                    and not self.recording_manager.recording):
                logger.info("[AUTO-RECORD] Starting recording automatically on acquisition start")
                if self.recording_manager.start():
                    self.recording = True
                    self.recording_start_time = self.recording_manager.recording_start_time
                    self.recording_filename = self.recording_manager.current_file.name if self.recording_manager.current_file else None
                    logger.info(f"[AUTO-RECORD] Recording started: {self.recording_filename}")
                else:
                    logger.warning("[AUTO-RECORD] Failed to start automatic recording")
            logger.info(f"[TIMING] Auto-record check: {(time.time()-_start_time)*1000:.1f}ms")

            self._publish_system_status()  # Full status with resource monitoring

            # ACK — confirmed: acquisition is fully running
            elapsed_ms = int((time.time() - _start_time) * 1000)
            self._publish_command_ack("acquire/start", request_id, True)
            logger.info(f"[TIMING] START complete + ACK: {elapsed_ms}ms")
            if self._acq_events:
                self._acq_events.emit(AcquisitionEvent.ACQUIRE_RUNNING, {
                    'channels': len(self.config.channels) if self.config else 0,
                    'elapsed_ms': int((time.time() - _start_time) * 1000),
                })

            # Reset scan health counters on fresh start
            self._scan_consecutive_errors = 0
            self._scan_total_errors = 0
            self._scan_loop_healthy = True
            self._safety_eval_failures = 0
            self._historian_error_count = 0

            # Forward acquisition start to all connected cRIO nodes
            # Wrapped in separate try-except to prevent rollback after success ack
            try:
                self._forward_acquisition_command_to_crio('start', request_id)
                logger.info(f"[TIMING] cRIO forward complete: {(time.time()-_start_time)*1000:.1f}ms")
            except Exception as crio_err:
                logger.error(f"[STATE MACHINE] cRIO forward failed (acquisition still running locally): {crio_err}")
                if self._acq_events:
                    self._acq_events.emit(AcquisitionEvent.CRIO_START_ACK_TIMEOUT, {
                        'error': str(crio_err),
                    }, severity='warning')

        except Exception as e:
            logger.error(f"[STATE] Error starting acquisition: {e}", exc_info=True)
            if self._acq_events:
                self._acq_events.emit(AcquisitionEvent.START_FAILED, {
                    'error': str(e),
                    'elapsed_ms': int((time.time() - _start_time) * 1000),
                }, severity='error')
            # STATE ROLLBACK: Force back to stopped on error
            self._state_machine.force_state(DAQState.STOPPED)
            # Unlock safety config on failure
            if self.project_manager:
                self.project_manager.unlock_safety_config()
            logger.error(f"[STATE] Rolled back to STOPPED (state={self._state_machine.state.name})")
            self._publish_system_status()  # Notify frontend of state rollback
            self._publish_command_ack("acquire/start", request_id, False, str(e))
        finally:
            if self._acq_events:
                self._acq_events.end_flow()

    def _handle_acquire_stop(self, request_id: Optional[str] = None, force: bool = False):
        """Coordinated acquisition stop — cascades session, recording, cRIO.

        Sequence:
            1. Permission check
            2. Safety gate: reject if alarms/interlocks active (unless force=True)
            3. State → STOPPING (immediate status push for UI feedback)
            4. Cascade: stop session → stop recording
            5. Forward stop to cRIO nodes and wait for ACK (up to 5 s)
            6. Stop local engines (scripts, triggers, watchdog)
            7. State → STOPPED
            8. Audit + cleanup
            9. ACK to dashboard (confirmed complete)
        """
        _start_time = time.time()
        logger.info(f"[TIMING] _handle_acquire_stop called (force={force})")
        flow_id = request_id or str(uuid.uuid4())[:8]
        if self._acq_events:
            self._acq_events.start_flow(flow_id)
            self._acq_events.emit(AcquisitionEvent.STOP_REQUESTED, {'request_id': request_id})
        try:
            # 1. PERMISSION CHECK
            if not self._has_permission(Permission.STOP_ACQUISITION):
                logger.warning("[SECURITY] Acquisition stop denied - insufficient permissions")
                self._publish_command_ack("acquire/stop", request_id, False, "Permission denied")
                return
            logger.info(f"[TIMING] STOP Permission check: {(time.time()-_start_time)*1000:.1f}ms")

            # 2. SAFETY GATE: Block stop if alarms or interlocks are active
            #    Stopping acquisition while a safety condition is active means
            #    losing monitoring — outputs stay in their current state with no
            #    feedback loop.  Require force=True to override.
            if not force:
                safety_issues = []
                if self.alarm_manager:
                    active_alarms = self.alarm_manager.get_active_alarms()
                    if active_alarms:
                        alarm_names = [f"{a.channel}:{a.severity.name}" for a in active_alarms[:5]]
                        safety_issues.append(f"{len(active_alarms)} active alarm(s): {', '.join(alarm_names)}")
                if self.safety_manager and self.safety_manager.latch_state.name == 'TRIPPED':
                    tripped = [iid for iid, il in self.safety_manager.interlocks.items()
                               if hasattr(il, 'tripped') and il.tripped]
                    safety_issues.append(f"Safety latch TRIPPED ({len(tripped)} interlock(s))")
                if safety_issues:
                    msg = "Cannot stop with active safety conditions: " + "; ".join(safety_issues) + \
                          ". Send with force=true to override."
                    logger.warning(f"[SAFETY] Acquisition stop blocked: {msg}")
                    self._publish_command_ack("acquire/stop", request_id, False, msg)
                    return
            logger.info(f"[TIMING] STOP Safety gate: {(time.time()-_start_time)*1000:.1f}ms")

            # 3. STATE TRANSITION: running → stopping
            logger.info(f"[STATE] Acquisition stop requested (current: {self._state_machine.state.name})")
            if not self._state_machine.to(DAQState.STOPPING):
                logger.warning(f"[STATE] Acquisition stop rejected (state={self._state_machine.state.name})")
                self._publish_command_ack("acquire/stop", request_id, False, "Not acquiring")
                return
            logger.info(f"[TIMING] STOP State update: {(time.time()-_start_time)*1000:.1f}ms")
            self._publish_system_status(skip_resource_monitoring=True)  # Fast UI feedback: show STOPPING

            # 4. CASCADE: Stop session and recording BEFORE stopping acquisition
            #    Session must stop first (it depends on recording and acquisition)
            session_active = (self.user_variables and self.user_variables.session.active)
            if session_active:
                logger.info("[STATE] Cascading stop to active session")
                self._handle_test_session_stop()
            if self.recording:
                logger.info("[STATE] Cascading stop to recording")
                self._handle_recording_stop()
            logger.info(f"[TIMING] STOP Session+recording cascade: {(time.time()-_start_time)*1000:.1f}ms")

            # 5. FORWARD to cRIO nodes and wait for ACK confirmation
            crio_ack_ok = self._stop_crio_nodes_and_wait(request_id, timeout_s=5.0)
            logger.info(f"[TIMING] STOP cRIO forward+wait: {(time.time()-_start_time)*1000:.1f}ms (ack={crio_ack_ok})")

            # 6. STOP local engines
            if self.script_manager:
                self.script_manager.on_acquisition_stop()
                self._publish_script_status()
            if self.trigger_engine:
                self.trigger_engine.on_acquisition_stop()
            if self.watchdog_engine:
                self.watchdog_engine.on_acquisition_stop()
            logger.info(f"[TIMING] STOP Engines notified: {(time.time()-_start_time)*1000:.1f}ms")

            # 7. STATE TRANSITION: stopping → stopped
            self._state_machine.to(DAQState.STOPPED)
            logger.info(f"[STATE] Acquisition stopped successfully (state={self._state_machine.state.name})")

            # 8. CLEANUP & AUDIT
            if self.project_manager:
                self.project_manager.unlock_safety_config()
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.ACQUISITION_STOPPED,
                    user=self.auth_username or "system",
                    description="Data acquisition stopped",
                    details={
                        'session_was_active': session_active,
                        'recording_was_active': self.recording,
                        'crio_ack': crio_ack_ok,
                        'forced': force,
                        'elapsed_ms': int((time.time() - _start_time) * 1000),
                    }
                )
            self._clear_channel_claims()
            self._publish_system_status()  # Full status with resource monitoring

            # 9. ACK — confirmed: everything is stopped
            elapsed_ms = int((time.time() - _start_time) * 1000)
            self._publish_command_ack("acquire/stop", request_id, True)
            logger.info(f"[TIMING] STOP complete + ACK: {elapsed_ms}ms")
            if self._acq_events:
                self._acq_events.emit(AcquisitionEvent.ACQUIRE_STOPPED, {
                    'elapsed_ms': elapsed_ms,
                    'crio_ack': crio_ack_ok,
                })

        except Exception as e:
            logger.error(f"[STATE MACHINE] Error stopping acquisition: {e}", exc_info=True)
            self._publish_command_ack("acquire/stop", request_id, False, str(e))
            if self._acq_events:
                self._acq_events.emit(AcquisitionEvent.STOP_FAILED, {'error': str(e)}, severity='error')
        finally:
            if self._acq_events:
                self._acq_events.end_flow()

    def _handle_safe_state(self, payload: Any, request_id: Optional[str] = None):
        """Set all outputs to safe state (DO=0, AO=0)

        Called when loading/importing a project to ensure outputs are safe
        before any configuration changes are applied.
        """
        # PERMISSION CHECK
        if not self._has_permission(Permission.TRIGGER_SAFE_STATE):
            logger.warning("[SECURITY] Safe-state command denied - insufficient permissions")
            self._publish_command_ack("system/safe-state", request_id, False, "Permission denied")
            return

        reason = payload.get('reason', 'command') if isinstance(payload, dict) else 'command'
        logger.info(f"[SAFE STATE] Setting all outputs to safe state - reason: {reason}")

        # Forward atomic safe-state command to all online cRIO nodes
        # This triggers hardware.set_safe_state() on the cRIO in a single call,
        # rather than relying on individual per-channel output commands
        self._forward_safe_state_to_crio(reason, request_id)

        # Reset all local outputs (cRIO channels also sent individually as fallback).
        # bypass_interlock=True: safe state IS the interlock response, it MUST
        # be able to drive outputs to safe values regardless of interlock state.
        for channel_name, config in self.config.channels.items():
            if config.channel_type == ChannelType.DIGITAL_OUTPUT:
                try:
                    self._set_output_value(channel_name, 0, bypass_interlock=True)
                    logger.info(f"[SAFE STATE] DO {channel_name} -> 0 (OFF)")
                except Exception as e:
                    logger.error(f"[SAFE STATE] Failed to set {channel_name}: {e}")
            elif config.channel_type == ChannelType.VOLTAGE_OUTPUT:
                try:
                    # Voltage output safe state: 0V
                    self._set_output_value(channel_name, 0.0, bypass_interlock=True)
                    logger.info(f"[SAFE STATE] VO {channel_name} -> 0.0V")
                except Exception as e:
                    logger.error(f"[SAFE STATE] Failed to set {channel_name}: {e}")
            elif config.channel_type == ChannelType.CURRENT_OUTPUT:
                try:
                    # Current output safe state: 0mA
                    self._set_output_value(channel_name, 0.0, bypass_interlock=True)
                    logger.info(f"[SAFE STATE] CO {channel_name} -> 0.0mA")
                except Exception as e:
                    logger.error(f"[SAFE STATE] Failed to set {channel_name}: {e}")

        # Publish confirmation
        self.mqtt_client.publish(
            f"{self.get_topic_base()}/status/safe-state",
            json.dumps({
                'success': True,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            })
        )
        self._publish_command_ack("system/safe-state", request_id, True)
        logger.info("[SAFE STATE] All outputs set to safe state")

    def _handle_recording_start(self, payload: Any, request_id: Optional[str] = None):
        """Start data recording with state validation"""
        # PERMISSION CHECK
        if not self._has_permission(Permission.START_RECORDING):
            logger.warning("[SECURITY] Recording start denied - insufficient permissions")
            self._publish_command_ack("recording/start", request_id, False, "Permission denied")
            return

        # STATE VALIDATION: Check prerequisites
        logger.info(f"[STATE MACHINE] Recording start requested (acquiring={self.acquiring}, recording={self.recording})")

        if not self.acquiring:
            logger.error("[STATE MACHINE] Recording start rejected - acquisition not running (PREREQUISITE FAILED)")
            self._publish_command_ack("recording/start", request_id, False, "Acquisition must be running to start recording")
            return

        if self.recording_manager.recording:
            logger.warning("[STATE MACHINE] Recording start rejected - already recording")
            self._publish_command_ack("recording/start", request_id, False, "Recording already active")
            return

        # STATE TRANSITION: idle → starting
        logger.info("[STATE MACHINE] Recording transitioning: idle → starting")

        # Get optional filename from payload
        filename = None
        if isinstance(payload, dict):
            filename = payload.get('filename')

            # Also apply any config from payload
            config_updates = {k: v for k, v in payload.items() if k != 'filename' and k != 'request_id'}
            if config_updates:
                logger.info(f"[STATE MACHINE] Applying recording config updates: {list(config_updates.keys())}")
                self.recording_manager.configure(config_updates)

        # STATE TRANSITION: starting → recording
        if self.recording_manager.start(filename):
            self.recording = True
            self.recording_start_time = self.recording_manager.recording_start_time
            self.recording_filename = self.recording_manager.current_file.name if self.recording_manager.current_file else None
            logger.info(f"[STATE MACHINE] Recording started successfully (file: {self.recording_filename})")
            self._publish_command_ack("recording/start", request_id, True)
            self._publish_system_status()

            # Start Azure IoT streaming if configured
            azure_config = self._get_azure_config()
            if azure_config:
                self._sync_azure_config_to_historian(streaming=True)
        else:
            logger.error("[STATE MACHINE] Recording start failed - manager returned False")
            self._publish_command_ack("recording/start", request_id, False, "Failed to start recording")

    def _handle_recording_stop(self, request_id: Optional[str] = None):
        """Stop data recording with state validation"""
        # PERMISSION CHECK
        if not self._has_permission(Permission.STOP_RECORDING):
            logger.warning("[SECURITY] Recording stop denied - insufficient permissions")
            self._publish_command_ack("recording/stop", request_id, False, "Permission denied")
            return

        # STATE VALIDATION: Check current state
        logger.info(f"[STATE MACHINE] Recording stop requested (recording={self.recording})")

        if not self.recording_manager.recording:
            logger.warning("[STATE MACHINE] Recording stop rejected - not recording")
            self._publish_command_ack("recording/stop", request_id, False, "Recording not active")
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
            self._publish_command_ack("recording/stop", request_id, True)
            self._publish_system_status()

            # Stop Azure IoT streaming if it was active
            if self._get_azure_config():
                self._sync_azure_config_to_historian(streaming=False)
        else:
            logger.error("[STATE MACHINE] Recording stop failed - manager returned False")
            self._publish_command_ack("recording/stop", request_id, False, "Failed to stop recording")

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

    # =========================================================================
    # NOTIFICATION MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_notifications_config_update(self, payload: Any):
        """Update notification configuration (Twilio SMS + Email)."""
        if not isinstance(payload, dict):
            self._publish_notifications_response(False, "Invalid payload")
            return

        if not self.notification_manager:
            self._publish_notifications_response(False, "Notification manager not initialized")
            return

        if self.notification_manager.configure(payload):
            self._publish_notifications_response(True, "Notification configuration updated")
        else:
            self._publish_notifications_response(False, "Failed to update notification config")

    def _handle_notifications_config_get(self):
        """Return current notification configuration."""
        if not self.notification_manager:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/notifications/config",
            json.dumps(self.notification_manager.get_config()),
            retain=True,
            qos=1
        )

    def _handle_notifications_test(self, payload: Any):
        """Send a test notification (SMS or Email)."""
        if not isinstance(payload, dict):
            self._publish_notifications_response(False, "Invalid payload")
            return

        if not self.notification_manager:
            self._publish_notifications_response(False, "Notification manager not initialized")
            return

        channel = payload.get('channel', '')
        config_override = payload.get('config')

        result = self.notification_manager.send_test_notification(channel, config_override)
        self._publish_notifications_response(result['success'], result['message'])

    def _publish_notifications_response(self, success: bool, message: str):
        """Publish notification command response."""
        if not self.mqtt_client:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/notifications/response",
            json.dumps({
                'success': success,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }),
            qos=1
        )

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

    def _handle_recording_db_test(self, payload: Any):
        """Test PostgreSQL database connection"""
        if not isinstance(payload, dict):
            self._publish_recording_response(False, "Invalid payload")
            return

        success, message = PostgreSQLWriter.test_connection(
            host=payload.get('host', 'localhost'),
            port=payload.get('port', 5432),
            dbname=payload.get('dbname', 'iccsflux'),
            user=payload.get('user', 'iccsflux'),
            password=payload.get('password', ''),
        )
        self._publish_recording_response(success, message)

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

    def _handle_recording_read(self, payload: Any):
        """Read historical data from a recording file"""
        if not isinstance(payload, dict):
            self._publish_recording_read_response({"success": False, "error": "Invalid payload"})
            return

        filename = payload.get('filename')
        if not filename:
            self._publish_recording_read_response({"success": False, "error": "No filename specified"})
            return

        result = self.recording_manager.read_file(
            filename=filename,
            start_time=payload.get('start_time'),
            end_time=payload.get('end_time'),
            channels=payload.get('channels'),
            decimation=payload.get('decimation', 1),
            max_samples=payload.get('max_samples', 50000)
        )

        self._publish_recording_read_response(result)

    def _handle_recording_read_range(self, payload: Any):
        """Read a range of samples from a recording file (lazy loading)"""
        if not isinstance(payload, dict):
            self._publish_recording_read_response({"success": False, "error": "Invalid payload"})
            return

        filename = payload.get('filename')
        if not filename:
            self._publish_recording_read_response({"success": False, "error": "No filename specified"})
            return

        result = self.recording_manager.read_file_range(
            filename=filename,
            start_sample=payload.get('start_sample', 0),
            end_sample=payload.get('end_sample'),
            channels=payload.get('channels')
        )

        self._publish_recording_read_response(result)

    def _handle_recording_file_info(self, payload: Any):
        """Get metadata about a recording file"""
        if not isinstance(payload, dict):
            self._publish_recording_read_response({"success": False, "error": "Invalid payload"})
            return

        filename = payload.get('filename')
        if not filename:
            self._publish_recording_read_response({"success": False, "error": "No filename specified"})
            return

        result = self.recording_manager.get_file_info(filename)
        self._publish_recording_read_response(result)

    def _publish_recording_read_response(self, result: dict):
        """Publish recording read response"""
        base = self.get_topic_base()

        # Add timestamp
        result["timestamp"] = datetime.now().isoformat()

        self.mqtt_client.publish(
            f"{base}/recording/read/response",
            json.dumps(result)
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
    # HISTORIAN COMMAND HANDLERS
    # =========================================================================

    def _handle_historian_query(self, payload: Any):
        """Query historical data from the SQLite historian."""
        base = self.get_topic_base()
        if not self.historian:
            self.mqtt_client.publish(f"{base}/historian/query/response",
                                     json.dumps({"success": False, "error": "Historian not available"}))
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(f"{base}/historian/query/response",
                                     json.dumps({"success": False, "error": "Invalid payload"}))
            return

        channels = payload.get('channels', [])
        start_ms = int(payload.get('start_ms', 0))
        end_ms = int(payload.get('end_ms', int(time.time() * 1000)))
        max_points = int(payload.get('max_points', 2000))
        panel_id = payload.get('_panel_id')

        result = self.historian.query(channels, start_ms, end_ms, max_points)
        if panel_id:
            result['_panel_id'] = panel_id
        self.mqtt_client.publish(f"{base}/historian/query/response", json.dumps(result))

    def _handle_historian_tags(self):
        """Return available historian tags with time ranges."""
        base = self.get_topic_base()
        if not self.historian:
            self.mqtt_client.publish(f"{base}/historian/tags/response",
                                     json.dumps({"success": False, "tags": []}))
            return

        tags = self.historian.get_available_tags()
        self.mqtt_client.publish(f"{base}/historian/tags/response",
                                 json.dumps({"success": True, "tags": tags}))

    def _handle_historian_export(self, payload: Any):
        """Export historian data as CSV."""
        base = self.get_topic_base()
        if not self.historian:
            self.mqtt_client.publish(f"{base}/historian/export/response",
                                     json.dumps({"success": False, "error": "Historian not available"}))
            return

        if not isinstance(payload, dict):
            self.mqtt_client.publish(f"{base}/historian/export/response",
                                     json.dumps({"success": False, "error": "Invalid payload"}))
            return

        channels = payload.get('channels', [])
        start_ms = int(payload.get('start_ms', 0))
        end_ms = int(payload.get('end_ms', int(time.time() * 1000)))
        panel_id = payload.get('_panel_id')

        csv_data = self.historian.export_csv(channels, start_ms, end_ms)

        # Safety cap: if CSV > 5 MB, truncate and warn (MQTT not suited for huge payloads)
        max_csv_bytes = 5 * 1024 * 1024
        truncated = False
        if len(csv_data) > max_csv_bytes:
            # Keep header + as many complete rows as fit
            lines = csv_data.split('\n')
            header = lines[0] if lines else ''
            kept = [header]
            size = len(header) + 1
            for line in lines[1:]:
                size += len(line) + 1
                if size > max_csv_bytes:
                    break
                kept.append(line)
            csv_data = '\n'.join(kept)
            truncated = True

        response: dict = {"success": True, "csv": csv_data, "truncated": truncated}
        if panel_id:
            response['_panel_id'] = panel_id
        self.mqtt_client.publish(f"{base}/historian/export/response",
                                 json.dumps(response))

    def _handle_historian_stats(self):
        """Return historian database statistics."""
        base = self.get_topic_base()
        if not self.historian:
            self.mqtt_client.publish(f"{base}/historian/stats/response",
                                     json.dumps({"success": False, "error": "Historian not available"}))
            return

        stats = self.historian.get_stats()
        stats['success'] = True
        self.mqtt_client.publish(f"{base}/historian/stats/response", json.dumps(stats))

    # =========================================================================
    # LOG VIEWER HANDLERS
    # =========================================================================

    def _drain_and_publish_logs(self):
        """Drain log buffer and publish entries to MQTT for the Log Viewer."""
        if not self._log_handler or not self.mqtt_client:
            return
        entries = self._log_handler.drain()
        if entries:
            base = self.get_topic_base()
            try:
                self.mqtt_client.publish(
                    f"{base}/logs/stream",
                    json.dumps(entries),
                    qos=0
                )
            except Exception:
                pass  # Log streaming must never affect the publish loop

    def _handle_logs_query(self, payload: Any):
        """Handle log query request — returns recent log entries."""
        base = self.get_topic_base()
        try:
            count = 200
            level = None
            if isinstance(payload, dict):
                count = min(payload.get('count', 200), 500)
                level = payload.get('level')

            entries = self._log_handler.get_recent(count=count, level=level)
            self.mqtt_client.publish(
                f"{base}/logs/query/response",
                json.dumps({'success': True, 'entries': entries}),
                qos=0
            )
        except Exception as e:
            self.mqtt_client.publish(
                f"{base}/logs/query/response",
                json.dumps({'success': False, 'error': str(e)}),
                qos=0
            )

    # =========================================================================
    # AZURE IOT HUB COMMAND HANDLERS
    # =========================================================================

    def _handle_azure_config(self, payload: Any):
        """Update Azure IoT Hub configuration (stored in project, used when recording starts)"""
        if not isinstance(payload, dict):
            self._publish_azure_response({"success": False, "error": "Invalid payload"})
            return

        try:
            connection_string = payload.get('connection_string')
            channels = payload.get('channels', [])
            batch_size = payload.get('batch_size', 10)
            batch_interval_ms = payload.get('batch_interval_ms', 1000)

            # Store Azure config in system config (will be saved with project)
            if not hasattr(self.config.system, 'azure_iot') or self.config.system.azure_iot is None:
                self.config.system.azure_iot = {}

            # Update config
            if connection_string is not None:
                self.config.system.azure_iot['connection_string'] = connection_string
            self.config.system.azure_iot['channels'] = channels
            self.config.system.azure_iot['batch_size'] = batch_size
            self.config.system.azure_iot['batch_interval_ms'] = batch_interval_ms

            self._publish_azure_response({"success": True, "message": "Azure config saved to project"})
            self._publish_azure_config_current()

            # Write config to historian so the Azure uploader can read it
            self._sync_azure_config_to_historian()

            # Log to audit trail
            if self.audit_trail:
                self.audit_trail.log_config_change(
                    config_type='azure_iot',
                    item_id='azure_iot_config',
                    user=self.current_session_id or 'system',
                    previous_value=None,
                    new_value={'channels': channels}
                )

            logger.info(f"Azure IoT config saved: {len(channels)} channels")

        except Exception as e:
            logger.error(f"Error configuring Azure IoT: {e}")
            self._publish_azure_response({"success": False, "error": str(e)})

    def _handle_azure_config_get(self):
        """Get current Azure IoT configuration"""
        self._publish_azure_config_current()

    def _handle_azure_start(self, payload: Any = None):
        """Start Azure IoT Hub streaming"""
        azure_config = self._get_azure_config()
        if not azure_config:
            self._publish_azure_response({"success": False, "error": "Azure IoT Hub not configured"})
            return

        # Write streaming=True to historian so uploader picks it up
        self._sync_azure_config_to_historian(streaming=True)
        self._publish_azure_response({"success": True, "message": "Azure IoT streaming started"})
        logger.info("Azure IoT Hub streaming enabled")

    def _handle_azure_stop(self):
        """Stop Azure IoT Hub streaming"""
        # Write streaming=False to historian so uploader picks it up
        self._sync_azure_config_to_historian(streaming=False)
        self._publish_azure_response({"success": True, "message": "Azure IoT streaming stopped"})
        logger.info("Azure IoT Hub streaming disabled")

    def _sync_azure_config_to_historian(self, streaming: Optional[bool] = None):
        """Write current Azure config to historian.db for the uploader to read."""
        if not self.historian:
            return
        try:
            azure_cfg = self._get_azure_config() or {}
            config = {
                'connection_string': azure_cfg.get('connection_string', ''),
                'channels': azure_cfg.get('channels', []),
                'batch_size': azure_cfg.get('batch_size', 10),
                'upload_interval_ms': azure_cfg.get('batch_interval_ms', 1000),
                'node_id': azure_cfg.get('node_id', getattr(self.config.system, 'node_id', 'node-001')),
                'streaming': streaming if streaming is not None else False,
            }
            self.historian.write_azure_config(config)
        except Exception as e:
            logger.warning(f"Failed to sync Azure config to historian: {e}")

    def _handle_azure_status_get(self):
        """Get Azure IoT Hub status"""
        self._publish_azure_config_current()

    def _publish_azure_response(self, result: dict):
        """Publish Azure command response"""
        base = self.get_topic_base()
        result["timestamp"] = datetime.now().isoformat()
        self.mqtt_client.publish(
            f"{base}/azure/response",
            json.dumps(result)
        )

    def _publish_azure_config_current(self):
        """Publish current Azure IoT configuration (from project config)"""
        base = self.get_topic_base()

        # Get config from project/system config
        azure_cfg = self._get_azure_config()

        if azure_cfg:
            config = {
                'enabled': False,  # Streaming is tied to recording, not standalone enabled
                'channels': azure_cfg.get('channels', []),
                'batch_size': azure_cfg.get('batch_size', 10),
                'batch_interval_ms': azure_cfg.get('batch_interval_ms', 1000),
                'has_connection_string': True,
            }
        else:
            config = {
                'enabled': False,
                'channels': [],
                'batch_size': 10,
                'batch_interval_ms': 1000,
                'has_connection_string': False,
            }

        # Stats come from external Azure uploader service via nisystem/azure/status topic
        # We just publish the config here
        self.mqtt_client.publish(
            f"{base}/azure/config/current",
            json.dumps({
                "config": config,
                "stats": {},  # External service publishes stats to nisystem/azure/status
                "available": True,  # External Azure uploader service handles availability
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

        # Track cRIO discovery ping interval (every 10 seconds = every 5 heartbeats at 2s interval)
        crio_ping_counter = 0
        crio_ping_interval = 5  # heartbeats between pings

        # Credential health check interval (every ~60s = every 30 heartbeats at 2s interval)
        credential_health_counter = 0
        credential_health_interval = 30

        # Session lock check interval (every ~30s = every 15 heartbeats at 2s interval)
        session_lock_counter = 0
        session_lock_interval = 15

        security_summary_counter = 0
        security_summary_interval = 150

        audit_integrity_counter = 0
        audit_integrity_interval = 43200

        while not self._shutdown_requested.wait(timeout=self._heartbeat_interval):
            if not self._running.is_set():
                continue

            try:
                self._heartbeat_sequence += 1
                uptime = 0.0
                if self._start_time:
                    uptime = (datetime.now() - self._start_time).total_seconds()

                base = self.get_topic_base()

                # Report actual acquiring state - user must press START to begin
                # cRIO online status is separate from acquisition state
                current_mode = self.config.system.project_mode.value if self.config and self.config.system else 'cdaq'

                payload = {
                    "sequence": self._heartbeat_sequence,
                    "timestamp": datetime.now().isoformat(),
                    "acquiring": self.acquiring,
                    "recording": self.recording,
                    "mode": current_mode,  # cdaq, crio, or opto22
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

                # Periodic cRIO discovery ping - ensures we find cRIO nodes even without manual scan
                crio_ping_counter += 1
                if crio_ping_counter >= crio_ping_interval:
                    crio_ping_counter = 0
                    self._send_crio_discovery_ping()

                # Does NOT stop acquisition, recording, or any backend processes.
                session_lock_counter += 1
                if session_lock_counter >= session_lock_interval:
                    session_lock_counter = 0
                    if self.user_session_manager:
                        locked_ids = self.user_session_manager.lock_expired_sessions()
                        for sid in locked_ids:
                            if sid == self.current_session_id:
                                self._publish_auth_status()  # Notify dashboard of lock
                        self.user_session_manager.cleanup_expired_sessions()

                # Periodic credential health check — detect offline nodes that are reachable
                credential_health_counter += 1
                if credential_health_counter >= credential_health_interval:
                    credential_health_counter = 0
                    self._check_node_credential_health()

                security_summary_counter += 1
                if security_summary_counter >= security_summary_interval:
                    security_summary_counter = 0
                    if self.security_monitor:
                        summary = self.security_monitor.get_summary()
                        self.mqtt_client.publish(
                            f'{base}/security/summary',
                            json.dumps(summary), retain=True)
                        # Check for new anomalies and log to audit
                        anomalies = self.security_monitor.get_and_clear_anomalies()
                        for anomaly in anomalies:
                            if self.audit_trail:
                                self.audit_trail.log_event(
                                    event_type=AuditEventType.SECURITY_ANOMALY,
                                    user="SYSTEM",
                                    description=anomaly['description'],
                                    details=anomaly
                                )
                            self.mqtt_client.publish(
                                f'{base}/security/anomaly',
                                json.dumps(anomaly))

                audit_integrity_counter += 1
                if audit_integrity_counter >= audit_integrity_interval:
                    audit_integrity_counter = 0
                    if self.audit_trail:
                        is_valid, errors, count = self.audit_trail.verify_integrity()
                        if not is_valid:
                            logger.warning(f"[AUDIT] Daily integrity check FAILED: "
                                          f"{len(errors)} error(s) in {count} entries")
                            self.mqtt_client.publish(
                                f'{base}/audit/integrity_failure',
                                json.dumps({'errors': errors[:10], 'entries_checked': count}),
                                qos=1)

            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}", exc_info=True)

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

    def _publish_health(self):
        """Publish continuous health status for diagnostic overlay."""
        base = self.get_topic_base()
        now = time.time()

        # Hardware health (reuse existing method if available)
        hw_health = None
        if self.hardware_reader:
            try:
                hw_health = self.hardware_reader.get_health_status()
            except Exception:
                hw_health = {'healthy': False, 'error': 'health_check_failed'}

        # Channel stats
        nan_count = 0
        stale_count = 0
        with self.values_lock:
            for name, val in self.channel_values.items():
                if isinstance(val, float) and val != val:  # NaN check
                    nan_count += 1
                ts = self.channel_acquisition_ts_us.get(name, 0)
                if ts > 0 and (now - ts / 1_000_000) > 10.0:
                    stale_count += 1

        health = {
            'timestamp': datetime.now().isoformat(),
            'scan_loop': {
                'healthy': self._scan_loop_healthy,
                'consecutive_errors': self._scan_consecutive_errors,
                'total_errors': self._scan_total_errors,
                'last_successful_scan': self._last_successful_scan_time,
                'errors_per_minute': (self._scan_total_errors / max(1, (now - self._last_successful_scan_time))) * 60 if self._last_successful_scan_time > 0 else 0,
            },
            'hardware': hw_health,
            'safety': {
                'last_eval_time': self._last_safety_eval_time,
                'eval_failures': self._safety_eval_failures,
                'healthy': self._safety_eval_failures < 3,
            },
            'channels': {
                'total': len(self.config.channels) if self.config else 0,
                'nan_count': nan_count,
                'stale_count': stale_count,
            },
        }
        try:
            self.mqtt_client.publish(
                f"{base}/status/health",
                json.dumps(health),
                qos=0
            )
        except Exception:
            pass  # Health publish must never disrupt the publish loop

    def _publish_system_status(self, skip_resource_monitoring: bool = False):
        """Publish comprehensive system status.

        Args:
            skip_resource_monitoring: If True, skip CPU/memory/disk monitoring
                                     for faster status updates (e.g., during state changes)
        """
        base = self.get_topic_base()

        # Update resource monitoring (skip for fast path)
        if not skip_resource_monitoring and self._resource_monitor_enabled and self._process:
            try:
                self._cpu_percent = self._process.cpu_percent(interval=None)
                mem_info = self._process.memory_info()
                self._memory_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
                # Get disk usage for data directory
                if self._psutil:
                    disk = self._psutil.disk_usage('/')
                    self._disk_percent = disk.percent
                    self._disk_used_gb = disk.used / (1024 ** 3)  # Convert to GB
                    self._disk_total_gb = disk.total / (1024 ** 3)
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
            "node_type": "daq",
            # Project mode (cdaq = PC is PLC, crio = cRIO is PLC/HMI split)
            "project_mode": self.config.system.project_mode.value,
            "simulation_mode": self.config.system.simulation_mode or not NIDAQMX_AVAILABLE,
            "acquiring": self.acquiring,
            "acquisition_state": self.acquisition_state,  # stopped, initializing, running
            "system_mode": self._system_mode,
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
            # Per-project operational settings
            "log_level": self.config.system.log_level,
            "log_max_file_size_mb": self.config.system.log_max_file_size_mb,
            "log_backup_count": self.config.system.log_backup_count,
            "service_heartbeat_interval_sec": self.config.system.service_heartbeat_interval_sec,
            "service_health_timeout_sec": self.config.system.service_health_timeout_sec,
            "service_shutdown_timeout_sec": self.config.system.service_shutdown_timeout_sec,
            "service_command_ack_timeout_sec": self.config.system.service_command_ack_timeout_sec,
            "dataviewer_retention_days": self.config.system.dataviewer_retention_days,
            "scan_timing": self._scan_timing.to_dict(),
            "channel_count": len(self.config.channels),
            "config_path": self.config_path,
            # Sequence status
            "sequences_active": self._get_active_sequence_count(),
            "sequences_total": len(self.sequence_manager.sequences) if self.sequence_manager else 0,
            # Hardware source summary - shows cRIO vs cDAQ vs Modbus channel counts
            "hardware_sources": get_hardware_source_summary(self.config),
            "crio_channel_count": len(get_crio_channels(self.config)),
            "local_daq_channel_count": len(get_local_daq_channels(self.config)),
            "modbus_channel_count": len(get_modbus_channels(self.config)),
            # Resource monitoring
            "cpu_percent": round(self._cpu_percent, 1) if self._resource_monitor_enabled else None,
            "memory_mb": round(self._memory_mb, 1) if self._resource_monitor_enabled else None,
            "disk_percent": round(self._disk_percent, 1) if self._resource_monitor_enabled else None,
            "disk_used_gb": round(self._disk_used_gb, 1) if self._resource_monitor_enabled else None,
            "disk_total_gb": round(self._disk_total_gb, 1) if self._resource_monitor_enabled else None,
            "resource_monitoring": self._resource_monitor_enabled,
            # Test session
            "session_active": self.user_variables.session.active if self.user_variables else False,
            # Watchdog output config
            "watchdog_output": {
                "enabled": self.config.system.watchdog_output_enabled,
                "channel": self.config.system.watchdog_output_channel,
                "rate_hz": self.config.system.watchdog_output_rate_hz
            },
            # Hardware health
            "hardware_health": self.hardware_reader.get_health_status() if self.hardware_reader else None,
            # MQTT publish queue health
            "publish_queue_drops": self._publish_queue_drops,
            "publish_queue_size": self._publish_queue.qsize(),
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

        # Publish Modbus connection status (if configured)
        if self.modbus_reader:
            try:
                self._publish_modbus_status()
            except Exception as e:
                logger.debug(f"Error publishing Modbus status: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Get current system metrics for health/metrics endpoints.

        Returns a dict suitable for JSON serialization.
        This can be passed as a metrics_provider to DashboardServer.
        """
        uptime_seconds = 0.0
        if self._start_time:
            uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        metrics = {
            'uptime_seconds': round(uptime_seconds, 1),
            'acquiring': self.acquiring,
            'acquisition_state': self.acquisition_state,
            'recording': self.recording,
            'channel_count': len(self.config.channels) if self.config else 0,
            'scan_rate_hz': self.config.system.scan_rate_hz if self.config else 0,
            'publish_rate_hz': self.config.system.publish_rate_hz if self.config else 0,
            'dt_scan_ms': round(self.last_scan_dt_ms, 2),
            'dt_publish_ms': round(self.last_publish_dt_ms, 2),
            'scan_timing': self._scan_timing.to_dict(),
            'command_queue_size': self._command_queue.qsize(),
            'command_queue_capacity': self._command_queue.maxsize,
        }

        if self._resource_monitor_enabled:
            metrics['cpu_percent'] = round(self._cpu_percent, 1)
            metrics['memory_mb'] = round(self._memory_mb, 1)
            metrics['disk_percent'] = round(self._disk_percent, 1)

        return metrics

    def _publish_alarms_cleared(self, reason: str = "project_change"):
        """Publish alarm cleared message to signal frontend to clear stale alarm data.

        This is called when:
        - A new project is loaded (clears previous project's alarms)
        - A project is closed (clears all alarms)
        - No project is configured at startup

        The frontend should listen for this message and clear:
        - Active alarms
        - Alarm history
        - Alarm configurations (for orphaned channels)
        - localStorage alarm data

        Also clears retained MQTT messages for individual alarm topics to prevent
        stale alarms from reappearing when frontend reconnects.
        """
        base = self.get_topic_base()
        cleared_count = 0

        # Clear retained MQTT messages for all known active alarms from AlarmManager
        if self.alarm_manager:
            active_alarms = self.alarm_manager.get_active_alarms()
            for alarm in active_alarms:
                # Publish empty retained message to clear the retained alarm
                self.mqtt_client.publish(
                    f"{base}/alarms/active/{alarm.alarm_id}",
                    "",  # Empty payload clears retained message
                    retain=True,
                    qos=1
                )
                cleared_count += 1

        # Also clear any alarms tracked in legacy alarms_active dict
        for source in list(self.alarms_active.keys()):
            self.mqtt_client.publish(
                f"{base}/alarms/active/{source}",
                "",  # Empty payload clears retained message
                retain=True,
                qos=1
            )
            cleared_count += 1
        self.alarms_active.clear()

        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} retained alarm messages from MQTT broker")

        # Also publish clear notification to frontend
        self.mqtt_client.publish(
            f"{base}/alarms/cleared",
            json.dumps({
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            })
        )
        logger.debug(f"Published alarms/cleared message, reason: {reason}")

    def _clear_stale_node_retained_messages(self, new_node_ids: set):
        """Clear retained MQTT messages for nodes no longer in the current project.

        When a new project is loaded, any remote nodes (cRIO, Opto22, cFP) that were
        in the previous project but are NOT in the new project have stale retained
        messages on the broker. These cause phantom alarms/status on dashboard connect.

        Args:
            new_node_ids: Set of source_node_id values from the newly loaded project.
        """
        stale_nodes = self._previous_project_node_ids - new_node_ids
        if not stale_nodes:
            self._previous_project_node_ids = new_node_ids
            return

        base = self.get_topic_base()

        # Retained topic patterns that remote nodes publish
        retained_patterns = [
            "status/system",
            "alarms/status",
            "interlock/status",
            "state",
        ]

        cleared = 0
        for node_id in stale_nodes:
            for pattern in retained_patterns:
                topic = f"{base}/nodes/{node_id}/{pattern}"
                self.mqtt_client.publish(topic, b"", retain=True, qos=1)
                cleared += 1

        if cleared:
            logger.info(f"Cleared {cleared} retained messages for {len(stale_nodes)} "
                        f"stale node(s): {', '.join(sorted(stale_nodes))}")

        self._previous_project_node_ids = new_node_ids

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
        logger.info(f"[AUTH] Login request received: {payload}")

        if not isinstance(payload, dict):
            logger.warning("[AUTH] Invalid payload - not a dict")
            self._publish_auth_status(error="Invalid login payload")
            return

        if not self.user_session_manager:
            logger.error("[AUTH] User session manager not initialized!")
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
                    user=username,
                    description=f"User '{username}' logged in",
                    details={"role": session.role.value, "source_ip": source_ip}
                )

            self._publish_auth_status()
            self._publish_system_status()
        else:
            logger.warning(f"Failed login attempt for user '{username}'")
            self.current_session_id = None
            self.current_user_role = None

            if self.security_monitor:
                self.security_monitor.record_failed_login()

            # Log failed attempt to audit trail
            if self.audit_trail:
                self.audit_trail.log_event(
                    AuditEventType.USER_LOGIN_FAILED,
                    user=username,
                    description=f"Failed login attempt for '{username}'",
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
                    user=username,
                    description=f"User '{username}' logged out"
                )

        logger.info(f"User '{username}' logged out")
        self.current_session_id = None
        self.current_user_role = None
        self._publish_auth_status()
        self._publish_system_status()

    def _handle_auth_unlock(self, payload: Any):
        """Handle session unlock request — re-authenticate locked session.

        Does NOT create a new session. Same session_id, same audit trail.
        Backend processes (acquisition, recording, scripts, safety) are unaffected.
        """
        if not isinstance(payload, dict):
            self._publish_auth_status(error="Invalid unlock payload")
            return

        if not self.user_session_manager or not self.current_session_id:
            self._publish_auth_status(error="No session to unlock")
            return

        password = payload.get('password', '')
        if not password:
            self._publish_auth_status(error="Password required to unlock")
            return

        session = self.user_session_manager.unlock_session(
            self.current_session_id, password
        )

        if session:
            logger.info(f"[AUTH] Session unlocked for {session.username}")
            self._publish_auth_status()
        else:
            logger.warning("[AUTH] Session unlock failed: incorrect password")
            self._publish_auth_status(error="Incorrect password")

    def _publish_auth_status(self, error: Optional[str] = None):
        """Publish authentication status with role and session state information"""
        logger.info(f"[AUTH] Publishing auth status (error={error})")
        base = self.get_topic_base()

        # Get user info if authenticated
        user_info = None
        permissions = []
        session_state = "active"
        if self.current_session_id and self.user_session_manager:
            session = self.user_session_manager.validate_session(self.current_session_id)
            if session:
                user_info = self.user_session_manager.get_user_info(session.username)
                session_state = session.state.value
                # Get permissions for this role
                from user_session import ROLE_PERMISSIONS, LOCKED_SESSION_PERMISSIONS, SessionState, UserRole
                role = UserRole(session.role.value) if isinstance(session.role, UserRole) else session.role
                if session.state == SessionState.LOCKED:
                    permissions = [p.value for p in LOCKED_SESSION_PERMISSIONS]
                else:
                    role_perms = ROLE_PERMISSIONS.get(role, set())
                    permissions = [p.value for p in role_perms]

        status = {
            "authenticated": self.authenticated,
            "username": self.auth_username,
            "role": self.current_user_role,
            "session_state": session_state,
            "permissions": permissions,
            "display_name": user_info.get('display_name') if user_info else None,
            "timestamp": datetime.now().isoformat()
        }

        if error:
            status["error"] = error

        topic = f"{base}/auth/status"
        self.mqtt_client.publish(
            topic,
            json.dumps(status),
            retain=True
        )
        logger.info(f"[AUTH] Published auth status to {topic}: authenticated={status['authenticated']}, role={status['role']}")

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
                        event_type=AuditEventType.CONFIG_CHANGE,
                        user=self.auth_username or "system",
                        description=f"User '{username}' created with role '{role}'",
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
                        event_type=AuditEventType.CONFIG_CHANGE,
                        user=self.auth_username or "system",
                        description=f"User '{username}' updated: {', '.join(update_fields.keys())}",
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
                        event_type=AuditEventType.CONFIG_CHANGE,
                        user=self.auth_username or "system",
                        description=f"User '{username}' deleted",
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
            user=username,
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
            # Build filter kwargs for export
            export_filters = {}
            if start_time:
                export_filters['start_time'] = datetime.fromisoformat(start_time)
            if end_time:
                export_filters['end_time'] = datetime.fromisoformat(end_time)

            # Generate export file path
            export_dir = Path(getattr(self.config.system, 'data_directory', 'data')) / 'exports'
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = export_dir / f"audit_export_{timestamp_str}.csv"

            self.audit_trail.export_csv(
                output_path=filepath,
                **export_filters
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
        """Apply current in-memory channel configuration to hardware.

        This reinitializes hardware tasks with the CURRENT channel config (not from file).
        Use this after making channel changes via MQTT to apply them to hardware.

        Payload options:
            restart_acquisition: bool (default False) - if True, restart acquisition after apply
        """
        try:
            logger.info("Applying current channel configuration to hardware...")

            # Parse options
            restart_acq = False
            if isinstance(payload, dict):
                restart_acq = payload.get('restart_acquisition', False)

            # Stop acquisition if running
            was_acquiring = self.acquiring
            if was_acquiring:
                logger.info("Stopping acquisition to apply config changes")
                self._stop_acquire()

            # Reinitialize hardware reader with current in-memory config
            # (Do NOT reload from file - use self.config as-is)
            self._reinit_hardware_reader()

            # Publish updated channel config to frontend
            self._publish_channel_config()

            # Publish status update
            self._publish_system_status()

            # Optionally restart acquisition
            if restart_acq and was_acquiring:
                logger.info("Restarting acquisition after config apply")
                self._start_acquire()

            logger.info("Configuration applied successfully")
            self._publish_config_response(True, "Configuration applied to hardware")

        except Exception as e:
            logger.error(f"Failed to apply configuration: {e}")
            self._publish_config_response(False, f"Apply failed: {str(e)}")

    def _handle_config_system_update(self, payload: Any):
        """Update system configuration (scan rate, publish rate, project mode) at runtime.

        Payload:
            scan_rate_hz: float - New scan rate (capped at 100 Hz)
            publish_rate_hz: float - New publish rate (capped at 10 Hz)
            project_mode: str - 'cdaq' or 'crio'
        """
        try:
            if not isinstance(payload, dict):
                self._publish_config_response(False, "Invalid payload - expected object")
                return

            old_scan_rate = self.config.system.scan_rate_hz
            old_publish_rate = self.config.system.publish_rate_hz
            old_project_mode = self.config.system.project_mode

            # Update scan rate if provided
            if 'scan_rate_hz' in payload:
                new_scan_rate = min(float(payload['scan_rate_hz']), 100.0)  # Cap at 100 Hz
                if new_scan_rate < 0.1:
                    new_scan_rate = 0.1  # Minimum 0.1 Hz
                self.config.system.scan_rate_hz = new_scan_rate
                self._scan_timing.target_ms = 1000.0 / new_scan_rate
                logger.info(f"Scan rate updated: {old_scan_rate} Hz -> {new_scan_rate} Hz")

                # Reinit hardware reader so DAQmx sample clock matches new rate
                if self.hardware_reader and old_scan_rate != new_scan_rate:
                    logger.info(f"Reinitializing hardware reader for new sample rate: {new_scan_rate} Hz")
                    self._reinit_hardware_reader()

            # Update publish rate if provided
            if 'publish_rate_hz' in payload:
                new_publish_rate = min(float(payload['publish_rate_hz']), 10.0)  # Cap at 10 Hz
                if new_publish_rate < 0.1:
                    new_publish_rate = 0.1  # Minimum 0.1 Hz
                self.config.system.publish_rate_hz = new_publish_rate
                logger.info(f"Publish rate updated: {old_publish_rate} Hz -> {new_publish_rate} Hz")

            # Update project mode if provided (reject while acquiring to prevent state corruption)
            if 'project_mode' in payload:
                if self.acquiring:
                    logger.warning("Cannot change project mode while acquiring — stop acquisition first")
                    self._publish_config_response(False, "Stop acquisition before changing project mode")
                    return
                mode_str = payload['project_mode'].lower()
                if mode_str in ('cdaq', 'crio', 'opto22', 'cfp'):
                    try:
                        new_mode = ProjectMode(mode_str)
                        old_mode = self.config.system.project_mode
                        self.config.system.project_mode = new_mode
                        logger.info(f"Project mode updated: {old_mode.value} -> {new_mode.value}")
                        # Clean up stale channel values from the previous mode's channels
                        valid_names = set(self.config.channels.keys())
                        stale = [k for k in self.channel_values if k not in valid_names]
                        for k in stale:
                            del self.channel_values[k]
                            self.channel_timestamps.pop(k, None)
                            self.channel_acquisition_ts_us.pop(k, None)
                            self.channel_qualities.pop(k, None)
                        if stale:
                            logger.info(f"Cleaned up {len(stale)} stale channel values after mode switch")
                        # Reinitialize Modbus reader for new mode's channels
                        self._init_modbus_reader()
                    except ValueError:
                        logger.warning(f"Invalid project_mode: {mode_str}")
                else:
                    logger.warning(f"Invalid project_mode: {mode_str} (must be 'cdaq', 'crio', 'opto22', or 'cfp')")

            # Update watchdog output settings if provided
            if 'watchdog_output' in payload:
                wd = payload['watchdog_output']
                if isinstance(wd, dict):
                    self.config.system.watchdog_output_enabled = wd.get('enabled', False)
                    self.config.system.watchdog_output_channel = wd.get('channel', '')
                    self.config.system.watchdog_output_rate_hz = float(wd.get('rate_hz', 1.0))
                    logger.info(f"Watchdog output updated: enabled={self.config.system.watchdog_output_enabled}, "
                                f"channel={self.config.system.watchdog_output_channel}, "
                                f"rate={self.config.system.watchdog_output_rate_hz} Hz")

            # Update alarm flood detection parameters if provided
            if 'alarm_flood' in payload and self.alarm_manager:
                af = payload['alarm_flood']
                if isinstance(af, dict):
                    self.alarm_manager.configure_flood(
                        threshold=af.get('threshold', 10),
                        window_s=af.get('window_s', 60.0)
                    )

            # Update logging settings if provided
            if 'log_level' in payload:
                new_level = str(payload['log_level']).upper()
                if new_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
                    self.config.system.log_level = new_level
                    logging.getLogger().setLevel(new_level)
                    logger.info(f"Log level updated to {new_level}")
            if 'log_max_file_size_mb' in payload:
                self.config.system.log_max_file_size_mb = max(1, int(payload['log_max_file_size_mb']))
            if 'log_backup_count' in payload:
                self.config.system.log_backup_count = max(0, int(payload['log_backup_count']))

            # Update service timing settings if provided
            if 'service_heartbeat_interval_sec' in payload:
                self.config.system.service_heartbeat_interval_sec = max(0.5, float(payload['service_heartbeat_interval_sec']))
            if 'service_health_timeout_sec' in payload:
                self.config.system.service_health_timeout_sec = max(1.0, float(payload['service_health_timeout_sec']))
            if 'service_shutdown_timeout_sec' in payload:
                self.config.system.service_shutdown_timeout_sec = max(1.0, float(payload['service_shutdown_timeout_sec']))
            if 'service_command_ack_timeout_sec' in payload:
                self.config.system.service_command_ack_timeout_sec = max(1.0, float(payload['service_command_ack_timeout_sec']))

            # Update data viewer retention if provided
            if 'dataviewer_retention_days' in payload:
                self.config.system.dataviewer_retention_days = max(1, int(payload['dataviewer_retention_days']))

            # Publish status to reflect new settings
            self._publish_system_status()

            # Push updated config to all cRIO nodes (includes new rates)
            if self.config.system.project_mode == ProjectMode.CRIO:
                self._push_config_to_all_crios()

            # Send confirmation response
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/config/system/update/response",
                json.dumps({
                    "success": True,
                    "scan_rate_hz": self.config.system.scan_rate_hz,
                    "publish_rate_hz": self.config.system.publish_rate_hz,
                    "project_mode": self.config.system.project_mode.value,
                    "watchdog_output": {
                        "enabled": self.config.system.watchdog_output_enabled,
                        "channel": self.config.system.watchdog_output_channel,
                        "rate_hz": self.config.system.watchdog_output_rate_hz
                    },
                    "log_level": self.config.system.log_level,
                    "log_max_file_size_mb": self.config.system.log_max_file_size_mb,
                    "log_backup_count": self.config.system.log_backup_count,
                    "service_heartbeat_interval_sec": self.config.system.service_heartbeat_interval_sec,
                    "service_health_timeout_sec": self.config.system.service_health_timeout_sec,
                    "service_shutdown_timeout_sec": self.config.system.service_shutdown_timeout_sec,
                    "service_command_ack_timeout_sec": self.config.system.service_command_ack_timeout_sec,
                    "dataviewer_retention_days": self.config.system.dataviewer_retention_days,
                })
            )

            logger.info(f"System config updated - scan: {self.config.system.scan_rate_hz} Hz, publish: {self.config.system.publish_rate_hz} Hz, mode: {self.config.system.project_mode.value}")

        except Exception as e:
            logger.error(f"Failed to update system config: {e}")
            self._publish_config_response(False, f"System config update failed: {str(e)}")

    def _reinit_hardware_reader(self):
        """Reinitialize hardware reader with current in-memory config.

        This does NOT reload config from file - it uses self.config as-is.
        Preserves output state (DO/AO) across reinitialization.
        """
        # Preserve output values before closing old hardware reader
        preserved_output_values = {}
        if self.hardware_reader:
            preserved_output_values = dict(self.hardware_reader.output_values)
            logger.info(f"Preserving {len(preserved_output_values)} output values across reinit: {preserved_output_values}")
            try:
                self.hardware_reader.close()
            except Exception as e:
                logger.warning(f"Error closing hardware reader: {e}")
            self.hardware_reader = None

        # Clean up existing simulator
        if self.simulator:
            self.simulator = None

        # Reinitialize based on current config
        if self.config.system.simulation_mode:
            logger.info("Reinitializing simulator with current config")
            self.simulator = self._create_simulator()
        elif not HW_READER_AVAILABLE:
            logger.warning("nidaqmx not available - using simulator")
            self.simulator = self._create_simulator()
        else:
            logger.info("Reinitializing hardware reader with current config")
            try:
                # Restore preserved output values BEFORE creating hardware reader
                # so _create_digital_output_tasks can use them
                self.hardware_reader = HardwareReader(self.config, initial_output_values=preserved_output_values)
                logger.info("Hardware reader reinitialized successfully")
            except Exception as e:
                logger.error(f"Failed to reinitialize hardware reader: {e}")
                logger.warning("Falling back to simulator - check NI hardware connection")
                self.simulator = self._create_simulator()
                self._publish_config_response(True,
                    f"WARNING: NI hardware unavailable ({e}). Running in simulation mode.")

        # Reinitialize Modbus reader if configured
        self._init_modbus_reader()

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
            settings["system_mode"] = self._system_mode

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

    def _load_system_mode(self) -> str:
        """Load system mode from settings."""
        settings_path = self._get_settings_path()
        try:
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                mode = settings.get("system_mode", "standalone")
                if mode in ("standalone", "station"):
                    return mode
        except Exception as e:
            logger.warning(f"Could not load system mode: {e}")
        return "standalone"

    def _save_system_mode(self, mode: str):
        """Save system mode to settings."""
        settings_path = self._get_settings_path()
        try:
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
            settings["system_mode"] = mode
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save system mode: {e}")

    def _apply_saved_security_settings(self):
        """Load security settings from disk on startup and apply to runtime."""
        try:
            settings_path = self._get_settings_path()
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                sec = settings.get("security_settings", {})
                if sec and self.security_monitor:
                    self.security_monitor.enabled = sec.get('anomaly_detection_enabled', False)
                    self.security_monitor.max_command_rate = sec.get('anomaly_command_rate_limit', 200)
                    self.security_monitor.max_failed_logins = sec.get('anomaly_failed_login_rate_limit', 10)
                    logger.info(f"[SECURITY] Loaded settings: anomaly_detection={self.security_monitor.enabled}")
        except Exception as e:
            logger.warning(f"Could not load security settings: {e}")

    def _handle_security_settings(self, payload):
        """Handle security settings update from dashboard AdminTab."""
        if not isinstance(payload, dict):
            return
        settings_path = self._get_settings_path()
        try:
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
            settings["security_settings"] = payload
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
            logger.info(f"[SECURITY] Updated security settings: "
                        f"session_lock={payload.get('session_lock_enabled')}, "
                        f"guest_access={payload.get('guest_access_enabled')}, "
                        f"anomaly_detection={payload.get('anomaly_detection_enabled')}")
            # Apply to security monitor if present
            if self.security_monitor and payload.get('anomaly_detection_enabled') is not None:
                self.security_monitor.enabled = payload.get('anomaly_detection_enabled', False)
            # Apply to user session manager if present
            if hasattr(self, 'user_session') and self.user_session:
                max_sessions = payload.get('max_concurrent_sessions', 0)
                if max_sessions > 0:
                    self.user_session.max_concurrent_sessions = max_sessions
        except Exception as e:
            logger.warning(f"Could not save security settings: {e}")

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
        # IMPORTANT: Clear MQTT retained messages BEFORE clearing alarm manager
        self._publish_alarms_cleared(reason="no_project")
        if self.alarm_manager:
            self.alarm_manager.clear_all(clear_configs=True)

        # Clear safety interlocks (per-project)
        if self.safety_manager:
            self.safety_manager.clear_all()

        logger.info("No project configured - starting with empty state")

    def _clear_startup_state(self):
        """Clear all state on startup to provide clean slate for user

        User will choose via UI whether to load last project or start fresh.
        This prevents conflicts between old backend state and user's choice.

        Clears:
        - All channels (from INI config)
        - Channel values
        - Alarm configs and active alarms
        - Scripts/sequences/schedules
        - Current project reference
        """
        logger.info("Clearing startup state - awaiting user project choice...")

        # Clear current project reference
        self.current_project_path = None

        # Capture remote node IDs before clearing channels, then clear their
        # retained MQTT messages (no project loaded = all remote nodes are stale)
        if self.config and self.config.channels:
            self._previous_project_node_ids = {
                ch.source_node_id for ch in self.config.channels.values()
                if ch.source_node_id
            }
            self._clear_stale_node_retained_messages(set())

        # Clear all channels from config
        # Keep hardware settings (MQTT broker, device name, scan rate) but remove channels
        if self.config:
            logger.info(f"Clearing {len(self.config.channels)} channels from config")
            self.config.channels.clear()

        # Clear channel values
        self.channel_values.clear()

        # Clear alarm manager (configs and active alarms)
        if self.alarm_manager:
            logger.info("Clearing alarm manager")
            self.alarm_manager.clear_all(clear_configs=True)
            # Publish alarms cleared to MQTT
            self._publish_alarms_cleared(reason="startup_clean_slate")

        # Clear safety manager (interlocks and trip state)
        if self.safety_manager:
            logger.info("Clearing safety manager")
            self.safety_manager.clear_all()

        # Clear script manager
        if self.script_manager:
            logger.info("Clearing script manager")
            # Stop all running scripts first
            self.script_manager.stop_all_scripts()
            # Clear all scripts and runtimes
            self.script_manager.scripts.clear()
            self.script_manager.runtimes.clear()
            self.script_manager.clear_controlled_outputs()

        # Clear test session state - ensure session is inactive on startup
        if self.user_variables:
            logger.info("Clearing test session state")
            # Force session to inactive state
            with self.user_variables.lock:
                self.user_variables.session.active = False
                self.user_variables.session.started_at = None
                self.user_variables.session.started_by = None
            # Publish inactive session status
            self._publish_test_session_status()

        # Clear sequence manager
        if self.sequence_manager:
            logger.info("Clearing sequence manager")
            # Clear all sequences if method exists
            if hasattr(self.sequence_manager, 'sequences'):
                self.sequence_manager.sequences.clear()

        # Clear scheduler jobs if they exist
        if self.scheduler and hasattr(self.scheduler, 'jobs'):
            logger.info("Clearing scheduler jobs")
            for job_id in list(self.scheduler.jobs.keys()):
                self.scheduler.remove_job(job_id)

        # Publish empty channel configs to MQTT
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/config/channels",
            json.dumps({}),
            retain=True,
            qos=1
        )

        # Check for autosave file (crash recovery)
        # Publish status BEFORE startup-cleared so frontend has the info
        self._publish_autosave_status()

        # Publish startup cleared event to trigger frontend dialog
        # This tells frontend to show the "Load Last Project" or "Start Fresh" dialog
        self.mqtt_client.publish(
            f"{base}/system/startup-cleared",
            json.dumps({
                "cleared": True,
                "timestamp": datetime.now().isoformat(),
                "reason": "service_started"
            }),
            retain=False,  # Don't retain - only for current session
            qos=1
        )

        logger.info("✓ Startup state cleared - ready for user to load project or start fresh")

    def _handle_project_load_last(self):
        """Load the last used project from settings"""
        base = self.get_topic_base()

        # Try to load the last project path from settings
        last_path = self._load_last_project_path()

        if not last_path:
            logger.info("No last project found in settings")
            self.mqtt_client.publish(
                f"{base}/project/loaded",
                json.dumps({
                    "success": False,
                    "message": "No last project found"
                })
            )
            return

        if not last_path.exists():
            logger.warning(f"Last project file not found: {last_path}")
            # Clear invalid path from settings
            self._save_last_project_path(None)
            self.mqtt_client.publish(
                f"{base}/project/loaded",
                json.dumps({
                    "success": False,
                    "message": f"Last project file not found: {last_path.name}"
                })
            )
            return

        # Load the project
        logger.info(f"Loading last used project: {last_path}")
        self._load_project_from_path(last_path, publish=True)

    def _handle_project_list(self):
        """List available project files from default projects directory"""
        base = self.get_topic_base()
        projects_dir = self._get_projects_dir()

        projects = []
        current_name = self.current_project_path.name if self.current_project_path else None

        for f in projects_dir.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as fp:
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
            with open(project_path, 'r', encoding='utf-8') as f:
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
            if self.acquiring:
                if publish:
                    self._publish_project_response(False, "Stop acquisition before loading project")
                return False

            # Check for new format (embedded channels) vs legacy format (separate .ini)
            has_embedded_channels = "channels" in project_data and project_data["channels"]

            if has_embedded_channels:
                # New format: Apply channels and system settings from project JSON
                logger.info(f"Loading project with embedded config: {len(project_data['channels'])} channels")
                success, error_msg = self._apply_project_config(project_data)
                if not success:
                    if publish:
                        self._publish_project_response(False, f"Failed to apply project configuration: {error_msg}")
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
                    event_type=AuditEventType.PROJECT_LOADED,
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

            # Auto-push config to all known remote nodes after project load
            # This ensures nodes have the TAG name -> physical channel mappings
            self._push_config_to_all_crio_nodes()

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

    # =========================================================================
    # STATION MANAGEMENT — Multi-Project Concurrent Support
    # =========================================================================

    def _create_project_context(self, project_id: str, project_data: Dict[str, Any],
                                 project_path: Path) -> ProjectContext:
        """Create a ProjectContext with isolated manager instances for a project.

        This is the factory method that initializes all per-project managers
        (recording, alarms, safety, scripts, sequences, triggers, watchdog,
        variables, PID) with proper callback wiring.
        """
        # Parse config from project data
        sys_data = project_data.get("system", {})
        cur = self.config.system if self.config else SystemConfig()

        mode_str = sys_data.get("project_mode", "cdaq").lower()
        try:
            project_mode = ProjectMode(mode_str)
        except ValueError:
            project_mode = ProjectMode.CDAQ

        system = SystemConfig(
            mqtt_broker=sys_data.get("mqtt_broker", "localhost"),
            mqtt_port=int(sys_data.get("mqtt_port", 1883)),
            mqtt_base_topic=sys_data.get("mqtt_base_topic", "nisystem"),
            scan_rate_hz=min(float(sys_data.get("scan_rate_hz", 4)), 100.0),
            publish_rate_hz=min(float(sys_data.get("publish_rate_hz", 4)), 10.0),
            simulation_mode=sys_data.get("simulation_mode", False),
            log_directory=sys_data.get("log_directory", "./logs"),
            config_reload_topic=sys_data.get("config_reload_topic", "nisystem/config/reload"),
            project_mode=project_mode,
            node_id=cur.node_id,
            node_name=cur.node_name,
            default_project=cur.default_project,
            log_level=sys_data.get("log_level", cur.log_level),
            log_max_file_size_mb=int(sys_data.get("log_max_file_size_mb", cur.log_max_file_size_mb)),
            log_backup_count=int(sys_data.get("log_backup_count", cur.log_backup_count)),
            service_heartbeat_interval_sec=float(sys_data.get("service_heartbeat_interval_sec", cur.service_heartbeat_interval_sec)),
            service_health_timeout_sec=float(sys_data.get("service_health_timeout_sec", cur.service_health_timeout_sec)),
            service_shutdown_timeout_sec=float(sys_data.get("service_shutdown_timeout_sec", cur.service_shutdown_timeout_sec)),
            service_command_ack_timeout_sec=float(sys_data.get("service_command_ack_timeout_sec", cur.service_command_ack_timeout_sec)),
            dataviewer_retention_days=int(sys_data.get("dataviewer_retention_days", cur.dataviewer_retention_days)),
        )

        # Parse channels
        channels_data = project_data.get("channels", {})
        channels: Dict[str, ChannelConfig] = {}
        for name, ch_data in channels_data.items():
            ch_type_str = ch_data.get("channel_type", "voltage")
            channel_type = ChannelType(ch_type_str)
            tc_type = None
            if ch_data.get("thermocouple_type"):
                tc_type = ThermocoupleType(ch_data["thermocouple_type"])

            channels[name] = ChannelConfig(
                name=name,
                module=ch_data.get("module", ""),
                physical_channel=ch_data.get("physical_channel", ""),
                channel_type=channel_type,
                description=ch_data.get("description", ""),
                units=ch_data.get("units", ""),
                visible=ch_data.get("visible", True),
                group=ch_data.get("group", ""),
                scale_slope=float(ch_data.get("scale_slope", 1.0)),
                scale_offset=float(ch_data.get("scale_offset", 0.0)),
                scale_type=ch_data.get("scale_type", "none"),
                four_twenty_scaling=ch_data.get("four_twenty_scaling", False),
                eng_units_min=float(ch_data["eng_units_min"]) if ch_data.get("eng_units_min") is not None else None,
                eng_units_max=float(ch_data["eng_units_max"]) if ch_data.get("eng_units_max") is not None else None,
                pre_scaled_min=float(ch_data["pre_scaled_min"]) if ch_data.get("pre_scaled_min") is not None else None,
                pre_scaled_max=float(ch_data["pre_scaled_max"]) if ch_data.get("pre_scaled_max") is not None else None,
                scaled_min=float(ch_data["scaled_min"]) if ch_data.get("scaled_min") is not None else None,
                scaled_max=float(ch_data["scaled_max"]) if ch_data.get("scaled_max") is not None else None,
                voltage_range=float(ch_data.get("voltage_range", 10.0)),
                current_range_ma=float(ch_data.get("current_range_ma", 20.0)),
                terminal_config=ch_data.get("terminal_config", "differential"),
                thermocouple_type=tc_type,
                cjc_source=ch_data.get("cjc_source", "internal"),
                cjc_value=float(ch_data.get("cjc_value", 25.0)),
                rtd_type=ch_data.get("rtd_type", "Pt100"),
                rtd_resistance=float(ch_data.get("rtd_resistance", 100.0)),
                rtd_wiring=ch_data.get("rtd_wiring", ch_data.get("resistance_config", "4-wire")),
                rtd_current=float(ch_data.get("rtd_current", ch_data.get("excitation_current", 0.001))),
                invert=ch_data.get("invert", False),
                default_state=ch_data.get("default_state", False),
                default_value=float(ch_data.get("default_value", 0.0)),
                low_limit=float(ch_data["low_limit"]) if ch_data.get("low_limit") is not None else None,
                high_limit=float(ch_data["high_limit"]) if ch_data.get("high_limit") is not None else None,
                low_warning=float(ch_data["low_warning"]) if ch_data.get("low_warning") is not None else None,
                high_warning=float(ch_data["high_warning"]) if ch_data.get("high_warning") is not None else None,
                alarm_enabled=ch_data.get("alarm_enabled", False),
                hihi_limit=float(ch_data["hihi_limit"]) if ch_data.get("hihi_limit") is not None else None,
                hi_limit=float(ch_data["hi_limit"]) if ch_data.get("hi_limit") is not None else None,
                lo_limit=float(ch_data["lo_limit"]) if ch_data.get("lo_limit") is not None else None,
                lolo_limit=float(ch_data["lolo_limit"]) if ch_data.get("lolo_limit") is not None else None,
                alarm_priority=ch_data.get("alarm_priority", "medium"),
                alarm_deadband=float(ch_data.get("alarm_deadband", 1.0)),
                alarm_delay_sec=float(ch_data.get("alarm_delay_sec", 0.0)),
                digital_alarm_enabled=ch_data.get("digital_alarm_enabled", False),
                digital_expected_state=ch_data.get("digital_expected_state", "HIGH"),
                digital_debounce_ms=int(ch_data.get("digital_debounce_ms", 100)),
                digital_invert=ch_data.get("digital_invert", False),
                safety_action=ch_data.get("safety_action"),
                safety_interlock=ch_data.get("safety_interlock"),
                log=ch_data.get("log", True),
                log_interval_ms=int(ch_data.get("log_interval_ms", 1000)),
                source_type=ch_data.get("source_type", "local"),
                source_node_id=ch_data.get("source_node_id") or ch_data.get("node_id", "")
            )

        config = NISystemConfig(
            system=system,
            dataviewer=self.config.dataviewer if self.config else DataViewerConfig(),
            chassis=self.config.chassis if self.config else {},
            modules=self.config.modules if self.config else {},
            channels=channels,
            safety_actions=self.config.safety_actions if self.config else {}
        )

        # Assign color
        color_index = self._next_color_index % 8
        self._next_color_index += 1

        # Create the context
        ctx = ProjectContext(
            project_id=project_id,
            project_path=project_path,
            project_data=project_data,
            project_name=project_data.get('name', project_id),
            color_index=color_index,
            config=config,
        )

        # Data directory for this project
        data_dir = Path(getattr(config.system, 'data_directory', 'data')) / project_id

        # Initialize per-project managers with callback closures
        # Each closure captures ctx to scope data access to this project

        # Recording manager — separate directory per project
        recording_dir = Path(config.system.log_directory) / project_id
        recording_dir.mkdir(parents=True, exist_ok=True)
        ctx.recording_manager = RecordingManager(default_path=str(recording_dir))
        ctx.recording_manager.on_status_change = lambda: self._publish_project_status(project_id)

        # Alarm manager
        project_data_dir = data_dir / 'alarms'
        project_data_dir.mkdir(parents=True, exist_ok=True)
        ctx.alarm_manager = AlarmManager(
            data_dir=project_data_dir,
            publish_callback=lambda topic, payload, **kw: self._publish_project_mqtt(project_id, f"alarms/{topic}", payload, **kw)
        )
        # Auto-create alarm configs from channel limits
        for ch_name, ch_config in channels.items():
            alarm_configs = self._build_alarm_configs_for_channel(ch_config)
            for ac in alarm_configs:
                ctx.alarm_manager.add_alarm_config(ac)

        # Sequence manager
        ctx.sequence_manager = SequenceManager()
        ctx.sequence_manager.on_set_output = lambda ch, val: self._project_set_output(project_id, ch, val)
        ctx.sequence_manager.on_start_recording = lambda: ctx.recording_manager.start() if ctx.recording_manager else None
        ctx.sequence_manager.on_stop_recording = lambda: ctx.recording_manager.stop() if ctx.recording_manager else None
        ctx.sequence_manager.on_publish = lambda topic, payload: self._publish_project_mqtt(project_id, topic, payload)

        # Script manager
        script_data_dir = data_dir / 'scripts'
        script_data_dir.mkdir(parents=True, exist_ok=True)
        ctx.script_manager = ScriptManager(data_dir=script_data_dir)
        ctx.script_manager.on_get_channel_value = lambda ch: ctx.channel_values.get(ch)
        ctx.script_manager.on_get_channel_timestamp = lambda ch: ctx.channel_timestamps.get(ch, 0.0)
        ctx.script_manager.on_get_channel_names = lambda: list(ctx.channel_names)
        ctx.script_manager.on_set_output = lambda ch, val: self._project_set_output(project_id, ch, val)

        # Trigger engine
        ctx.trigger_engine = TriggerEngine()
        ctx.trigger_engine.set_output = lambda ch, val: self._project_set_output(project_id, ch, val)

        # Watchdog engine
        ctx.watchdog_engine = WatchdogEngine()
        ctx.watchdog_engine.set_output = lambda ch, val: self._project_set_output(project_id, ch, val)

        # User variable manager
        var_data_dir = data_dir / 'variables'
        var_data_dir.mkdir(parents=True, exist_ok=True)
        ctx.user_variables = UserVariableManager(data_dir=str(var_data_dir))

        # Safety manager
        safety_data_dir = data_dir / 'safety'
        safety_data_dir.mkdir(parents=True, exist_ok=True)

        def ctx_get_channel_value(channel: str) -> Optional[float]:
            val = ctx.channel_values.get(channel)
            if val is None:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        ctx.safety_manager = SafetyManager(
            data_dir=safety_data_dir,
            get_channel_value=ctx_get_channel_value,
            get_channel_type=lambda ch: str(channels[ch].channel_type.value) if ch in channels else None,
            get_all_channels=lambda: {n: {'name': n, 'channel_type': c.channel_type.value} for n, c in channels.items()},
            publish_callback=lambda topic, payload, **kw: self._publish_project_mqtt(project_id, f"safety/{topic}", payload, **kw),
            set_output_callback=lambda ch, val: self._project_set_output(project_id, ch, val),
            stop_session_callback=lambda: self._project_stop_acquisition(project_id),
            get_system_state=lambda: {'status': 'online' if self.running else 'offline', 'acquiring': ctx.acquiring, 'recording': ctx.recording},
            get_alarm_state=lambda: {'active_count': len(ctx.alarms_active), 'alarms': dict(ctx.alarms_active)},
            trigger_safe_state_callback=lambda reason: self._forward_safe_state_to_crio(reason)
        )
        ctx.safety_manager.node_id = getattr(config.system, 'node_id', 'node-001')

        # PID engine
        try:
            ctx.pid_engine = PIDEngine(
                on_set_output=lambda ch, val: self._project_set_output(project_id, ch, val)
            )
            ctx.pid_engine.set_status_callback(
                lambda loop_id, status: self._publish_project_mqtt(project_id, f"pid/loop/{loop_id}/status", json.dumps(status))
            )
        except Exception as e:
            logger.error(f"Failed to init PID engine for {project_id}: {e}")
            ctx.pid_engine = None

        # Load project-specific data into managers
        self._load_project_data_into_context(ctx, project_data)

        # Initialize channel values
        for name, channel in channels.items():
            if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                ctx.channel_values[name] = channel.default_state
            elif channel.channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT):
                ctx.channel_values[name] = channel.default_value
            else:
                ctx.channel_values[name] = 0.0

        logger.info(f"Created project context '{project_id}': {len(channels)} channels, color={color_index}")
        return ctx

    def _load_project_data_into_context(self, ctx: ProjectContext, project_data: Dict[str, Any]):
        """Load scripts, alarms, interlocks, triggers, etc. from project JSON into context managers."""
        # Safety interlocks
        if ctx.safety_manager:
            interlocks_data = project_data.get('interlocks', [])
            for interlock_data in interlocks_data:
                interlock = Interlock.from_dict(interlock_data)
                ctx.safety_manager.add_interlock(interlock, 'project_load')
            safe_state_data = project_data.get('safeStateConfig')
            if safe_state_data:
                ctx.safety_manager.update_safe_state_config(safe_state_data)

        # Scripts
        if ctx.script_manager:
            ctx.script_manager.load_scripts_from_project(project_data)

        # User variables
        if ctx.user_variables:
            ctx.user_variables.load_variables_from_project(project_data)
            channel_names = list(ctx.channel_names)
            ctx.user_variables.load_formulas_from_project(project_data, channel_names)

        # Triggers
        if ctx.trigger_engine:
            ctx.trigger_engine.load_from_project(project_data)

        # Watchdogs
        if ctx.watchdog_engine:
            ctx.watchdog_engine.load_from_project(project_data)

        # PID loops
        if ctx.pid_engine:
            pid_data = project_data.get('pidLoops', {})
            if pid_data:
                ctx.pid_engine.load_config(pid_data)

        # Alarm flood detection
        safety_data = project_data.get('safety', {})
        flood_cfg = safety_data.get('alarmFlood')
        if flood_cfg and isinstance(flood_cfg, dict) and ctx.alarm_manager:
            ctx.alarm_manager.configure_flood(
                threshold=flood_cfg.get('threshold', 10),
                window_s=flood_cfg.get('window_s', 60.0)
            )

    def _build_alarm_configs_for_channel(self, ch: ChannelConfig) -> list:
        """Build alarm configs from a channel's ISA-18.2 limits. Returns list of AlarmConfig."""
        configs = []
        if not ch.alarm_enabled:
            return configs

        name = ch.name
        # Check ISA-18.2 limits
        if ch.hihi_limit is not None:
            configs.append(AlarmConfig(
                id=f"alarm-{name}-hihi", channel=name, severity=AlarmSeverity.CRITICAL,
                setpoint=ch.hihi_limit, comparison='>', deadband=ch.alarm_deadband,
                delay_sec=ch.alarm_delay_sec, priority=ch.alarm_priority,
                description=f"HiHi alarm on {name}"
            ))
        if ch.hi_limit is not None:
            configs.append(AlarmConfig(
                id=f"alarm-{name}-hi", channel=name, severity=AlarmSeverity.HIGH,
                setpoint=ch.hi_limit, comparison='>', deadband=ch.alarm_deadband,
                delay_sec=ch.alarm_delay_sec, priority=ch.alarm_priority,
                description=f"Hi alarm on {name}"
            ))
        if ch.lo_limit is not None:
            configs.append(AlarmConfig(
                id=f"alarm-{name}-lo", channel=name, severity=AlarmSeverity.LOW,
                setpoint=ch.lo_limit, comparison='<', deadband=ch.alarm_deadband,
                delay_sec=ch.alarm_delay_sec, priority=ch.alarm_priority,
                description=f"Lo alarm on {name}"
            ))
        if ch.lolo_limit is not None:
            configs.append(AlarmConfig(
                id=f"alarm-{name}-lolo", channel=name, severity=AlarmSeverity.CRITICAL,
                setpoint=ch.lolo_limit, comparison='<', deadband=ch.alarm_deadband,
                delay_sec=ch.alarm_delay_sec, priority=ch.alarm_priority,
                description=f"LoLo alarm on {name}"
            ))
        return configs

    def _detect_channel_conflicts(self) -> Dict[str, list]:
        """Detect physical channel conflicts across all loaded projects.

        Returns:
            Dict mapping physical_channel -> list of project_ids that claim it
        """
        physical_map: Dict[str, list] = {}  # physical_channel -> [project_ids]
        for pid, ctx in self.active_projects.items():
            if not ctx.config or not ctx.config.channels:
                continue
            for ch_name, ch in ctx.config.channels.items():
                phys = getattr(ch, 'physical_channel', None)
                if phys:
                    if phys not in physical_map:
                        physical_map[phys] = []
                    physical_map[phys].append(pid)

        # Filter to only conflicts (2+ projects on same channel)
        return {phys: pids for phys, pids in physical_map.items() if len(pids) > 1}

    def _estimate_station_scan_budget(self, channels: Dict[str, 'ChannelConfig']) -> Dict[str, Any]:
        """Estimate whether a channel set can be read within the 500ms scan budget.

        Returns a dict with:
          - feasible: bool — whether the channel set fits within budget
          - channel_count: int — total channels
          - module_count: int — distinct NI modules involved
          - estimated_ms: float — estimated per-scan read time
          - budget_ms: float — maximum allowed (500ms)
          - details: str — human-readable summary
        """
        BUDGET_MS = 500.0

        # Group channels by module (physical_channel prefix before '/')
        modules: Dict[str, int] = {}
        remote_count = 0
        sim_count = 0
        for name, ch in channels.items():
            source = getattr(ch, 'hardware_source', None)
            if source and str(source).lower() in ('crio', 'opto22', 'cfp', 'modbus', 'opcua', 'rest', 'ethernetip'):
                remote_count += 1
                continue
            phys = getattr(ch, 'physical_channel', None) or ''
            if not phys:
                sim_count += 1
                continue
            # Module = everything before the last '/' (e.g., "cDAQ1Mod1/ai0" → "cDAQ1Mod1")
            module = phys.rsplit('/', 1)[0] if '/' in phys else phys
            modules[module] = modules.get(module, 0) + 1

        total_hw = sum(modules.values())
        module_count = len(modules)

        # Timing estimates (conservative, based on NI-DAQmx characteristics):
        # - Each module's continuous task has ~2ms overhead per read_all call
        # - Each analog channel adds ~0.1ms of conversion/scaling
        # - DI tasks are fast (~0.5ms each)
        # - Counter tasks add ~1ms each
        # - Safety/alarm/PID processing adds ~1ms per project
        # Remote and simulated channels are essentially free (no hardware read)
        estimated_ms = (
            module_count * 2.0 +      # Per-module task read overhead
            total_hw * 0.1 +           # Per-channel conversion
            len(self.active_projects) * 1.0  # Per-project engine processing
        )

        feasible = estimated_ms < BUDGET_MS
        details = (
            f"{total_hw} hardware channels across {module_count} modules, "
            f"{remote_count} remote, {sim_count} simulated — "
            f"estimated {estimated_ms:.1f}ms per scan (budget: {BUDGET_MS:.0f}ms)"
        )

        return {
            'feasible': feasible,
            'channel_count': len(channels),
            'hw_channel_count': total_hw,
            'module_count': module_count,
            'remote_count': remote_count,
            'simulated_count': sim_count,
            'estimated_ms': round(estimated_ms, 1),
            'budget_ms': BUDGET_MS,
            'details': details,
        }

    def _get_station_union_channels(self) -> Dict[str, 'ChannelConfig']:
        """Get the union of ALL loaded project channels (not just acquiring ones).

        In station mode, the hardware reader is created once with all channels
        from all loaded projects, so any project can start acquisition
        without rebuilding the reader.
        """
        all_channels: Dict[str, 'ChannelConfig'] = {}
        for ctx in self.active_projects.values():
            if ctx.config and ctx.config.channels:
                all_channels.update(ctx.config.channels)
        return all_channels

    MAX_STATION_PROJECTS = 3

    def _handle_station_load(self, payload: Any):
        """Load a project into the station for concurrent multi-project operation."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            # Guard: must be in station mode
            if self._system_mode != 'station':
                self._publish_station_response(
                    False,
                    "Cannot load projects in standalone mode. "
                    "Switch to station mode first (system/mode → station)."
                )
                return

            # Guard: hard limit of 3 station projects
            if len(self.active_projects) >= self.MAX_STATION_PROJECTS:
                self._publish_station_response(
                    False,
                    f"Station limit reached ({self.MAX_STATION_PROJECTS} projects maximum). "
                    f"Unload a project before loading another."
                )
                return

            # Guard: no loading while any project is acquiring
            acquiring_projects = [pid for pid, ctx in self.active_projects.items() if ctx.acquiring]
            if acquiring_projects:
                self._publish_station_response(
                    False,
                    f"Cannot load projects while acquisition is running. "
                    f"Stop acquisition on {', '.join(acquiring_projects)} first."
                )
                return

            filename = payload.get('filename', '')
            abs_path = payload.get('path', '')
            project_id = payload.get('projectId', '')

            if abs_path:
                project_path = Path(abs_path)
            elif filename:
                if self.projects_dir:
                    project_path = self.projects_dir / filename
                else:
                    project_path = Path('config/projects') / filename
            else:
                self._publish_station_response(False, "Missing 'filename' or 'path' in payload")
                return

            if not project_path.exists():
                self._publish_station_response(False, f"Project not found: {project_path}")
                return

            # Read project JSON
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)

            if project_data.get("type") != "nisystem-project":
                self._publish_station_response(False, "Invalid project format")
                return

            # Auto-generate project_id from filename if not provided
            if not project_id:
                project_id = project_path.stem.lower().replace(' ', '_').replace('-', '_')

            # Check if already loaded
            if project_id in self.active_projects:
                self._publish_station_response(False, f"Project '{project_id}' is already loaded")
                return

            # Create project context
            ctx = self._create_project_context(project_id, project_data, project_path)
            self.active_projects[project_id] = ctx

            # Detect and log channel conflicts
            conflicts = self._detect_channel_conflicts()
            if conflicts:
                conflict_msg = "; ".join(f"{phys}: {pids}" for phys, pids in conflicts.items())
                logger.warning(f"Channel conflicts detected: {conflict_msg}")

            # Check scan budget for the full union of loaded project channels
            union_channels = self._get_station_union_channels()
            budget = self._estimate_station_scan_budget(union_channels)
            if not budget['feasible']:
                logger.warning(f"[STATION] Scan budget exceeded: {budget['details']}")

            # Publish success
            self.mqtt_client.publish(
                f"{base}/station/loaded",
                json.dumps({
                    "success": True,
                    "projectId": project_id,
                    "projectName": ctx.project_name,
                    "channelCount": len(ctx.channel_names),
                    "conflicts": {phys: pids for phys, pids in conflicts.items()},
                    "colorIndex": ctx.color_index,
                    "scanBudget": budget,
                })
            )

            # Publish updated station status
            self._publish_station_status()

            # Save station state for persistence
            self._save_station_state()

            logger.info(f"Loaded project '{project_id}' into station ({len(ctx.channel_names)} channels)")

        except Exception as e:
            logger.error(f"Error loading project into station: {e}")
            import traceback
            traceback.print_exc()
            self._publish_station_response(False, str(e))

    def _handle_station_unload(self, payload: Any):
        """Unload a project from the station."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            # Guard: must be in station mode
            if self._system_mode != 'station':
                self._publish_station_response(
                    False, "Cannot unload projects in standalone mode."
                )
                return

            project_id = payload.get('projectId', '')
            if not project_id:
                self._publish_station_response(False, "Missing 'projectId'")
                return

            if project_id not in self.active_projects:
                self._publish_station_response(False, f"Project '{project_id}' not loaded")
                return

            ctx = self.active_projects[project_id]

            # Stop acquisition if running
            if ctx.acquiring:
                self._project_stop_acquisition(project_id)

            # Teardown managers
            ctx.teardown()

            # Remove from active projects
            del self.active_projects[project_id]

            self.mqtt_client.publish(
                f"{base}/station/unloaded",
                json.dumps({"success": True, "projectId": project_id})
            )

            self._publish_station_status()
            self._save_station_state()

            logger.info(f"Unloaded project '{project_id}' from station")

        except Exception as e:
            logger.error(f"Error unloading project from station: {e}")
            self._publish_station_response(False, str(e))

    def _handle_station_list(self, payload: Any = None):
        """Publish list of loaded projects in the station."""
        self._publish_station_status()

    def _publish_station_status(self):
        """Publish station status with all loaded projects."""
        base = self.get_topic_base()
        projects = []
        conflicts = self._detect_channel_conflicts()

        for pid, ctx in self.active_projects.items():
            summary = ctx.to_summary()
            # Enrich with cross-project conflict info
            project_conflicts = {}
            for phys, pids in conflicts.items():
                if pid in pids:
                    project_conflicts[phys] = [p for p in pids if p != pid]
            summary['channelConflicts'] = project_conflicts
            projects.append(summary)

        self.mqtt_client.publish(
            f"{base}/station/status",
            json.dumps({
                "projects": projects,
                "totalChannels": sum(len(ctx.channel_names) for ctx in self.active_projects.values()),
                "conflicts": conflicts,
            }),
            retain=True
        )

    def _handle_mode_switch(self, payload: Any):
        """Switch between standalone and station mode."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            mode = payload.get('mode', '')
            if mode not in ('standalone', 'station'):
                self.mqtt_client.publish(
                    f"{base}/system/mode/response",
                    json.dumps({"success": False, "message": f"Invalid mode: {mode}"})
                )
                return

            old_mode = self._system_mode
            self._system_mode = mode
            self._save_system_mode(mode)

            if old_mode == 'station' and mode == 'standalone':
                # Switching to standalone — unload all station projects
                for pid in list(self.active_projects.keys()):
                    ctx = self.active_projects[pid]
                    if ctx.acquiring:
                        self._project_stop_acquisition(pid)
                    ctx.teardown()
                    del self.active_projects[pid]
                self._save_station_state()
                logger.info("Switched to standalone mode — all station projects unloaded")

            elif old_mode == 'standalone' and mode == 'station':
                # Switching to station mode — restore station state if any
                self._restore_station_state()
                logger.info("Switched to station mode")

            self.mqtt_client.publish(
                f"{base}/system/mode/response",
                json.dumps({"success": True, "mode": mode, "previousMode": old_mode})
            )

            # Re-publish system status with updated mode
            self._publish_system_status()

        except Exception as e:
            logger.error(f"Error switching system mode: {e}")
            self.mqtt_client.publish(
                f"{base}/system/mode/response",
                json.dumps({"success": False, "message": str(e)})
            )

    def _publish_station_response(self, success: bool, message: str):
        """Publish station command response."""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/station/response",
            json.dumps({"success": success, "message": message})
        )

    def _handle_station_config_save(self, payload: Any):
        """Save current loaded projects as a station configuration preset."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            name = payload.get('name', '').strip()
            if not name:
                self.mqtt_client.publish(
                    f"{base}/station/config/save/response",
                    json.dumps({"success": False, "message": "Missing 'name'"})
                )
                return

            if not self.active_projects:
                self.mqtt_client.publish(
                    f"{base}/station/config/save/response",
                    json.dumps({"success": False, "message": "No projects loaded to save"})
                )
                return

            # Build config
            config = {
                "name": name,
                "created": datetime.now().isoformat(),
                "modified": datetime.now().isoformat(),
                "projects": [
                    {
                        "project_id": pid,
                        "path": str(ctx.project_path),
                        "color_index": ctx.color_index,
                    }
                    for pid, ctx in self.active_projects.items()
                ]
            }

            # Save to config/stations/
            self._station_configs_dir.mkdir(parents=True, exist_ok=True)
            safe_name = name.lower().replace(' ', '_').replace('-', '_')
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            config_path = self._station_configs_dir / f"{safe_name}.json"

            # If file exists, preserve created timestamp
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                    config["created"] = existing.get("created", config["created"])
                except Exception:
                    pass

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            self.mqtt_client.publish(
                f"{base}/station/config/save/response",
                json.dumps({
                    "success": True,
                    "name": name,
                    "filename": config_path.name,
                    "projectCount": len(config["projects"]),
                })
            )
            logger.info(f"Saved station config '{name}' with {len(config['projects'])} projects")

        except Exception as e:
            logger.error(f"Error saving station config: {e}")
            self.mqtt_client.publish(
                f"{base}/station/config/save/response",
                json.dumps({"success": False, "message": str(e)})
            )

    def _handle_station_config_load(self, payload: Any):
        """Load a station configuration preset — loads all projects from the config."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            # Guard: must be in station mode
            if self._system_mode != 'station':
                self.mqtt_client.publish(
                    f"{base}/station/config/load/response",
                    json.dumps({
                        "success": False,
                        "message": "Cannot load station config in standalone mode."
                    })
                )
                return

            # Guard: no loading while any project is acquiring
            acquiring_projects = [pid for pid, ctx in self.active_projects.items() if ctx.acquiring]
            if acquiring_projects:
                self.mqtt_client.publish(
                    f"{base}/station/config/load/response",
                    json.dumps({
                        "success": False,
                        "message": f"Cannot load station config while acquisition is running. "
                                   f"Stop acquisition on {', '.join(acquiring_projects)} first."
                    })
                )
                return

            config_filename = payload.get('filename', '')
            if not config_filename:
                self.mqtt_client.publish(
                    f"{base}/station/config/load/response",
                    json.dumps({"success": False, "message": "Missing 'filename'"})
                )
                return

            config_path = self._station_configs_dir / config_filename
            if not config_path.exists():
                self.mqtt_client.publish(
                    f"{base}/station/config/load/response",
                    json.dumps({"success": False, "message": f"Station config not found: {config_filename}"})
                )
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Enforce 3-project limit
            projects_in_config = config.get('projects', [])
            already_loaded = sum(1 for p in projects_in_config if p.get('project_id') in self.active_projects)
            new_to_load = len(projects_in_config) - already_loaded
            available_slots = self.MAX_STATION_PROJECTS - len(self.active_projects)
            if new_to_load > available_slots:
                self.mqtt_client.publish(
                    f"{base}/station/config/load/response",
                    json.dumps({
                        "success": False,
                        "message": f"Config has {new_to_load} new projects but only {available_slots} "
                                   f"slot(s) available (max {self.MAX_STATION_PROJECTS})."
                    })
                )
                return

            loaded = []
            errors = []

            for entry in projects_in_config:
                project_path = Path(entry['path'])
                project_id = entry.get('project_id', '')

                if project_id in self.active_projects:
                    loaded.append(project_id)  # Already loaded, skip
                    continue

                if not project_path.exists():
                    errors.append(f"{project_id}: file not found ({project_path})")
                    continue

                try:
                    with open(project_path, 'r', encoding='utf-8') as pf:
                        project_data = json.load(pf)

                    if not project_id:
                        project_id = project_path.stem.lower().replace(' ', '_').replace('-', '_')

                    ctx = self._create_project_context(project_id, project_data, project_path)
                    ctx.color_index = entry.get('color_index', ctx.color_index)
                    self.active_projects[project_id] = ctx
                    loaded.append(project_id)
                except Exception as e:
                    errors.append(f"{project_id}: {e}")

            self._save_station_state()
            self._publish_station_status()

            self.mqtt_client.publish(
                f"{base}/station/config/load/response",
                json.dumps({
                    "success": True,
                    "configName": config.get('name', config_filename),
                    "loaded": loaded,
                    "errors": errors,
                })
            )
            logger.info(f"Loaded station config '{config.get('name')}': {len(loaded)} projects, {len(errors)} errors")

        except Exception as e:
            logger.error(f"Error loading station config: {e}")
            self.mqtt_client.publish(
                f"{base}/station/config/load/response",
                json.dumps({"success": False, "message": str(e)})
            )

    def _handle_station_config_list(self, payload: Any = None):
        """List all saved station configuration presets."""
        base = self.get_topic_base()
        configs = []

        if self._station_configs_dir.exists():
            for config_path in sorted(self._station_configs_dir.glob('*.json')):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    configs.append({
                        "filename": config_path.name,
                        "name": config.get("name", config_path.stem),
                        "projectCount": len(config.get("projects", [])),
                        "projects": [
                            {"project_id": p.get("project_id", ""), "path": p.get("path", "")}
                            for p in config.get("projects", [])
                        ],
                        "created": config.get("created", ""),
                        "modified": config.get("modified", ""),
                    })
                except Exception as e:
                    logger.debug(f"Error reading station config {config_path}: {e}")

        self.mqtt_client.publish(
            f"{base}/station/config/list/response",
            json.dumps({"configs": configs})
        )

    def _handle_station_config_delete(self, payload: Any):
        """Delete a saved station configuration preset."""
        base = self.get_topic_base()
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            config_filename = payload.get('filename', '')
            if not config_filename:
                self.mqtt_client.publish(
                    f"{base}/station/config/delete/response",
                    json.dumps({"success": False, "message": "Missing 'filename'"})
                )
                return

            config_path = self._station_configs_dir / config_filename
            if not config_path.exists():
                self.mqtt_client.publish(
                    f"{base}/station/config/delete/response",
                    json.dumps({"success": False, "message": f"Config not found: {config_filename}"})
                )
                return

            config_path.unlink()
            self.mqtt_client.publish(
                f"{base}/station/config/delete/response",
                json.dumps({"success": True, "filename": config_filename})
            )
            logger.info(f"Deleted station config: {config_filename}")

        except Exception as e:
            logger.error(f"Error deleting station config: {e}")
            self.mqtt_client.publish(
                f"{base}/station/config/delete/response",
                json.dumps({"success": False, "message": str(e)})
            )

    def _publish_project_mqtt(self, project_id: str, subtopic: str, payload: Any, **kwargs):
        """Publish MQTT message under a project's namespace."""
        base = self.get_topic_base()
        topic = f"{base}/projects/{project_id}/{subtopic}"
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        retain = kwargs.get('retain', False)
        qos = kwargs.get('qos', 0)
        self.mqtt_client.publish(topic, payload, qos=qos, retain=retain)

    def _publish_project_status(self, project_id: str):
        """Publish status for a specific project."""
        if project_id not in self.active_projects:
            return
        ctx = self.active_projects[project_id]
        self._publish_project_mqtt(project_id, "status", ctx.to_summary())

    def _project_set_output(self, project_id: str, channel: str, value: Any):
        """Set an output value scoped to a project. Validates channel ownership."""
        if project_id not in self.active_projects:
            logger.warning(f"Output set for unknown project '{project_id}'")
            return
        ctx = self.active_projects[project_id]
        if channel not in ctx.channel_names:
            logger.warning(f"Output set denied: channel '{channel}' not in project '{project_id}'")
            return
        # Delegate to the existing output handler
        self._handle_output_set({
            'channel': channel,
            'value': value,
            'source': f'project:{project_id}'
        })

    def _project_start_acquisition(self, project_id: str):
        """Start acquisition for a specific project.

        If the global scan loop is not running, it starts with the union of ALL
        loaded project channels (read-all-upfront). If already running, this
        project's channels must already be in the reader — no rebuild occurs.
        """
        if project_id not in self.active_projects:
            logger.warning(f"Start acquisition for unknown project '{project_id}'")
            return
        ctx = self.active_projects[project_id]
        if ctx.acquiring:
            logger.info(f"Project '{project_id}' already acquiring")
            return

        # If scan loop is already running, check channel coverage
        uncovered: list = []
        if self.acquiring and self.hardware_reader and ctx.config:
            reader_channels = set()
            if hasattr(self.hardware_reader, 'channel_names'):
                reader_channels = set(self.hardware_reader.channel_names)
            elif hasattr(self.hardware_reader, 'latest_values'):
                reader_channels = set(self.hardware_reader.latest_values.keys())
            for ch_name in ctx.channel_names:
                ch_cfg = ctx.config.channels.get(ch_name)
                if ch_cfg and getattr(ch_cfg, 'physical_channel', None):
                    if ch_name not in reader_channels:
                        uncovered.append(ch_name)
            if uncovered:
                logger.warning(
                    f"[STATION] Project '{project_id}' has {len(uncovered)} hardware channels "
                    f"not in the running reader (loaded after acquisition started). "
                    f"These channels will read as NaN. Stop all projects and restart "
                    f"to include them. Uncovered: {uncovered[:5]}"
                )
                # Publish warning but still allow start — soft warning, not hard block
                self._publish_project_mqtt(project_id, "status/warning", json.dumps({
                    "type": "uncovered_channels",
                    "message": f"{len(uncovered)} hardware channels not in reader — stop all and restart to include",
                    "channels": uncovered[:10],
                }))

        ctx.state_machine.to(DAQState.RUNNING)
        logger.info(f"Started acquisition for project '{project_id}'"
                     + (f" ({len(uncovered)} uncovered channels)" if uncovered else ""))
        self._publish_project_mqtt(project_id, "status/acquisition", json.dumps({
            "state": "running", "projectId": project_id,
            "uncoveredChannels": uncovered[:10] if uncovered else [],
        }))

        # Ensure the global scan loop is running (shared hardware reader)
        if not self.acquiring:
            # Start the main scan loop with ALL loaded project channels
            self._start_scan_loop_for_station()

        self._publish_station_status()

    def _project_stop_acquisition(self, project_id: str):
        """Stop acquisition for a specific project."""
        if project_id not in self.active_projects:
            return
        ctx = self.active_projects[project_id]
        if not ctx.acquiring:
            return

        # Stop recording if active
        if ctx.recording and ctx.recording_manager:
            ctx.recording_manager.stop()

        # Stop scripts
        if ctx.script_manager:
            ctx.script_manager.stop_all_scripts()

        ctx.state_machine.to(DAQState.STOPPED)
        logger.info(f"Stopped acquisition for project '{project_id}'")
        self._publish_project_mqtt(project_id, "status/acquisition", json.dumps({
            "state": "stopped", "projectId": project_id
        }))

        # Check if any projects still acquiring
        any_acquiring = any(c.acquiring for c in self.active_projects.values())
        if not any_acquiring:
            # Stop the global scan loop if no projects need it
            self._stop_scan_loop_for_station()

        self._publish_station_status()

    def _start_scan_loop_for_station(self):
        """Ensure the global scan loop is running for multi-project station operation.

        Station mode design:
        - The hardware reader is created ONCE with the union of ALL loaded project
          channels (not just currently acquiring ones). This means any project can
          start/stop acquisition without rebuilding the reader or interrupting
          other projects' scan rates.
        - The dispatch step filters the shared value pool to each project's channels.
        - If a new project is loaded while acquisition is running and it has channels
          not in the reader, those channels won't produce data until all projects
          stop and the reader is rebuilt on next start.
        """
        # Use union of ALL loaded projects' channels (not just acquiring)
        # so the reader covers everything upfront — no rebuilds needed
        all_channels = self._get_station_union_channels()

        if not all_channels:
            return

        # Validate scan budget before starting
        budget = self._estimate_station_scan_budget(all_channels)
        logger.info(f"[STATION] Scan budget: {budget['details']}")
        if not budget['feasible']:
            logger.warning(
                f"[STATION] Channel set may exceed 500ms scan budget "
                f"({budget['estimated_ms']}ms estimated). "
                f"Consider reducing channel count or splitting across systems."
            )

        # Update the shared config with ALL loaded channels for hardware reader
        if self.config:
            self.config.channels = all_channels

        # Determine simulation mode from station projects (any project with
        # simulation_mode=True forces simulator for the whole station)
        station_sim_mode = any(
            ctx.project_data.get('system', {}).get('simulation_mode', False)
            for ctx in self.active_projects.values()
        )
        # Also respect global config
        use_simulation = station_sim_mode or self.config.system.simulation_mode

        # Create or rebuild hardware reader for station channel set.
        # Station mode may load different channels than standalone mode,
        # so we must rebuild if the existing reader has different channels.
        needs_rebuild = False
        if self.hardware_reader and not use_simulation:
            reader_channels = set()
            if hasattr(self.hardware_reader, 'channel_names'):
                reader_channels = set(self.hardware_reader.channel_names)
            elif hasattr(self.hardware_reader, 'latest_values'):
                reader_channels = set(self.hardware_reader.latest_values.keys())
            station_channels = set(all_channels.keys())
            if not station_channels.issubset(reader_channels):
                needs_rebuild = True
                logger.info(f"[STATION] Rebuilding hardware reader: "
                            f"station needs {len(station_channels)} channels, "
                            f"reader has {len(reader_channels)}")
        if self.simulator and not use_simulation:
            needs_rebuild = True  # Was using simulator but station wants real hardware
        if not self.simulator and use_simulation:
            needs_rebuild = True  # Station wants simulator but we have hardware reader
        # Check if existing simulator has wrong channels (e.g. leftover from standalone mode)
        if self.simulator and use_simulation and not needs_rebuild:
            sim_channels = set(self.simulator.channel_simulators.keys())
            station_channels = set(all_channels.keys())
            if not station_channels.issubset(sim_channels):
                needs_rebuild = True
                logger.info(f"[STATION] Rebuilding simulator: "
                            f"station needs {len(station_channels)} channels, "
                            f"simulator has {len(sim_channels)}")

        if use_simulation:
            if not self.simulator or needs_rebuild:
                # Update config to simulation mode for simulator creation
                self.config.system.simulation_mode = True
                self.simulator = self._create_simulator()
                if self.hardware_reader:
                    try:
                        self.hardware_reader.stop()
                    except Exception:
                        pass
                    self.hardware_reader = None
                logger.info(f"[STATION] Simulator created with {len(all_channels)} channels")
        elif HW_READER_AVAILABLE and (not self.hardware_reader or needs_rebuild):
            try:
                # Stop existing reader before rebuilding
                if self.hardware_reader:
                    try:
                        self.hardware_reader.stop()
                    except Exception:
                        pass
                self.hardware_reader = HardwareReader(self.config)
                self.simulator = None
                logger.info(f"[STATION] Hardware reader created with {len(all_channels)} channels "
                            f"across {budget['module_count']} modules")
            except Exception as e:
                logger.error(f"Failed to init hardware reader for station: {e}")
                self.simulator = self._create_simulator()
                self.hardware_reader = None
        elif not HW_READER_AVAILABLE and not self.simulator:
            logger.warning("[STATION] nidaqmx not available — falling back to simulator")
            self.simulator = self._create_simulator()

        # Start scan loop if not running (uses existing infrastructure)
        if not self.acquiring:
            self._state_machine.to(DAQState.RUNNING)

    def _stop_scan_loop_for_station(self):
        """Stop the global scan loop when no projects need acquisition."""
        if self.acquiring:
            self._state_machine.to(DAQState.STOPPED)

    def _on_project_acquire_start(self, client, userdata, msg):
        """Critical callback: Start acquisition for a specific project."""
        try:
            # Extract project_id from topic: .../projects/{project_id}/acquire/start
            parts = msg.topic.split('/')
            proj_idx = parts.index('projects') + 1
            project_id = parts[proj_idx]
            self._project_start_acquisition(project_id)
        except Exception as e:
            logger.error(f"Error in project acquire start: {e}")

    def _on_project_acquire_stop(self, client, userdata, msg):
        """Critical callback: Stop acquisition for a specific project."""
        try:
            parts = msg.topic.split('/')
            proj_idx = parts.index('projects') + 1
            project_id = parts[proj_idx]
            self._project_stop_acquisition(project_id)
        except Exception as e:
            logger.error(f"Error in project acquire stop: {e}")

    def _on_project_recording_start(self, client, userdata, msg):
        """Critical callback: Start recording for a specific project."""
        try:
            parts = msg.topic.split('/')
            proj_idx = parts.index('projects') + 1
            project_id = parts[proj_idx]
            if project_id in self.active_projects:
                ctx = self.active_projects[project_id]
                if ctx.recording_manager:
                    ctx.recording_manager.start()
                    self._publish_project_status(project_id)
                    self._publish_station_status()
        except Exception as e:
            logger.error(f"Error in project recording start: {e}")

    def _on_project_recording_stop(self, client, userdata, msg):
        """Critical callback: Stop recording for a specific project."""
        try:
            parts = msg.topic.split('/')
            proj_idx = parts.index('projects') + 1
            project_id = parts[proj_idx]
            if project_id in self.active_projects:
                ctx = self.active_projects[project_id]
                if ctx.recording_manager:
                    ctx.recording_manager.stop()
                    self._publish_project_status(project_id)
                    self._publish_station_status()
        except Exception as e:
            logger.error(f"Error in project recording stop: {e}")

    def _save_station_state(self):
        """Persist station state (loaded projects) for restart recovery."""
        try:
            state = {
                "loaded_projects": [
                    {
                        "project_id": pid,
                        "path": str(ctx.project_path),
                        "color_index": ctx.color_index,
                    }
                    for pid, ctx in self.active_projects.items()
                ]
            }
            self._station_state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._station_state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save station state: {e}")

    def _restore_station_state(self):
        """Restore station state from previous session on startup."""
        if not self._station_state_path.exists():
            return
        try:
            with open(self._station_state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            for entry in state.get('loaded_projects', []):
                project_path = Path(entry['path'])
                project_id = entry['project_id']
                if project_path.exists() and project_id not in self.active_projects:
                    with open(project_path, 'r', encoding='utf-8') as pf:
                        project_data = json.load(pf)
                    ctx = self._create_project_context(project_id, project_data, project_path)
                    ctx.color_index = entry.get('color_index', ctx.color_index)
                    self.active_projects[project_id] = ctx
                    logger.info(f"Restored project '{project_id}' from station state")
        except Exception as e:
            logger.warning(f"Failed to restore station state: {e}")

    def _dispatch_values_to_projects(self, valid_channels: set, scan_interval: float):
        """Dispatch scanned values to each active project's managers.

        Called once per scan cycle. Filters global channel_values to each
        project's owned channels, then runs that project's alarm, safety,
        script, PID, trigger, and watchdog evaluations.
        """
        if not self.active_projects:
            return

        for project_id, ctx in self.active_projects.items():
            if not ctx.acquiring:
                continue

            try:
                # Filter global values to this project's channels
                with self.values_lock:
                    for ch_name in ctx.channel_names:
                        if ch_name in self.channel_values:
                            ctx.channel_values[ch_name] = self.channel_values[ch_name]
                        if ch_name in self.channel_timestamps:
                            ctx.channel_timestamps[ch_name] = self.channel_timestamps[ch_name]
                        if ch_name in self.channel_acquisition_ts_us:
                            ctx.channel_acquisition_ts_us[ch_name] = self.channel_acquisition_ts_us[ch_name]

                project_valid = valid_channels & ctx.channel_names

                # Process alarms for this project
                if ctx.alarm_manager:
                    for ch_name in project_valid:
                        val = ctx.channel_values.get(ch_name)
                        if val is not None:
                            try:
                                ctx.alarm_manager.process_value(ch_name, val)
                            except Exception:
                                pass

                # Process user variables
                if ctx.user_variables:
                    try:
                        ctx.user_variables.process_scan(ctx.channel_values)
                    except Exception as e:
                        logger.debug(f"[STATION] User vars error for {project_id}: {e}")

                # Process PID loops
                if ctx.pid_engine:
                    try:
                        ctx.pid_engine.process_scan(ctx.channel_values, scan_interval)
                    except Exception as e:
                        logger.debug(f"[STATION] PID error for {project_id}: {e}")

                # Process triggers
                if ctx.trigger_engine:
                    try:
                        ctx.trigger_engine.process_scan(ctx.channel_values)
                    except Exception as e:
                        logger.debug(f"[STATION] Trigger error for {project_id}: {e}")

                # Process watchdogs
                if ctx.watchdog_engine:
                    try:
                        ctx.watchdog_engine.process_scan(ctx.channel_values, ctx.channel_timestamps)
                    except Exception as e:
                        logger.debug(f"[STATION] Watchdog error for {project_id}: {e}")

                # Evaluate safety interlocks
                if ctx.safety_manager:
                    try:
                        ctx.safety_manager.evaluate_all()
                    except Exception as e:
                        logger.error(f"[STATION] Safety eval failed for {project_id}: {e}")

            except Exception as e:
                logger.error(f"[STATION] Error dispatching to project {project_id}: {e}")

    def _publish_project_channel_batches(self, all_values: Dict[str, Any]):
        """Publish per-project channel value batches during the publish loop."""
        if not self.active_projects:
            return

        for project_id, ctx in self.active_projects.items():
            if not ctx.acquiring:
                continue

            try:
                # Filter values to this project's channels
                project_values = {}
                for ch_name in ctx.channel_names:
                    if ch_name in all_values:
                        project_values[ch_name] = all_values[ch_name]

                if not project_values:
                    continue

                # Build batch payload matching the standard batch format
                batch_payload = {
                    't': time.time(),
                    'ts_us': int(time.time_ns() // 1000),
                    'v': project_values,
                    'bad': [],
                    'alarm': [],
                    'warn': [],
                    'stale': [],
                    'projectId': project_id,
                }

                # Add alarm/warning state from project's alarm manager
                if ctx.alarm_manager and ctx.alarm_manager.active_alarms:
                    for alarm_id, active in ctx.alarm_manager.active_alarms.items():
                        ch = active.channel if hasattr(active, 'channel') else ''
                        if ch in project_values:
                            sev = active.severity.value if hasattr(active.severity, 'value') else str(active.severity)
                            if sev in ('CRITICAL', 'HIGH'):
                                batch_payload['alarm'].append(ch)
                            elif sev in ('MEDIUM', 'LOW', 'WARNING'):
                                batch_payload['warn'].append(ch)

                self._publish_project_mqtt(
                    project_id, "channels/batch",
                    json.dumps(batch_payload)
                )

                # Write to project's recording manager — include user variables
                # so they end up in CSV/TDMS alongside hardware channels.
                # Variables are prefixed with "uv." to distinguish from channels.
                if ctx.recording_manager and ctx.recording_manager.recording:
                    channel_configs = {
                        name: {'units': ch.units, 'description': ch.description}
                        for name, ch in ctx.config.channels.items()
                    }
                    record_values = dict(project_values)
                    if getattr(ctx, 'user_variables', None):
                        try:
                            var_dict = ctx.user_variables.get_values_dict()
                            for var_id, var_info in var_dict.items():
                                vname = var_info.get('name')
                                if not vname:
                                    continue
                                # Per-variable opt-in flag — only included if
                                # Mike checked "Record this variable" on the
                                # Data tab. Default False so existing projects
                                # don't suddenly grow new CSV columns.
                                if not var_info.get('log', False):
                                    continue
                                key = f"uv.{vname}"
                                record_values[key] = var_info.get('value')
                                channel_configs[key] = {
                                    'units': var_info.get('units', ''),
                                    'description': f"User variable: {vname}",
                                }
                        except Exception as e:
                            logger.debug(f"User-vars recording skipped: {e}")
                    ctx.recording_manager.write_sample(record_values, channel_configs)

            except Exception as e:
                logger.error(f"[STATION] Publish error for project {project_id}: {e}")

    def _route_project_command(self, topic: str, payload: Any, request_id: Optional[str] = None):
        """Route a per-project command to the correct ProjectContext's managers.

        Topic format: {base}/projects/{project_id}/commands/{command}
        """
        try:
            parts = topic.split('/')
            proj_idx = parts.index('projects') + 1
            project_id = parts[proj_idx]
            # Everything after 'commands/' is the command path
            cmd_idx = parts.index('commands') + 1
            command = '/'.join(parts[cmd_idx:]) if cmd_idx < len(parts) else ''
        except (ValueError, IndexError):
            logger.warning(f"Malformed project command topic: {topic}")
            return

        if project_id not in self.active_projects:
            logger.warning(f"Project command for unknown project '{project_id}': {command}")
            return

        ctx = self.active_projects[project_id]

        # Route to project-specific handlers
        if command == 'status/request':
            self._publish_project_status(project_id)
        elif command.startswith('script/'):
            self._route_project_script_command(project_id, ctx, command, payload)
        elif command.startswith('alarm/'):
            self._route_project_alarm_command(project_id, ctx, command, payload)
        elif command.startswith('safety/'):
            self._route_project_safety_command(project_id, ctx, command, payload)
        elif command == 'output/set':
            if isinstance(payload, dict):
                ch = payload.get('channel', '')
                val = payload.get('value')
                self._project_set_output(project_id, ch, val)
        elif command.startswith('recording/'):
            self._route_project_recording_command(project_id, ctx, command, payload)
        elif command.startswith('variables/'):
            self._route_project_variable_command(project_id, ctx, command, payload)
        elif command.startswith('sequence/'):
            self._route_project_sequence_command(project_id, ctx, command, payload)
        else:
            logger.debug(f"Unhandled project command: {project_id}/{command}")

    def _route_project_script_command(self, project_id: str, ctx: ProjectContext,
                                       command: str, payload: Any):
        """Route script commands for a project."""
        if not ctx.script_manager:
            return
        action = command.split('/')[-1]
        if action == 'add':
            ctx.script_manager.add_script_from_payload(payload)
        elif action == 'update':
            ctx.script_manager.update_script_from_payload(payload)
        elif action == 'remove':
            script_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.script_manager.remove_script(script_id)
        elif action == 'start':
            script_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.script_manager.start_script(script_id)
        elif action == 'stop':
            script_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.script_manager.stop_script(script_id)
        elif action == 'clear-all':
            ctx.script_manager.clear_all()
        elif action == 'list':
            scripts = ctx.script_manager.list_scripts()
            self._publish_project_mqtt(project_id, "script/list/response", scripts)

    def _route_project_alarm_command(self, project_id: str, ctx: ProjectContext,
                                      command: str, payload: Any):
        """Route alarm commands for a project."""
        if not ctx.alarm_manager:
            return
        action = command.split('/')[-1]
        if action == 'configure':
            # Dynamic alarm config push (same format as standalone)
            if isinstance(payload, dict):
                try:
                    config = AlarmConfig(
                        id=payload.get('id', ''),
                        channel=payload.get('channel', ''),
                        name=payload.get('name', payload.get('channel', '')),
                        description=payload.get('description', ''),
                        enabled=payload.get('enabled', True),
                        severity=AlarmSeverity(payload.get('severity', 'HIGH')),
                        high_high=payload.get('high_high'),
                        high=payload.get('high'),
                        low=payload.get('low'),
                        low_low=payload.get('low_low'),
                        deadband=payload.get('deadband', 0),
                        on_delay_s=payload.get('on_delay_s', 0),
                        off_delay_s=payload.get('off_delay_s', 0),
                        latch_behavior=LatchBehavior(payload.get('latch_behavior', 'AUTO_CLEAR')),
                        group=payload.get('group', ''),
                        actions=payload.get('actions', []),
                    )
                    ctx.alarm_manager.add_alarm_config(config)
                    self._publish_project_mqtt(project_id, "alarms/configure/response",
                                               {"success": True, "alarm_id": config.id})
                except Exception as e:
                    self._publish_project_mqtt(project_id, "alarms/configure/response",
                                               {"success": False, "error": str(e)})
        elif action == 'acknowledge':
            alarm_id = payload.get('alarm_id', '') if isinstance(payload, dict) else ''
            ctx.alarm_manager.acknowledge(alarm_id)
        elif action == 'clear' or action == 'reset':
            alarm_id = payload.get('alarm_id', '') if isinstance(payload, dict) else ''
            ctx.alarm_manager.clear(alarm_id)
        elif action == 'shelve':
            alarm_id = payload.get('alarm_id', '') if isinstance(payload, dict) else ''
            duration = payload.get('duration', 3600) if isinstance(payload, dict) else 3600
            ctx.alarm_manager.shelve(alarm_id, duration)
        elif action == 'unshelve':
            alarm_id = payload.get('alarm_id', '') if isinstance(payload, dict) else ''
            ctx.alarm_manager.unshelve(alarm_id)

    def _route_project_safety_command(self, project_id: str, ctx: ProjectContext,
                                       command: str, payload: Any):
        """Route safety/interlock commands for a project."""
        if not ctx.safety_manager:
            return
        action = command.replace('safety/', '')
        if action == 'latch/arm':
            ctx.safety_manager.arm_latch()
        elif action == 'latch/disarm':
            ctx.safety_manager.disarm_latch()
        elif action == 'trip/reset':
            interlock_id = payload.get('interlock_id', '') if isinstance(payload, dict) else ''
            ctx.safety_manager.reset_trip(interlock_id)
        elif action == 'status/request':
            status = ctx.safety_manager.get_status()
            self._publish_project_mqtt(project_id, "safety/status", status)

    def _route_project_recording_command(self, project_id: str, ctx: ProjectContext,
                                          command: str, payload: Any):
        """Route recording commands for a project."""
        if not ctx.recording_manager:
            return
        action = command.split('/')[-1]
        if action == 'config':
            if isinstance(payload, dict):
                ctx.recording_manager.configure(payload)
        elif action == 'list':
            recordings = ctx.recording_manager.list_recordings()
            self._publish_project_mqtt(project_id, "recording/list/response", recordings)

    def _route_project_variable_command(self, project_id: str, ctx: ProjectContext,
                                         command: str, payload: Any):
        """Route user variable commands for a project."""
        if not ctx.user_variables:
            return
        action = command.split('/')[-1]
        if action == 'create':
            ctx.user_variables.create_from_payload(payload)
        elif action == 'update':
            ctx.user_variables.update_from_payload(payload)
        elif action == 'delete':
            var_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.user_variables.delete(var_id)
        elif action == 'set':
            if isinstance(payload, dict):
                ctx.user_variables.set_value(payload.get('id', ''), payload.get('value'))
        elif action == 'list':
            variables = ctx.user_variables.list_variables()
            self._publish_project_mqtt(project_id, "variables/list/response", variables)

    def _route_project_sequence_command(self, project_id: str, ctx: ProjectContext,
                                         command: str, payload: Any):
        """Route sequence commands for a project."""
        if not ctx.sequence_manager:
            return
        action = command.split('/')[-1]
        if action == 'start':
            seq_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.sequence_manager.start(seq_id)
        elif action == 'pause':
            seq_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.sequence_manager.pause(seq_id)
        elif action == 'resume':
            seq_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.sequence_manager.resume(seq_id)
        elif action == 'abort':
            seq_id = payload.get('id', '') if isinstance(payload, dict) else ''
            ctx.sequence_manager.abort(seq_id)

    def _handle_project_load(self, payload: Any):
        """Load a project file - supports both filename (from default dir) and full path"""
        # PERMISSION CHECK
        if not self._has_permission(Permission.LOAD_PROJECT):
            logger.warning("[SECURITY] Project load denied - insufficient permissions")
            self._publish_project_response(False, "Permission denied")
            return

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
        """Import a project directly from JSON object

        Used when frontend loads a project file and sends the parsed JSON.
        The project is saved to config/projects/ and then loaded.
        """
        if not isinstance(payload, dict):
            self._publish_project_response(False, "Invalid payload - expected JSON object")
            return

        # Validate project structure
        if payload.get("type") != "nisystem-project":
            self._publish_project_response(False, "Invalid project - missing 'type: nisystem-project'")
            return

        # Check if acquisition is running
        if self.acquiring:
            self._publish_project_response(False, "Cannot import project while acquisition is running")
            return

        try:
            # Determine filename from project name
            project_name = payload.get("name", "Imported Project")
            safe_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in project_name)
            safe_name = safe_name.strip().replace(' ', '_')
            filename = f"{safe_name}.json"

            # Save to config/projects/
            projects_dir = self._get_projects_dir()
            project_path = projects_dir / filename

            # Add/update metadata
            payload["type"] = "nisystem-project"
            payload["version"] = payload.get("version", "1.0")
            payload["modified"] = datetime.now().isoformat()
            if not payload.get("created"):
                payload["created"] = datetime.now().isoformat()

            # Save the file
            with open(project_path, 'w') as f:
                json.dump(payload, f, indent=2)

            logger.info(f"Saved imported project to {project_path}")

            # Apply the project configuration
            success, error_msg = self._apply_project_config(payload)
            if success:
                self.current_project_data = payload
                self.current_project_path = project_path  # Now has a file path
                self._save_last_project_path(project_path)

                self._publish_channel_config()

                logger.info(f"Imported project: {project_name} -> {filename}")
                self._publish_project_response(True, f"Project '{project_name}' imported to projects/{filename}")
            else:
                self._publish_project_response(False, f"Failed to apply project configuration: {error_msg}")
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
        # IMPORTANT: Clear MQTT retained messages BEFORE clearing alarm manager
        self._publish_alarms_cleared(reason="project_closed")
        if self.alarm_manager:
            self.alarm_manager.clear_all(clear_configs=True)

        # Clear safety state - interlocks are per-project
        if self.safety_manager:
            self.safety_manager.clear_all()

        logger.info("Project closed - now in empty state")

        self.mqtt_client.publish(
            f"{base}/project/closed",
            json.dumps({"success": True, "message": "Project closed"})
        )

    # =========================================================================
    # AUTOSAVE / CRASH RECOVERY
    # =========================================================================

    def _get_autosave_path(self) -> Path:
        """Get the path to the autosave file"""
        projects_dir = self._get_projects_dir()
        return projects_dir / ".autosave.json"

    def _handle_project_autosave(self, payload: Any):
        """Save current state to autosave file for crash recovery"""
        if not isinstance(payload, dict):
            return

        autosave_data = payload.get("data", {})
        if not autosave_data:
            return

        # Inject backend-authoritative state (PID loops)
        if self.pid_engine and self.pid_engine.loops:
            autosave_data["pidLoops"] = self.pid_engine.to_config_dict()

        autosave_path = self._get_autosave_path()

        try:
            # Add metadata
            autosave_data["_autosave"] = {
                "timestamp": datetime.now().isoformat(),
                "source_project": self.current_project_path.name if self.current_project_path else None,
                "reason": "periodic_autosave"
            }

            with open(autosave_path, 'w') as f:
                json.dump(autosave_data, f, indent=2)

            logger.debug(f"Autosave written to {autosave_path}")

        except Exception as e:
            logger.error(f"Failed to write autosave: {e}")

    def _handle_project_autosave_discard(self):
        """Delete the autosave file (user chose not to recover)"""
        base = self.get_topic_base()
        autosave_path = self._get_autosave_path()

        try:
            if autosave_path.exists():
                autosave_path.unlink()
                logger.info("Autosave file discarded by user")

            self.mqtt_client.publish(
                f"{base}/project/autosave/status",
                json.dumps({"exists": False, "discarded": True})
            )

        except Exception as e:
            logger.error(f"Failed to delete autosave: {e}")

    def _handle_project_autosave_check(self):
        """Check if autosave file exists and publish status"""
        self._publish_autosave_status()

    def _handle_create_instance(self, payload):
        """Create a config file for a new DAQ service instance.

        Receives: { node_id, node_name, simulation_mode }
        Creates: config/system_{node_id}.ini
        Responds with config path and launch command.
        """
        base = self.get_topic_base()
        try:
            node_id = payload.get('node_id', '').strip()
            node_name = payload.get('node_name', '').strip() or node_id
            simulation_mode = payload.get('simulation_mode', False)

            if not node_id:
                self.mqtt_client.publish(
                    f"{base}/system/create-instance/response",
                    json.dumps({"success": False, "error": "node_id is required"})
                )
                return

            # Sanitize node_id for filename
            safe_id = node_id.replace(' ', '_').replace('/', '-')
            config_dir = Path(self.config_path).parent
            new_config_path = config_dir / f"system_{safe_id}.ini"

            if new_config_path.exists():
                self.mqtt_client.publish(
                    f"{base}/system/create-instance/response",
                    json.dumps({
                        "success": False,
                        "error": f"Config already exists: {new_config_path.name}"
                    })
                )
                return

            # Copy current config as template and update node-specific fields
            import configparser as _cp
            cfg = _cp.ConfigParser()
            cfg.read(self.config_path)

            if not cfg.has_section('system'):
                cfg.add_section('system')

            cfg.set('system', 'node_id', node_id)
            cfg.set('system', 'node_name', node_name)
            cfg.set('system', 'simulation_mode', str(simulation_mode).lower())

            with open(new_config_path, 'w') as f:
                cfg.write(f)

            launch_cmd = f"python -m services.daq_service.daq_service -c {new_config_path}"

            logger.info(f"[MULTI-INSTANCE] Created config for {node_id}: {new_config_path}")

            self.mqtt_client.publish(
                f"{base}/system/create-instance/response",
                json.dumps({
                    "success": True,
                    "node_id": node_id,
                    "config_path": str(new_config_path),
                    "launch_command": launch_cmd
                })
            )
        except Exception as e:
            logger.error(f"[MULTI-INSTANCE] Failed to create instance: {e}", exc_info=True)
            self.mqtt_client.publish(
                f"{base}/system/create-instance/response",
                json.dumps({"success": False, "error": str(e)})
            )

    def _publish_autosave_status(self):
        """Publish autosave status to MQTT"""
        base = self.get_topic_base()
        autosave_path = self._get_autosave_path()

        status = {"exists": False}

        if autosave_path.exists():
            try:
                with open(autosave_path, 'r') as f:
                    autosave_data = json.load(f)

                metadata = autosave_data.get("_autosave", {})
                status = {
                    "exists": True,
                    "timestamp": metadata.get("timestamp"),
                    "source_project": metadata.get("source_project"),
                    "project_name": autosave_data.get("name", "Unsaved Project")
                }
                logger.info(f"Autosave file found from {metadata.get('timestamp')}")

            except Exception as e:
                logger.error(f"Failed to read autosave file: {e}")
                status = {"exists": False, "error": str(e)}

        self.mqtt_client.publish(
            f"{base}/project/autosave/status",
            json.dumps(status),
            retain=True
        )

    def _delete_autosave_on_save(self):
        """Delete autosave file after successful project save"""
        autosave_path = self._get_autosave_path()
        if autosave_path.exists():
            try:
                autosave_path.unlink()
                logger.info("Autosave file deleted after successful save")
                # Publish updated status
                self._publish_autosave_status()
            except Exception as e:
                logger.error(f"Failed to delete autosave after save: {e}")

    def _handle_project_save(self, payload: Any):
        """Save project to file - saves to current path or specified path"""
        # PERMISSION CHECK
        if not self._has_permission(Permission.SAVE_PROJECT):
            logger.warning("[SECURITY] Project save denied - insufficient permissions")
            self._publish_project_response(False, "Permission denied")
            return

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
        project_data["version"] = "2.0"
        project_data["config"] = Path(self.config_path).name

        if not project_data.get("created"):
            project_data["created"] = datetime.now().isoformat()

        # Inject backend-authoritative state that the frontend doesn't track
        # PID loops are configured via MQTT commands and live in pid_engine
        if self.pid_engine and self.pid_engine.loops:
            project_data["pidLoops"] = self.pid_engine.to_config_dict()

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
                self._delete_autosave_on_save()  # Clear autosave after successful save
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
                self._delete_autosave_on_save()  # Clear autosave after successful save

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

        # Handle both file-based projects and JSON-imported projects
        has_project = bool(self.current_project_path or self.current_project_data)

        self.mqtt_client.publish(
            f"{base}/project/current",
            json.dumps({
                "filename": self.current_project_path.name if self.current_project_path else (
                    self.current_project_data.get("name", "Imported Project") if self.current_project_data else None
                ),
                "path": str(self.current_project_path) if self.current_project_path else None,
                "project": self.current_project_data if has_project else None
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

    def _get_allowed_modbus_ips(self) -> set:
        """Build set of allowed Modbus TCP IP addresses from configured chassis/devices."""
        allowed = set()
        if hasattr(self.config, 'chassis') and self.config.chassis:
            for chassis in self.config.chassis.values():
                ip = getattr(chassis, 'ip_address', '')
                if ip:
                    allowed.add(ip)
        return allowed

    def _handle_modbus_write_register(self, payload: Any):
        """
        Write a value to a Modbus register with optional verification.

        Supports two modes:
        1. Direct register access: specify register_address directly
        2. Channel-based: specify channel name to use its configured register

        Payload options:
        - channel: Channel name (uses channel's register config)
        - register_address: Direct register address (if not using channel)
        - value: Value to write (required)
        - slave_id: Modbus slave ID (required for direct mode, optional for channel mode)
        - data_type: 'int16', 'uint16', 'int32', 'uint32', 'float32' (default: uint16)
        - verify: true/false - read back after write to confirm (default: false)
        - connection_type: 'tcp' or 'rtu' (default: tcp)
        - ip_address: For TCP connections (must be a configured device)
        - port: TCP port (default: 502)
        - serial_port: For RTU connections
        - baudrate, parity, stopbits, bytesize: RTU params
        """
        base = self.get_topic_base()

        if not isinstance(payload, dict):
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Invalid payload"
            }))
            return

        # Check for channel-based write
        channel_name = payload.get('channel')
        register_address = payload.get('register_address')
        value = payload.get('value')
        data_type = payload.get('data_type', 'uint16')
        verify = payload.get('verify', False)

        # Connection parameters
        connection_type = payload.get('connection_type', 'tcp')
        slave_id = payload.get('slave_id')
        ip_address = payload.get('ip_address')
        port = payload.get('port', 502)
        serial_port = payload.get('serial_port')
        baudrate = payload.get('baudrate', 9600)
        parity = payload.get('parity', 'N')
        stopbits = payload.get('stopbits', 1)
        bytesize = payload.get('bytesize', 8)

        # If channel specified, get register info from channel config
        if channel_name:
            if channel_name not in self.config.channels:
                self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                    "success": False, "error": f"Channel '{channel_name}' not found"
                }))
                return

            ch_config = self.config.channels[channel_name]

            # Get register address from channel
            if hasattr(ch_config, 'address') and ch_config.address is not None:
                register_address = ch_config.address
            elif hasattr(ch_config, 'modbus_address') and ch_config.modbus_address is not None:
                register_address = ch_config.modbus_address
            else:
                self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                    "success": False, "error": f"Channel '{channel_name}' has no register address configured"
                }))
                return

            # Get slave ID from channel if not specified
            if slave_id is None:
                slave_id = getattr(ch_config, 'slave_id', None) or getattr(ch_config, 'modbus_slave_id', 1)

            # Get data type from channel if available
            if hasattr(ch_config, 'data_type') and ch_config.data_type:
                data_type = ch_config.data_type

            # In channel mode, connection params come exclusively from device config
            # (payload ip_address/serial_port are ignored for security)
            payload_ip = payload.get('ip_address')
            ip_address = None
            serial_port = None
            if hasattr(ch_config, 'device') and ch_config.device:
                device_id = ch_config.device
                if hasattr(self.config, 'chassis') and self.config.chassis:
                    for chassis in self.config.chassis.values():
                        if hasattr(chassis, 'devices'):
                            for dev in chassis.devices:
                                if getattr(dev, 'id', None) == device_id or getattr(dev, 'name', None) == device_id:
                                    if hasattr(dev, 'ip_address') and dev.ip_address:
                                        ip_address = dev.ip_address
                                    if hasattr(dev, 'serial_port') and dev.serial_port:
                                        serial_port = dev.serial_port
                                        connection_type = 'rtu'
                                    break
            if payload_ip and payload_ip != ip_address:
                logger.warning(
                    f"[SECURITY] Modbus write: payload ip_address='{payload_ip}' ignored in channel mode "
                    f"for channel '{channel_name}' (using device config ip='{ip_address}')"
                )

        # Validate required params
        if value is None:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Missing required parameter: value"
            }))
            return

        if register_address is None:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Missing register_address (specify directly or via channel)"
            }))
            return

        if slave_id is None:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Missing slave_id"
            }))
            return

        if connection_type == 'tcp' and not ip_address:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Missing ip_address for TCP connection"
            }))
            return

        # IP allowlisting: only allow writes to configured Modbus device IPs
        if connection_type == 'tcp' and ip_address:
            allowed_ips = self._get_allowed_modbus_ips()
            if allowed_ips and ip_address not in allowed_ips:
                logger.warning(
                    f"[SECURITY] Modbus write blocked: target IP '{ip_address}' "
                    f"is not a configured Modbus device (allowed: {allowed_ips})"
                )
                self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                    "success": False,
                    "error": f"IP address '{ip_address}' is not a configured Modbus device"
                }))
                return

        if connection_type == 'rtu' and not serial_port:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "Missing serial_port for RTU connection"
            }))
            return

        try:
            import struct
            from pymodbus.client import ModbusTcpClient, ModbusSerialClient

            # Create connection
            if connection_type == 'tcp':
                client = ModbusTcpClient(host=ip_address, port=port, timeout=3)
            else:
                client = ModbusSerialClient(
                    port=serial_port,
                    baudrate=baudrate,
                    parity=parity,
                    stopbits=stopbits,
                    bytesize=bytesize,
                    timeout=3
                )

            if not client.connect():
                self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                    "success": False, "error": "Failed to connect to device"
                }))
                return

            try:
                # Convert value to register(s) based on data type
                registers = self._value_to_modbus_registers(float(value), data_type)

                if registers is None:
                    self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                        "success": False, "error": f"Unsupported data type: {data_type}"
                    }))
                    return

                # Write register(s)
                if len(registers) == 1:
                    result = client.write_register(int(register_address), registers[0], device_id=int(slave_id))
                else:
                    result = client.write_registers(int(register_address), registers, device_id=int(slave_id))

                if result.isError():
                    self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                        "success": False,
                        "error": f"Modbus write error at register {register_address}",
                        "channel": channel_name,
                        "register_address": register_address,
                        "requested_value": value
                    }))
                    return

                # Verification: read back the value
                verified_value = None
                verification_passed = None

                if verify:
                    time.sleep(0.05)  # Small delay before read-back

                    read_result = client.read_holding_registers(int(register_address), len(registers), device_id=int(slave_id))

                    if not read_result.isError():
                        verified_value = self._modbus_registers_to_value(read_result.registers, data_type)

                        # Check if values match (with tolerance for floats)
                        if data_type in ('float32', 'real', 'float'):
                            verification_passed = abs(verified_value - float(value)) < 0.001
                        else:
                            verification_passed = int(verified_value) == int(value)
                    else:
                        verification_passed = False
                        logger.warning(f"Verification read-back failed for register {register_address}")

                # Build response
                response = {
                    "success": True,
                    "message": f"Successfully wrote to register {register_address}",
                    "register_address": register_address,
                    "slave_id": slave_id,
                    "value_written": value,
                    "data_type": data_type
                }

                if channel_name:
                    response["channel"] = channel_name

                if verify:
                    response["verified"] = verification_passed
                    response["verified_value"] = verified_value
                    if not verification_passed:
                        response["success"] = False
                        response["warning"] = "Write verification failed - value read back does not match"

                logger.info(f"Modbus write: register={register_address}, value={value}, type={data_type}, verified={verification_passed}")
                self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps(response))

            finally:
                client.close()

        except ImportError:
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": "pymodbus library not available"
            }))
        except Exception as e:
            logger.error(f"Failed to write Modbus register: {e}")
            self.mqtt_client.publish(f"{base}/modbus/write_register/response", json.dumps({
                "success": False, "error": str(e)
            }))

    def _value_to_modbus_registers(self, value: float, data_type: str) -> list:
        """Convert a value to Modbus register(s) based on data type"""
        import struct

        try:
            if data_type in ('int16', 'sint16'):
                packed = struct.pack('>h', int(value))
                return [struct.unpack('>H', packed)[0]]
            elif data_type in ('uint16', 'word'):
                return [int(value) & 0xFFFF]
            elif data_type in ('int32', 'sint32', 'dint'):
                packed = struct.pack('>i', int(value))
                return list(struct.unpack('>HH', packed))
            elif data_type in ('uint32', 'dword'):
                packed = struct.pack('>I', int(value))
                return list(struct.unpack('>HH', packed))
            elif data_type in ('float32', 'real', 'float'):
                packed = struct.pack('>f', float(value))
                return list(struct.unpack('>HH', packed))
            else:
                # Default to uint16
                return [int(value) & 0xFFFF]
        except Exception as e:
            logger.error(f"Error converting value {value} to {data_type}: {e}")
            return None

    def _modbus_registers_to_value(self, registers: list, data_type: str) -> float:
        """Convert Modbus register(s) to a value based on data type"""
        import struct

        try:
            if data_type in ('int16', 'sint16'):
                packed = struct.pack('>H', registers[0])
                return struct.unpack('>h', packed)[0]
            elif data_type in ('uint16', 'word'):
                return registers[0]
            elif data_type in ('int32', 'sint32', 'dint'):
                packed = struct.pack('>HH', registers[0], registers[1])
                return struct.unpack('>i', packed)[0]
            elif data_type in ('uint32', 'dword'):
                packed = struct.pack('>HH', registers[0], registers[1])
                return struct.unpack('>I', packed)[0]
            elif data_type in ('float32', 'real', 'float'):
                packed = struct.pack('>HH', registers[0], registers[1])
                return struct.unpack('>f', packed)[0]
            else:
                return registers[0]
        except Exception as e:
            logger.error(f"Error converting registers {registers} from {data_type}: {e}")
            return None

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
    # CRIO NODE HANDLERS
    # =========================================================================

    def _handle_crio_node_status(self, topic: str, payload: Dict[str, Any]):
        """
        Handle status message from a remote cRIO, Opto22, GC, or CFP node.

        When a remote node publishes to {mqtt_base}/nodes/{node_id}/status/system,
        we register it with device_discovery so it appears in the Configuration tab.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/status/system")
            payload: Status payload containing node_type, status, channels, etc.
        """
        if not isinstance(payload, dict):
            return

        # Only process if it's a remote node (cRIO, Opto22, GC, or CFP)
        node_type = payload.get('node_type')
        if node_type not in ('crio', 'opto22', 'gc', 'cfp'):
            return

        # Extract node_id from topic: nisystem/nodes/{node_id}/status/system
        parts = topic.split('/')
        node_idx = -1
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_idx = i + 1
                break

        if node_idx < 0:
            logger.warning(f"Could not extract node_id from topic: {topic}")
            return

        node_id = parts[node_idx]

        # Don't register ourselves
        if node_id == self.config.system.node_id:
            return

        # Register with device discovery based on node type
        status = payload.get('status', 'unknown')

        # Check if this is a NEW node (not seen before)
        if node_type == 'crio':
            existing_nodes = {n.node_id for n in self.device_discovery.get_crio_nodes()}
        elif node_type == 'opto22':
            existing_nodes = {n.node_id for n in self.device_discovery.get_opto22_nodes()}
        elif node_type == 'gc':
            existing_nodes = {n.node_id for n in self.device_discovery.get_gc_nodes()}
        elif node_type == 'cfp':
            existing_nodes = {n.node_id for n in self.device_discovery.get_cfp_nodes()}
        else:
            return
        is_new_node = node_id not in existing_nodes

        if status == 'offline':
            if node_type == 'crio':
                self.device_discovery.mark_crio_offline(node_id)
            elif node_type == 'opto22':
                self.device_discovery.mark_opto22_offline(node_id)
            elif node_type == 'cfp':
                self.device_discovery.mark_cfp_offline(node_id)
            else:  # gc
                self.device_discovery.mark_gc_offline(node_id)
        else:
            if node_type == 'crio':
                self.device_discovery.register_crio_node(node_id, payload)
            elif node_type == 'opto22':
                self.device_discovery.register_opto22_node(node_id, payload)
            elif node_type == 'cfp':
                self.device_discovery.register_cfp_node(node_id, payload)
            else:  # gc
                self.device_discovery.register_gc_node(node_id, payload)

        logger.info(f"{node_type.upper()} node status received: {node_id} -> {status}")

        # If a new node was discovered, notify frontend so it can refresh discovery
        if is_new_node and status != 'offline':
            base = self.get_topic_base()
            discovery_topic = f"{base}/discovery/{node_type}-found"
            self.mqtt_client.publish(
                discovery_topic,
                json.dumps({
                    "node_id": node_id,
                    "node_type": node_type,
                    "status": status,
                    "product_type": payload.get('product_type', {'crio': 'cRIO', 'opto22': 'groov EPIC', 'cfp': 'CompactFieldPoint', 'gc': 'GC Analyzer'}.get(node_type, 'Unknown')),
                    "channels": payload.get('channels', 0),
                    "timestamp": datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"Notified frontend: new {node_type.upper()} node discovered: {node_id}")

        # Auto-push config to remote node if:
        # 1. It's a new node that just came online
        # 2. Config version mismatch (node has stale config)
        if status != 'offline':
            should_push = False
            reason = ""

            # Check 1: New node - always push config
            if is_new_node:
                should_push = True
                reason = "new node discovered"

            # Check 2: Config version mismatch or missing
            if not should_push:
                reported_version = payload.get('config_version', '')
                if node_type == 'opto22':
                    expected_version = self._opto22_config_versions.get(node_id, '')
                elif node_type == 'cfp':
                    expected_version = self._cfp_config_versions.get(node_id, '')
                else:
                    expected_version = self._crio_config_versions.get(node_id, '')
                if expected_version:
                    # We have an expected version - check if node matches
                    if not reported_version:
                        # Node doesn't report a version - needs config push
                        should_push = True
                        reason = "node has no config version (needs config push)"
                    elif reported_version != expected_version:
                        # Version mismatch
                        should_push = True
                        reason = f"config version mismatch (has: {reported_version}, expected: {expected_version})"

            if should_push:
                logger.info(f"Auto-pushing config to {node_type.upper()} {node_id}: {reason}")
                if node_type == 'opto22':
                    self._push_opto22_channel_config(node_id)
                elif node_type == 'cfp':
                    self._push_cfp_channel_config(node_id)
                else:
                    self._push_crio_channel_config(node_id)

    def _handle_crio_heartbeat(self, topic: str, payload: Dict[str, Any]):
        """
        Handle heartbeat from a remote cRIO or Opto22 node.

        Used as fallback discovery when status message was missed.
        Heartbeats are published every 2 seconds by remote nodes, so this
        ensures we discover nodes even if we miss their initial status.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/heartbeat")
            payload: Heartbeat payload with node_type, node_id, etc.
        """
        if not isinstance(payload, dict):
            return

        # Only process cRIO, Opto22, GC, and CFP heartbeats
        node_type = payload.get('node_type')
        if node_type not in ('crio', 'opto22', 'gc', 'cfp'):
            return

        # Extract node_id from topic: nisystem/nodes/{node_id}/heartbeat
        parts = topic.split('/')
        node_idx = -1
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_idx = i + 1
                break

        if node_idx < 0:
            return

        node_id = parts[node_idx]

        # Don't register ourselves
        if node_id == self.config.system.node_id:
            return

        # Update heartbeat timestamp without overwriting full registration
        # If we have full info from status message, preserve it
        heartbeat_data = {
            'status': 'online',
            'channels': payload.get('channels', 0),
            'pc_connected': payload.get('pc_connected', False),
            'ip_address': payload.get('ip_address', 'unknown'),
            'product_type': payload.get('product_type', 'cRIO' if node_type == 'crio' else ('groov EPIC' if node_type == 'opto22' else 'GC Analyzer')),
            'serial_number': payload.get('serial_number', ''),
        }

        if node_type == 'crio':
            self.device_discovery.update_crio_heartbeat(node_id, heartbeat_data)
        elif node_type == 'opto22':
            self.device_discovery.update_opto22_heartbeat(node_id, heartbeat_data)
        elif node_type == 'cfp':
            self.device_discovery.update_cfp_heartbeat(node_id, heartbeat_data)
        else:  # gc
            self.device_discovery.update_gc_heartbeat(node_id, heartbeat_data)

    def _handle_crio_channel_value(self, topic: str, payload: Dict[str, Any]):
        """
        Handle channel value(s) from a remote cRIO node.

        Supports two formats:
        1. Individual: topic=.../channels/{channel}, payload={value: x, timestamp: t}
        2. Batch: topic=.../channels/batch, payload={channel: {value: x, timestamp: t}, ...}

        Maps cRIO channel values to local channels based on source_type and source_node_id.
        This enables "magic" mode where cRIO channels appear just like local cDAQ channels.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/channels/batch")
            payload: Channel value(s) payload
        """
        if not isinstance(payload, dict):
            return

        # Extract node_id from topic
        # Pattern: {base}/nodes/{node_id}/channels/{channel_or_batch}
        parts = topic.split('/')
        try:
            nodes_idx = parts.index('nodes')
            channels_idx = parts.index('channels')
            node_id = parts[nodes_idx + 1]

            # Don't process our own published values (self-echo prevention)
            if node_id == self.config.system.node_id:
                return

            # What comes after "channels/" - could be "batch" or a channel name
            channel_suffix = '/'.join(parts[channels_idx + 1:])
        except (ValueError, IndexError):
            return

        # Determine if this is batch or individual format
        if channel_suffix == 'batch':
            # Batch format: payload = {channel_name: {value: x, timestamp: t}, ...}
            self._process_crio_batch_values(node_id, payload)
        else:
            # Individual format: channel_suffix is the crio_channel name
            value = payload.get('value')
            if value is not None:
                self._process_crio_single_value(node_id, channel_suffix, value)

    def _process_crio_batch_values(self, node_id: str, batch_payload: Dict[str, Any]):
        """Process batch channel values from cRIO/Opto22.

        Supports lean format: { t, ts_us, v: {ch: val}, bad?: [], stale?: [] }
        """
        # Lean format detection
        if 'v' in batch_payload and 't' in batch_payload:
            ts_us = batch_payload.get('ts_us', 0)
            bad_set = set(batch_payload.get('bad', []))
            with self.values_lock:
                for crio_channel, value in batch_payload['v'].items():
                    quality = 'bad' if crio_channel in bad_set else 'good'
                    if value is not None:
                        self._update_crio_channel_value(node_id, crio_channel, value, ts_us, quality)
        else:
            # Legacy format fallback (should not happen after uniform migration)
            with self.values_lock:
                for crio_channel, ch_data in batch_payload.items():
                    if isinstance(ch_data, dict):
                        value = ch_data.get('value')
                        acquisition_ts_us = ch_data.get('acquisition_ts_us', 0)
                        quality = ch_data.get('quality', 'good')
                    else:
                        value = ch_data
                        acquisition_ts_us = 0
                        quality = 'good'

                    if value is not None:
                        self._update_crio_channel_value(node_id, crio_channel, value, acquisition_ts_us, quality)

    def _process_crio_single_value(self, node_id: str, crio_channel: str, value: Any):
        """Process single channel value from cRIO."""
        with self.values_lock:
            self._update_crio_channel_value(node_id, crio_channel, value, 0, 'good')

    def _update_crio_channel_value(self, node_id: str, crio_channel: str, value: Any,
                                    acquisition_ts_us: int = 0, quality: str = 'good'):
        """Store a remote node channel value. The publish loop batches all values automatically."""
        if crio_channel.startswith('sys.'):
            self._sync_crio_system_state(crio_channel, value)
            return

        # Resolve cRIO channel name to local TAG name
        local_name = self._resolve_remote_channel(node_id, crio_channel)
        if not local_name:
            return

        # Store value — publish loop batches via _publish_channels_batch()
        self.channel_values[local_name] = value
        # Preserve cRIO hardware timestamp when available (don't overwrite with PC time)
        if acquisition_ts_us > 0:
            self.channel_timestamps[local_name] = acquisition_ts_us / 1_000_000.0
            self.channel_acquisition_ts_us[local_name] = acquisition_ts_us
        else:
            self.channel_timestamps[local_name] = time.time()
        if not hasattr(self, 'channel_qualities'):
            self.channel_qualities = {}
        self.channel_qualities[local_name] = quality

    def _resolve_remote_channel(self, node_id: str, crio_channel: str) -> Optional[str]:
        """Map a remote node channel name to the local TAG name, or None if not found."""
        # Direct TAG name match (remote node sends TAG names after config push)
        if crio_channel in self.config.channels:
            if self.config.channels[crio_channel].is_remote_node:
                return crio_channel

        # Fallback: physical_channel match
        for name, channel in self.config.channels.items():
            source_type = getattr(channel, 'source_type', 'local')
            source_node = getattr(channel, 'source_node_id', '')
            if source_type in ('crio', 'opto22') and source_node == node_id:
                if channel.physical_channel == crio_channel:
                    return name

        return None

    def _sync_crio_system_state(self, channel: str, value: Any):
        """Drop sys.* channels from cRIO — state is synced via dedicated MQTT topics.

        Acquiring: _handle_node_state_change (QoS 1 retained /state topic)
        Session: _handle_crio_session_status (dedicated /session/status topic)
        Recording: controlled via explicit commands only
        """
        pass

    def _handle_node_state_change(self, topic: str, payload: Dict[str, Any]):
        """Handle cRIO/edge node state transition (QoS 1, retained).

        The cRIO publishes to nodes/{node_id}/state on every state change.
        This replaces the old _sync_crio_system_state() polling approach and
        _stop_command_time cooldown hack with a reliable, retained signal.

        Args:
            topic: e.g. "nisystem/nodes/crio-001/state"
            payload: {node_id, old_state, new_state, reason, timestamp}
        """
        if not isinstance(payload, dict):
            return

        node_id = payload.get('node_id')
        old_state = payload.get('old_state', '?')
        new_state = payload.get('new_state', '?')
        reason = payload.get('reason', '')

        if not node_id:
            # Try to extract from topic
            parts = topic.split('/')
            for i, p in enumerate(parts):
                if p == 'nodes' and i + 1 < len(parts):
                    node_id = parts[i + 1]
                    break
        if not node_id:
            return

        logger.info(f"[NODE_STATE] {node_id}: {old_state} -> {new_state}"
                     f"{f' ({reason})' if reason else ''}")

        # Update device discovery tracking if available
        if self.device_discovery:
            # Look up node across all node type registries
            node_obj = None
            with getattr(self.device_discovery, '_crio_lock', threading.Lock()):
                crio_nodes = getattr(self.device_discovery, '_crio_nodes', {})
                if node_id in crio_nodes:
                    node_obj = crio_nodes[node_id]
            if node_obj is None:
                opto_nodes = getattr(self.device_discovery, '_opto22_nodes', {})
                if node_id in opto_nodes:
                    node_obj = opto_nodes[node_id]
            if node_obj is None:
                cfp_nodes = getattr(self.device_discovery, '_cfp_nodes', {})
                if node_id in cfp_nodes:
                    node_obj = cfp_nodes[node_id]
            if node_obj:
                node_obj.status = new_state.lower() if new_state in ('IDLE', 'ACQUIRING') else node_obj.status
                # Track state timestamp on the object if it has the attribute
                if hasattr(node_obj, 'last_seen'):
                    node_obj.last_seen = payload.get('timestamp', node_obj.last_seen)

        # Log significant transitions for debugging
        if new_state == 'ACQUIRING':
            logger.info(f"[NODE_STATE] {node_id} is now acquiring")
        elif new_state == 'IDLE' and old_state == 'ACQUIRING':
            logger.info(f"[NODE_STATE] {node_id} stopped acquiring")

    def _handle_crio_config_response(self, topic: str, payload: Dict[str, Any]):
        """
        Handle ACK from cRIO after config push.

        When cRIO receives and processes a config push, it publishes a response to
        {mqtt_base}/nodes/{node_id}/config/response with status and channel count.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/config/response")
            payload: Response payload with 'status', 'channels', 'config_version'
        """
        if not isinstance(payload, dict):
            return

        # Extract node_id from topic: nisystem/nodes/{node_id}/config/response
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        status = payload.get('status')
        channels = payload.get('channels', 0)
        config_version = payload.get('config_version', '')

        with self._crio_push_lock:
            if node_id in self._pending_crio_pushes:
                push_info = self._pending_crio_pushes.pop(node_id)
                attempts = push_info.get('attempts', 1)

                if status in ('ok', 'success'):
                    # Store the confirmed config version
                    if config_version:
                        self._crio_config_versions[node_id] = config_version
                    logger.info(f"cRIO {node_id} confirmed config: {channels} channels (attempt {attempts})")
                    self._publish_crio_response(
                        True, f"Config confirmed by {node_id}: {channels} channels",
                        node_id=node_id, config_version=config_version
                    )
                    # Signal any waiting threads (e.g., START command waiting for config ACK)
                    if node_id in self._crio_config_ack_events:
                        self._crio_config_ack_events[node_id].set()
                else:
                    error_msg = payload.get('error', payload.get('message', 'Unknown error'))
                    logger.error(f"cRIO {node_id} rejected config: {error_msg}")
                    self._publish_crio_response(False, f"Config rejected by {node_id}: {error_msg}")
            else:
                # Unexpected ACK (maybe from direct push or duplicate)
                logger.debug(f"cRIO {node_id} config response (no pending push): {status}")

    def _handle_crio_session_status(self, topic: str, payload: Dict[str, Any]):
        """
        Handle session status from cRIO (for CRIO mode - cRIO is source of truth).

        In CRIO project mode, cRIO owns the session state. PC reflects cRIO's state
        to maintain a consistent view for the dashboard.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/session/status")
            payload: Session status with 'active', 'name', 'operator', etc.
        """
        if not isinstance(payload, dict):
            return

        # Only process in CRIO mode
        if self.config.system.project_mode != ProjectMode.CRIO:
            return

        # Extract node_id from topic
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        # Update local session state to reflect cRIO's state
        active = payload.get('active', False)
        name = payload.get('name', '')
        operator = payload.get('operator', '')
        locked_outputs = payload.get('locked_outputs', [])
        start_time = payload.get('start_time')

        if self.user_variables:
            # Check if state actually changed (avoid spam logging and republishing)
            prev_active = self.user_variables.session.active
            prev_name = self.user_variables.session.name

            # Sync cRIO session state to local user_variables
            self.user_variables.session.active = active
            self.user_variables.session.name = name
            if start_time:
                # Convert to ISO string (started_at is a string field)
                if isinstance(start_time, str):
                    self.user_variables.session.started_at = start_time
                else:
                    self.user_variables.session.started_at = datetime.fromtimestamp(start_time).isoformat()
            else:
                self.user_variables.session.started_at = None
            self.user_variables.session.started_by = operator

            # Only log and republish when state changes
            if active != prev_active or name != prev_name:
                logger.info(f"[SESSION] Synced from cRIO {node_id}: active={active}, name={name}")
                # Publish updated status to dashboard
                self._publish_test_session_status()
                self._publish_user_variables_values()

    def _handle_crio_script_status(self, topic: str, payload: Dict[str, Any]):
        """
        Handle script status from cRIO (for CRIO mode - scripts run on cRIO).

        In CRIO project mode, scripts run on cRIO. PC relays cRIO's script status
        to the dashboard.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/script/status")
            payload: Script status dict with script IDs and running states
        """
        if not isinstance(payload, dict):
            return

        # Only process in CRIO mode
        if self.config.system.project_mode != ProjectMode.CRIO:
            return

        # Extract node_id from topic
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        logger.debug(f"[SCRIPT] Received script status from cRIO {node_id}: {len(payload)} scripts")

        # Relay cRIO script status to dashboard
        # The dashboard expects status on {base}/script/status
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/script/status",
            json.dumps(payload),
            retain=True
        )

    def _handle_crio_alarm_event(self, topic: str, payload: Dict[str, Any]):
        """
        Handle alarm event from cRIO (for CRIO mode - alarms evaluated on cRIO).

        In CRIO project mode, cRIO evaluates alarms locally. PC receives alarm events
        and relays them to the dashboard, also storing in alarm history.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/alarm/event")
            payload: Alarm event with 'channel', 'prev_state', 'new_state', 'value', etc.
        """
        if not isinstance(payload, dict):
            return

        # Only process in CRIO mode
        if self.config.system.project_mode != ProjectMode.CRIO:
            return

        # Extract node_id from topic
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        channel = payload.get('channel', '')
        prev_state = payload.get('prev_state', 'normal')
        new_state = payload.get('new_state', 'normal')
        value = payload.get('value')
        timestamp = payload.get('timestamp')

        logger.info(f"[ALARM] cRIO {node_id}: {channel} {prev_state} -> {new_state} (value={value})")

        # Dashboard receives alarm events directly from cRIO via per-alarm
        # retained topics (alarms/active/{alarm_id}). No DAQ relay needed.

    def _handle_crio_alarm_status(self, topic: str, payload: Dict[str, Any]):
        """
        Handle alarm status from cRIO (for CRIO mode - alarm counts/active alarms).

        In CRIO mode, cRIO publishes aggregate alarm status including active alarm
        counts and list of active alarms. We relay this to the dashboard.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/alarm/status")
            payload: Alarm status with 'active', 'acknowledged', 'returned', 'total', 'alarms'
        """
        if not isinstance(payload, dict):
            return

        # Only process in CRIO mode
        if self.config.system.project_mode != ProjectMode.CRIO:
            return

        # Extract node_id from topic
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        active = payload.get('active', 0)
        total = payload.get('total', 0)
        alarms = payload.get('alarms', [])

        if total > 0:
            logger.debug(f"[ALARM] cRIO {node_id} status: {active} active, {total} total")

        # Dashboard receives alarm status directly from cRIO via retained
        # alarms/status topic. No DAQ relay needed.

    def _handle_crio_command_ack(self, topic: str, payload: Dict[str, Any]):
        """
        Handle command acknowledgment from cRIO (for CRIO mode).

        When cRIO receives and processes a command (acquire/start, session/start, etc.),
        it publishes an ACK with success status, the command name, and current state.
        This allows us to sync our state with cRIO definitively.

        Args:
            topic: MQTT topic (e.g., "nisystem/nodes/crio-001/command/ack")
            payload: ACK with 'success', 'command', 'state', 'acquiring', 'session_active', etc.
        """
        if not isinstance(payload, dict):
            return

        # Only process in CRIO mode
        if self.config.system.project_mode != ProjectMode.CRIO:
            return

        # Extract node_id from topic
        parts = topic.split('/')
        node_id = None
        for i, p in enumerate(parts):
            if p == 'nodes' and i + 1 < len(parts):
                node_id = parts[i + 1]
                break

        if not node_id:
            return

        # Only process ACKs from registered cRIO nodes (not from ourselves)
        if self.device_discovery:
            crio_nodes = self.device_discovery.get_crio_nodes()
            is_crio_node = any(n.node_id == node_id for n in crio_nodes)
            if not is_crio_node:
                # This ACK is from a non-cRIO node (probably ourselves), ignore it
                return

        success = payload.get('success', False)
        command = payload.get('command', '')
        reason = payload.get('reason', '')
        request_id = payload.get('request_id', '')
        crio_state = payload.get('state', '')
        crio_acquiring = payload.get('acquiring', False)
        crio_session = payload.get('session_active', False)

        logger.info(f"[CRIO_ACK] {node_id} {command}: success={success}, state={crio_state}, "
                   f"acquiring={crio_acquiring}, session={crio_session}"
                   + (f", reason={reason}" if reason else ""))

        # Signal any waiting _stop_crio_nodes_and_wait() callers
        if command == 'acquire/stop' and hasattr(self, '_crio_stop_ack_events'):
            event = self._crio_stop_ack_events.get(node_id)
            if event:
                event.set()

        # Only sync acquisition/session state from acquire/session command ACKs.
        # Output ACKs don't include acquiring/session_active fields (they default to False),
        # so syncing from them would incorrectly kill acquisition.
        is_state_command = command in ('acquire/start', 'acquire/stop', 'session/start', 'session/stop')

        if is_state_command:
            current_state = self._state_machine.state
            if current_state in (DAQState.INITIALIZING, DAQState.STOPPING):
                logger.debug(f"[CRIO_ACK] Ignoring state sync during transition ({current_state.name})")
            elif self.acquiring != crio_acquiring:
                target = DAQState.RUNNING if crio_acquiring else DAQState.STOPPED
                logger.info(f"[CRIO_ACK] Syncing acquiring: {self.acquiring} -> {crio_acquiring}")
                self._state_machine.to(target)

            if self.user_variables and self.user_variables.session.active != crio_session:
                if current_state in (DAQState.INITIALIZING, DAQState.STOPPING):
                    logger.debug(f"[CRIO_ACK] Ignoring session sync during transition ({current_state.name})")
                else:
                    logger.info(f"[CRIO_ACK] Syncing session: {self.user_variables.session.active} -> {crio_session}")
                    self.user_variables.session.active = crio_session

        # Publish status update (including ACK details for dashboard feedback)
        self._publish_system_status(skip_resource_monitoring=True)

        # Relay ACK to dashboard for UI feedback
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/command/ack",
            json.dumps(payload)
        )

    def _handle_crio_push_config(self, node_id: str, config_data: Dict[str, Any]):
        """
        Push configuration to a cRIO node.

        Args:
            node_id: Target cRIO node ID
            config_data: Configuration to push (channels, scripts, etc.)
        """
        if not self.mqtt_client:
            return

        # Publish to cRIO node's config topic
        mqtt_base = self.config.system.mqtt_base_topic
        topic = f"{mqtt_base}/nodes/{node_id}/config/full"

        self.mqtt_client.publish(
            topic,
            json.dumps(config_data),
            qos=1
        )
        logger.info(f"Pushed config to cRIO node: {node_id}")

    def _check_crio_push_timeouts(self):
        """
        Check for timed-out cRIO config pushes and retry if needed.

        Called periodically from publish loop (~1Hz). Non-blocking - just iterates
        pending pushes and compares timestamps.
        """
        now = time.time()
        # Check cRIO pending pushes
        with self._crio_push_lock:
            for node_id, push_info in list(self._pending_crio_pushes.items()):
                elapsed = now - push_info['timestamp']
                if elapsed > self._CRIO_CONFIG_TIMEOUT:
                    if push_info['attempts'] < self._CRIO_CONFIG_MAX_RETRIES:
                        push_info['attempts'] += 1
                        push_info['timestamp'] = now
                        logger.warning(f"cRIO config push timeout for {node_id} - retrying (attempt {push_info['attempts']}/{self._CRIO_CONFIG_MAX_RETRIES})")
                        config_data = push_info['config']
                        threading.Thread(
                            target=self._handle_crio_push_config,
                            args=(node_id, config_data),
                            daemon=True
                        ).start()
                    else:
                        del self._pending_crio_pushes[node_id]
                        logger.error(f"cRIO config push to {node_id} failed after {self._CRIO_CONFIG_MAX_RETRIES} attempts - no ACK received")
                        self._publish_crio_response(
                            False,
                            f"Config push to {node_id} failed: no response after {self._CRIO_CONFIG_MAX_RETRIES} retries"
                        )

    def _handle_crio_push_config_request(self, payload: Dict[str, Any]):
        """
        Handle request from frontend to push config to a cRIO node.

        Payload: {
            "node_id": "crio-001",
            "channels": [...],       # Channel configs to push
            "scripts": [...],        # Python scripts to push
            "safe_state_outputs": [] # DO channels for safe state
        }
        """
        if not isinstance(payload, dict):
            self._publish_crio_response(False, "Invalid payload")
            return

        node_id = payload.get('node_id')
        if not node_id:
            self._publish_crio_response(False, "Missing node_id")
            return

        # Check if node is known - but don't fail if not found
        # The node may be online even if not yet registered (timing issue with retained messages)
        crio_nodes = self.device_discovery.get_crio_nodes()
        opto22_nodes = self.device_discovery.get_opto22_nodes()
        node_exists = any(n.node_id == node_id for n in crio_nodes) or \
                      any(n.node_id == node_id for n in opto22_nodes)
        if not node_exists:
            logger.warning(f"Node {node_id} not in discovery registry - pushing config anyway")

        # Build config to push
        # Convert channels list to dict if needed (dashboard sends list, cRIO expects dict)
        channels_raw = payload.get('channels', [])
        if isinstance(channels_raw, list):
            channels_dict = {ch.get('name'): ch for ch in channels_raw if ch.get('name')}
        else:
            channels_dict = channels_raw

        config_data = {
            'channels': channels_dict,
            'scripts': payload.get('scripts', []),
            'safe_state_outputs': payload.get('safe_state_outputs', []),
            'scan_rate_hz': payload.get('scan_rate_hz', 4),
            'publish_rate_hz': payload.get('publish_rate_hz', 4),
            'timestamp': datetime.now().isoformat()
        }

        # Use dashboard-provided config_version if available (allows dashboard
        # to track sync by comparing its own hash against cRIO's reported version).
        # Fall back to server-side MD5 hash for backwards compatibility.
        config_hash = payload.get('config_version')
        if not config_hash:
            import hashlib
            channels_str = json.dumps(config_data.get('channels', []), sort_keys=True)
            config_hash = hashlib.md5(channels_str.encode()).hexdigest()[:8]
        config_data['config_version'] = config_hash

        # Track this push for ACK/retry logic
        with self._crio_push_lock:
            self._pending_crio_pushes[node_id] = {
                'config': config_data,
                'attempts': 1,
                'timestamp': time.time(),
                'node_id': node_id,
                'config_version': config_hash
            }
            # Store expected version
            self._crio_config_versions[node_id] = config_hash

        # Push to cRIO node (don't report success yet - wait for ACK)
        self._handle_crio_push_config(node_id, config_data)
        logger.info(f"Config push initiated to {node_id} (version: {config_hash}, awaiting ACK...)")

    def _handle_crio_list_request(self):
        """Handle request to list all known cRIO nodes."""
        crio_nodes = self.device_discovery.get_crio_nodes()

        # Convert to serializable format
        nodes_list = []
        for node in crio_nodes:
            nodes_list.append({
                'node_id': node.node_id,
                'ip_address': node.ip_address,
                'product_type': node.product_type,
                'serial_number': node.serial_number,
                'status': node.status,
                'last_seen': node.last_seen,
                'channels': node.channels,
                'modules': [
                    {
                        'name': m.name,
                        'slot': m.slot,
                        'product_type': m.product_type,
                        'description': m.description,
                        'channels': [
                            {
                                'name': c.name,
                                'channel_type': c.channel_type,
                                'description': c.description,
                                'category': c.category
                            }
                            for c in (m.channels or [])
                        ]
                    }
                    for m in (node.modules or [])
                ]
            })

        self._publish_crio_list(nodes_list)

    def _publish_crio_response(self, success: bool, message: str,
                               node_id: str = '', config_version: str = ''):
        """Publish response to cRIO operation."""
        if not self.mqtt_client:
            return

        mqtt_base = self.config.system.mqtt_base_topic
        topic = f"{mqtt_base}/crio/response"

        payload: Dict[str, Any] = {
            'success': success,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        if node_id:
            payload['node_id'] = node_id
        if config_version:
            payload['config_version'] = config_version

        self.mqtt_client.publish(topic, json.dumps(payload), qos=1)

    def _publish_crio_list(self, nodes: list):
        """Publish list of cRIO nodes."""
        if not self.mqtt_client:
            return

        mqtt_base = self.config.system.mqtt_base_topic
        topic = f"{mqtt_base}/crio/list/response"

        self.mqtt_client.publish(
            topic,
            json.dumps({
                'success': True,
                'nodes': nodes,
                'count': len(nodes),
                'timestamp': datetime.now().isoformat()
            }),
            qos=1
        )

    # ── Node Health Check ────────────────────────────────────────────────────

    def _check_node_credential_health(self):
        """Check offline nodes — publish diagnostic if reachable but not on MQTT.

        Port 8883 is anonymous (TLS-only), so credential desync is no longer
        possible. This check helps diagnose other connectivity issues like
        missing TLS certs or service crashes.
        """
        if not self.mqtt_client or not self.device_discovery:
            return

        offline_nodes = self.device_discovery.get_offline_nodes()
        if not offline_nodes:
            return

        base = self.get_topic_base()

        for node_id, info in offline_nodes.items():
            ip = info['ip_address']
            try:
                reachable = self.device_discovery.check_node_reachable(ip, port=22, timeout=2.0)
            except Exception:
                reachable = False

            if reachable:
                logger.info(f"Node {node_id} ({ip}) is reachable but offline on MQTT — service may need redeploy")
                self.mqtt_client.publish(
                    f"{base}/nodes/{node_id}/credential_status",
                    json.dumps({
                        'node_id': node_id,
                        'ip_address': ip,
                        'node_type': info.get('node_type', 'unknown'),
                        'product_type': info.get('product_type', ''),
                        'reachable': True,
                        'mqtt_connected': False,
                        'diagnosis': 'offline_reachable',
                        'message': f'{info.get("product_type", "Node")} at {ip} is reachable but not connecting to MQTT. Run the deploy script to reinstall.',
                        'timestamp': datetime.now().isoformat(),
                    }),
                    qos=1
                )

    def _forward_acquisition_command_to_crio(self, command: str, request_id: Optional[str] = None):
        """
        Forward acquisition start/stop commands to all known cRIO nodes.
        On 'start', also pushes the channel configuration so cRIO knows TAG names.

        Args:
            command: 'start' or 'stop'
            request_id: Optional request ID for command correlation
        """
        if not self.mqtt_client or not self.device_discovery:
            return

        crio_nodes = self.device_discovery.get_crio_nodes()
        if not crio_nodes:
            return

        mqtt_base = self.config.system.mqtt_base_topic

        # Generate request_id if not provided (for ACK correlation)
        if not request_id:
            request_id = str(uuid.uuid4())

        for node in crio_nodes:
            if node.status != 'online':
                continue

            # On start: push config if cRIO doesn't have confirmed config.
            # Cancel any pending debounce timer first to prevent race where
            # channels were modified but debounce hasn't fired yet.
            if command == 'start':
                with self._crio_push_lock:
                    if self._crio_push_debounce_timer:
                        self._crio_push_debounce_timer.cancel()
                        self._crio_push_debounce_timer = None
                        self._crio_config_versions.clear()
                        logger.debug("[START] Cancelled pending debounce timer, cleared config versions")
                    has_confirmed_config = node.node_id in self._crio_config_versions

                if has_confirmed_config:
                    logger.info(f"cRIO {node.node_id} already has confirmed config - sending start directly")
                else:
                    # Fire-and-forget config push — don't block the start path.
                    # The cRIO handles config arriving during acquisition via
                    # internal was_acquiring restart.  Config ACK still arrives
                    # on config/response for diagnostics/logging.
                    logger.info(f"cRIO {node.node_id} has no confirmed config — pushing (fire-and-forget)")
                    self._push_crio_channel_config(node.node_id)

            topic = f"{mqtt_base}/nodes/{node.node_id}/system/acquire/{command}"
            self.mqtt_client.publish(
                topic,
                json.dumps({
                    'command': command,
                    'request_id': request_id,
                    'timestamp': datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"Forwarded acquisition {command} to cRIO: {node.node_id} (request_id={request_id[:8]})")

    def _stop_crio_nodes_and_wait(self, request_id: Optional[str] = None, timeout_s: float = 5.0) -> bool:
        """Forward acquisition stop to all online cRIO nodes and wait for ACK.

        Returns True if all cRIOs acknowledged (or no cRIOs online), False on timeout.
        """
        if not self.mqtt_client or not self.device_discovery:
            return True  # No cRIO infrastructure — nothing to wait for

        crio_nodes = self.device_discovery.get_crio_nodes()
        online_nodes = [n for n in crio_nodes if n.status == 'online']
        if not online_nodes:
            return True  # No online cRIOs

        mqtt_base = self.config.system.mqtt_base_topic
        stop_request_id = request_id or str(uuid.uuid4())

        # Set up ACK tracking events
        pending_acks: Dict[str, threading.Event] = {}
        for node in online_nodes:
            pending_acks[node.node_id] = threading.Event()
        self._crio_stop_ack_events = pending_acks

        # Publish stop to all online cRIOs
        for node in online_nodes:
            topic = f"{mqtt_base}/nodes/{node.node_id}/system/acquire/stop"
            self.mqtt_client.publish(
                topic,
                json.dumps({
                    'command': 'stop',
                    'request_id': stop_request_id,
                    'timestamp': datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"[STOP] Sent acquire/stop to cRIO {node.node_id}")

        # Wait for all ACKs (or timeout)
        all_ok = True
        deadline = time.time() + timeout_s
        for node_id, event in pending_acks.items():
            remaining = max(0.1, deadline - time.time())
            if not event.wait(timeout=remaining):
                logger.warning(f"[STOP] cRIO {node_id} did not ACK stop within {timeout_s}s")
                all_ok = False
            else:
                logger.info(f"[STOP] cRIO {node_id} confirmed stop")

        self._crio_stop_ack_events = {}
        return all_ok

    def _forward_safe_state_to_crio(self, reason: str, request_id: Optional[str] = None):
        """
        Forward atomic safe-state command to all online cRIO nodes.

        Sends a single MQTT message per cRIO that triggers hardware.set_safe_state()
        on the cRIO, setting ALL outputs to safe values atomically. This is more
        reliable than sending individual per-channel output commands.
        """
        if not self.mqtt_client or not self.device_discovery:
            return

        crio_nodes = self.device_discovery.get_crio_nodes()
        if not crio_nodes:
            return

        mqtt_base = self.config.system.mqtt_base_topic

        for node in crio_nodes:
            if node.status != 'online':
                logger.warning(f"[SAFE STATE] cRIO {node.node_id} is offline - cannot forward safe-state")
                continue

            topic = f"{mqtt_base}/nodes/{node.node_id}/safety/safe-state"
            self.mqtt_client.publish(
                topic,
                json.dumps({
                    'reason': reason,
                    'request_id': request_id or '',
                    'timestamp': datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"[SAFE STATE] Forwarded atomic safe-state to cRIO: {node.node_id}")

    def _forward_alarm_ack_to_crio(self, channel: str, user: str):
        """
        Forward alarm acknowledgment to all known cRIO nodes.

        In CRIO mode, cRIO owns alarm state. When user acknowledges an alarm
        in the dashboard, we forward to cRIO so it can update its alarm state.

        Args:
            channel: Channel name or alarm ID to acknowledge
            user: User who acknowledged
        """
        if not self.mqtt_client or not self.device_discovery:
            return

        crio_nodes = self.device_discovery.get_crio_nodes()
        if not crio_nodes:
            return

        mqtt_base = self.config.system.mqtt_base_topic

        for node in crio_nodes:
            if node.status != 'online':
                continue

            topic = f"{mqtt_base}/nodes/{node.node_id}/alarm/acknowledge"
            self.mqtt_client.publish(
                topic,
                json.dumps({
                    'channel': channel,
                    'user': user,
                    'timestamp': datetime.now().isoformat()
                }),
                qos=1
            )
            logger.info(f"Forwarded alarm ack to cRIO: {node.node_id} channel={channel}")

    def _push_config_to_all_crio_nodes(self):
        """
        Push channel configuration to all known online cRIO, Opto22, and CFP nodes.
        Called automatically after project load/import to ensure remote nodes
        have the TAG name -> physical channel mappings.

        Each node receives only its own channels:
        - cRIO: filtered by physical_channel.startswith('Mod')
        - Opto22: filtered by source_type=='opto22' and source_node_id match
        - CFP: filtered by source_type=='cfp' and source_node_id match
        So multiple nodes of the same type get independent configs.
        """
        if not self.mqtt_client or not self.device_discovery:
            return

        pushed = 0

        # Push to cRIO nodes
        crio_nodes = self.device_discovery.get_crio_nodes()
        for node in (crio_nodes or []):
            if node.status != 'online':
                logger.debug(f"Skipping offline cRIO node: {node.node_id}")
                continue
            logger.info(f"Auto-pushing config to cRIO node: {node.node_id}")
            self._push_crio_channel_config(node.node_id)
            pushed += 1

        # Push to Opto22 nodes
        opto22_nodes = self.device_discovery.get_opto22_nodes()
        for node in (opto22_nodes or []):
            if node.status != 'online':
                logger.debug(f"Skipping offline Opto22 node: {node.node_id}")
                continue
            logger.info(f"Auto-pushing config to Opto22 node: {node.node_id}")
            self._push_opto22_channel_config(node.node_id)
            pushed += 1

        # Push to CFP nodes
        cfp_nodes = self.device_discovery.get_cfp_nodes()
        for node in (cfp_nodes or []):
            if node.status != 'online':
                logger.debug(f"Skipping offline CFP node: {node.node_id}")
                continue
            logger.info(f"Auto-pushing config to CFP node: {node.node_id}")
            self._push_cfp_channel_config(node.node_id)
            pushed += 1

        if pushed > 0:
            logger.info(f"Auto-pushed config to {pushed} remote node(s) after project load")

    def _push_crio_channel_config(self, node_id: str):
        """
        Push channel configuration to a cRIO node.

        Filters channels that belong to cRIO (physical_channel starts with 'Mod')
        and sends them with TAG names so cRIO can map TAG -> physical channel.

        Args:
            node_id: Target cRIO node ID (e.g., 'crio-001')
        """
        if not self.mqtt_client or not self.config:
            return

        # Filter channels belonging to this cRIO node by source_type + source_node_id
        # Fallback: if no source_type set, match by physical_channel starting with 'Mod'
        # Build as dict keyed by TAG name (cRIO expects dict, not list)
        crio_channels = {}
        for name, channel in self.config.channels.items():
            source_type = getattr(channel, 'source_type', 'local') or 'local'
            source_node = getattr(channel, 'source_node_id', '') or ''
            physical_ch = getattr(channel, 'physical_channel', '') or ''
            # Match by source_type/node_id (preferred), or by physical_channel for legacy configs
            is_crio_channel = (
                (source_type == 'crio' and source_node == node_id) or
                (source_type == 'local' and physical_ch.startswith('Mod'))
            )
            if is_crio_channel:
                # Build channel config dict with TAG name as 'name' field
                ch_dict = {
                    'name': name,  # TAG name (e.g., 'tag_72')
                    'physical_channel': physical_ch,  # e.g., 'Mod4/port0/line0'
                    'channel_type': channel.channel_type.value if hasattr(channel.channel_type, 'value') else str(channel.channel_type),
                }
                # Add optional fields if present
                if hasattr(channel, 'thermocouple_type') and channel.thermocouple_type:
                    # Convert enum to string value if needed
                    tc_type = channel.thermocouple_type
                    ch_dict['thermocouple_type'] = tc_type.value if hasattr(tc_type, 'value') else str(tc_type)
                if hasattr(channel, 'default_state'):
                    ch_dict['default_state'] = channel.default_state
                if hasattr(channel, 'invert'):
                    ch_dict['invert'] = channel.invert
                if hasattr(channel, 'scale_slope') and channel.scale_slope is not None:
                    ch_dict['scale_slope'] = channel.scale_slope
                if hasattr(channel, 'scale_offset') and channel.scale_offset is not None:
                    ch_dict['scale_offset'] = channel.scale_offset
                # Full scaling params (map, 4-20mA) — ISA-95 Level 1 scaling
                ch_dict['scale_type'] = getattr(channel, 'scale_type', 'none') or 'none'
                ch_dict['four_twenty_scaling'] = getattr(channel, 'four_twenty_scaling', False)
                for attr in ('eng_units_min', 'eng_units_max',
                             'pre_scaled_min', 'pre_scaled_max',
                             'scaled_min', 'scaled_max'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val
                if hasattr(channel, 'unit') and channel.unit:
                    ch_dict['unit'] = channel.unit
                # Alarm configuration (ISA-18.2)
                if hasattr(channel, 'alarm_enabled'):
                    ch_dict['alarm_enabled'] = channel.alarm_enabled
                if hasattr(channel, 'hihi_limit') and channel.hihi_limit is not None:
                    ch_dict['hihi_limit'] = channel.hihi_limit
                if hasattr(channel, 'hi_limit') and channel.hi_limit is not None:
                    ch_dict['hi_limit'] = channel.hi_limit
                if hasattr(channel, 'lo_limit') and channel.lo_limit is not None:
                    ch_dict['lo_limit'] = channel.lo_limit
                if hasattr(channel, 'lolo_limit') and channel.lolo_limit is not None:
                    ch_dict['lolo_limit'] = channel.lolo_limit
                # Legacy limits (backward compatibility)
                if hasattr(channel, 'high_limit') and channel.high_limit is not None:
                    ch_dict['high_limit'] = channel.high_limit
                if hasattr(channel, 'low_limit') and channel.low_limit is not None:
                    ch_dict['low_limit'] = channel.low_limit
                # Alarm parameters
                if hasattr(channel, 'alarm_priority') and channel.alarm_priority:
                    ch_dict['alarm_priority'] = channel.alarm_priority
                if hasattr(channel, 'alarm_deadband') and channel.alarm_deadband is not None:
                    ch_dict['alarm_deadband'] = channel.alarm_deadband
                if hasattr(channel, 'alarm_delay_sec') and channel.alarm_delay_sec is not None:
                    ch_dict['alarm_delay_sec'] = channel.alarm_delay_sec
                if hasattr(channel, 'alarm_off_delay_sec') and channel.alarm_off_delay_sec is not None:
                    ch_dict['alarm_off_delay_sec'] = channel.alarm_off_delay_sec
                if hasattr(channel, 'rate_of_change_limit') and channel.rate_of_change_limit is not None:
                    ch_dict['rate_of_change_limit'] = channel.rate_of_change_limit
                if hasattr(channel, 'rate_of_change_period_s') and channel.rate_of_change_period_s is not None:
                    ch_dict['rate_of_change_period_s'] = channel.rate_of_change_period_s
                # Safety configuration (for autonomous cRIO safety)
                if hasattr(channel, 'safety_action') and channel.safety_action:
                    ch_dict['safety_action'] = channel.safety_action
                if hasattr(channel, 'safety_interlock') and channel.safety_interlock:
                    ch_dict['safety_interlock'] = channel.safety_interlock
                # Expected state for digital inputs (safety check)
                if hasattr(channel, 'digital_expected_state') and channel.digital_expected_state:
                    # Convert 'HIGH'/'LOW' to True/False for cRIO
                    ch_dict['expected_state'] = channel.digital_expected_state.upper() == 'HIGH'

                # Resistance measurement params
                for attr in ('resistance_range', 'resistance_wiring'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val

                # Counter input params
                for attr in ('counter_mode', 'counter_edge', 'counter_min_freq', 'counter_max_freq'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val

                # Pulse/counter output params
                for attr in ('pulse_frequency', 'pulse_duty_cycle', 'pulse_idle_state'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val

                # Relay params
                for attr in ('relay_type', 'momentary_pulse_ms'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val

                crio_channels[name] = ch_dict

        if not crio_channels:
            logger.debug(f"No cRIO channels to push to {node_id}")
            return

        # Build safety_actions dict for cRIO (filter to cRIO-relevant outputs only)
        safety_actions_data = {}
        if hasattr(self.config, 'safety_actions'):
            for action_name, action in self.config.safety_actions.items():
                crio_actions = {}
                for ch_name, value in action.actions.items():
                    ch = self.config.channels.get(ch_name)
                    if ch and getattr(ch, 'physical_channel', '').startswith('Mod'):
                        crio_actions[ch_name] = value
                if crio_actions:
                    safety_actions_data[action_name] = {
                        'name': action_name,
                        'description': getattr(action, 'description', ''),
                        'actions': crio_actions,
                        'trigger_alarm': getattr(action, 'trigger_alarm', False),
                        'alarm_message': getattr(action, 'alarm_message', '')
                    }

        # Build interlocks for this node (filter to interlocks with controls on node channels)
        # Edge nodes only support: channel_value, digital_input, alarm_active,
        # no_active_alarms, acquiring. DAQ-only types fail-open on the node,
        # so skip interlocks whose conditions are ALL DAQ-only.
        _DAQ_ONLY_CONDITION_TYPES = {
            'mqtt_connected', 'daq_connected', 'not_recording',
            'variable_value', 'expression'
        }
        node_interlocks = []
        if self.safety_manager:
            crio_channel_names = set(crio_channels.keys())
            for interlock in self.safety_manager.get_all_interlocks():
                # Include if any control targets a channel on this node
                has_node_control = any(
                    ctrl.channel in crio_channel_names
                    for ctrl in interlock.controls
                    if ctrl.channel
                )
                # Also include stop_session controls (no channel, applicable everywhere)
                has_stop = any(
                    ctrl.control_type == 'stop_session'
                    for ctrl in interlock.controls
                )
                if has_node_control or has_stop:
                    # Skip if ALL conditions are DAQ-only (interlock can never trip on node)
                    if interlock.conditions and all(
                        c.condition_type in _DAQ_ONLY_CONDITION_TYPES
                        for c in interlock.conditions
                    ):
                        logger.warning(
                            f"Interlock '{interlock.name}' has only DAQ-only conditions "
                            f"— skipping push to node (DAQ will evaluate it)")
                        continue
                    node_interlocks.append(interlock.to_dict())

        # Build safe state config for this node
        safe_state_data = None
        if self.safety_manager:
            safe_state_data = self.safety_manager.safe_state_config.to_dict()

        # Generate config version hash (includes channels + safety_actions + rates)
        import hashlib
        config_for_hash = {
            'channels': crio_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz
        }
        config_str = json.dumps(config_for_hash, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

        # Build and publish config
        mqtt_base = self.config.system.mqtt_base_topic
        config_data = {
            'channels': crio_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'scripts': [],
            'safe_state_outputs': [],
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz,
            'di_poll_rate_hz': getattr(self.config.system, 'di_poll_rate_hz', 20.0),
            'watchdog_output': {
                'enabled': self.config.system.watchdog_output_enabled,
                'channel': self.config.system.watchdog_output_channel,
                'rate_hz': self.config.system.watchdog_output_rate_hz
            },
            'timestamp': datetime.now().isoformat(),
            'config_version': config_hash
        }
        if safe_state_data:
            config_data['safe_state_config'] = safe_state_data

        # Track this push for ACK/retry logic
        with self._crio_push_lock:
            self._pending_crio_pushes[node_id] = {
                'config': config_data,
                'attempts': 1,
                'timestamp': time.time(),
                'node_id': node_id,
                'config_version': config_hash
            }
            # Store expected version
            self._crio_config_versions[node_id] = config_hash

        topic = f"{mqtt_base}/nodes/{node_id}/config/full"
        self.mqtt_client.publish(topic, json.dumps(config_data), qos=1)
        logger.info(f"Pushed {len(crio_channels)} channels + {len(safety_actions_data)} safety actions + {len(node_interlocks)} interlocks to cRIO {node_id} (version: {config_hash})")

        # Clean up any stale channel values after config push
        self._cleanup_stale_channel_values()

    def _push_opto22_channel_config(self, node_id: str):
        """
        Push channel configuration to an Opto22 node.

        Filters channels that belong to Opto22 (source_type == 'opto22' and
        source_node_id matches) and sends them so the node can run safety,
        scripts, PID, sequences, and watchdog autonomously.

        Args:
            node_id: Target Opto22 node ID (e.g., 'opto22-001')
        """
        if not self.mqtt_client or not self.config:
            return

        # Filter channels that belong to this Opto22 node
        opto22_channels = {}
        for name, channel in self.config.channels.items():
            source_type = getattr(channel, 'source_type', 'local') or 'local'
            source_node = getattr(channel, 'source_node_id', '') or ''
            if source_type == 'opto22' and source_node == node_id:
                ch_dict = {
                    'name': name,
                    'physical_channel': getattr(channel, 'physical_channel', '') or '',
                    'channel_type': channel.channel_type.value if hasattr(channel.channel_type, 'value') else str(channel.channel_type),
                }
                # Optional fields
                if hasattr(channel, 'thermocouple_type') and channel.thermocouple_type:
                    tc_type = channel.thermocouple_type
                    ch_dict['thermocouple_type'] = tc_type.value if hasattr(tc_type, 'value') else str(tc_type)
                if hasattr(channel, 'default_state'):
                    ch_dict['default_state'] = channel.default_state
                if hasattr(channel, 'invert'):
                    ch_dict['invert'] = channel.invert
                # Scaling params
                if hasattr(channel, 'scale_slope') and channel.scale_slope is not None:
                    ch_dict['scale_slope'] = channel.scale_slope
                if hasattr(channel, 'scale_offset') and channel.scale_offset is not None:
                    ch_dict['scale_offset'] = channel.scale_offset
                ch_dict['scale_type'] = getattr(channel, 'scale_type', 'none') or 'none'
                ch_dict['four_twenty_scaling'] = getattr(channel, 'four_twenty_scaling', False)
                for attr in ('eng_units_min', 'eng_units_max',
                             'pre_scaled_min', 'pre_scaled_max',
                             'scaled_min', 'scaled_max'):
                    val = getattr(channel, attr, None)
                    if val is not None:
                        ch_dict[attr] = val
                if hasattr(channel, 'unit') and channel.unit:
                    ch_dict['unit'] = channel.unit
                # Alarm configuration (ISA-18.2)
                if hasattr(channel, 'alarm_enabled'):
                    ch_dict['alarm_enabled'] = channel.alarm_enabled
                for limit_attr in ('hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit',
                                   'high_limit', 'low_limit'):
                    val = getattr(channel, limit_attr, None)
                    if val is not None:
                        ch_dict[limit_attr] = val
                if hasattr(channel, 'alarm_priority') and channel.alarm_priority:
                    ch_dict['alarm_priority'] = channel.alarm_priority
                if hasattr(channel, 'alarm_deadband') and channel.alarm_deadband is not None:
                    ch_dict['alarm_deadband'] = channel.alarm_deadband
                if hasattr(channel, 'alarm_delay_sec') and channel.alarm_delay_sec is not None:
                    ch_dict['alarm_delay_sec'] = channel.alarm_delay_sec
                if hasattr(channel, 'alarm_off_delay_sec') and channel.alarm_off_delay_sec is not None:
                    ch_dict['alarm_off_delay_sec'] = channel.alarm_off_delay_sec
                if hasattr(channel, 'rate_of_change_limit') and channel.rate_of_change_limit is not None:
                    ch_dict['rate_of_change_limit'] = channel.rate_of_change_limit
                if hasattr(channel, 'rate_of_change_period_s') and channel.rate_of_change_period_s is not None:
                    ch_dict['rate_of_change_period_s'] = channel.rate_of_change_period_s
                # Safety configuration
                if hasattr(channel, 'safety_action') and channel.safety_action:
                    ch_dict['safety_action'] = channel.safety_action
                if hasattr(channel, 'safety_interlock') and channel.safety_interlock:
                    ch_dict['safety_interlock'] = channel.safety_interlock
                # groov-specific fields
                if hasattr(channel, 'groov_topic') and channel.groov_topic:
                    ch_dict['groov_topic'] = channel.groov_topic
                if hasattr(channel, 'groov_module_index') and channel.groov_module_index is not None:
                    ch_dict['groov_module_index'] = channel.groov_module_index
                if hasattr(channel, 'groov_channel_index') and channel.groov_channel_index is not None:
                    ch_dict['groov_channel_index'] = channel.groov_channel_index

                opto22_channels[name] = ch_dict

        if not opto22_channels:
            logger.debug(f"No Opto22 channels to push to {node_id}")
            return

        # Build safety_actions dict (filter to Opto22-relevant outputs only)
        safety_actions_data = {}
        if hasattr(self.config, 'safety_actions'):
            for action_name, action in self.config.safety_actions.items():
                node_actions = {}
                for ch_name, value in action.actions.items():
                    if ch_name in opto22_channels:
                        node_actions[ch_name] = value
                if node_actions:
                    safety_actions_data[action_name] = {
                        'name': action_name,
                        'description': getattr(action, 'description', ''),
                        'actions': node_actions,
                        'trigger_alarm': getattr(action, 'trigger_alarm', False),
                        'alarm_message': getattr(action, 'alarm_message', '')
                    }

        # Build interlocks for this node (filter to interlocks with controls on node channels)
        _DAQ_ONLY_CONDITION_TYPES = {
            'mqtt_connected', 'daq_connected', 'not_recording',
            'variable_value', 'expression'
        }
        node_interlocks = []
        if self.safety_manager:
            opto22_channel_names = set(opto22_channels.keys())
            for interlock in self.safety_manager.get_all_interlocks():
                has_node_control = any(
                    ctrl.channel in opto22_channel_names
                    for ctrl in interlock.controls
                    if ctrl.channel
                )
                has_stop = any(
                    ctrl.control_type == 'stop_session'
                    for ctrl in interlock.controls
                )
                if has_node_control or has_stop:
                    if interlock.conditions and all(
                        c.condition_type in _DAQ_ONLY_CONDITION_TYPES
                        for c in interlock.conditions
                    ):
                        logger.warning(
                            f"Interlock '{interlock.name}' has only DAQ-only conditions "
                            f"— skipping push to Opto22 node (DAQ will evaluate it)")
                        continue
                    node_interlocks.append(interlock.to_dict())

        # Build safe state config
        safe_state_data = None
        if self.safety_manager:
            safe_state_data = self.safety_manager.safe_state_config.to_dict()

        # Generate config version hash
        import hashlib
        config_for_hash = {
            'channels': opto22_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz
        }
        config_str = json.dumps(config_for_hash, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

        # Build CODESYS config section (PID loops + register map for deterministic control)
        codesys_config_data = None
        if self.pid_engine:
            opto22_channel_names = set(opto22_channels.keys())
            codesys_pid_loops = []
            for loop_id, loop in self.pid_engine.loops.items():
                # Include PID loops whose PV or CV channel belongs to this node
                if loop.pv_channel in opto22_channel_names or (
                    loop.cv_channel and loop.cv_channel in opto22_channel_names
                ):
                    codesys_pid_loops.append(loop.to_config_dict())

            if codesys_pid_loops or node_interlocks:
                codesys_config_data = {
                    'enabled': True,
                    'pid_loops': codesys_pid_loops,
                    'register_map_version': '1.0',
                    'interlock_count': len(node_interlocks),
                    'channel_count': len(opto22_channels),
                }

        # Build and publish config
        mqtt_base = self.config.system.mqtt_base_topic
        config_data = {
            'channels': opto22_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'safe_state_outputs': [],
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz,
            'watchdog_output': {
                'enabled': self.config.system.watchdog_output_enabled,
                'channel': self.config.system.watchdog_output_channel,
                'rate_hz': self.config.system.watchdog_output_rate_hz
            },
            'timestamp': datetime.now().isoformat(),
            'config_version': config_hash
        }
        if safe_state_data:
            config_data['safe_state_config'] = safe_state_data
        if codesys_config_data:
            config_data['codesys_config'] = codesys_config_data

        # Store expected version for sync tracking
        self._opto22_config_versions[node_id] = config_hash

        topic = f"{mqtt_base}/nodes/{node_id}/config/full"
        self.mqtt_client.publish(topic, json.dumps(config_data), qos=1)
        codesys_info = ""
        if codesys_config_data:
            codesys_info = f" + CODESYS ({len(codesys_config_data.get('pid_loops', []))} PID loops)"
        logger.info(f"Pushed {len(opto22_channels)} channels + {len(safety_actions_data)} safety actions + {len(node_interlocks)} interlocks{codesys_info} to Opto22 {node_id} (version: {config_hash})")

        self._cleanup_stale_channel_values()

    def _push_cfp_channel_config(self, node_id: str):
        """
        Push channel configuration to a CompactFieldPoint (CFP) node.

        Filters channels where source_type == 'cfp' and source_node_id matches,
        builds Modbus-specific channel config dicts (address, register_type,
        data_type, slave_id), filters interlocks with controls targeting this
        node's channels, and publishes to the node's config/full topic.

        Args:
            node_id: Target CFP node ID (e.g., 'cfp-001')
        """
        if not self.mqtt_client or not self.config:
            return

        # Filter channels that belong to this CFP node
        cfp_channels = {}
        for name, channel in self.config.channels.items():
            source_type = getattr(channel, 'source_type', 'local') or 'local'
            source_node = getattr(channel, 'source_node_id', '') or ''
            if source_type == 'cfp' and source_node == node_id:
                ch_dict = {
                    'name': name,
                    'channel_type': channel.channel_type.value if hasattr(channel.channel_type, 'value') else str(channel.channel_type),
                }
                # Modbus-specific fields (CFP uses Modbus transport)
                if hasattr(channel, 'modbus_address') and channel.modbus_address is not None:
                    ch_dict['address'] = channel.modbus_address
                elif hasattr(channel, 'register_address') and channel.register_address is not None:
                    ch_dict['address'] = channel.register_address
                else:
                    ch_dict['address'] = 0
                ch_dict['register_type'] = getattr(channel, 'register_type', 'holding') or 'holding'
                ch_dict['data_type'] = getattr(channel, 'data_type', 'int16') or 'int16'
                ch_dict['slave_id'] = getattr(channel, 'modbus_slave_id', getattr(channel, 'slave_id', 1)) or 1

                # Scaling (CFP uses scale/offset rather than scale_slope/scale_offset)
                scale_slope = getattr(channel, 'scale_slope', None)
                scale_offset = getattr(channel, 'scale_offset', None)
                if scale_slope is not None:
                    ch_dict['scale'] = scale_slope
                if scale_offset is not None:
                    ch_dict['offset'] = scale_offset

                # Writable flag (output channels)
                ch_type_str = ch_dict['channel_type']
                is_output = ch_type_str in (
                    'voltage_output', 'current_output', 'digital_output',
                    'counter_output', 'pulse_output', 'modbus_coil'
                )
                ch_dict['writable'] = is_output
                if hasattr(channel, 'default_state'):
                    ch_dict['default_value'] = channel.default_state

                # Unit
                if hasattr(channel, 'unit') and channel.unit:
                    ch_dict['unit'] = channel.unit

                # Alarm configuration (ISA-18.2)
                if hasattr(channel, 'alarm_enabled'):
                    ch_dict['alarm_enabled'] = channel.alarm_enabled
                for limit_attr in ('hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit',
                                   'high_limit', 'low_limit'):
                    val = getattr(channel, limit_attr, None)
                    if val is not None:
                        ch_dict[limit_attr] = val
                if hasattr(channel, 'alarm_deadband') and channel.alarm_deadband is not None:
                    ch_dict['alarm_deadband'] = channel.alarm_deadband
                if hasattr(channel, 'alarm_delay_sec') and channel.alarm_delay_sec is not None:
                    ch_dict['alarm_delay_sec'] = channel.alarm_delay_sec
                if hasattr(channel, 'alarm_priority') and channel.alarm_priority:
                    ch_dict['alarm_priority'] = channel.alarm_priority
                if hasattr(channel, 'alarm_off_delay_sec') and channel.alarm_off_delay_sec is not None:
                    ch_dict['alarm_off_delay_sec'] = channel.alarm_off_delay_sec
                if hasattr(channel, 'rate_of_change_limit') and channel.rate_of_change_limit is not None:
                    ch_dict['rate_of_change_limit'] = channel.rate_of_change_limit
                if hasattr(channel, 'rate_of_change_period_s') and channel.rate_of_change_period_s is not None:
                    ch_dict['rate_of_change_period_s'] = channel.rate_of_change_period_s

                # Safety configuration
                if hasattr(channel, 'safety_action') and channel.safety_action:
                    ch_dict['safety_action'] = channel.safety_action
                if hasattr(channel, 'safety_interlock') and channel.safety_interlock:
                    ch_dict['safety_interlock'] = channel.safety_interlock

                cfp_channels[name] = ch_dict

        if not cfp_channels:
            logger.debug(f"No CFP channels to push to {node_id}")
            return

        # Build safety_actions dict (filter to CFP-relevant outputs only)
        safety_actions_data = {}
        if hasattr(self.config, 'safety_actions'):
            for action_name, action in self.config.safety_actions.items():
                node_actions = {}
                for ch_name, value in action.actions.items():
                    if ch_name in cfp_channels:
                        node_actions[ch_name] = value
                if node_actions:
                    safety_actions_data[action_name] = {
                        'name': action_name,
                        'description': getattr(action, 'description', ''),
                        'actions': node_actions,
                        'trigger_alarm': getattr(action, 'trigger_alarm', False),
                        'alarm_message': getattr(action, 'alarm_message', '')
                    }

        # Build interlocks for this node (filter to interlocks with controls on node channels)
        _DAQ_ONLY_CONDITION_TYPES = {
            'mqtt_connected', 'daq_connected', 'not_recording',
            'variable_value', 'expression'
        }
        node_interlocks = []
        if self.safety_manager:
            cfp_channel_names = set(cfp_channels.keys())
            for interlock in self.safety_manager.get_all_interlocks():
                has_node_control = any(
                    ctrl.channel in cfp_channel_names
                    for ctrl in interlock.controls
                    if ctrl.channel
                )
                has_stop = any(
                    ctrl.control_type == 'stop_session'
                    for ctrl in interlock.controls
                )
                if has_node_control or has_stop:
                    if interlock.conditions and all(
                        c.condition_type in _DAQ_ONLY_CONDITION_TYPES
                        for c in interlock.conditions
                    ):
                        logger.warning(
                            f"Interlock '{interlock.name}' has only DAQ-only conditions "
                            f"-- skipping push to CFP node (DAQ will evaluate it)")
                        continue
                    node_interlocks.append(interlock.to_dict())

        # Build safe state config
        safe_state_data = None
        if self.safety_manager:
            safe_state_data = self.safety_manager.safe_state_config.to_dict()

        # Generate config version hash
        import hashlib
        config_for_hash = {
            'channels': cfp_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz
        }
        config_str = json.dumps(config_for_hash, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

        # Build and publish config
        mqtt_base = self.config.system.mqtt_base_topic
        config_data = {
            'channels': cfp_channels,
            'safety_actions': safety_actions_data,
            'interlocks': node_interlocks,
            'scan_rate_hz': self.config.system.scan_rate_hz,
            'publish_rate_hz': self.config.system.publish_rate_hz,
            'timestamp': datetime.now().isoformat(),
            'config_version': config_hash
        }
        if safe_state_data:
            config_data['safe_state_config'] = safe_state_data

        # Store expected version for sync tracking
        self._cfp_config_versions[node_id] = config_hash

        topic = f"{mqtt_base}/nodes/{node_id}/config/full"
        self.mqtt_client.publish(topic, json.dumps(config_data), qos=1)
        logger.info(f"Pushed {len(cfp_channels)} channels + {len(safety_actions_data)} safety actions + {len(node_interlocks)} interlocks to CFP {node_id} (version: {config_hash})")

        self._cleanup_stale_channel_values()

    def _push_crio_channel_config_and_wait(self, node_id: str, timeout: float = 5.0) -> bool:
        """
        Push config to cRIO and WAIT for ACK response.

        This is used by START command to ensure cRIO has the config BEFORE
        acquisition begins. Without this, cRIO might start acquiring without
        knowing TAG names, causing values to not appear in dashboard.

        Args:
            node_id: cRIO node ID to push to
            timeout: Max seconds to wait for ACK (default 5.0)

        Returns:
            True if config was ACKed within timeout, False otherwise
        """
        # Create event for this node
        ack_event = threading.Event()
        self._crio_config_ack_events[node_id] = ack_event

        try:
            # Push config (this is non-blocking, just publishes MQTT)
            logger.info(f"[CONFIG_SYNC] Pushing config to cRIO {node_id} and waiting for ACK...")
            self._push_crio_channel_config(node_id)

            # Wait for ACK (set by _handle_crio_config_response)
            acked = ack_event.wait(timeout=timeout)

            if acked:
                logger.info(f"[CONFIG_SYNC] Config ACK received from {node_id}")
            else:
                logger.warning(f"[CONFIG_SYNC] Config ACK TIMEOUT from {node_id} after {timeout}s")

            return acked
        finally:
            # Clean up event
            self._crio_config_ack_events.pop(node_id, None)

    def _push_config_to_all_crios(self):
        """Push channel config to all online cRIO nodes.

        DEPRECATED: Use _push_config_to_all_crio_nodes() instead.
        This is a simple wrapper for backward compatibility.
        """
        self._push_config_to_all_crio_nodes()

    def _schedule_crio_config_push(self):
        """
        Schedule a debounced config push to all cRIO nodes.

        Use this for channel create/update/delete operations where multiple
        rapid calls should be coalesced into a single push. This prevents
        the race condition where rapid bulk creates each trigger a separate
        push, overwriting tracking state.

        NOTE: For START command, use _push_crio_channel_config_and_wait()
        instead - that's synchronous and waits for ACK.
        """
        with self._crio_push_lock:
            # Invalidate confirmed config versions - channels have changed
            # This ensures START will push fresh config after channel modifications
            self._crio_config_versions.clear()
            self._opto22_config_versions.clear()
            self._cfp_config_versions.clear()
            logger.debug("[DEBOUNCE] Cleared confirmed config versions (channels modified)")

            # Cancel existing timer if pending
            if self._crio_push_debounce_timer:
                self._crio_push_debounce_timer.cancel()

            # Schedule new push after debounce delay
            self._crio_push_debounce_timer = threading.Timer(
                self._crio_push_debounce_delay,
                self._push_config_to_all_crio_nodes
            )
            self._crio_push_debounce_timer.daemon = True  # Don't block shutdown
            self._crio_push_debounce_timer.start()
            logger.debug(f"[DEBOUNCE] Scheduled config push in {self._crio_push_debounce_delay}s")

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

    def _handle_test_session_start(self, payload: Dict[str, Any], request_id: Optional[str] = None):
        """Start a test session with safety interlock validation"""
        logger.info("[SESSION] Received test session START request")
        started_by = payload.get('started_by', 'user') if isinstance(payload, dict) else 'user'

        # In CRIO mode, forward to cRIO - it's the source of truth for session state
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info("[SESSION] CRIO mode - forwarding session start to cRIO")
            mqtt_base = self.config.system.mqtt_base_topic

            # Try to get cRIO nodes, with retry if not found
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []

            if not crio_nodes:
                # Attempt discovery ping and wait briefly
                logger.info("[SESSION] No cRIO nodes found, sending discovery ping...")
                self._send_crio_discovery_ping()

                # Wait up to 3 seconds for cRIO to respond
                for attempt in range(6):
                    time.sleep(0.5)
                    crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
                    if crio_nodes:
                        logger.info(f"[SESSION] cRIO discovered after {(attempt+1)*0.5}s")
                        break

            if not crio_nodes:
                logger.warning("[SESSION] No cRIO nodes discovered after retry! Cannot forward session start.")
                # Publish failure response to dashboard
                base = self.get_topic_base()
                self.mqtt_client.publish(
                    f"{base}/test-session/status",
                    json.dumps({
                        'active': False,
                        'error': 'No cRIO nodes discovered - check cRIO connection and try again',
                        'timestamp': datetime.now().isoformat()
                    })
                )
                self._publish_command_ack("test-session/start", request_id, False, "No cRIO nodes discovered")
                return
            else:
                logger.info(f"[SESSION] Found {len(crio_nodes)} cRIO node(s): {[n.node_id for n in crio_nodes]}")
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/session/start"
                crio_payload = {
                    'name': payload.get('name', ''),
                    'operator': started_by,
                    'locked_outputs': payload.get('locked_outputs', []),
                    'timeout_minutes': payload.get('timeout_minutes', 0),
                    'test_id': payload.get('test_id', ''),
                    'description': payload.get('description', ''),
                    'operator_notes': payload.get('operator_notes', ''),
                }
                # Brief delay to allow cRIO to finish transitioning to ACQUIRING state
                # after the acquire/start command was sent (avoids race condition where
                # session/start arrives before cRIO finishes its START transition)
                if self.acquiring:
                    time.sleep(0.2)
                self.mqtt_client.publish(crio_topic, json.dumps(crio_payload), qos=1)
                logger.info(f"[SESSION] Forwarded start to cRIO {node.node_id}")

            # ACK that we forwarded successfully (cRIO will publish session/status separately)
            self._publish_command_ack("test-session/start", request_id, True)

            # Audit trail: Log session start (PC audit for cRIO mode)
            if self.audit_trail and crio_nodes:
                self.audit_trail.log_event(
                    event_type=AuditEventType.TEST_SESSION_STARTED,
                    user=started_by,
                    description="Test session started (forwarded to cRIO)",
                    details={
                        'mode': 'crio',
                        'target_nodes': [n.node_id for n in crio_nodes],
                        'timeout_minutes': payload.get('timeout_minutes', 0),
                        'test_id': payload.get('test_id', ''),
                    }
                )

            # cRIO will publish session/status which triggers _handle_crio_session_status
            return

        # CDAQ mode - handle locally (PC is PLC)
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
            require_no_active=require_no_active,
            test_id=payload.get('test_id') if isinstance(payload, dict) else None,
            description=payload.get('description') if isinstance(payload, dict) else None,
            operator_notes=payload.get('operator_notes') if isinstance(payload, dict) else None,
        )

        if result.get('success'):
            self._publish_command_ack("test-session/start", request_id, True)
            self._publish_test_session_status()
            self._publish_user_variables_values()

            # Audit trail: Log session start
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.TEST_SESSION_STARTED,
                    user=started_by,
                    description="Test session started",
                    details={
                        'mode': 'cdaq',
                        'require_no_latched': require_no_latched,
                        'require_no_active': require_no_active,
                        'test_id': payload.get('test_id', '') if isinstance(payload, dict) else '',
                    }
                )
        else:
            self._publish_command_ack("test-session/start", request_id, False, result.get('error', 'Failed to start session'))

    def _handle_test_session_stop(self, request_id: Optional[str] = None):
        """Stop the test session"""
        logger.info("[SESSION] Received test session STOP request")

        # In CRIO mode, forward to cRIO - it's the source of truth for session state
        if self.config.system.project_mode == ProjectMode.CRIO:
            logger.info("[SESSION] CRIO mode - forwarding session stop to cRIO")
            mqtt_base = self.config.system.mqtt_base_topic
            # Forward to all discovered cRIO nodes (typically just one)
            crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
            if not crio_nodes:
                logger.warning("[SESSION] No cRIO nodes discovered! Cannot forward session stop.")
                self._publish_command_ack("test-session/stop", request_id, False, "No cRIO nodes discovered")
                return
            for node in crio_nodes:
                crio_topic = f"{mqtt_base}/nodes/{node.node_id}/session/stop"
                crio_payload = {'reason': 'user_command'}
                self.mqtt_client.publish(crio_topic, json.dumps(crio_payload), qos=1)
                logger.info(f"[SESSION] Forwarded stop to cRIO {node.node_id}")

            # ACK that we forwarded successfully
            self._publish_command_ack("test-session/stop", request_id, True)

            # Audit trail: Log session stop (PC audit for cRIO mode)
            if self.audit_trail and crio_nodes:
                self.audit_trail.log_event(
                    event_type=AuditEventType.TEST_SESSION_STOPPED,
                    user=self.auth_username or "user",
                    description="Test session stopped (forwarded to cRIO)",
                    details={
                        'mode': 'crio',
                        'target_nodes': [n.node_id for n in crio_nodes],
                        'reason': 'user_command'
                    }
                )

            # cRIO will publish session/status which triggers _handle_crio_session_status
            return

        # CDAQ mode - handle locally (PC is PLC)
        result = self.user_variables.stop_session()

        if result.get('success'):
            self._publish_command_ack("test-session/stop", request_id, True)
            self._publish_test_session_status()
            self._publish_user_variables_values()

            # Audit trail: Log session stop
            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type=AuditEventType.TEST_SESSION_STOPPED,
                    user=self.auth_username or "user",
                    description="Test session stopped",
                    details={
                        'mode': 'cdaq',
                        'stopped_at': result.get('stopped_at'),
                        'session_started_at': result.get('session_started_at')
                    }
                )
        else:
            self._publish_command_ack("test-session/stop", request_id, False, result.get('error', 'Failed to stop session'))

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

        # Include list of outputs controlled by session scripts (locked for manual control)
        if self.script_manager:
            status['controlled_outputs'] = list(self.script_manager.get_controlled_outputs())
        else:
            status['controlled_outputs'] = []

        self.mqtt_client.publish(
            f"{base}/test-session/status",
            json.dumps(status),
            retain=True
        )

    def _check_session_timeout(self):
        """
        Check if CDAQ mode session has timed out.

        This provides autonomous operation protection - if the session runs
        longer than the configured timeout, it automatically stops.
        This matches the behavior of cRIO/Opto22 edge nodes.
        """
        if not self.user_variables:
            return

        result = self.user_variables.check_session_timeout()
        if result and result.get('success'):
            # Session was stopped due to timeout
            logger.warning(f"[SESSION] Auto-stopped due to timeout after {result.get('timeout_minutes', 0)} minutes")

            # Publish status update
            self._publish_test_session_status()
            self._publish_user_variables_values()

            # Publish timeout event for frontend notification
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/test-session/timeout",
                json.dumps({
                    'reason': 'timeout',
                    'timeout_minutes': result.get('timeout_minutes', 0),
                    'stopped_at': result.get('stopped_at'),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
            )

            # Audit log the timeout
            if self.audit_trail:
                self.audit_trail.log(
                    AuditEventType.USER_SESSION_TIMEOUT,
                    user="system",
                    details={
                        'timeout_minutes': result.get('timeout_minutes', 0),
                        'session_started_at': result.get('session_started_at')
                    }
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

        # PERMISSION CHECK
        if not self._has_permission(Permission.MODIFY_CHANNELS):
            logger.warning("[SECURITY] Channel update denied - insufficient permissions")
            self._publish_config_response(False, "Permission denied")
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
        # Accept both 'unit' (singular, used by frontend) and 'units' (plural, legacy)
        if 'units' in config_data:
            channel.units = config_data['units']
        elif 'unit' in config_data:
            channel.units = config_data['unit']
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

        # Auto-enable map scaling when user sets any of the four scaling fields
        # but scale_type wasn't explicitly included in this update.
        # This makes inline table edits "just work" without a separate dropdown.
        _MAP_FIELDS = {'pre_scaled_min', 'pre_scaled_max', 'scaled_min', 'scaled_max'}
        if (_MAP_FIELDS & set(config_data.keys())
                and 'scale_type' not in config_data
                and (channel.scale_type or 'none') == 'none'):
            channel.scale_type = 'map'
            logger.info(f"Auto-enabled map scaling for {channel_name} (scaling fields set via inline edit)")

        # Map scaling parameters
        if 'pre_scaled_min' in config_data:
            channel.pre_scaled_min = float(config_data['pre_scaled_min']) if config_data['pre_scaled_min'] is not None else None
        if 'pre_scaled_max' in config_data:
            channel.pre_scaled_max = float(config_data['pre_scaled_max']) if config_data['pre_scaled_max'] is not None else None
        if 'scaled_min' in config_data:
            channel.scaled_min = float(config_data['scaled_min']) if config_data['scaled_min'] is not None else None
        if 'scaled_max' in config_data:
            channel.scaled_max = float(config_data['scaled_max']) if config_data['scaled_max'] is not None else None

        # Thermocouple-specific parameters — accept both 'tc_type' and
        # 'thermocouple_type' (frontend sends thermocouple_type)
        tc_field_value = config_data.get('thermocouple_type') or config_data.get('tc_type')
        if tc_field_value is not None and ('tc_type' in config_data or 'thermocouple_type' in config_data):
            from config_parser import ThermocoupleType
            try:
                channel.thermocouple_type = ThermocoupleType(tc_field_value)
            except ValueError:
                logger.warning(f"Invalid thermocouple type: {tc_field_value}")
        if 'cjc_source' in config_data:
            import cjc_source as _cjc
            requested = config_data['cjc_source']
            coerced = _cjc.coerce(channel.channel_type, requested)
            channel.cjc_source = coerced
            if requested and _cjc.normalize(requested) != coerced:
                logger.warning(
                    f"Channel {channel_name}: cjc_source '{requested}' is "
                    f"invalid for {channel.channel_type.value} — coerced to '{coerced}'"
                )
        if 'cjc_value' in config_data:
            channel.cjc_value = float(config_data['cjc_value'])

        # RTD parameters
        if 'rtd_type' in config_data:
            channel.rtd_type = config_data['rtd_type']
        if 'rtd_wiring' in config_data:
            channel.rtd_wiring = config_data['rtd_wiring']
        if 'rtd_current' in config_data:
            channel.rtd_current = float(config_data['rtd_current'])

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
        # Coerce to a valid value for the channel type AND module — current/TC/RTD/strain
        # and DIFF-only modules (NI-9215 etc) are forced to 'differential' since
        # other configs cause wrong readings.
        if 'terminal_config' in config_data:
            import terminal_config as _tc
            requested = config_data['terminal_config']
            mod = self.config.modules.get(channel.module) if channel.module else None
            mod_type = getattr(mod, 'module_type', None) if mod else None
            coerced = _tc.coerce(channel.channel_type, requested, mod_type)
            channel.terminal_config = coerced
            if _tc.normalize(requested) != coerced:
                logger.warning(
                    f"Channel {channel_name}: terminal_config '{requested}' is "
                    f"invalid for {channel.channel_type.value} (module {mod_type or 'unknown'}) "
                    f"— coerced to '{coerced}'"
                )

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

        # Modbus-specific parameters
        if 'modbus_register_type' in config_data:
            channel.modbus_register_type = config_data['modbus_register_type']
        if 'modbus_address' in config_data:
            channel.modbus_address = int(config_data['modbus_address'])
        if 'modbus_data_type' in config_data:
            channel.modbus_data_type = config_data['modbus_data_type']
        if 'modbus_byte_order' in config_data:
            channel.modbus_byte_order = config_data['modbus_byte_order']
        if 'modbus_word_order' in config_data:
            channel.modbus_word_order = config_data['modbus_word_order']
        if 'modbus_scale' in config_data:
            channel.modbus_scale = float(config_data['modbus_scale'])
        if 'modbus_offset' in config_data:
            channel.modbus_offset = float(config_data['modbus_offset'])
        if 'modbus_slave_id' in config_data:
            channel.modbus_slave_id = int(config_data['modbus_slave_id']) if config_data['modbus_slave_id'] is not None else None
        if 'modbus_register_count' in config_data:
            channel.modbus_register_count = int(config_data['modbus_register_count']) if config_data['modbus_register_count'] is not None else None
        if 'modbus_register_index' in config_data:
            channel.modbus_register_index = int(config_data['modbus_register_index'])

        # ISA-18.2 Alarm Configuration
        alarm_config_changed = False
        if 'alarm_enabled' in config_data:
            old_val = getattr(channel, 'alarm_enabled', False)
            channel.alarm_enabled = bool(config_data['alarm_enabled'])
            if old_val != channel.alarm_enabled:
                alarm_config_changed = True
        if 'hi_limit' in config_data:
            channel.hi_limit = float(config_data['hi_limit']) if config_data['hi_limit'] is not None else None
            alarm_config_changed = True
        if 'lo_limit' in config_data:
            channel.lo_limit = float(config_data['lo_limit']) if config_data['lo_limit'] is not None else None
            alarm_config_changed = True
        if 'hihi_limit' in config_data:
            channel.hihi_limit = float(config_data['hihi_limit']) if config_data['hihi_limit'] is not None else None
            alarm_config_changed = True
        if 'lolo_limit' in config_data:
            channel.lolo_limit = float(config_data['lolo_limit']) if config_data['lolo_limit'] is not None else None
            alarm_config_changed = True
        if 'alarm_priority' in config_data:
            channel.alarm_priority = config_data['alarm_priority']
            alarm_config_changed = True
        if 'alarm_deadband' in config_data:
            channel.alarm_deadband = float(config_data['alarm_deadband']) if config_data['alarm_deadband'] is not None else 1.0
            alarm_config_changed = True
        if 'alarm_delay_sec' in config_data:
            channel.alarm_delay_sec = float(config_data['alarm_delay_sec']) if config_data['alarm_delay_sec'] is not None else 0
            alarm_config_changed = True

        # Digital input alarm settings
        if 'digital_alarm_enabled' in config_data:
            channel.digital_alarm_enabled = bool(config_data['digital_alarm_enabled'])
            alarm_config_changed = True
        if 'digital_expected_state' in config_data:
            channel.digital_expected_state = config_data['digital_expected_state']
            alarm_config_changed = True
        if 'digital_debounce_ms' in config_data:
            channel.digital_debounce_ms = int(config_data['digital_debounce_ms'])
            alarm_config_changed = True
        if 'digital_invert' in config_data:
            channel.digital_invert = bool(config_data['digital_invert'])
            alarm_config_changed = True

        # Update AlarmManager if alarm config changed
        if alarm_config_changed and self.alarm_manager:
            self._update_channel_alarm_config(channel_name, channel)

        # Push to cRIO if this is a cRIO channel (debounced)
        physical_ch = getattr(channel, 'physical_channel', '')
        if physical_ch.startswith('Mod') and self.config.system.project_mode == ProjectMode.CRIO:
            self._schedule_crio_config_push()

        # Validate scaling config
        is_valid, error_msg = validate_scaling_config(channel)
        if not is_valid:
            logger.warning(f"Scaling validation warning for {channel_name}: {error_msg}")

        logger.info(f"Updated channel {channel_name} (type: {channel.channel_type.value})")

        # Audit trail: Log channel configuration change
        if self.audit_trail:
            self.audit_trail.log_config_change(
                config_type="channel",
                item_id=channel_name,
                user=self.auth_username or "system",
                previous_value=None,  # Could capture old values if needed
                new_value=config_data,
                reason=config_data.get('reason', '')
            )

        self._publish_channel_config()
        self._publish_config_response(True, f"Updated {channel_name}")

    def _check_physical_channel_collision(
        self,
        physical_channel: str,
        source_node_id: str = '',
        exclude_channel: Optional[str] = None
    ) -> Optional[str]:
        """
        Check if a physical channel is already in use by another tag.

        Args:
            physical_channel: The physical channel path (e.g., "Mod1/ai0")
            source_node_id: The source node ID for remote channels (e.g., "crio-001")
            exclude_channel: Channel name to exclude from check (for updates)

        Returns:
            Name of the conflicting channel, or None if no collision
        """
        if not physical_channel:
            return None

        for name, ch in self.config.channels.items():
            # Skip the channel being updated
            if exclude_channel and name == exclude_channel:
                continue

            # Check if same physical channel on same source node
            ch_source_node = getattr(ch, 'source_node_id', '') or ''
            ch_physical = ch.physical_channel or ''

            # Compare: same physical channel AND same source node
            if ch_physical == physical_channel and ch_source_node == source_node_id:
                return name

        return None

    def _handle_channel_create(self, payload: Any):
        """Create a new channel at runtime"""
        if not self.authenticated:
            logger.warning("Channel create rejected - not authenticated")
            self._publish_config_response(False, "Not authenticated")
            return

        # PERMISSION CHECK
        if not self._has_permission(Permission.MODIFY_CHANNELS):
            logger.warning("[SECURITY] Channel create denied - insufficient permissions")
            self._publish_config_response(False, "Permission denied")
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

        # Validate physical channel is not already in use
        physical_channel = config_data.get('physical_channel', '')
        source_node_id = config_data.get('source_node_id', '')
        if physical_channel:
            collision = self._check_physical_channel_collision(
                physical_channel, source_node_id, exclude_channel=None
            )
            if collision:
                self._publish_config_response(
                    False,
                    f"Physical channel '{physical_channel}' is already used by tag '{collision}'"
                )
                return

        try:
            # Parse channel type
            channel_type_str = config_data.get('channel_type', 'voltage')
            channel_type = ChannelType(channel_type_str)

            # Parse thermocouple type if applicable (only if value is not None)
            tc_type = None
            if config_data.get('thermocouple_type'):
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
                cjc_value=float(config_data.get('cjc_value', 25.0)),
                rtd_type=config_data.get('rtd_type', 'Pt100'),
                rtd_wiring=config_data.get('rtd_wiring', config_data.get('resistance_config', '4-wire')),
                rtd_current=float(config_data.get('rtd_current', 0.001)),
                counter_mode=config_data.get('counter_mode', 'frequency'),
                pulses_per_unit=float(config_data.get('pulses_per_unit', 1.0)),
                counter_edge=config_data.get('counter_edge', 'rising'),
                counter_reset_on_read=bool(config_data.get('counter_reset_on_read', False)),
                # Modbus-specific parameters
                modbus_register_type=config_data.get('modbus_register_type', 'holding'),
                modbus_address=int(config_data.get('modbus_address', 0)),
                modbus_data_type=config_data.get('modbus_data_type', 'float32'),
                modbus_byte_order=config_data.get('modbus_byte_order', 'big'),
                modbus_word_order=config_data.get('modbus_word_order', 'big'),
                modbus_scale=float(config_data.get('modbus_scale', 1.0)),
                modbus_offset=float(config_data.get('modbus_offset', 0.0)),
                modbus_slave_id=int(config_data['modbus_slave_id']) if config_data.get('modbus_slave_id') is not None else None,
                modbus_register_count=int(config_data['modbus_register_count']) if config_data.get('modbus_register_count') is not None else None,
                modbus_register_index=int(config_data.get('modbus_register_index', 0)),
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
            elif channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT):
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

            # Push to cRIO if this is a cRIO channel (debounced to coalesce rapid creates)
            physical_ch = config_data.get('physical_channel', '')
            if physical_ch.startswith('Mod') and self.config.system.project_mode == ProjectMode.CRIO:
                self._schedule_crio_config_push()

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

        # PERMISSION CHECK
        if not self._has_permission(Permission.MODIFY_CHANNELS):
            logger.warning("[SECURITY] Channel delete denied - insufficient permissions")
            self._publish_config_response(False, "Permission denied")
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

        # Push updated config to cRIO (so it removes the deleted channel) - debounced
        if self.config.system.project_mode == ProjectMode.CRIO:
            self._schedule_crio_config_push()

        self._publish_config_response(True, f"Deleted channel {channel_name}")

    def _cleanup_stale_channel_values(self):
        """Remove channel_values entries for channels no longer in config.

        This prevents stale values from being published after channels are
        deleted or config is changed.
        """
        stale_keys = [name for name in self.channel_values if name not in self.config.channels]
        if stale_keys:
            for key in stale_keys:
                del self.channel_values[key]
                if key in self.channel_raw_values:
                    del self.channel_raw_values[key]
                if key in self.channel_timestamps:
                    del self.channel_timestamps[key]
                self._logged_open_tc.discard(key)
                self._stale_warn_times.pop(key, None)
            logger.info(f"Cleaned up {len(stale_keys)} stale channel values")

    def _handle_channel_bulk_create(self, payload: Any):
        """Create multiple channels at once (from discovery)"""
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
                # Frontend sends both channel_type (hardware direction) and category (measurement type)
                # hw_type is the hardware direction (digital_input, analog_input, voltage_output, etc.)
                # category is the measurement type (digital, voltage, thermocouple, etc.)
                hw_type = ch_config.get('channel_type', '')
                category = ch_config.get('category', '')
                logger.info(f"Bulk create {channel_name}: hw_type={hw_type}, category={category}")

                # Check hw_type FIRST - it's the definitive hardware direction
                # OUTPUT types
                if hw_type in ('voltage_output', 'analog_output'):
                    channel_type_str = 'voltage_output'
                elif hw_type == 'current_output':
                    channel_type_str = 'current_output'
                elif hw_type == 'digital_output':
                    channel_type_str = 'digital_output'
                # INPUT types by hw_type (takes precedence over category)
                elif hw_type == 'digital_input':
                    channel_type_str = 'digital_input'
                elif hw_type == 'thermocouple':
                    channel_type_str = 'thermocouple'
                elif hw_type == 'current_input':
                    channel_type_str = 'current_input'
                elif hw_type == 'rtd':
                    channel_type_str = 'rtd'
                elif hw_type in ('voltage_input', 'analog_input'):
                    channel_type_str = 'voltage_input'
                elif hw_type in ('counter_input', 'ci'):
                    channel_type_str = 'counter'
                # Fallback to category for specialized types
                elif category == 'thermocouple':
                    channel_type_str = 'thermocouple'
                elif category == 'current_input':
                    channel_type_str = 'current_input'
                elif category == 'rtd':
                    channel_type_str = 'rtd'
                elif category == 'strain_input':
                    channel_type_str = 'strain'
                elif category in ('counter', 'counter_input'):
                    channel_type_str = 'counter'
                elif category == 'voltage_input':
                    channel_type_str = 'voltage_input'
                elif category == 'digital_input':
                    channel_type_str = 'digital_input'
                elif category == 'bridge_input':
                    channel_type_str = 'voltage_input'  # Bridge modules read as voltage
                elif category == 'iepe_input':
                    channel_type_str = 'voltage_input'  # IEPE modules read as voltage
                elif category == 'resistance_input':
                    channel_type_str = 'voltage_input'  # Resistance modules read as voltage
                else:
                    # Unknown hw_type and category - log warning and default to voltage_input
                    logger.warning(f"Unknown hw_type='{hw_type}' category='{category}' for channel {channel_name}, defaulting to voltage_input")
                    channel_type_str = 'voltage_input'

                channel_type = ChannelType(channel_type_str)

                tc_type = None
                if ch_config.get('thermocouple_type'):
                    from config_parser import ThermocoupleType
                    tc_type = ThermocoupleType(ch_config['thermocouple_type'])

                # Determine source type - cRIO/Opto22/cDAQ channels have different metadata
                # Frontend sends: 'crio', 'opto22', 'cdaq', 'local'
                # Remote nodes (crio, opto22) have source_node_id for matching values
                source_type = ch_config.get('source_type', 'local')
                if source_type in ('crio', 'opto22'):
                    # Remote node - preserve type and get node ID
                    source_node_id = ch_config.get('node_id') or ch_config.get('source_node_id', '')
                else:
                    source_type = 'local'  # Local DAQ (cDAQ/PXI/USB)
                    source_node_id = ''

                channel = ChannelConfig(
                    name=channel_name,
                    module=ch_config.get('module', ''),
                    physical_channel=ch_config.get('physical_channel', ''),
                    channel_type=channel_type,
                    description=ch_config.get('description', ''),
                    units=ch_config.get('units', ch_config.get('unit', '')),  # Support both
                    visible=ch_config.get('visible', True),
                    group=ch_config.get('group', ''),
                    thermocouple_type=tc_type,
                    cjc_source=ch_config.get('cjc_source', 'internal'),
                    cjc_value=float(ch_config.get('cjc_value', 25.0)),
                    voltage_range=float(ch_config.get('voltage_range', 10.0)),
                    current_range_ma=float(ch_config.get('current_range_ma', 20.0)),
                    terminal_config=ch_config.get('terminal_config', 'differential'),
                    # RTD
                    rtd_type=ch_config.get('rtd_type', 'Pt100'),
                    rtd_wiring=ch_config.get('rtd_wiring', ch_config.get('resistance_config', '4-wire')),
                    rtd_current=float(ch_config.get('rtd_current', 0.001)),
                    # Scaling
                    scale_slope=float(ch_config.get('scale_slope', 1.0)),
                    scale_offset=float(ch_config.get('scale_offset', 0.0)),
                    scale_type=ch_config.get('scale_type', 'none'),
                    four_twenty_scaling=ch_config.get('four_twenty_scaling', False),
                    eng_units_min=float(ch_config['eng_units_min']) if ch_config.get('eng_units_min') is not None else None,
                    eng_units_max=float(ch_config['eng_units_max']) if ch_config.get('eng_units_max') is not None else None,
                    # Limits
                    low_limit=float(ch_config['low_limit']) if ch_config.get('low_limit') is not None else None,
                    high_limit=float(ch_config['high_limit']) if ch_config.get('high_limit') is not None else None,
                    low_warning=float(ch_config['low_warning']) if ch_config.get('low_warning') is not None else None,
                    high_warning=float(ch_config['high_warning']) if ch_config.get('high_warning') is not None else None,
                    # Digital
                    invert=ch_config.get('invert', False),
                    default_state=ch_config.get('default_state', False),
                    default_value=float(ch_config.get('default_value', 0.0)),
                    # Logging
                    log=ch_config.get('log', True),
                    log_interval_ms=int(ch_config.get('log_interval_ms', 1000)),
                    # Multi-node support
                    source_type=source_type,
                    source_node_id=source_node_id
                )

                self.config.channels[channel_name] = channel

                # Initialize value
                if channel_type == ChannelType.DIGITAL_OUTPUT:
                    self.channel_values[channel_name] = channel.default_state
                elif channel_type in (ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT):
                    self.channel_values[channel_name] = channel.default_value
                else:
                    self.channel_values[channel_name] = 0.0

                if self.simulator:
                    self.simulator.add_channel(channel)

                created.append(channel_name)

            except Exception as e:
                logger.error(f"Bulk create failed for {channel_name}: {e}")
                failed.append({"name": channel_name, "error": str(e)})

        # Update dependency tracker once at the end
        if self.dependency_tracker and created:
            self.dependency_tracker.refresh(self.config)

        # Reinitialize hardware reader with new channels
        if created:
            self._reinit_hardware_reader()

        # Clean up any stale channel values
        self._cleanup_stale_channel_values()

        logger.info(f"Bulk create: {len(created)} created, {len(failed)} failed")
        self._publish_channel_config()

        # Push config to all cRIO nodes after bulk create (debounced)
        # This ensures cRIO has the TAG name -> physical channel mappings
        if created and self.config.system.project_mode == ProjectMode.CRIO:
            self._schedule_crio_config_push()

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

    def _send_crio_discovery_ping(self):
        """Send a discovery ping to all cRIO nodes.

        Called periodically from heartbeat loop and during discovery scan.
        cRIO nodes respond by publishing their status, which registers them.
        """
        if not self.mqtt_client:
            return

        mqtt_base = self.config.system.mqtt_base_topic
        self.mqtt_client.publish(
            f"{mqtt_base}/discovery/ping",
            json.dumps({"request": "status", "timestamp": datetime.now().isoformat()}),
            qos=1
        )
        logger.debug("Sent cRIO discovery ping")

    def _handle_discovery_scan(self, payload: Any = None):
        """Handle device discovery scan request.

        Args:
            payload: Optional dict with 'mode' key:
                - 'cdaq': Only scan local NI cDAQ hardware
                - 'crio': Only ping cRIO nodes
                - 'opto22': Only scan Opto22 nodes
                - 'all' or None: Scan everything (default)

        Pings remote cRIO nodes and waits for responses before returning results.
        Scans local hardware first, then waits for cRIO responses.
        """
        # PERMISSION CHECK
        if not self._has_permission(Permission.MODIFY_CHANNELS):
            logger.warning("[SECURITY] Discovery scan denied - insufficient permissions")
            base = self.get_topic_base()
            self.mqtt_client.publish(f"{base}/discovery/result", json.dumps({
                "success": False, "error": "Permission denied", "total_channels": 0
            }))
            return

        # Get mode from payload
        mode = 'all'
        if isinstance(payload, dict):
            mode = payload.get('mode', 'all') or 'all'

        logger.info(f"Starting device discovery scan (mode: {mode})...")
        base = self.get_topic_base()

        # CFP mode: targeted Modbus slot probe (separate from system-wide discovery)
        if mode == 'cfp' and isinstance(payload, dict):
            ip_address = payload.get('ip_address', '')
            port = int(payload.get('port', 502))
            slave_id = int(payload.get('slave_id', 1))
            backplane_model = payload.get('backplane_model', 'cFP-1808')
            device_name = payload.get('device_name', '')

            if not ip_address:
                cfp_result = {'success': False, 'message': 'CFP scan requires ip_address', 'slots': []}
            else:
                logger.info(f"Probing CFP backplane at {ip_address}:{port} ({backplane_model})...")
                cfp_result = self.device_discovery.scan_cfp(
                    ip_address=ip_address, port=port, slave_id=slave_id,
                    backplane_model=backplane_model, device_name=device_name
                )
                logger.info(f"CFP probe complete: {cfp_result.get('message', '')}")

            self.mqtt_client.publish(
                f"{base}/discovery/cfp/result",
                json.dumps(cfp_result), qos=1
            )
            return

        try:
            import time

            crio_count_before = 0
            crio_found = False

            # Step 1: Ping cRIO nodes if mode allows (crio or all)
            if mode in ('crio', 'all'):
                crio_count_before = len(self.device_discovery.get_crio_nodes())
                self._send_crio_discovery_ping()
                logger.info(f"Sent discovery ping (known cRIOs before: {crio_count_before})")

            # Step 2: Scan local hardware if mode allows (cdaq, opto22, or all)
            # Note: opto22 nodes are included in device_discovery.scan() results
            if mode in ('cdaq', 'opto22', 'all'):
                result = self.device_discovery.scan()
                if not result.success:
                    logger.warning(f"Hardware discovery failed: {result.message}")
                logger.info(f"Local hardware scan complete: {result.message}")
            elif mode == 'crio':
                # For crio-only mode, create empty result (will be populated after cRIO ping)
                from device_discovery import DiscoveryResult
                result = DiscoveryResult(
                    success=True,
                    message="Waiting for cRIO responses...",
                    timestamp=datetime.now().isoformat()
                )

            # Step 3: Wait for cRIO responses if we sent pings
            if mode in ('crio', 'all'):
                max_wait = 6.0
                wait_interval = 0.5
                waited = 0.0

                while waited < max_wait:
                    time.sleep(wait_interval)
                    waited += wait_interval

                    crio_count_now = len(self.device_discovery.get_crio_nodes())
                    if crio_count_now > crio_count_before:
                        logger.info(f"cRIO detected during wait ({crio_count_before} -> {crio_count_now}) after {waited:.1f}s")
                        crio_found = True
                        time.sleep(0.5)
                        break

                if not crio_found and crio_count_before == 0:
                    logger.info(f"No cRIO responses after {waited:.1f}s wait")

            # Step 4: Build final result based on mode
            if mode == 'crio':
                # cRIO-only mode: build result directly from registered nodes
                # Do NOT call device_discovery.scan() — it enumerates local cDAQ hardware
                from device_discovery import DiscoveryResult
                crio_nodes = self.device_discovery.get_crio_nodes()
                crio_channels = sum(n.channels for n in crio_nodes)
                crio_msg = f"Found {len(crio_nodes)} cRIO node(s), {crio_channels} channels"
                result = DiscoveryResult(
                    success=True,
                    message=crio_msg,
                    timestamp=datetime.now().isoformat(),
                    crio_nodes=crio_nodes,
                    total_channels=crio_channels
                )
                logger.info(f"cRIO discovery: {crio_msg}")
            else:
                # For 'all' or 'cdaq' modes, re-scan to include any newly found cRIOs
                crio_count_now = len(self.device_discovery.get_crio_nodes())
                should_rescan = crio_found or crio_count_now > crio_count_before
                if mode == 'all' and should_rescan:
                    result = self.device_discovery.scan()
                    if not result.success:
                        logger.warning(f"Re-scan hardware discovery failed: {result.message}")
                    logger.info(f"Re-scanned with cRIO nodes: {result.message}")

            # Filter result based on mode
            result_dict = result.to_dict()
            if mode == 'cdaq':
                # Only include local cDAQ chassis, remove remote nodes
                result_dict['crio_nodes'] = []
                result_dict['opto22_nodes'] = []
            elif mode == 'opto22':
                # Only include Opto22 nodes
                result_dict['chassis'] = []
                result_dict['standalone_devices'] = []
                result_dict['crio_nodes'] = []

            # Recalculate total channels based on filtered results
            total_channels = 0
            for chassis in result_dict.get('chassis', []):
                for module in chassis.get('modules', []):
                    total_channels += len(module.get('channels', []))
            for device in result_dict.get('standalone_devices', []):
                total_channels += len(device.get('channels', []))
            for node in result_dict.get('crio_nodes', []):
                for module in node.get('modules', []):
                    total_channels += len(module.get('channels', []))
            for node in result_dict.get('opto22_nodes', []):
                for module in node.get('modules', []):
                    total_channels += len(module.get('channels', []))
            result_dict['total_channels'] = total_channels

            # Publish filtered discovery result
            self.mqtt_client.publish(
                f"{base}/discovery/result",
                json.dumps(result_dict),
                qos=1
            )

            logger.info(f"Discovery complete (mode: {mode}): {result_dict.get('message', 'OK')}")

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
        self._publish_system_status()  # Update system status with scheduler_enabled=true

    def _handle_schedule_disable(self):
        """Disable the schedule"""
        self.scheduler.disable()
        self._publish_schedule_response(True, "Schedule disabled")
        self._publish_schedule_status()
        self._publish_system_status()  # Update system status with scheduler_enabled=false

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
                "log_directory": self.config.system.log_directory,
                "project_mode": self.config.system.project_mode.value,
                "log_level": self.config.system.log_level,
                "log_max_file_size_mb": self.config.system.log_max_file_size_mb,
                "log_backup_count": self.config.system.log_backup_count,
                "service_heartbeat_interval_sec": self.config.system.service_heartbeat_interval_sec,
                "service_health_timeout_sec": self.config.system.service_health_timeout_sec,
                "service_shutdown_timeout_sec": self.config.system.service_shutdown_timeout_sec,
                "service_command_ack_timeout_sec": self.config.system.service_command_ack_timeout_sec,
                "dataviewer_retention_days": self.config.system.dataviewer_retention_days,
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
                    "cjc_value": getattr(ch, 'cjc_value', 25.0),
                    # RTD-specific
                    "rtd_type": getattr(ch, 'rtd_type', 'Pt100'),
                    "rtd_wiring": getattr(ch, 'rtd_wiring', '4-wire'),
                    "rtd_current": getattr(ch, 'rtd_current', 0.001),
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

            # Terminal configuration (always save — critical for correct hardware readings)
            if ch.terminal_config:
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
                "unit": channel.units,  # Frontend uses 'unit' (singular) — publish both
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
                "cjc_value": getattr(channel, 'cjc_value', 25.0),
                "rtd_type": getattr(channel, 'rtd_type', 'Pt100'),
                "rtd_wiring": getattr(channel, 'rtd_wiring', '4-wire'),
                "rtd_current": getattr(channel, 'rtd_current', 0.001),
                "voltage_range": channel.voltage_range,
                "current_range_ma": channel.current_range_ma,
                "log_interval_ms": channel.log_interval_ms,
                # Hardware source info for cRIO vs cDAQ distinction
                "hardware_source": channel.hardware_source.value,
                "hardware_source_display": channel.hardware_source_display,
                "is_crio": channel.is_crio,
                "is_local_daq": channel.is_local_daq,
                "is_modbus": channel.is_modbus,
                # Modbus-specific config (for dashboard channel editing)
                "modbus_register_type": channel.modbus_register_type,
                "modbus_address": channel.modbus_address,
                "modbus_data_type": channel.modbus_data_type,
                "modbus_byte_order": channel.modbus_byte_order,
                "modbus_word_order": channel.modbus_word_order,
                "modbus_scale": channel.modbus_scale,
                "modbus_offset": channel.modbus_offset,
                "modbus_slave_id": channel.modbus_slave_id,
                "modbus_register_count": channel.modbus_register_count,
                "modbus_register_index": channel.modbus_register_index,
                "source_node_id": channel.source_node_id,
                "safety_can_run_locally": channel.safety_can_run_locally
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

    def _publish_channel_claims(self):
        """Publish claimed physical channels for cross-instance conflict detection.

        Other DAQ instances and the station manager subscribe to these retained
        messages to prevent channel overlap in station mode.
        """
        if not self.mqtt_client or not self.config:
            return
        base = self.get_topic_base()
        channels = [
            ch.physical_channel for ch in self.config.channels.values()
            if ch.physical_channel
        ]
        project_name = ""
        if self.current_project_path:
            project_name = self.current_project_path.name
        payload = json.dumps({
            "channels": channels,
            "project": project_name,
            "node_id": self.config.system.node_id,
            "node_name": self.config.system.node_name,
        })
        self.mqtt_client.publish(
            f"{base}/channels/claimed", payload, retain=True, qos=1
        )
        logger.info(f"Published channel claims ({len(channels)} channels)")

    def _clear_channel_claims(self):
        """Clear retained channel claims on acquisition stop or shutdown."""
        if not self.mqtt_client or not self.config:
            return
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/channels/claimed", "", retain=True, qos=1
        )
        logger.debug("Cleared channel claims")

    # =========================================================================
    # NON-BLOCKING MQTT PUBLISH QUEUE
    # =========================================================================

    def _queue_publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        """Queue an MQTT message for non-blocking publish.

        This method returns immediately, even if the broker is slow or disconnected.
        Messages are published by a background thread.

        On queue full: drops the OLDEST queued message and inserts the new one.
        For real-time telemetry, the latest reading is always more valuable than
        a stale one. QoS-1+ messages are kept (they need delivery guarantees) and
        only QoS-0 messages get dropped.

        Args:
            topic: MQTT topic
            payload: JSON payload string
            qos: Quality of service (0, 1, or 2)
            retain: Whether to retain the message
        """
        try:
            self._publish_queue.put_nowait((topic, payload, qos, retain))
        except queue.Full:
            # Queue is full — drop the oldest QoS-0 message to make room for
            # this newer one. This keeps live data fresh during slow-broker
            # periods instead of accumulating a backlog of stale values.
            try:
                # Find and drop the oldest QoS-0 message
                with self._publish_queue.mutex:
                    dropped = None
                    for i, (t, p, q, r) in enumerate(self._publish_queue.queue):
                        if q == 0:
                            dropped = self._publish_queue.queue[i]
                            del self._publish_queue.queue[i]
                            break
                if dropped:
                    # Now there's space — insert the new message
                    self._publish_queue.put_nowait((topic, payload, qos, retain))
                    self._publish_queue_drops += 1
                else:
                    # All queued messages are QoS-1+ (delivery-guaranteed) —
                    # we must drop the new one to honor the QoS contract.
                    self._publish_queue_drops += 1
            except Exception:
                self._publish_queue_drops += 1
            if self._publish_queue_drops % 100 == 1:
                logger.warning(
                    f"MQTT publish queue full — dropped oldest message to keep "
                    f"latest data fresh ({self._publish_queue_drops} drops total). "
                    f"Check MQTT broker performance."
                )

    def _start_publish_queue_thread(self):
        """Start the background publish queue drain thread."""
        if self._publish_thread is None or not self._publish_thread.is_alive():
            self._publish_thread = threading.Thread(
                target=self._publish_queue_loop,
                name="MQTTPublishQueue",
                daemon=True
            )
            self._publish_thread.start()
            logger.info("Started non-blocking MQTT publish queue thread")

    def _publish_queue_loop(self):
        """Background thread that drains the publish queue.

        Runs until the service stops. Publishes messages with timeout to prevent
        blocking indefinitely on broker issues. Failed publishes are re-queued
        with a max retry count to prevent infinite loops.
        """
        MAX_RETRIES = 3
        RETRY_BACKOFF_S = 0.5

        while self.running:
            try:
                # Wait for message with timeout (allows clean shutdown)
                item = self._publish_queue.get(timeout=1.0)
                # Items are (topic, payload, qos, retain) or (topic, payload, qos, retain, retry_count)
                if len(item) == 5:
                    topic, payload, qos, retain, retry_count = item
                else:
                    topic, payload, qos, retain = item
                    retry_count = 0

                try:
                    # Publish with client (paho-mqtt handles reconnection)
                    if self.mqtt_client and self.mqtt_client.is_connected():
                        self.mqtt_client.publish(topic, payload, qos=qos, retain=retain)
                    else:
                        # Client not connected - re-queue for retry
                        if retry_count < MAX_RETRIES:
                            logger.warning(f"MQTT not connected, re-queuing message to {topic} (retry {retry_count + 1}/{MAX_RETRIES})")
                            time.sleep(RETRY_BACKOFF_S * (retry_count + 1))
                            try:
                                self._publish_queue.put_nowait((topic, payload, qos, retain, retry_count + 1))
                            except queue.Full:
                                logger.error(f"MQTT publish queue full, dropping retry message to {topic}")
                        else:
                            logger.error(f"MQTT message to {topic} dropped after {MAX_RETRIES} retries (client not connected)")
                except Exception as e:
                    # Publish call itself failed - re-queue with backoff
                    if retry_count < MAX_RETRIES:
                        logger.warning(f"MQTT publish failed for {topic}, re-queuing (retry {retry_count + 1}/{MAX_RETRIES}): {e}", exc_info=True)
                        time.sleep(RETRY_BACKOFF_S * (retry_count + 1))
                        try:
                            self._publish_queue.put_nowait((topic, payload, qos, retain, retry_count + 1))
                        except queue.Full:
                            logger.error(f"MQTT publish queue full, dropping retry message to {topic}")
                    else:
                        logger.error(f"MQTT message to {topic} dropped after {MAX_RETRIES} retries: {e}", exc_info=True)

                self._publish_queue.task_done()
            except queue.Empty:
                # No messages - continue loop
                continue
            except Exception as e:
                logger.error(f"Publish queue error: {e}", exc_info=True)

        # Drain remaining messages on shutdown
        while not self._publish_queue.empty():
            try:
                item = self._publish_queue.get_nowait()
                topic, payload, qos, retain = item[0], item[1], item[2], item[3]
                if self.mqtt_client and self.mqtt_client.is_connected():
                    self.mqtt_client.publish(topic, payload, qos=qos, retain=retain)
                self._publish_queue.task_done()
            except queue.Empty:
                break
            except Exception as e:
                logger.warning(f"Failed to drain publish queue message: {e}")

        logger.info("MQTT publish queue thread stopped")

    def _publish_simple_value(self, channel_name: str, value: float, units: str = ''):
        """Publish a simple value without requiring channel config.

        Used for system channels (sys.*) and other synthetic values
        that don't have hardware channel configuration.
        """
        try:
            base = self.get_topic_base()
            payload = {
                "value": value,
                "timestamp": datetime.now().isoformat(),
                "units": units,
                "quality": "good"
            }
            # Use non-blocking queue for simple value publishing
            self._queue_publish(f"{base}/channels/{channel_name}", json.dumps(payload))
        except Exception as e:
            logger.error(f"Error publishing {channel_name}: {e}")

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

            # Determine specific error status from raw value
            # Open thermocouple detection: NI DAQmx returns ~1e308 for open TC
            error_status = "disconnected"
            error_string = "NaN"
            if raw_value is not None:
                if isinstance(raw_value, float):
                    if math.isinf(raw_value):
                        error_status = "overflow"
                        error_string = "Inf"
                    elif abs(raw_value) > 1e300:  # Open thermocouple threshold
                        error_status = "open_thermocouple"
                        error_string = "Open TC"

            # Get SOE acquisition timestamp (microseconds since epoch)
            acquisition_ts_us = self.channel_acquisition_ts_us.get(channel_name, 0)

            # Get quality from remote node if available, otherwise determine locally
            remote_quality = getattr(self, 'channel_qualities', {}).get(channel_name)

            # Handle NaN - JSON doesn't support NaN, so use null and set quality to "bad"
            if is_nan:
                payload = {
                    "value": None,  # JSON null
                    "value_string": error_string,  # Human readable (NaN, Open TC, Inf)
                    "timestamp": datetime.now().isoformat(),
                    "acquisition_ts_us": acquisition_ts_us,  # SOE: microsecond precision
                    "units": channel.units,
                    "quality": "bad",  # NaN always means bad quality
                    "status": error_status  # More specific: disconnected, open_thermocouple, overflow
                }
            else:
                # Use remote node's quality if available, otherwise assume good
                quality = remote_quality if remote_quality else "good"
                payload = {
                    "value": value,
                    "timestamp": datetime.now().isoformat(),
                    "acquisition_ts_us": acquisition_ts_us,  # SOE: microsecond precision
                    "units": channel.units,
                    "quality": quality,
                    "status": "normal" if quality == "good" else "uncertain"
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

            # Use non-blocking queue for channel value publishing (most frequent operation)
            # This prevents the publish loop from blocking if broker is slow/disconnected
            self._queue_publish(f"{base}/channels/{channel_name}", json.dumps(payload))
        except Exception as e:
            logger.error(f"Error publishing {channel_name}: {e}")

    def _publish_channels_batch(self, values: Dict[str, Any]):
        """
        Publish all channel values in a single lean batch message.

        Lean format — shared fields appear once, per-channel data is minimal:
        {
          "t": "2026-03-05T18:03:09",     # timestamp (once)
          "ts_us": 1741198989619452,       # acquisition epoch µs (once)
          "v": {"Ch1": 23.45, "Ch2": null},# values (null = bad/disconnected)
          "bad": ["Ch2"],                  # quality=bad channels
          "alarm": ["Ch3"],               # quality=alarm channels (over limit)
          "warn": ["Ch7"]                 # quality=warning channels
        }
        Units are sent at config time and omitted from batch.
        Channels not in bad/alarm/warn are quality=good, status=normal.
        """
        import math
        if not self.mqtt_client:
            return

        try:
            base = self.get_topic_base()
            timestamp = datetime.now().isoformat()
            ts_us = int(time.time() * 1_000_000)

            v = {}
            bad = []
            alarm = []
            warn = []

            for channel_name, value in values.items():
                if channel_name not in self.config.channels:
                    continue

                channel = self.config.channels[channel_name]

                if getattr(channel, 'is_crio', False):
                    continue

                is_nan = isinstance(value, float) and math.isnan(value)

                if is_nan:
                    v[channel_name] = None
                    bad.append(channel_name)
                else:
                    v[channel_name] = value

                    # Check limits (each limit is independent)
                    numeric_value = float(value) if isinstance(value, (int, float)) else (1.0 if value else 0.0)
                    is_alarm = (channel.low_limit is not None and numeric_value < channel.low_limit) or \
                               (channel.high_limit is not None and numeric_value > channel.high_limit)
                    is_warn = (not is_alarm) and (
                        (channel.low_warning is not None and numeric_value < channel.low_warning) or
                        (channel.high_warning is not None and numeric_value > channel.high_warning)
                    )
                    if is_alarm:
                        alarm.append(channel_name)
                    elif is_warn:
                        warn.append(channel_name)

            batch_payload = {'t': timestamp, 'ts_us': ts_us, 'v': v}
            if bad:
                batch_payload['bad'] = bad
            if alarm:
                batch_payload['alarm'] = alarm
            if warn:
                batch_payload['warn'] = warn

            self._queue_publish(f"{base}/channels/batch", json.dumps(batch_payload))

        except Exception as e:
            logger.error(f"Error publishing channels batch: {e}")

    def _publish_session_status(self):
        """
        Publish session/acquisition status.

        This matches the cRIO/Opto22 session/status topic for frontend compatibility.
        """
        if not self.mqtt_client:
            return

        try:
            base = self.get_topic_base()
            session_active = getattr(self, 'test_session_active', False)

            payload = {
                'acquiring': self.acquiring,
                'recording': self.recording,
                'session_active': session_active,
                'timestamp': datetime.now().isoformat()
            }

            # Add session info if available
            if session_active and hasattr(self, 'test_session_id'):
                payload['session_id'] = self.test_session_id
                if hasattr(self, 'test_session_start_time') and self.test_session_start_time:
                    elapsed = (datetime.now() - self.test_session_start_time).total_seconds()
                    payload['session_elapsed_sec'] = round(elapsed, 1)

            self.mqtt_client.publish(
                f"{base}/session/status",
                json.dumps(payload),
                qos=0
            )

        except Exception as e:
            logger.error(f"Error publishing session status: {e}")

    def _publish_config_response(self, request_type: str, success: bool,
                                   data: Optional[Dict] = None, error: Optional[str] = None):
        """
        Publish config operation response.

        This matches the cRIO/Opto22 config/response topic for frontend compatibility.
        """
        if not self.mqtt_client:
            return

        try:
            base = self.get_topic_base()
            payload = {
                'request_type': request_type,
                'success': success,
                'timestamp': datetime.now().isoformat()
            }

            if data:
                payload['data'] = data
            if error:
                payload['error'] = error

            self.mqtt_client.publish(
                f"{base}/config/response",
                json.dumps(payload),
                qos=1
            )

        except Exception as e:
            logger.error(f"Error publishing config response: {e}")

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
        # PERMISSION CHECK
        if not self._has_permission(Permission.ACK_ALARMS):
            logger.warning("[SECURITY] Alarm acknowledge denied - insufficient permissions")
            return

        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarmId') or payload.get('alarm_id')
        channel = payload.get('channel')  # cRIO uses channel name
        user = payload.get('user', 'Unknown')

        if alarm_id or channel:
            logger.info(f"Alarm acknowledged: {alarm_id or channel} by {user}")

            # In CRIO mode, forward to cRIO (cRIO owns alarm state)
            if self.config.system.project_mode == ProjectMode.CRIO:
                self._forward_alarm_ack_to_crio(channel or alarm_id, user)

            # Use enhanced alarm manager if available (for local/PC mode)
            if self.alarm_manager:
                self.alarm_manager.acknowledge_alarm(alarm_id or channel, user)
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
        # PERMISSION CHECK
        if not self._has_permission(Permission.RESET_ALARMS):
            logger.warning("[SECURITY] Alarm reset denied - insufficient permissions")
            return

        if not isinstance(payload, dict):
            return
        alarm_id = payload.get('alarm_id')
        user = payload.get('user', 'Unknown')
        if alarm_id and self.alarm_manager:
            self.alarm_manager.reset_alarm(alarm_id, user)
            logger.info(f"Alarm reset: {alarm_id} by {user}")

    def _handle_alarm_shelve(self, payload: Any):
        """Shelve (temporarily suppress) an alarm"""
        # PERMISSION CHECK
        if not self._has_permission(Permission.SHELVE_ALARMS):
            logger.warning("[SECURITY] Alarm shelve denied - insufficient permissions")
            return

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

    # =========================================================================
    # SAFETY / INTERLOCK HANDLERS
    # =========================================================================

    def _handle_safety_latch_arm(self, payload: Any):
        """Arm the safety latch"""
        if not self.safety_manager:
            return
        user = payload.get('user', 'Unknown') if isinstance(payload, dict) else 'Unknown'
        if self.safety_manager.arm_latch(user):
            logger.info(f"Safety latch armed by {user}")
        else:
            logger.warning(f"Failed to arm safety latch - user: {user}")

    def _handle_safety_latch_disarm(self, payload: Any):
        """Disarm the safety latch"""
        if not self.safety_manager:
            return
        user = payload.get('user', 'Unknown') if isinstance(payload, dict) else 'Unknown'
        self.safety_manager.disarm_latch(user)
        logger.info(f"Safety latch disarmed by {user}")

    def _handle_safety_trip_reset(self, payload: Any):
        """Reset the trip state"""
        if not self.safety_manager:
            return
        user = payload.get('user', 'Unknown') if isinstance(payload, dict) else 'Unknown'
        if self.safety_manager.reset_trip(user):
            logger.info(f"Safety trip reset by {user}")
        else:
            logger.warning(f"Failed to reset trip - interlocks still failed")

    def _handle_safety_status_request(self):
        """Publish safety status"""
        if self.safety_manager:
            self.safety_manager.publish_status()

    def _handle_safety_config_update(self, payload: Any):
        """Update safe state configuration"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        self.safety_manager.update_safe_state_config(payload)
        logger.info("Safe state config updated")

    def _handle_interlock_add(self, payload: Any):
        """Add a new interlock"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        user = payload.get('user', 'system')
        reason = payload.get('reason', '')
        interlock = Interlock.from_dict(payload)
        result = self.safety_manager.add_interlock(interlock, user, reason)
        if result:
            logger.info(f"Interlock added: {interlock.name}")
        else:
            # Blocked by safety guard — notify frontend
            base = self.get_topic_base()
            self.mqtt_client.publish(
                f"{base}/interlocks/error",
                json.dumps({'error': 'blocked', 'interlock_id': interlock.id,
                           'message': 'Cannot modify critical interlock while ARMED/TRIPPED'}),
                qos=1)

    def _handle_interlock_update(self, payload: Any):
        """Update an existing interlock"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        interlock_id = payload.get('id')
        user = payload.get('user', 'system')
        reason = payload.get('reason', '')
        if interlock_id:
            success = self.safety_manager.update_interlock(interlock_id, payload, user, reason)
            if success:
                logger.info(f"Interlock updated: {interlock_id}")
            else:
                base = self.get_topic_base()
                self.mqtt_client.publish(
                    f"{base}/interlocks/error",
                    json.dumps({'error': 'blocked', 'interlock_id': interlock_id,
                               'message': 'Cannot modify critical interlock while ARMED/TRIPPED'}),
                    qos=1)

    def _handle_interlock_remove(self, payload: Any):
        """Remove an interlock"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        interlock_id = payload.get('id')
        user = payload.get('user', 'system')
        reason = payload.get('reason', '')
        if interlock_id:
            success = self.safety_manager.remove_interlock(interlock_id, user, reason)
            if success:
                logger.info(f"Interlock removed: {interlock_id}")
            else:
                base = self.get_topic_base()
                self.mqtt_client.publish(
                    f"{base}/interlocks/error",
                    json.dumps({'error': 'blocked', 'interlock_id': interlock_id,
                               'message': 'Cannot remove critical interlock while ARMED/TRIPPED'}),
                    qos=1)

    def _handle_interlock_bypass(self, payload: Any):
        """Bypass or un-bypass an interlock"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        interlock_id = payload.get('id')
        bypass = payload.get('bypass', True)
        user = payload.get('user', 'Unknown')
        reason = payload.get('reason', '')
        if interlock_id:
            self.safety_manager.bypass_interlock(interlock_id, bypass, user, reason)
            action = 'bypassed' if bypass else 'un-bypassed'
            logger.info(f"Interlock {action}: {interlock_id} by {user}")

    def _handle_interlock_sync(self, payload: Any):
        """Sync interlock from frontend (add or update)"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        reason = payload.get('reason', 'frontend_sync')
        interlock = Interlock.from_dict(payload)
        self.safety_manager.add_interlock(interlock, 'frontend_sync', reason)

    def _handle_interlocks_list(self):
        """Publish list of all interlocks"""
        if not self.safety_manager:
            return
        base = self.get_topic_base()
        interlocks = [i.to_dict() for i in self.safety_manager.get_all_interlocks()]
        self.mqtt_client.publish(
            f"{base}/interlocks/list/response",
            json.dumps({'interlocks': interlocks}),
            qos=1
        )

    def _handle_interlock_acknowledge_trip(self, payload: Any):
        """Acknowledge a tripped interlock (IEC 61511 operator response)"""
        if not self.safety_manager or not isinstance(payload, dict):
            return
        interlock_id = payload.get('id')
        user = payload.get('user', 'unknown')
        reason = payload.get('reason', '')
        if not interlock_id:
            return
        result = self.safety_manager.acknowledge_trip(interlock_id, user, reason)
        if result:
            self._publish_safety_status()

    def _handle_alarm_config_sync(self, payload: Any):
        """Sync alarm configs from frontend SafetyTab to backend AlarmManager.

        Receives alarm configuration updates from the frontend and applies them
        to the backend AlarmManager, closing the alarm config sync gap.
        """
        if not self.alarm_manager or not isinstance(payload, dict):
            return
        configs = payload.get('configs', [])
        updated = 0
        for cfg in configs:
            alarm_id = cfg.get('id')
            if not alarm_id:
                continue
            existing = self.alarm_manager.get_alarm_config(alarm_id)
            if existing:
                # Update existing alarm config with frontend values
                severity_str = cfg.get('severity', 'medium').upper()
                severity_map = {
                    'CRITICAL': AlarmSeverity.CRITICAL,
                    'HIGH': AlarmSeverity.HIGH,
                    'MEDIUM': AlarmSeverity.MEDIUM,
                    'LOW': AlarmSeverity.LOW
                }
                existing.severity = severity_map.get(severity_str, AlarmSeverity.MEDIUM)
                existing.high_high = cfg.get('high_high')
                existing.high = cfg.get('high')
                existing.low = cfg.get('low')
                existing.low_low = cfg.get('low_low')
                existing.deadband = cfg.get('deadband', 0)
                existing.on_delay_s = cfg.get('on_delay_s', 0)
                existing.off_delay_s = cfg.get('off_delay_s', 0)
                existing.enabled = cfg.get('enabled', False)
                behavior = cfg.get('behavior', 'auto_clear')
                behavior_map = {
                    'auto_clear': LatchBehavior.AUTO_CLEAR,
                    'latch': LatchBehavior.LATCH,
                    'timed_latch': LatchBehavior.TIMED_LATCH
                }
                existing.latch_behavior = behavior_map.get(behavior, LatchBehavior.AUTO_CLEAR)
                updated += 1
            else:
                # Create new alarm config from frontend data
                channel_name = cfg.get('channel', '')
                severity_str = cfg.get('severity', 'medium').upper()
                severity_map = {
                    'CRITICAL': AlarmSeverity.CRITICAL,
                    'HIGH': AlarmSeverity.HIGH,
                    'MEDIUM': AlarmSeverity.MEDIUM,
                    'LOW': AlarmSeverity.LOW
                }
                behavior = cfg.get('behavior', 'auto_clear')
                behavior_map = {
                    'auto_clear': LatchBehavior.AUTO_CLEAR,
                    'latch': LatchBehavior.LATCH,
                    'timed_latch': LatchBehavior.TIMED_LATCH
                }
                new_config = AlarmConfig(
                    id=alarm_id,
                    channel=channel_name,
                    name=cfg.get('name', channel_name),
                    description=cfg.get('description', ''),
                    enabled=cfg.get('enabled', False),
                    severity=severity_map.get(severity_str, AlarmSeverity.MEDIUM),
                    high_high=cfg.get('high_high'),
                    high=cfg.get('high'),
                    low=cfg.get('low'),
                    low_low=cfg.get('low_low'),
                    deadband=cfg.get('deadband', 0),
                    on_delay_s=cfg.get('on_delay_s', 0),
                    off_delay_s=cfg.get('off_delay_s', 0),
                    latch_behavior=behavior_map.get(behavior, LatchBehavior.AUTO_CLEAR),
                    group=cfg.get('group', ''),
                    actions=[]
                )
                self.alarm_manager.add_alarm_config(new_config)
                updated += 1
        if updated:
            logger.info(f"Synced {updated} alarm configs from frontend")

    def _handle_safety_alarm_delete(self, payload: Any):
        """Cascade-purge alarm configs for a deleted channel/variable/script.

        Called when ConfigurationTab deletes a channel (or a user variable /
        python script reference is removed). Without this handler, alarm
        configs become orphaned and may continue to evaluate against ghost
        channels — leading to phantom trips or stale UI state.

        Accepts either:
            { "channel": "<name>" }   — primary form
            { "alarm_id": "<id>" }    — for direct ID-based delete
        """
        if not self.alarm_manager or not isinstance(payload, dict):
            return
        channel = payload.get('channel')
        alarm_id = payload.get('alarm_id')
        removed = 0
        if alarm_id:
            existing = self.alarm_manager.get_alarm_config(alarm_id)
            if existing:
                self.alarm_manager.remove_alarm_config(alarm_id)
                removed += 1
        if channel:
            # Iterate over a snapshot — remove_alarm_config mutates the dict.
            for cfg in list(self.alarm_manager.get_configs_for_channel(channel)):
                self.alarm_manager.remove_alarm_config(cfg.id)
                removed += 1
        if removed:
            logger.info(f"Cascade-deleted {removed} alarm config(s) for channel={channel!r} alarm_id={alarm_id!r}")

    def _handle_safety_interlock_delete(self, payload: Any):
        """Cascade-purge interlocks (or interlock conditions) referencing
        a deleted channel/variable/script.

        Two modes:
          1) Whole-interlock delete by id: { "interlock_id": "<id>" }
          2) Reference cascade: { "channel": "<name>" } — remove every
             interlock that has at least one condition pointing at the
             named channel/variable/script. Critical interlocks armed/tripped
             are protected by remove_interlock's existing guard.
        """
        if not self.safety_manager or not isinstance(payload, dict):
            return
        interlock_id = payload.get('interlock_id')
        channel = payload.get('channel')
        user = payload.get('user', 'system')
        reason = payload.get('reason', 'Cascade delete from channel removal')
        removed = 0
        if interlock_id:
            if self.safety_manager.remove_interlock(interlock_id, user=user, reason=reason):
                removed += 1
        if channel:
            # Snapshot — remove_interlock mutates the interlocks dict.
            try:
                with self.safety_manager.lock:
                    candidates = list(self.safety_manager.interlocks.values())
            except Exception:
                candidates = list(getattr(self.safety_manager, 'interlocks', {}).values())
            for il in candidates:
                # Remove if any condition references the deleted channel/var.
                refs_channel = any(
                    (getattr(c, 'channel', None) == channel)
                    or (getattr(c, 'variable_id', None) == channel)
                    for c in (il.conditions or [])
                )
                if refs_channel:
                    if self.safety_manager.remove_interlock(il.id, user=user, reason=reason):
                        removed += 1
                    else:
                        logger.warning(
                            f"Could not cascade-delete interlock {il.id!r} ({il.name!r}) — "
                            f"likely critical+armed; leaving in place"
                        )
        if removed:
            logger.info(f"Cascade-deleted {removed} interlock(s) for channel={channel!r} interlock_id={interlock_id!r}")

    # =========================================================================
    # PID CONTROL HANDLERS
    # =========================================================================

    def _handle_pid_list_loops(self):
        """Publish list of all PID loops"""
        if not self.pid_engine:
            return
        base = self.get_topic_base()
        loops = [loop.to_config_dict() for loop in self.pid_engine.get_all_loops()]
        self.mqtt_client.publish(
            f"{base}/pid/loops/response",
            json.dumps({'loops': loops, 'count': len(loops)}),
            qos=1
        )

    def _handle_pid_add_loop(self, payload: Any):
        """Add a new PID loop"""
        if not self.pid_engine or not isinstance(payload, dict):
            return

        try:
            loop = PIDLoop.from_dict(payload)
            if self.pid_engine.add_loop(loop):
                self._publish_pid_response(True, f"Added PID loop: {loop.name}")
                self._handle_pid_list_loops()  # Publish updated list
            else:
                self._publish_pid_response(False, f"Loop ID already exists: {loop.id}")
        except Exception as e:
            logger.error(f"Failed to add PID loop: {e}")
            self._publish_pid_response(False, str(e))

    def _handle_pid_remove_loop(self, payload: Any):
        """Remove a PID loop"""
        if not self.pid_engine:
            return

        loop_id = payload.get('id') if isinstance(payload, dict) else payload
        if self.pid_engine.remove_loop(loop_id):
            self._publish_pid_response(True, f"Removed PID loop: {loop_id}")
            self._handle_pid_list_loops()
        else:
            self._publish_pid_response(False, f"Loop not found: {loop_id}")

    def _handle_pid_loop_config(self, loop_id: str, payload: Any):
        """Get or update PID loop configuration"""
        if not self.pid_engine:
            return

        base = self.get_topic_base()

        if not payload or payload == {}:
            # GET - return current config
            loop = self.pid_engine.get_loop(loop_id)
            if loop:
                self.mqtt_client.publish(
                    f"{base}/pid/loop/{loop_id}/config/response",
                    json.dumps(loop.to_config_dict()),
                    qos=1
                )
            else:
                self._publish_pid_response(False, f"Loop not found: {loop_id}")
        else:
            # UPDATE - apply configuration changes
            if isinstance(payload, dict):
                if self.pid_engine.update_loop(loop_id, payload):
                    self._publish_pid_response(True, f"Updated loop: {loop_id}")
                else:
                    self._publish_pid_response(False, f"Loop not found: {loop_id}")

    def _handle_pid_loop_setpoint(self, loop_id: str, payload: Any):
        """Set PID loop setpoint"""
        if not self.pid_engine:
            return

        setpoint = payload.get('value') if isinstance(payload, dict) else payload
        try:
            setpoint = float(setpoint)
            if self.pid_engine.set_setpoint(loop_id, setpoint):
                self._publish_pid_response(True, f"Setpoint set to {setpoint}")
            else:
                self._publish_pid_response(False, f"Loop not found: {loop_id}")
        except (ValueError, TypeError):
            self._publish_pid_response(False, "Invalid setpoint value")

    def _handle_pid_loop_mode(self, loop_id: str, payload: Any):
        """Set PID loop mode (auto/manual)"""
        if not self.pid_engine:
            return

        mode = payload.get('value') if isinstance(payload, dict) else payload
        if self.pid_engine.set_mode(loop_id, mode):
            self._publish_pid_response(True, f"Mode set to {mode}")
        else:
            self._publish_pid_response(False, f"Invalid mode or loop not found")

    def _handle_pid_loop_output(self, loop_id: str, payload: Any):
        """Set manual output value"""
        if not self.pid_engine:
            return

        output = payload.get('value') if isinstance(payload, dict) else payload
        try:
            output = float(output)
            if self.pid_engine.set_manual_output(loop_id, output):
                self._publish_pid_response(True, f"Manual output set to {output}")
            else:
                self._publish_pid_response(False, f"Loop not found: {loop_id}")
        except (ValueError, TypeError):
            self._publish_pid_response(False, "Invalid output value")

    def _handle_pid_loop_tuning(self, loop_id: str, payload: Any):
        """Update PID tuning parameters"""
        if not self.pid_engine or not isinstance(payload, dict):
            return

        kp = payload.get('kp')
        ki = payload.get('ki')
        kd = payload.get('kd')

        if kp is None or ki is None or kd is None:
            self._publish_pid_response(False, "Missing kp, ki, or kd parameter")
            return

        try:
            if self.pid_engine.set_tuning(loop_id, float(kp), float(ki), float(kd)):
                self._publish_pid_response(True, f"Tuning updated: Kp={kp}, Ki={ki}, Kd={kd}")
            else:
                self._publish_pid_response(False, f"Loop not found: {loop_id}")
        except (ValueError, TypeError):
            self._publish_pid_response(False, "Invalid tuning values")

    def _publish_pid_response(self, success: bool, message: str):
        """Publish response to PID commands"""
        base = self.get_topic_base()
        self.mqtt_client.publish(
            f"{base}/pid/response",
            json.dumps({'success': success, 'message': message}),
            qos=1
        )

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
        # PERMISSION CHECK
        if not self._has_permission(Permission.CONTROL_OUTPUTS):
            logger.warning("[SECURITY] Output control denied - insufficient permissions")
            self._publish_output_response(False, error="Permission denied")
            return

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
        if channel.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                                        ChannelType.COUNTER_OUTPUT, ChannelType.PULSE_OUTPUT):
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

        # Reverse-scale: user sends engineering units, hardware expects raw values
        # e.g., user sets 50% valve → reverse_scaling converts to 5V raw for hardware
        eng_value = value  # Preserve engineering value for cache/display
        raw_value = reverse_scaling(channel, float(value)) if isinstance(value, (int, float)) else value

        # Write the value
        logger.info(f"Setting output {channel_name} = {value} (raw: {raw_value})")

        try:
            # Determine which backend handles this channel
            source_type = getattr(channel, 'source_type', 'local')
            source_node_id = getattr(channel, 'source_node_id', '')
            is_modbus = channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL) or source_type == 'cfp'

            # Auto-detect cRIO channels: if physical_channel starts with "Mod" (no chassis prefix)
            # it's a cRIO channel - local cDAQ channels have chassis prefix like "cDAQ1Mod1/ai0"
            # Only auto-promote in cRIO mode; in cDAQ mode all channels are local.
            physical_ch = getattr(channel, 'physical_channel', '')
            if (source_type != 'crio' and physical_ch.startswith('Mod')
                    and self.config.system.project_mode == ProjectMode.CRIO):
                # This is a cRIO channel - route to cRIO regardless of online status
                # (MQTT will queue the message if cRIO isn't connected yet)
                source_type = 'crio'
                # Try to find a registered cRIO, otherwise use default
                crio_nodes = self.device_discovery.get_crio_nodes() if self.device_discovery else []
                if crio_nodes:
                    source_node_id = crio_nodes[0].get('node_id', 'crio-001')
                else:
                    source_node_id = 'crio-001'  # Default cRIO node ID
                logger.debug(f"Auto-detected cRIO channel {channel_name} -> {source_node_id}")

            # Serialize the entire write+cache update under output_write_lock
            # so this MQTT-driven write can't interleave with concurrent writes
            # from scripts, triggers, watchdogs, or safe-state.
            with self.output_write_lock:
                if source_type == 'crio':
                    # Forward command to cRIO node via MQTT
                    if source_node_id and self.mqtt_client:
                        base = self.get_topic_base()
                        # Extract base topic (e.g., "nisystem" from "nisystem/daq")
                        mqtt_base = base.split('/')[0] if '/' in base else base
                        # Send to cRIO's command topic with TAG name in payload
                        # (cRIO stores output_tasks by TAG name, not physical channel)
                        # Include physical_channel for fallback when config not pushed to cRIO
                        crio_topic = f"{mqtt_base}/nodes/{source_node_id}/commands/output"
                        cmd_payload = {
                            "channel": channel_name,  # Use TAG name
                            "value": raw_value,
                            "physical_channel": physical_ch  # Fallback for when config not pushed
                        }
                        self.mqtt_client.publish(crio_topic, json.dumps(cmd_payload), qos=1)
                        logger.info(f"Forwarded output command to cRIO: {source_node_id} {channel_name} ({physical_ch}) = {raw_value}")
                    else:
                        logger.error(f"Cannot forward to cRIO - missing node_id or MQTT client")
                        self._publish_output_response(False, channel=channel_name, error="cRIO node not available")
                        return
                elif is_modbus and self.modbus_reader:
                    self.modbus_reader.write_channel(channel_name, raw_value)
                elif self.simulator:
                    self.simulator.write_channel(channel_name, raw_value)
                elif self.hardware_reader:
                    self.hardware_reader.write_channel(channel_name, raw_value)

                # Update cache with engineering value (for display)
                with self.values_lock:
                    self.channel_values[channel_name] = eng_value
                    self.channel_timestamps[channel_name] = time.time()

            # Publish engineering value for dashboard display
            self._publish_channel_value(channel_name, eng_value)

            # Publish success response with engineering value
            self._publish_output_response(True, channel=channel_name, value=eng_value)

            logger.info(f"Output {channel_name} set to {eng_value} (raw: {raw_value})")

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
        if channel.channel_type in (ChannelType.COUNTER, ChannelType.COUNTER_INPUT, ChannelType.FREQUENCY_INPUT):
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
        """Execute a safety action with full logging, verification, and ACK.

        Safety actions are critical - we must verify outputs actually changed.
        """
        if action_name not in self.config.safety_actions:
            logger.critical(
                f"SAFETY FAILURE: Unknown safety action '{action_name}' triggered by {trigger_source}! "
                f"This is a configuration error - safety response NOT executed!"
            )
            self._publish_alarm(
                trigger_source,
                f"CRITICAL: Safety action '{action_name}' not found - NO SAFETY RESPONSE!"
            )
            self._publish_safety_ack(action_name, trigger_source, False, "Action not found")
            return

        action = self.config.safety_actions[action_name]
        logger.warning(f"SAFETY: Executing action '{action_name}' triggered by {trigger_source}")

        # Track execution results
        executed = []
        failed = []
        verified = []
        verify_failed = []

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

        # Verify outputs were set correctly (read back and compare)
        # Small delay to allow hardware to update
        time.sleep(0.05)  # 50ms settling time

        for channel_name, expected_value in action.actions.items():
            if channel_name not in self.config.channels:
                continue
            try:
                with self.values_lock:
                    actual_value = self.channel_values.get(channel_name)

                if actual_value is None:
                    verify_failed.append(f"{channel_name}: no readback")
                    logger.error(f"SAFETY VERIFY: {channel_name} - no readback value")
                else:
                    # Compare values (handle bool/float comparison)
                    expected_num = float(expected_value) if isinstance(expected_value, (int, float)) else (1.0 if expected_value else 0.0)
                    actual_num = float(actual_value) if isinstance(actual_value, (int, float)) else (1.0 if actual_value else 0.0)

                    # Allow small tolerance for floating point
                    if abs(expected_num - actual_num) < 0.01:
                        verified.append(f"{channel_name}={actual_value}")
                        logger.info(f"SAFETY VERIFY: {channel_name} = {actual_value} (OK)")
                    else:
                        verify_failed.append(f"{channel_name}: expected {expected_value}, got {actual_value}")
                        logger.error(f"SAFETY VERIFY FAILED: {channel_name} expected {expected_value}, got {actual_value}")
            except Exception as e:
                verify_failed.append(f"{channel_name}: verify error - {e}")
                logger.error(f"SAFETY VERIFY ERROR: {channel_name} - {e}")

        # Determine overall success
        all_executed = len(failed) == 0
        all_verified = len(verify_failed) == 0
        success = all_executed and all_verified

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
        elif verify_failed:
            logger.critical(
                f"SAFETY ACTION '{action_name}' VERIFICATION FAILED! "
                f"Verified: {len(verified)}, Failed: {len(verify_failed)} - {verify_failed}"
            )
            self._publish_alarm(
                f"safety_{action_name}",
                f"CRITICAL: Safety action verification failed! {', '.join(verify_failed)}"
            )
        else:
            logger.warning(
                f"SAFETY: Action '{action_name}' completed and verified - "
                f"{len(executed)} commands executed, {len(verified)} verified"
            )

        # Publish ACK with verification status
        ack_message = "OK" if success else (
            f"Execute failed: {failed}" if failed else f"Verify failed: {verify_failed}"
        )
        self._publish_safety_ack(action_name, trigger_source, success, ack_message)

        # Publish alarm if configured
        if action.trigger_alarm:
            self._publish_alarm(trigger_source, action.alarm_message)

    def _publish_safety_ack(self, action_name: str, trigger_source: str, success: bool, message: str):
        """Publish safety action acknowledgment for verification tracking."""
        base = self.get_topic_base()
        payload = {
            "action": action_name,
            "trigger": trigger_source,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        # Safety ACKs use QoS 1 for reliable delivery
        self.mqtt_client.publish(
            f"{base}/safety/ack",
            json.dumps(payload),
            qos=1
        )
        logger.info(f"SAFETY ACK: {action_name} - {'SUCCESS' if success else 'FAILED'}: {message}")

    def _scan_loop(self):
        """Main scan loop - reads all inputs at scan rate.

        Uses epoch-anchored timing to prevent cumulative drift.
        Each scan targets an absolute time rather than sleeping relative
        to the end of the previous scan.
        """
        logger.info(f"Starting scan loop at {self.config.system.scan_rate_hz} Hz")
        next_scan_time = time.time()

        # Periodic scan timing diagnostic
        _scan_diag_interval = 30.0
        _scan_diag_next = time.time() + _scan_diag_interval
        _scan_diag_count = 0
        _scan_diag_total_ms = 0.0
        _scan_diag_max_ms = 0.0
        _scan_diag_overruns = 0

        while self.running:
            # Calculate interval dynamically to pick up runtime rate changes
            scan_interval = 1.0 / self.config.system.scan_rate_hz
            next_scan_time += scan_interval
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
                        # Check hardware reader health
                        if not self.hardware_reader.is_healthy():
                            if not getattr(self, '_reader_degraded_notified', False):
                                logger.error("[SCAN] Hardware reader unhealthy — attempting auto-reinit")
                                self._reader_degraded_notified = True
                                base = self.get_topic_base()
                                self.mqtt_client.publish(
                                    f"{base}/status/hardware_degraded",
                                    json.dumps({
                                        'health': self.hardware_reader.get_health_status(),
                                        'timestamp': datetime.now().isoformat(),
                                    }), qos=1)
                                # Auto-reinit: try to recreate the hardware reader
                                try:
                                    self._reinit_hardware_reader()
                                    logger.info("[SCAN] Hardware reader auto-reinit successful")
                                except Exception as reinit_err:
                                    logger.error(f"[SCAN] Hardware reader auto-reinit failed: {reinit_err}")
                        else:
                            self._reader_degraded_notified = False

                    # Read from Modbus devices (if configured)
                    # Modbus polls on its own background thread — just grab latest values
                    # Track expected vs received channels for COMM_FAIL detection
                    try:
                        if self.modbus_reader:
                            modbus_values = self.modbus_reader.get_latest_values()
                            if modbus_values:
                                raw_values.update(modbus_values)
                            # Detect offline Modbus channels: expected but not returned
                            expected_modbus = set(self.modbus_reader.channel_configs.keys())
                            missing_modbus = expected_modbus - set(modbus_values.keys()) if modbus_values else expected_modbus
                            for ch_name in missing_modbus:
                                raw_values.setdefault(ch_name, float('nan'))
                    except Exception as e:
                        logger.error(f"[SCAN] Modbus read failed: {e}")

                    # Read from external data sources (REST API, OPC-UA, etc.)
                    try:
                        if self.data_source_manager:
                            data_source_values = self.data_source_manager.get_all_values()
                            if data_source_values:
                                raw_values.update(data_source_values)
                    except Exception as e:
                        logger.error(f"[SCAN] Data source read failed: {e}")

                    # Apply scaling and update values under lock
                    # Track which channels have valid values for safety/alarm processing
                    valid_channels = set()

                    # Snapshot channel config to prevent race with config updates
                    channel_config_snapshot = dict(self.config.channels)

                    # Periodic scaling diagnostic (every 10 seconds)
                    _now = time.time()
                    _diag_scaling = getattr(self, '_diag_scaling_next', 0)
                    _do_scaling_diag = _now >= _diag_scaling
                    if _do_scaling_diag:
                        self._diag_scaling_next = _now + 10.0

                    with self.values_lock:
                        for name, raw_value in raw_values.items():
                            # Validate raw value first (catches NaN, Inf, open TC, etc.)
                            validated_raw, status = validate_and_clamp(raw_value)

                            # Apply scaling based on channel configuration
                            try:
                                channel = channel_config_snapshot.get(name)
                            except (KeyError, RuntimeError):
                                channel = None  # Channel removed during scan
                            if channel is not None:
                                # Don't apply scaling to output channels - they store engineering units directly
                                if channel.channel_type in (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT,
                                                               ChannelType.COUNTER_OUTPUT, ChannelType.PULSE_OUTPUT):
                                    self.channel_values[name] = raw_value
                                    if is_valid_value(raw_value):
                                        valid_channels.add(name)
                                else:
                                    # Only scale valid values
                                    if is_valid_value(validated_raw):
                                        scaled_value = apply_scaling(channel, validated_raw)

                                        # Scaling diagnostic — log every 10s so we can see what's happening
                                        if _do_scaling_diag:
                                            logger.info(
                                                f"[SCALING] {name}: raw={validated_raw:.4f} "
                                                f"scaled={scaled_value:.4f} "
                                                f"type={channel.channel_type.value} "
                                                f"scale_type={channel.scale_type} "
                                                f"four_twenty={channel.four_twenty_scaling} "
                                                f"eng_min={channel.eng_units_min} eng_max={channel.eng_units_max} "
                                                f"pre_min={channel.pre_scaled_min} pre_max={channel.pre_scaled_max} "
                                                f"sc_min={channel.scaled_min} sc_max={channel.scaled_max} "
                                                f"slope={channel.scale_slope} offset={channel.scale_offset}"
                                            )

                                        # Validate scaled value too (scaling could produce bad values)
                                        if is_valid_value(scaled_value):
                                            self.channel_values[name] = scaled_value
                                            valid_channels.add(name)
                                        else:
                                            self.channel_values[name] = float('nan')
                                    else:
                                        # Invalid raw value -> NaN
                                        self.channel_values[name] = float('nan')
                                        # Log first occurrence of open thermocouple
                                        if status == 'open_tc' and name not in self._logged_open_tc:
                                            logger.warning(f"Open thermocouple detected on {name}")
                                            self._logged_open_tc.add(name)
                                    # Store raw value for diagnostics (even if invalid)
                                    self.channel_raw_values[name] = raw_value
                            else:
                                self.channel_values[name] = validated_raw
                                if is_valid_value(validated_raw):
                                    valid_channels.add(name)
                            self.channel_timestamps[name] = start_time
                            # SOE: Store high-precision acquisition timestamp
                            self.channel_acquisition_ts_us[name] = acquisition_ts_us

                    # Check safety OUTSIDE the lock (only for valid values)
                    # In CRIO mode, cRIO handles safety/alarm for its channels
                    # PC only processes non-cRIO channels (or cDAQ mode processes all)
                    is_crio_mode = self.config.system.project_mode == ProjectMode.CRIO

                    for name in valid_channels:
                        if name in self.channel_values:
                            value = self.channel_values[name]
                            # Double-check validity before safety/alarm processing
                            if not is_valid_value(value):
                                continue

                            # Check if this is a cRIO channel that cRIO handles
                            channel = channel_config_snapshot.get(name)
                            is_crio_channel = channel and channel.is_crio if channel else False

                            # Skip safety/alarm processing for cRIO channels in CRIO mode
                            # cRIO evaluates these locally and publishes events
                            if is_crio_mode and is_crio_channel:
                                continue

                            # Legacy Modbus channels (channel_type == modbus_register/coil) skip
                            # safety limit checks — Modbus is not a safety-rated protocol.
                            # CFP channels transported via Modbus but carrying real signal types
                            # (thermocouple, voltage_input, etc.) DO get safety checks since
                            # they represent known, typed I/O modules.
                            is_legacy_modbus = channel and channel.is_modbus and getattr(channel, 'source_type', '') != 'cfp' if channel else False
                            if not is_legacy_modbus:
                                self._check_safety(name, value)

                            # Process through alarm manager (informational, all channel types)
                            if self.alarm_manager:
                                try:
                                    self.alarm_manager.process_value(name, value)
                                except Exception as e:
                                    logger.debug(f"Alarm manager error for {name}: {e}")

                    # Process user variables (accumulators, timers, stats, etc.)
                    try:
                        if self.user_variables:
                            self.user_variables.process_scan(self.channel_values)
                            # Process formula blocks (must be after process_scan so user vars are updated)
                            self.user_variables.process_formula_blocks(self.channel_values)
                    except Exception as e:
                        logger.error(f"[SCAN] User variables evaluation failed: {e}")

                    # Process PID control loops (deterministic timing critical)
                    try:
                        if self.pid_engine:
                            self.pid_engine.process_scan(self.channel_values, scan_interval)
                    except Exception as e:
                        logger.error(f"[SCAN] PID engine update failed: {e}")

                    # Process automation triggers
                    try:
                        if self.trigger_engine:
                            self.trigger_engine.process_scan(self.channel_values)
                    except Exception as e:
                        logger.error(f"[SCAN] Trigger engine evaluation failed: {e}")

                    # Process watchdogs (channel health monitoring)
                    try:
                        if self.watchdog_engine:
                            self.watchdog_engine.process_scan(self.channel_values, self.channel_timestamps)
                    except Exception as e:
                        logger.error(f"[SCAN] Watchdog engine check failed: {e}")

                    # Evaluate safety interlocks (backend-authoritative safety logic)
                    try:
                        if self.safety_manager:
                            _t_safety = time.time()
                            self.safety_manager.evaluate_all()
                            _safety_ms = (time.time() - _t_safety) * 1000
                            if _safety_ms > 10.0:
                                logger.warning(
                                    f"[SCAN] Safety evaluation took {_safety_ms:.1f}ms (>10ms)"
                                )
                    except Exception as e:
                        self._safety_eval_failures += 1
                        logger.error(f"[SCAN] Safety eval failed (#{self._safety_eval_failures}): {e}", exc_info=True)
                        if self._acq_events:
                            self._acq_events.emit(AcquisitionEvent.SAFETY_EVAL_FAILED, {
                                'error': str(e), 'consecutive_failures': self._safety_eval_failures,
                            }, severity='error')
                        if self._safety_eval_failures >= 3:
                            logger.critical("[SCAN] 3 consecutive safety eval failures — applying safe state")
                            if self._acq_events:
                                self._acq_events.emit(AcquisitionEvent.SAFETY_SAFE_STATE_APPLIED, {
                                    'reason': 'safety_evaluation_failure',
                                }, severity='error')
                            try:
                                self._handle_safe_state({'reason': 'safety_evaluation_failure'})
                            except Exception:
                                logger.error("[SCAN] Failed to apply safe state after safety eval failure")
                    else:
                        # Safety eval succeeded — reset failure counter
                        if self._safety_eval_failures > 0:
                            logger.info(f"[SCAN] Safety eval recovered after {self._safety_eval_failures} failures")
                            if self._acq_events:
                                self._acq_events.emit(AcquisitionEvent.SAFETY_EVAL_RECOVERED, {
                                    'recovered_after': self._safety_eval_failures,
                                })
                            self._safety_eval_failures = 0
                        self._last_safety_eval_time = time.time()

                    # === MULTI-PROJECT: Dispatch values to each active project ===
                    self._dispatch_values_to_projects(valid_channels, scan_interval)

                except Exception as e:
                    self._scan_consecutive_errors += 1
                    self._scan_total_errors += 1
                    logger.error(f"[SCAN] Error #{self._scan_consecutive_errors}: {e}", exc_info=True)
                    if self._acq_events:
                        self._acq_events.emit(AcquisitionEvent.SCAN_LOOP_ERROR, {
                            'error': str(e), 'consecutive': self._scan_consecutive_errors,
                        }, severity='error')
                    if self._scan_consecutive_errors >= 100:
                        logger.critical("[SCAN] 100 consecutive errors — auto-stopping acquisition")
                        if self._acq_events:
                            self._acq_events.emit(AcquisitionEvent.SCAN_LOOP_FATAL, {
                                'error': 'Auto-stopped after 100 consecutive scan failures',
                                'total_errors': self._scan_total_errors,
                            }, severity='error')
                        self._handle_acquire_stop()
                        break
                else:
                    # Scan succeeded — reset error counter
                    if self._scan_consecutive_errors > 0:
                        logger.info(f"[SCAN] Recovered after {self._scan_consecutive_errors} consecutive errors")
                        if self._acq_events:
                            self._acq_events.emit(AcquisitionEvent.SCAN_LOOP_RECOVERED, {
                                'recovered_after': self._scan_consecutive_errors,
                            })
                    self._scan_consecutive_errors = 0
                    self._scan_loop_healthy = True
                    self._last_successful_scan_time = time.time()

            # Track loop timing
            elapsed = time.time() - start_time
            self.last_scan_dt_ms = elapsed * 1000
            self._scan_timing.record(self.last_scan_dt_ms)

            # Diagnostic tracking
            if self.acquiring:
                _scan_diag_count += 1
                _scan_diag_total_ms += self.last_scan_dt_ms
                if self.last_scan_dt_ms > _scan_diag_max_ms:
                    _scan_diag_max_ms = self.last_scan_dt_ms

            now_diag = time.time()
            if now_diag >= _scan_diag_next:
                if _scan_diag_count > 0:
                    avg_ms = _scan_diag_total_ms / _scan_diag_count
                    hz_actual = _scan_diag_count / _scan_diag_interval
                    logger.info(
                        f"[SCAN DIAG] {_scan_diag_interval:.0f}s: "
                        f"scans={_scan_diag_count} ({hz_actual:.2f} Hz actual), "
                        f"avg={avg_ms:.2f}ms, max={_scan_diag_max_ms:.2f}ms, "
                        f"overruns={_scan_diag_overruns}, "
                        f"target={scan_interval*1000:.0f}ms ({self.config.system.scan_rate_hz} Hz)"
                    )
                _scan_diag_next = now_diag + _scan_diag_interval
                _scan_diag_count = 0
                _scan_diag_total_ms = 0.0
                _scan_diag_max_ms = 0.0
                _scan_diag_overruns = 0

            # Sleep until next epoch-anchored target (prevents cumulative drift)
            sleep_time = max(0, next_scan_time - time.time())
            # If we fell behind by more than one interval, reset to prevent burst catch-up
            if time.time() - next_scan_time >= scan_interval:
                _scan_diag_overruns += 1
                next_scan_time = time.time()
            time.sleep(sleep_time)

    def _publish_loop(self):
        """Publish loop - publishes values at publish rate.

        Uses epoch-anchored timing to prevent cumulative drift.
        """
        logger.info(f"Starting publish loop at {self.config.system.publish_rate_hz} Hz")

        publish_count = 0
        status_publish_counter = 0
        next_publish_time = time.time()

        while self.running:
            # Calculate interval dynamically to pick up runtime rate changes
            publish_interval = 1.0 / self.config.system.publish_rate_hz
            next_publish_time += publish_interval
            start_time = time.time()

            # Only publish if acquiring
            if self.acquiring:
                try:
                    with self.values_lock:
                        values = dict(self.channel_values)

                    if publish_count == 0:
                        logger.info(f"Publishing {len(values)} channels")

                    # Publish batch only — individual per-channel publishes removed
                    # to avoid 52+ MQTT messages per cycle (was causing cascading updates
                    # and ~13x message overhead). The batch contains all values the
                    # frontend needs in a single message.
                    self._publish_channels_batch(values)

                    # Multi-project: publish per-project channel batches
                    self._publish_project_channel_batches(values)

                    # Publish session status (cRIO/Opto22 pattern)
                    self._publish_session_status()

                    # Add system state channels (sys.*) for recording context
                    # These help understand why py.* values might be NaN when reviewing data
                    session_active = getattr(self, 'test_session_active', False)
                    values['sys.acquiring'] = 1.0 if self.acquiring else 0.0
                    values['sys.session_active'] = 1.0 if session_active else 0.0
                    values['sys.recording'] = 1.0 if (self.recording_manager and self.recording_manager.recording) else 0.0

                    # NOTE: sys.* values are NOT published via MQTT channels to avoid self-echo loop.
                    # State is already published via _publish_system_status() on status/system topic.
                    # The values dict entries above are kept for recording context only.

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
                        # Add sys.* channel configs for recording
                        channel_configs['sys.acquiring'] = {'units': 'bool', 'description': 'Acquisition active'}
                        channel_configs['sys.session_active'] = {'units': 'bool', 'description': 'Test session active'}
                        channel_configs['sys.recording'] = {'units': 'bool', 'description': 'Recording active'}

                        # Add user variables to recording (uv.* prefix) —
                        # only those with the "Record" checkbox enabled
                        # (var.log=True). Default is False so existing
                        # projects don't grow new CSV columns unexpectedly.
                        if self.user_variables:
                            for var in self.user_variables.get_all_variables():
                                if not getattr(var, 'log', False):
                                    continue
                                uv_name = f"uv.{var.name}"
                                values[uv_name] = var.value
                                channel_configs[uv_name] = {'units': var.units, 'description': var.description or var.variable_type}

                            # Add formula outputs to recording (fx.* prefix)
                            formula_values = self.user_variables.get_formula_values_dict()
                            for block_id, outputs in formula_values.items():
                                block = self.user_variables.formula_blocks.get(block_id)
                                for out_name, out_value in outputs.items():
                                    fx_name = f"fx.{out_name}"
                                    values[fx_name] = out_value
                                    # Get units from block outputs metadata if available
                                    units = ''
                                    if block and out_name in block.outputs:
                                        units = block.outputs[out_name].get('units', '')
                                    channel_configs[fx_name] = {'units': units, 'description': f'Formula: {out_name}'}

                        # Stage 2: skip scan-rate write_sample when chunk
                        # recording is active. _on_chunk fires per hw read
                        # and writes one row per hardware sample via
                        # RecordingManager.write_chunk, so write_sample here
                        # would duplicate rows with stale timestamps.
                        if not getattr(self, '_chunk_recording_active', False):
                            self.recording_manager.write_sample(values, channel_configs)

                    # Historian: silent 1 Hz write of ALL channels (unconditional)
                    if self.historian:
                        try:
                            # channel_configs may not be defined if recording is inactive
                            hist_units = {}
                            for name, ch in self.config.channels.items():
                                hist_units[name] = ch.units or ''
                            # Include units for script-published py.* channels too,
                            # otherwise DataViewer historical playback shows them
                            # without units even when the script declared them.
                            for pname, punits in self._published_units.items():
                                hist_units[pname] = punits
                            # Include units for user variables that opted into recording
                            if self.user_variables:
                                for var in self.user_variables.get_all_variables():
                                    if getattr(var, 'log', False):
                                        hist_units[f"uv.{var.name}"] = var.units or ''
                            self.historian.write_batch(int(time.time() * 1000), values, units=hist_units)
                        except Exception as hist_err:
                            self._historian_error_count += 1
                            if self._historian_error_count <= 5 or self._historian_error_count % 100 == 0:
                                logger.error(f"[PUBLISH] Historian write failed (#{self._historian_error_count}): {hist_err}")
                            if self._acq_events and self._historian_error_count <= 5:
                                self._acq_events.emit(AcquisitionEvent.HISTORIAN_ERROR, {
                                    'error': str(hist_err), 'total_errors': self._historian_error_count,
                                }, severity='warning')

                    # Note: Azure IoT Hub streaming is handled by external azure_uploader_service
                    # which subscribes to nisystem/nodes/+/channels/values topics directly

                    publish_count += 1

                except Exception as e:
                    import traceback
                    logger.error(f"Error in publish loop: {e}\n{traceback.format_exc()}")

            # Publish system status periodically (every ~1 second)
            # Skip during transitions to avoid publishing stale state
            status_publish_counter += 1
            if status_publish_counter >= self.config.system.publish_rate_hz:
                if self.acquisition_state not in ('initializing', 'stopping'):
                    self._publish_system_status()
                # Publish user variable values and formula block values (at 1 Hz, not full publish rate)
                if self.user_variables:
                    self._publish_user_variables_values()
                    self._publish_formula_blocks_values()
                # Drain log buffer and publish to MQTT (~every 1s)
                self._log_publish_counter += 1
                if self._log_publish_counter >= 2:
                    self._log_publish_counter = 0
                    self._drain_and_publish_logs()

                # Publish health status every ~5 seconds
                if self.acquiring and (time.time() - self._last_health_publish_time >= 5.0):
                    try:
                        self._publish_health()
                        self._last_health_publish_time = time.time()
                    except Exception:
                        pass

                # Check for cRIO config push timeouts (non-blocking)
                self._check_crio_push_timeouts()

                # Check session timeout (CDAQ mode only - cRIO handles its own timeout)
                if self.config.system.project_mode != ProjectMode.CRIO:
                    self._check_session_timeout()

                # Industrial-grade: Periodic hardware output verification
                # Refresh actual output states from hardware to detect drift/faults
                if self.hardware_reader and self.acquiring and not self.config.system.simulation_mode:
                    try:
                        refreshed = self.hardware_reader.refresh_output_states()
                        if refreshed:
                            # Update channel_values with verified hardware states
                            with self.values_lock:
                                for ch_name, actual_val in refreshed.items():
                                    self.channel_values[ch_name] = actual_val
                    except Exception as e:
                        logger.warning(f"Output state refresh failed: {e}")

                status_publish_counter = 0

            # Track loop timing
            elapsed = time.time() - start_time
            self.last_publish_dt_ms = elapsed * 1000

            # Sleep until next epoch-anchored target (prevents cumulative drift)
            sleep_time = max(0, next_publish_time - time.time())
            # If we fell behind by more than one interval, reset to prevent burst catch-up
            if time.time() - next_publish_time >= publish_interval:
                next_publish_time = time.time()
            time.sleep(sleep_time)

    def _log_value(self, channel_name: str, value: Any):
        """Log a value to file (rotates daily at midnight)"""
        today = datetime.now().strftime('%Y%m%d')

        # Rotate file at midnight
        if self.log_file is not None and getattr(self, '_log_file_date', '') != today:
            self.log_file.flush()
            self.log_file.close()
            self.log_file = None

        if self.log_file is None:
            log_dir = Path(self.config.system.log_directory)
            log_dir.mkdir(parents=True, exist_ok=True)

            log_path = log_dir / f"data_{today}.csv"
            file_exists = log_path.exists()

            self.log_file = open(log_path, 'a')
            self._log_file_date = today

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

        # Start non-blocking MQTT publish queue thread
        self._start_publish_queue_thread()

        # Start command processing thread (drains _command_queue from MQTT)
        self._command_thread = threading.Thread(
            target=self._command_processing_loop, daemon=True, name="command")
        self._command_thread.start()

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

        # Load system mode and restore station state if in station mode
        self._system_mode = self._load_system_mode()
        if self._system_mode == 'station':
            self._restore_station_state()
        if self.active_projects:
            logger.info(f"Restored {len(self.active_projects)} projects from station state")
            self._publish_station_status()

        self._apply_saved_security_settings()

        # Clear all state on startup - user will choose to load project or start fresh via UI
        self._clear_startup_state()

    def stop(self):
        """Stop the DAQ service gracefully"""
        logger.info("Initiating graceful shutdown...")

        # Signal shutdown to all threads
        self._shutdown_requested.set()
        self.running = False

        # Stop acquiring first to prevent new data
        self._state_machine.force_state(DAQState.STOPPED)

        # Teardown all station projects
        for pid, ctx in list(self.active_projects.items()):
            try:
                ctx.teardown()
            except Exception as e:
                logger.warning(f"Error tearing down project {pid}: {e}")

        # Clear channel claims before shutdown
        self._clear_channel_claims()

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

        # Signal Azure uploader to stop (via historian, before it's closed)
        if self._get_azure_config() and self.historian:
            logger.info("Signaling Azure uploader to stop...")
            self._sync_azure_config_to_historian(streaming=False)

        # Close historian database
        if self.historian:
            logger.info("Closing historian database...")
            self.historian.close()

        # Stop notification manager
        if self.notification_manager:
            logger.info("Stopping notification manager...")
            self.notification_manager.shutdown()

        # Save alarm manager state
        if self.alarm_manager:
            logger.info("Saving alarm manager state...")
            self.alarm_manager.save_all()

        # Remove log streaming handler
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)

        # Save safety manager state
        if self.safety_manager:
            logger.info("Saving safety manager state...")
            self.safety_manager.save_all()

        # Join threads with reasonable timeouts
        shutdown_timeout = 5.0  # seconds per thread
        for thread_name, thread in [
            ("command", self._command_thread),
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

    # Read node_id from config to create per-node instance lock
    # This allows multiple DAQ service instances on the same PC (different configs)
    # Default lock name stays "NISystemDAQService" for backward compatibility
    # Only use per-node lock when node_id is explicitly set in config
    import configparser as _cp
    _cfg = _cp.ConfigParser()
    _cfg.read(args.config)
    _node_id = _cfg.get('system', 'node_id', fallback=None)

    # Enforce single instance — per-node lock if node_id is set, else original lock name
    _lock_name = f"NISystemDAQService_{_node_id}" if _node_id else "NISystemDAQService"
    instance = SingleInstance(_lock_name)
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

    try:
        service = DAQService(args.config)
        service.run()
    except KeyboardInterrupt:
        logger.info("DAQ Service interrupted by user")
    except Exception:
        logger.critical("DAQ Service fatal error", exc_info=True)
        sys.exit(1)
    finally:
        instance.release()

if __name__ == "__main__":
    main()
