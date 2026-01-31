"""
DAQ Service State Machine

States:
- STOPPED: Not acquiring, safe state
- INITIALIZING: Starting up acquisition (config reload, hardware init)
- RUNNING: Actively acquiring data
- STOPPING: Shutting down acquisition (cleanup, cascade stops)

State transitions are explicit and validated.
Invalid transitions are rejected with logging.

Adapted from cRIO node V2 state machine pattern.
"""

from enum import Enum, auto
from typing import Optional, Dict, Any, List, Callable
import logging
import threading

logger = logging.getLogger('DAQService')


class DAQState(Enum):
    """DAQ acquisition lifecycle states."""
    STOPPED = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    STOPPING = auto()


# Valid state transitions: (from_state, to_state) -> allowed
VALID_TRANSITIONS = {
    # From STOPPED
    (DAQState.STOPPED, DAQState.STOPPED): True,        # No-op
    (DAQState.STOPPED, DAQState.INITIALIZING): True,   # Normal start command
    (DAQState.STOPPED, DAQState.RUNNING): True,        # Direct start (script/scheduler/cRIO sync)

    # From INITIALIZING
    (DAQState.INITIALIZING, DAQState.INITIALIZING): True,  # No-op
    (DAQState.INITIALIZING, DAQState.RUNNING): True,       # Start successful
    (DAQState.INITIALIZING, DAQState.STOPPED): True,       # Rollback on error

    # From RUNNING
    (DAQState.RUNNING, DAQState.RUNNING): True,        # No-op
    (DAQState.RUNNING, DAQState.STOPPING): True,       # Normal stop command
    (DAQState.RUNNING, DAQState.STOPPED): True,        # Direct stop (script/scheduler/cRIO sync)

    # From STOPPING
    (DAQState.STOPPING, DAQState.STOPPING): True,      # No-op
    (DAQState.STOPPING, DAQState.STOPPED): True,       # Stop complete
}


class DAQStateMachine:
    """
    Thread-safe state machine for DAQ acquisition lifecycle.

    All state transitions are validated against VALID_TRANSITIONS.
    Enter/exit callbacks are fired on valid transitions.
    The internal lock ensures atomicity of check-and-set operations.

    Usage:
        sm = DAQStateMachine()
        sm.on_enter(DAQState.RUNNING, start_engines)
        sm.on_exit(DAQState.RUNNING, stop_engines)
        success = sm.to(DAQState.INITIALIZING)
    """

    def __init__(self, initial_state: DAQState = DAQState.STOPPED):
        self._state = initial_state
        self._lock = threading.Lock()
        self._enter_callbacks: Dict[DAQState, List[Callable]] = {s: [] for s in DAQState}
        self._exit_callbacks: Dict[DAQState, List[Callable]] = {s: [] for s in DAQState}

    @property
    def state(self) -> DAQState:
        """Current state (read-only)."""
        return self._state

    @property
    def is_acquiring(self) -> bool:
        """True if in RUNNING or INITIALIZING state."""
        return self._state in (DAQState.RUNNING, DAQState.INITIALIZING)

    @property
    def acquisition_state(self) -> str:
        """Current state as lowercase string for status publishing."""
        return self._state.name.lower()

    def on_enter(self, state: DAQState, callback: Callable):
        """Register callback for entering a state.

        Callback signature: callback(old_state, new_state, payload)
        """
        self._enter_callbacks[state].append(callback)

    def on_exit(self, state: DAQState, callback: Callable):
        """Register callback for exiting a state.

        Callback signature: callback(old_state, new_state, payload)
        """
        self._exit_callbacks[state].append(callback)

    def can_transition(self, to_state: DAQState) -> bool:
        """Check if transition is valid without executing it."""
        return VALID_TRANSITIONS.get((self._state, to_state), False)

    def to(self, new_state: DAQState, payload: Optional[Dict[str, Any]] = None) -> bool:
        """
        Attempt state transition (thread-safe).

        Args:
            new_state: Target state
            payload: Optional data passed to callbacks

        Returns:
            True if transition succeeded, False if rejected
        """
        with self._lock:
            old_state = self._state

            # Check if transition is valid
            if not self.can_transition(new_state):
                logger.warning(f"[STATE] Invalid transition: {old_state.name} -> {new_state.name}")
                return False

            # No-op if same state
            if old_state == new_state:
                return True

            # Execute exit callbacks for old state
            for callback in self._exit_callbacks[old_state]:
                try:
                    callback(old_state, new_state, payload)
                except Exception as e:
                    logger.error(f"[STATE] Exit callback error ({old_state.name}): {e}")

            # Update state
            self._state = new_state
            logger.info(f"[STATE] {old_state.name} -> {new_state.name}")

            # Execute enter callbacks for new state
            for callback in self._enter_callbacks[new_state]:
                try:
                    callback(old_state, new_state, payload)
                except Exception as e:
                    logger.error(f"[STATE] Enter callback error ({new_state.name}): {e}")

            return True

    def force_state(self, new_state: DAQState):
        """Force state without validation (shutdown/emergency only)."""
        with self._lock:
            old = self._state
            self._state = new_state
            if old != new_state:
                logger.info(f"[STATE] Forced: {old.name} -> {new_state.name}")

    def get_status(self) -> Dict[str, Any]:
        """Get current state as dictionary for MQTT publishing."""
        return {
            'state': self._state.name,
            'acquiring': self.is_acquiring,
            'acquisition_state': self.acquisition_state,
        }
