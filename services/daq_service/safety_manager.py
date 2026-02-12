"""
Backend Safety Manager for NISystem

Provides backend-authoritative safety/interlock evaluation that runs
independent of the frontend (JavaScript). This ensures safety logic
executes reliably even if the browser tab closes or crashes.

Features:
- Interlock condition evaluation using real-time channel values
- Latch state machine (SAFE → ARMED → TRIPPED)
- Trip actions (stop session, reset outputs to safe state)
- MQTT publishing of safety status for frontend display
- Interlock history/audit trail (IEC 61511 compliance)

The frontend becomes display-only - all safety logic runs here.
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
import uuid

logger = logging.getLogger('SafetyManager')


class LatchState(Enum):
    """Safety latch states"""
    SAFE = "safe"          # Latch is disarmed, outputs blocked
    ARMED = "armed"        # Latch is armed, outputs allowed
    TRIPPED = "tripped"    # System tripped due to interlock failure


class ConditionOperator(Enum):
    """Comparison operators for interlock conditions"""
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "="
    NE = "!="


@dataclass
class InterlockCondition:
    """Single condition in an interlock"""
    id: str
    condition_type: str  # channel_value, digital_input, mqtt_connected, daq_connected, acquiring, no_active_alarms, etc.
    channel: Optional[str] = None
    operator: Optional[str] = None  # <, <=, >, >=, =, !=
    value: Optional[Any] = None
    invert: bool = False
    delay_s: float = 0.0
    alarm_id: Optional[str] = None       # For alarm_active, alarm_state conditions
    alarm_state_check: Optional[str] = None  # For alarm_state: expected state (active, acknowledged, etc.)
    variable_id: Optional[str] = None    # For variable_value conditions
    expression: Optional[str] = None     # For expression conditions

    def to_dict(self) -> dict:
        d = {
            'id': self.id,
            'type': self.condition_type,
            'channel': self.channel,
            'operator': self.operator,
            'value': self.value,
            'invert': self.invert,
            'delay_s': self.delay_s
        }
        if self.alarm_id is not None:
            d['alarmId'] = self.alarm_id
        if self.alarm_state_check is not None:
            d['alarmState'] = self.alarm_state_check
        if self.variable_id is not None:
            d['variableId'] = self.variable_id
        if self.expression is not None:
            d['expression'] = self.expression
        return d

    VALID_OPERATORS = {'==', '!=', '<', '>', '<=', '>='}
    VALID_CONDITION_TYPES = {
        'channel_value', 'digital_input',
        'mqtt_connected', 'daq_connected',
        'acquiring', 'not_recording', 'no_active_alarms',
        'alarm_active', 'alarm_state',
        'variable_value', 'expression'
    }

    @staticmethod
    def from_dict(d: dict) -> 'InterlockCondition':
        operator = d.get('operator')
        condition_type = d.get('type', d.get('condition_type', 'channel_value'))

        if operator and operator not in InterlockCondition.VALID_OPERATORS:
            logger.error(f"Interlock condition has invalid operator '{operator}' — must be one of {InterlockCondition.VALID_OPERATORS}")
            return None
        if condition_type not in InterlockCondition.VALID_CONDITION_TYPES:
            logger.error(f"Interlock condition has unknown type '{condition_type}' — must be one of {InterlockCondition.VALID_CONDITION_TYPES}")
            return None
        if condition_type == 'channel_value' and not d.get('channel'):
            logger.error("Interlock condition of type 'channel_value' has no channel specified")
            return None
        if condition_type == 'digital_input' and not d.get('channel'):
            logger.error("Interlock condition of type 'digital_input' has no channel specified")
            return None
        if condition_type in ('alarm_active', 'alarm_state') and not d.get('alarmId'):
            logger.error(f"Interlock condition of type '{condition_type}' has no alarmId specified")
            return None
        if condition_type == 'variable_value' and not d.get('variableId'):
            logger.error("Interlock condition of type 'variable_value' has no variableId specified")
            return None

        return InterlockCondition(
            id=d.get('id', str(uuid.uuid4())),
            condition_type=condition_type,
            channel=d.get('channel'),
            operator=operator,
            value=d.get('value'),
            invert=d.get('invert', False),
            delay_s=d.get('delay_s', 0.0),
            alarm_id=d.get('alarmId'),
            alarm_state_check=d.get('alarmState'),
            variable_id=d.get('variableId'),
            expression=d.get('expression')
        )


@dataclass
class InterlockControl:
    """Action controlled by an interlock"""
    control_type: str  # digital_output, analog_output, session_start, recording_start, etc.
    channel: Optional[str] = None
    set_value: Optional[Any] = None  # For set_digital_output, set_analog_output actions
    button_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'type': self.control_type,
            'channel': self.channel,
            'setValue': self.set_value,
            'buttonId': self.button_id
        }

    @staticmethod
    def from_dict(d: dict) -> 'InterlockControl':
        return InterlockControl(
            control_type=d.get('type', d.get('control_type', '')),
            channel=d.get('channel'),
            set_value=d.get('setValue', d.get('set_value')),
            button_id=d.get('buttonId', d.get('button_id'))
        )


@dataclass
class Interlock:
    """Interlock definition"""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    conditions: List[InterlockCondition] = field(default_factory=list)
    condition_logic: str = "AND"  # AND or OR
    controls: List[InterlockControl] = field(default_factory=list)

    # Bypass
    bypass_allowed: bool = False
    bypassed: bool = False
    bypassed_by: Optional[str] = None
    bypassed_at: Optional[str] = None
    bypass_reason: Optional[str] = None
    max_bypass_duration: Optional[float] = None  # seconds

    # Tracking
    demand_count: int = 0
    last_demand_time: Optional[str] = None
    last_proof_test: Optional[str] = None
    proof_test_interval_days: Optional[float] = None  # IEC 61511: periodic verification interval

    # IEC 61511 / ISA-18.2 compliance
    priority: str = "medium"  # critical, high, medium, low — operational display priority
    sil_rating: Optional[str] = None  # SIL1, SIL2, SIL3, SIL4
    requires_acknowledgment: bool = False  # Require operator ack after trip

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
            'bypassReason': self.bypass_reason,
            'maxBypassDuration': self.max_bypass_duration,
            'demandCount': self.demand_count,
            'lastDemandTime': self.last_demand_time,
            'lastProofTest': self.last_proof_test,
            'proofTestIntervalDays': self.proof_test_interval_days,
            'priority': self.priority,
            'silRating': self.sil_rating,
            'requiresAcknowledgment': self.requires_acknowledgment
        }

    @staticmethod
    def from_dict(d: dict) -> 'Interlock':
        return Interlock(
            id=d.get('id', str(uuid.uuid4())),
            name=d.get('name', ''),
            description=d.get('description', ''),
            enabled=d.get('enabled', True),
            conditions=[cond for c in d.get('conditions', []) if (cond := InterlockCondition.from_dict(c)) is not None],
            condition_logic=d.get('conditionLogic', d.get('condition_logic', 'AND')),
            controls=[InterlockControl.from_dict(c) for c in d.get('controls', [])],
            bypass_allowed=d.get('bypassAllowed', d.get('bypass_allowed', False)),
            bypassed=d.get('bypassed', False),
            bypassed_by=d.get('bypassedBy', d.get('bypassed_by')),
            bypassed_at=d.get('bypassedAt', d.get('bypassed_at')),
            bypass_reason=d.get('bypassReason', d.get('bypass_reason')),
            max_bypass_duration=d.get('maxBypassDuration', d.get('max_bypass_duration')),
            demand_count=d.get('demandCount', d.get('demand_count', 0)),
            last_demand_time=d.get('lastDemandTime', d.get('last_demand_time')),
            last_proof_test=d.get('lastProofTest', d.get('last_proof_test')),
            proof_test_interval_days=d.get('proofTestIntervalDays', d.get('proof_test_interval_days')),
            priority=d.get('priority', 'medium'),
            sil_rating=d.get('silRating', d.get('sil_rating')),
            requires_acknowledgment=d.get('requiresAcknowledgment', d.get('requires_acknowledgment', False))
        )


@dataclass
class InterlockStatus:
    """Runtime status of an interlock"""
    id: str
    name: str
    satisfied: bool
    enabled: bool
    bypassed: bool
    failed_conditions: List[Dict[str, Any]] = field(default_factory=list)
    # IEC 61511 compliance fields
    priority: str = "medium"
    sil_rating: Optional[str] = None
    requires_acknowledgment: bool = False
    trip_acknowledged: bool = False
    trip_acknowledged_by: Optional[str] = None
    trip_acknowledged_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            'id': self.id,
            'name': self.name,
            'satisfied': self.satisfied,
            'enabled': self.enabled,
            'bypassed': self.bypassed,
            'failedConditions': self.failed_conditions,
            'priority': self.priority,
            'silRating': self.sil_rating,
            'requiresAcknowledgment': self.requires_acknowledgment,
        }
        if self.requires_acknowledgment:
            d['tripAcknowledged'] = self.trip_acknowledged
            d['tripAcknowledgedBy'] = self.trip_acknowledged_by
            d['tripAcknowledgedAt'] = self.trip_acknowledged_at
        return d


@dataclass
class SafeStateConfig:
    """Configuration for safe state on trip"""
    reset_digital_outputs: bool = True
    reset_analog_outputs: bool = True
    stop_session: bool = True
    digital_output_channels: List[str] = field(default_factory=list)  # Empty = all
    analog_output_channels: List[str] = field(default_factory=list)   # Empty = all
    analog_safe_value: float = 0.0

    def to_dict(self) -> dict:
        return {
            'resetDigitalOutputs': self.reset_digital_outputs,
            'resetAnalogOutputs': self.reset_analog_outputs,
            'stopSession': self.stop_session,
            'digitalOutputChannels': self.digital_output_channels,
            'analogOutputChannels': self.analog_output_channels,
            'analogSafeValue': self.analog_safe_value
        }

    @staticmethod
    def from_dict(d: dict) -> 'SafeStateConfig':
        return SafeStateConfig(
            reset_digital_outputs=d.get('resetDigitalOutputs', d.get('reset_digital_outputs', True)),
            reset_analog_outputs=d.get('resetAnalogOutputs', d.get('reset_analog_outputs', True)),
            stop_session=d.get('stopSession', d.get('stop_session', True)),
            digital_output_channels=d.get('digitalOutputChannels', d.get('digital_output_channels', [])),
            analog_output_channels=d.get('analogOutputChannels', d.get('analog_output_channels', [])),
            analog_safe_value=d.get('analogSafeValue', d.get('analog_safe_value', 0.0))
        )


@dataclass
class InterlockHistoryEntry:
    """Audit log entry for interlock events"""
    id: str
    timestamp: str
    interlock_id: str
    interlock_name: str
    event: str  # created, enabled, disabled, bypassed, bypass_removed, demand, cleared, proof_test, trip_acknowledged
    user: Optional[str] = None
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'interlockId': self.interlock_id,
            'interlockName': self.interlock_name,
            'event': self.event,
            'user': self.user,
            'reason': self.reason,
            'details': self.details
        }


class SafetyManager:
    """
    Backend Safety Manager - authoritative source for safety logic.

    Evaluates interlocks, manages latch state, and executes trip actions.
    Frontend subscribes to status updates and becomes display-only.
    """

    def __init__(
        self,
        data_dir: Path,
        get_channel_value: Callable[[str], Optional[float]],
        get_channel_type: Callable[[str], Optional[str]],
        get_all_channels: Callable[[], Dict[str, Any]],
        publish_callback: Optional[Callable[[str, Any], None]] = None,
        set_output_callback: Optional[Callable[[str, Any], None]] = None,
        stop_session_callback: Optional[Callable[[], None]] = None,
        get_system_state: Optional[Callable[[], Dict[str, Any]]] = None,
        get_alarm_state: Optional[Callable[[], Dict[str, Any]]] = None,
        trigger_safe_state_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize SafetyManager.

        Args:
            data_dir: Directory for persistence files
            get_channel_value: Callback to get current channel value
            get_channel_type: Callback to get channel type
            get_all_channels: Callback to get all channel configs
            publish_callback: Callback to publish MQTT messages (topic, payload)
            set_output_callback: Callback to set output value (channel, value)
            stop_session_callback: Callback to stop test session
            get_system_state: Callback to get system state (acquiring, recording, etc.)
            get_alarm_state: Callback to get alarm state (active alarms, etc.)
            trigger_safe_state_callback: Callback to send atomic safe-state to remote nodes (cRIO)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self._get_channel_value = get_channel_value
        self._get_channel_type = get_channel_type
        self._get_all_channels = get_all_channels
        self._publish = publish_callback
        self._set_output = set_output_callback
        self._stop_session = stop_session_callback
        self._get_system_state = get_system_state
        self._get_alarm_state = get_alarm_state
        self._trigger_safe_state = trigger_safe_state_callback

        # Thread safety
        self.lock = threading.RLock()

        # Interlock definitions
        self.interlocks: Dict[str, Interlock] = {}

        # Previous interlock states for demand tracking
        self._previous_states: Dict[str, bool] = {}

        # Condition delay tracking
        self._condition_delay_state: Dict[str, Dict[str, Any]] = {}

        # Latch state
        self.latch_state = LatchState.SAFE
        self.latch_id = "main"  # Support multiple latches in future

        # Trip state
        self.is_tripped = False
        self.last_trip_time: Optional[str] = None
        self.last_trip_reason: Optional[str] = None

        # Safe state configuration
        self.safe_state_config = SafeStateConfig()

        # Executed actions tracking (prevent repeated execution)
        self._executed_actions: Set[str] = set()

        # Per-interlock trip acknowledgment state (runtime-only, not persisted)
        self._trip_ack_state: Dict[str, dict] = {}

        # Interlock history (audit trail)
        self.history: List[InterlockHistoryEntry] = []
        self.max_history = 1000

        # Node ID for multi-node systems
        self.node_id = "local"

        # Load persisted state
        self._load_interlocks()
        self._load_safe_state_config()
        self._load_history()

        logger.info("SafetyManager initialized")

    # ========================================================================
    # Interlock Management
    # ========================================================================

    def add_interlock(self, interlock: Interlock, user: str = "system") -> str:
        """Add or update an interlock. Warns if condition channels don't exist."""
        # Cross-validate: check condition channels exist in current hardware config
        if self._get_all_channels:
            try:
                all_channels = self._get_all_channels()
                if all_channels:
                    known = set(all_channels.keys())
                    for cond in interlock.conditions:
                        if cond.channel and cond.channel not in known:
                            logger.warning(
                                f"Interlock '{interlock.name}': condition channel "
                                f"'{cond.channel}' not found in hardware config"
                            )
            except Exception as e:
                logger.debug(f"Channel cross-validation skipped: {e}")

        with self.lock:
            self.interlocks[interlock.id] = interlock
            self._record_event(interlock, 'created' if interlock.id not in self.interlocks else 'modified', user)
            self._save_interlocks()
            self._publish_interlock_update(interlock)
            logger.info(f"Added/updated interlock: {interlock.name}")
            return interlock.id

    def remove_interlock(self, interlock_id: str, user: str = "system"):
        """Remove an interlock"""
        with self.lock:
            if interlock_id in self.interlocks:
                interlock = self.interlocks.pop(interlock_id)
                self._save_interlocks()
                if self._publish:
                    self._publish('interlocks/removed', {'id': interlock_id})
                logger.info(f"Removed interlock: {interlock.name}")

    def update_interlock(self, interlock_id: str, updates: Dict[str, Any], user: str = "system"):
        """Update interlock properties"""
        with self.lock:
            if interlock_id not in self.interlocks:
                return

            interlock = self.interlocks[interlock_id]
            was_enabled = interlock.enabled

            # Apply updates
            for key, value in updates.items():
                if hasattr(interlock, key):
                    setattr(interlock, key, value)

            # Track enable/disable
            if was_enabled != interlock.enabled:
                event = 'enabled' if interlock.enabled else 'disabled'
                self._record_event(interlock, event, user)
            else:
                self._record_event(interlock, 'modified', user)

            self._save_interlocks()
            self._publish_interlock_update(interlock)

    def bypass_interlock(self, interlock_id: str, bypass: bool, user: str, reason: str = ""):
        """Bypass or un-bypass an interlock"""
        with self.lock:
            if interlock_id not in self.interlocks:
                return False

            interlock = self.interlocks[interlock_id]
            if not interlock.bypass_allowed and bypass:
                logger.warning(f"Bypass not allowed for interlock: {interlock.name}")
                return False

            was_bypassed = interlock.bypassed
            interlock.bypassed = bypass

            if bypass:
                interlock.bypassed_at = datetime.now().isoformat()
                interlock.bypassed_by = user
                interlock.bypass_reason = reason
                if not was_bypassed:
                    self._record_event(interlock, 'bypassed', user, reason)
            else:
                interlock.bypassed_at = None
                interlock.bypassed_by = None
                interlock.bypass_reason = None
                if was_bypassed:
                    self._record_event(interlock, 'bypass_removed', user, reason)

            self._save_interlocks()
            self._publish_interlock_update(interlock)
            return True

    def get_interlock(self, interlock_id: str) -> Optional[Interlock]:
        """Get an interlock by ID"""
        return self.interlocks.get(interlock_id)

    def get_all_interlocks(self) -> List[Interlock]:
        """Get all interlocks"""
        return list(self.interlocks.values())

    # ========================================================================
    # Condition Evaluation
    # ========================================================================

    def _evaluate_condition_raw(self, condition: InterlockCondition) -> Dict[str, Any]:
        """Evaluate a single condition without delay logic"""
        result = {
            'satisfied': False,
            'current_value': None,
            'reason': 'Unknown condition type'
        }

        cond_type = condition.condition_type

        if cond_type == 'mqtt_connected':
            # Always True from backend perspective (we're running)
            connected = True
            result = {
                'satisfied': connected,
                'current_value': connected,
                'reason': 'MQTT connected' if connected else 'MQTT disconnected'
            }

        elif cond_type == 'daq_connected':
            state = self._get_system_state() if self._get_system_state else {}
            connected = state.get('status') == 'online'
            result = {
                'satisfied': connected,
                'current_value': connected,
                'reason': 'DAQ online' if connected else 'DAQ offline'
            }

        elif cond_type == 'acquiring':
            state = self._get_system_state() if self._get_system_state else {}
            acquiring = state.get('acquiring', False)
            result = {
                'satisfied': acquiring,
                'current_value': acquiring,
                'reason': 'System acquiring' if acquiring else 'System not acquiring'
            }

        elif cond_type == 'not_recording':
            state = self._get_system_state() if self._get_system_state else {}
            recording = state.get('recording', False)
            result = {
                'satisfied': not recording,
                'current_value': not recording,
                'reason': 'Not recording' if not recording else 'Currently recording'
            }

        elif cond_type == 'no_active_alarms':
            alarm_state = self._get_alarm_state() if self._get_alarm_state else {}
            active_count = alarm_state.get('active_count', 0)
            no_alarms = active_count == 0
            result = {
                'satisfied': no_alarms,
                'current_value': active_count,
                'reason': 'No active alarms' if no_alarms else f'{active_count} active alarm(s)'
            }

        elif cond_type == 'channel_value':
            if not condition.channel or condition.operator is None or condition.value is None:
                result['reason'] = 'Invalid channel condition'
            else:
                value = self._get_channel_value(condition.channel)
                if value is None:
                    result['reason'] = f'Channel {condition.channel} has no value'
                else:
                    satisfied = self._compare_values(value, condition.operator, condition.value)
                    result = {
                        'satisfied': satisfied,
                        'current_value': value,
                        'reason': f'{condition.channel} = {value:.2f} ({("OK" if satisfied else f"requires {condition.operator} {condition.value}")})'
                    }

        elif cond_type == 'digital_input':
            if not condition.channel:
                result['reason'] = 'Invalid digital input condition'
            else:
                value = self._get_channel_value(condition.channel)
                if value is None:
                    result['reason'] = f'Channel {condition.channel} has no value'
                else:
                    raw_state = value != 0
                    actual_state = not raw_state if condition.invert else raw_state
                    expected = condition.value in (True, 1)
                    satisfied = actual_state == expected
                    invert_note = ' [inverted]' if condition.invert else ''
                    result = {
                        'satisfied': satisfied,
                        'current_value': value,
                        'reason': f"{condition.channel} = {'ON' if actual_state else 'OFF'}{invert_note} ({'OK' if satisfied else ('requires ON' if expected else 'requires OFF')})"
                    }

        elif cond_type == 'alarm_active':
            # Satisfied when specific alarm is NOT active (same semantics as frontend)
            if not condition.alarm_id:
                result['reason'] = 'No alarm ID specified'
            else:
                alarm_state = self._get_alarm_state() if self._get_alarm_state else {}
                active_alarms = alarm_state.get('active_alarms', {})
                is_active = condition.alarm_id in active_alarms
                result = {
                    'satisfied': not is_active,
                    'current_value': is_active,
                    'reason': f'Alarm {condition.alarm_id} is {"active" if is_active else "clear"}'
                }

        elif cond_type == 'alarm_state':
            # Check if alarm is in a specific state
            if not condition.alarm_id or not condition.alarm_state_check:
                result['reason'] = 'Invalid alarm state condition'
            else:
                alarm_state = self._get_alarm_state() if self._get_alarm_state else {}
                active_alarms = alarm_state.get('active_alarms', {})
                alarm_info = active_alarms.get(condition.alarm_id)
                current_state = alarm_info.get('state', 'none') if alarm_info else 'none'
                in_state = current_state == condition.alarm_state_check
                result = {
                    'satisfied': in_state,
                    'current_value': current_state,
                    'reason': f'Alarm {condition.alarm_id} is {current_state}' + (
                        ' (OK)' if in_state else f' (requires {condition.alarm_state_check})')
                }

        elif cond_type == 'variable_value':
            # Check user variable value — variables are published as channel values
            if not condition.variable_id or condition.operator is None or condition.value is None:
                result['reason'] = 'Invalid variable condition'
            else:
                value = self._get_channel_value(condition.variable_id)
                if value is None:
                    result['reason'] = f'Variable {condition.variable_id} not found'
                else:
                    satisfied = self._compare_values(value, condition.operator, condition.value)
                    result = {
                        'satisfied': satisfied,
                        'current_value': value,
                        'reason': f'Variable {condition.variable_id} = {value}' + (
                            ' (OK)' if satisfied else f' (requires {condition.operator} {condition.value})')
                    }

        elif cond_type == 'expression':
            # Expression evaluation is frontend-only; backend defaults to satisfied (fail-open)
            # to avoid false trips from unsupported server-side expression parsing
            result = {
                'satisfied': True,
                'current_value': None,
                'reason': 'Expression conditions evaluated on frontend only'
            }

        return result

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Compare values using the specified operator"""
        if operator == '<':
            return current < threshold
        elif operator == '<=':
            return current <= threshold
        elif operator == '>':
            return current > threshold
        elif operator == '>=':
            return current >= threshold
        elif operator == '=' or operator == '==':
            return current == threshold
        elif operator == '!=' or operator == '<>':
            return current != threshold
        return False

    def _evaluate_condition(self, condition: InterlockCondition) -> Dict[str, Any]:
        """Evaluate condition with delay logic"""
        raw_result = self._evaluate_condition_raw(condition)

        # If no delay configured, return raw result
        if not condition.delay_s or condition.delay_s <= 0:
            return raw_result

        now = time.time()
        delay_key = condition.id
        delay_state = self._condition_delay_state.get(delay_key)

        if raw_result['satisfied']:
            # Condition is satisfied - check if delay has elapsed
            if not delay_state or not delay_state.get('met', False):
                start_time = delay_state.get('start_time', now) if delay_state else now
                elapsed = now - start_time

                if elapsed >= condition.delay_s:
                    self._condition_delay_state[delay_key] = {'start_time': start_time, 'met': True}
                    return raw_result
                else:
                    self._condition_delay_state[delay_key] = {'start_time': start_time, 'met': False}
                    return {
                        **raw_result,
                        'satisfied': False,
                        'delay_remaining': condition.delay_s - elapsed,
                        'reason': f"{raw_result['reason']} (waiting {condition.delay_s - elapsed:.1f}s)"
                    }
            return raw_result
        else:
            # Condition not satisfied - reset delay timer
            if delay_key in self._condition_delay_state:
                del self._condition_delay_state[delay_key]
            return raw_result

    def evaluate_interlock(self, interlock: Interlock) -> InterlockStatus:
        """Evaluate an interlock and return its status"""
        # Common fields for all return paths
        ack_state = self._trip_ack_state.get(interlock.id, {})

        if not interlock.enabled:
            return InterlockStatus(
                id=interlock.id,
                name=interlock.name,
                satisfied=True,
                enabled=False,
                bypassed=False,
                failed_conditions=[],
                priority=interlock.priority,
                sil_rating=interlock.sil_rating,
                requires_acknowledgment=interlock.requires_acknowledgment,
            )

        # Check bypass expiration
        if interlock.bypassed and interlock.max_bypass_duration and interlock.bypassed_at:
            try:
                bypass_time = datetime.fromisoformat(interlock.bypassed_at).timestamp()
                elapsed = time.time() - bypass_time
                if elapsed >= interlock.max_bypass_duration:
                    self.bypass_interlock(interlock.id, False, 'system', 'Bypass time expired')
            except Exception as e:
                logger.error(f"Bypass expiration check failed for interlock {interlock.id}: {e}")

        if interlock.bypassed:
            return InterlockStatus(
                id=interlock.id,
                name=interlock.name,
                satisfied=True,
                enabled=True,
                bypassed=True,
                failed_conditions=[],
                priority=interlock.priority,
                sil_rating=interlock.sil_rating,
                requires_acknowledgment=interlock.requires_acknowledgment,
            )

        # Evaluate conditions
        failed_conditions = []
        results = []

        for condition in interlock.conditions:
            result = self._evaluate_condition(condition)
            results.append(result['satisfied'])

            if not result['satisfied']:
                failed_conditions.append({
                    'condition': condition.to_dict(),
                    'currentValue': result.get('current_value'),
                    'reason': result.get('reason', ''),
                    'delayRemaining': result.get('delay_remaining')
                })

        # Apply logic
        if interlock.condition_logic == 'OR':
            satisfied = any(results) if results else True
            if satisfied:
                failed_conditions = []  # Clear failures if any condition passed
        else:  # AND
            satisfied = all(results) if results else True

        # Track demand (transition from satisfied to not satisfied)
        was_satisfied = self._previous_states.get(interlock.id, True)
        if was_satisfied and not satisfied:
            interlock.demand_count += 1
            interlock.last_demand_time = datetime.now().isoformat()
            self._record_event(interlock, 'demand', 'system', None, {
                'failedConditions': [fc['reason'] for fc in failed_conditions]
            })
        elif not was_satisfied and satisfied:
            self._record_event(interlock, 'cleared', 'system')
            # Clear trip acknowledgment when interlock returns to satisfied
            if interlock.id in self._trip_ack_state:
                del self._trip_ack_state[interlock.id]

        self._previous_states[interlock.id] = satisfied

        return InterlockStatus(
            id=interlock.id,
            name=interlock.name,
            satisfied=satisfied,
            enabled=True,
            bypassed=False,
            failed_conditions=failed_conditions,
            priority=interlock.priority,
            sil_rating=interlock.sil_rating,
            requires_acknowledgment=interlock.requires_acknowledgment,
            trip_acknowledged=ack_state.get('acknowledged', False),
            trip_acknowledged_by=ack_state.get('user'),
            trip_acknowledged_at=ack_state.get('timestamp'),
        )

    # ========================================================================
    # Latch Management
    # ========================================================================

    def arm_latch(self, user: str = "system") -> bool:
        """Arm the safety latch"""
        with self.lock:
            # Check if we can arm
            if self.is_tripped:
                logger.warning("Cannot arm latch - system is tripped")
                return False

            if self._has_failed_interlocks():
                logger.warning("Cannot arm latch - interlocks failed")
                return False

            self.latch_state = LatchState.ARMED
            self._publish_latch_state(user=user)
            logger.info(f"Latch armed by {user}")
            return True

    def disarm_latch(self, user: str = "system"):
        """Disarm the safety latch"""
        with self.lock:
            self.latch_state = LatchState.SAFE
            self._publish_latch_state(user=user)
            logger.info(f"Latch disarmed by {user}")

    def _has_failed_interlocks(self) -> bool:
        """Check if any enabled interlocks have failed"""
        for interlock in self.interlocks.values():
            if interlock.enabled:
                status = self.evaluate_interlock(interlock)
                if not status.satisfied and not status.bypassed:
                    return True
        return False

    def get_failed_interlocks(self) -> List[InterlockStatus]:
        """Get list of failed interlocks"""
        failed = []
        for interlock in self.interlocks.values():
            if interlock.enabled:
                status = self.evaluate_interlock(interlock)
                if not status.satisfied and not status.bypassed:
                    failed.append(status)
        return failed

    # ========================================================================
    # Trip System
    # ========================================================================

    def trip_system(self, reason: str):
        """
        Trip the system - set all outputs to safe state.
        Called when an interlock fails while latch is armed.
        """
        with self.lock:
            logger.critical(f"SYSTEM TRIP: {reason}")

            self.is_tripped = True
            self.last_trip_time = datetime.now().isoformat()
            self.last_trip_reason = reason
            self.latch_state = LatchState.TRIPPED

            config = self.safe_state_config

            # Send atomic safe-state to remote nodes (cRIO) FIRST for fastest response.
            # This is a single MQTT message that triggers hardware.set_safe_state() on
            # the cRIO, rather than relying on individual per-channel output commands.
            if self._trigger_safe_state:
                try:
                    self._trigger_safe_state(reason)
                    logger.warning("TRIP: Atomic safe-state sent to remote nodes")
                except Exception as e:
                    logger.error(f"Failed to send atomic safe-state to remote nodes: {e}")

            # Stop session first
            if config.stop_session and self._stop_session:
                try:
                    self._stop_session()
                    logger.warning("Session stopped due to trip")
                except Exception as e:
                    logger.error(f"Failed to stop session: {e}")

            # Reset digital outputs to OFF
            if config.reset_digital_outputs and self._set_output:
                channels = self._get_all_channels() if self._get_all_channels else {}
                do_channels = config.digital_output_channels if config.digital_output_channels else [
                    name for name, ch in channels.items()
                    if ch.get('channel_type') == 'digital_output'
                ]

                for channel in do_channels:
                    try:
                        self._set_output(channel, 0)
                        logger.warning(f"TRIP: Set {channel} = 0")
                    except Exception as e:
                        logger.error(f"Failed to reset DO {channel}: {e}")

            # Reset analog outputs to safe value
            if config.reset_analog_outputs and self._set_output:
                channels = self._get_all_channels() if self._get_all_channels else {}
                ao_channels = config.analog_output_channels if config.analog_output_channels else [
                    name for name, ch in channels.items()
                    if ch.get('channel_type') == 'analog_output'
                ]

                for channel in ao_channels:
                    try:
                        self._set_output(channel, config.analog_safe_value)
                        logger.warning(f"TRIP: Set {channel} = {config.analog_safe_value}")
                    except Exception as e:
                        logger.error(f"Failed to reset AO {channel}: {e}")

            # Publish trip event
            self._publish_trip_event(reason)
            self._publish_latch_state(tripped=True, trip_reason=reason)

    def reset_trip(self, user: str = "system") -> bool:
        """Reset the trip state (after operator acknowledges and clears interlocks)"""
        with self.lock:
            if self._has_failed_interlocks():
                logger.warning("Cannot reset trip - interlocks still failed")
                return False

            self.is_tripped = False
            self.last_trip_reason = None
            self.latch_state = LatchState.SAFE
            self._publish_latch_state(user=user)
            logger.info(f"Trip reset by {user}")
            return True

    def acknowledge_trip(self, interlock_id: str, user: str, reason: str = "") -> bool:
        """Acknowledge a tripped interlock (IEC 61511 operator response).

        Records that an operator has acknowledged the trip condition for audit trail purposes.
        This does NOT reset the interlock — the underlying condition must clear first.
        """
        with self.lock:
            interlock = self.interlocks.get(interlock_id)
            if not interlock:
                logger.warning(f"Cannot acknowledge trip - interlock {interlock_id} not found")
                return False
            if not interlock.requires_acknowledgment:
                logger.warning(f"Interlock {interlock_id} does not require acknowledgment")
                return False

            self._trip_ack_state[interlock_id] = {
                'acknowledged': True,
                'user': user,
                'timestamp': datetime.now().isoformat(),
                'reason': reason
            }
            self._record_event(interlock, 'trip_acknowledged', user, reason)
            logger.info(f"Trip acknowledged for interlock '{interlock.name}' by {user}")
            return True

    # ========================================================================
    # Interlock Action Execution
    # ========================================================================

    def execute_interlock_actions(self, interlock: Interlock):
        """Execute active control actions for a failed interlock"""
        logger.warning(f"Executing actions for failed interlock: {interlock.name}")

        for control in interlock.controls:
            action_key = f"{interlock.id}-{control.control_type}-{control.channel or ''}"

            # Skip if already executed
            if action_key in self._executed_actions:
                continue

            if control.control_type == 'set_digital_output':
                if control.channel and self._set_output:
                    value = control.set_value if control.set_value is not None else 0
                    logger.warning(f"INTERLOCK: Setting DO {control.channel} to {value}")
                    self._set_output(control.channel, value)
                    self._executed_actions.add(action_key)

            elif control.control_type == 'set_analog_output':
                if control.channel and self._set_output:
                    value = control.set_value if control.set_value is not None else 0
                    logger.warning(f"INTERLOCK: Setting AO {control.channel} to {value}")
                    self._set_output(control.channel, value)
                    self._executed_actions.add(action_key)

            elif control.control_type == 'stop_session':
                if self._stop_session:
                    logger.warning("INTERLOCK: Stopping session")
                    self._stop_session()
                    self._executed_actions.add(action_key)

    def clear_interlock_action_tracking(self, interlock_id: str):
        """Clear executed action tracking when interlock becomes satisfied"""
        keys_to_remove = [k for k in self._executed_actions if k.startswith(f"{interlock_id}-")]
        for key in keys_to_remove:
            self._executed_actions.discard(key)

    # ========================================================================
    # Main Evaluation Loop
    # ========================================================================

    def evaluate_all(self) -> Dict[str, Any]:
        """
        Evaluate all interlocks and update latch state.
        Called periodically from the main DAQ loop.

        Returns status summary for publishing to MQTT.
        """
        with self.lock:
            statuses = []
            any_failed = False

            for interlock in self.interlocks.values():
                status = self.evaluate_interlock(interlock)
                statuses.append(status)

                if status.enabled and not status.satisfied and not status.bypassed:
                    any_failed = True

                    # Execute actions for newly failed interlocks
                    was_satisfied = self._previous_states.get(interlock.id + "_action", True)
                    if was_satisfied:
                        self.execute_interlock_actions(interlock)
                    self._previous_states[interlock.id + "_action"] = False
                else:
                    # Clear action tracking when interlock recovers
                    if not self._previous_states.get(interlock.id + "_action", True):
                        self.clear_interlock_action_tracking(interlock.id)
                    self._previous_states[interlock.id + "_action"] = True

            # Check if we should trip
            if any_failed and self.latch_state == LatchState.ARMED and not self.is_tripped:
                failed = self.get_failed_interlocks()
                reason = f"Interlock failed: {', '.join([f.name for f in failed])}"
                self.trip_system(reason)

            # Collect proof test status for interlocks with intervals
            proof_tests_due = []
            for interlock in self.interlocks.values():
                if interlock.proof_test_interval_days is not None:
                    info = self._compute_proof_test_info(interlock)
                    if info['overdue']:
                        proof_tests_due.append(info)

            return {
                'latchState': self.latch_state.value,
                'isTripped': self.is_tripped,
                'lastTripTime': self.last_trip_time,
                'lastTripReason': self.last_trip_reason,
                'hasFailedInterlocks': any_failed,
                'interlockStatuses': [s.to_dict() for s in statuses],
                'proofTestsDue': proof_tests_due,
                'timestamp': datetime.now().isoformat()
            }

    # ========================================================================
    # Control Blocking Checks
    # ========================================================================

    def is_control_blocked(self, control_type: str, identifier: str = None) -> Dict[str, Any]:
        """Check if a control type is blocked by any interlock"""
        blocked_by = []

        for interlock in self.interlocks.values():
            if not interlock.enabled:
                continue

            status = self.evaluate_interlock(interlock)
            if status.satisfied or status.bypassed:
                continue

            for control in interlock.controls:
                if control.control_type == control_type:
                    if control_type in ('digital_output', 'analog_output') and identifier:
                        if control.channel == identifier:
                            blocked_by.append(status)
                    elif control_type == 'button_action' and identifier:
                        if control.button_id == identifier:
                            blocked_by.append(status)
                    elif control_type not in ('digital_output', 'analog_output', 'button_action'):
                        blocked_by.append(status)

        return {
            'blocked': len(blocked_by) > 0,
            'blockedBy': [b.to_dict() for b in blocked_by]
        }

    def is_output_blocked(self, channel: str) -> Dict[str, Any]:
        """Check if an output channel is blocked"""
        do_result = self.is_control_blocked('digital_output', channel)
        ao_result = self.is_control_blocked('analog_output', channel)

        all_blocked_by = do_result['blockedBy'] + ao_result['blockedBy']
        return {
            'blocked': len(all_blocked_by) > 0,
            'blockedBy': all_blocked_by
        }

    # ========================================================================
    # Safe State Configuration
    # ========================================================================

    def update_safe_state_config(self, config: Dict[str, Any]):
        """Update safe state configuration"""
        with self.lock:
            self.safe_state_config = SafeStateConfig.from_dict(config)
            self._save_safe_state_config()

    # ========================================================================
    # History/Audit Trail
    # ========================================================================

    def _record_event(
        self,
        interlock: Interlock,
        event: str,
        user: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Record an interlock event to the audit trail"""
        entry = InterlockHistoryEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            interlock_id=interlock.id,
            interlock_name=interlock.name,
            event=event,
            user=user,
            reason=reason,
            details=details
        )

        self.history.append(entry)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Save periodically
        if len(self.history) % 10 == 0:
            self._save_history()

        logger.info(f"[Interlock] {event}: {interlock.name}{f' - {reason}' if reason else ''}")

    def get_history(self, limit: int = 100, interlock_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get interlock history entries"""
        entries = self.history.copy()
        if interlock_id:
            entries = [e for e in entries if e.interlock_id == interlock_id]
        entries.reverse()  # Most recent first
        return [e.to_dict() for e in entries[:limit]]

    # ========================================================================
    # Proof Test Scheduling (IEC 61511)
    # ========================================================================

    def record_proof_test(self, interlock_id: str, user: str = "system", result: str = "pass",
                          notes: str = "") -> bool:
        """
        Record that a proof test was performed on an interlock.

        IEC 61511 requires periodic verification that safety interlocks
        will function when demanded. This records the test completion.

        Args:
            interlock_id: The interlock that was tested
            user: Who performed the test
            result: 'pass' or 'fail'
            notes: Optional test notes
        """
        with self.lock:
            interlock = self.interlocks.get(interlock_id)
            if not interlock:
                logger.warning(f"Cannot record proof test: interlock {interlock_id} not found")
                return False

            interlock.last_proof_test = datetime.now().isoformat()
            self._record_event(interlock, 'proof_test', user, notes, {
                'result': result,
                'notes': notes
            })
            self._save_interlocks()

            logger.info(f"Proof test recorded for '{interlock.name}': {result} by {user}")

            if self._publish:
                self._publish('safety/proof_test', {
                    'interlockId': interlock_id,
                    'interlockName': interlock.name,
                    'result': result,
                    'user': user,
                    'notes': notes,
                    'timestamp': interlock.last_proof_test
                })

            return True

    def get_proof_test_status(self, interlock_id: str) -> Optional[Dict[str, Any]]:
        """Get proof test status for a single interlock"""
        interlock = self.interlocks.get(interlock_id)
        if not interlock:
            return None

        return self._compute_proof_test_info(interlock)

    def get_all_proof_test_status(self) -> List[Dict[str, Any]]:
        """Get proof test status for all interlocks that have a test interval configured"""
        results = []
        for interlock in self.interlocks.values():
            if interlock.proof_test_interval_days is not None:
                results.append(self._compute_proof_test_info(interlock))
        return results

    def _compute_proof_test_info(self, interlock: Interlock) -> Dict[str, Any]:
        """Compute proof test scheduling info for an interlock"""
        info = {
            'interlockId': interlock.id,
            'interlockName': interlock.name,
            'intervalDays': interlock.proof_test_interval_days,
            'lastTest': interlock.last_proof_test,
            'nextDue': None,
            'daysUntilDue': None,
            'overdue': False
        }

        if interlock.proof_test_interval_days is None:
            return info

        if interlock.last_proof_test:
            try:
                last_test_dt = datetime.fromisoformat(interlock.last_proof_test)
                next_due_dt = last_test_dt + timedelta(days=interlock.proof_test_interval_days)
                now = datetime.now()
                days_until = (next_due_dt - now).total_seconds() / 86400.0

                info['nextDue'] = next_due_dt.isoformat()
                info['daysUntilDue'] = round(days_until, 1)
                info['overdue'] = days_until < 0
            except (ValueError, TypeError):
                # If last_proof_test is malformed, treat as overdue
                info['overdue'] = True
        else:
            # Never tested — overdue
            info['overdue'] = True

        return info

    def check_proof_tests(self) -> List[Dict[str, Any]]:
        """
        Check all interlocks for overdue proof tests.
        Called periodically (e.g., once per minute from main loop).

        Returns list of overdue interlocks and publishes notifications.
        """
        overdue = []

        with self.lock:
            for interlock in self.interlocks.values():
                if not interlock.enabled:
                    continue
                if interlock.proof_test_interval_days is None:
                    continue

                info = self._compute_proof_test_info(interlock)
                if info['overdue']:
                    overdue.append(info)

        if overdue and self._publish:
            self._publish('safety/proof_tests_due', {
                'count': len(overdue),
                'interlocks': overdue,
                'timestamp': datetime.now().isoformat()
            })

        return overdue

    # ========================================================================
    # MQTT Publishing
    # ========================================================================

    def _publish_latch_state(self, user: str = None, tripped: bool = False, trip_reason: str = None):
        """Publish latch state to MQTT"""
        if not self._publish:
            return

        self._publish('safety/latch/state', {
            'latchId': self.latch_id,
            'state': self.latch_state.value,
            'armed': self.latch_state == LatchState.ARMED,
            'tripped': tripped,
            'tripReason': trip_reason,
            'user': user,
            'timestamp': datetime.now().isoformat()
        })

    def _publish_trip_event(self, reason: str):
        """Publish trip event to MQTT"""
        if not self._publish:
            return

        self._publish('safety/trip', {
            'reason': reason,
            'timestamp': self.last_trip_time,
            'resetDigitalOutputs': self.safe_state_config.reset_digital_outputs,
            'resetAnalogOutputs': self.safe_state_config.reset_analog_outputs,
            'stoppedSession': self.safe_state_config.stop_session
        })

    def _publish_interlock_update(self, interlock: Interlock):
        """Publish interlock update to MQTT"""
        if not self._publish:
            return

        self._publish('interlocks/updated', interlock.to_dict())

    def publish_status(self):
        """Publish full safety status to MQTT"""
        if not self._publish:
            return

        status = self.evaluate_all()
        self._publish('safety/status', status)

    # ========================================================================
    # Persistence
    # ========================================================================

    def _save_interlocks(self):
        """Save interlocks to disk"""
        try:
            path = self.data_dir / 'interlocks.json'
            data = [i.to_dict() for i in self.interlocks.values()]
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving interlocks: {e}")

    def _load_interlocks(self):
        """Load interlocks from disk"""
        try:
            path = self.data_dir / 'interlocks.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                for d in data:
                    interlock = Interlock.from_dict(d)
                    self.interlocks[interlock.id] = interlock
                logger.info(f"Loaded {len(self.interlocks)} interlocks")
        except Exception as e:
            logger.error(f"Error loading interlocks: {e}")

    def _save_safe_state_config(self):
        """Save safe state config to disk"""
        try:
            path = self.data_dir / 'safe_state_config.json'
            with open(path, 'w') as f:
                json.dump(self.safe_state_config.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Error saving safe state config: {e}")

    def _load_safe_state_config(self):
        """Load safe state config from disk"""
        try:
            path = self.data_dir / 'safe_state_config.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                self.safe_state_config = SafeStateConfig.from_dict(data)
                logger.info("Loaded safe state config")
        except Exception as e:
            logger.error(f"Error loading safe state config: {e}")

    def _save_history(self):
        """Save interlock history to disk"""
        try:
            path = self.data_dir / 'interlock_history.json'
            data = [e.to_dict() for e in self.history[-500:]]  # Save last 500
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving interlock history: {e}")

    def _load_history(self):
        """Load interlock history from disk"""
        try:
            path = self.data_dir / 'interlock_history.json'
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                for d in data:
                    entry = InterlockHistoryEntry(
                        id=d.get('id', str(uuid.uuid4())),
                        timestamp=d.get('timestamp', ''),
                        interlock_id=d.get('interlockId', d.get('interlock_id', '')),
                        interlock_name=d.get('interlockName', d.get('interlock_name', '')),
                        event=d.get('event', ''),
                        user=d.get('user'),
                        reason=d.get('reason'),
                        details=d.get('details')
                    )
                    self.history.append(entry)
                logger.info(f"Loaded {len(self.history)} interlock history entries")
        except Exception as e:
            logger.error(f"Error loading interlock history: {e}")

    def save_all(self):
        """Save all state to disk"""
        with self.lock:
            self._save_interlocks()
            self._save_safe_state_config()
            self._save_history()

    def clear_all(self):
        """Clear all safety state"""
        with self.lock:
            self.interlocks.clear()
            self.history.clear()
            self._previous_states.clear()
            self._condition_delay_state.clear()
            self._executed_actions.clear()
            self.latch_state = LatchState.SAFE
            self.is_tripped = False
            self.last_trip_time = None
            self.last_trip_reason = None
            self._save_interlocks()
            self._save_history()
            logger.info("Safety manager cleared")
