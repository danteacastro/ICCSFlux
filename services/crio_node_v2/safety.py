"""
Safety Module for cRIO Node V2

Provides single-pass safety checking with:
- Configurable alarm limits (HIHI, HI, LO, LOLO)
- Rate-of-change alarms
- On-delay and off-delay for alarm stability
- Alarm shelving (SHELVED, OUT_OF_SERVICE) per ISA-18.2
- Safety actions (set outputs, stop session)
- Alarm state tracking
- Event publishing
- Interlock evaluation with latch state machine (IEC 61511)
- Alarm flood detection (ISA-18.2)
- Persistent alarm history and interlock state
- Configurable per-channel safe state
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Tuple, Union

logger = logging.getLogger('cRIONode')


class AlarmSeverity(Enum):
    """Alarm severity levels."""
    NONE = 0
    WARNING = 1     # HI or LO
    CRITICAL = 2    # HIHI or LOLO


class AlarmState(Enum):
    """Alarm state machine states (ISA-18.2 compliant)."""
    NORMAL = 0
    ACTIVE = 1
    ACKNOWLEDGED = 2
    RETURNED = 3          # Condition cleared but not acknowledged
    SHELVED = 4           # Temporarily suppressed by operator
    OUT_OF_SERVICE = 5    # Disabled for maintenance


class LatchState(Enum):
    """Safety latch states for interlock system."""
    SAFE = "safe"        # Disarmed — interlocks evaluate but do not trip
    ARMED = "armed"      # Armed — interlock failure triggers trip actions
    TRIPPED = "tripped"  # Tripped — controlled outputs held at trip values


@dataclass
class AlarmConfig:
    """Alarm configuration for a channel."""
    channel: str
    enabled: bool = True
    hihi_limit: Optional[float] = None
    hi_limit: Optional[float] = None
    lo_limit: Optional[float] = None
    lolo_limit: Optional[float] = None
    deadband: float = 0.0
    delay_seconds: float = 0.0
    off_delay_seconds: float = 0.0
    rate_of_change_limit: Optional[float] = None
    rate_of_change_period_s: float = 60.0
    safety_action: Optional[Union[str, Dict[str, Any]]] = None


@dataclass
class AlarmEvent:
    """Alarm event record."""
    channel: str
    alarm_type: str  # 'hihi', 'hi', 'lo', 'lolo', 'rate_of_change'
    value: float
    limit: float
    severity: AlarmSeverity
    timestamp: float
    state: AlarmState = AlarmState.ACTIVE


@dataclass
class ChannelAlarmState:
    """Track alarm state for a channel."""
    state: AlarmState = AlarmState.NORMAL
    active_alarm_type: Optional[str] = None
    active_since: Optional[float] = None
    last_value: float = 0.0
    acknowledged: bool = False
    # Shelving fields
    shelved_at: Optional[float] = None
    shelved_by: Optional[str] = None
    shelve_expires_at: Optional[float] = None
    # State before shelving (to restore on unshelve)
    pre_shelve_state: Optional[AlarmState] = None


# =========================================================================
# INTERLOCK DATA STRUCTURES
# =========================================================================

@dataclass
class InterlockCondition:
    """Single condition within an interlock."""
    id: str
    condition_type: str   # 'channel_value', 'digital_input', 'alarm_active',
                          # 'no_active_alarms', 'acquiring'
    channel: Optional[str] = None
    operator: Optional[str] = None   # '<', '<=', '>', '>=', '==', '!='
    value: Optional[Any] = None
    invert: bool = False
    delay_s: float = 0.0

    VALID_OPERATORS = {'==', '!=', '<', '>', '<=', '>='}
    VALID_CONDITION_TYPES = {
        'channel_value', 'digital_input',
        'alarm_active', 'no_active_alarms', 'acquiring'
    }

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'type': self.condition_type,
            'channel': self.channel,
            'operator': self.operator,
            'value': self.value,
            'invert': self.invert,
            'delay_s': self.delay_s,
        }

    @staticmethod
    def from_dict(d: dict) -> 'InterlockCondition':
        # Accept both DAQ service format ('type') and node format ('condition_type')
        return InterlockCondition(
            id=d.get('id', ''),
            condition_type=d.get('type', d.get('condition_type', 'channel_value')),
            channel=d.get('channel'),
            operator=d.get('operator'),
            value=d.get('value'),
            invert=d.get('invert', False),
            delay_s=float(d.get('delay_s', 0.0)),
        )


@dataclass
class InterlockControl:
    """Action to execute when interlock trips."""
    control_type: str     # 'set_digital_output', 'set_analog_output', 'stop_session'
    channel: Optional[str] = None
    set_value: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'type': self.control_type,
            'channel': self.channel,
            'setValue': self.set_value,
        }

    @staticmethod
    def from_dict(d: dict) -> 'InterlockControl':
        # Accept both DAQ service format ('type'/'setValue') and node format ('control_type'/'set_value')
        return InterlockControl(
            control_type=d.get('type', d.get('control_type', '')),
            channel=d.get('channel'),
            set_value=d.get('setValue', d.get('set_value')),
        )


@dataclass
class Interlock:
    """Full interlock definition."""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    conditions: List[InterlockCondition] = field(default_factory=list)
    condition_logic: str = "AND"   # "AND" or "OR"
    controls: List[InterlockControl] = field(default_factory=list)
    bypass_allowed: bool = False
    bypassed: bool = False
    bypassed_by: Optional[str] = None
    bypassed_at: Optional[float] = None
    max_bypass_duration: Optional[float] = None
    demand_count: int = 0
    last_demand_time: Optional[float] = None
    last_proof_test: Optional[float] = None
    proof_test_interval_days: Optional[float] = None
    priority: str = "medium"
    sil_rating: Optional[str] = None
    requires_acknowledgment: bool = False
    is_critical: bool = False  # Requires Admin; blocks modify while ARMED/TRIPPED

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'conditions': [c.to_dict() for c in self.conditions],
            'conditionLogic': self.condition_logic,
            'controls': [c.to_dict() for c in self.controls],
            'bypassAllowed': self.bypass_allowed,
            'bypassed': self.bypassed,
            'bypassedBy': self.bypassed_by,
            'bypassedAt': self.bypassed_at,
            'maxBypassDuration': self.max_bypass_duration,
            'demandCount': self.demand_count,
            'lastDemandTime': self.last_demand_time,
            'lastProofTest': self.last_proof_test,
            'proofTestIntervalDays': self.proof_test_interval_days,
            'priority': self.priority,
            'silRating': self.sil_rating,
            'requiresAcknowledgment': self.requires_acknowledgment,
            'isCritical': self.is_critical,
        }

    @staticmethod
    def from_dict(d: dict) -> 'Interlock':
        # Accept both DAQ service camelCase and node snake_case field names
        return Interlock(
            id=d.get('id', ''),
            name=d.get('name', ''),
            description=d.get('description', ''),
            enabled=d.get('enabled', True),
            conditions=[InterlockCondition.from_dict(c) for c in d.get('conditions', [])],
            condition_logic=d.get('conditionLogic', d.get('condition_logic', 'AND')),
            controls=[InterlockControl.from_dict(c) for c in d.get('controls', [])],
            bypass_allowed=d.get('bypassAllowed', d.get('bypass_allowed', False)),
            bypassed=d.get('bypassed', False),
            bypassed_by=d.get('bypassedBy', d.get('bypassed_by')),
            bypassed_at=d.get('bypassedAt', d.get('bypassed_at')),
            max_bypass_duration=d.get('maxBypassDuration', d.get('max_bypass_duration')),
            demand_count=int(d.get('demandCount', d.get('demand_count', 0))),
            last_demand_time=d.get('lastDemandTime', d.get('last_demand_time')),
            last_proof_test=d.get('lastProofTest', d.get('last_proof_test')),
            proof_test_interval_days=d.get('proofTestIntervalDays', d.get('proof_test_interval_days')),
            priority=d.get('priority', 'medium'),
            sil_rating=d.get('silRating', d.get('sil_rating')),
            requires_acknowledgment=d.get('requiresAcknowledgment', d.get('requires_acknowledgment', False)),
            is_critical=d.get('isCritical', d.get('is_critical', False)),
        )


@dataclass
class SafeStateConfig:
    """Per-channel safe state configuration.

    channel_safe_values maps output channel names to their safe values.
    Channels NOT listed use ChannelConfig.default_value as fallback.
    """
    channel_safe_values: Dict[str, float] = field(default_factory=dict)
    stop_session: bool = True

    def to_dict(self) -> dict:
        return {
            'channelSafeValues': dict(self.channel_safe_values),
            'stopSession': self.stop_session,
        }

    @staticmethod
    def from_dict(d: dict) -> 'SafeStateConfig':
        # Accept node format (channel_safe_values dict) or DAQ service format
        # (resetDigitalOutputs, analogSafeValue, channel lists)
        csv = d.get('channel_safe_values', d.get('channelSafeValues'))
        if csv is not None:
            # Node format: explicit per-channel values
            return SafeStateConfig(
                channel_safe_values={k: float(v) for k, v in csv.items()},
                stop_session=d.get('stop_session', d.get('stopSession', True)),
            )
        # DAQ service format: category-based with channel lists
        channel_safe_values = {}
        analog_safe = float(d.get('analogSafeValue', d.get('analog_safe_value', 0.0)))
        if d.get('resetDigitalOutputs', d.get('reset_digital_outputs', True)):
            for ch in d.get('digitalOutputChannels', d.get('digital_output_channels', [])):
                channel_safe_values[ch] = 0.0
        if d.get('resetAnalogOutputs', d.get('reset_analog_outputs', True)):
            for ch in d.get('analogOutputChannels', d.get('analog_output_channels', [])):
                channel_safe_values[ch] = analog_safe
        return SafeStateConfig(
            channel_safe_values=channel_safe_values,
            stop_session=d.get('stopSession', d.get('stop_session', True)),
        )


class SafetyManager:
    """
    Single-pass safety checking with ISA-18.2 alarm management
    and IEC 61511 interlock evaluation.

    Usage:
        safety = SafetyManager(data_dir='/path/to/safety')
        safety.configure('temp_1', AlarmConfig(...))

        # In main loop:
        events = safety.check_all(channel_values)
        for event in events:
            # Handle event (publish, trigger action)
    """

    def __init__(self, data_dir: Optional[str] = None):
        # Alarm state
        self._configs: Dict[str, AlarmConfig] = {}
        self._states: Dict[str, ChannelAlarmState] = {}
        self._output_channels: set = set()

        # Track outputs held by safety actions (prevents scripts/MQTT from overriding)
        # Maps: output_channel -> { 'alarm_channel': str, 'action': str, 'held_since': float }
        self._safety_held_outputs: Dict[str, Dict[str, Any]] = {}

        # Off-delay timers: channel -> timestamp when off-delay started
        self._off_delay_timers: Dict[str, float] = {}

        # Rate-of-change tracking: channel -> [(timestamp, value), ...]
        self._value_history: Dict[str, List[Tuple[float, float]]] = {}

        # Rate-of-change active flags (for hysteresis)
        self._roc_active: Dict[str, bool] = {}

        # Callback for alarm events
        self.on_alarm: Optional[Callable[[AlarmEvent], None]] = None

        # Callback for safety actions
        self.on_action: Optional[Callable[[str, str, float], None]] = None

        # Callback for stop session action
        self.on_stop_session: Optional[Callable[[], None]] = None

        # =====================================================================
        # INTERLOCK STATE
        # =====================================================================
        self._interlocks: Dict[str, Interlock] = {}
        self._latch_state: LatchState = LatchState.SAFE
        self._is_tripped: bool = False
        self._last_trip_time: Optional[float] = None
        self._last_trip_reason: Optional[str] = None
        self._interlock_prev_states: Dict[str, bool] = {}  # id -> was_satisfied
        self._condition_delay_state: Dict[str, Dict[str, Any]] = {}  # cond_id -> delay tracking
        self._executed_actions: set = set()  # action keys already fired
        self._interlock_held_outputs: Dict[str, str] = {}  # output_channel -> interlock_id
        self._trip_ack_state: Dict[str, dict] = {}  # interlock_id -> ack info
        self._interlock_status: Optional[Dict[str, Any]] = None  # last evaluation result

        # Callback for interlock trip actions (same sig as on_action)
        self.on_interlock_action: Optional[Callable[[str, str, float], None]] = None

        # Callback for MQTT publishing (topic, payload)
        self.on_publish: Optional[Callable[[str, Dict[str, Any]], None]] = None

        # Acquiring flag (set by node main loop for 'acquiring' condition type)
        self._acquiring: bool = False

        # =====================================================================
        # SAFE STATE CONFIG
        # =====================================================================
        self._safe_state_config: SafeStateConfig = SafeStateConfig()

        # =====================================================================
        # PERSISTENCE
        # =====================================================================
        self._data_dir = data_dir
        self._alarm_history: List[Dict[str, Any]] = []
        self._max_alarm_history = 200

        # =====================================================================
        # FLOOD DETECTION
        # =====================================================================
        self._alarm_timestamps: List[float] = []
        self._flood_active: bool = False
        self._flood_first_alarm: Optional[Dict[str, Any]] = None
        self._flood_start_time: Optional[float] = None
        self.FLOOD_THRESHOLD = 10
        self.FLOOD_WINDOW_S = 60.0
        self.FLOOD_CLEAR_RATIO = 0.5

        # Load persisted state
        if self._data_dir:
            self._ensure_data_dir()
            self._load_persisted_state()

    def _ensure_data_dir(self):
        """Create data directory if it doesn't exist."""
        if self._data_dir:
            try:
                os.makedirs(self._data_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create data dir {self._data_dir}: {e}")

    def set_output_channels(self, channels: set):
        """Update the set of known valid output channels."""
        self._output_channels = set(channels)

    def configure(self, channel: str, config: AlarmConfig):
        """Configure alarm limits for a channel."""
        self._configs[channel] = config
        if channel not in self._states:
            self._states[channel] = ChannelAlarmState()

    def configure_from_dict(self, channel: str, data: Dict[str, Any]):
        """Configure from dictionary (from config file)."""
        # Support both legacy string and new dict format for safety_action
        raw_action = data.get('safety_action')
        config = AlarmConfig(
            channel=channel,
            enabled=data.get('alarm_enabled', True),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
            deadband=data.get('alarm_deadband', 0.0),
            delay_seconds=data.get('alarm_delay_sec', 0.0),
            off_delay_seconds=data.get('alarm_off_delay_sec', 0.0),
            rate_of_change_limit=data.get('rate_of_change_limit'),
            rate_of_change_period_s=data.get('rate_of_change_period_s', 60.0),
            safety_action=raw_action
        )
        self.configure(channel, config)

    def load_config(self, config_data: Dict[str, Any]):
        """Load alarm and interlock configuration from a config push.

        Called by the node when it receives a config/full MQTT message.
        """
        # Load alarm configs
        for alarm_data in config_data.get('alarms', []):
            channel = alarm_data.get('channel', '')
            if channel:
                self.configure_from_dict(channel, alarm_data)

        # Load interlocks if present
        if 'interlocks' in config_data:
            self.configure_interlocks(config_data['interlocks'])

        # Load safe state config if present
        if 'safe_state_config' in config_data:
            self.configure_safe_state(config_data['safe_state_config'])

        self._save_alarm_configs()
        logger.info(f"Safety config loaded: {len(self._configs)} alarms, "
                    f"{len(self._interlocks)} interlocks")

    def check_all(self, channel_values: Dict[str, float],
                  configured_channels: Optional[set] = None) -> List[AlarmEvent]:
        """
        Check all channels for alarm conditions and evaluate interlocks.

        Args:
            channel_values: {channel_name: value}
            configured_channels: Optional set of all configured channel names.
                If provided, channels in this set but missing from channel_values
                will generate COMM_FAIL alarms (hardware offline detection).

        Returns:
            List of new alarm events
        """
        events = []
        now = time.time()
        state_changed = False

        # Check shelve expiry first
        self._check_shelve_expiry(now)

        for channel, value in channel_values.items():
            config = self._configs.get(channel)
            if not config or not config.enabled:
                continue

            state = self._states.get(channel)
            if state and state.state in (AlarmState.SHELVED, AlarmState.OUT_OF_SERVICE):
                # Skip evaluation for shelved/OOS alarms
                state.last_value = value
                # Still track value history for ROC (so rate is accurate when unshelved)
                self._record_value_history(channel, value, now)
                continue

            event = self._check_channel(channel, value, config, now)
            if event:
                state_changed = True

                # Check alarm flood
                self._check_flood(event, now)

                # Suppress non-critical alarms during flood
                if self._should_suppress_alarm(event):
                    logger.debug(f"Alarm suppressed (flood): {channel} {event.alarm_type}")
                    # Still record history even if suppressed
                    self._record_alarm_history(event)
                    continue

                events.append(event)
                self._record_alarm_history(event)

                # Trigger callback
                if self.on_alarm:
                    try:
                        self.on_alarm(event)
                    except Exception as e:
                        logger.error(f"Alarm callback error: {e}", exc_info=True)

                # Execute safety action
                if config.safety_action and event.state == AlarmState.ACTIVE:
                    self._execute_action(config.safety_action, channel, value)

            # Check rate-of-change
            if config.rate_of_change_limit is not None:
                roc_event = self._check_rate_of_change(channel, value, config, now)
                if roc_event:
                    state_changed = True
                    self._check_flood(roc_event, now)

                    if not self._should_suppress_alarm(roc_event):
                        events.append(roc_event)
                        self._record_alarm_history(roc_event)
                        if self.on_alarm:
                            try:
                                self.on_alarm(roc_event)
                            except Exception as e:
                                logger.error(f"ROC alarm callback error: {e}", exc_info=True)
                        if config.safety_action:
                            self._execute_action(config.safety_action, channel, value)
                    else:
                        self._record_alarm_history(roc_event)

        # Detect missing channels (possible hardware offline / module unplug)
        if configured_channels:
            for channel in configured_channels:
                if channel in channel_values:
                    # Channel present — clear any COMM_FAIL
                    state = self._states.get(channel)
                    if state and state.active_alarm_type == 'comm_fail':
                        state.state = AlarmState.NORMAL
                        state.active_alarm_type = None
                        state_changed = True
                        events.append(AlarmEvent(
                            channel=channel, alarm_type='comm_fail_clear',
                            value=channel_values[channel], limit=0.0,
                            severity=AlarmSeverity.NONE, timestamp=now,
                            state=AlarmState.NORMAL,
                        ))
                        logger.info(f"COMM_FAIL cleared: Channel '{channel}' back online")
                    continue

                config = self._configs.get(channel)
                if not config or not config.enabled:
                    continue
                state = self._states.get(channel)
                if not state:
                    state = ChannelAlarmState()
                    self._states[channel] = state
                if state.state in (AlarmState.SHELVED, AlarmState.OUT_OF_SERVICE):
                    continue

                # Generate COMM_FAIL if not already active
                if state.active_alarm_type != 'comm_fail':
                    state.state = AlarmState.ACTIVE
                    state.active_alarm_type = 'comm_fail'
                    state.active_since = now
                    state.acknowledged = False
                    state_changed = True
                    event = AlarmEvent(
                        channel=channel, alarm_type='comm_fail',
                        value=0.0, limit=0.0,  # Use 0.0 instead of NaN (NaN breaks JSON serialization)
                        severity=AlarmSeverity.CRITICAL, timestamp=now,
                        state=AlarmState.ACTIVE,
                    )
                    events.append(event)
                    self._record_alarm_history(event)
                    logger.warning(f"COMM_FAIL: Channel '{channel}' missing — hardware offline?")
                    if self.on_alarm:
                        try:
                            self.on_alarm(event)
                        except Exception:
                            pass
                    if config.safety_action:
                        self._execute_action(config.safety_action, channel, float('nan'))

        # Evaluate interlocks after alarms (so alarm_active conditions see current state)
        if self._interlocks:
            self._interlock_status = self.evaluate_all_interlocks(channel_values)

        # Persist alarm states if any changed
        if state_changed:
            self._save_alarm_states()

        return events

    def _record_value_history(self, channel: str, value: float, now: float):
        """Record value for rate-of-change calculation."""
        history = self._value_history.get(channel)
        if history is None:
            history = []
            self._value_history[channel] = history
        history.append((now, value))
        # Keep only last 120 seconds of history (2x max period for safety margin)
        cutoff = now - 120.0
        self._value_history[channel] = [(t, v) for t, v in history if t >= cutoff]

    def _check_rate_of_change(self, channel: str, value: float, config: AlarmConfig,
                               now: float) -> Optional[AlarmEvent]:
        """Check rate-of-change alarm condition."""
        self._record_value_history(channel, value, now)

        history = self._value_history.get(channel, [])
        if len(history) < 2:
            return None

        period = config.rate_of_change_period_s
        cutoff = now - period
        points = [(t, v) for t, v in history if t >= cutoff]
        if len(points) < 2:
            return None

        first_t, first_v = points[0]
        last_t, last_v = points[-1]
        dt = last_t - first_t
        if dt < 0.001:
            return None

        rate = abs(last_v - first_v) / dt
        limit = config.rate_of_change_limit
        was_active = self._roc_active.get(channel, False)

        if was_active:
            # Apply 20% hysteresis for clearing
            if rate < limit * 0.8:
                self._roc_active[channel] = False
            return None
        else:
            if rate >= limit:
                self._roc_active[channel] = True
                return AlarmEvent(
                    channel=channel,
                    alarm_type='rate_of_change',
                    value=value,
                    limit=limit,
                    severity=AlarmSeverity.WARNING,
                    timestamp=now,
                    state=AlarmState.ACTIVE
                )

        return None

    def _check_channel(self, channel: str, value: float, config: AlarmConfig,
                        now: float) -> Optional[AlarmEvent]:
        """Check single channel for alarm condition."""
        state = self._states.get(channel)
        if not state:
            state = ChannelAlarmState()
            self._states[channel] = state

        state.last_value = value

        # NaN from hardware (open TC, broken sensor) — treat as COMM_FAIL
        if isinstance(value, float) and math.isnan(value):
            if state.state != AlarmState.ACTIVE or state.active_alarm_type != 'comm_fail':
                state.state = AlarmState.ACTIVE
                state.active_alarm_type = 'comm_fail'
                state.active_since = now
                state.acknowledged = False
                return AlarmEvent(
                    channel=channel, alarm_type='comm_fail',
                    value=0.0, limit=0.0,
                    severity=AlarmSeverity.CRITICAL, timestamp=now,
                    state=AlarmState.ACTIVE,
                )
            return None

        # Determine alarm condition
        alarm_type = None
        limit = None
        severity = AlarmSeverity.NONE

        if config.hihi_limit is not None and value >= config.hihi_limit:
            alarm_type = 'hihi'
            limit = config.hihi_limit
            severity = AlarmSeverity.CRITICAL
        elif config.lolo_limit is not None and value <= config.lolo_limit:
            alarm_type = 'lolo'
            limit = config.lolo_limit
            severity = AlarmSeverity.CRITICAL
        elif config.hi_limit is not None and value >= config.hi_limit:
            alarm_type = 'hi'
            limit = config.hi_limit
            severity = AlarmSeverity.WARNING
        elif config.lo_limit is not None and value <= config.lo_limit:
            alarm_type = 'lo'
            limit = config.lo_limit
            severity = AlarmSeverity.WARNING

        # State machine transitions
        if alarm_type:
            # Alarm condition present — cancel any off-delay timer
            self._off_delay_timers.pop(channel, None)

            if state.state == AlarmState.NORMAL:
                # New alarm - check on-delay
                if state.active_since is None:
                    state.active_since = now

                if (now - state.active_since) >= config.delay_seconds:
                    # Delay expired, alarm active
                    state.state = AlarmState.ACTIVE
                    state.active_alarm_type = alarm_type
                    state.acknowledged = False

                    return AlarmEvent(
                        channel=channel,
                        alarm_type=alarm_type,
                        value=value,
                        limit=limit,
                        severity=severity,
                        timestamp=now,
                        state=AlarmState.ACTIVE
                    )
            elif state.state == AlarmState.RETURNED:
                # Condition returned while waiting for ack
                state.state = AlarmState.ACTIVE
                state.active_alarm_type = alarm_type

        else:
            # No alarm condition - apply deadband + off-delay
            if state.state == AlarmState.ACTIVE:
                # Check if we've cleared the limit with deadband
                cleared = True
                if state.active_alarm_type in ('hihi', 'hi'):
                    limit = config.hihi_limit if state.active_alarm_type == 'hihi' else config.hi_limit
                    if limit and value >= (limit - config.deadband):
                        cleared = False
                elif state.active_alarm_type in ('lolo', 'lo'):
                    limit = config.lolo_limit if state.active_alarm_type == 'lolo' else config.lo_limit
                    if limit and value <= (limit + config.deadband):
                        cleared = False

                if cleared:
                    # Apply off-delay before transitioning
                    if config.off_delay_seconds > 0:
                        if channel not in self._off_delay_timers:
                            self._off_delay_timers[channel] = now
                        elapsed = now - self._off_delay_timers[channel]
                        if elapsed < config.off_delay_seconds:
                            # Still in off-delay, stay ACTIVE
                            return None
                        # Off-delay expired, clear the timer
                        self._off_delay_timers.pop(channel, None)

                    if state.acknowledged:
                        state.state = AlarmState.NORMAL
                        state.active_alarm_type = None
                        state.active_since = None
                        self._release_holds_for_channel(channel)
                    else:
                        state.state = AlarmState.RETURNED

            elif state.state == AlarmState.RETURNED:
                # Waiting for ack with condition cleared
                pass

            else:
                # Reset delay timer
                state.active_since = None

        return None

    def _execute_action(self, action: Union[str, Dict[str, Any]], channel: str, value: float):
        """Execute safety action. Supports both legacy string and dict formats."""
        if isinstance(action, str):
            self._execute_string_action(action, channel, value)
        elif isinstance(action, dict):
            self._execute_dict_action(action, channel, value)
        else:
            logger.warning(f"Unknown safety action type: {type(action)}")

    def _execute_string_action(self, action: str, channel: str, value: float):
        """Execute legacy string-format safety action (e.g., 'set:output_1:0')."""
        parts = action.split(':')

        if len(parts) == 3 and parts[0] == 'set':
            target_channel = parts[1]
            if self._output_channels and target_channel not in self._output_channels:
                logger.error(f"Safety action target '{target_channel}' is not a known output channel, ignoring action: {action}")
                return
            try:
                target_value = float(parts[2])
            except ValueError:
                logger.error(f"Invalid safety action value: {action}", exc_info=True)
                return

            logger.warning(f"Safety action: {target_channel} = {target_value} "
                          f"(triggered by {channel} = {value})")

            if self.on_action:
                try:
                    self.on_action(target_channel, action, target_value)
                except Exception as e:
                    logger.error(f"Safety action callback error: {e}", exc_info=True)

            self._safety_held_outputs[target_channel] = {
                'alarm_channel': channel,
                'action': action,
                'held_since': time.time()
            }
            logger.info(f"Output {target_channel} safety-held by alarm on {channel}")
        else:
            logger.warning(f"Unknown safety action format: {action}")

    def _execute_dict_action(self, action: Dict[str, Any], channel: str, value: float):
        """Execute dict-format safety action."""
        action_type = action.get('type', '')

        if action_type in ('set_digital_output', 'set_analog_output'):
            target_channel = action.get('channel')
            target_value = action.get('value', 0)
            if not target_channel:
                logger.error(f"Safety action missing 'channel': {action}")
                return
            if self._output_channels and target_channel not in self._output_channels:
                logger.error(f"Safety action target '{target_channel}' is not a known output channel")
                return

            logger.warning(f"Safety action: {target_channel} = {target_value} "
                          f"(triggered by {channel} = {value})")

            if self.on_action:
                try:
                    self.on_action(target_channel, str(action), float(target_value))
                except Exception as e:
                    logger.error(f"Safety action callback error: {e}", exc_info=True)

            self._safety_held_outputs[target_channel] = {
                'alarm_channel': channel,
                'action': action,
                'held_since': time.time()
            }

        elif action_type == 'stop_session':
            logger.warning(f"Safety action: STOP SESSION (triggered by {channel} = {value})")
            if self.on_stop_session:
                try:
                    self.on_stop_session()
                except Exception as e:
                    logger.error(f"Stop session callback error: {e}", exc_info=True)
        else:
            logger.warning(f"Unknown safety action type: {action_type}")

    # =========================================================================
    # ALARM SHELVING (ISA-18.2)
    # =========================================================================

    def shelve_alarm(self, channel: str, duration_s: float, operator: str = 'unknown') -> bool:
        """Shelve an alarm temporarily. Skips evaluation until duration expires or unshelved."""
        state = self._states.get(channel)
        if not state:
            return False

        now = time.time()
        state.pre_shelve_state = state.state
        state.state = AlarmState.SHELVED
        state.shelved_at = now
        state.shelved_by = operator
        state.shelve_expires_at = now + duration_s
        logger.info(f"Alarm shelved: {channel} for {duration_s}s by {operator}")
        return True

    def unshelve_alarm(self, channel: str) -> bool:
        """Remove shelving from an alarm. Restores previous state."""
        state = self._states.get(channel)
        if not state or state.state != AlarmState.SHELVED:
            return False

        state.state = state.pre_shelve_state or AlarmState.NORMAL
        state.shelved_at = None
        state.shelved_by = None
        state.shelve_expires_at = None
        state.pre_shelve_state = None
        logger.info(f"Alarm unshelved: {channel}")
        return True

    def set_out_of_service(self, channel: str, operator: str = 'unknown') -> bool:
        """Set alarm to out-of-service (disabled for maintenance). No auto-expiry."""
        state = self._states.get(channel)
        if not state:
            return False

        state.pre_shelve_state = state.state
        state.state = AlarmState.OUT_OF_SERVICE
        state.shelved_by = operator
        state.shelved_at = time.time()
        state.shelve_expires_at = None
        logger.info(f"Alarm set out-of-service: {channel} by {operator}")
        return True

    def return_to_service(self, channel: str) -> bool:
        """Return alarm from out-of-service to normal evaluation."""
        state = self._states.get(channel)
        if not state or state.state != AlarmState.OUT_OF_SERVICE:
            return False

        state.state = AlarmState.NORMAL
        state.active_alarm_type = None
        state.active_since = None
        state.acknowledged = False
        state.shelved_at = None
        state.shelved_by = None
        state.shelve_expires_at = None
        state.pre_shelve_state = None
        logger.info(f"Alarm returned to service: {channel}")
        return True

    def _check_shelve_expiry(self, now: float):
        """Auto-unshelve alarms whose shelve duration has expired."""
        for channel, state in list(self._states.items()):
            if (state.state == AlarmState.SHELVED
                    and state.shelve_expires_at is not None
                    and now >= state.shelve_expires_at):
                self.unshelve_alarm(channel)

    # =========================================================================
    # ACKNOWLEDGEMENT & QUERIES
    # =========================================================================

    def acknowledge(self, channel: str) -> bool:
        """Acknowledge alarm for channel."""
        state = self._states.get(channel)
        if not state:
            return False

        if state.state in (AlarmState.ACTIVE, AlarmState.RETURNED):
            state.acknowledged = True

            if state.state == AlarmState.RETURNED:
                # Condition already cleared, go to normal
                state.state = AlarmState.NORMAL
                state.active_alarm_type = None
                state.active_since = None
                self._release_holds_for_channel(channel)

            logger.info(f"Alarm acknowledged: {channel}")
            return True

        return False

    # Alias for compatibility (Opto22 node calls acknowledge_alarm)
    acknowledge_alarm = acknowledge

    def get_active_alarms(self) -> List[Dict[str, Any]]:
        """Get list of active alarms."""
        alarms = []

        for channel, state in self._states.items():
            if state.state != AlarmState.NORMAL:
                alarms.append({
                    'channel': channel,
                    'state': state.state.name,
                    'alarm_type': state.active_alarm_type,
                    'value': state.last_value,
                    'acknowledged': state.acknowledged,
                    'active_since': state.active_since,
                    'shelved_by': state.shelved_by,
                    'shelve_expires_at': state.shelve_expires_at,
                })

        return alarms

    def get_alarm_counts(self) -> Dict[str, int]:
        """Get alarm counts by state."""
        counts = {
            'active': 0,
            'acknowledged': 0,
            'returned': 0,
            'shelved': 0,
            'out_of_service': 0,
            'total': 0
        }

        for state in self._states.values():
            if state.state == AlarmState.ACTIVE:
                if state.acknowledged:
                    counts['acknowledged'] += 1
                else:
                    counts['active'] += 1
                counts['total'] += 1
            elif state.state == AlarmState.RETURNED:
                counts['returned'] += 1
                counts['total'] += 1
            elif state.state == AlarmState.SHELVED:
                counts['shelved'] += 1
            elif state.state == AlarmState.OUT_OF_SERVICE:
                counts['out_of_service'] += 1

        return counts

    # =========================================================================
    # SAFETY HOLD MANAGEMENT
    # =========================================================================

    def _release_holds_for_channel(self, alarm_channel: str):
        """Release all safety holds that were triggered by the given alarm channel."""
        released = []
        for output_ch, hold_info in list(self._safety_held_outputs.items()):
            if hold_info['alarm_channel'] == alarm_channel:
                released.append(output_ch)
                del self._safety_held_outputs[output_ch]
        if released:
            logger.info(f"Safety holds released for {released} (alarm {alarm_channel} cleared)")

    def is_safety_held(self, channel: str) -> bool:
        """Check if an output channel is held by a safety action."""
        return channel in self._safety_held_outputs

    def get_safety_hold_info(self, channel: str) -> Optional[Dict[str, Any]]:
        """Get safety hold details for an output channel, or None if not held."""
        return self._safety_held_outputs.get(channel)

    def get_all_safety_holds(self) -> Dict[str, Dict[str, Any]]:
        """Get all current safety holds. For status reporting."""
        return dict(self._safety_held_outputs)

    def is_interlock_held(self, channel: str) -> bool:
        """Check if an output channel is held by a tripped interlock."""
        return channel in self._interlock_held_outputs

    def is_output_blocked(self, channel: str) -> bool:
        """Check if output is blocked by EITHER alarm safety hold OR interlock trip."""
        return self.is_safety_held(channel) or self.is_interlock_held(channel)

    def get_output_block_reason(self, channel: str) -> Optional[str]:
        """Get human-readable reason why an output is blocked."""
        if channel in self._safety_held_outputs:
            info = self._safety_held_outputs[channel]
            return f"Safety-held by alarm on {info.get('alarm_channel', 'unknown')}"
        if channel in self._interlock_held_outputs:
            iid = self._interlock_held_outputs[channel]
            interlock = self._interlocks.get(iid)
            name = interlock.name if interlock else iid
            return f"Blocked by tripped interlock '{name}'"
        return None

    def clear_all(self):
        """Clear all alarm states (for testing/reset). Does NOT clear interlocks."""
        for state in self._states.values():
            state.state = AlarmState.NORMAL
            state.active_alarm_type = None
            state.active_since = None
            state.acknowledged = False
            state.shelved_at = None
            state.shelved_by = None
            state.shelve_expires_at = None
            state.pre_shelve_state = None
        self._safety_held_outputs.clear()
        self._off_delay_timers.clear()
        self._value_history.clear()
        self._roc_active.clear()

    # =========================================================================
    # INTERLOCK CONFIGURATION
    # =========================================================================

    def configure_interlocks(self, interlocks_data: List[Dict[str, Any]]):
        """Load interlocks from config push. Preserves latch/trip state for existing IDs."""
        # Snapshot runtime state BEFORE clearing (IEC 61511: trip state survives config update)
        prev_latch = self._latch_state
        prev_tripped = self._is_tripped
        prev_trip_time = getattr(self, '_last_trip_time', None)
        prev_trip_reason = getattr(self, '_last_trip_reason', None)
        prev_states = dict(self._interlock_prev_states)
        prev_executed = set(self._executed_actions)
        prev_held = dict(self._interlock_held_outputs)
        prev_ack = dict(self._trip_ack_state)
        prev_delay = dict(self._condition_delay_state)

        # Rebuild interlock definitions from new config
        self._interlocks.clear()
        for data in interlocks_data:
            try:
                interlock = Interlock.from_dict(data)
                self._interlocks[interlock.id] = interlock
            except Exception as e:
                logger.error(f"Failed to parse interlock: {e}")

        # Restore system-wide latch/trip state (independent of individual interlocks)
        self._latch_state = prev_latch
        self._is_tripped = prev_tripped
        if hasattr(self, '_last_trip_time'):
            self._last_trip_time = prev_trip_time
        if hasattr(self, '_last_trip_reason'):
            self._last_trip_reason = prev_trip_reason

        # Restore per-interlock state only for IDs that still exist
        surviving_ids = set(self._interlocks.keys())
        new_prev_states = {}
        for key, val in prev_states.items():
            # Keys are either interlock_id or "{interlock_id}_action"
            base_id = key.replace('_action', '') if key.endswith('_action') else key
            if base_id in surviving_ids:
                new_prev_states[key] = val
        self._interlock_prev_states = new_prev_states

        # Restore executed actions for surviving interlocks
        new_executed = set()
        for key in prev_executed:
            parts = key.split('-', 1)
            if parts[0] in surviving_ids:
                new_executed.add(key)
        self._executed_actions = new_executed

        # Restore held outputs for surviving interlocks
        new_held = {}
        for ch, iid in prev_held.items():
            if iid in surviving_ids:
                new_held[ch] = iid
        self._interlock_held_outputs = new_held

        # Restore ack state for surviving interlocks
        new_ack = {iid: ack for iid, ack in prev_ack.items() if iid in surviving_ids}
        self._trip_ack_state = new_ack

        # Restore delay state (condition IDs are stable across config pushes)
        self._condition_delay_state = prev_delay

        self._save_interlocks()
        logger.info(f"Configured {len(self._interlocks)} interlocks "
                    f"(latch={self._latch_state.value}, tripped={self._is_tripped})")

    def add_interlock(self, interlock: Interlock):
        """Add or update a single interlock."""
        self._interlocks[interlock.id] = interlock
        self._save_interlocks()

    def remove_interlock(self, interlock_id: str):
        """Remove an interlock by ID."""
        if interlock_id in self._interlocks:
            del self._interlocks[interlock_id]
            self._interlock_prev_states.pop(interlock_id, None)
            self._interlock_prev_states.pop(f"{interlock_id}_action", None)
            # Clean up per-interlock runtime state
            self._clear_interlock_action_tracking(interlock_id)
            self._trip_ack_state.pop(interlock_id, None)
            # Clean up condition delay state for this interlock's conditions
            delay_keys = [k for k in self._condition_delay_state
                          if k.startswith(interlock_id)]
            for k in delay_keys:
                del self._condition_delay_state[k]
            self._save_interlocks()

    # =========================================================================
    # INTERLOCK EVALUATION
    # =========================================================================

    def _evaluate_condition(self, cond: InterlockCondition,
                            channel_values: Dict[str, float],
                            now: float) -> Dict[str, Any]:
        """Evaluate a single interlock condition against current values.

        Returns dict with: satisfied (bool), current_value, reason (str)
        """
        result = {'satisfied': False, 'current_value': None, 'reason': ''}

        if cond.condition_type == 'channel_value':
            value = channel_values.get(cond.channel)
            if value is None:
                result['reason'] = f'Channel {cond.channel} has no value (OFFLINE?)'
                result['channel_offline'] = True
                return result
            if isinstance(value, float) and math.isnan(value):
                result['reason'] = f'Channel {cond.channel} has NaN value (OFFLINE?)'
                result['channel_offline'] = True
                return result
            satisfied = self._compare(value, cond.operator, cond.value)
            if cond.invert:
                satisfied = not satisfied
            result = {
                'satisfied': satisfied,
                'current_value': value,
                'reason': f'{cond.channel} = {value:.4g}'
            }

        elif cond.condition_type == 'digital_input':
            value = channel_values.get(cond.channel)
            if value is None:
                result['reason'] = f'Channel {cond.channel} has no value (OFFLINE?)'
                result['channel_offline'] = True
                return result
            if isinstance(value, float) and math.isnan(value):
                result['reason'] = f'Channel {cond.channel} has NaN value (OFFLINE?)'
                result['channel_offline'] = True
                return result
            raw_state = value != 0
            actual_state = not raw_state if cond.invert else raw_state
            expected = cond.value in (True, 1, 1.0)
            result = {
                'satisfied': actual_state == expected,
                'current_value': value,
                'reason': f'{cond.channel} = {"ON" if actual_state else "OFF"}'
            }

        elif cond.condition_type == 'alarm_active':
            # Satisfied when channel has NO active alarm
            ch_state = self._states.get(cond.channel)
            is_active = (ch_state is not None and
                         ch_state.state in (AlarmState.ACTIVE, AlarmState.RETURNED))
            result = {
                'satisfied': not is_active,
                'current_value': is_active,
                'reason': f'Alarm on {cond.channel} is {"active" if is_active else "clear"}'
            }

        elif cond.condition_type == 'no_active_alarms':
            active_count = sum(1 for s in self._states.values()
                               if s.state in (AlarmState.ACTIVE, AlarmState.RETURNED))
            result = {
                'satisfied': active_count == 0,
                'current_value': active_count,
                'reason': f'{active_count} active alarm(s)'
            }

        elif cond.condition_type == 'acquiring':
            result = {
                'satisfied': self._acquiring,
                'current_value': self._acquiring,
                'reason': 'Acquiring' if self._acquiring else 'Not acquiring'
            }

        else:
            # Unknown condition type — fail open (satisfied)
            result = {
                'satisfied': True,
                'current_value': None,
                'reason': f'Unknown condition type: {cond.condition_type}'
            }

        # Apply per-condition on-delay (condition must stay satisfied for delay_s
        # before reporting satisfied — prevents premature interlock clearing)
        if cond.delay_s > 0 and result['satisfied']:
            result = self._apply_condition_delay(cond.id, result, cond.delay_s, now)
        elif cond.delay_s > 0 and not result['satisfied']:
            # Condition unsatisfied — clear delay tracking
            self._condition_delay_state.pop(cond.id, None)

        return result

    @staticmethod
    def _compare(current: float, operator: str, threshold) -> bool:
        """Compare two values with the given operator."""
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return False
        if operator == '<':
            return current < threshold
        elif operator == '<=':
            return current <= threshold
        elif operator == '>':
            return current > threshold
        elif operator == '>=':
            return current >= threshold
        elif operator in ('=', '=='):
            return current == threshold
        elif operator in ('!=', '<>'):
            return current != threshold
        return False

    def _apply_condition_delay(self, cond_id: str, result: Dict[str, Any],
                                delay_s: float, now: float) -> Dict[str, Any]:
        """Apply on-delay logic to a condition result (for satisfied conditions).

        The condition must remain continuously satisfied for delay_s seconds
        before reporting as satisfied. This prevents premature interlock clearing
        from brief transient good readings.
        """
        delay_state = self._condition_delay_state.get(cond_id)

        if delay_state is None or not delay_state.get('met', False):
            # Start or continue delay timer
            start_time = delay_state.get('start', now) if delay_state else now
            elapsed = now - start_time

            if elapsed >= delay_s:
                # Delay elapsed — condition is truly satisfied
                self._condition_delay_state[cond_id] = {'start': start_time, 'met': True}
                return result
            else:
                # Still waiting — override to not-satisfied
                remaining = delay_s - elapsed
                self._condition_delay_state[cond_id] = {'start': start_time, 'met': False}
                return {**result, 'satisfied': False,
                        'delay_remaining': remaining,
                        'reason': f"{result['reason']} (waiting {remaining:.1f}s)"}
        else:
            # Already confirmed met — pass through
            return result

    def evaluate_interlock(self, interlock: Interlock,
                           channel_values: Dict[str, float],
                           now: float) -> Dict[str, Any]:
        """Evaluate a single interlock. Returns status dict."""
        if not interlock.enabled:
            return {'id': interlock.id, 'name': interlock.name,
                    'satisfied': True, 'enabled': False, 'bypassed': False,
                    'failed_conditions': [], 'priority': interlock.priority,
                    'sil_rating': interlock.sil_rating, 'demand_count': interlock.demand_count}

        # Check bypass expiry
        if (interlock.bypassed and interlock.max_bypass_duration
                and interlock.bypassed_at):
            if (now - interlock.bypassed_at) >= interlock.max_bypass_duration:
                interlock.bypassed = False
                interlock.bypassed_by = None
                interlock.bypassed_at = None
                logger.warning(f"Interlock '{interlock.name}' bypass expired")

        if interlock.bypassed:
            return {'id': interlock.id, 'name': interlock.name,
                    'satisfied': True, 'enabled': True, 'bypassed': True,
                    'bypassed_by': interlock.bypassed_by,
                    'failed_conditions': [], 'priority': interlock.priority,
                    'sil_rating': interlock.sil_rating, 'demand_count': interlock.demand_count}

        # Evaluate each condition
        failed = []
        results = []
        for cond in interlock.conditions:
            r = self._evaluate_condition(cond, channel_values, now)
            results.append(r['satisfied'])
            if not r['satisfied']:
                fail_info = {
                    'condition_id': cond.id,
                    'condition_type': cond.condition_type,
                    'channel': cond.channel,
                    'current_value': r.get('current_value'),
                    'reason': r.get('reason', '')
                }
                if r.get('channel_offline'):
                    fail_info['channel_offline'] = True
                failed.append(fail_info)

        if interlock.condition_logic == 'OR':
            satisfied = any(results) if results else True
            if satisfied:
                failed = []
        else:  # AND
            satisfied = all(results) if results else True

        # Track demand transitions (satisfied -> unsatisfied)
        # Use None default to avoid false demand count on first evaluation
        was_satisfied = self._interlock_prev_states.get(interlock.id)
        if was_satisfied is True and not satisfied:
            interlock.demand_count += 1
            interlock.last_demand_time = now
            logger.warning(f"Interlock '{interlock.name}' DEMAND #{interlock.demand_count}: "
                          f"conditions failed")
        self._interlock_prev_states[interlock.id] = satisfied

        has_offline = any(c.get('channel_offline') for c in failed)
        return {
            'id': interlock.id,
            'name': interlock.name,
            'satisfied': satisfied,
            'enabled': True,
            'bypassed': False,
            'failed_conditions': failed,
            'has_offline_channels': has_offline,
            'priority': interlock.priority,
            'sil_rating': interlock.sil_rating,
            'demand_count': interlock.demand_count,
        }

    def evaluate_all_interlocks(self, channel_values: Dict[str, float]) -> Dict[str, Any]:
        """Evaluate all interlocks. Called from check_all() after alarm evaluation.

        Returns status summary for MQTT publishing.
        """
        now = time.time()
        statuses = []
        any_failed = False

        for interlock in self._interlocks.values():
            status = self.evaluate_interlock(interlock, channel_values, now)
            statuses.append(status)

            if status['enabled'] and not status['satisfied'] and not status.get('bypassed'):
                any_failed = True
                # Execute trip actions for newly failed interlocks
                action_key = f"{interlock.id}_action"
                was_ok = self._interlock_prev_states.get(action_key, True)
                if was_ok:
                    self._execute_interlock_actions(interlock)
                self._interlock_prev_states[action_key] = False
            else:
                action_key = f"{interlock.id}_action"
                was_failed = not self._interlock_prev_states.get(action_key, True)
                if was_failed and not self._is_tripped:
                    # Interlock recovered and system is not tripped — clear action tracking.
                    # Do NOT release holds while system is TRIPPED (safety outputs must stay held
                    # until trip is explicitly reset by operator).
                    self._clear_interlock_action_tracking(interlock.id)
                self._interlock_prev_states[action_key] = True

        # Trip system if ARMED and any interlock failed
        if any_failed and self._latch_state == LatchState.ARMED and not self._is_tripped:
            failed_names = [s['name'] for s in statuses
                           if s['enabled'] and not s['satisfied'] and not s.get('bypassed')]
            self._trip_system(f"Interlock failed: {', '.join(failed_names)}")

        return {
            'latchState': self._latch_state.value,
            'isTripped': self._is_tripped,
            'lastTripTime': self._last_trip_time,
            'lastTripReason': self._last_trip_reason,
            'hasFailedInterlocks': any_failed,
            'interlockStatuses': statuses,
            'timestamp': now,
        }

    # =========================================================================
    # INTERLOCK TRIP SYSTEM
    # =========================================================================

    def _trip_system(self, reason: str):
        """Execute trip: set controlled outputs to their interlock-defined values.

        This is NOT a blanket safe state. Each failed interlock controls
        specific outputs with specific values.
        """
        logger.critical(f"SYSTEM TRIP: {reason}")
        self._is_tripped = True
        self._last_trip_time = time.time()
        self._last_trip_reason = reason
        self._latch_state = LatchState.TRIPPED

        # Execute per-interlock trip actions for failed interlocks
        for interlock in self._interlocks.values():
            if not interlock.enabled or interlock.bypassed:
                continue
            if not self._interlock_prev_states.get(interlock.id, True):
                # This interlock has failed — execute its specific actions
                self._execute_interlock_actions(interlock)

        if self.on_publish:
            try:
                self.on_publish('safety/trip', {
                    'reason': reason,
                    'timestamp': self._last_trip_time,
                    'latchState': self._latch_state.value,
                })
            except Exception as e:
                logger.error(f"Failed to publish trip event: {e}")

        self._save_interlocks()

    def _execute_interlock_actions(self, interlock: Interlock):
        """Execute the control actions for a failed interlock."""
        for control in interlock.controls:
            action_key = f"{interlock.id}-{control.control_type}-{control.channel or ''}"
            if action_key in self._executed_actions:
                continue  # Already executed

            if control.control_type in ('set_digital_output', 'set_analog_output'):
                if control.channel and self.on_interlock_action:
                    value = control.set_value if control.set_value is not None else 0.0
                    logger.warning(f"INTERLOCK '{interlock.name}': "
                                 f"Setting {control.channel} = {value}")
                    try:
                        self.on_interlock_action(control.channel, interlock.name, value)
                    except Exception as e:
                        logger.error(f"Interlock action failed for {control.channel}: {e}")
                    self._interlock_held_outputs[control.channel] = interlock.id
                    self._executed_actions.add(action_key)

            elif control.control_type == 'stop_session':
                logger.warning(f"INTERLOCK '{interlock.name}': Stopping session")
                if self.on_stop_session:
                    try:
                        self.on_stop_session()
                    except Exception as e:
                        logger.error(f"Stop session failed: {e}")
                    self._executed_actions.add(action_key)

    def _clear_interlock_action_tracking(self, interlock_id: str):
        """Clear executed action tracking when interlock recovers."""
        keys_to_remove = [k for k in self._executed_actions if k.startswith(f"{interlock_id}-")]
        for k in keys_to_remove:
            self._executed_actions.discard(k)
        # Release held outputs for this interlock
        held = [ch for ch, iid in list(self._interlock_held_outputs.items())
                if iid == interlock_id]
        for ch in held:
            del self._interlock_held_outputs[ch]
            logger.info(f"Interlock hold released: {ch} (interlock {interlock_id} recovered)")

    # =========================================================================
    # LATCH STATE MACHINE
    # =========================================================================

    def arm_latch(self, user: str = "system") -> Tuple[bool, str]:
        """Arm the safety system. Only allowed when no interlocks are failed and not tripped."""
        if self._is_tripped:
            msg = "Cannot arm: system is tripped"
            logger.warning(msg)
            return False, msg

        # Check no interlocks are currently failed
        for interlock in self._interlocks.values():
            if interlock.enabled and not interlock.bypassed:
                if not self._interlock_prev_states.get(interlock.id, True):
                    msg = f"Cannot arm: interlock '{interlock.name}' is failed"
                    logger.warning(msg)
                    return False, msg

        self._latch_state = LatchState.ARMED
        msg = f"Safety latch ARMED by {user}"
        logger.info(msg)
        if self.on_publish:
            try:
                self.on_publish('safety/latch/state', {
                    'state': 'armed', 'user': user, 'timestamp': time.time()
                })
            except Exception:
                pass
        return True, msg

    def disarm_latch(self, user: str = "system") -> Tuple[bool, str]:
        """Disarm the safety system. Refuses if system is tripped (must reset first)."""
        if self._is_tripped:
            msg = "Cannot disarm: system is tripped (reset trip first)"
            logger.warning(msg)
            return False, msg
        self._latch_state = LatchState.SAFE
        msg = f"Safety latch DISARMED by {user}"
        logger.info(msg)
        if self.on_publish:
            try:
                self.on_publish('safety/latch/state', {
                    'state': 'safe', 'user': user, 'timestamp': time.time()
                })
            except Exception:
                pass
        return True, msg

    def reset_trip(self, user: str = "system") -> Tuple[bool, str]:
        """Reset after trip. Only allowed when all interlocks are satisfied."""
        if not self._is_tripped:
            msg = "Cannot reset: system is not tripped"
            logger.warning(msg)
            return False, msg

        for interlock in self._interlocks.values():
            if interlock.enabled and not interlock.bypassed:
                if not self._interlock_prev_states.get(interlock.id, True):
                    msg = f"Cannot reset: interlock '{interlock.name}' still failed"
                    logger.warning(msg)
                    return False, msg

        self._is_tripped = False
        self._last_trip_reason = None
        self._latch_state = LatchState.SAFE
        self._executed_actions.clear()
        self._interlock_held_outputs.clear()
        self._trip_ack_state.clear()
        msg = f"Trip RESET by {user}"
        logger.info(msg)

        if self.on_publish:
            try:
                self.on_publish('safety/latch/state', {
                    'state': 'safe', 'user': user, 'timestamp': time.time(),
                    'event': 'trip_reset'
                })
            except Exception:
                pass

        self._save_interlocks()
        return True, msg

    def acknowledge_trip(self, interlock_id: str, user: str) -> bool:
        """Acknowledge a tripped interlock (audit trail only, does NOT reset)."""
        interlock = self._interlocks.get(interlock_id)
        if not interlock:
            return False

        self._trip_ack_state[interlock_id] = {
            'acknowledged': True,
            'user': user,
            'timestamp': time.time()
        }
        logger.info(f"Trip acknowledged for '{interlock.name}' by {user}")
        return True

    def bypass_interlock(self, interlock_id: str, bypass: bool,
                         user: str, reason: str = "",
                         max_duration_s: Optional[float] = None) -> Tuple[bool, str]:
        """Bypass or un-bypass an interlock."""
        interlock = self._interlocks.get(interlock_id)
        if not interlock:
            msg = f"Bypass failed: interlock '{interlock_id}' not found"
            logger.warning(msg)
            return False, msg
        if bypass and not interlock.bypass_allowed:
            msg = f"Bypass not allowed for interlock '{interlock.name}'"
            logger.warning(msg)
            return False, msg

        interlock.bypassed = bypass
        if bypass:
            interlock.bypassed_by = user
            interlock.bypassed_at = time.time()
            if max_duration_s is not None:
                interlock.max_bypass_duration = max_duration_s
            msg = (f"Interlock '{interlock.name}' BYPASSED by {user}"
                   f"{f' reason: {reason}' if reason else ''}")
            logger.info(msg)
        else:
            interlock.bypassed_by = None
            interlock.bypassed_at = None
            msg = f"Interlock '{interlock.name}' UN-BYPASSED by {user}"
            logger.info(msg)

        self._save_interlocks()
        return True, msg

    def record_proof_test(self, interlock_id: str, user: str = "system") -> bool:
        """Record a proof test for an interlock (IEC 61511)."""
        interlock = self._interlocks.get(interlock_id)
        if not interlock:
            return False
        interlock.last_proof_test = time.time()
        logger.info(f"Proof test recorded for '{interlock.name}' by {user}")
        self._save_interlocks()
        return True

    @property
    def latch_state(self) -> LatchState:
        return self._latch_state

    @property
    def is_tripped(self) -> bool:
        return self._is_tripped

    def get_interlock_status(self) -> Dict[str, Any]:
        """Get current interlock status summary."""
        if self._interlock_status:
            return self._interlock_status
        return {
            'latchState': self._latch_state.value,
            'isTripped': self._is_tripped,
            'lastTripTime': self._last_trip_time,
            'lastTripReason': self._last_trip_reason,
            'hasFailedInterlocks': False,
            'interlockStatuses': [],
            'timestamp': time.time(),
        }

    # =========================================================================
    # ALARM FLOOD DETECTION (ISA-18.2)
    # =========================================================================

    def _check_flood(self, event: AlarmEvent, now: float):
        """Track alarm rate and detect flood conditions."""
        self._alarm_timestamps.append(now)

        # Prune timestamps outside window
        cutoff = now - self.FLOOD_WINDOW_S
        self._alarm_timestamps = [t for t in self._alarm_timestamps if t >= cutoff]

        alarm_rate = len(self._alarm_timestamps)

        if not self._flood_active:
            if alarm_rate >= self.FLOOD_THRESHOLD:
                # Flood detected
                self._flood_active = True
                self._flood_start_time = now
                self._flood_first_alarm = {
                    'channel': event.channel,
                    'alarm_type': event.alarm_type,
                    'value': event.value,
                    'limit': event.limit,
                    'timestamp': event.timestamp,
                }
                logger.critical(
                    f"ALARM FLOOD DETECTED: {alarm_rate} alarms in {self.FLOOD_WINDOW_S}s. "
                    f"First-out: {event.channel} ({event.alarm_type})")

                if self.on_publish:
                    try:
                        self.on_publish('safety/alarm_flood', {
                            'active': True,
                            'rate': alarm_rate,
                            'window_s': self.FLOOD_WINDOW_S,
                            'first_alarm': self._flood_first_alarm,
                            'timestamp': now,
                        })
                    except Exception:
                        pass
        else:
            # Check if flood has cleared
            clear_threshold = int(self.FLOOD_THRESHOLD * self.FLOOD_CLEAR_RATIO)
            if alarm_rate <= clear_threshold:
                duration = now - (self._flood_start_time or now)
                logger.info(f"Alarm flood cleared after {duration:.1f}s "
                           f"(rate dropped to {alarm_rate})")
                self._flood_active = False
                self._flood_first_alarm = None
                self._flood_start_time = None

                if self.on_publish:
                    try:
                        self.on_publish('safety/alarm_flood', {
                            'active': False,
                            'rate': alarm_rate,
                            'duration_s': duration,
                            'timestamp': now,
                        })
                    except Exception:
                        pass

    def _should_suppress_alarm(self, event: AlarmEvent) -> bool:
        """During flood, suppress non-CRITICAL alarms."""
        if not self._flood_active:
            return False
        return event.severity != AlarmSeverity.CRITICAL

    @property
    def is_alarm_flood_active(self) -> bool:
        return self._flood_active

    def get_flood_status(self) -> Dict[str, Any]:
        """Get current flood status for MQTT publishing."""
        return {
            'active': self._flood_active,
            'first_alarm': self._flood_first_alarm,
            'alarm_rate': len(self._alarm_timestamps),
            'flood_start_time': self._flood_start_time,
        }

    # =========================================================================
    # CONFIGURABLE SAFE STATE
    # =========================================================================

    def configure_safe_state(self, config_data: Dict[str, Any]):
        """Update safe state configuration."""
        self._safe_state_config = SafeStateConfig.from_dict(config_data)
        self._save_safe_state_config()
        logger.info(f"Safe state configured: {len(self._safe_state_config.channel_safe_values)} channels")

    def get_safe_state_config(self) -> SafeStateConfig:
        """Get current safe state config."""
        return self._safe_state_config

    def get_channel_safe_value(self, channel: str, default_value: float = 0.0) -> float:
        """Get the safe value for a specific channel.

        Priority: SafeStateConfig.channel_safe_values > default_value param > 0.0
        """
        if channel in self._safe_state_config.channel_safe_values:
            return self._safe_state_config.channel_safe_values[channel]
        return default_value

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _atomic_write(self, path: str, data: Any):
        """Write JSON data atomically (write to .tmp then rename)."""
        tmp_path = path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(data, f)
            # On Windows, os.replace is atomic within the same volume
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Atomic write failed for {path}: {e}")
            # Clean up tmp file
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _load_persisted_state(self):
        """Load all persisted state from disk at startup."""
        if not self._data_dir:
            return
        data_path = Path(self._data_dir)

        # Load alarm configs
        try:
            path = data_path / 'alarm_configs.json'
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                for ch_name, cfg_data in data.items():
                    self.configure_from_dict(ch_name, cfg_data)
                logger.info(f"Loaded {len(data)} alarm configs from disk")
        except Exception as e:
            logger.error(f"Failed to load alarm configs: {e}")

        # Load active alarm states
        try:
            path = data_path / 'alarm_states.json'
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                for ch_name, state_data in data.items():
                    state = self._states.get(ch_name)
                    if not state:
                        state = ChannelAlarmState()
                        self._states[ch_name] = state
                    try:
                        state.state = AlarmState[state_data.get('state', 'NORMAL')]
                    except KeyError:
                        state.state = AlarmState.NORMAL
                    state.active_alarm_type = state_data.get('active_alarm_type')
                    state.active_since = state_data.get('active_since')
                    state.last_value = state_data.get('last_value', 0.0)
                    state.acknowledged = state_data.get('acknowledged', False)
                logger.info(f"Loaded {len(data)} alarm states from disk")
        except Exception as e:
            logger.error(f"Failed to load alarm states: {e}")

        # Load alarm history
        try:
            path = data_path / 'alarm_history.json'
            if path.exists():
                with open(path, 'r') as f:
                    self._alarm_history = json.load(f)
                logger.info(f"Loaded {len(self._alarm_history)} alarm history entries")
        except Exception as e:
            logger.error(f"Failed to load alarm history: {e}")

        # Load interlocks
        try:
            path = data_path / 'interlocks.json'
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                for d in data:
                    try:
                        interlock = Interlock.from_dict(d)
                        self._interlocks[interlock.id] = interlock
                    except Exception as ie:
                        logger.error(f"Failed to parse persisted interlock: {ie}")
                logger.info(f"Loaded {len(self._interlocks)} interlocks from disk")
        except Exception as e:
            logger.error(f"Failed to load interlocks: {e}")

        # Load safe state config
        try:
            path = data_path / 'safe_state_config.json'
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                self._safe_state_config = SafeStateConfig.from_dict(data)
                logger.info(f"Loaded safe state config: "
                           f"{len(self._safe_state_config.channel_safe_values)} channels")
        except Exception as e:
            logger.error(f"Failed to load safe state config: {e}")

    def _save_alarm_configs(self):
        """Persist alarm configs to disk."""
        if not self._data_dir:
            return
        try:
            path = str(Path(self._data_dir) / 'alarm_configs.json')
            data = {}
            for ch_name, config in self._configs.items():
                data[ch_name] = {
                    'alarm_enabled': config.enabled,
                    'hihi_limit': config.hihi_limit,
                    'hi_limit': config.hi_limit,
                    'lo_limit': config.lo_limit,
                    'lolo_limit': config.lolo_limit,
                    'alarm_deadband': config.deadband,
                    'alarm_delay_sec': config.delay_seconds,
                    'alarm_off_delay_sec': config.off_delay_seconds,
                    'rate_of_change_limit': config.rate_of_change_limit,
                    'rate_of_change_period_s': config.rate_of_change_period_s,
                    'safety_action': config.safety_action,
                }
            self._atomic_write(path, data)
        except Exception as e:
            logger.error(f"Failed to save alarm configs: {e}")

    def _save_alarm_states(self):
        """Persist active alarm states to disk (for crash recovery)."""
        if not self._data_dir:
            return
        try:
            path = str(Path(self._data_dir) / 'alarm_states.json')
            data = {}
            for ch_name, state in self._states.items():
                if state.state != AlarmState.NORMAL:
                    data[ch_name] = {
                        'state': state.state.name,
                        'active_alarm_type': state.active_alarm_type,
                        'active_since': state.active_since,
                        'last_value': state.last_value,
                        'acknowledged': state.acknowledged,
                    }
            self._atomic_write(path, data)
        except Exception as e:
            logger.error(f"Failed to save alarm states: {e}")

    def _record_alarm_history(self, event: AlarmEvent):
        """Record alarm event to in-memory history and persist periodically."""
        entry = {
            'channel': event.channel,
            'alarm_type': event.alarm_type,
            'value': event.value,
            'limit': event.limit,
            'severity': event.severity.name,
            'state': event.state.name,
            'timestamp': event.timestamp,
        }
        self._alarm_history.append(entry)
        if len(self._alarm_history) > self._max_alarm_history:
            self._alarm_history = self._alarm_history[-self._max_alarm_history:]

        # Save every 10 events to avoid excessive disk writes
        if len(self._alarm_history) % 10 == 0:
            self._save_alarm_history()

    def _save_alarm_history(self):
        """Persist alarm history to disk."""
        if not self._data_dir:
            return
        try:
            path = str(Path(self._data_dir) / 'alarm_history.json')
            self._atomic_write(path, self._alarm_history[-self._max_alarm_history:])
        except Exception as e:
            logger.error(f"Failed to save alarm history: {e}")

    def _save_interlocks(self):
        """Persist interlocks to disk (includes bypass/demand state)."""
        if not self._data_dir:
            return
        try:
            path = str(Path(self._data_dir) / 'interlocks.json')
            data = [i.to_dict() for i in self._interlocks.values()]
            self._atomic_write(path, data)
        except Exception as e:
            logger.error(f"Failed to save interlocks: {e}")

    def _save_safe_state_config(self):
        """Persist safe state config to disk."""
        if not self._data_dir:
            return
        try:
            path = str(Path(self._data_dir) / 'safe_state_config.json')
            self._atomic_write(path, self._safe_state_config.to_dict())
        except Exception as e:
            logger.error(f"Failed to save safe state config: {e}")

    def save_all(self):
        """Save all state to disk. Called on shutdown."""
        self._save_alarm_configs()
        self._save_alarm_states()
        self._save_alarm_history()
        self._save_interlocks()
        self._save_safe_state_config()

    def get_alarm_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alarm history entries (most recent first)."""
        return list(reversed(self._alarm_history[-limit:]))
