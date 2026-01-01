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

import json
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
            'shelve_allowed': self.shelve_allowed
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
            shelve_allowed=d.get('shelve_allowed', True)
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
            'duration_seconds': (datetime.now() - self.triggered_at).total_seconds()
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

        # Load saved state
        self._load_configs()
        self._load_active_alarms()
        self._load_history()

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
            timestamp = time.time()

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

        now = time.time()
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

        # Check if alarm condition is met
        condition_met, threshold_type, threshold_value = self._check_thresholds(config, value)

        # Also check rate-of-change
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

    def _trigger_alarm(self, config: AlarmConfig, value: float, threshold_type: str, threshold_value: float):
        """Create a new active alarm"""
        now = datetime.now()

        # Determine first-out
        is_first_out = False
        if self.first_out_alarm_id is None or \
           (self.cascade_start_time and time.time() - self.cascade_start_time > self.CASCADE_WINDOW_S):
            # New cascade
            self.alarm_sequence += 1
            self.first_out_alarm_id = config.id
            self.cascade_start_time = time.time()
            is_first_out = True

        self.alarm_sequence += 1

        # Create message
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
            message=message
        )

        self.active_alarms[config.id] = alarm
        self.stats['total_alarms'] += 1

        # Log to history
        self._log_event(alarm, 'triggered', value, threshold_value, None)

        # Publish to MQTT
        self._publish_alarm(alarm)

        # Execute actions
        self._execute_actions(config.actions, alarm)

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
        """Unshelve an alarm"""
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm is None or alarm.state != AlarmState.SHELVED:
                return False

            # Revert to previous state
            if alarm.acknowledged_at:
                alarm.state = AlarmState.ACKNOWLEDGED
            else:
                alarm.state = AlarmState.ACTIVE

            alarm.shelved_at = None
            alarm.shelved_by = None
            alarm.shelve_expires_at = None
            alarm.shelve_reason = ""

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
                'config_count': len(self.alarm_configs)
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
