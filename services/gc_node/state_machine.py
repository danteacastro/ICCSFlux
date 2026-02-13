"""
State Machine for GC Node

Simplified 3-state machine for read-only GC bridge:
- IDLE: Not connected to data sources
- ACQUIRING: Actively reading/watching for GC data
- ERROR: Data source error (auto-retry)

No SESSION state — GC node is read-only, no output locks needed.
"""

from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional
import logging

logger = logging.getLogger('GCNode')


class State(Enum):
    IDLE = auto()
    ACQUIRING = auto()
    ANALYZING = auto()
    ERROR = auto()


VALID_TRANSITIONS = {
    (State.IDLE, State.ACQUIRING): True,
    (State.IDLE, State.IDLE): True,
    (State.IDLE, State.ERROR): True,
    (State.ACQUIRING, State.IDLE): True,
    (State.ACQUIRING, State.ACQUIRING): True,
    (State.ACQUIRING, State.ANALYZING): True,
    (State.ACQUIRING, State.ERROR): True,
    (State.ANALYZING, State.ACQUIRING): True,
    (State.ANALYZING, State.IDLE): True,
    (State.ANALYZING, State.ERROR): True,
    (State.ANALYZING, State.ANALYZING): True,
    (State.ERROR, State.IDLE): True,
    (State.ERROR, State.ACQUIRING): True,
    (State.ERROR, State.ERROR): True,
}


class StateTransition:
    """Manages state transitions with validation and callbacks."""

    def __init__(self, initial_state: State = State.IDLE):
        self._state = initial_state
        self._enter_callbacks: Dict[State, List[Callable]] = {s: [] for s in State}
        self._exit_callbacks: Dict[State, List[Callable]] = {s: [] for s in State}
        self._last_error: str = ""

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_acquiring(self) -> bool:
        return self._state == State.ACQUIRING

    @property
    def is_analyzing(self) -> bool:
        return self._state == State.ANALYZING

    @property
    def is_error(self) -> bool:
        return self._state == State.ERROR

    @property
    def last_error(self) -> str:
        return self._last_error

    def on_enter(self, state: State, callback: Callable):
        self._enter_callbacks[state].append(callback)

    def on_exit(self, state: State, callback: Callable):
        self._exit_callbacks[state].append(callback)

    def can_transition(self, to_state: State) -> bool:
        return VALID_TRANSITIONS.get((self._state, to_state), False)

    def to(self, new_state: State, payload: Optional[Dict[str, Any]] = None) -> bool:
        old_state = self._state

        if not self.can_transition(new_state):
            logger.warning(f"Invalid state transition: {old_state.name} -> {new_state.name}")
            return False

        if old_state == new_state:
            return True

        for callback in self._exit_callbacks[old_state]:
            try:
                callback(old_state, new_state, payload)
            except Exception as e:
                logger.error(f"Exit callback error ({old_state.name}): {e}")

        if new_state == State.ERROR and payload:
            self._last_error = payload.get('error', 'Unknown error')

        self._state = new_state
        logger.info(f"State transition: {old_state.name} -> {new_state.name}")

        for callback in self._enter_callbacks[new_state]:
            try:
                callback(old_state, new_state, payload)
            except Exception as e:
                logger.error(f"Enter callback error ({new_state.name}): {e}")

        return True

    def get_status(self) -> Dict[str, Any]:
        status = {
            'state': self._state.name,
            'acquiring': self.is_acquiring,
            'analyzing': self.is_analyzing,
        }
        if self.is_error:
            status['last_error'] = self._last_error
        return status
