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
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
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


class SafetyManager:
    """
    Single-pass safety checking with ISA-18.2 alarm management.

    Usage:
        safety = SafetyManager()
        safety.configure('temp_1', AlarmConfig(...))

        # In main loop:
        events = safety.check_all(channel_values)
        for event in events:
            # Handle event (publish, trigger action)
    """

    def __init__(self):
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

    def check_all(self, channel_values: Dict[str, float]) -> List[AlarmEvent]:
        """
        Check all channels for alarm conditions.

        Args:
            channel_values: {channel_name: value}

        Returns:
            List of new alarm events
        """
        events = []
        now = time.time()

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
                events.append(event)

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
                    events.append(roc_event)
                    if self.on_alarm:
                        try:
                            self.on_alarm(roc_event)
                        except Exception as e:
                            logger.error(f"ROC alarm callback error: {e}", exc_info=True)
                    if config.safety_action:
                        self._execute_action(config.safety_action, channel, value)

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
        for channel, state in self._states.items():
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

    def clear_all(self):
        """Clear all alarm states (for testing/reset)."""
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
