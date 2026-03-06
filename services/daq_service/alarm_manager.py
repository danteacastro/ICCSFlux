"""
Enhanced Alarm Manager for NISystem

Provides industrial-grade alarm management with:
- Severity levels (Critical, High, Medium, Low)
- Latching behavior (latch, auto-clear, timed-latch)
- Time-based triggers (on-delay, off-delay, rate-of-change)
- Deadband/hysteresis to prevent chatter
- Alarm states (Normal, Active, Acknowledged, Shelved)
- First-out indication
- Audit logging for compliance
- Alarm groups and cascading actions
"""

import gzip
import json
import math
import os
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable, Set
from enum import Enum

logger = logging.getLogger('AlarmManager')


class AlarmSeverity(Enum):
    """Alarm severity levels (ISA-18.2 style)"""
    CRITICAL = 1    # Immediate shutdown, requires manual reset
    HIGH = 2        # Auto-action, may require acknowledgment
    MEDIUM = 3      # Warning, logged, optional action
    LOW = 4         # Advisory, logged only


class AlarmState(Enum):
    """Alarm lifecycle states"""
    NORMAL = "normal"           # No alarm condition
    ACTIVE = "active"           # Alarm triggered, unacknowledged
    ACKNOWLEDGED = "acknowledged"  # Acknowledged but condition persists
    RETURNED = "returned"       # Condition cleared, unacknowledged (for latching)
    SHELVED = "shelved"         # Temporarily suppressed
    OUT_OF_SERVICE = "out_of_service"  # Disabled for maintenance


class LatchBehavior(Enum):
    """How alarm clears when condition returns to normal"""
    AUTO_CLEAR = "auto_clear"   # Clears immediately when condition clears
    LATCH = "latch"             # Stays active until manually reset
    TIMED_LATCH = "timed_latch" # Auto-clears after delay once condition clears


@dataclass
class AlarmConfig:
    """Configuration for a single alarm point"""
    id: str                         # Unique alarm ID
    channel: str                    # Channel to monitor
    name: str                       # Human-readable name
    description: str = ""
    enabled: bool = True

    # Severity
    severity: AlarmSeverity = AlarmSeverity.MEDIUM

    # Thresholds (use None to disable)
    high_high: Optional[float] = None   # Critical high
    high: Optional[float] = None        # High warning
    low: Optional[float] = None         # Low warning
    low_low: Optional[float] = None     # Critical low

    # Deadband prevents alarm chatter at threshold boundary
    # Alarm triggers at threshold, clears at (threshold - deadband) for high alarms
    deadband: float = 0.0

    # Time-based filtering
    on_delay_s: float = 0.0         # Must be in alarm for X seconds before triggering
    off_delay_s: float = 0.0        # Must be clear for X seconds before clearing

    # Rate-of-change alarm
    rate_limit: Optional[float] = None  # Max change per second
    rate_window_s: float = 1.0          # Time window for rate calculation

    # Behavior
    latch_behavior: LatchBehavior = LatchBehavior.AUTO_CLEAR
    timed_latch_s: float = 60.0     # For TIMED_LATCH: seconds after clear to auto-reset

    # Actions
    actions: List[str] = field(default_factory=list)  # Action IDs to execute

    # Grouping
    group: str = ""                 # Alarm group (e.g., "Zone1", "Coolant")
    priority: int = 0               # Priority within severity (for first-out)

    # Shelving
    max_shelve_time_s: float = 3600.0  # Max time alarm can be shelved (1 hour default)
    shelve_allowed: bool = True

    # Safety action (ISA-18.2) - action ID to execute when alarm triggers
    safety_action: Optional[str] = None

    # Digital input alarm configuration
    # For DI channels: alarm when state != expected_state (after invert)
    digital_alarm_enabled: bool = False
    digital_expected_state: bool = True   # Expected "safe" state (True=HIGH, False=LOW)
    digital_invert: bool = False          # Invert input before comparison (NC vs NO)
    digital_debounce_ms: float = 100.0    # Debounce time in ms

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'channel': self.channel,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'severity': self.severity.name,
            'high_high': self.high_high,
            'high': self.high,
            'low': self.low,
            'low_low': self.low_low,
            'deadband': self.deadband,
            'on_delay_s': self.on_delay_s,
            'off_delay_s': self.off_delay_s,
            'rate_limit': self.rate_limit,
            'rate_window_s': self.rate_window_s,
            'latch_behavior': self.latch_behavior.value,
            'timed_latch_s': self.timed_latch_s,
            'actions': self.actions,
            'group': self.group,
            'priority': self.priority,
            'max_shelve_time_s': self.max_shelve_time_s,
            'shelve_allowed': self.shelve_allowed,
            'safety_action': self.safety_action,
            'digital_alarm_enabled': self.digital_alarm_enabled,
            'digital_expected_state': self.digital_expected_state,
            'digital_invert': self.digital_invert,
            'digital_debounce_ms': self.digital_debounce_ms
        }

    @staticmethod
    def from_dict(d: dict) -> 'AlarmConfig':
        """Create from dictionary"""
        return AlarmConfig(
            id=d.get('id', ''),
            channel=d.get('channel', ''),
            name=d.get('name', ''),
            description=d.get('description', ''),
            enabled=d.get('enabled', True),
            severity=AlarmSeverity[d.get('severity', 'MEDIUM')],
            high_high=d.get('high_high'),
            high=d.get('high'),
            low=d.get('low'),
            low_low=d.get('low_low'),
            deadband=d.get('deadband', 0.0),
            on_delay_s=d.get('on_delay_s', 0.0),
            off_delay_s=d.get('off_delay_s', 0.0),
            rate_limit=d.get('rate_limit'),
            rate_window_s=d.get('rate_window_s', 1.0),
            latch_behavior=LatchBehavior(d.get('latch_behavior', 'auto_clear')),
            timed_latch_s=d.get('timed_latch_s', 60.0),
            actions=d.get('actions', []),
            group=d.get('group', ''),
            priority=d.get('priority', 0),
            max_shelve_time_s=d.get('max_shelve_time_s', 3600.0),
            shelve_allowed=d.get('shelve_allowed', True),
            safety_action=d.get('safety_action'),
            digital_alarm_enabled=d.get('digital_alarm_enabled', False),
            digital_expected_state=d.get('digital_expected_state', True),
            digital_invert=d.get('digital_invert', False),
            digital_debounce_ms=d.get('digital_debounce_ms', 100.0)
        )


