"""
Watchdog Engine - Monitors channels for abnormal conditions

Watchdog condition types:
- stale_data: Channel hasn't updated for too long
- out_of_range: Value outside min/max limits
- rate_exceeded: Rate of change too fast
- stuck_value: Value hasn't changed (sensor failure)

Actions:
- notification: Show notification in UI
- alarm: Raise an alarm
- setOutput: Set a digital/analog output
- stopSequence: Stop a running sequence
- stopRecording: Stop recording
- runSequence: Start a sequence (e.g., safe shutdown)

Usage:
    engine = WatchdogEngine()
    engine.load_from_project(project_data)

    # In scan loop:
    engine.process_scan(channel_values, channel_timestamps)
"""

import logging
import threading
import time
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger(__name__)


class AutomationRunMode(Enum):
    """When automation should be active (acquisition must be running for any mode)"""
    ACQUISITION = "acquisition"  # Active when acquiring data
    SESSION = "session"          # Active only during test session (subset of acquisition)


class WatchdogConditionType(Enum):
    STALE_DATA = "stale_data"
    OUT_OF_RANGE = "out_of_range"
    RATE_EXCEEDED = "rate_exceeded"
    STUCK_VALUE = "stuck_value"


class WatchdogActionType(Enum):
    NOTIFICATION = "notification"
    ALARM = "alarm"
    SET_OUTPUT = "setOutput"
    STOP_SEQUENCE = "stopSequence"
    STOP_RECORDING = "stopRecording"
    RUN_SEQUENCE = "runSequence"


@dataclass
class WatchdogCondition:
    """Condition for triggering a watchdog"""
    condition_type: WatchdogConditionType
    # For stale_data
    max_stale_ms: int = 5000
    # For out_of_range
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    # For rate_exceeded
    max_rate_per_min: Optional[float] = None
    # For stuck_value
    stuck_duration_ms: int = 30000
    stuck_tolerance: float = 0.001

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WatchdogCondition':
        condition_type = WatchdogConditionType(data.get('type', 'stale_data'))

        return WatchdogCondition(
            condition_type=condition_type,
            max_stale_ms=data.get('maxStaleMs', 5000),
            min_value=data.get('minValue'),
            max_value=data.get('maxValue'),
            max_rate_per_min=data.get('maxRatePerMin'),
            stuck_duration_ms=data.get('stuckDurationMs', 30000),
            stuck_tolerance=data.get('stuckTolerance', 0.001)
        )


@dataclass
class WatchdogAction:
    """Action to execute when watchdog triggers"""
    action_type: WatchdogActionType
    message: Optional[str] = None
    channel: Optional[str] = None
    value: Optional[float] = None
    sequence_id: Optional[str] = None
    alarm_severity: str = "warning"  # 'info', 'warning', 'critical'

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WatchdogAction':
        return WatchdogAction(
            action_type=WatchdogActionType(data.get('type', 'notification')),
            message=data.get('message'),
            channel=data.get('channel'),
            value=data.get('value'),
            sequence_id=data.get('sequenceId'),
            alarm_severity=data.get('alarmSeverity', 'warning')
        )


