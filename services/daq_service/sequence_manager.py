"""
Sequence Manager for NISystem

Manages automation sequences that execute server-side, surviving browser
disconnects and enabling headless operation.

Sequences consist of steps like:
- Set output values
- Wait for duration
- Wait for condition
- Start/stop recording
- Loop sections
- Conditional branching
"""

import json
import time
import threading
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger('SequenceManager')


class StepTimeoutError(Exception):
    """Raised when a sequence step (e.g., WAIT_CONDITION) times out.
    Caught by the execution loop to mark the sequence as ERROR instead of
    silently continuing to the next step."""
    pass

class SequenceState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"

class StepType(str, Enum):
    SET_OUTPUT = "setOutput"
    WAIT_DURATION = "waitDuration"
    WAIT_CONDITION = "waitCondition"
    START_RECORDING = "startRecording"
    STOP_RECORDING = "stopRecording"
    START_ACQUISITION = "startAcquisition"
    STOP_ACQUISITION = "stopAcquisition"
    LOG_MESSAGE = "logMessage"
    TRIGGER_ALARM = "triggerAlarm"
    LOOP_START = "loopStart"
    LOOP_END = "loopEnd"
    CONDITIONAL = "conditional"
    CALL_SEQUENCE = "callSequence"

@dataclass
class SequenceStep:
    """A single step in a sequence"""
    type: str
    label: Optional[str] = None
    # For setOutput
    channel: Optional[str] = None
    value: Optional[Any] = None
    # For waitDuration
    duration_ms: Optional[int] = None
    # For waitCondition
    condition_channel: Optional[str] = None
    condition_operator: Optional[str] = None  # ==, !=, <, >, <=, >=
    condition_value: Optional[Any] = None
    condition_timeout_ms: Optional[int] = None
    # For recording
    recording_filename: Optional[str] = None
    # For logging
    message: Optional[str] = None
    # For loops
    loop_count: Optional[int] = None
    loop_id: Optional[str] = None
    # For conditionals
    true_step_index: Optional[int] = None
    false_step_index: Optional[int] = None
    # For call sequence
    sequence_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> 'SequenceStep':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

@dataclass
class Sequence:
    """A complete automation sequence"""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    steps: List[SequenceStep] = field(default_factory=list)
    # Runtime state
    state: SequenceState = SequenceState.IDLE
    current_step_index: int = 0
    start_time: Optional[float] = None
    paused_time: Optional[float] = None
    error_message: Optional[str] = None
    # Loop tracking
    loop_counters: Dict[str, int] = field(default_factory=dict)
    loop_start_indices: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "steps": [s.to_dict() for s in self.steps],
            "state": self.state.value if isinstance(self.state, SequenceState) else self.state,
            "current_step_index": self.current_step_index,
            "start_time": self.start_time,
            "paused_time": self.paused_time,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Sequence':
        steps = [SequenceStep.from_dict(s) for s in data.get("steps", [])]
        state = data.get("state", "idle")
        if isinstance(state, str):
            state = SequenceState(state)
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            steps=steps,
            state=state,
            current_step_index=data.get("current_step_index", 0),
            start_time=data.get("start_time"),
            paused_time=data.get("paused_time"),
            error_message=data.get("error_message")
        )