@dataclass
class ActiveAlarm:
    """Runtime state of an active alarm"""
    alarm_id: str               # Reference to AlarmConfig.id
    channel: str
    name: str
    severity: AlarmSeverity
    state: AlarmState
    threshold_type: str         # 'high_high', 'high', 'low', 'low_low', 'rate'
    threshold_value: float
    triggered_value: float      # Value that triggered the alarm
    current_value: float        # Current value

    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    cleared_at: Optional[datetime] = None

    # First-out tracking
    sequence_number: int = 0    # Global sequence for first-out
    is_first_out: bool = False  # First alarm in a cascade

    # Shelving
    shelved_at: Optional[datetime] = None
    shelved_by: Optional[str] = None
    shelve_expires_at: Optional[datetime] = None
    shelve_reason: str = ""

    message: str = ""

    # Safety action to execute (from AlarmConfig)
    safety_action: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MQTT/JSON"""
        return {
            'alarm_id': self.alarm_id,
            'channel': self.channel,
            'name': self.name,
            'severity': self.severity.name,
            'state': self.state.value,
            'threshold_type': self.threshold_type,
            'threshold_value': self.threshold_value,
            'triggered_value': self.triggered_value,
            'current_value': self.current_value,
            'triggered_at': self.triggered_at.isoformat(),
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'acknowledged_by': self.acknowledged_by,
            'cleared_at': self.cleared_at.isoformat() if self.cleared_at else None,
            'sequence_number': self.sequence_number,
            'is_first_out': self.is_first_out,
            'shelved_at': self.shelved_at.isoformat() if self.shelved_at else None,
            'shelved_by': self.shelved_by,
            'shelve_expires_at': self.shelve_expires_at.isoformat() if self.shelve_expires_at else None,
            'shelve_reason': self.shelve_reason,
            'message': self.message,
            'duration_seconds': (datetime.now() - self.triggered_at).total_seconds(),
            'safety_action': self.safety_action
        }


@dataclass
class AlarmHistoryEntry:
    """Audit log entry for alarm events"""
    timestamp: datetime
    alarm_id: str
    channel: str
    event_type: str             # 'triggered', 'acknowledged', 'cleared', 'reset', 'shelved', 'unshelved'
    severity: AlarmSeverity
    value: Optional[float]
    threshold: Optional[float]
    user: Optional[str]
    message: str
    duration_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'alarm_id': self.alarm_id,
            'channel': self.channel,
            'event_type': self.event_type,
            'severity': self.severity.name,
            'value': self.value,
            'threshold': self.threshold,
            'user': self.user,
            'message': self.message,
            'duration_seconds': self.duration_seconds
        }


# ============================================================================
# Event Correlation Types (for SOE and multi-alarm analysis)
# ============================================================================

@dataclass
class CorrelationRule:
    """
    Defines how alarms should be correlated/grouped.

    When trigger_alarm fires, look for related_alarms within time_window_ms.
    If found, group them together with root_cause_hint indicating likely root cause.
    """
    id: str
    name: str
    trigger_alarm: str           # Primary alarm ID that starts correlation
    related_alarms: List[str]    # Alarm IDs to group when triggered together
    time_window_ms: int = 1000   # Window for grouping (default 1s)
    root_cause_hint: str = ""    # Which alarm is likely root cause (alarm ID or empty)
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'trigger_alarm': self.trigger_alarm,
            'related_alarms': self.related_alarms,
            'time_window_ms': self.time_window_ms,
            'root_cause_hint': self.root_cause_hint,
            'enabled': self.enabled,
            'description': self.description
        }

    @staticmethod
    def from_dict(d: dict) -> 'CorrelationRule':
        return CorrelationRule(
            id=d.get('id', ''),
            name=d.get('name', ''),
            trigger_alarm=d.get('trigger_alarm', ''),
            related_alarms=d.get('related_alarms', []),
            time_window_ms=d.get('time_window_ms', 1000),
            root_cause_hint=d.get('root_cause_hint', ''),
            enabled=d.get('enabled', True),
            description=d.get('description', '')
        )


@dataclass
class EventCorrelation:
    """
    Represents a group of correlated alarms that triggered together.
    Used for root cause analysis and reducing alarm flooding.
    """
    correlation_id: str          # UUID for this correlation group
    trigger_alarm_id: str        # The alarm that triggered the correlation
    related_alarm_ids: List[str] # Other alarms in this correlation
    timestamp: datetime          # When correlation was detected
    root_cause_alarm_id: str     # Which alarm is identified as root cause
    correlation_rule_id: str     # Which rule detected this correlation
    node_id: str = ""            # Source node (for multi-node systems)

    def to_dict(self) -> dict:
        return {
            'correlation_id': self.correlation_id,
            'trigger_alarm_id': self.trigger_alarm_id,
            'related_alarm_ids': self.related_alarm_ids,
            'timestamp': self.timestamp.isoformat(),
            'root_cause_alarm_id': self.root_cause_alarm_id,
            'correlation_rule_id': self.correlation_rule_id,
            'node_id': self.node_id
        }


@dataclass
class SOEEvent:
    """
    Sequence of Events entry with microsecond precision.
    Used for forensic analysis of alarm cascades.
    """
    event_id: str                # UUID
    timestamp_us: int            # Microseconds since epoch (for ordering)
    timestamp_iso: str           # ISO string for display
    event_type: str              # 'alarm_triggered', 'alarm_cleared', 'state_change', 'digital_edge'
    source_channel: str
    value: Any                   # Current value
    previous_value: Any          # Previous value (for edges/changes)
    severity: Optional[str] = None
    message: str = ""
    node_id: str = ""
    alarm_id: Optional[str] = None
    correlation_id: Optional[str] = None  # Link to correlation group

    def to_dict(self) -> dict:
        return {
            'event_id': self.event_id,
            'timestamp_us': self.timestamp_us,
            'timestamp_iso': self.timestamp_iso,
            'event_type': self.event_type,
            'source_channel': self.source_channel,
            'value': self.value,
            'previous_value': self.previous_value,
            'severity': self.severity,
            'message': self.message,
            'node_id': self.node_id,
            'alarm_id': self.alarm_id,
            'correlation_id': self.correlation_id
        }


class AlarmManager:
    """
    Central alarm management engine

    Handles:
    - Alarm evaluation against thresholds
    - State machine for alarm lifecycle
    - Delay timers (on-delay, off-delay)
    - Rate-of-change detection
    - First-out determination
    - Audit logging
    - Persistence
    """

    def __init__(self, data_dir: Path, publish_callback: Optional[Callable] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.publish_callback = publish_callback

        # Thread safety
        self.lock = threading.RLock()

        # Configuration
        self.alarm_configs: Dict[str, AlarmConfig] = {}

        # Active alarms by alarm_id
        self.active_alarms: Dict[str, ActiveAlarm] = {}

        # Delay tracking
        self.on_delay_timers: Dict[str, float] = {}   # alarm_id -> start_time
        self.off_delay_timers: Dict[str, float] = {}  # alarm_id -> start_time
        self.timed_latch_timers: Dict[str, float] = {} # alarm_id -> clear_time

        # Rate of change tracking
        self.value_history: Dict[str, List[tuple]] = {}  # channel -> [(time, value), ...]

        # Digital input debounce tracking
        self.digital_debounce_timers: Dict[str, float] = {}  # alarm_id -> state_change_time
        self.digital_last_states: Dict[str, bool] = {}       # alarm_id -> last_debounced_state

        # First-out tracking
        self.alarm_sequence = 0
        self.first_out_alarm_id: Optional[str] = None
        self.cascade_start_time: Optional[float] = None
        self.CASCADE_WINDOW_S = 5.0  # Alarms within 5s are part of same cascade

        # History for audit log
        self.history: List[AlarmHistoryEntry] = []
        self.max_history = 10000

        # Stats
        self.stats = {
            'total_alarms': 0,
            'total_acknowledged': 0,
            'total_cleared': 0,
            'total_shelved': 0
        }

        # Alarm flood detection (ISA-18.2) — configurable per project
        self.FLOOD_THRESHOLD = 10       # Alarms within window to trigger flood
        self.FLOOD_WINDOW_S = 60.0      # Time window for flood detection (seconds)
        self._flood_active = False
        self._flood_start_time: Optional[float] = None
        self._flood_alarm_times: List[float] = []   # timestamps of recent alarm triggers
        self._flood_suppressed_count = 0
        self._flood_root_cause_id: Optional[str] = None  # First alarm in the flood

        # Event Correlation
        self.correlation_rules: Dict[str, CorrelationRule] = {}
        self.active_correlations: Dict[str, EventCorrelation] = {}
        self.recent_alarms: List[tuple] = []  # [(timestamp_us, alarm_id), ...] for correlation window
        self.max_recent_alarms = 100

        # SOE (Sequence of Events) buffer
        self.soe_buffer: List[SOEEvent] = []
        self.max_soe_events = 10000
        self.node_id = ""  # Set by DAQ service

        # Append-only JSONL event log (survives restarts, no truncation)
        self._log_dir = self.data_dir / 'logs' / 'alarms'
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file: Optional[Path] = None
        self._max_log_size_mb = 50.0
        self._init_log_file()

        # Load saved state
        self._load_configs()
        self._load_active_alarms()
        self._load_history()
        self._load_correlation_rules()

    def configure_flood(self, threshold: int = 10, window_s: float = 60.0):
        """Update alarm flood detection parameters at runtime (ISA-18.2).

        Args:
            threshold: Number of alarms within window to trigger flood (min 2, max 100)
            window_s: Time window in seconds for flood detection (min 10, max 600)
        """
        with self.lock:
            self.FLOOD_THRESHOLD = max(2, min(100, int(threshold)))
            self.FLOOD_WINDOW_S = max(10.0, min(600.0, float(window_s)))
            logger.info(f"Flood detection updated: threshold={self.FLOOD_THRESHOLD}, window={self.FLOOD_WINDOW_S}s")

    def add_alarm_config(self, config: AlarmConfig):
        """Add or update an alarm configuration"""
        with self.lock:
            self.alarm_configs[config.id] = config
            self._save_configs()
            logger.info(f"Added/updated alarm config: {config.id}")

    def remove_alarm_config(self, alarm_id: str):
        """Remove an alarm configuration"""
        with self.lock:
            if alarm_id in self.alarm_configs:
                del self.alarm_configs[alarm_id]
                # Also clear any active alarm
                if alarm_id in self.active_alarms:
                    del self.active_alarms[alarm_id]
                self._save_configs()
                logger.info(f"Removed alarm config: {alarm_id}")

    def get_alarm_config(self, alarm_id: str) -> Optional[AlarmConfig]:
        """Get alarm configuration by ID"""
        return self.alarm_configs.get(alarm_id)

    def get_configs_for_channel(self, channel: str) -> List[AlarmConfig]:
        """Get all alarm configs for a channel"""
        return [c for c in self.alarm_configs.values() if c.channel == channel]

    def process_value(self, channel: str, value: float, timestamp: Optional[float] = None):
        """
        Process a new value for alarm checking
        Called from the scan loop for each channel
        """
        if timestamp is None:
            timestamp = time.monotonic()

        with self.lock:
            # Update rate-of-change history
            self._update_rate_history(channel, value, timestamp)

            # Check all alarms for this channel
            for config in self.get_configs_for_channel(channel):
                if not config.enabled:
                    continue

                self._evaluate_alarm(config, value, timestamp)

            # Check timed latch expiry
            self._check_timed_latches(timestamp)

            # Check shelve expiry
            self._check_shelve_expiry()

            # Check if alarm flood has ended
            self._check_flood_clear(timestamp)

    def _update_rate_history(self, channel: str, value: float, timestamp: float):
        """Track value history for rate-of-change detection"""
        if channel not in self.value_history:
            self.value_history[channel] = []

        history = self.value_history[channel]
        history.append((timestamp, value))

        # Keep only last 60 seconds of history
        cutoff = timestamp - 60.0
        self.value_history[channel] = [(t, v) for t, v in history if t >= cutoff]

    def _get_rate_of_change(self, channel: str, window_s: float) -> Optional[float]:
        """Calculate rate of change over the specified window"""
        history = self.value_history.get(channel, [])
        if len(history) < 2:
            return None

        now = time.monotonic()
        cutoff = now - window_s

        # Get points within window
        points = [(t, v) for t, v in history if t >= cutoff]
        if len(points) < 2:
            return None

        # Calculate rate (change per second)
        first_t, first_v = points[0]
        last_t, last_v = points[-1]

        dt = last_t - first_t
        if dt < 0.001:  # Avoid division by zero
            return None

        return (last_v - first_v) / dt

    def _evaluate_alarm(self, config: AlarmConfig, value: float, timestamp: float):
        """Evaluate alarm conditions and manage state"""
        alarm_id = config.id
        current_alarm = self.active_alarms.get(alarm_id)

        # NaN from hardware (open TC, broken sensor) — force alarm active
        if isinstance(value, float) and math.isnan(value):
            self._handle_alarm_condition(config, 0.0, timestamp, 'comm_fail', 0.0)
            return

        # Check for digital input alarm first
        if config.digital_alarm_enabled:
            condition_met, threshold_type, threshold_value = self._check_digital_alarm(
                config, value, timestamp
            )
        else:
            # Check analog thresholds
            condition_met, threshold_type, threshold_value = self._check_thresholds(config, value)

            # Also check rate-of-change for analog
            if not condition_met and config.rate_limit is not None:
                rate = self._get_rate_of_change(config.channel, config.rate_window_s)
                if rate is not None and abs(rate) > config.rate_limit:
                    condition_met = True
                    threshold_type = 'rate'
                    threshold_value = config.rate_limit

        if condition_met:
            # Alarm condition is active
            self._handle_alarm_condition(config, value, timestamp, threshold_type, threshold_value)
        else:
            # Alarm condition is clear
            self._handle_clear_condition(config, value, timestamp)

    def _check_digital_alarm(self, config: AlarmConfig, value: float, timestamp: float) -> tuple:
        """
        Check digital input alarm with debounce and invert logic.

        Logic:
        1. Convert value to boolean (0 = False, non-zero = True)
        2. Apply invert if configured (for NC sensors)
        3. Compare to expected_state
        4. Apply debounce to prevent chatter
        5. Alarm triggers when state != expected_state (after debounce)
        """
        alarm_id = config.id

        # Convert value to boolean
        raw_state = value != 0

        # Apply invert (for normally-closed sensors)
        actual_state = not raw_state if config.digital_invert else raw_state

        # Get last debounced state
        last_state = self.digital_last_states.get(alarm_id)

        # Check if state changed
        if last_state is None:
            # First reading - initialize
            self.digital_last_states[alarm_id] = actual_state
            self.digital_debounce_timers.pop(alarm_id, None)
            last_state = actual_state
        elif actual_state != last_state:
            # State changed - check debounce
            debounce_start = self.digital_debounce_timers.get(alarm_id)
            if debounce_start is None:
                # Start debounce timer
                self.digital_debounce_timers[alarm_id] = timestamp
                # Keep using last state until debounce complete
                actual_state = last_state
            else:
                # Check if debounce complete
                elapsed_ms = (timestamp - debounce_start) * 1000
                if elapsed_ms >= config.digital_debounce_ms:
                    # Debounce complete - accept new state
                    self.digital_last_states[alarm_id] = actual_state
                    self.digital_debounce_timers.pop(alarm_id, None)
                else:
                    # Still in debounce - keep using last state
                    actual_state = last_state
        else:
            # State unchanged - clear any debounce timer
            self.digital_debounce_timers.pop(alarm_id, None)

        # Alarm condition: actual state != expected state
        expected = config.digital_expected_state
        condition_met = actual_state != expected

        if condition_met:
            # Use the actual state as the threshold value for display
            return True, 'digital_state', 1.0 if expected else 0.0
        else:
            return False, None, None

    def _check_thresholds(self, config: AlarmConfig, value: float) -> tuple:
        """Check if value exceeds any threshold"""
        # Check from most severe to least severe
        if config.high_high is not None and value >= config.high_high:
            return True, 'high_high', config.high_high
        if config.low_low is not None and value <= config.low_low:
            return True, 'low_low', config.low_low
        if config.high is not None and value >= config.high:
            return True, 'high', config.high
        if config.low is not None and value <= config.low:
            return True, 'low', config.low

        return False, None, None

    def _should_clear_threshold(self, config: AlarmConfig, value: float, threshold_type: str, threshold_value: float) -> bool:
        """Check if value has returned to normal (with deadband)"""
        deadband = config.deadband

        if threshold_type in ('high_high', 'high'):
            return value < (threshold_value - deadband)
        elif threshold_type in ('low_low', 'low'):
            return value > (threshold_value + deadband)
        elif threshold_type == 'rate':
            rate = self._get_rate_of_change(config.channel, config.rate_window_s)
            return rate is None or abs(rate) <= config.rate_limit * 0.8  # 20% hysteresis
        elif threshold_type == 'digital_state':
            # For digital alarms, check if current state matches expected
            raw_state = value != 0
            actual_state = not raw_state if config.digital_invert else raw_state
            return actual_state == config.digital_expected_state

        return True

    def _handle_alarm_condition(self, config: AlarmConfig, value: float, timestamp: float,
                                 threshold_type: str, threshold_value: float):
        """Handle when alarm condition is active"""
        alarm_id = config.id
        current = self.active_alarms.get(alarm_id)

        # Clear any off-delay timer
        self.off_delay_timers.pop(alarm_id, None)
        self.timed_latch_timers.pop(alarm_id, None)

        if current is None:
            # New alarm condition
            if config.on_delay_s > 0:
                # Start on-delay timer
                if alarm_id not in self.on_delay_timers:
                    self.on_delay_timers[alarm_id] = timestamp
                    return

                # Check if on-delay has elapsed
                elapsed = timestamp - self.on_delay_timers[alarm_id]
                if elapsed < config.on_delay_s:
                    return

            # Trigger alarm
            self._trigger_alarm(config, value, threshold_type, threshold_value)
            self.on_delay_timers.pop(alarm_id, None)

        elif current.state == AlarmState.SHELVED:
            # Update current value but don't change state
            current.current_value = value

        else:
            # Update current value
            current.current_value = value

            # If was RETURNED (latched, condition cleared then came back), go back to ACKNOWLEDGED or ACTIVE
            if current.state == AlarmState.RETURNED:
                if current.acknowledged_at:
                    current.state = AlarmState.ACKNOWLEDGED
                else:
                    current.state = AlarmState.ACTIVE

    def _handle_clear_condition(self, config: AlarmConfig, value: float, timestamp: float):
        """Handle when alarm condition has cleared"""
        alarm_id = config.id
        current = self.active_alarms.get(alarm_id)

        # Clear on-delay timer if condition cleared before timer expired
        self.on_delay_timers.pop(alarm_id, None)

        if current is None:
            return  # No active alarm

        if current.state == AlarmState.SHELVED:
            current.current_value = value
            return  # Shelved alarms don't clear

        # Check if value has returned past deadband
        if not self._should_clear_threshold(config, value, current.threshold_type, current.threshold_value):
            return  # Still within deadband

        # Handle based on latch behavior
        if config.latch_behavior == LatchBehavior.AUTO_CLEAR:
            self._handle_auto_clear(config, current, value, timestamp)

        elif config.latch_behavior == LatchBehavior.LATCH:
            # Move to RETURNED state if not already acknowledged
            if current.state == AlarmState.ACTIVE:
                current.state = AlarmState.RETURNED
            current.current_value = value
            current.cleared_at = datetime.now()

        elif config.latch_behavior == LatchBehavior.TIMED_LATCH:
            if current.state == AlarmState.ACTIVE:
                current.state = AlarmState.RETURNED
                current.cleared_at = datetime.now()

            # Start timed latch timer
            if alarm_id not in self.timed_latch_timers:
                self.timed_latch_timers[alarm_id] = timestamp
            current.current_value = value

    def _handle_auto_clear(self, config: AlarmConfig, current: ActiveAlarm, value: float, timestamp: float):
        """Handle auto-clear with off-delay"""
        alarm_id = config.id

        if config.off_delay_s > 0:
            # Start off-delay timer
            if alarm_id not in self.off_delay_timers:
                self.off_delay_timers[alarm_id] = timestamp

            # Check if off-delay has elapsed
            elapsed = timestamp - self.off_delay_timers[alarm_id]
            if elapsed < config.off_delay_s:
                current.current_value = value
                return

        # Clear the alarm
        self._clear_alarm(alarm_id, "Auto-cleared")
        self.off_delay_timers.pop(alarm_id, None)

    def _check_timed_latches(self, timestamp: float):
        """Check if any timed latches have expired"""
        expired = []
        for alarm_id, clear_time in self.timed_latch_timers.items():
            config = self.alarm_configs.get(alarm_id)
            if config is None:
                expired.append(alarm_id)
                continue

            elapsed = timestamp - clear_time
            if elapsed >= config.timed_latch_s:
                expired.append(alarm_id)

        for alarm_id in expired:
            self._clear_alarm(alarm_id, "Timed latch expired")
            self.timed_latch_timers.pop(alarm_id, None)

    def _check_shelve_expiry(self):
        """Check if any shelved alarms have expired"""
        now = datetime.now()
        for alarm_id, alarm in list(self.active_alarms.items()):
            if alarm.state == AlarmState.SHELVED and alarm.shelve_expires_at:
                if now >= alarm.shelve_expires_at:
                    self.unshelve_alarm(alarm_id, "System", "Shelve time expired")

    def _check_flood_clear(self, timestamp: float):
        """Check if alarm flood condition has ended"""
        if not self._flood_active:
            return

        # Prune old timestamps
        cutoff = timestamp - self.FLOOD_WINDOW_S
        self._flood_alarm_times = [t for t in self._flood_alarm_times if t >= cutoff]

        # Flood clears when alarm rate drops below half the threshold
        if len(self._flood_alarm_times) < self.FLOOD_THRESHOLD // 2:
            duration = timestamp - self._flood_start_time if self._flood_start_time else 0
            logger.info(
                f"ALARM FLOOD CLEARED: lasted {duration:.1f}s, "
                f"suppressed {self._flood_suppressed_count} alarms"
            )
            self._log_flood_event('flood_end', {
                'duration_s': round(duration, 1),
                'suppressed_count': self._flood_suppressed_count,
                'root_cause': self._flood_root_cause_id
            })
            if self.publish_callback:
                self.publish_callback('alarm_flood', {
                    'active': False,
                    'duration_s': round(duration, 1),
                    'suppressed_count': self._flood_suppressed_count,
                    'root_cause': self._flood_root_cause_id,
                    'timestamp': datetime.now().isoformat()
                })

            self._flood_active = False
            self._flood_start_time = None
            self._flood_suppressed_count = 0
            self._flood_root_cause_id = None

    def _log_flood_event(self, event_type: str, details: Dict[str, Any]):
        """Log a flood event to alarm history"""
        entry = AlarmHistoryEntry(
            timestamp=datetime.now(),
            alarm_id='__flood__',
            channel='',
            event_type=event_type,
            severity=AlarmSeverity.CRITICAL,
            value=None,
            threshold=None,
            user=None,
            message=f"Alarm flood {event_type.replace('flood_', '')}: {json.dumps(details)}"
        )
        self.history.append(entry)
        self._append_to_log(entry)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def get_flood_status(self) -> Dict[str, Any]:
        """Get current alarm flood status"""
        with self.lock:
            # Prune for current count
            if self._flood_alarm_times:
                cutoff = time.monotonic() - self.FLOOD_WINDOW_S
                current_count = sum(1 for t in self._flood_alarm_times if t >= cutoff)
            else:
                current_count = 0

            return {
                'active': self._flood_active,
                'alarm_rate': current_count,
                'threshold': self.FLOOD_THRESHOLD,
                'window_s': self.FLOOD_WINDOW_S,
                'suppressed_count': self._flood_suppressed_count,
                'root_cause': self._flood_root_cause_id,
                'duration_s': round(time.monotonic() - self._flood_start_time, 1) if self._flood_start_time else 0
            }

    def _trigger_alarm(self, config: AlarmConfig, value: float, threshold_type: str, threshold_value: float):
        """Create a new active alarm"""
        now = datetime.now()
        mono_now = time.monotonic()

        # --- Alarm flood detection (ISA-18.2) ---
        self._flood_alarm_times.append(mono_now)
        # Prune timestamps outside the window (cap at 10000 to prevent unbounded growth)
        cutoff = mono_now - self.FLOOD_WINDOW_S
        self._flood_alarm_times = [t for t in self._flood_alarm_times if t >= cutoff]
        if len(self._flood_alarm_times) > 10000:
            self._flood_alarm_times = self._flood_alarm_times[-10000:]

        if not self._flood_active:
            if len(self._flood_alarm_times) >= self.FLOOD_THRESHOLD:
                # Flood detected
                self._flood_active = True
                self._flood_start_time = mono_now
                self._flood_suppressed_count = 0
                self._flood_root_cause_id = self.first_out_alarm_id or config.id
                logger.critical(
                    f"ALARM FLOOD DETECTED: {len(self._flood_alarm_times)} alarms "
                    f"in {self.FLOOD_WINDOW_S}s (threshold: {self.FLOOD_THRESHOLD}). "
                    f"Root cause: {self._flood_root_cause_id}"
                )
                self._log_flood_event('flood_start', {
                    'alarm_count': len(self._flood_alarm_times),
                    'root_cause': self._flood_root_cause_id,
                    'threshold': self.FLOOD_THRESHOLD,
                    'window_s': self.FLOOD_WINDOW_S
                })
                if self.publish_callback:
                    self.publish_callback('alarm_flood', {
                        'active': True,
                        'alarm_count': len(self._flood_alarm_times),
                        'root_cause': self._flood_root_cause_id,
                        'timestamp': now.isoformat()
                    })

        if self._flood_active:
            # During a flood, suppress non-critical alarms
            if config.severity not in (AlarmSeverity.CRITICAL, AlarmSeverity.HIGH):
                self._flood_suppressed_count += 1
                logger.info(
                    f"ALARM SUPPRESSED (flood): {config.name} "
                    f"(severity={config.severity.name}, suppressed={self._flood_suppressed_count})"
                )
                self.stats['total_alarms'] += 1
                return  # Do not create ActiveAlarm for suppressed alarms

        # Determine first-out
        is_first_out = False
        if self.first_out_alarm_id is None or \
           (self.cascade_start_time and time.monotonic() - self.cascade_start_time > self.CASCADE_WINDOW_S):
            # New cascade
            self.alarm_sequence += 1
            self.first_out_alarm_id = config.id
            self.cascade_start_time = time.monotonic()
            is_first_out = True

        self.alarm_sequence += 1

        # Create message based on alarm type
        if threshold_type == 'digital_state':
            # Digital input alarm message
            raw_state = value != 0
            actual_state = not raw_state if config.digital_invert else raw_state
            state_str = "HIGH" if actual_state else "LOW"
            expected_str = "HIGH" if config.digital_expected_state else "LOW"
            message = f"{config.name} is {state_str} (expected {expected_str})"
        else:
            # Analog threshold alarm message
            direction = "exceeded" if threshold_type.startswith('high') else "fell below"
            message = f"{config.name} {direction} {threshold_type.replace('_', ' ')} limit: {value:.2f} (limit: {threshold_value})"

        alarm = ActiveAlarm(
            alarm_id=config.id,
            channel=config.channel,
            name=config.name,
            severity=config.severity,
            state=AlarmState.ACTIVE,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
            triggered_value=value,
            current_value=value,
            triggered_at=now,
            sequence_number=self.alarm_sequence,
            is_first_out=is_first_out,
            message=message,
            safety_action=config.safety_action  # Include safety action from config
        )

        self.active_alarms[config.id] = alarm
        self.stats['total_alarms'] += 1

        # Log to history
        self._log_event(alarm, 'triggered', value, threshold_value, None)

        # Publish to MQTT
        self._publish_alarm(alarm)

        # Execute actions
        self._execute_actions(config.actions, alarm)

        # Execute safety action if configured (ISA-18.2 automatic response)
        if config.safety_action:
            self._execute_safety_action(config.safety_action, alarm)

        logger.warning(f"ALARM TRIGGERED: {message}")

    def _clear_alarm(self, alarm_id: str, reason: str = "Cleared"):
        """Clear an active alarm"""
        alarm = self.active_alarms.get(alarm_id)
        if alarm is None:
            return

        duration = (datetime.now() - alarm.triggered_at).total_seconds()

        # Log to history
        self._log_event(alarm, 'cleared', alarm.current_value, alarm.threshold_value, None, duration)

        # Remove from active
        del self.active_alarms[alarm_id]
        self.stats['total_cleared'] += 1

        # Check if this was the first-out alarm
        if alarm_id == self.first_out_alarm_id:
            self.first_out_alarm_id = None
            self.cascade_start_time = None

        # Publish cleared state
        self._publish_alarm_cleared(alarm_id)

        logger.info(f"ALARM CLEARED: {alarm.name} - {reason} (duration: {duration:.1f}s)")

    def acknowledge_alarm(self, alarm_id: str, user: str = "Unknown"):
        """Acknowledge an alarm"""
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm is None:
                logger.warning(f"Cannot acknowledge alarm {alarm_id}: not found")
                return False

            if alarm.state not in (AlarmState.ACTIVE, AlarmState.RETURNED):
                logger.warning(f"Cannot acknowledge alarm {alarm_id}: invalid state {alarm.state}")
                return False

            alarm.state = AlarmState.ACKNOWLEDGED
            alarm.acknowledged_at = datetime.now()
            alarm.acknowledged_by = user
            self.stats['total_acknowledged'] += 1

            # Log
            self._log_event(alarm, 'acknowledged', alarm.current_value, alarm.threshold_value, user)

            # Publish update
            self._publish_alarm(alarm)

            logger.info(f"ALARM ACKNOWLEDGED: {alarm.name} by {user}")
            return True

    def acknowledge_all(self, user: str = "Unknown", severity: Optional[AlarmSeverity] = None):
        """Acknowledge all active alarms, optionally filtered by severity"""
        with self.lock:
            acknowledged = 0
            for alarm_id, alarm in list(self.active_alarms.items()):
                if alarm.state in (AlarmState.ACTIVE, AlarmState.RETURNED):
                    if severity is None or alarm.severity == severity:
                        self.acknowledge_alarm(alarm_id, user)
                        acknowledged += 1

            logger.info(f"Acknowledged {acknowledged} alarms")
            return acknowledged

    def reset_alarm(self, alarm_id: str, user: str = "Unknown"):
        """Reset (force clear) a latched alarm"""
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm is None:
                logger.warning(f"Cannot reset alarm {alarm_id}: not found")
                return False

            config = self.alarm_configs.get(alarm_id)
            if config and config.latch_behavior == LatchBehavior.AUTO_CLEAR:
                logger.warning(f"Cannot reset non-latching alarm {alarm_id}")
                return False

            # Log as reset
            self._log_event(alarm, 'reset', alarm.current_value, alarm.threshold_value, user,
                           (datetime.now() - alarm.triggered_at).total_seconds())

            self._clear_alarm(alarm_id, f"Reset by {user}")
            logger.info(f"ALARM RESET: {alarm.name} by {user}")
            return True

    def reset_all_latched(self, user: str = "Unknown"):
        """Reset all latched alarms"""
        with self.lock:
            reset_count = 0
            for alarm_id in list(self.active_alarms.keys()):
                config = self.alarm_configs.get(alarm_id)
                if config and config.latch_behavior != LatchBehavior.AUTO_CLEAR:
                    if self.reset_alarm(alarm_id, user):
                        reset_count += 1

            logger.info(f"Reset {reset_count} latched alarms")
            return reset_count

    def shelve_alarm(self, alarm_id: str, user: str, reason: str = "", duration_s: float = 3600.0):
        """Shelve (temporarily suppress) an alarm"""
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm is None:
                return False

            config = self.alarm_configs.get(alarm_id)
            if config and not config.shelve_allowed:
                logger.warning(f"Shelving not allowed for alarm {alarm_id}")
                return False

            # Limit duration
            max_duration = config.max_shelve_time_s if config else 3600.0
            duration_s = min(duration_s, max_duration)

            alarm.state = AlarmState.SHELVED
            alarm.shelved_at = datetime.now()
            alarm.shelved_by = user
            alarm.shelve_expires_at = datetime.now() + timedelta(seconds=duration_s)
            alarm.shelve_reason = reason
            self.stats['total_shelved'] += 1

            # Log
            self._log_event(alarm, 'shelved', alarm.current_value, alarm.threshold_value, user)

            # Publish update
            self._publish_alarm(alarm)

            logger.info(f"ALARM SHELVED: {alarm.name} by {user} for {duration_s}s: {reason}")
            return True

    def unshelve_alarm(self, alarm_id: str, user: str, reason: str = ""):
        """Unshelve an alarm — re-evaluate current value to get correct state"""
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm is None or alarm.state != AlarmState.SHELVED:
                return False

            alarm.shelved_at = None
            alarm.shelved_by = None
            alarm.shelve_expires_at = None
            alarm.shelve_reason = ""

            # Re-evaluate alarm condition against current value instead of
            # blindly restoring old state (value may have changed while shelved)
            config = self.alarm_configs.get(alarm_id)
            condition_met = False
            if config and alarm.current_value is not None:
                if config.digital_alarm_enabled:
                    condition_met, _, _ = self._check_digital_alarm(config, alarm.current_value, time.time())
                else:
                    condition_met, _, _ = self._check_thresholds(config, alarm.current_value)

            if condition_met:
                # Condition still active — restore to appropriate active state
                if alarm.acknowledged_at:
                    alarm.state = AlarmState.ACKNOWLEDGED
                else:
                    alarm.state = AlarmState.ACTIVE
            else:
                # Condition cleared while shelved — remove the alarm
                self._log_event(alarm, 'unshelved', alarm.current_value, alarm.threshold_value, user)
                self._log_event(alarm, 'cleared_after_unshelve', alarm.current_value, alarm.threshold_value, user)
                del self.active_alarms[alarm_id]
                self._publish_alarm_cleared(alarm_id)
                logger.info(f"ALARM UNSHELVED+CLEARED: {alarm.name} by {user} — condition no longer active")
                return True

            # Log
            self._log_event(alarm, 'unshelved', alarm.current_value, alarm.threshold_value, user)

            # Publish update
            self._publish_alarm(alarm)

            logger.info(f"ALARM UNSHELVED: {alarm.name} by {user}: {reason}")
            return True

    def disable_alarm(self, alarm_id: str, user: str):
        """Put alarm out of service"""
        with self.lock:
            config = self.alarm_configs.get(alarm_id)
            if config:
                config.enabled = False
                self._save_configs()

            alarm = self.active_alarms.get(alarm_id)
            if alarm:
                alarm.state = AlarmState.OUT_OF_SERVICE
                self._log_event(alarm, 'disabled', alarm.current_value, alarm.threshold_value, user)
                self._publish_alarm(alarm)

            logger.info(f"ALARM DISABLED: {alarm_id} by {user}")
            return True

    def enable_alarm(self, alarm_id: str, user: str):
        """Return alarm to service"""
        with self.lock:
            config = self.alarm_configs.get(alarm_id)
            if config:
                config.enabled = True
                self._save_configs()

            alarm = self.active_alarms.get(alarm_id)
            if alarm and alarm.state == AlarmState.OUT_OF_SERVICE:
                # Will be re-evaluated on next scan
                del self.active_alarms[alarm_id]

            logger.info(f"ALARM ENABLED: {alarm_id} by {user}")
            return True

    def _execute_actions(self, action_ids: List[str], alarm: ActiveAlarm):
        """Execute actions when alarm triggers"""
        # Actions are executed by the main DAQ service via callback
        if self.publish_callback:
            for action_id in action_ids:
                try:
                    self.publish_callback('action', {
                        'action_id': action_id,
                        'alarm_id': alarm.alarm_id,
                        'severity': alarm.severity.name
                    })
                except Exception as e:
                    logger.error(f"Error executing action {action_id}: {e}")

    def _execute_safety_action(self, safety_action_id: str, alarm: ActiveAlarm):
        """
        Execute a safety action when alarm triggers (ISA-18.2 automatic response).

        Safety actions are defined in the frontend and executed via MQTT callback.
        The DAQ service handles the actual execution (trip, set outputs, etc.)
        """
        if not self.publish_callback:
            logger.warning(f"Cannot execute safety action {safety_action_id}: no publish callback")
            return

        try:
            self.publish_callback('safety_action', {
                'action_id': safety_action_id,
                'alarm_id': alarm.alarm_id,
                'channel': alarm.channel,
                'severity': alarm.severity.name,
                'threshold_type': alarm.threshold_type,
                'triggered_at': alarm.triggered_at.isoformat(),
                'message': alarm.message
            })
            logger.warning(f"SAFETY ACTION TRIGGERED: {safety_action_id} by alarm {alarm.alarm_id}")
        except Exception as e:
            logger.error(f"Error executing safety action {safety_action_id}: {e}")

    def _log_event(self, alarm: ActiveAlarm, event_type: str, value: Optional[float],
                   threshold: Optional[float], user: Optional[str], duration: Optional[float] = None):
        """Add entry to audit log"""
        entry = AlarmHistoryEntry(
            timestamp=datetime.now(),
            alarm_id=alarm.alarm_id,
            channel=alarm.channel,
            event_type=event_type,
            severity=alarm.severity,
            value=value,
            threshold=threshold,
            user=user,
            message=alarm.message,
            duration_seconds=duration
        )

        self.history.append(entry)
        self._append_to_log(entry)

        # Trim history if needed
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Save periodically (every 10 entries)
        if len(self.history) % 10 == 0:
            self._save_history()

    def _publish_alarm(self, alarm: ActiveAlarm):
        """Publish alarm state to MQTT"""
        if self.publish_callback:
            self.publish_callback('alarm', alarm.to_dict())

    def _publish_alarm_cleared(self, alarm_id: str):
        """Publish alarm cleared state"""
        if self.publish_callback:
            self.publish_callback('alarm_cleared', {'alarm_id': alarm_id})

    # ========================
    # Getters for UI
    # ========================

    def get_active_alarms(self, severity: Optional[AlarmSeverity] = None,
                          group: Optional[str] = None) -> List[ActiveAlarm]:
        """Get active alarms, optionally filtered"""
        with self.lock:
            alarms = list(self.active_alarms.values())

            if severity:
                alarms = [a for a in alarms if a.severity == severity]
            if group:
                alarms = [a for a in alarms
                         if self.alarm_configs.get(a.alarm_id, AlarmConfig('', '', '')).group == group]

            # Sort by severity, then sequence
            alarms.sort(key=lambda a: (a.severity.value, a.sequence_number))
            return alarms

    def get_first_out_alarm(self) -> Optional[ActiveAlarm]:
        """Get the first-out alarm (root cause indicator)"""
        if self.first_out_alarm_id:
            return self.active_alarms.get(self.first_out_alarm_id)
        return None

    def get_alarm_counts(self) -> Dict[str, int]:
        """Get counts by state and severity"""
        with self.lock:
            counts = {
                'total': len(self.active_alarms),
                'active': 0,
                'acknowledged': 0,
                'returned': 0,
                'shelved': 0,
                'critical': 0,
                'high': 0,
                'medium': 0,
                'low': 0
            }

            for alarm in self.active_alarms.values():
                counts[alarm.state.value] = counts.get(alarm.state.value, 0) + 1
                counts[alarm.severity.name.lower()] = counts.get(alarm.severity.name.lower(), 0) + 1

            return counts

    def get_history(self, limit: int = 100, channel: Optional[str] = None,
                    event_type: Optional[str] = None) -> List[AlarmHistoryEntry]:
        """Get alarm history entries"""
        with self.lock:
            entries = self.history.copy()

            if channel:
                entries = [e for e in entries if e.channel == channel]
            if event_type:
                entries = [e for e in entries if e.event_type == event_type]

            # Most recent first
            entries.reverse()
            return entries[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get alarm statistics"""
        with self.lock:
            return {
                **self.stats,
                'counts': self.get_alarm_counts(),
                'first_out': self.first_out_alarm_id,
                'config_count': len(self.alarm_configs),
                'flood': self.get_flood_status()
            }

    # ========================
    # Persistence
    # ========================

    def _save_configs(self):
        """Save alarm configurations to disk"""
        try:
            path = self.data_dir / 'alarm_configs.json'
            data = {k: v.to_dict() for k, v in self.alarm_configs.items()}
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving alarm configs: {e}")

    def _load_configs(self):
        """Load alarm configurations from disk"""
        try:
            path = self.data_dir / 'alarm_configs.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                self.alarm_configs = {k: AlarmConfig.from_dict(v) for k, v in data.items()}
                logger.info(f"Loaded {len(self.alarm_configs)} alarm configurations")
        except Exception as e:
            logger.error(f"Error loading alarm configs: {e}")

    def _save_active_alarms(self):
        """Save active alarms to disk for recovery after restart"""
        try:
            path = self.data_dir / 'active_alarms.json'
            data = {k: v.to_dict() for k, v in self.active_alarms.items()}
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving active alarms: {e}")

    def _load_active_alarms(self):
        """Load active alarms from disk"""
        try:
            path = self.data_dir / 'active_alarms.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)

                for alarm_id, alarm_data in data.items():
                    try:
                        alarm = ActiveAlarm(
                            alarm_id=alarm_data['alarm_id'],
                            channel=alarm_data['channel'],
                            name=alarm_data['name'],
                            severity=AlarmSeverity[alarm_data['severity']],
                            state=AlarmState(alarm_data['state']),
                            threshold_type=alarm_data['threshold_type'],
                            threshold_value=alarm_data['threshold_value'],
                            triggered_value=alarm_data['triggered_value'],
                            current_value=alarm_data['current_value'],
                            triggered_at=datetime.fromisoformat(alarm_data['triggered_at']),
                            sequence_number=alarm_data.get('sequence_number', 0),
                            is_first_out=alarm_data.get('is_first_out', False),
                            message=alarm_data.get('message', '')
                        )

                        if alarm_data.get('acknowledged_at'):
                            alarm.acknowledged_at = datetime.fromisoformat(alarm_data['acknowledged_at'])
                            alarm.acknowledged_by = alarm_data.get('acknowledged_by')

                        self.active_alarms[alarm_id] = alarm
                    except Exception as e:
                        logger.error(f"Error loading alarm {alarm_id}: {e}")

                logger.info(f"Loaded {len(self.active_alarms)} active alarms")
        except Exception as e:
            logger.error(f"Error loading active alarms: {e}")

    def _save_history(self):
        """Save recent alarm history to disk"""
        try:
            path = self.data_dir / 'alarm_history.json'
            # Save last 1000 entries
            entries = self.history[-1000:]
            data = [e.to_dict() for e in entries]
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving alarm history: {e}")

    # ========================================================================
    # Append-Only JSONL Event Log
    # ========================================================================

    def _init_log_file(self):
        """Find newest .jsonl file under max size, or create a new one."""
        existing = sorted(self._log_dir.glob('alarm_events_*.jsonl'), reverse=True)
        for f in existing:
            try:
                if f.stat().st_size / (1024 * 1024) < self._max_log_size_mb:
                    self._log_file = f
                    return
            except OSError:
                continue
        self._create_new_log_file()

    def _create_new_log_file(self):
        """Create a new timestamped JSONL log file."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_file = self._log_dir / f'alarm_events_{ts}.jsonl'

    def _append_to_log(self, entry: AlarmHistoryEntry):
        """Append a single event to the JSONL log file, rotate if needed."""
        try:
            line = json.dumps(entry.to_dict(), default=str) + '\n'
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
            # Check rotation
            try:
                if self._log_file.stat().st_size / (1024 * 1024) >= self._max_log_size_mb:
                    self._create_new_log_file()
            except OSError:
                pass
        except Exception as e:
            logger.error(f"Error appending to alarm event log: {e}")

    def _cleanup_old_logs(self):
        """Gzip files > 7 days old, delete files > 365 days old."""
        try:
            now = datetime.now()
            for f in self._log_dir.iterdir():
                if not f.is_file():
                    continue
                try:
                    age = now - datetime.fromtimestamp(f.stat().st_mtime)
                except OSError:
                    continue
                # Delete very old files (gzipped or not)
                if age > timedelta(days=365):
                    f.unlink()
                    logger.info(f"Deleted old alarm log: {f.name}")
                # Compress uncompressed files older than 7 days
                elif age > timedelta(days=7) and f.suffix == '.jsonl' and f != self._log_file:
                    gz_path = f.with_suffix('.jsonl.gz')
                    try:
                        with open(f, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
                            while True:
                                chunk = src.read(65536)
                                if not chunk:
                                    break
                                dst.write(chunk)
                        f.unlink()
                        logger.info(f"Compressed alarm log: {f.name}")
                    except Exception as e:
                        logger.error(f"Error compressing {f.name}: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up alarm logs: {e}")

    def _load_history(self):
        """Load alarm history from disk"""
        try:
            path = self.data_dir / 'alarm_history.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)

                for entry_data in data:
                    try:
                        entry = AlarmHistoryEntry(
                            timestamp=datetime.fromisoformat(entry_data['timestamp']),
                            alarm_id=entry_data['alarm_id'],
                            channel=entry_data['channel'],
                            event_type=entry_data['event_type'],
                            severity=AlarmSeverity[entry_data['severity']],
                            value=entry_data.get('value'),
                            threshold=entry_data.get('threshold'),
                            user=entry_data.get('user'),
                            message=entry_data.get('message', ''),
                            duration_seconds=entry_data.get('duration_seconds')
                        )
                        self.history.append(entry)
                    except Exception as e:
                        logger.error(f"Error loading history entry: {e}")

                logger.info(f"Loaded {len(self.history)} alarm history entries")
        except Exception as e:
            logger.error(f"Error loading alarm history: {e}")

    def save_all(self):
        """Save all state to disk"""
        with self.lock:
            self._save_configs()
            self._save_active_alarms()
            self._save_history()
            self._save_correlation_rules()
            self._cleanup_old_logs()

    # ========================================================================
    # Correlation Rule Management
    # ========================================================================

    def add_correlation_rule(self, rule: CorrelationRule):
        """Add or update a correlation rule"""
        with self.lock:
            self.correlation_rules[rule.id] = rule
            self._save_correlation_rules()
            logger.info(f"Added/updated correlation rule: {rule.id}")

    def remove_correlation_rule(self, rule_id: str):
        """Remove a correlation rule"""
        with self.lock:
            if rule_id in self.correlation_rules:
                del self.correlation_rules[rule_id]
                self._save_correlation_rules()
                logger.info(f"Removed correlation rule: {rule_id}")

    def get_correlation_rules(self) -> List[CorrelationRule]:
        """Get all correlation rules"""
        return list(self.correlation_rules.values())

    def _save_correlation_rules(self):
        """Save correlation rules to disk"""
        try:
            path = self.data_dir / 'correlation_rules.json'
            data = [r.to_dict() for r in self.correlation_rules.values()]
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving correlation rules: {e}")

    def _load_correlation_rules(self):
        """Load correlation rules from disk"""
        try:
            path = self.data_dir / 'correlation_rules.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)

                for rule_data in data:
                    try:
                        rule = CorrelationRule.from_dict(rule_data)
                        self.correlation_rules[rule.id] = rule
                    except Exception as e:
                        logger.error(f"Error loading correlation rule: {e}")

                logger.info(f"Loaded {len(self.correlation_rules)} correlation rules")
        except Exception as e:
            logger.error(f"Error loading correlation rules: {e}")

    # ========================================================================
    # Event Correlation Engine
    # ========================================================================

    def _check_correlation(self, alarm_id: str, timestamp_us: int) -> Optional[EventCorrelation]:
        """
        Check if this alarm should be correlated with other recent alarms.
        Called when an alarm is triggered.
        Returns EventCorrelation if correlation detected, None otherwise.
        """
        import uuid

        # Add to recent alarms list
        self.recent_alarms.append((timestamp_us, alarm_id))

        # Trim to max size
        if len(self.recent_alarms) > self.max_recent_alarms:
            self.recent_alarms = self.recent_alarms[-self.max_recent_alarms:]

        # Check all enabled correlation rules
        for rule in self.correlation_rules.values():
            if not rule.enabled:
                continue

            # Is this alarm the trigger for this rule?
            if alarm_id == rule.trigger_alarm:
                # Look for related alarms in the time window
                time_window_us = rule.time_window_ms * 1000
                window_start = timestamp_us - time_window_us

                related_found = []
                for ts, aid in self.recent_alarms:
                    if ts >= window_start and aid in rule.related_alarms:
                        related_found.append(aid)

                if related_found:
                    # Correlation detected!
                    root_cause = rule.root_cause_hint if rule.root_cause_hint else alarm_id
                    correlation = EventCorrelation(
                        correlation_id=str(uuid.uuid4()),
                        trigger_alarm_id=alarm_id,
                        related_alarm_ids=related_found,
                        timestamp=datetime.now(),
                        root_cause_alarm_id=root_cause,
                        correlation_rule_id=rule.id,
                        node_id=self.node_id
                    )

                    # Store active correlation
                    self.active_correlations[correlation.correlation_id] = correlation

                    logger.info(f"Correlation detected: {correlation.correlation_id} "
                               f"(trigger={alarm_id}, related={related_found})")

                    # Publish correlation event
                    if self.publish_callback:
                        self.publish_callback('correlations/detected', correlation.to_dict())

                    return correlation

            # Check if any related alarm matches this alarm (reverse lookup)
            if alarm_id in rule.related_alarms:
                # Look for trigger alarm in window
                time_window_us = rule.time_window_ms * 1000
                window_start = timestamp_us - time_window_us

                for ts, aid in self.recent_alarms:
                    if ts >= window_start and aid == rule.trigger_alarm:
                        # Found the trigger - check if correlation already exists
                        existing = False
                        for corr in self.active_correlations.values():
                            if corr.trigger_alarm_id == aid and alarm_id in corr.related_alarm_ids:
                                existing = True
                                break

                        if not existing:
                            # Create new correlation
                            root_cause = rule.root_cause_hint if rule.root_cause_hint else rule.trigger_alarm
                            correlation = EventCorrelation(
                                correlation_id=str(uuid.uuid4()),
                                trigger_alarm_id=aid,
                                related_alarm_ids=[alarm_id],
                                timestamp=datetime.now(),
                                root_cause_alarm_id=root_cause,
                                correlation_rule_id=rule.id,
                                node_id=self.node_id
                            )

                            self.active_correlations[correlation.correlation_id] = correlation

                            logger.info(f"Correlation detected (reverse): {correlation.correlation_id}")

                            if self.publish_callback:
                                self.publish_callback('correlations/detected', correlation.to_dict())

                            return correlation

        return None

    def get_correlations_for_alarm(self, alarm_id: str) -> List[EventCorrelation]:
        """Get all correlations involving this alarm"""
        correlations = []
        for corr in self.active_correlations.values():
            if corr.trigger_alarm_id == alarm_id or alarm_id in corr.related_alarm_ids:
                correlations.append(corr)
        return correlations

    def clear_correlation(self, correlation_id: str):
        """Clear a correlation when all related alarms are cleared"""
        if correlation_id in self.active_correlations:
            del self.active_correlations[correlation_id]
            logger.info(f"Cleared correlation: {correlation_id}")

    # ========================================================================
    # SOE (Sequence of Events) Buffer
    # ========================================================================

    def add_soe_event(
        self,
        event_type: str,
        source_channel: str,
        value: Any,
        previous_value: Any = None,
        severity: Optional[str] = None,
        message: str = "",
        alarm_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timestamp_us: Optional[int] = None
    ) -> SOEEvent:
        """
        Add an event to the SOE buffer.
        Called when significant events occur (alarms, state changes, digital edges).
        """
        import uuid

        if timestamp_us is None:
            timestamp_us = time.time_ns() // 1000

        event = SOEEvent(
            event_id=str(uuid.uuid4()),
            timestamp_us=timestamp_us,
            timestamp_iso=datetime.now().isoformat(),
            event_type=event_type,
            source_channel=source_channel,
            value=value,
            previous_value=previous_value,
            severity=severity,
            message=message,
            node_id=self.node_id,
            alarm_id=alarm_id,
            correlation_id=correlation_id
        )

        with self.lock:
            self.soe_buffer.append(event)

            # Trim buffer if needed
            if len(self.soe_buffer) > self.max_soe_events:
                self.soe_buffer = self.soe_buffer[-self.max_soe_events:]

        # Publish SOE event
        if self.publish_callback:
            self.publish_callback('soe/event', event.to_dict())

        return event

    def get_soe_events(
        self,
        start_time_us: Optional[int] = None,
        end_time_us: Optional[int] = None,
        event_types: Optional[List[str]] = None,
        channels: Optional[List[str]] = None,
        limit: int = 1000
    ) -> List[SOEEvent]:
        """
        Query SOE events with optional filters.
        Returns events ordered by timestamp (newest first).
        """
        events = self.soe_buffer.copy()

        # Apply filters
        if start_time_us is not None:
            events = [e for e in events if e.timestamp_us >= start_time_us]

        if end_time_us is not None:
            events = [e for e in events if e.timestamp_us <= end_time_us]

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        if channels:
            events = [e for e in events if e.source_channel in channels]

        # Sort by timestamp descending (newest first)
        events.sort(key=lambda e: e.timestamp_us, reverse=True)

        # Apply limit
        return events[:limit]

    def export_soe_csv(self, filepath: str, **filters) -> int:
        """
        Export SOE events to CSV file with full timestamp precision.
        Returns number of events exported.
        """
        import csv

        events = self.get_soe_events(**filters)

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp_us', 'timestamp_iso', 'event_type', 'channel',
                'value', 'previous_value', 'severity', 'message',
                'alarm_id', 'correlation_id', 'node_id'
            ])

            for event in events:
                writer.writerow([
                    event.timestamp_us,
                    event.timestamp_iso,
                    event.event_type,
                    event.source_channel,
                    event.value,
                    event.previous_value,
                    event.severity or '',
                    event.message,
                    event.alarm_id or '',
                    event.correlation_id or '',
                    event.node_id
                ])

        logger.info(f"Exported {len(events)} SOE events to {filepath}")
        return len(events)

    def clear_soe_buffer(self):
        """Clear all SOE events from buffer"""
        with self.lock:
            self.soe_buffer.clear()
        logger.info("SOE buffer cleared")

    def clear_all(self, clear_configs: bool = False):
        """
        Clear all alarm state to start fresh.

        Called when:
        - No project is loaded (startup with empty state)
        - Project is closed
        - User explicitly requests reset

        Args:
            clear_configs: If True, also clear alarm configurations.
                          If False (default), only clear runtime state.
        """
        with self.lock:
            # Clear active alarms
            self.active_alarms.clear()

            # Clear history
            self.history.clear()

            # Clear SOE buffer
            self.soe_buffer.clear()

            # Clear timers
            self.on_delay_timers.clear()
            self.off_delay_timers.clear()
            self.timed_latch_timers.clear()

            # Clear rate history
            self.value_history.clear()

            # Clear digital debounce state
            self.digital_debounce_timers.clear()
            self.digital_last_states.clear()

            # Reset first-out tracking
            self.alarm_sequence = 0
            self.first_out_alarm_id = None
            self.cascade_start_time = None

            # Clear correlations
            self.active_correlations.clear()
            self.recent_alarms.clear()

            # Clear flood state
            self._flood_active = False
            self._flood_start_time = None
            self._flood_alarm_times.clear()
            self._flood_suppressed_count = 0
            self._flood_root_cause_id = None

            # Reset stats
            self.stats = {
                'total_alarms': 0,
                'total_acknowledged': 0,
                'total_cleared': 0,
                'total_shelved': 0
            }

            # Optionally clear configs
            if clear_configs:
                self.alarm_configs.clear()
                self._save_configs()

            # Save empty state to disk
            self._save_active_alarms()
            self._save_history()

            logger.info(f"Alarm manager cleared (configs={'cleared' if clear_configs else 'preserved'})")
