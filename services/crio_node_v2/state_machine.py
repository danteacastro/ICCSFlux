"""
State Machine for cRIO Node V2

States:
- IDLE: Not acquiring, outputs at safe state
- ACQUIRING: Reading channels, publishing values
- SESSION: Acquiring + session active + output locks enforced

State transitions are explicit and validated.
Invalid transitions are rejected with logging.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger('cRIONode')

class State(Enum):
    """cRIO operational states."""
    IDLE = auto()
    ACQUIRING = auto()
    SESSION = auto()

# Valid state transitions: (from_state, to_state) -> allowed
VALID_TRANSITIONS = {
    # From IDLE
    (State.IDLE, State.ACQUIRING): True,
    (State.IDLE, State.SESSION): False,  # Must acquire first
    (State.IDLE, State.IDLE): True,  # No-op

    # From ACQUIRING
    (State.ACQUIRING, State.IDLE): True,
    (State.ACQUIRING, State.SESSION): True,
    (State.ACQUIRING, State.ACQUIRING): True,  # No-op

    # From SESSION
    (State.SESSION, State.IDLE): True,  # Stops session and acquisition
    (State.SESSION, State.ACQUIRING): True,  # Stops session, keeps acquiring
    (State.SESSION, State.SESSION): True,  # No-op
}

@dataclass
class SessionInfo:
    """Session state information."""
    name: str = ''
    operator: str = ''
    start_time: float = 0.0
    locked_outputs: List[str] = None
    timeout_minutes: float = 0.0
    test_id: str = ''
    description: str = ''
    operator_notes: str = ''

    def __post_init__(self):
        if self.locked_outputs is None:
            self.locked_outputs = []

class StateTransition:
    """
    Manages state transitions with validation and callbacks.

    Usage:
        transition = StateTransition()

        # Register callbacks
        transition.on_enter(State.ACQUIRING, start_hardware)
        transition.on_exit(State.SESSION, stop_session)

        # Attempt transition
        success = transition.to(State.ACQUIRING)
    """

    def __init__(self, initial_state: State = State.IDLE):
        self._state = initial_state
        self._session = SessionInfo()
        self._enter_callbacks: Dict[State, List[callable]] = {s: [] for s in State}
        self._exit_callbacks: Dict[State, List[callable]] = {s: [] for s in State}

    @property
    def state(self) -> State:
        """Current state (read-only)."""
        return self._state

    @property
    def session(self) -> SessionInfo:
        """Current session info (read-only)."""
        return self._session

    @property
    def is_acquiring(self) -> bool:
        """True if in ACQUIRING or SESSION state."""
        return self._state in (State.ACQUIRING, State.SESSION)

    @property
    def is_session_active(self) -> bool:
        """True if in SESSION state."""
        return self._state == State.SESSION

    def on_enter(self, state: State, callback: callable):
        """Register callback for entering a state."""
        self._enter_callbacks[state].append(callback)

    def on_exit(self, state: State, callback: callable):
        """Register callback for exiting a state."""
        self._exit_callbacks[state].append(callback)

    def can_transition(self, to_state: State) -> bool:
        """Check if transition is valid without executing it."""
        return VALID_TRANSITIONS.get((self._state, to_state), False)

    def to(self, new_state: State, payload: Optional[Dict[str, Any]] = None) -> bool:
        """
        Attempt state transition.

        Args:
            new_state: Target state
            payload: Optional data for transition (e.g., session config)

        Returns:
            True if transition succeeded, False if rejected
        """
        old_state = self._state

        # Check if transition is valid
        if not self.can_transition(new_state):
            logger.warning(f"Invalid state transition: {old_state.name} -> {new_state.name}")
            return False

        # No-op if same state
        if old_state == new_state:
            return True

        # Execute exit callbacks for old state
        for callback in self._exit_callbacks[old_state]:
            try:
                callback(old_state, new_state, payload)
            except Exception as e:
                logger.error(f"Exit callback error ({old_state.name}): {e}")

        # Handle session-specific logic
        if new_state == State.SESSION:
            self._start_session(payload or {})
        elif old_state == State.SESSION:
            self._end_session()

        # Update state
        self._state = new_state
        logger.info(f"State transition: {old_state.name} -> {new_state.name}")

        # Execute enter callbacks for new state
        for callback in self._enter_callbacks[new_state]:
            try:
                callback(old_state, new_state, payload)
            except Exception as e:
                logger.error(f"Enter callback error ({new_state.name}): {e}")

        return True

    def _start_session(self, payload: Dict[str, Any]):
        """Initialize session state."""
        import time
        self._session = SessionInfo(
            name=payload.get('name', ''),
            operator=payload.get('operator', ''),
            start_time=time.time(),
            locked_outputs=payload.get('locked_outputs', []),
            timeout_minutes=payload.get('timeout_minutes', 0.0),
            test_id=payload.get('test_id', ''),
            description=payload.get('description', ''),
            operator_notes=payload.get('operator_notes', ''),
        )
        logger.info(f"Session started: {self._session.name} by {self._session.operator} (test_id={self._session.test_id})")

    def _end_session(self):
        """Clear session state."""
        import time
        if self._session.start_time:
            duration = time.time() - self._session.start_time
            logger.info(f"Session ended: {self._session.name} after {duration:.1f}s")
        self._session = SessionInfo()

    def is_output_locked(self, channel: str) -> bool:
        """Check if output is locked by current session."""
        if self._state != State.SESSION:
            return False
        return channel in self._session.locked_outputs

    def get_status(self) -> Dict[str, Any]:
        """Get current state as dictionary for MQTT publishing."""
        import time
        status = {
            'state': self._state.name,
            'acquiring': self.is_acquiring,
            'session_active': self.is_session_active,
        }

        if self.is_session_active:
            status.update({
                'session_name': self._session.name,
                'session_operator': self._session.operator,
                'session_start_time': self._session.start_time,
                'session_duration_s': time.time() - self._session.start_time,
                'locked_outputs': self._session.locked_outputs,
                'test_id': self._session.test_id,
                'description': self._session.description,
                'operator_notes': self._session.operator_notes,
            })

        return status