@dataclass
class Watchdog:
    """Complete watchdog definition"""
    id: str
    name: str
    description: str
    enabled: bool
    channels: List[str]
    condition: WatchdogCondition
    actions: List[WatchdogAction]
    recovery_actions: List[WatchdogAction] = field(default_factory=list)
    auto_recover: bool = True
    cooldown_ms: int = 10000
    run_mode: AutomationRunMode = AutomationRunMode.ACQUISITION  # When to be active
    # Runtime state
    is_triggered: bool = False
    triggered_at: Optional[float] = None
    triggered_channels: List[str] = field(default_factory=list)
    last_triggered: Optional[float] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Watchdog':
        condition = WatchdogCondition.from_dict(data.get('condition', {}))
        actions = [WatchdogAction.from_dict(a) for a in data.get('actions', [])]
        recovery_actions = [WatchdogAction.from_dict(a) for a in data.get('recoveryActions', [])]

        # Parse run mode (default to acquisition for backward compatibility)
        run_mode_str = data.get('runMode', 'acquisition')
        try:
            run_mode = AutomationRunMode(run_mode_str)
        except ValueError:
            run_mode = AutomationRunMode.ACQUISITION

        return Watchdog(
            id=data.get('id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            enabled=data.get('enabled', True),
            channels=data.get('channels', []),
            condition=condition,
            actions=actions,
            recovery_actions=recovery_actions,
            auto_recover=data.get('autoRecover', True),
            cooldown_ms=data.get('cooldownMs', 10000),
            run_mode=run_mode,
            is_triggered=data.get('isTriggered', False),
            triggered_at=data.get('triggeredAt'),
            triggered_channels=data.get('triggeredChannels', [])
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'channels': self.channels,
            'runMode': self.run_mode.value,
            'isTriggered': self.is_triggered,
            'triggeredAt': self.triggered_at,
            'triggeredChannels': self.triggered_channels,
            'lastTriggered': self.last_triggered
        }


@dataclass
class ChannelTracker:
    """Track channel state for watchdog evaluation"""
    last_value: Optional[float] = None
    last_update_time: Optional[float] = None
    stuck_since: Optional[float] = None
    rate_history: List[tuple] = field(default_factory=list)  # [(time, value), ...]


class WatchdogEngine:
    """
    Backend watchdog monitoring engine.

    Monitors channels for abnormal conditions and executes actions.
    """

    def __init__(self):
        self.watchdogs: Dict[str, Watchdog] = {}
        self.channel_trackers: Dict[str, ChannelTracker] = {}
        self.lock = threading.Lock()

        # Callbacks for actions
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.start_recording: Optional[Callable[[], None]] = None
        self.stop_recording: Optional[Callable[[], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self.raise_alarm: Optional[Callable[[str, str, str], None]] = None

        # System state tracking
        self._is_acquiring: bool = False
        self._is_session_active: bool = False

    def on_acquisition_start(self):
        """Called when acquisition starts"""
        self._is_acquiring = True
        logger.debug("Watchdog engine: acquisition started")

    def on_acquisition_stop(self):
        """Called when acquisition stops"""
        self._is_acquiring = False
        logger.debug("Watchdog engine: acquisition stopped")

    def on_session_start(self):
        """Called when test session starts"""
        self._is_session_active = True
        logger.debug("Watchdog engine: session started")

    def on_session_stop(self):
        """Called when test session stops"""
        self._is_session_active = False
        logger.debug("Watchdog engine: session stopped")

    def _is_watchdog_active(self, wd: Watchdog) -> bool:
        """Check if watchdog should be active based on its run_mode.

        Note: Nothing runs if acquisition isn't active - acquisition is the base requirement.
        """
        if not self._is_acquiring:
            return False

        if wd.run_mode == AutomationRunMode.ACQUISITION:
            return True  # Active whenever acquiring
        elif wd.run_mode == AutomationRunMode.SESSION:
            return self._is_session_active  # Active only during session (subset of acquisition)
        return False

    def load_from_project(self, project_data: Dict[str, Any]) -> int:
        """
        Load watchdogs from project data.

        Args:
            project_data: Project JSON with scripts.watchdogs array

        Returns:
            Number of watchdogs loaded
        """
        with self.lock:
            self.watchdogs.clear()
            self.channel_trackers.clear()

            scripts_data = project_data.get('scripts', {})
            watchdogs_data = scripts_data.get('watchdogs', [])

            if not watchdogs_data:
                logger.debug("No watchdogs found in project")
                return 0

            for wd_data in watchdogs_data:
                try:
                    wd = Watchdog.from_dict(wd_data)
                    self.watchdogs[wd.id] = wd

                    # Initialize trackers for channels
                    for ch in wd.channels:
                        if ch not in self.channel_trackers:
                            self.channel_trackers[ch] = ChannelTracker()

                    logger.debug(f"Loaded watchdog: {wd.name} ({wd.condition.condition_type.value})")
                except Exception as e:
                    logger.error(f"Failed to load watchdog: {e}")

            logger.info(f"Loaded {len(self.watchdogs)} watchdogs from project")
            return len(self.watchdogs)

    def clear(self):
        """Clear all watchdogs"""
        with self.lock:
            self.watchdogs.clear()
            self.channel_trackers.clear()
            logger.info("Cleared all watchdogs")

    def process_scan(self, channel_values: Dict[str, float],
                     channel_timestamps: Dict[str, float] = None):
        """
        Process all watchdogs for the current scan.

        Called every scan from the DAQ loop.

        Args:
            channel_values: Current channel values
            channel_timestamps: Last update times per channel (optional)
        """
        if channel_timestamps is None:
            channel_timestamps = {}

        now = time.time()

        # Update channel trackers
        for channel, value in channel_values.items():
            if channel not in self.channel_trackers:
                self.channel_trackers[channel] = ChannelTracker()

            tracker = self.channel_trackers[channel]
            timestamp = channel_timestamps.get(channel, now)

            # Update rate history (keep last 60 seconds)
            tracker.rate_history.append((now, value))
            cutoff = now - 60
            tracker.rate_history = [(t, v) for t, v in tracker.rate_history if t >= cutoff]

            # Track stuck value
            if tracker.last_value is not None:
                if abs(value - tracker.last_value) <= 0.001:  # Small tolerance
                    if tracker.stuck_since is None:
                        tracker.stuck_since = now
                else:
                    tracker.stuck_since = None
            else:
                tracker.stuck_since = None

            tracker.last_value = value
            tracker.last_update_time = timestamp

        with self.lock:
            for wd in self.watchdogs.values():
                if not wd.enabled:
                    continue

                # Check if watchdog should be active based on run_mode
                if not self._is_watchdog_active(wd):
                    continue

                triggered_channels = self._evaluate_watchdog(wd, channel_values, now)

                if triggered_channels:
                    if not wd.is_triggered:
                        # Check cooldown
                        if wd.last_triggered:
                            elapsed = (now - wd.last_triggered) * 1000
                            if elapsed < wd.cooldown_ms:
                                continue

                        # Trigger!
                        self._trigger_watchdog(wd, triggered_channels, now)

                elif wd.is_triggered and wd.auto_recover:
                    # Condition cleared - recover
                    self._recover_watchdog(wd, now)

    def _evaluate_watchdog(self, wd: Watchdog, channel_values: Dict[str, float],
                          now: float) -> List[str]:
        """
        Evaluate watchdog condition.

        Returns list of channels that triggered the condition (empty if OK).
        """
        triggered = []
        cond = wd.condition

        for channel in wd.channels:
            if channel not in channel_values:
                continue

            tracker = self.channel_trackers.get(channel)
            if not tracker:
                continue

            value = channel_values[channel]

            if cond.condition_type == WatchdogConditionType.STALE_DATA:
                if tracker.last_update_time:
                    age_ms = (now - tracker.last_update_time) * 1000
                    if age_ms > cond.max_stale_ms:
                        triggered.append(channel)

            elif cond.condition_type == WatchdogConditionType.OUT_OF_RANGE:
                if not math.isnan(value):
                    if cond.min_value is not None and value < cond.min_value:
                        triggered.append(channel)
                    elif cond.max_value is not None and value > cond.max_value:
                        triggered.append(channel)

            elif cond.condition_type == WatchdogConditionType.RATE_EXCEEDED:
                if cond.max_rate_per_min and len(tracker.rate_history) >= 2:
                    # Calculate rate over last few samples
                    if len(tracker.rate_history) >= 2:
                        old_t, old_v = tracker.rate_history[0]
                        new_t, new_v = tracker.rate_history[-1]
                        if new_t > old_t:
                            rate_per_sec = abs(new_v - old_v) / (new_t - old_t)
                            rate_per_min = rate_per_sec * 60
                            if rate_per_min > cond.max_rate_per_min:
                                triggered.append(channel)

            elif cond.condition_type == WatchdogConditionType.STUCK_VALUE:
                if tracker.stuck_since:
                    stuck_ms = (now - tracker.stuck_since) * 1000
                    if stuck_ms > cond.stuck_duration_ms:
                        triggered.append(channel)

        return triggered

    def _trigger_watchdog(self, wd: Watchdog, triggered_channels: List[str], now: float):
        """Handle watchdog trigger"""
        logger.warning(f"Watchdog triggered: {wd.name} on channels: {triggered_channels}")

        wd.is_triggered = True
        wd.triggered_at = now
        wd.triggered_channels = triggered_channels
        wd.last_triggered = now

        # Execute actions
        for action in wd.actions:
            try:
                self._execute_action(action, wd)
            except Exception as e:
                logger.error(f"Failed to execute watchdog action: {e}")

    def _recover_watchdog(self, wd: Watchdog, now: float):
        """Handle watchdog recovery"""
        logger.info(f"Watchdog recovered: {wd.name}")

        wd.is_triggered = False
        wd.triggered_at = None
        wd.triggered_channels = []

        # Execute recovery actions
        for action in wd.recovery_actions:
            try:
                self._execute_action(action, wd)
            except Exception as e:
                logger.error(f"Failed to execute watchdog recovery action: {e}")

    def _execute_action(self, action: WatchdogAction, wd: Watchdog):
        """Execute a single watchdog action"""

        if action.action_type == WatchdogActionType.NOTIFICATION:
            if self.publish_notification:
                message = action.message or f"Watchdog '{wd.name}' triggered"
                self.publish_notification('watchdog', wd.name, message)

        elif action.action_type == WatchdogActionType.ALARM:
            if self.raise_alarm:
                message = action.message or f"Watchdog alarm: {wd.name}"
                self.raise_alarm(wd.id, action.alarm_severity, message)

        elif action.action_type == WatchdogActionType.SET_OUTPUT:
            if self.set_output and action.channel is not None:
                logger.info(f"Watchdog {wd.name}: setting {action.channel} = {action.value}")
                self.set_output(action.channel, action.value)

        elif action.action_type == WatchdogActionType.STOP_SEQUENCE:
            if self.stop_sequence and action.sequence_id:
                logger.info(f"Watchdog {wd.name}: stopping sequence {action.sequence_id}")
                self.stop_sequence(action.sequence_id)

        elif action.action_type == WatchdogActionType.STOP_RECORDING:
            if self.stop_recording:
                logger.info(f"Watchdog {wd.name}: stopping recording")
                self.stop_recording()

        elif action.action_type == WatchdogActionType.RUN_SEQUENCE:
            if self.run_sequence and action.sequence_id:
                logger.info(f"Watchdog {wd.name}: starting sequence {action.sequence_id}")
                self.run_sequence(action.sequence_id)

    def manual_clear(self, watchdog_id: str) -> bool:
        """Manually clear a triggered watchdog"""
        with self.lock:
            if watchdog_id not in self.watchdogs:
                return False

            wd = self.watchdogs[watchdog_id]
            if wd.is_triggered:
                wd.is_triggered = False
                wd.triggered_at = None
                wd.triggered_channels = []
                logger.info(f"Watchdog manually cleared: {wd.name}")
                return True
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current watchdog status for monitoring"""
        with self.lock:
            triggered_count = sum(1 for wd in self.watchdogs.values() if wd.is_triggered)

            return {
                'count': len(self.watchdogs),
                'enabled': sum(1 for wd in self.watchdogs.values() if wd.enabled),
                'triggered': triggered_count,
                'watchdogs': {
                    wd.id: wd.to_dict() for wd in self.watchdogs.values()
                }
            }