class SequenceManager:
    """
    Manages sequence execution server-side.

    Callbacks:
    - on_set_output(channel, value): Called to set an output channel
    - on_start_recording(filename): Called to start recording
    - on_stop_recording(): Called to stop recording
    - on_start_acquisition(): Called to start acquisition
    - on_stop_acquisition(): Called to stop acquisition
    - on_get_channel_value(channel): Called to get current channel value
    - on_sequence_event(event_type, sequence): Called on sequence state changes
    """

    MAX_SEQUENCES = 50              # Security Compliance resource limit
    MAX_STEPS_PER_SEQUENCE = 500    # Security Compliance resource limit
    MAX_LOOP_ITERATIONS = 100000    # Hard cap to prevent runaway loops
                                    # (1000 iter/sec for ~100s before forced exit)

    def __init__(self, sequences_file: Optional[str] = None):
        self.sequences: Dict[str, Sequence] = {}
        self.sequences_file = sequences_file or self._get_default_sequences_file()

        # Callbacks
        self.on_set_output: Optional[Callable[[str, Any], None]] = None
        self.on_start_recording: Optional[Callable[[Optional[str]], None]] = None
        self.on_stop_recording: Optional[Callable[[], None]] = None
        self.on_start_acquisition: Optional[Callable[[], None]] = None
        self.on_stop_acquisition: Optional[Callable[[], None]] = None
        self.on_get_channel_value: Optional[Callable[[str], Any]] = None
        self.on_sequence_event: Optional[Callable[[str, Sequence], None]] = None
        self.on_log_message: Optional[Callable[[str], None]] = None

        # Execution thread
        self._running_sequence_id: Optional[str] = None
        self._execution_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Start unpaused

        self._lock = threading.Lock()

        # Load saved sequences
        self._load_sequences()

    def _get_default_sequences_file(self) -> str:
        """Get default path for sequences file"""
        service_dir = Path(__file__).parent
        project_root = service_dir.parent.parent
        return str(project_root / "config" / "sequences.json")

    def _load_sequences(self):
        """Load sequences from file"""
        try:
            path = Path(self.sequences_file)
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                    for seq_data in data.get("sequences", []):
                        seq = Sequence.from_dict(seq_data)
                        # Reset runtime state on load
                        seq.state = SequenceState.IDLE
                        seq.current_step_index = 0
                        seq.start_time = None
                        seq.paused_time = None
                        seq.error_message = None
                        seq.loop_counters = {}
                        seq.loop_start_indices = {}
                        self.sequences[seq.id] = seq
                logger.info(f"Loaded {len(self.sequences)} sequences from {self.sequences_file}")
        except Exception as e:
            logger.warning(f"Could not load sequences: {e}")

    def _save_sequences(self):
        """Save sequences to file"""
        try:
            path = Path(self.sequences_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "sequences": [seq.to_dict() for seq in self.sequences.values()]
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self.sequences)} sequences")
        except Exception as e:
            logger.error(f"Could not save sequences: {e}")

    def add_sequence(self, sequence: Sequence) -> bool:
        """Add or update a sequence"""
        with self._lock:
            # Enforce step limit per sequence
            if len(sequence.steps) > self.MAX_STEPS_PER_SEQUENCE:
                logger.warning(f"Sequence '{sequence.name}' has {len(sequence.steps)} steps, "
                               f"exceeds limit of {self.MAX_STEPS_PER_SEQUENCE}")
                return False

            # Enforce total sequence count (allow updates to existing)
            if sequence.id not in self.sequences and len(self.sequences) >= self.MAX_SEQUENCES:
                logger.warning(f"Sequence limit reached ({self.MAX_SEQUENCES}), "
                               f"cannot add '{sequence.name}'")
                return False

            self.sequences[sequence.id] = sequence
            self._save_sequences()
            logger.info(f"Added sequence: {sequence.name} ({sequence.id})")
            return True

    def remove_sequence(self, sequence_id: str) -> bool:
        """Remove a sequence"""
        with self._lock:
            if sequence_id in self.sequences:
                # Can't remove running sequence
                if self._running_sequence_id == sequence_id:
                    return False
                del self.sequences[sequence_id]
                self._save_sequences()
                logger.info(f"Removed sequence: {sequence_id}")
                return True
            return False

    def get_sequence(self, sequence_id: str) -> Optional[Sequence]:
        """Get a sequence by ID"""
        return self.sequences.get(sequence_id)

    def get_all_sequences(self) -> List[Sequence]:
        """Get all sequences"""
        return list(self.sequences.values())

    def get_running_sequence(self) -> Optional[Sequence]:
        """Get currently running sequence"""
        if self._running_sequence_id:
            return self.sequences.get(self._running_sequence_id)
        return None

    def start_sequence(self, sequence_id: str) -> bool:
        """Start executing a sequence"""
        with self._lock:
            seq = self.sequences.get(sequence_id)
            if not seq:
                logger.error(f"Sequence not found: {sequence_id}")
                return False

            if not seq.enabled:
                logger.warning(f"Sequence is disabled: {seq.name}")
                return False

            if self._running_sequence_id:
                logger.warning(f"Another sequence is running: {self._running_sequence_id}")
                return False

            # Initialize sequence state
            seq.state = SequenceState.RUNNING
            seq.current_step_index = 0
            seq.start_time = time.time()
            seq.paused_time = None
            seq.error_message = None
            seq.loop_counters = {}
            seq.loop_start_indices = {}

            self._running_sequence_id = sequence_id
            self._stop_event.clear()
            self._pause_event.set()

            # Start execution thread
            self._execution_thread = threading.Thread(
                target=self._execute_sequence,
                args=(seq,),
                daemon=True
            )
            self._execution_thread.start()

            logger.info(f"Started sequence: {seq.name}")
            self._emit_event("started", seq)
            return True

    def pause_sequence(self, sequence_id: str) -> bool:
        """Pause a running sequence.

        Callbacks (_emit_event) fire OUTSIDE the lock to prevent deadlock
        if a listener tries to acquire the lock or holds another lock that
        would lead to inversion.
        """
        seq_to_emit = None
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False

            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.PAUSED
                seq.paused_time = time.time()
                self._pause_event.clear()
                logger.info(f"Paused sequence: {seq.name}")
                seq_to_emit = seq
            else:
                return False
        if seq_to_emit is not None:
            self._emit_event("paused", seq_to_emit)
        return True

    def resume_sequence(self, sequence_id: str) -> bool:
        """Resume a paused sequence. _emit_event called outside lock."""
        seq_to_emit = None
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False

            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.PAUSED:
                seq.state = SequenceState.RUNNING
                seq.paused_time = None
                self._pause_event.set()
                logger.info(f"Resumed sequence: {seq.name}")
                seq_to_emit = seq
            else:
                return False
        if seq_to_emit is not None:
            self._emit_event("resumed", seq_to_emit)
        return True

    def abort_sequence(self, sequence_id: str) -> bool:
        """Abort a running or paused sequence"""
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False

            seq = self.sequences.get(sequence_id)
            if seq and seq.state in (SequenceState.RUNNING, SequenceState.PAUSED):
                seq.state = SequenceState.ABORTED
                self._stop_event.set()
                self._pause_event.set()  # Unblock if paused
                logger.info(f"Aborted sequence: {seq.name}")
                self._emit_event("aborted", seq)
                return True
            return False

    def _execute_sequence(self, seq: Sequence):
        """Execute sequence steps in a thread"""
        try:
            while seq.current_step_index < len(seq.steps):
                # Check for stop
                if self._stop_event.is_set():
                    break

                # Wait if paused
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                step = seq.steps[seq.current_step_index]

                try:
                    self._execute_step(seq, step)
                except Exception as e:
                    logger.error(f"Step execution error: {e}")
                    seq.state = SequenceState.ERROR
                    seq.error_message = str(e)
                    self._emit_event("error", seq)
                    break

                # Move to next step (unless step changed it, e.g., loop)
                if seq.state == SequenceState.RUNNING:
                    seq.current_step_index += 1
                    self._emit_event("stepCompleted", seq)

            # Sequence completed
            if seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.COMPLETED
                logger.info(f"Sequence completed: {seq.name}")
                self._emit_event("completed", seq)

        except Exception as e:
            logger.error(f"Sequence execution error: {e}")
            seq.state = SequenceState.ERROR
            seq.error_message = str(e)
            self._emit_event("error", seq)

        finally:
            with self._lock:
                self._running_sequence_id = None

    def _execute_step(self, seq: Sequence, step: SequenceStep):
        """Execute a single step"""
        step_type = step.type

        if step_type == StepType.SET_OUTPUT.value:
            if self.on_set_output and step.channel is not None:
                self.on_set_output(step.channel, step.value)
                logger.debug(f"Set {step.channel} = {step.value}")

        elif step_type == StepType.WAIT_DURATION.value:
            duration_s = (step.duration_ms or 0) / 1000.0
            self._wait_with_check(duration_s)

        elif step_type == StepType.WAIT_CONDITION.value:
            self._wait_for_condition(step)

        elif step_type == StepType.START_RECORDING.value:
            if self.on_start_recording:
                self.on_start_recording(step.recording_filename)

        elif step_type == StepType.STOP_RECORDING.value:
            if self.on_stop_recording:
                self.on_stop_recording()

        elif step_type == StepType.START_ACQUISITION.value:
            if self.on_start_acquisition:
                self.on_start_acquisition()

        elif step_type == StepType.STOP_ACQUISITION.value:
            if self.on_stop_acquisition:
                self.on_stop_acquisition()

        elif step_type == StepType.LOG_MESSAGE.value:
            if self.on_log_message and step.message:
                self.on_log_message(step.message)
            logger.info(f"Sequence log: {step.message}")

        elif step_type == StepType.LOOP_START.value:
            loop_id = step.loop_id or f"loop_{seq.current_step_index}"
            if loop_id not in seq.loop_counters:
                seq.loop_counters[loop_id] = 0
                seq.loop_start_indices[loop_id] = seq.current_step_index

        elif step_type == StepType.LOOP_END.value:
            loop_id = step.loop_id or f"loop_{seq.current_step_index}"
            if loop_id not in seq.loop_counters:
                # LOOP_END without matching LOOP_START — log and skip to avoid hang.
                logger.warning(
                    f"[SEQUENCE {seq.name}] LOOP_END at step {seq.current_step_index} "
                    f"has no matching LOOP_START (loop_id={loop_id!r}) — skipping"
                )
            else:
                seq.loop_counters[loop_id] += 1
                # Cap requested iterations at MAX_LOOP_ITERATIONS to prevent runaway loops
                requested = step.loop_count or 1
                if requested > self.MAX_LOOP_ITERATIONS:
                    logger.warning(
                        f"[SEQUENCE {seq.name}] Loop count {requested} exceeds "
                        f"MAX_LOOP_ITERATIONS={self.MAX_LOOP_ITERATIONS} — capping"
                    )
                loop_count = min(requested, self.MAX_LOOP_ITERATIONS)
                if seq.loop_counters[loop_id] < loop_count:
                    # Jump back to loop start
                    seq.current_step_index = seq.loop_start_indices[loop_id]
                else:
                    # Loop complete, clean up
                    del seq.loop_counters[loop_id]
                    del seq.loop_start_indices[loop_id]

        elif step_type == StepType.CONDITIONAL.value:
            condition_met = self._evaluate_condition(step)
            target_index = None
            if condition_met and step.true_step_index is not None:
                target_index = step.true_step_index
            elif not condition_met and step.false_step_index is not None:
                target_index = step.false_step_index
            if target_index is not None:
                # Validate bounds — bad index would silently terminate sequence
                # (the while loop exits when current_step_index >= len(steps)).
                if target_index < 0 or target_index >= len(seq.steps):
                    logger.error(
                        f"[SEQUENCE {seq.name}] CONDITIONAL step jumps to invalid "
                        f"index {target_index} (sequence has {len(seq.steps)} steps) "
                        f"— skipping jump"
                    )
                else:
                    seq.current_step_index = target_index - 1  # -1 because we'll increment

        elif step_type == StepType.CALL_SEQUENCE.value:
            # Note: nested sequences not implemented yet
            logger.warning(f"Call sequence not implemented: {step.sequence_id}")

    def _wait_with_check(self, duration_s: float):
        """Wait for duration, checking for stop/pause"""
        end_time = time.time() + duration_s
        while time.time() < end_time:
            if self._stop_event.is_set():
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            time.sleep(0.1)

    def _wait_for_condition(self, step: SequenceStep):
        """Wait for a condition to be met.

        Raises StepTimeoutError if the condition isn't met within the
        configured timeout. Previously it just logged a warning and let
        the sequence continue as if the condition had been satisfied —
        which silently moved Mike's equipment to the wrong state.
        """
        if not self.on_get_channel_value:
            raise StepTimeoutError(
                f"WAIT_CONDITION step has no channel-value callback registered"
            )
        if not step.condition_channel:
            raise StepTimeoutError(
                f"WAIT_CONDITION step is missing condition_channel"
            )

        timeout_s = (step.condition_timeout_ms or 30000) / 1000.0
        end_time = time.time() + timeout_s

        while time.time() < end_time:
            if self._stop_event.is_set():
                return  # Aborted, not a timeout
            self._pause_event.wait()
            if self._stop_event.is_set():
                return

            if self._evaluate_condition(step):
                return  # Condition satisfied

            time.sleep(0.1)

        # Timeout fired — raise so the execution loop can mark the sequence
        # as ERROR instead of silently proceeding to the next step.
        raise StepTimeoutError(
            f"Condition timeout after {timeout_s}s: "
            f"{step.condition_channel} {step.condition_operator} {step.condition_value}"
        )

    def _evaluate_condition(self, step: SequenceStep) -> bool:
        """Evaluate a condition"""
        if not self.on_get_channel_value or not step.condition_channel:
            return True

        current_value = self.on_get_channel_value(step.condition_channel)
        if current_value is None:
            return False

        target = step.condition_value
        op = step.condition_operator or "=="

        try:
            if op == "==":
                return current_value == target
            elif op == "!=":
                return current_value != target
            elif op == "<":
                return float(current_value) < float(target)
            elif op == ">":
                return float(current_value) > float(target)
            elif op == "<=":
                return float(current_value) <= float(target)
            elif op == ">=":
                return float(current_value) >= float(target)
        except (ValueError, TypeError):
            return False

        return False

    def _emit_event(self, event_type: str, seq: Sequence):
        """Emit a sequence event"""
        if self.on_sequence_event:
            try:
                self.on_sequence_event(event_type, seq)
            except Exception as e:
                logger.error(f"Error in sequence event handler: {e}")

    def get_status(self) -> dict:
        """Get sequence manager status"""
        running = self.get_running_sequence()
        return {
            "sequence_count": len(self.sequences),
            "running_sequence_id": self._running_sequence_id,
            "running_sequence_name": running.name if running else None,
            "running_sequence_state": running.state.value if running else None,
            "running_sequence_step": running.current_step_index if running else None,
            "running_sequence_total_steps": len(running.steps) if running else None,
            "running_sequence_progress": (
                round(running.current_step_index / len(running.steps) * 100)
                if running and running.steps else 0
            )
        }

    def shutdown(self):
        """Shutdown the sequence manager"""
        if self._running_sequence_id:
            self.abort_sequence(self._running_sequence_id)
        self._save_sequences()
        logger.info("Sequence manager shutdown")
