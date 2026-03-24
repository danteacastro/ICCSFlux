"""
GC Run Scheduler — manages a queue of runs for automated GC analysis.

Supports:
- Priority ordering (calibration > check_standard > blank > sample)
- Auto-blank insertion every N samples
- Auto-calibration check at configurable intervals
- Batch add from CSV-style dicts
- MQTT command interface (queue_add, queue_batch, queue_cancel, queue_get, queue_clear)
"""

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger('GCNode')

class RunType(IntEnum):
    """Run type with priority ordering (lower = higher priority)."""
    CALIBRATION = 0
    CHECK_STANDARD = 1
    BLANK = 2
    SAMPLE = 3

_RUN_TYPE_MAP = {
    'calibration': RunType.CALIBRATION,
    'cal': RunType.CALIBRATION,
    'check_standard': RunType.CHECK_STANDARD,
    'check': RunType.CHECK_STANDARD,
    'blank': RunType.BLANK,
    'sample': RunType.SAMPLE,
}

_DEFAULT_PRIORITY = {
    RunType.CALIBRATION: 10,
    RunType.CHECK_STANDARD: 20,
    RunType.BLANK: 30,
    RunType.SAMPLE: 100,
}

class RunStatus:
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    FAILED = 'failed'

@dataclass
class QueuedRun:
    """A single run in the queue."""
    run_id: str              # Unique ID (auto-generated)
    sample_id: str = ""      # User-provided sample identifier
    run_type: RunType = RunType.SAMPLE
    method_name: str = ""    # Analysis method to use (empty = current)
    port: int = 0            # Valve port number (0 = default)
    priority: int = 100      # Lower = higher priority (type-based default)
    status: str = RunStatus.PENDING
    notes: str = ""
    added_time: float = 0.0
    start_time: float = 0.0
    finish_time: float = 0.0
    result: Optional[Dict] = None
    auto_inserted: bool = False  # True if auto-blank or auto-cal

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for MQTT/JSON transport."""
        return {
            'run_id': self.run_id,
            'sample_id': self.sample_id,
            'run_type': self.run_type.name.lower(),
            'method_name': self.method_name,
            'port': self.port,
            'priority': self.priority,
            'status': self.status,
            'notes': self.notes,
            'added_time': self.added_time,
            'start_time': self.start_time,
            'finish_time': self.finish_time,
            'result': self.result,
            'auto_inserted': self.auto_inserted,
        }

@dataclass
class SchedulerConfig:
    """Configuration for the run scheduler."""
    enabled: bool = False
    auto_blank_interval: int = 10     # Insert blank every N samples (0 = disabled)
    auto_cal_interval: int = 0        # Insert calibration every N samples (0 = disabled)
    auto_blank_method: str = ""       # Method for auto-blanks (empty = current)
    auto_cal_method: str = ""         # Method for auto-cal (empty = current)
    max_queue_size: int = 200

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SchedulerConfig':
        return cls(
            enabled=data.get('enabled', False),
            auto_blank_interval=int(data.get('auto_blank_interval', 10)),
            auto_cal_interval=int(data.get('auto_cal_interval', 0)),
            auto_blank_method=data.get('auto_blank_method', ''),
            auto_cal_method=data.get('auto_cal_method', ''),
            max_queue_size=int(data.get('max_queue_size', 200)),
        )

class GCScheduler:
    """Run queue scheduler for GC analysis.

    Manages an ordered queue of runs. After each completed run, checks
    for auto-inserts (blank, calibration) and starts the next queued run.
    """

    def __init__(self, config: SchedulerConfig):
        self._config = config
        self._queue: List[QueuedRun] = []
        self._completed: List[QueuedRun] = []
        self._current_run: Optional[QueuedRun] = None
        self._sample_count_since_blank = 0
        self._sample_count_since_cal = 0
        self._next_id = 1
        self._total_runs = 0

    # ------------------------------------------------------------------
    # Queue Management
    # ------------------------------------------------------------------

    def add_run(self, sample_id: str = "", run_type: str = "sample",
                method_name: str = "", port: int = 0, notes: str = "",
                priority: Optional[int] = None) -> QueuedRun:
        """Add a run to the queue. Returns the queued run.

        Raises ValueError for invalid run_type or if queue is full.
        """
        # Accept both RunType enum and string
        if isinstance(run_type, RunType):
            rt = run_type
        else:
            rt = _RUN_TYPE_MAP.get(run_type.lower().strip())
            if rt is None:
                raise ValueError(
                    f"Invalid run_type '{run_type}'. "
                    f"Valid types: {', '.join(_RUN_TYPE_MAP.keys())}"
                )

        if len(self._queue) >= self._config.max_queue_size:
            raise ValueError(
                f"Queue is full ({self._config.max_queue_size} runs). "
                "Cancel or clear runs before adding more."
            )

        run_id = f"run-{self._next_id:04d}"
        self._next_id += 1

        if priority is None:
            priority = _DEFAULT_PRIORITY[rt]

        run = QueuedRun(
            run_id=run_id,
            sample_id=sample_id,
            run_type=rt,
            method_name=method_name,
            port=port,
            priority=priority,
            status=RunStatus.PENDING,
            notes=notes,
            added_time=time.time(),
        )

        self._insert_sorted(run)
        logger.info(
            f"Queued {run.run_type.name} run {run.run_id} "
            f"(sample={sample_id!r}, priority={priority}, queue_depth={len(self._queue)})"
        )
        return run

    def add_batch(self, runs: List[Dict[str, Any]]) -> List[QueuedRun]:
        """Add multiple runs from a list of dicts (CSV import).

        Each dict may contain: sample_id, run_type, method_name, port, notes, priority.
        Returns list of successfully queued runs. Logs errors for invalid entries.
        """
        added: List[QueuedRun] = []
        for i, run_dict in enumerate(runs):
            try:
                run = self.add_run(
                    sample_id=str(run_dict.get('sample_id', '')),
                    run_type=str(run_dict.get('run_type', 'sample')),
                    method_name=str(run_dict.get('method_name', '')),
                    port=int(run_dict.get('port', 0)),
                    notes=str(run_dict.get('notes', '')),
                    priority=run_dict.get('priority'),
                )
                added.append(run)
            except (ValueError, TypeError) as e:
                logger.warning(f"Batch entry {i} skipped: {e}")
        logger.info(f"Batch add: {len(added)}/{len(runs)} runs queued")
        return added

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a pending run by ID. Returns True if found and cancelled."""
        for i, run in enumerate(self._queue):
            if run.run_id == run_id:
                if run.status != RunStatus.PENDING:
                    logger.warning(f"Cannot cancel run {run_id}: status is {run.status}")
                    return False
                run.status = RunStatus.CANCELLED
                run.finish_time = time.time()
                self._queue.pop(i)
                self._completed.append(run)
                self._trim_completed()
                logger.info(f"Cancelled run {run_id}")
                return True
        logger.warning(f"Run {run_id} not found in queue")
        return False

    def clear_queue(self) -> int:
        """Clear all pending runs. Returns count removed."""
        count = len(self._queue)
        now = time.time()
        for run in self._queue:
            run.status = RunStatus.CANCELLED
            run.finish_time = now
            self._completed.append(run)
        self._queue.clear()
        self._trim_completed()
        if count > 0:
            logger.info(f"Cleared {count} runs from queue")
        return count

    def reorder(self, run_id: str, new_position: int) -> bool:
        """Move a pending run to a new position in the queue.

        new_position is clamped to valid range [0, queue_depth-1].
        Returns True if the run was found and moved.
        """
        src_idx = None
        for i, run in enumerate(self._queue):
            if run.run_id == run_id:
                src_idx = i
                break

        if src_idx is None:
            logger.warning(f"Reorder: run {run_id} not found in queue")
            return False

        run = self._queue.pop(src_idx)
        new_position = max(0, min(new_position, len(self._queue)))
        self._queue.insert(new_position, run)
        logger.info(f"Reordered run {run_id} from position {src_idx} to {new_position}")
        return True

    # ------------------------------------------------------------------
    # Run Lifecycle
    # ------------------------------------------------------------------

    def get_next_run(self) -> Optional[QueuedRun]:
        """Get the next run to execute (checks auto-inserts first).

        Returns None if queue is empty and no auto-inserts needed.
        Marks the returned run as 'running'.
        """
        if self._current_run is not None:
            logger.warning("get_next_run called while a run is already active")
            return None

        # Check auto-insert before pulling from queue
        auto_run = self._check_auto_inserts()
        if auto_run is not None:
            self._start_run(auto_run)
            return auto_run

        # Pull from queue
        if not self._queue:
            return None

        run = self._queue.pop(0)
        self._start_run(run)
        return run

    def complete_current_run(self, result: Optional[Dict] = None,
                             success: bool = True) -> Optional[QueuedRun]:
        """Mark current run as completed/failed. Returns the completed run.

        Updates sample counters for auto-insert logic.
        Returns None if no run is active.
        """
        if self._current_run is None:
            logger.warning("complete_current_run called with no active run")
            return None

        run = self._current_run
        run.finish_time = time.time()
        run.result = result
        run.status = RunStatus.COMPLETED if success else RunStatus.FAILED
        self._current_run = None
        self._total_runs += 1

        # Update auto-insert counters based on completed run type
        if success:
            if run.run_type == RunType.SAMPLE:
                self._sample_count_since_blank += 1
                self._sample_count_since_cal += 1
            elif run.run_type == RunType.BLANK:
                self._sample_count_since_blank = 0
            elif run.run_type == RunType.CALIBRATION:
                self._sample_count_since_cal = 0
                # Calibration also resets blank counter
                self._sample_count_since_blank = 0

        self._completed.append(run)
        self._trim_completed()

        status = run.status.upper()
        elapsed = run.finish_time - run.start_time
        logger.info(
            f"Run {run.run_id} {status} ({run.run_type.name}, "
            f"{elapsed:.1f}s, samples_since_blank={self._sample_count_since_blank})"
        )
        return run

    def _start_run(self, run: QueuedRun) -> None:
        """Mark a run as running and set it as the current run."""
        run.status = RunStatus.RUNNING
        run.start_time = time.time()
        self._current_run = run
        logger.info(
            f"Starting run {run.run_id}: {run.run_type.name} "
            f"sample_id={run.sample_id!r} method={run.method_name!r}"
        )

    def _check_auto_inserts(self) -> Optional[QueuedRun]:
        """Check if an auto-blank or auto-cal should be inserted.

        Returns a new auto-inserted QueuedRun, or None.
        Calibration check takes priority over blank.
        """
        # Auto-calibration check
        if (self._config.auto_cal_interval > 0
                and self._sample_count_since_cal >= self._config.auto_cal_interval):
            run_id = f"run-{self._next_id:04d}"
            self._next_id += 1
            run = QueuedRun(
                run_id=run_id,
                sample_id="auto-cal",
                run_type=RunType.CHECK_STANDARD,
                method_name=self._config.auto_cal_method,
                priority=_DEFAULT_PRIORITY[RunType.CHECK_STANDARD],
                status=RunStatus.PENDING,
                notes="Auto-inserted calibration check",
                added_time=time.time(),
                auto_inserted=True,
            )
            logger.info(
                f"Auto-inserting calibration check after "
                f"{self._sample_count_since_cal} samples"
            )
            return run

        # Auto-blank insertion
        if (self._config.auto_blank_interval > 0
                and self._sample_count_since_blank >= self._config.auto_blank_interval):
            run_id = f"run-{self._next_id:04d}"
            self._next_id += 1
            run = QueuedRun(
                run_id=run_id,
                sample_id="auto-blank",
                run_type=RunType.BLANK,
                method_name=self._config.auto_blank_method,
                priority=_DEFAULT_PRIORITY[RunType.BLANK],
                status=RunStatus.PENDING,
                notes="Auto-inserted blank run",
                added_time=time.time(),
                auto_inserted=True,
            )
            logger.info(
                f"Auto-inserting blank after "
                f"{self._sample_count_since_blank} samples"
            )
            return run

        return None

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_queue(self) -> List[Dict[str, Any]]:
        """Return serializable queue state."""
        result: List[Dict[str, Any]] = []
        if self._current_run is not None:
            result.append(self._current_run.to_dict())
        for run in self._queue:
            result.append(run.to_dict())
        return result

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler status dict."""
        return {
            'enabled': self._config.enabled,
            'queue_depth': len(self._queue),
            'is_running': self._current_run is not None,
            'current_run': self._current_run.to_dict() if self._current_run else None,
            'total_runs': self._total_runs,
            'completed_count': len(self._completed),
            'sample_count_since_blank': self._sample_count_since_blank,
            'sample_count_since_cal': self._sample_count_since_cal,
            'auto_blank_interval': self._config.auto_blank_interval,
            'auto_cal_interval': self._config.auto_cal_interval,
            'max_queue_size': self._config.max_queue_size,
        }

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def is_running(self) -> bool:
        return self._current_run is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trim_completed(self) -> None:
        """Keep completed list bounded (max 500, trim to 250)."""
        if len(self._completed) > 500:
            self._completed = self._completed[-250:]

    def _insert_sorted(self, run: QueuedRun) -> None:
        """Insert a run into the queue maintaining priority order.

        Lower priority number = earlier in queue. Runs with equal priority
        are ordered FIFO (new run goes after existing same-priority runs).
        """
        insert_at = len(self._queue)
        for i, existing in enumerate(self._queue):
            if run.priority < existing.priority:
                insert_at = i
                break
        self._queue.insert(insert_at, run)

    # ------------------------------------------------------------------
    # MQTT Command Handler
    # ------------------------------------------------------------------

    def handle_command(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle scheduler MQTT commands. Returns response dict.

        Commands:
        - queue_add: Add a single run
        - queue_batch: Add multiple runs
        - queue_cancel: Cancel a run by ID
        - queue_clear: Clear all pending runs
        - queue_get: Get current queue state
        - queue_reorder: Move a run to new position
        """
        try:
            if command == 'queue_add':
                run = self.add_run(
                    sample_id=str(payload.get('sample_id', '')),
                    run_type=str(payload.get('run_type', 'sample')),
                    method_name=str(payload.get('method_name', '')),
                    port=int(payload.get('port', 0)),
                    notes=str(payload.get('notes', '')),
                    priority=payload.get('priority'),
                )
                return {'ok': True, 'run': run.to_dict()}

            elif command == 'queue_batch':
                runs_data = payload.get('runs', [])
                if not isinstance(runs_data, list):
                    return {'ok': False, 'error': "'runs' must be a list"}
                added = self.add_batch(runs_data)
                return {
                    'ok': True,
                    'added': len(added),
                    'total': len(runs_data),
                    'runs': [r.to_dict() for r in added],
                }

            elif command == 'queue_cancel':
                run_id = payload.get('run_id', '')
                if not run_id:
                    return {'ok': False, 'error': "Missing 'run_id'"}
                success = self.cancel_run(run_id)
                return {'ok': success, 'run_id': run_id}

            elif command == 'queue_clear':
                count = self.clear_queue()
                return {'ok': True, 'cleared': count}

            elif command == 'queue_get':
                return {
                    'ok': True,
                    'queue': self.get_queue(),
                    'status': self.get_status(),
                }

            elif command == 'queue_reorder':
                run_id = payload.get('run_id', '')
                position = payload.get('position')
                if not run_id:
                    return {'ok': False, 'error': "Missing 'run_id'"}
                if position is None:
                    return {'ok': False, 'error': "Missing 'position'"}
                success = self.reorder(run_id, int(position))
                return {'ok': success, 'run_id': run_id, 'position': int(position)}

            else:
                return {'ok': False, 'error': f"Unknown command: {command}"}

        except ValueError as e:
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"Scheduler command error ({command}): {e}", exc_info=True)
            return {'ok': False, 'error': f"Internal error: {e}"}
