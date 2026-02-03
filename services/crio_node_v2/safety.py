"""
Safety Module for cRIO Node V2

Provides single-pass safety checking with:
- Configurable alarm limits (HIHI, HI, LO, LOLO)
- Safety actions (set outputs on alarm)
- Alarm state tracking
- Event publishing
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger('cRIONode')


class AlarmSeverity(Enum):
    """Alarm severity levels."""
    NONE = 0
    WARNING = 1     # HI or LO
    CRITICAL = 2    # HIHI or LOLO


class AlarmState(Enum):
    """Alarm state machine states."""
    NORMAL = 0
    ACTIVE = 1
    ACKNOWLEDGED = 2
    RETURNED = 3  # Condition cleared but not acknowledged


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
    safety_action: Optional[str] = None  # e.g., "set:output_1:0"


@dataclass
class AlarmEvent:
    """Alarm event record."""
    channel: str
    alarm_type: str  # 'hihi', 'hi', 'lo', 'lolo'
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


class SafetyManager:
    """
    Single-pass safety checking.

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

        # Callback for alarm events
        self.on_alarm: Optional[Callable[[AlarmEvent], None]] = None

        # Callback for safety actions
        self.on_action: Optional[Callable[[str, str, float], None]] = None

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
        config = AlarmConfig(
            channel=channel,
            enabled=data.get('alarm_enabled', True),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
            deadband=data.get('alarm_deadband', 0.0),
            delay_seconds=data.get('alarm_delay_sec', 0.0),
            safety_action=data.get('safety_action')
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

        for channel, value in channel_values.items():
            config = self._configs.get(channel)
            if not config or not config.enabled:
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

        return events

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
            # Alarm condition present
            if state.state == AlarmState.NORMAL:
                # New alarm - check delay
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
            # No alarm condition - apply deadband
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
                    if state.acknowledged:
                        state.state = AlarmState.NORMAL
                        state.active_alarm_type = None
                        state.active_since = None
                    else:
                        state.state = AlarmState.RETURNED

            elif state.state == AlarmState.RETURNED:
                # Waiting for ack with condition cleared
                pass

            else:
                # Reset delay timer
                state.active_since = None

        return None

    def _execute_action(self, action: str, channel: str, value: float):
        """Execute safety action."""
        # Parse action string (e.g., "set:output_1:0")
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
        else:
            logger.warning(f"Unknown safety action format: {action}")

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

            logger.info(f"Alarm acknowledged: {channel}")
            return True

        return False

    def get_active_alarms(self) -> List[Dict[str, Any]]:
        """Get list of active alarms."""
        alarms = []

        for channel, state in self._states.items():
            if state.state != AlarmState.NORMAL:
                config = self._configs.get(channel)
                alarms.append({
                    'channel': channel,
                    'state': state.state.name,
                    'alarm_type': state.active_alarm_type,
                    'value': state.last_value,
                    'acknowledged': state.acknowledged,
                    'active_since': state.active_since
                })

        return alarms

    def get_alarm_counts(self) -> Dict[str, int]:
        """Get alarm counts by state."""
        counts = {
            'active': 0,
            'acknowledged': 0,
            'returned': 0,
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

        return counts

    def clear_all(self):
        """Clear all alarm states (for testing/reset)."""
        for state in self._states.values():
            state.state = AlarmState.NORMAL
            state.active_alarm_type = None
            state.active_since = None
            state.acknowledged = False
