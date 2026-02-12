"""
Trigger Engine - Evaluates automation triggers in the backend

Trigger types:
- valueReached: Fire when a channel value crosses a threshold
- timeElapsed: Fire after a duration from start event
- scheduled: Fire at specific time/date
- stateChange: Fire when system state changes
- sequenceEvent: Fire when sequence events occur

Actions:
- startSequence / runSequence: Start a sequence
- stopSequence: Stop a sequence
- setOutput: Set a digital/analog output
- startRecording / stopRecording: Control recording
- notification: Show notification
- runFormula: Execute a formula
- log: Log to file

Usage:
    engine = TriggerEngine()
    engine.load_from_project(project_data)

    # In scan loop:
    engine.process_scan(channel_values, current_state)
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


class TriggerType(Enum):
    VALUE_REACHED = "valueReached"
    TIME_ELAPSED = "timeElapsed"
    SCHEDULED = "scheduled"
    STATE_CHANGE = "stateChange"
    SEQUENCE_EVENT = "sequenceEvent"


class TriggerActionType(Enum):
    START_SEQUENCE = "startSequence"
    RUN_SEQUENCE = "runSequence"  # Alias
    STOP_SEQUENCE = "stopSequence"
    SET_OUTPUT = "setOutput"
    SET_SETPOINT = "setSetpoint"
    START_RECORDING = "startRecording"
    STOP_RECORDING = "stopRecording"
    NOTIFICATION = "notification"
    RUN_FORMULA = "runFormula"
    SOUND = "sound"
    LOG = "log"


@dataclass
class TriggerAction:
    """Action to execute when a trigger fires"""
    action_type: TriggerActionType
    sequence_id: Optional[str] = None
    channel: Optional[str] = None
    value: Optional[float] = None
    message: Optional[str] = None
    formula: Optional[str] = None
    sound: Optional[str] = None
    log_file: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TriggerAction':
        action_type_str = data.get('type', 'notification')
        # Handle aliases
        if action_type_str == 'runSequence':
            action_type_str = 'startSequence'

        return TriggerAction(
            action_type=TriggerActionType(action_type_str),
            sequence_id=data.get('sequenceId'),
            channel=data.get('channel'),
            value=data.get('value'),
            message=data.get('message'),
            formula=data.get('formula'),
            sound=data.get('sound'),
            log_file=data.get('logFile')
        )


@dataclass
class TriggerCondition:
    """Base trigger condition"""
    trigger_type: TriggerType
    # For valueReached
    channel: Optional[str] = None
    operator: Optional[str] = None  # '<', '>', '<=', '>=', '==', '!='
    threshold: Optional[float] = None
    hysteresis: Optional[float] = 0.0
    # For timeElapsed
    duration_ms: Optional[int] = None
    start_event: Optional[str] = None  # 'acquisitionStart', 'sequenceStart', 'manual'
    # For scheduled
    schedule_type: Optional[str] = None  # 'once', 'daily', 'weekly'
    schedule_time: Optional[str] = None  # HH:MM
    schedule_days: Optional[List[int]] = None  # 0-6 for weekly
    schedule_date: Optional[str] = None  # YYYY-MM-DD for once
    # For stateChange
    state_type: Optional[str] = None  # 'acquisition', 'recording', etc.
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    # For sequenceEvent
    sequence_id: Optional[str] = None
    event_type: Optional[str] = None  # 'started', 'completed', 'aborted', etc.

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TriggerCondition':
        trigger_type = TriggerType(data.get('type', 'valueReached'))

        return TriggerCondition(
            trigger_type=trigger_type,
            channel=data.get('channel'),
            operator=data.get('operator'),
            threshold=data.get('value'),
            hysteresis=data.get('hysteresis', 0.0),
            duration_ms=data.get('durationMs'),
            start_event=data.get('startEvent'),
            schedule_type=data.get('schedule', {}).get('type') if isinstance(data.get('schedule'), dict) else None,
            schedule_time=data.get('schedule', {}).get('time') if isinstance(data.get('schedule'), dict) else None,
            schedule_days=data.get('schedule', {}).get('daysOfWeek') if isinstance(data.get('schedule'), dict) else None,
            schedule_date=data.get('schedule', {}).get('date') if isinstance(data.get('schedule'), dict) else None,
            state_type=data.get('stateType'),
            from_state=data.get('fromState'),
            to_state=data.get('toState'),
            sequence_id=data.get('sequenceId'),
            event_type=data.get('event')
        )


@dataclass
class AutomationTrigger:
    """Complete automation trigger with condition and actions"""
    id: str
    name: str
    description: str
    enabled: bool
    one_shot: bool
    cooldown_ms: int
    condition: TriggerCondition
    actions: List[TriggerAction]
    run_mode: AutomationRunMode = AutomationRunMode.ACQUISITION  # When to be active
    # Runtime state
    last_triggered: Optional[float] = None
    has_fired: bool = False  # For one-shot triggers
    # For value triggers - track state for hysteresis
    last_value_state: Optional[bool] = None  # Was condition true last scan?
    # For time elapsed triggers
    start_time: Optional[float] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'AutomationTrigger':
        # Parse trigger condition
        trigger_data = data.get('trigger', {})
        condition = TriggerCondition.from_dict(trigger_data)

        # Parse actions
        actions_data = data.get('actions', [])
        actions = [TriggerAction.from_dict(a) for a in actions_data]

        # Parse run mode (default to acquisition for backward compatibility)
        run_mode_str = data.get('runMode', 'acquisition')
        try:
            run_mode = AutomationRunMode(run_mode_str)
        except ValueError:
            run_mode = AutomationRunMode.ACQUISITION

        return AutomationTrigger(
            id=data.get('id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            enabled=data.get('enabled', True),
            one_shot=data.get('oneShot', False),
            cooldown_ms=data.get('cooldownMs', 5000),
            condition=condition,
            actions=actions,
            run_mode=run_mode,
            last_triggered=data.get('lastTriggered')
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'oneShot': self.one_shot,
            'cooldownMs': self.cooldown_ms,
            'runMode': self.run_mode.value,
            'lastTriggered': self.last_triggered,
            'hasFired': self.has_fired
        }


class TriggerEngine:
    """
    Backend trigger evaluation engine.

    Evaluates trigger conditions every scan and executes actions when conditions are met.
    """

    def __init__(self):
        self.triggers: Dict[str, AutomationTrigger] = {}
        self.lock = threading.Lock()

        # Callbacks for actions
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.start_recording: Optional[Callable[[], None]] = None
        self.stop_recording: Optional[Callable[[], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None

        # System state tracking
        self._acquisition_start_time: Optional[float] = None
        self._is_acquiring: bool = False
        self._is_session_active: bool = False
        self._last_system_state: Dict[str, Any] = {}
        self._scheduled_check_time: float = 0

    def load_from_project(self, project_data: Dict[str, Any]) -> int:
        """
        Load triggers from project data.

        Args:
            project_data: Project JSON with scripts.triggers array

        Returns:
            Number of triggers loaded
        """
        with self.lock:
            self.triggers.clear()

            scripts_data = project_data.get('scripts', {})
            triggers_data = scripts_data.get('triggers', [])

            if not triggers_data:
                logger.debug("No triggers found in project")
                return 0

            for trigger_data in triggers_data:
                try:
                    trigger = AutomationTrigger.from_dict(trigger_data)
                    self.triggers[trigger.id] = trigger
                    logger.debug(f"Loaded trigger: {trigger.name} ({trigger.condition.trigger_type.value})")
                except Exception as e:
                    logger.error(f"Failed to load trigger: {e}")

            logger.info(f"Loaded {len(self.triggers)} triggers from project")
            return len(self.triggers)

    def clear(self):
        """Clear all triggers"""
        with self.lock:
            self.triggers.clear()
            logger.info("Cleared all triggers")

    def on_acquisition_start(self):
        """Called when acquisition starts"""
        self._acquisition_start_time = time.time()
        self._is_acquiring = True
        logger.debug("Trigger engine: acquisition started")

    def on_acquisition_stop(self):
        """Called when acquisition stops"""
        self._acquisition_start_time = None
        self._is_acquiring = False
        logger.debug("Trigger engine: acquisition stopped")

    def on_session_start(self):
        """Called when test session starts"""
        self._is_session_active = True
        logger.debug("Trigger engine: session started")

    def on_session_stop(self):
        """Called when test session stops"""
        self._is_session_active = False
        logger.debug("Trigger engine: session stopped")

    def _is_trigger_active(self, trigger: AutomationTrigger) -> bool:
        """Check if trigger should be active based on its run_mode.

        Note: Nothing runs if acquisition isn't active - acquisition is the base requirement.
        """
        if not self._is_acquiring:
            return False

        if trigger.run_mode == AutomationRunMode.ACQUISITION:
            return True  # Active whenever acquiring
        elif trigger.run_mode == AutomationRunMode.SESSION:
            return self._is_session_active  # Active only during session (subset of acquisition)
        return False

    def on_state_change(self, state_type: str, from_state: str, to_state: str):
        """
        Notify the engine of a state change.

        Args:
            state_type: Type of state (acquisition, recording, etc.)
            from_state: Previous state
            to_state: New state
        """
        with self.lock:
            now = time.time()

            for trigger in self.triggers.values():
                if not trigger.enabled or trigger.has_fired:
                    continue

                cond = trigger.condition
                if cond.trigger_type != TriggerType.STATE_CHANGE:
                    continue

                if cond.state_type != state_type:
                    continue

                # Check from_state if specified
                if cond.from_state and cond.from_state != from_state:
                    continue

                # Check to_state
                if cond.to_state != to_state:
                    continue

                # Check cooldown
                if trigger.last_triggered:
                    elapsed = (now - trigger.last_triggered) * 1000
                    if elapsed < trigger.cooldown_ms:
                        continue

                # Fire!
                self._fire_trigger(trigger, now)

    def on_sequence_event(self, sequence_id: str, event: str):
        """
        Notify the engine of a sequence event.

        Args:
            sequence_id: ID of the sequence
            event: Event type (started, completed, aborted, error)
        """
        with self.lock:
            now = time.time()

            for trigger in self.triggers.values():
                if not trigger.enabled or trigger.has_fired:
                    continue

                cond = trigger.condition
                if cond.trigger_type != TriggerType.SEQUENCE_EVENT:
                    continue

                # Check sequence ID if specified
                if cond.sequence_id and cond.sequence_id != sequence_id:
                    continue

                # Check event type
                if cond.event_type != event:
                    continue

                # Check cooldown
                if trigger.last_triggered:
                    elapsed = (now - trigger.last_triggered) * 1000
                    if elapsed < trigger.cooldown_ms:
                        continue

                # Fire!
                self._fire_trigger(trigger, now)

    def process_scan(self, channel_values: Dict[str, float], system_state: Dict[str, Any] = None):
        """
        Process all triggers for the current scan.

        Called every scan from the DAQ loop.

        Args:
            channel_values: Current channel values
            system_state: Current system state (optional)
        """
        if system_state is None:
            system_state = {}

        now = time.time()

        with self.lock:
            for trigger in self.triggers.values():
                if not trigger.enabled:
                    continue

                # Check if trigger should be active based on run_mode
                if not self._is_trigger_active(trigger):
                    continue

                if trigger.one_shot and trigger.has_fired:
                    continue

                # Check cooldown
                if trigger.last_triggered:
                    elapsed = (now - trigger.last_triggered) * 1000
                    if elapsed < trigger.cooldown_ms:
                        continue

                should_fire = self._evaluate_condition(trigger, channel_values, now)

                if should_fire:
                    self._fire_trigger(trigger, now)

    def _evaluate_condition(self, trigger: AutomationTrigger,
                           channel_values: Dict[str, float],
                           now: float) -> bool:
        """
        Evaluate if a trigger condition is met.

        Returns True if the trigger should fire.
        """
        cond = trigger.condition

        if cond.trigger_type == TriggerType.VALUE_REACHED:
            return self._evaluate_value_reached(trigger, channel_values)

        elif cond.trigger_type == TriggerType.TIME_ELAPSED:
            return self._evaluate_time_elapsed(trigger, now)

        elif cond.trigger_type == TriggerType.SCHEDULED:
            return self._evaluate_scheduled(trigger, now)

        # stateChange and sequenceEvent are handled by event callbacks
        return False

    def _evaluate_value_reached(self, trigger: AutomationTrigger,
                                channel_values: Dict[str, float]) -> bool:
        """Evaluate a value-reached trigger"""
        cond = trigger.condition

        if not cond.channel or cond.channel not in channel_values:
            return False

        value = channel_values[cond.channel]
        threshold = cond.threshold or 0
        hysteresis = cond.hysteresis or 0
        operator = cond.operator or '=='

        # Handle NaN
        if math.isnan(value):
            return False

        # Evaluate condition
        condition_met = False

        if operator == '>':
            condition_met = value > threshold
        elif operator == '<':
            condition_met = value < threshold
        elif operator == '>=':
            condition_met = value >= threshold
        elif operator == '<=':
            condition_met = value <= threshold
        elif operator == '==':
            condition_met = abs(value - threshold) < 0.001
        elif operator == '!=':
            condition_met = abs(value - threshold) >= 0.001

        # Apply hysteresis - only fire on transition from false to true
        was_met = trigger.last_value_state
        trigger.last_value_state = condition_met

        if hysteresis > 0:
            # With hysteresis, only fire on rising edge with margin
            if was_met is None:
                return condition_met
            if not was_met and condition_met:
                return True
            return False
        else:
            # Without hysteresis, fire on rising edge
            if was_met is None:
                return condition_met
            return not was_met and condition_met

    def _evaluate_time_elapsed(self, trigger: AutomationTrigger, now: float) -> bool:
        """Evaluate a time-elapsed trigger"""
        cond = trigger.condition

        if not cond.duration_ms:
            return False

        # Determine start time based on start event
        start_time = None

        if cond.start_event == 'acquisitionStart':
            start_time = self._acquisition_start_time
        elif cond.start_event == 'manual':
            start_time = trigger.start_time
        # 'sequenceStart' would need sequence tracking

        if start_time is None:
            return False

        elapsed_ms = (now - start_time) * 1000
        return elapsed_ms >= cond.duration_ms

    def _evaluate_scheduled(self, trigger: AutomationTrigger, now: float) -> bool:
        """Evaluate a scheduled trigger"""
        cond = trigger.condition

        if not cond.schedule_time:
            return False

        # Parse schedule time (HH:MM)
        try:
            hour, minute = map(int, cond.schedule_time.split(':'))
        except (ValueError, AttributeError) as e:
            logger.warning(f"Invalid schedule_time format '{cond.schedule_time}': {e}")
            return False

        current_dt = datetime.now()
        current_time = current_dt.hour * 60 + current_dt.minute
        schedule_time = hour * 60 + minute

        # Check if we're within the minute of scheduled time
        if abs(current_time - schedule_time) > 1:
            return False

        # Check day of week for weekly schedules
        if cond.schedule_type == 'weekly' and cond.schedule_days:
            if current_dt.weekday() not in cond.schedule_days:
                return False

        # Check date for once schedules
        if cond.schedule_type == 'once' and cond.schedule_date:
            if current_dt.strftime('%Y-%m-%d') != cond.schedule_date:
                return False

        # Only fire once per minute
        if trigger.last_triggered:
            last_dt = datetime.fromtimestamp(trigger.last_triggered)
            if (last_dt.hour == current_dt.hour and
                last_dt.minute == current_dt.minute and
                last_dt.day == current_dt.day):
                return False

        return True

    def _fire_trigger(self, trigger: AutomationTrigger, now: float):
        """Execute trigger actions"""
        logger.info(f"Trigger fired: {trigger.name}")

        trigger.last_triggered = now
        if trigger.one_shot:
            trigger.has_fired = True

        # Execute actions
        for action in trigger.actions:
            try:
                self._execute_action(action, trigger)
            except Exception as e:
                logger.error(f"Failed to execute trigger action: {e}")

    def _execute_action(self, action: TriggerAction, trigger: AutomationTrigger):
        """Execute a single trigger action"""

        if action.action_type in (TriggerActionType.START_SEQUENCE, TriggerActionType.RUN_SEQUENCE):
            if self.run_sequence and action.sequence_id:
                logger.info(f"Trigger {trigger.name}: starting sequence {action.sequence_id}")
                self.run_sequence(action.sequence_id)

        elif action.action_type == TriggerActionType.STOP_SEQUENCE:
            if self.stop_sequence and action.sequence_id:
                logger.info(f"Trigger {trigger.name}: stopping sequence {action.sequence_id}")
                self.stop_sequence(action.sequence_id)

        elif action.action_type == TriggerActionType.SET_OUTPUT:
            if self.set_output and action.channel is not None:
                logger.info(f"Trigger {trigger.name}: setting {action.channel} = {action.value}")
                self.set_output(action.channel, action.value)

        elif action.action_type == TriggerActionType.SET_SETPOINT:
            # Same as set_output for now
            if self.set_output and action.channel is not None:
                logger.info(f"Trigger {trigger.name}: setting setpoint {action.channel} = {action.value}")
                self.set_output(action.channel, action.value)

        elif action.action_type == TriggerActionType.START_RECORDING:
            if self.start_recording:
                logger.info(f"Trigger {trigger.name}: starting recording")
                self.start_recording()

        elif action.action_type == TriggerActionType.STOP_RECORDING:
            if self.stop_recording:
                logger.info(f"Trigger {trigger.name}: stopping recording")
                self.stop_recording()

        elif action.action_type == TriggerActionType.NOTIFICATION:
            if self.publish_notification and action.message:
                logger.info(f"Trigger {trigger.name}: notification - {action.message}")
                self.publish_notification('trigger', trigger.name, action.message)

        elif action.action_type == TriggerActionType.LOG:
            if action.message:
                logger.info(f"Trigger {trigger.name} LOG: {action.message}")

    def get_status(self) -> Dict[str, Any]:
        """Get current trigger status for monitoring"""
        with self.lock:
            return {
                'count': len(self.triggers),
                'enabled': sum(1 for t in self.triggers.values() if t.enabled),
                'triggers': {
                    t.id: t.to_dict() for t in self.triggers.values()
                }
            }
