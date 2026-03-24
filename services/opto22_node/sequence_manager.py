"""
Sequence Manager for Opto22 Node

Server-side sequence execution that survives browser disconnection:
- Step types: set output, wait duration, wait condition, log, loop
- Pause/resume/abort control
- Condition evaluation with timeout
- Loop support with counters

Extracted from the Opto22 monolithic node.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger('Opto22Node.Sequences')

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
    LOG_MESSAGE = "logMessage"
    LOOP_START = "loopStart"
    LOOP_END = "loopEnd"

@dataclass
class SequenceStep:
    type: str
    label: Optional[str] = None
    channel: Optional[str] = None
    value: Optional[Any] = None
    duration_ms: Optional[int] = None
    condition_channel: Optional[str] = None
    condition_operator: Optional[str] = None
    condition_value: Optional[Any] = None
    condition_timeout_ms: Optional[int] = None
    message: Optional[str] = None
    loop_count: Optional[int] = None
    loop_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'SequenceStep':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

@dataclass
class Sequence:
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    steps: List[SequenceStep] = field(default_factory=list)
    state: SequenceState = SequenceState.IDLE
    current_step_index: int = 0
    start_time: Optional[float] = None
    loop_counters: Dict[str, int] = field(default_factory=dict)
    loop_start_indices: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "state": self.state.value, "current_step_index": self.current_step_index}

    @classmethod
    def from_dict(cls, data: dict) -> 'Sequence':
        steps = [SequenceStep.from_dict(s) for s in data.get("steps", [])]
        return cls(id=data["id"], name=data["name"], steps=steps, enabled=data.get("enabled", True))

class SequenceManager:
    def __init__(self):
        self.sequences: Dict[str, Sequence] = {}
        self.on_set_output: Optional[Callable[[str, Any], None]] = None
        self.on_get_channel_value: Optional[Callable[[str], Any]] = None
        self.on_sequence_event: Optional[Callable[[str, Sequence], None]] = None
        self._running_sequence_id: Optional[str] = None
        self._execution_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._lock = threading.Lock()

    def add_sequence(self, sequence: Sequence) -> bool:
        with self._lock:
            self.sequences[sequence.id] = sequence
            return True

    def start_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            seq = self.sequences.get(sequence_id)
            if not seq or not seq.enabled or self._running_sequence_id: return False
            seq.state = SequenceState.RUNNING
            seq.current_step_index = 0
            seq.start_time = time.time()
            seq.loop_counters = {}
            seq.loop_start_indices = {}
            self._running_sequence_id = sequence_id
            self._stop_event.clear()
            self._pause_event.set()
            self._execution_thread = threading.Thread(target=self._execute, args=(seq,), daemon=True)
            self._execution_thread.start()
            if self.on_sequence_event: self.on_sequence_event("started", seq)
            return True

    def pause_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id: return False
            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.PAUSED
                self._pause_event.clear()
                if self.on_sequence_event: self.on_sequence_event("paused", seq)
                return True
            return False

    def resume_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id: return False
            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.PAUSED:
                seq.state = SequenceState.RUNNING
                self._pause_event.set()
                if self.on_sequence_event: self.on_sequence_event("resumed", seq)
                return True
            return False

    def abort_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id: return False
            seq = self.sequences.get(sequence_id)
            if seq:
                seq.state = SequenceState.ABORTED
                self._stop_event.set()
                self._pause_event.set()
                if self.on_sequence_event: self.on_sequence_event("aborted", seq)
            return True

    def _execute(self, seq: Sequence):
        try:
            while seq.current_step_index < len(seq.steps):
                if self._stop_event.is_set(): break
                self._pause_event.wait()
                if self._stop_event.is_set(): break
                step = seq.steps[seq.current_step_index]
                self._execute_step(seq, step)
                if seq.state == SequenceState.RUNNING: seq.current_step_index += 1
            if seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.COMPLETED
                if self.on_sequence_event: self.on_sequence_event("completed", seq)
        finally:
            with self._lock: self._running_sequence_id = None

    def _execute_step(self, seq: Sequence, step: SequenceStep):
        if step.type == StepType.SET_OUTPUT.value and self.on_set_output and step.channel:
            self.on_set_output(step.channel, step.value)
        elif step.type == StepType.WAIT_DURATION.value:
            end = time.time() + (step.duration_ms or 0) / 1000.0
            while time.time() < end and not self._stop_event.is_set():
                self._pause_event.wait()
                time.sleep(0.1)
        elif step.type == StepType.WAIT_CONDITION.value:
            end = time.time() + (step.condition_timeout_ms or 30000) / 1000.0
            while time.time() < end and not self._stop_event.is_set():
                self._pause_event.wait()
                if self.on_get_channel_value and step.condition_channel:
                    val = self.on_get_channel_value(step.condition_channel)
                    if self._check_condition(val, step.condition_operator, step.condition_value): return
                time.sleep(0.1)
        elif step.type == StepType.LOOP_START.value:
            loop_id = step.loop_id or f"loop_{seq.current_step_index}"
            if loop_id not in seq.loop_counters:
                seq.loop_counters[loop_id] = 0
                seq.loop_start_indices[loop_id] = seq.current_step_index
        elif step.type == StepType.LOOP_END.value:
            loop_id = step.loop_id or f"loop_{seq.current_step_index}"
            if loop_id in seq.loop_counters:
                seq.loop_counters[loop_id] += 1
                if seq.loop_counters[loop_id] < (step.loop_count or 1):
                    seq.current_step_index = seq.loop_start_indices[loop_id]
                else:
                    del seq.loop_counters[loop_id]
                    del seq.loop_start_indices[loop_id]

    def _check_condition(self, val, op, target) -> bool:
        if val is None: return False
        try:
            if op == "==": return val == target
            if op == "!=": return val != target
            if op == "<": return float(val) < float(target)
            if op == ">": return float(val) > float(target)
            if op == "<=": return float(val) <= float(target)
            if op == ">=": return float(val) >= float(target)
        except (ValueError, TypeError) as e:
            logger.warning(f"Condition evaluation failed: {val} {op} {target}: {e}")
        return False

    def load_config(self, config: Dict[str, Any]):
        with self._lock:
            self.sequences.clear()
            for seq_data in config.get('sequences', []):
                try:
                    self.sequences[seq_data['id']] = Sequence.from_dict(seq_data)
                except Exception as e:
                    logger.error(f"Failed to load sequence: {e}")

    def on_acquisition_start(self):
        """Called when acquisition starts."""
        pass  # Sequences continue running if active

    def on_acquisition_stop(self):
        """Called when acquisition stops - abort running sequences."""
        if self._running_sequence_id:
            self.abort_sequence(self._running_sequence_id)
