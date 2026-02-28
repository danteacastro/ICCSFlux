"""
Script Manager for ICCSFlux

Executes Python scripts server-side for headless operation.
Scripts have access to the same API as the browser Pyodide playground:
- tags.* - Read channel values
- outputs.set() - Control outputs
- publish() - Publish computed values
- session.* - Session control

Scripts run in isolated threads and can be controlled via MQTT.
"""

import ast
import json
import time
import math
import asyncio
import threading
import logging
import traceback
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Callable, Set
from enum import Enum
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import queue

logger = logging.getLogger('ScriptManager')

# Default maximum runtime for scripts (seconds). Scripts can override via max_runtime_seconds.
DEFAULT_SCRIPT_TIMEOUT_S = 30

# Maximum script code size (bytes). Prevents denial-of-service via oversized payloads.
MAX_SCRIPT_CODE_BYTES = 256 * 1024  # 256 KB

# Maximum script name length (characters).
MAX_SCRIPT_NAME_LENGTH = 256


# =============================================================================
# STATE PERSISTENCE
# =============================================================================

class StatePersistence:
    """
    Persistent state storage for scripts.

    Stores key-value pairs in a JSON file that survives service restarts.
    Each script gets its own namespace to prevent collisions.

    File location: {data_dir}/script_state.json
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.state_file = self.data_dir / "script_state.json"
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Load state from disk"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    self._state = json.load(f)
                logger.info(f"Loaded script state: {len(self._state)} scripts")
        except Exception as e:
            logger.warning(f"Failed to load script state: {e}")
            self._state = {}

    def _save(self):
        """Save state to disk (atomic write)"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(self._state, f, indent=2)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to save script state: {e}")

    def persist(self, script_id: str, key: str, value: Any) -> bool:
        """Store a value persistently for a script"""
        with self._lock:
            if script_id not in self._state:
                self._state[script_id] = {}
            self._state[script_id][key] = value
            self._save()
            return True

    def restore(self, script_id: str, key: str, default: Any = None) -> Any:
        """Restore a persisted value for a script"""
        with self._lock:
            return self._state.get(script_id, {}).get(key, default)

    def clear_script(self, script_id: str):
        """Clear all persisted state for a script"""
        with self._lock:
            if script_id in self._state:
                del self._state[script_id]
                self._save()

    def get_all(self, script_id: str) -> Dict[str, Any]:
        """Get all persisted state for a script"""
        with self._lock:
            return self._state.get(script_id, {}).copy()


# Global persistence instance (set by ScriptManager)
_persistence: Optional[StatePersistence] = None


# =============================================================================
# HELPER CLASSES FOR SCRIPTS (available in script namespace)
# =============================================================================

class RateCalculator:
    """Calculate rate of change over a time window.

    Example:
        flow_rate = RateCalculator(window_seconds=60)
        while session.active:
            gpm = flow_rate.update(tags.FlowCounter)
            publish('FlowGPM', gpm * 60, units='GPM')
            next_scan()
    """
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._history: List[tuple] = []  # (timestamp, value)

    def update(self, value: float) -> float:
        """Update with new value and return rate (units per second)."""
        now = time.time()
        self._history.append((now, value))

        # Remove old entries outside window
        cutoff = now - self.window_seconds
        self._history = [(t, v) for t, v in self._history if t >= cutoff]

        if len(self._history) < 2:
            return 0.0

        # Calculate rate from oldest to newest in window
        t0, v0 = self._history[0]
        t1, v1 = self._history[-1]
        dt = t1 - t0

        if dt <= 0:
            return 0.0

        return (v1 - v0) / dt

    def reset(self):
        """Clear history."""
        self._history.clear()


class Accumulator:
    """Track cumulative totals from counter values.

    Handles counter rollover and resets automatically.

    Example:
        total_flow = Accumulator()
        while session.active:
            total = total_flow.update(tags.FlowCounter)
            publish('TotalGallons', total, units='gal')
            next_scan()
    """
    def __init__(self, initial: float = 0.0):
        self._total = initial
        self._last_value: Optional[float] = None

    def update(self, value: float) -> float:
        """Update with new counter value and return cumulative total."""
        if self._last_value is not None:
            delta = value - self._last_value
            # Handle rollover (assume counter went backwards = rollover)
            if delta < 0:
                delta = value  # Treat as fresh start from value
            self._total += delta

        self._last_value = value
        return self._total

    def reset(self, initial: float = 0.0):
        """Reset the accumulator."""
        self._total = initial
        self._last_value = None

    @property
    def total(self) -> float:
        return self._total


class EdgeDetector:
    """Detect rising and falling edges.

    Example:
        pump_edge = EdgeDetector(threshold=0.5)
        while session.active:
            rising, falling, state = pump_edge.update(tags.Pump_Status)
            if rising:
                print("Pump started!")
            next_scan()
    """
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._last_state: Optional[bool] = None

    def update(self, value: float) -> tuple:
        """Update and return (rising, falling, current_state)."""
        current_state = value > self.threshold

        rising = False
        falling = False

        if self._last_state is not None:
            rising = current_state and not self._last_state
            falling = not current_state and self._last_state

        self._last_state = current_state
        return (rising, falling, current_state)

    def reset(self):
        """Reset edge detector state."""
        self._last_state = None


class RollingStats:
    """Calculate running statistics over a sample window.

    Example:
        temp_stats = RollingStats(window_size=100)
        while session.active:
            stats = temp_stats.update(tags.TC001)
            publish('TempAvg', stats['mean'], units='F')
            next_scan()
    """
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._buffer: List[float] = []

    def update(self, value: float) -> dict:
        """Update with new value and return statistics dict."""
        self._buffer.append(value)
        if len(self._buffer) > self.window_size:
            self._buffer = self._buffer[-self.window_size:]

        if not self._buffer:
            return {'mean': 0, 'min': 0, 'max': 0, 'std': 0, 'count': 0}

        n = len(self._buffer)
        mean = sum(self._buffer) / n
        min_val = min(self._buffer)
        max_val = max(self._buffer)

        # Standard deviation
        if n > 1:
            variance = sum((x - mean) ** 2 for x in self._buffer) / (n - 1)
            std = variance ** 0.5
        else:
            std = 0.0

        return {
            'mean': mean,
            'min': min_val,
            'max': max_val,
            'std': std,
            'count': n
        }

    def reset(self):
        """Clear the buffer."""
        self._buffer.clear()


class Counter:
    """Universal counter with totalizing, batch, sliding window, debounce,
    duty cycle, run hours, cycle tracking, and stopwatch capabilities.

    Enable features via constructor — use only what you need.

    Args:
        target:     Preset value. ``done`` becomes True when count >= target.
        window:     Sliding window in seconds for ``window_count`` and ``rate``.
        debounce:   Require N consecutive stable readings before accepting
                    a state change (0 = disabled).
        auto_reset: Automatically reset count when target is reached
                    (increments ``batch`` number).
        mode:       'rate' (default) — update() integrates a rate signal over
                    time (e.g. Hz, GPM).  'cumulative' — update() tracks delta
                    between successive readings (e.g. hardware edge count).

    Quick examples::

        # Simple event counter with target
        parts = Counter(target=500)
        parts.increment()
        if parts.done: ...

        # Totalizer (integrate rate signal)
        fuel = Counter()
        fuel.update(tags.Gas_SCFM)   # call every scan
        fuel.total                    # cumulative value

        # Hardware edge counter (cumulative mode)
        flow = Counter(mode='cumulative')
        flow.update(tags.Flow_Pulses)  # hardware edge count
        flow.total                     # tracks delta between reads

        # Shifting count — events in rolling window
        faults = Counter(window=600)
        faults.tick()                 # record event
        faults.window_count           # events in last 10 min
        faults.rate                   # events per second
    """

    _MAX_EVENTS = 10000  # Cap sliding window to prevent unbounded memory growth

    def __init__(self, target=None, window=None, debounce=0, auto_reset=False, mode='rate'):
        # Core counting
        self._count = 0
        self._total = 0
        self._target = target
        self._auto_reset = auto_reset
        self._batch = 0
        self._mode = mode  # 'rate' or 'cumulative'

        # Sliding window
        self._window_seconds = window
        self._events: list = []

        # Debounce
        self._debounce_n = max(0, int(debounce))
        self._debounce_buf: list = []
        self._debounced_state = False

        # Edge detection
        self._last_bool: Any = None

        # Totalizer
        self._last_value: Any = None
        self._last_update_time = time.time()

        # Duty cycle / run hours
        self._is_on = False
        self._on_accum = 0.0
        self._total_on = 0.0
        self._last_duty_time = time.time()
        self._duty_events: list = []

        # Cycle tracking
        self._cycle_count = 0
        self._cycle_start: Any = None
        self._cycle_times: list = []

        # Stopwatch / laps
        self._start_time = time.time()
        self._laps: dict = {}
        self._lap_start = time.time()

    # ----- core counting ------------------------------------------------

    def increment(self, n: int = 1):
        self._count += n
        self._total += n
        self._check_target()

    def decrement(self, n: int = 1):
        self._count -= n

    def tick(self):
        now = time.time()
        self._events.append(now)
        if self._window_seconds:
            cutoff = now - self._window_seconds
            self._events = [t for t in self._events if t >= cutoff]
        elif len(self._events) > self._MAX_EVENTS:
            self._events = self._events[-self._MAX_EVENTS:]
        self.increment()

    def reset(self):
        self._count = 0
        self._start_time = time.time()
        self._lap_start = time.time()

    def set(self, value):
        self._count = value

    # ----- smart update -------------------------------------------------

    def update(self, value):
        now = time.time()

        # Cumulative mode: always treat as numeric (hardware counters
        # can read 0 or 1 which would otherwise route to _update_bool)
        if self._mode == 'cumulative':
            self._update_analog(float(value), now)
            return

        is_bool = isinstance(value, bool) or (isinstance(value, (int, float)) and value in (0, 1, 0.0, 1.0, True, False))
        if is_bool:
            self._update_bool(bool(value), now)
        else:
            self._update_analog(float(value), now)

    def _update_bool(self, current: bool, now: float):
        if self._debounce_n > 0:
            self._debounce_buf.append(current)
            if len(self._debounce_buf) > self._debounce_n:
                self._debounce_buf.pop(0)
            if len(self._debounce_buf) >= self._debounce_n:
                if not all(v == current for v in self._debounce_buf):
                    current = self._debounced_state
        self._debounced_state = current

        if self._last_bool is not None:
            if current and not self._last_bool:
                self.increment()
                self._events.append(now)
                if self._window_seconds:
                    cutoff = now - self._window_seconds
                    self._events = [t for t in self._events if t >= cutoff]
                elif len(self._events) > self._MAX_EVENTS:
                    self._events = self._events[-self._MAX_EVENTS:]
                self._cycle_start = now
            if not current and self._last_bool:
                if self._cycle_start is not None:
                    dt = now - self._cycle_start
                    self._cycle_times.append(dt)
                    if len(self._cycle_times) > 200:
                        self._cycle_times.pop(0)
                    self._cycle_count += 1
                    self._cycle_start = None
        self._last_bool = current

        dt = now - self._last_duty_time
        if current:
            self._on_accum += dt
            self._total_on += dt
        self._last_duty_time = now
        self._is_on = current

        if self._window_seconds:
            self._duty_events.append((now, current))
            cutoff = now - self._window_seconds
            self._duty_events = [(t, v) for t, v in self._duty_events if t >= cutoff]

    def _update_analog(self, value: float, now: float):
        if self._last_value is not None:
            dt = now - self._last_update_time
            if dt > 0:
                if self._mode == 'cumulative':
                    # Delta between successive readings (for hardware edge counts)
                    delta = value - self._last_value
                    if delta >= 0:
                        self._count += delta
                        self._total += delta
                else:
                    # Integrate rate signal over time (default)
                    increment = value * dt
                    self._count += increment
                    self._total += increment
        self._last_value = value
        self._last_update_time = now
        self._check_target()

    # ----- target / batch -----------------------------------------------

    def _check_target(self):
        if self._target is not None and self._count >= self._target:
            if self._auto_reset:
                self._batch += 1
                self._count = 0

    @property
    def target(self):
        return self._target

    @target.setter
    def target(self, value):
        self._target = value

    @property
    def done(self) -> bool:
        if self._target is None:
            return False
        return self._count >= self._target

    @property
    def remaining(self):
        if self._target is None:
            return 0
        return max(0, self._target - self._count)

    @property
    def batch(self) -> int:
        return self._batch

    @property
    def count(self):
        return self._count

    @property
    def total(self):
        return self._total

    # ----- sliding window ------------------------------------------------

    @property
    def window_count(self) -> int:
        if not self._window_seconds:
            return len(self._events)
        cutoff = time.time() - self._window_seconds
        self._events = [t for t in self._events if t >= cutoff]
        return len(self._events)

    @property
    def rate(self) -> float:
        wc = self.window_count
        w = self._window_seconds or (time.time() - self._start_time)
        return wc / w if w > 0 else 0.0

    # ----- debounce ------------------------------------------------------

    @property
    def state(self) -> bool:
        return self._debounced_state

    @property
    def stable(self) -> bool:
        if self._debounce_n <= 0:
            return True
        if len(self._debounce_buf) < self._debounce_n:
            return False
        return len(set(self._debounce_buf)) == 1

    # ----- duty cycle / run hours ----------------------------------------

    @property
    def duty(self) -> float:
        if self._window_seconds and self._duty_events:
            now = time.time()
            cutoff = now - self._window_seconds
            events = [(t, v) for t, v in self._duty_events if t >= cutoff]
            if not events:
                return 0.0
            on_time = 0.0
            for i in range(len(events) - 1):
                if events[i][1]:
                    on_time += events[i + 1][0] - events[i][0]
            if events[-1][1]:
                on_time += now - events[-1][0]
            return min(100.0, (on_time / self._window_seconds) * 100)
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        return min(100.0, (self._total_on / elapsed) * 100)

    @property
    def run_time(self) -> float:
        extra = 0.0
        if self._is_on:
            extra = time.time() - self._last_duty_time
        return self._total_on + extra

    @property
    def run_hours(self) -> float:
        return self.run_time / 3600.0

    # ----- cycle tracking ------------------------------------------------

    @property
    def cycles(self) -> int:
        return self._cycle_count

    @property
    def cycle_avg(self) -> float:
        return sum(self._cycle_times) / len(self._cycle_times) if self._cycle_times else 0.0

    @property
    def cycle_min(self) -> float:
        return min(self._cycle_times) if self._cycle_times else 0.0

    @property
    def cycle_max(self) -> float:
        return max(self._cycle_times) if self._cycle_times else 0.0

    # ----- stopwatch / laps ----------------------------------------------

    @property
    def elapsed(self) -> float:
        return time.time() - self._start_time

    def lap(self, name: str):
        now = time.time()
        self._laps[name] = now - self._lap_start
        self._lap_start = now

    @property
    def laps(self) -> dict:
        return dict(self._laps)


class Scheduler:
    """Simple job scheduler for timed operations.

    Example:
        scheduler = Scheduler()
        scheduler.add_interval('log', seconds=60, func=my_log_function)
        while session.active:
            scheduler.tick()
            next_scan()
    """
    def __init__(self):
        self._jobs: Dict[str, dict] = {}

    def add_interval(self, job_id: str, func: Callable, seconds: float = 0,
                     minutes: float = 0, hours: float = 0):
        """Add an interval job that runs periodically."""
        interval = seconds + (minutes * 60) + (hours * 3600)
        self._jobs[job_id] = {
            'type': 'interval',
            'func': func,
            'interval': interval,
            'last_run': 0,
            'paused': False,
            'run_count': 0
        }

    def add_cron(self, job_id: str, func: Callable, minute: int = None,
                 hour: int = None, day_of_week: int = None):
        """Add a cron-like job (simplified - checks each tick)."""
        self._jobs[job_id] = {
            'type': 'cron',
            'func': func,
            'minute': minute,
            'hour': hour,
            'day_of_week': day_of_week,
            'last_run_minute': None,
            'paused': False,
            'run_count': 0
        }

    def add_once(self, job_id: str, func: Callable, delay: float):
        """Add a one-shot job that runs after a delay."""
        self._jobs[job_id] = {
            'type': 'once',
            'func': func,
            'run_at': time.time() + delay,
            'paused': False,
            'run_count': 0
        }

    def tick(self):
        """Check and run due jobs. Call this in your main loop."""
        now = time.time()
        now_dt = datetime.fromtimestamp(now)

        for job_id, job in list(self._jobs.items()):
            if job['paused']:
                continue

            should_run = False

            if job['type'] == 'interval':
                if now - job['last_run'] >= job['interval']:
                    should_run = True
                    job['last_run'] = now

            elif job['type'] == 'cron':
                current_minute = (now_dt.hour, now_dt.minute)
                if current_minute != job['last_run_minute']:
                    # Check if matches cron spec
                    matches = True
                    if job['minute'] is not None and now_dt.minute != job['minute']:
                        matches = False
                    if job['hour'] is not None and now_dt.hour != job['hour']:
                        matches = False
                    if job['day_of_week'] is not None and now_dt.weekday() != job['day_of_week']:
                        matches = False

                    if matches:
                        should_run = True
                        job['last_run_minute'] = current_minute

            elif job['type'] == 'once':
                if now >= job['run_at']:
                    should_run = True

            if should_run:
                try:
                    job['func']()
                    job['run_count'] += 1
                except Exception as e:
                    logger.error(f"Scheduler job {job_id} error: {e}")

                # Remove one-shot jobs after running
                if job['type'] == 'once':
                    del self._jobs[job_id]

    def pause(self, job_id: str):
        """Pause a job."""
        if job_id in self._jobs:
            self._jobs[job_id]['paused'] = True

    def resume(self, job_id: str):
        """Resume a paused job."""
        if job_id in self._jobs:
            self._jobs[job_id]['paused'] = False

    def remove(self, job_id: str):
        """Remove a job."""
        self._jobs.pop(job_id, None)

    def is_paused(self, job_id: str) -> bool:
        """Check if job is paused."""
        return self._jobs.get(job_id, {}).get('paused', False)

    def get_jobs(self) -> dict:
        """Get all jobs status."""
        return {
            jid: {'type': j['type'], 'paused': j['paused'], 'run_count': j['run_count']}
            for jid, j in self._jobs.items()
        }


class StateMachine:
    """Finite State Machine for sequence/recipe control.

    Define states and transitions, then call tick() each scan to evaluate.
    Transitions fire when their condition function returns True.

    Example - Simple heating sequence:
        sm = StateMachine('IDLE')

        # Define states with optional entry/exit actions
        sm.add_state('IDLE')
        sm.add_state('HEATING', on_enter=lambda: outputs.set('Heater', True),
                                on_exit=lambda: outputs.set('Heater', False))
        sm.add_state('SOAKING')
        sm.add_state('COOLING', on_enter=lambda: outputs.set('CoolValve', True),
                                on_exit=lambda: outputs.set('CoolValve', False))
        sm.add_state('COMPLETE')

        # Define transitions with conditions
        sm.add_transition('IDLE', 'HEATING', lambda: vars.StartCmd > 0)
        sm.add_transition('HEATING', 'SOAKING', lambda: tags.Temp >= vars.TargetTemp)
        sm.add_transition('SOAKING', 'COOLING', lambda: sm.time_in_state() >= vars.SoakTime)
        sm.add_transition('COOLING', 'COMPLETE', lambda: tags.Temp <= vars.CooldownTemp)
        sm.add_transition('COMPLETE', 'IDLE', lambda: vars.ResetCmd > 0)

        while session.active:
            sm.tick()
            publish('SM_State', sm.state)
            publish('SM_StateTime', sm.time_in_state())
            next_scan()

    Example - Recipe with phases:
        recipe = StateMachine('IDLE')
        recipe.add_state('IDLE')
        recipe.add_state('PHASE1_HEAT', on_enter=lambda: set_temp(100))
        recipe.add_state('PHASE1_HOLD')
        recipe.add_state('PHASE2_HEAT', on_enter=lambda: set_temp(200))
        recipe.add_state('PHASE2_HOLD')
        recipe.add_state('COOLDOWN', on_enter=lambda: set_temp(25))
        recipe.add_state('DONE')

        # Chain the phases
        recipe.add_transition('IDLE', 'PHASE1_HEAT', lambda: vars.Go)
        recipe.add_transition('PHASE1_HEAT', 'PHASE1_HOLD', lambda: tags.Temp >= 100)
        recipe.add_transition('PHASE1_HOLD', 'PHASE2_HEAT', lambda: recipe.time_in_state() >= 300)
        # ... etc
    """

    def __init__(self, initial_state: str = 'IDLE'):
        self._states: Dict[str, dict] = {}
        self._transitions: List[dict] = []
        self._current_state: str = initial_state
        self._state_entered_at: float = time.time()
        self._previous_state: Optional[str] = None
        self._transition_count: int = 0
        self._history: List[tuple] = []  # [(timestamp, from_state, to_state), ...]
        self._max_history: int = 100

        # Auto-add initial state
        self.add_state(initial_state)

    def add_state(self, name: str, on_enter: Callable = None, on_exit: Callable = None,
                  on_tick: Callable = None):
        """Add a state with optional callbacks.

        Args:
            name: State name (use UPPERCASE by convention)
            on_enter: Called once when entering this state
            on_exit: Called once when leaving this state
            on_tick: Called every tick while in this state
        """
        self._states[name] = {
            'on_enter': on_enter,
            'on_exit': on_exit,
            'on_tick': on_tick
        }

    def add_transition(self, from_state: str, to_state: str, condition: Callable,
                       priority: int = 0, action: Callable = None):
        """Add a transition between states.

        Args:
            from_state: Source state name
            to_state: Destination state name
            condition: Function returning True when transition should fire
            priority: Higher priority transitions are evaluated first (default 0)
            action: Optional action to execute during transition
        """
        self._transitions.append({
            'from': from_state,
            'to': to_state,
            'condition': condition,
            'priority': priority,
            'action': action
        })
        # Keep transitions sorted by priority (descending)
        self._transitions.sort(key=lambda t: t['priority'], reverse=True)

    def tick(self) -> Optional[str]:
        """Evaluate transitions and execute state callbacks. Call every scan.

        Returns the new state name if a transition occurred, None otherwise.
        """
        # Execute on_tick for current state
        state_info = self._states.get(self._current_state)
        if state_info and state_info['on_tick']:
            try:
                state_info['on_tick']()
            except Exception as e:
                logger.error(f"StateMachine {self._current_state} on_tick error: {e}")

        # Evaluate transitions from current state
        for trans in self._transitions:
            if trans['from'] != self._current_state:
                continue

            try:
                if trans['condition']():
                    return self._do_transition(trans)
            except Exception as e:
                logger.error(f"StateMachine transition condition error: {e}")

        return None

    def _do_transition(self, trans: dict) -> str:
        """Execute a transition."""
        from_state = self._current_state
        to_state = trans['to']

        # Exit current state
        state_info = self._states.get(from_state)
        if state_info and state_info['on_exit']:
            try:
                state_info['on_exit']()
            except Exception as e:
                logger.error(f"StateMachine {from_state} on_exit error: {e}")

        # Execute transition action
        if trans['action']:
            try:
                trans['action']()
            except Exception as e:
                logger.error(f"StateMachine transition action error: {e}")

        # Update state
        self._previous_state = from_state
        self._current_state = to_state
        self._state_entered_at = time.time()
        self._transition_count += 1

        # Record history
        self._history.append((time.time(), from_state, to_state))
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Enter new state
        state_info = self._states.get(to_state)
        if state_info and state_info['on_enter']:
            try:
                state_info['on_enter']()
            except Exception as e:
                logger.error(f"StateMachine {to_state} on_enter error: {e}")

        logger.debug(f"StateMachine: {from_state} -> {to_state}")
        return to_state

    def force_state(self, state: str, run_callbacks: bool = True):
        """Force transition to a state (for manual override or error recovery).

        Args:
            state: Target state name
            run_callbacks: Whether to run on_exit/on_enter callbacks
        """
        if state not in self._states:
            self.add_state(state)

        if run_callbacks:
            # Exit current
            state_info = self._states.get(self._current_state)
            if state_info and state_info['on_exit']:
                try:
                    state_info['on_exit']()
                except Exception as e:
                    logger.error(f"State machine on_exit callback failed for state '{self._current_state}': {e}")
                    raise

        self._previous_state = self._current_state
        self._current_state = state
        self._state_entered_at = time.time()

        if run_callbacks:
            # Enter new
            state_info = self._states.get(state)
            if state_info and state_info['on_enter']:
                try:
                    state_info['on_enter']()
                except Exception as e:
                    logger.error(f"State machine on_enter callback failed for state '{state}': {e}")
                    raise

        self._history.append((time.time(), self._previous_state, state))

    @property
    def state(self) -> str:
        """Current state name."""
        return self._current_state

    @property
    def previous_state(self) -> Optional[str]:
        """Previous state name (before last transition)."""
        return self._previous_state

    def time_in_state(self) -> float:
        """Seconds elapsed since entering current state."""
        return time.time() - self._state_entered_at

    @property
    def transition_count(self) -> int:
        """Total number of transitions since creation."""
        return self._transition_count

    def get_history(self, limit: int = 10) -> List[tuple]:
        """Get recent transition history as [(timestamp, from, to), ...]."""
        return self._history[-limit:]

    def is_in(self, *states: str) -> bool:
        """Check if current state is one of the given states."""
        return self._current_state in states

    def reset(self, initial_state: str = None):
        """Reset state machine to initial state."""
        target = initial_state or list(self._states.keys())[0] if self._states else 'IDLE'
        self._current_state = target
        self._state_entered_at = time.time()
        self._previous_state = None
        self._transition_count = 0
        self._history.clear()


# =============================================================================
# SIGNAL PROCESSING HELPERS (available in script namespace)
# Keep in sync with services/crio_node_v2/script_engine.py (Group A only)
# =============================================================================


class SignalFilter:
    """Exponential Moving Average / first-order low-pass filter.

    Example:
        filt = SignalFilter(alpha=0.1)          # lower alpha = smoother
        filt = SignalFilter(tau=5.0, dt=0.1)    # time constant + sample period
        smooth = filt.update(tags.noisy_temp)
    """

    def __init__(self, alpha: float = None, tau: float = None, dt: float = None):
        if tau is not None and dt is not None:
            self._alpha = max(0.0, min(1.0, dt / (tau + dt)))
        elif alpha is not None:
            self._alpha = max(0.0, min(1.0, alpha))
        else:
            self._alpha = 0.1
        self._value = None

    def update(self, value: float) -> float:
        """Feed a new sample, returns filtered value."""
        if self._value is None:
            self._value = float(value)
        else:
            self._value += self._alpha * (float(value) - self._value)
        return self._value

    @property
    def value(self) -> float:
        """Current filtered value."""
        return self._value if self._value is not None else 0.0

    @property
    def alpha(self) -> float:
        """Current alpha coefficient."""
        return self._alpha

    def reset(self):
        """Reset filter state."""
        self._value = None


class LookupTable:
    """Linear interpolation from calibration points.

    Example:
        cal = LookupTable([(1000, 100), (5000, 50), (10000, 25)])
        temp = cal.lookup(3000)   # interpolated
        temp = cal(3000)          # same, via __call__
    """

    def __init__(self, points):
        if not points or len(points) < 2:
            raise ValueError("LookupTable requires at least 2 points")
        self._points = sorted(points, key=lambda p: p[0])
        self._xs = [p[0] for p in self._points]
        self._ys = [p[1] for p in self._points]

    def lookup(self, x: float) -> float:
        """Interpolate value at x. Clamps at endpoints."""
        x = float(x)
        if x <= self._xs[0]:
            return self._ys[0]
        if x >= self._xs[-1]:
            return self._ys[-1]
        # Binary search for interval
        lo, hi = 0, len(self._xs) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self._xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        # Linear interpolation
        t = (x - self._xs[lo]) / (self._xs[hi] - self._xs[lo])
        return self._ys[lo] + t * (self._ys[hi] - self._ys[lo])

    def __call__(self, x: float) -> float:
        return self.lookup(x)

    @property
    def points(self):
        """Sorted calibration points."""
        return list(self._points)


class RampSoak:
    """Time-based setpoint profile for thermal processes.

    Segment types:
    - ramp: {'type': 'ramp', 'target': float, 'rate': float}  (rate in units/min)
    - soak: {'type': 'soak', 'duration': float}  (duration in seconds)

    Example:
        profile = RampSoak([
            {'type': 'ramp', 'target': 500, 'rate': 10},
            {'type': 'soak', 'duration': 3600},
            {'type': 'ramp', 'target': 25,  'rate': 2},
        ])
        profile.start()
        pid.Furnace.setpoint = profile.tick()
    """

    def __init__(self, segments):
        if not segments:
            raise ValueError("RampSoak requires at least one segment")
        self._segments = segments
        self._start_time = None
        self._segment_index = 0
        self._segment_start_time = None
        self._segment_start_value = None
        self._done = False
        self._current_setpoint = 0.0

    def start(self, initial_value: float = 0.0):
        """Start the profile from initial_value."""
        self._start_time = time.time()
        self._segment_index = 0
        self._segment_start_time = self._start_time
        self._segment_start_value = float(initial_value)
        self._current_setpoint = float(initial_value)
        self._done = False

    def tick(self) -> float:
        """Compute and return current setpoint. Call each scan."""
        if self._start_time is None or self._done:
            return self._current_setpoint

        now = time.time()

        while self._segment_index < len(self._segments):
            seg = self._segments[self._segment_index]
            elapsed_in_seg = now - self._segment_start_time

            if seg['type'] == 'ramp':
                target = float(seg['target'])
                rate_per_sec = float(seg['rate']) / 60.0  # rate is units/min
                distance = target - self._segment_start_value
                if rate_per_sec <= 0:
                    ramp_duration = 0.0
                else:
                    ramp_duration = abs(distance) / rate_per_sec

                if elapsed_in_seg >= ramp_duration:
                    # Segment complete
                    self._current_setpoint = target
                    self._segment_start_value = target
                    self._segment_start_time += ramp_duration
                    self._segment_index += 1
                    continue
                else:
                    direction = 1.0 if distance >= 0 else -1.0
                    self._current_setpoint = self._segment_start_value + direction * rate_per_sec * elapsed_in_seg
                    return self._current_setpoint

            elif seg['type'] == 'soak':
                duration = float(seg['duration'])
                if elapsed_in_seg >= duration:
                    self._segment_start_time += duration
                    self._segment_index += 1
                    continue
                else:
                    return self._current_setpoint
            else:
                # Unknown segment type, skip
                self._segment_index += 1
                continue

        self._done = True
        return self._current_setpoint

    @property
    def setpoint(self) -> float:
        return self._current_setpoint

    @property
    def segment_index(self) -> int:
        return self._segment_index

    @property
    def done(self) -> bool:
        return self._done

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def progress(self) -> float:
        """Approximate progress 0.0 to 1.0 based on segment index."""
        total = len(self._segments)
        if total == 0 or self._done:
            return 1.0
        return self._segment_index / total

    def reset(self):
        """Reset profile to initial state."""
        self._start_time = None
        self._segment_index = 0
        self._segment_start_time = None
        self._segment_start_value = None
        self._done = False
        self._current_setpoint = 0.0


class TrendLine:
    """Online linear regression over a sliding window.

    Example:
        trend = TrendLine(window=300)
        result = trend.update(tags.reactor_pressure)
        if result['slope'] > 0.1 and result['r_squared'] > 0.9:
            publish('pressure_trend', 'RISING')
    """

    def __init__(self, window: int = 100):
        self._window = max(2, window)
        self._xs = []
        self._ys = []
        self._n = 0  # total updates (used as x-axis)

    def update(self, value: float) -> dict:
        """Add a value and return regression stats."""
        self._n += 1
        self._xs.append(self._n)
        self._ys.append(float(value))
        if len(self._xs) > self._window:
            self._xs.pop(0)
            self._ys.pop(0)

        n = len(self._xs)
        if n < 2:
            return {'slope': 0.0, 'intercept': float(value), 'r_squared': 0.0, 'count': n}

        sum_x = sum(self._xs)
        sum_y = sum(self._ys)
        sum_xy = sum(x * y for x, y in zip(self._xs, self._ys))
        sum_x2 = sum(x * x for x in self._xs)
        sum_y2 = sum(y * y for y in self._ys)

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return {'slope': 0.0, 'intercept': sum_y / n, 'r_squared': 0.0, 'count': n}

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # R-squared
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(self._xs, self._ys))
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in self._ys)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {'slope': slope, 'intercept': intercept, 'r_squared': r_squared, 'count': n}

    def predict(self, steps_ahead: int = 1) -> float:
        """Predict value steps_ahead from now using current regression."""
        n = len(self._xs)
        if n < 2:
            return self._ys[-1] if self._ys else 0.0
        sum_x = sum(self._xs)
        sum_y = sum(self._ys)
        sum_xy = sum(x * y for x, y in zip(self._xs, self._ys))
        sum_x2 = sum(x * x for x in self._xs)
        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return sum_y / n
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        return slope * (self._n + steps_ahead) + intercept

    def time_to_value(self, target: float) -> float:
        """Estimate steps until value reaches target. Returns float('nan') if unreachable."""
        n = len(self._xs)
        if n < 2:
            return float('nan')
        sum_x = sum(self._xs)
        sum_y = sum(self._ys)
        sum_xy = sum(x * y for x, y in zip(self._xs, self._ys))
        sum_x2 = sum(x * x for x in self._xs)
        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return float('nan')
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        if slope == 0:
            return float('nan')
        x_target = (target - intercept) / slope
        steps = x_target - self._n
        if steps < 0:
            return float('nan')
        return steps


class RingBuffer:
    """Fixed-size circular buffer with computed statistics.

    Example:
        buf = RingBuffer(size=100)
        buf.append(tags.vibration)
        if buf.full and buf.max - buf.min > threshold:
            publish('vibration_alarm', 1)
    """

    def __init__(self, size: int = 100):
        self._size = max(1, size)
        self._data = []
        self._index = 0
        self._full = False

    def append(self, value: float):
        """Add a value to the buffer."""
        value = float(value)
        if len(self._data) < self._size:
            self._data.append(value)
        else:
            self._data[self._index] = value
            self._full = True
        self._index = (self._index + 1) % self._size

    @property
    def values(self) -> list:
        """Contents in chronological order (oldest first)."""
        if not self._full:
            return list(self._data)
        return self._data[self._index:] + self._data[:self._index]

    @property
    def count(self) -> int:
        return len(self._data)

    @property
    def full(self) -> bool:
        return self._full

    @property
    def mean(self) -> float:
        if not self._data:
            return 0.0
        return sum(self._data) / len(self._data)

    @property
    def min(self) -> float:
        return min(self._data) if self._data else 0.0

    @property
    def max(self) -> float:
        return max(self._data) if self._data else 0.0

    @property
    def std(self) -> float:
        n = len(self._data)
        if n < 2:
            return 0.0
        m = sum(self._data) / n
        variance = sum((x - m) ** 2 for x in self._data) / (n - 1)
        return variance ** 0.5

    @property
    def last(self) -> float:
        if not self._data:
            return 0.0
        return self._data[(self._index - 1) % len(self._data)]

    @property
    def first(self) -> float:
        if not self._data:
            return 0.0
        if self._full:
            return self._data[self._index % self._size]
        return self._data[0]

    def clear(self):
        """Clear all data."""
        self._data.clear()
        self._index = 0
        self._full = False


class PeakDetector:
    """Detect peaks in a signal using rising/falling state transitions.

    Example:
        peaks = PeakDetector(min_height=0.5, min_distance=10)
        result = peaks.update(tags.detector_signal)
        if result:
            publish('peak_height', result['height'])
    """

    MAX_PEAKS = 1000

    def __init__(self, min_height: float = None, min_distance: int = 0, threshold: float = 0.0):
        self._min_height = min_height
        self._min_distance = max(0, min_distance)
        self._threshold = float(threshold)
        self._prev = None
        self._prev2 = None
        self._position = 0
        self._last_peak_pos = -self._min_distance - 1
        self._rising = False
        self._area_acc = 0.0
        self._area_baseline = None
        self._peaks = []
        self._last_peak = None

    def update(self, value: float) -> dict:
        """Feed a new sample. Returns peak dict when a peak is confirmed, else None."""
        value = float(value)
        self._position += 1
        result = None

        if self._prev is not None and self._prev2 is not None:
            # Peak: prev > prev2 and prev > value (prev was a local maximum)
            if self._prev > self._prev2 and self._prev > value:
                height = self._prev - self._threshold
                distance_ok = (self._position - 1 - self._last_peak_pos) >= self._min_distance
                height_ok = self._min_height is None or height >= self._min_height

                if distance_ok and height_ok:
                    result = {
                        'height': self._prev,
                        'position': self._position - 1,
                        'area': self._area_acc,
                    }
                    self._last_peak = result
                    self._peaks.append(result)
                    if len(self._peaks) > self.MAX_PEAKS:
                        self._peaks = self._peaks[-self.MAX_PEAKS:]
                    self._last_peak_pos = self._position - 1
                    self._area_acc = 0.0

        # Accumulate area above threshold
        if value > self._threshold:
            self._area_acc += value - self._threshold

        self._prev2 = self._prev
        self._prev = value
        return result

    @property
    def count(self) -> int:
        return len(self._peaks)

    @property
    def last_peak(self) -> dict:
        return self._last_peak

    @property
    def peaks(self) -> list:
        return list(self._peaks)


# =============================================================================
# ADVANCED HELPERS — DAQ-only (not available on cRIO)
# =============================================================================


class SpectralAnalysis:
    """FFT-based frequency domain analysis.

    Uses numpy.fft if available, falls back to pure-Python Cooley-Tukey radix-2 FFT.

    Example:
        spec = SpectralAnalysis(window_size=256, sample_rate=100.0)
        spec.update(tags.vibration)
        if spec.ready:
            result = spec.analyze()
            publish('dominant_freq', result['dominant_freq'])
    """

    def __init__(self, window_size: int = 256, sample_rate: float = 10.0):
        # Round up to next power of 2
        self._n = 1
        while self._n < window_size:
            self._n *= 2
        self._sample_rate = float(sample_rate)
        self._buffer = []
        # Pre-compute Hanning window
        self._window = [0.5 * (1 - math.cos(2 * math.pi * i / (self._n - 1))) for i in range(self._n)]

    def update(self, value: float):
        """Add a sample to the internal buffer."""
        self._buffer.append(float(value))
        if len(self._buffer) > self._n:
            self._buffer.pop(0)

    @property
    def ready(self) -> bool:
        return len(self._buffer) >= self._n

    def analyze(self) -> dict:
        """Compute frequency spectrum. Returns None if not enough data."""
        if not self.ready:
            return None

        data = self._buffer[-self._n:]
        # Apply window
        windowed = [d * w for d, w in zip(data, self._window)]

        try:
            import numpy as np
            spectrum = np.fft.rfft(windowed)
            magnitudes = [abs(c) * 2.0 / self._n for c in spectrum]
        except ImportError:
            spectrum = self._fft(windowed)
            half = self._n // 2 + 1
            magnitudes = [abs(spectrum[i]) * 2.0 / self._n for i in range(half)]

        freq_resolution = self._sample_rate / self._n
        frequencies = [i * freq_resolution for i in range(len(magnitudes))]

        # Skip DC component for dominant frequency
        if len(magnitudes) > 1:
            max_idx = max(range(1, len(magnitudes)), key=lambda i: magnitudes[i])
            dominant_freq = frequencies[max_idx]
            dominant_mag = magnitudes[max_idx]
        else:
            dominant_freq = 0.0
            dominant_mag = 0.0

        # THD: ratio of harmonics to fundamental
        thd = 0.0
        if dominant_mag > 0 and len(magnitudes) > 2:
            harmonic_power = sum(m * m for i, m in enumerate(magnitudes) if i > 0 and i != max_idx)
            thd = (harmonic_power ** 0.5) / dominant_mag

        return {
            'frequencies': frequencies,
            'magnitudes': magnitudes,
            'dominant_freq': dominant_freq,
            'dominant_mag': dominant_mag,
            'thd': thd,
        }

    @staticmethod
    def _fft(x):
        """Pure-Python Cooley-Tukey radix-2 FFT. Input must be power-of-2 length."""
        n = len(x)
        if n <= 1:
            return [complex(v) for v in x]
        even = SpectralAnalysis._fft(x[0::2])
        odd = SpectralAnalysis._fft(x[1::2])
        result = [0] * n
        for k in range(n // 2):
            w = complex(math.cos(-2 * math.pi * k / n), math.sin(-2 * math.pi * k / n))
            result[k] = even[k] + w * odd[k]
            result[k + n // 2] = even[k] - w * odd[k]
        return result


class SPCChart:
    """Statistical Process Control with Xbar/R chart and Western Electric rules.

    Example:
        spc = SPCChart(subgroup_size=5)
        spc.add_sample(tags.part_diameter)
        if not spc.in_control:
            violations = spc.check_rules()
            publish('spc_violation', violations[0])
    """

    # A2, D3, D4 constants for Xbar/R charts (subgroup sizes 2-10)
    _A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
    _D3 = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
    _D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}

    def __init__(self, subgroup_size: int = 5, num_subgroups: int = 25):
        self._sg_size = max(2, min(10, subgroup_size))
        self._max_subgroups = max(5, num_subgroups)
        self._current_subgroup = []
        self._subgroup_means = []
        self._subgroup_ranges = []
        self._lsl = None
        self._usl = None

    def add_sample(self, value: float):
        """Add an individual sample. Automatically forms subgroups."""
        self._current_subgroup.append(float(value))
        if len(self._current_subgroup) >= self._sg_size:
            self.add_subgroup(self._current_subgroup)
            self._current_subgroup = []

    def add_subgroup(self, values: list):
        """Add a complete subgroup of measurements."""
        vals = [float(v) for v in values]
        self._subgroup_means.append(sum(vals) / len(vals))
        self._subgroup_ranges.append(max(vals) - min(vals))
        if len(self._subgroup_means) > self._max_subgroups:
            self._subgroup_means.pop(0)
            self._subgroup_ranges.pop(0)

    def set_spec_limits(self, lsl: float, usl: float):
        """Set specification limits for Cp/Cpk calculation."""
        self._lsl = float(lsl)
        self._usl = float(usl)

    @property
    def x_bar(self) -> float:
        return sum(self._subgroup_means) / len(self._subgroup_means) if self._subgroup_means else 0.0

    @property
    def r_bar(self) -> float:
        return sum(self._subgroup_ranges) / len(self._subgroup_ranges) if self._subgroup_ranges else 0.0

    @property
    def ucl(self) -> float:
        a2 = self._A2.get(self._sg_size, 0.577)
        return self.x_bar + a2 * self.r_bar

    @property
    def lcl(self) -> float:
        a2 = self._A2.get(self._sg_size, 0.577)
        return self.x_bar - a2 * self.r_bar

    @property
    def sigma(self) -> float:
        """Estimated process standard deviation from R-bar."""
        d2_table = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}
        d2 = d2_table.get(self._sg_size, 2.326)
        return self.r_bar / d2 if d2 > 0 else 0.0

    @property
    def cp(self) -> float:
        if self._lsl is None or self._usl is None or self.sigma == 0:
            return 0.0
        return (self._usl - self._lsl) / (6 * self.sigma)

    @property
    def cpk(self) -> float:
        if self._lsl is None or self._usl is None or self.sigma == 0:
            return 0.0
        cpu = (self._usl - self.x_bar) / (3 * self.sigma)
        cpl = (self.x_bar - self._lsl) / (3 * self.sigma)
        return min(cpu, cpl)

    @property
    def in_control(self) -> bool:
        return len(self.check_rules()) == 0

    def check_rules(self) -> list:
        """Check Western Electric rules. Returns list of violation descriptions."""
        violations = []
        means = self._subgroup_means
        if len(means) < 2:
            return violations

        center = self.x_bar
        one_sigma = (self.ucl - center) / 3
        if one_sigma == 0:
            return violations

        # Rule 1: Any point beyond 3-sigma
        for i, m in enumerate(means):
            if abs(m - center) > 3 * one_sigma:
                violations.append(f"Rule 1: Point {i} beyond 3-sigma ({m:.4f})")

        # Rule 2: 2 of 3 consecutive beyond 2-sigma on same side
        for i in range(2, len(means)):
            window = means[i - 2:i + 1]
            above = sum(1 for m in window if m > center + 2 * one_sigma)
            below = sum(1 for m in window if m < center - 2 * one_sigma)
            if above >= 2:
                violations.append(f"Rule 2: 2 of 3 above 2-sigma at point {i}")
            if below >= 2:
                violations.append(f"Rule 2: 2 of 3 below 2-sigma at point {i}")

        # Rule 3: 4 of 5 consecutive beyond 1-sigma on same side
        for i in range(4, len(means)):
            window = means[i - 4:i + 1]
            above = sum(1 for m in window if m > center + one_sigma)
            below = sum(1 for m in window if m < center - one_sigma)
            if above >= 4:
                violations.append(f"Rule 3: 4 of 5 above 1-sigma at point {i}")
            if below >= 4:
                violations.append(f"Rule 3: 4 of 5 below 1-sigma at point {i}")

        # Rule 4: 8 consecutive on same side of center
        for i in range(7, len(means)):
            window = means[i - 7:i + 1]
            if all(m > center for m in window):
                violations.append(f"Rule 4: 8 consecutive above center at point {i}")
            if all(m < center for m in window):
                violations.append(f"Rule 4: 8 consecutive below center at point {i}")

        return violations


class BiquadFilter:
    """Second-order IIR digital filter (biquad).

    Use factory methods to create specific filter types:
        lp = BiquadFilter.lowpass(cutoff_hz=5.0, sample_rate=100.0)
        hp = BiquadFilter.highpass(cutoff_hz=1.0, sample_rate=100.0)
        bp = BiquadFilter.bandpass(center_hz=10.0, sample_rate=100.0, q=2.0)
        notch = BiquadFilter.notch(center_hz=60.0, sample_rate=100.0)
        output = lp.process(sample)
    """

    def __init__(self, b0, b1, b2, a1, a2):
        self._b0 = b0
        self._b1 = b1
        self._b2 = b2
        self._a1 = a1
        self._a2 = a2
        self._x1 = 0.0
        self._x2 = 0.0
        self._y1 = 0.0
        self._y2 = 0.0

    def process(self, sample: float) -> float:
        """Process one sample through the filter."""
        x0 = float(sample)
        y0 = self._b0 * x0 + self._b1 * self._x1 + self._b2 * self._x2 - self._a1 * self._y1 - self._a2 * self._y2
        self._x2 = self._x1
        self._x1 = x0
        self._y2 = self._y1
        self._y1 = y0
        return y0

    def reset(self):
        self._x1 = self._x2 = self._y1 = self._y2 = 0.0

    @classmethod
    def lowpass(cls, cutoff_hz: float, sample_rate: float, q: float = 0.7071):
        """Create a low-pass biquad filter."""
        w0 = 2 * math.pi * cutoff_hz / sample_rate
        alpha = math.sin(w0) / (2 * q)
        cos_w0 = math.cos(w0)
        a0 = 1 + alpha
        return cls(
            b0=(1 - cos_w0) / 2 / a0,
            b1=(1 - cos_w0) / a0,
            b2=(1 - cos_w0) / 2 / a0,
            a1=-2 * cos_w0 / a0,
            a2=(1 - alpha) / a0,
        )

    @classmethod
    def highpass(cls, cutoff_hz: float, sample_rate: float, q: float = 0.7071):
        """Create a high-pass biquad filter."""
        w0 = 2 * math.pi * cutoff_hz / sample_rate
        alpha = math.sin(w0) / (2 * q)
        cos_w0 = math.cos(w0)
        a0 = 1 + alpha
        return cls(
            b0=(1 + cos_w0) / 2 / a0,
            b1=-(1 + cos_w0) / a0,
            b2=(1 + cos_w0) / 2 / a0,
            a1=-2 * cos_w0 / a0,
            a2=(1 - alpha) / a0,
        )

    @classmethod
    def bandpass(cls, center_hz: float, sample_rate: float, q: float = 1.0):
        """Create a band-pass biquad filter."""
        w0 = 2 * math.pi * center_hz / sample_rate
        alpha = math.sin(w0) / (2 * q)
        cos_w0 = math.cos(w0)
        a0 = 1 + alpha
        return cls(
            b0=alpha / a0,
            b1=0.0,
            b2=-alpha / a0,
            a1=-2 * cos_w0 / a0,
            a2=(1 - alpha) / a0,
        )

    @classmethod
    def notch(cls, center_hz: float, sample_rate: float, q: float = 1.0):
        """Create a notch (band-reject) biquad filter."""
        w0 = 2 * math.pi * center_hz / sample_rate
        alpha = math.sin(w0) / (2 * q)
        cos_w0 = math.cos(w0)
        a0 = 1 + alpha
        return cls(
            b0=1.0 / a0,
            b1=-2 * cos_w0 / a0,
            b2=1.0 / a0,
            a1=-2 * cos_w0 / a0,
            a2=(1 - alpha) / a0,
        )

    @staticmethod
    def cascade(filters: list):
        """Chain multiple biquad filters in series."""
        return _CascadeFilter(filters)


class _CascadeFilter:
    """Internal: chains multiple biquad filters."""

    def __init__(self, filters):
        self._filters = list(filters)

    def process(self, sample: float) -> float:
        value = float(sample)
        for f in self._filters:
            value = f.process(value)
        return value

    def reset(self):
        for f in self._filters:
            f.reset()


class DataLog:
    """Structured custom data logging from scripts.

    Uses the existing publish() mechanism — no direct database access.
    Published values are captured by the recording manager automatically.

    Example:
        log = DataLog('quality')
        log.log(tags.PartWidth, label='width_mm')
        log.mark('out_of_spec')
    """

    MAX_MARKS = 1000

    def __init__(self, name: str, publish_fn=None):
        self._name = str(name)
        self._publish = publish_fn
        self._count = 0
        self._marks = []

    def log(self, value, label: str = None):
        """Log a value. Published as 'datalog.{name}.{label}'."""
        key = f'datalog.{self._name}.{label}' if label else f'datalog.{self._name}'
        self._count += 1
        if self._publish:
            self._publish(key, value)

    def log_dict(self, data: dict):
        """Log multiple key-value pairs at once."""
        for k, v in data.items():
            self.log(v, label=str(k))

    def mark(self, event_name: str):
        """Record a named event marker (published as value=1)."""
        key = f'datalog.{self._name}.mark.{event_name}'
        self._count += 1
        self._marks.append({'event': event_name, 'timestamp': time.time()})
        if len(self._marks) > self.MAX_MARKS:
            self._marks = self._marks[-self.MAX_MARKS:]
        if self._publish:
            self._publish(key, 1)

    @property
    def count(self) -> int:
        return self._count

    @property
    def marks(self) -> list:
        return list(self._marks)


# =============================================================================
# UNIT CONVERSION FUNCTIONS (available in script namespace)
# =============================================================================

def F_to_C(f: float) -> float:
    """Fahrenheit to Celsius."""
    return (f - 32) * 5 / 9

def C_to_F(c: float) -> float:
    """Celsius to Fahrenheit."""
    return c * 9 / 5 + 32

def GPM_to_LPM(gpm: float) -> float:
    """Gallons per minute to Liters per minute."""
    return gpm * 3.78541

def LPM_to_GPM(lpm: float) -> float:
    """Liters per minute to Gallons per minute."""
    return lpm / 3.78541

def PSI_to_bar(psi: float) -> float:
    """PSI to Bar."""
    return psi * 0.0689476

def bar_to_PSI(bar: float) -> float:
    """Bar to PSI."""
    return bar / 0.0689476

def gal_to_L(gal: float) -> float:
    """Gallons to Liters."""
    return gal * 3.78541

def L_to_gal(l: float) -> float:
    """Liters to Gallons."""
    return l / 3.78541

def BTU_to_kJ(btu: float) -> float:
    """BTU to Kilojoules."""
    return btu * 1.05506

def kJ_to_BTU(kj: float) -> float:
    """Kilojoules to BTU."""
    return kj / 1.05506

def lb_to_kg(lb: float) -> float:
    """Pounds to Kilograms."""
    return lb * 0.453592

def kg_to_lb(kg: float) -> float:
    """Kilograms to Pounds."""
    return kg / 0.453592


# =============================================================================
# TIME FUNCTIONS (available in script namespace)
# =============================================================================

def now() -> float:
    """Current Unix timestamp in seconds."""
    return time.time()

def now_ms() -> int:
    """Current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)

def now_iso() -> str:
    """Current time as ISO 8601 string."""
    return datetime.now().isoformat()

def time_of_day() -> str:
    """Current time as HH:MM:SS."""
    return datetime.now().strftime('%H:%M:%S')

def elapsed_since(start_ts: float) -> float:
    """Seconds elapsed since start_ts (in seconds)."""
    return time.time() - start_ts

def format_timestamp(ts_ms: int, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format millisecond timestamp to string."""
    return datetime.fromtimestamp(ts_ms / 1000).strftime(fmt)


# =============================================================================
# SCRIPT ENUMS AND DATA CLASSES
# =============================================================================

class ScriptState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ScriptRunMode(str, Enum):
    MANUAL = "manual"           # Started manually
    ACQUISITION = "acquisition"  # Auto-start with acquisition
    SESSION = "session"          # Auto-start with session


@dataclass
class Script:
    """A Python script definition"""
    id: str
    name: str
    code: str
    description: str = ""
    enabled: bool = True
    run_mode: ScriptRunMode = ScriptRunMode.MANUAL
    created_at: str = ""
    modified_at: str = ""
    max_runtime_seconds: float = DEFAULT_SCRIPT_TIMEOUT_S
    auto_restart: bool = False  # Auto-restart if script times out

    # Runtime state (not persisted)
    state: ScriptState = field(default=ScriptState.IDLE, repr=False)
    started_at: Optional[float] = field(default=None, repr=False)
    iterations: int = field(default=0, repr=False)
    error_message: Optional[str] = field(default=None, repr=False)
    timeout_exceeded: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "enabled": self.enabled,
            "runMode": self.run_mode.value if isinstance(self.run_mode, ScriptRunMode) else self.run_mode,
            "createdAt": self.created_at,
            "modifiedAt": self.modified_at,
            "autoRestart": self.auto_restart,
            # Runtime state
            "state": self.state.value if isinstance(self.state, ScriptState) else self.state,
            "startedAt": self.started_at,
            "iterations": self.iterations,
            "errorMessage": self.error_message
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Script':
        # Accept both camelCase (runMode) and snake_case (run_mode) for compatibility
        run_mode = data.get("runMode") or data.get("run_mode", "manual")
        if isinstance(run_mode, str):
            try:
                run_mode = ScriptRunMode(run_mode)
            except ValueError:
                run_mode = ScriptRunMode.MANUAL

        # Accept both camelCase (autoRestart) and snake_case (auto_restart)
        auto_restart = data.get("autoRestart") or data.get("auto_restart", False)

        return cls(
            id=data["id"],
            name=data["name"],
            code=data.get("code", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            run_mode=run_mode,
            created_at=data.get("createdAt") or data.get("created_at", ""),
            modified_at=data.get("modifiedAt") or data.get("modified_at", ""),
            auto_restart=auto_restart
        )


class ScriptRuntime:
    """
    Runtime environment for a single script.
    Provides the nisystem API (tags, outputs, session, publish).
    """

    def __init__(self, script: Script, manager: 'ScriptManager'):
        self.script = script
        self.manager = manager
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._published_values: Dict[str, Any] = {}

    def start(self):
        """Start script execution in a new thread with timeout monitoring"""
        if self._thread and self._thread.is_alive():
            logger.warning(f"Script {self.script.name} already running - ignoring start request")
            return False

        # Clean slate for new run
        self._stop_event.clear()
        self._thread = None  # Clear any old thread reference

        # Reset script state
        self.script.state = ScriptState.RUNNING
        self.script.started_at = time.time()
        self.script.iterations = 0
        self.script.error_message = None
        self.script.timeout_exceeded = False

        # Create and start new thread
        self._thread = threading.Thread(
            target=self._run,
            name=f"Script-{self.script.id}",
            daemon=True
        )
        self._thread.start()

        # Start timeout monitor thread
        max_runtime = getattr(self.script, 'max_runtime_seconds', 300.0)
        if max_runtime > 0:
            monitor = threading.Thread(
                target=self._monitor_timeout,
                args=(max_runtime,),
                name=f"ScriptMonitor-{self.script.id}",
                daemon=True
            )
            monitor.start()

        logger.info(f"Started script: {self.script.name} (thread={self._thread.name}, max_runtime={max_runtime}s)")
        return True

    def _monitor_timeout(self, timeout_seconds: float):
        """Monitor script for timeout and force stop if exceeded"""
        check_interval = 1.0  # Check every second
        start_time = self.script.started_at or time.time()

        while self._thread and self._thread.is_alive():
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"SCRIPT TIMEOUT: {self.script.name} exceeded {timeout_seconds}s - forcing stop")
                self.script.timeout_exceeded = True
                error_msg = f"Script timeout after {timeout_seconds}s - script was forcefully stopped"
                self.script.error_message = error_msg
                self._stop_event.set()

                # Publish timeout error to frontend
                self.manager.log_script_output(self.script.id, 'error', error_msg)

                # Wait briefly for graceful stop
                time.sleep(2.0)

                if self._thread and self._thread.is_alive():
                    logger.error(f"Script {self.script.name} did not respond to stop after timeout")
                    self.script.state = ScriptState.ERROR
                return

            time.sleep(check_interval)

    def stop(self):
        """Stop script execution and reset for clean restart"""
        logger.info(f"Stop requested for script: {self.script.name}")

        # Signal stop
        self._stop_event.set()

        # Wait for thread to finish if running
        if self._thread and self._thread.is_alive():
            self.script.state = ScriptState.STOPPING
            self._thread.join(timeout=5.0)

            if self._thread.is_alive():
                logger.warning(f"Script {self.script.name} did not stop gracefully (thread still alive)")

        # Always reset state for clean restart
        self.script.state = ScriptState.IDLE
        self.script.error_message = None
        self._thread = None  # Allow new thread on next start
        self._stop_event.clear()  # Reset stop event for next run
        logger.info(f"Stopped script: {self.script.name} - ready for restart")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """Execute the script code"""
        try:
            # Build the execution namespace with nisystem API
            namespace = self._build_namespace()

            # Preprocess code: strip 'await' keywords for sync execution
            # This allows the same script to work in both Pyodide (async) and backend (sync)
            import re
            code = self.script.code
            # Replace 'await next_scan()' with 'next_scan()'
            # Replace 'await wait_for(...)' with 'wait_for(...)'
            # Replace 'await wait_until(...)' with 'wait_until(...)'
            code = re.sub(r'\bawait\s+(next_scan|wait_for|wait_until)\s*\(', r'\1(', code)

            # AST-based sandbox validation before execution
            _blocked_dunder_attrs = frozenset({
                '__import__', '__subclasses__', '__bases__', '__globals__',
                '__code__', '__class__', '__builtins__', '__dict__',
                '__getattribute__', '__setattr__', '__delattr__',
                '__init_subclass__', '__mro__', '__mro_entries__',
                '__reduce__', '__reduce_ex__',
            })
            _blocked_func_names = frozenset({
                'getattr', 'setattr', 'delattr', 'eval', 'exec',
                'compile', 'open', '__import__', 'vars', 'dir',
                'globals', 'locals', 'breakpoint', 'memoryview',
                'classmethod', 'staticmethod', 'property', 'super',
            })
            _blocked_module_names = frozenset({
                'os', 'sys', 'subprocess', 'importlib', 'ctypes',
                'socket', 'signal', 'shutil', 'pathlib', 'io',
                'builtins', 'code', 'codeop', 'compileall',
            })

            class _SandboxValidator(ast.NodeVisitor):
                def visit_Import(self, node):
                    raise SecurityError("Import statements are not allowed")
                def visit_ImportFrom(self, node):
                    raise SecurityError("Import statements are not allowed")
                def visit_Attribute(self, node):
                    if node.attr in _blocked_dunder_attrs:
                        raise SecurityError(f"Access to '{node.attr}' is not allowed")
                    self.generic_visit(node)
                def visit_Call(self, node):
                    if isinstance(node.func, ast.Name) and node.func.id in _blocked_func_names:
                        raise SecurityError(f"Call to '{node.func.id}()' is not allowed")
                    self.generic_visit(node)
                def visit_Name(self, node):
                    if node.id in _blocked_module_names:
                        raise SecurityError(f"Access to '{node.id}' module is not allowed")
                    self.generic_visit(node)

            tree = ast.parse(code, mode='exec')
            _SandboxValidator().visit(tree)

            # Compile and execute (timeout enforced by _monitor_timeout thread)
            code_obj = compile(tree, f"<script:{self.script.name}>", 'exec')
            logger.info(f"Script {self.script.name}: executing with timeout={self.script.max_runtime_seconds}s")
            exec(code_obj, namespace)

            # If script has a main loop, it should have exited by now
            self.script.state = ScriptState.IDLE
            logger.info(f"Script {self.script.name} completed normally")

        except StopScript:
            # Normal stop via stop_event
            self.script.state = ScriptState.IDLE
            logger.info(f"Script {self.script.name} stopped")

        except Exception as e:
            self.script.state = ScriptState.ERROR
            # Store full traceback for better error reporting
            full_traceback = traceback.format_exc()
            self.script.error_message = str(e)
            logger.error(f"Script {self.script.name} error: {e}")
            logger.debug(full_traceback)

            # Publish the full traceback to frontend via output handler
            # This allows the UI to parse line numbers and display detailed errors
            self.manager.log_script_output(self.script.id, 'error', full_traceback)

            # Notify manager of error
            self.manager._on_script_error(self.script, str(e))

    def _build_namespace(self) -> dict:
        """Build the execution namespace with nisystem API.

        UNIFIED NAMESPACE:
        If the manager has a shared namespace callback (on_get_shared_namespace),
        scripts execute in the global console namespace. This means:
        - Variables defined in console are accessible in scripts
        - Variables defined in scripts are visible in Variable Explorer
        - All scripts and console share the same Python environment

        Script-specific functions (publish, next_scan, etc.) are added to
        the shared namespace but scoped to this script execution.
        """

        # Publish function - publish computed values
        def publish(name: str, value: float, units: str = '', description: str = '') -> None:
            self._published_values[name] = {
                'value': value,
                'units': units,
                'description': description,
                'timestamp': time.time()
            }
            self.manager.publish_value(self.script.id, name, value, units)

        # Sleep functions that respect stop event
        # Drift compensation: track target time to prevent cumulative drift
        _next_target_time = [0.0]  # Use list for closure mutability

        def next_scan() -> None:
            """Wait for next scan cycle (respects stop event, drift-compensated)"""
            self.script.iterations += 1
            scan_rate = self.manager.get_scan_rate()
            interval = 1.0 / scan_rate if scan_rate > 0 else 0.1

            now_mono = time.monotonic()

            # Initialize target time on first call
            if _next_target_time[0] == 0.0:
                _next_target_time[0] = now_mono + interval
            else:
                _next_target_time[0] += interval

            # Calculate remaining time to target (compensates for execution time)
            remaining = _next_target_time[0] - now_mono

            # If we're behind schedule, reset target to avoid catch-up bursts
            if remaining < 0:
                _next_target_time[0] = now_mono + interval
                remaining = interval

            if self._stop_event.wait(remaining):
                raise StopScript()

        def wait_for(seconds: float) -> None:
            """Wait for specified duration (respects stop event)"""
            if self._stop_event.wait(seconds):
                raise StopScript()

        def wait_until(condition_func, timeout: float = None) -> bool:
            """Wait until condition is true (respects stop event)"""
            start = time.time()
            while True:
                if self._stop_event.is_set():
                    raise StopScript()
                try:
                    if condition_func():
                        return True
                except Exception as e:
                    logger.warning(f"wait_until condition evaluation error: {e}")
                    return False
                if timeout and (time.time() - start) > timeout:
                    return False
                time.sleep(0.1)

        # Print function that logs to script output
        def script_print(*args, **kwargs):
            message = ' '.join(str(a) for a in args)
            self.manager.log_script_output(self.script.id, 'info', message)

        # Try to get the shared namespace from the manager
        # This enables unified Python environment across console and scripts
        if self.manager.on_get_shared_namespace:
            try:
                namespace = self.manager.on_get_shared_namespace()
            except Exception as e:
                logger.warning(f"Failed to get shared namespace: {e}, using isolated namespace")
                namespace = self._build_isolated_namespace()
        else:
            # No shared namespace - use isolated mode (backward compatible)
            namespace = self._build_isolated_namespace()

        # Add script-specific functions to the namespace
        # These override any existing definitions for this script execution
        script_additions = {
            # Script control functions
            'publish': publish,
            'next_scan': next_scan,
            'wait_for': wait_for,
            'wait_until': wait_until,

            # Override print to log to script output
            'print': script_print,

            # Helper classes (make available in shared namespace too)
            'Counter': Counter,
            'RateCalculator': RateCalculator,
            'Accumulator': Accumulator,
            'EdgeDetector': EdgeDetector,
            'RollingStats': RollingStats,
            'Scheduler': Scheduler,
            'StateMachine': StateMachine,

            # Signal processing helpers (Group A — also on cRIO)
            'SignalFilter': SignalFilter,
            'LookupTable': LookupTable,
            'RampSoak': RampSoak,
            'TrendLine': TrendLine,
            'RingBuffer': RingBuffer,
            'PeakDetector': PeakDetector,

            # Advanced helpers (Group B — DAQ-only)
            'SpectralAnalysis': SpectralAnalysis,
            'SPCChart': SPCChart,
            'BiquadFilter': BiquadFilter,
            'DataLog': lambda name: DataLog(name, publish_fn=publish),

            # Unit conversions
            'F_to_C': F_to_C,
            'C_to_F': C_to_F,
            'GPM_to_LPM': GPM_to_LPM,
            'LPM_to_GPM': LPM_to_GPM,
            'PSI_to_bar': PSI_to_bar,
            'bar_to_PSI': bar_to_PSI,
            'gal_to_L': gal_to_L,
            'L_to_gal': L_to_gal,
            'BTU_to_kJ': BTU_to_kJ,
            'kJ_to_BTU': kJ_to_BTU,
            'lb_to_kg': lb_to_kg,
            'kg_to_lb': kg_to_lb,

            # Time functions (use different name to avoid shadowing time module)
            'now': now,
            'now_ms': now_ms,
            'now_iso': now_iso,
            'time_of_day': time_of_day,
            'elapsed_since': elapsed_since,
            'format_timestamp': format_timestamp,

            # State persistence (survives service restarts)
            'persist': lambda key, value: self.manager.persistence.persist(self.script.id, key, value) if self.manager.persistence else False,
            'restore': lambda key, default=None: self.manager.persistence.restore(self.script.id, key, default) if self.manager.persistence else default,
        }

        namespace.update(script_additions)
        return namespace

    def _build_isolated_namespace(self) -> dict:
        """Build an isolated namespace (fallback when shared namespace unavailable).

        This creates a complete standalone namespace with all APIs.
        Used when on_get_shared_namespace is not configured.
        """

        # Tags API - read channel values
        class TagsAPI:
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def __getattr__(self, name: str) -> float:
                return self._runtime.manager.get_channel_value(name)

            def __getitem__(self, name: str) -> float:
                return self._runtime.manager.get_channel_value(name)

            def __contains__(self, name: str) -> bool:
                return self._runtime.manager.has_channel(name)

            def get(self, name: str, default: float = 0.0) -> float:
                if self._runtime.manager.has_channel(name):
                    return self._runtime.manager.get_channel_value(name)
                return default

            def keys(self) -> List[str]:
                return self._runtime.manager.get_channel_names()

            def age(self, name: str) -> float:
                """Get age of tag data in seconds"""
                ts = self._runtime.manager.get_channel_timestamp(name)
                if ts == 0:
                    return float('inf')
                return time.time() - ts

        # Outputs API - control outputs with arbitration
        class OutputsAPI:
            """Control outputs with optional exclusive claiming.

            Basic usage (no claiming):
                outputs.set('Relay1', 1)    # Set output
                outputs['Relay1'] = 1       # Same thing

            With arbitration (prevents conflicts between scripts):
                if outputs.claim('Heater'):
                    # We now have exclusive control
                    outputs.set('Heater', 1)
                    # ... do work ...
                    outputs.release('Heater')  # Or auto-released on script stop

            Check availability:
                if outputs.available('Heater'):
                    outputs.set('Heater', 1)
                else:
                    owner = outputs.claimed_by('Heater')
                    print(f"Heater controlled by {owner}")
            """
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def set(self, channel: str, value) -> bool:
                """Set output value. Returns True if command accepted.

                If another script has claimed this channel, the write is rejected.
                """
                return self._runtime.manager.set_output(
                    channel, value, self._runtime.script.id
                )

            def __setitem__(self, name: str, value) -> None:
                self.set(name, value)

            def claim(self, channel: str) -> bool:
                """Claim exclusive control of an output channel.

                Once claimed, other scripts cannot write to this channel.
                Claims are automatically released when script stops.

                Returns True if claim succeeded, False if already claimed.
                """
                return self._runtime.manager.claim_output(channel, self._runtime.script.id)

            def release(self, channel: str) -> bool:
                """Release a claimed output channel."""
                return self._runtime.manager.release_output(channel, self._runtime.script.id)

            def available(self, channel: str) -> bool:
                """Check if an output is available (not claimed by another script)."""
                return self._runtime.manager.is_output_available(channel, self._runtime.script.id)

            def claimed_by(self, channel: str) -> Optional[str]:
                """Get the script_id that has claimed a channel, or None if unclaimed."""
                return self._runtime.manager.get_claim_owner(channel)

            def claims(self) -> Dict[str, str]:
                """Get all current output claims (channel -> script_id)."""
                return self._runtime.manager.get_output_claims()

        # Session API - session state and control
        class SessionAPI:
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            @property
            def active(self) -> bool:
                # Check stop event first
                if self._runtime._stop_event.is_set():
                    raise StopScript()
                return self._runtime.manager.is_session_active()

            @property
            def elapsed(self) -> float:
                return self._runtime.manager.get_session_elapsed()

            @property
            def recording(self) -> bool:
                return self._runtime.manager.is_recording()

            def start(self) -> None:
                self._runtime.manager.start_acquisition()

            def stop(self) -> None:
                self._runtime.manager.stop_acquisition()

            def start_recording(self, filename: Optional[str] = None) -> None:
                self._runtime.manager.start_recording(filename)

            def stop_recording(self) -> None:
                self._runtime.manager.stop_recording()

            @staticmethod
            def now() -> float:
                """Current time in seconds (Unix timestamp)"""
                return time.time()

            @staticmethod
            def now_ms() -> int:
                """Current time in milliseconds"""
                return int(time.time() * 1000)

            @staticmethod
            def now_iso() -> str:
                """Current time as ISO string"""
                return datetime.now().isoformat()

        # Vars API - read/write user variables
        class VarsAPI:
            """Access user variables (constants, manual values, accumulators, strings, etc.)

            Example:
                # Read a numeric constant
                k_factor = vars.CalibrationFactor

                # Set a numeric variable
                vars.set('TargetTemp', 350.0)

                # Read/set a string variable
                batch_id = vars.BatchID
                vars.set('OperatorNotes', 'Test run #1')

                # Reset an accumulator
                vars.reset('TotalFlow')

                # Check if variable exists
                if 'MyVar' in vars:
                    value = vars.MyVar
            """
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def __getattr__(self, name: str):
                """Get variable value by attribute access: vars.MyVar
                Returns float for numeric variables, str for string variables."""
                return self._runtime.manager.get_variable_value(name)

            def __getitem__(self, name: str):
                """Get variable value by index: vars['MyVar']
                Returns float for numeric variables, str for string variables."""
                return self._runtime.manager.get_variable_value(name)

            def __contains__(self, name: str) -> bool:
                """Check if variable exists: 'MyVar' in vars"""
                return self._runtime.manager.has_variable(name)

            def get(self, name: str, default=0.0):
                """Get variable value with default if not found.
                Returns float for numeric, str for string variables."""
                if self._runtime.manager.has_variable(name):
                    return self._runtime.manager.get_variable_value(name)
                return default

            def set(self, name: str, value) -> bool:
                """Set a variable's value: vars.set('MyVar', 123.4) or vars.set('Notes', 'text')"""
                return self._runtime.manager.set_variable_value(name, value)

            def reset(self, name: str) -> bool:
                """Reset a variable (0 for numeric, empty string for string)"""
                return self._runtime.manager.reset_variable(name)

            def keys(self) -> List[str]:
                """Get all variable names"""
                return self._runtime.manager.get_variable_names()

        # PID Loop API - control PID loops
        class PidLoopProxy:
            """Proxy for a single PID loop, providing attribute access to loop properties.

            Example:
                pid.TC001.setpoint = 350      # Set setpoint
                pid.TC001.mode = 'auto'       # Set mode
                pid.TC001.output = 50         # Set manual output
                pid.TC001.tune(1.2, 0.5, 0.1) # Tune Kp, Ki, Kd
                pv = pid.TC001.pv             # Read process variable
            """
            def __init__(self, runtime: ScriptRuntime, loop_id: str):
                object.__setattr__(self, '_runtime', runtime)
                object.__setattr__(self, '_loop_id', loop_id)

            def __getattr__(self, name: str):
                """Get loop property"""
                status = self._runtime.manager.get_pid_status(self._loop_id)
                if status is None:
                    return None
                return status.get(name)

            def __setattr__(self, name: str, value):
                """Set loop property (setpoint, mode, output)"""
                if name == 'setpoint':
                    self._runtime.manager.set_pid_setpoint(self._loop_id, value)
                elif name == 'mode':
                    self._runtime.manager.set_pid_mode(self._loop_id, value)
                elif name == 'output':
                    self._runtime.manager.set_pid_output(self._loop_id, value)
                elif name == 'enabled':
                    self._runtime.manager.set_pid_enabled(self._loop_id, value)
                else:
                    raise AttributeError(f"Cannot set PID property: {name}")

            def tune(self, kp: float, ki: float, kd: float) -> bool:
                """Set PID tuning parameters"""
                return self._runtime.manager.set_pid_tuning(self._loop_id, kp, ki, kd)

            def enable(self) -> bool:
                """Enable the PID loop"""
                return self._runtime.manager.set_pid_enabled(self._loop_id, True)

            def disable(self) -> bool:
                """Disable the PID loop"""
                return self._runtime.manager.set_pid_enabled(self._loop_id, False)

            def auto(self) -> bool:
                """Switch to automatic mode"""
                return self._runtime.manager.set_pid_mode(self._loop_id, 'auto')

            def manual(self) -> bool:
                """Switch to manual mode"""
                return self._runtime.manager.set_pid_mode(self._loop_id, 'manual')

        class PidAPI:
            """Access PID loops from scripts.

            Example:
                # Set setpoint
                pid.TC001.setpoint = 350

                # Switch mode
                pid.TC001.mode = 'auto'  # or 'manual'
                pid.TC001.auto()         # shortcut

                # Set manual output (when in manual mode)
                pid.TC001.output = 50

                # Tune parameters
                pid.TC001.tune(kp=1.2, ki=0.5, kd=0.1)

                # Read current values
                pv = pid.TC001.pv
                cv = pid.TC001.output
                error = pid.TC001.error

                # Check all loops
                for loop_id in pid.keys():
                    status = pid[loop_id]
            """
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def __getattr__(self, name: str) -> PidLoopProxy:
                """Get loop proxy by attribute: pid.TC001"""
                return PidLoopProxy(self._runtime, name)

            def __getitem__(self, name: str) -> PidLoopProxy:
                """Get loop proxy by index: pid['TC001']"""
                return PidLoopProxy(self._runtime, name)

            def __contains__(self, name: str) -> bool:
                """Check if loop exists: 'TC001' in pid"""
                return self._runtime.manager.has_pid_loop(name)

            def keys(self) -> List[str]:
                """Get all PID loop IDs"""
                return self._runtime.manager.get_pid_loop_ids()

            def status(self, loop_id: str) -> Optional[dict]:
                """Get full status dict for a loop"""
                return self._runtime.manager.get_pid_status(loop_id)

            def all_status(self) -> Dict[str, dict]:
                """Get status of all loops"""
                return {lid: self._runtime.manager.get_pid_status(lid)
                        for lid in self.keys()}

        # Build isolated namespace
        namespace = {
            # Core API
            'tags': TagsAPI(self),
            'outputs': OutputsAPI(self),
            'session': SessionAPI(self),
            'vars': VarsAPI(self),
            'pid': PidAPI(self),

            # Standard library (safe subset)
            'time': time,
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            # Built-ins (safe subset)
            'abs': abs,
            'all': all,
            'any': any,
            'bool': bool,
            'dict': dict,
            'enumerate': enumerate,
            'filter': filter,
            'float': float,
            'format': format,
            'frozenset': frozenset,
            'int': int,
            'isinstance': isinstance,
            'len': len,
            'list': list,
            'map': map,
            'max': max,
            'min': min,
            'pow': pow,
            'range': range,
            'reversed': reversed,
            'round': round,
            'set': set,
            'sorted': sorted,
            'str': str,
            'sum': sum,
            'tuple': tuple,
            'type': type,
            'zip': zip,

            # Boolean/None
            'True': True,
            'False': False,
            'None': None,
        }

        # Try to add numpy and scipy
        try:
            import numpy as np_mod
            namespace['numpy'] = np_mod
            namespace['np'] = np_mod
        except ImportError:
            pass

        try:
            import scipy as scipy_mod
            namespace['scipy'] = scipy_mod
        except ImportError:
            pass

        return namespace


class StopScript(Exception):
    """Raised to stop script execution gracefully"""
    pass


class SecurityError(Exception):
    """Raised when script sandbox detects a disallowed operation"""
    pass


class ScriptManager:
    """
    Manages Python script execution server-side.

    Callbacks (set by DAQ service):
    - on_get_channel_value(channel): Get channel value
    - on_get_channel_timestamp(channel): Get channel timestamp
    - on_set_output(channel, value): Set output value
    - on_start_acquisition(): Start acquisition
    - on_stop_acquisition(): Stop acquisition
    - on_start_recording(filename): Start recording
    - on_stop_recording(): Stop recording
    - on_is_session_active(): Check if session is active
    - on_get_session_elapsed(): Get session elapsed time
    - on_is_recording(): Check if recording
    - on_publish_value(script_id, name, value, units): Publish computed value
    - on_script_event(event_type, script): Script state changed
    - on_script_output(script_id, type, message): Script logged output
    """

    def __init__(self, data_dir: Optional[Path] = None):
        global _persistence

        self.scripts: Dict[str, Script] = {}
        self.runtimes: Dict[str, ScriptRuntime] = {}

        # Initialize state persistence
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path('data')
        _persistence = StatePersistence(self.data_dir)
        self.persistence = _persistence

        # Callbacks (set by DAQ service)
        self.on_get_channel_value: Optional[Callable[[str], float]] = None
        self.on_get_channel_timestamp: Optional[Callable[[str], float]] = None
        self.on_get_channel_names: Optional[Callable[[], List[str]]] = None
        self.on_has_channel: Optional[Callable[[str], bool]] = None
        self.on_set_output: Optional[Callable[[str, Any], bool]] = None
        self.on_start_acquisition: Optional[Callable[[], None]] = None
        self.on_stop_acquisition: Optional[Callable[[], None]] = None
        self.on_start_recording: Optional[Callable[[Optional[str]], None]] = None
        self.on_stop_recording: Optional[Callable[[], None]] = None
        self.on_is_session_active: Optional[Callable[[], bool]] = None
        self.on_get_session_elapsed: Optional[Callable[[], float]] = None
        self.on_is_recording: Optional[Callable[[], bool]] = None
        self.on_get_scan_rate: Optional[Callable[[], float]] = None
        self.on_publish_value: Optional[Callable[[str, str, float, str], None]] = None
        self.on_script_event: Optional[Callable[[str, Script], None]] = None
        self.on_script_output: Optional[Callable[[str, str, str], None]] = None

        # User variables API callbacks (for vars.* in scripts)
        self.on_get_variable_value: Optional[Callable[[str], float]] = None
        self.on_set_variable_value: Optional[Callable[[str, float], bool]] = None
        self.on_reset_variable: Optional[Callable[[str], bool]] = None
        self.on_get_variable_names: Optional[Callable[[], List[str]]] = None
        self.on_has_variable: Optional[Callable[[str], bool]] = None

        # PID API callbacks (for pid.* in scripts)
        self.on_get_pid_status: Optional[Callable[[str], Optional[dict]]] = None
        self.on_set_pid_setpoint: Optional[Callable[[str, float], bool]] = None
        self.on_set_pid_mode: Optional[Callable[[str, str], bool]] = None
        self.on_set_pid_output: Optional[Callable[[str, float], bool]] = None
        self.on_set_pid_enabled: Optional[Callable[[str, bool], bool]] = None
        self.on_set_pid_tuning: Optional[Callable[[str, float, float, float], bool]] = None
        self.on_get_pid_loop_ids: Optional[Callable[[], List[str]]] = None
        self.on_has_pid_loop: Optional[Callable[[str], bool]] = None

        # Shared namespace callback - scripts execute in the global console namespace
        # This allows Variable Explorer to show script variables and enables
        # console<->script interoperability (define in console, use in script)
        self.on_get_shared_namespace: Optional[Callable[[], Dict[str, Any]]] = None

        self._lock = threading.Lock()

        # Track which outputs are controlled by scripts during active session
        # This allows selective lockout of only script-controlled channels
        self._controlled_outputs: Set[str] = set()

        # Output claims for arbitration - prevents multiple scripts from conflicting
        # Maps channel -> script_id that has claimed exclusive control
        self._output_claims: Dict[str, str] = {}

        # Startup delay for auto-start scripts (seconds)
        # Gives time for all nodes (including cRIO) to connect and send data
        self.acquisition_start_delay: float = 5.0  # seconds
        self.session_start_delay: float = 2.0  # seconds (session starts after acquisition)

        # Pending startup timer (to cancel if acquisition stops before delay completes)
        self._pending_start_timer: Optional[threading.Timer] = None

        logger.info("ScriptManager initialized")

    # =========================================================================
    # SCRIPT CRUD
    # =========================================================================

    def add_script(self, script: Script) -> bool:
        """Add or update a script"""
        # Enforce payload size limits
        if len(script.code.encode('utf-8')) > MAX_SCRIPT_CODE_BYTES:
            logger.error(f"Script '{script.name}' rejected: code size "
                        f"({len(script.code.encode('utf-8'))} bytes) exceeds "
                        f"limit ({MAX_SCRIPT_CODE_BYTES} bytes)")
            return False
        if len(script.name) > MAX_SCRIPT_NAME_LENGTH:
            logger.error(f"Script name rejected: length ({len(script.name)}) "
                        f"exceeds limit ({MAX_SCRIPT_NAME_LENGTH})")
            return False

        with self._lock:
            # Stop if running
            if script.id in self.runtimes and self.runtimes[script.id].is_running():
                self.stop_script(script.id)

            self.scripts[script.id] = script
            logger.info(f"Added script: {script.name} ({script.id})")
            return True

    def add_script_from_dict(self, data: dict) -> bool:
        """Add a script from dictionary data.

        Why this method exists:
        - MQTT handlers receive script data as JSON (dict), not Script objects
        - This provides a clean one-liner for adding scripts from API calls
        - Handles both 'runMode' (frontend) and 'run_mode' (backend) field names
        - Centralizes dict->Script conversion so MQTT handlers stay simple

        Example:
            data = {'id': 'abc', 'name': 'My Script', 'code': 'x=1', 'run_mode': 'session'}
            script_manager.add_script_from_dict(data)
        """
        # Normalize run_mode field name (backend uses snake_case, frontend uses camelCase)
        if 'run_mode' in data and 'runMode' not in data:
            data['runMode'] = data['run_mode']

        script = Script.from_dict(data)
        return self.add_script(script)

    def update_script(self, script_id: str, updates: dict) -> bool:
        """Update an existing script with partial data.

        Why this method exists:
        - Allows partial updates without replacing the entire script
        - Common pattern: update just the code, or just enable/disable
        - Preserves fields not in the updates dict
        - Handles camelCase/snake_case field name variations

        Example:
            script_manager.update_script('my-script', {'name': 'New Name'})
            script_manager.update_script('my-script', {'enabled': False})
            script_manager.update_script('my-script', {'run_mode': 'session'})
        """
        with self._lock:
            script = self.scripts.get(script_id)
            if not script:
                logger.error(f"Script not found for update: {script_id}")
                return False

            # Stop if running before updating
            if script_id in self.runtimes and self.runtimes[script_id].is_running():
                self.stop_script(script_id)

            # Apply updates
            if 'name' in updates:
                script.name = updates['name']
            if 'code' in updates:
                script.code = updates['code']
            if 'description' in updates:
                script.description = updates['description']
            if 'enabled' in updates:
                script.enabled = updates['enabled']

            # Handle run_mode with both naming conventions
            run_mode = updates.get('runMode') or updates.get('run_mode')
            if run_mode:
                if isinstance(run_mode, str):
                    try:
                        script.run_mode = ScriptRunMode(run_mode)
                    except ValueError:
                        logger.warning(f"Invalid run_mode: {run_mode}")
                elif isinstance(run_mode, ScriptRunMode):
                    script.run_mode = run_mode

            # Handle auto_restart with both naming conventions
            auto_restart = updates.get('autoRestart') or updates.get('auto_restart')
            if auto_restart is not None:
                script.auto_restart = bool(auto_restart)

            script.modified_at = datetime.now().isoformat()
            logger.info(f"Updated script: {script.name} ({script_id})")
            return True

    def remove_script(self, script_id: str) -> bool:
        """Remove a script"""
        with self._lock:
            if script_id not in self.scripts:
                return False

            # Stop if running
            if script_id in self.runtimes:
                self.runtimes[script_id].stop()
                del self.runtimes[script_id]

            del self.scripts[script_id]
            logger.info(f"Removed script: {script_id}")
            return True

    def get_script(self, script_id: str) -> Optional[Script]:
        """Get a script by ID"""
        return self.scripts.get(script_id)

    def get_all_scripts(self) -> List[Script]:
        """Get all scripts"""
        return list(self.scripts.values())

    def load_scripts_from_project(self, project_data: dict) -> None:
        """Load scripts from project data

        Supports two formats:
        1. Nested: project_data['scripts']['pythonScripts'] (frontend format)
        2. Flat: project_data['scripts'] as array (legacy format)
        """
        # Stop all current scripts first
        self.stop_all_scripts()
        self.scripts.clear()
        self.runtimes.clear()

        # Try nested format first (frontend saves as scripts.pythonScripts)
        scripts_section = project_data.get('scripts', {})
        if isinstance(scripts_section, dict):
            scripts_data = scripts_section.get('pythonScripts', [])
        elif isinstance(scripts_section, list):
            # Legacy flat format
            scripts_data = scripts_section
        else:
            scripts_data = []

        # Load scripts
        for script_data in scripts_data:
            try:
                script = Script.from_dict(script_data)
                self.scripts[script.id] = script
                logger.debug(f"Loaded script: {script.name} (runMode={script.run_mode.value})")
            except Exception as e:
                logger.error(f"Failed to load script: {e}")

        logger.info(f"Loaded {len(self.scripts)} scripts from project")

    def export_scripts_for_project(self) -> List[dict]:
        """Export scripts for saving to project"""
        return [s.to_dict() for s in self.scripts.values()]

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def start_script(self, script_id: str) -> bool:
        """Start a script"""
        script = self.scripts.get(script_id)
        if not script:
            logger.error(f"Script not found: {script_id}")
            return False

        if not script.enabled:
            logger.warning(f"Script is disabled: {script.name}")
            return False

        # Create runtime if needed
        if script_id not in self.runtimes:
            self.runtimes[script_id] = ScriptRuntime(script, self)

        runtime = self.runtimes[script_id]

        if runtime.is_running():
            logger.warning(f"Script already running: {script.name}")
            return False

        if runtime.start():
            self._emit_event('started', script)
            return True
        return False

    def stop_script(self, script_id: str) -> bool:
        """Stop a script and release its output claims"""
        if script_id not in self.runtimes:
            return False

        runtime = self.runtimes[script_id]
        script = self.scripts.get(script_id)

        runtime.stop()

        # Auto-release any outputs claimed by this script
        self.release_all_outputs(script_id)

        if script:
            self._emit_event('stopped', script)

        return True

    def stop_all_scripts(self) -> None:
        """Stop all running scripts"""
        for script_id in list(self.runtimes.keys()):
            self.stop_script(script_id)

    def reload_script(self, script_id: str, new_code: Optional[str] = None) -> bool:
        """Hot-reload a script without losing persisted state.

        This enables live code updates while acquisition continues running.
        The script's persisted state (via persist()/restore() API) is preserved
        across the reload.

        Process:
        1. Get script's current persisted state (already on disk)
        2. Stop the running script gracefully
        3. Update the code if new_code provided
        4. Restart the script
        5. Script calls restore() to recover its state

        Args:
            script_id: ID of the script to reload
            new_code: Optional new code to use (if None, reloads existing code)

        Returns:
            True if reload succeeded, False otherwise

        Example:
            # In script code - state survives hot-reload:
            counter = restore('counter', 0)
            while session.active:
                counter += 1
                persist('counter', counter)
                publish('Counter', counter)
                next_scan()
        """
        script = self.scripts.get(script_id)
        if not script:
            logger.error(f"Hot-reload failed: Script not found: {script_id}")
            return False

        was_running = self.is_script_running(script_id)
        logger.info(f"Hot-reload: {script.name} (was_running={was_running})")

        # Step 1: Stop if running (state is already persisted to disk)
        if was_running:
            logger.info(f"Hot-reload: Stopping {script.name} for code swap")
            self.stop_script(script_id)

            # Brief pause to ensure clean thread shutdown
            time.sleep(0.1)

        # Step 2: Update code if provided
        if new_code is not None:
            script.code = new_code
            script.modified_at = datetime.now().isoformat()
            logger.info(f"Hot-reload: Updated code for {script.name}")

        # Step 3: Create fresh runtime (old one may have stale references)
        if script_id in self.runtimes:
            del self.runtimes[script_id]

        # Step 4: Restart if it was running
        if was_running:
            logger.info(f"Hot-reload: Restarting {script.name}")
            if self.start_script(script_id):
                logger.info(f"Hot-reload: {script.name} restarted successfully")
                self._emit_event('reloaded', script)
                return True
            else:
                logger.error(f"Hot-reload: Failed to restart {script.name}")
                return False
        else:
            # Wasn't running - just updated the code
            logger.info(f"Hot-reload: {script.name} code updated (not running)")
            self._emit_event('updated', script)
            return True

    def is_script_running(self, script_id: str) -> bool:
        """Check if a script is running"""
        if script_id not in self.runtimes:
            return False
        return self.runtimes[script_id].is_running()

    def get_running_scripts(self) -> List[str]:
        """Get list of running script IDs"""
        return [sid for sid, rt in self.runtimes.items() if rt.is_running()]

    # =========================================================================
    # LIFECYCLE HOOKS
    # =========================================================================

    def on_acquisition_start(self) -> None:
        """Called when acquisition starts - auto-start acquisition scripts after delay

        The delay allows time for all nodes (including remote cRIO) to connect
        and start sending data before scripts begin executing.
        """
        # Cancel any pending timer from previous acquisition
        self._cancel_pending_start()

        # Count scripts that will auto-start
        scripts_to_start = [s for s in self.scripts.values()
                           if s.enabled and s.run_mode == ScriptRunMode.ACQUISITION]

        if not scripts_to_start:
            logger.info("Acquisition started - no acquisition scripts to auto-start")
            return

        logger.info(f"Acquisition started - will auto-start {len(scripts_to_start)} scripts "
                   f"after {self.acquisition_start_delay}s delay")

        # Schedule delayed start
        def delayed_start():
            logger.info(f"Acquisition delay complete - starting {len(scripts_to_start)} scripts")
            for script in scripts_to_start:
                if not self.is_script_running(script.id):
                    logger.info(f"  Auto-starting: {script.name}")
                    self.start_script(script.id)
            # Note: start_script() emits 'started' event for each script,
            # which triggers status publishing via _script_event_handler

        self._pending_start_timer = threading.Timer(self.acquisition_start_delay, delayed_start)
        self._pending_start_timer.daemon = True
        self._pending_start_timer.start()

    def _cancel_pending_start(self):
        """Cancel any pending delayed script start"""
        if self._pending_start_timer and self._pending_start_timer.is_alive():
            logger.info("Cancelling pending script auto-start")
            self._pending_start_timer.cancel()
            self._pending_start_timer = None

    def on_acquisition_stop(self) -> None:
        """Called when acquisition stops - stop ALL running scripts (safety first)

        When acquisition stops, ALL scripts must stop regardless of their run mode.
        This ensures clean state and prevents scripts from running without data.
        Also cancels any pending delayed starts.
        """
        # Cancel any pending delayed start
        self._cancel_pending_start()

        running_scripts = self.get_running_scripts()
        if running_scripts:
            logger.info(f"Acquisition stopped - stopping ALL {len(running_scripts)} running scripts")
            for script_id in running_scripts:
                script = self.scripts.get(script_id)
                if script:
                    logger.info(f"  Stopping: {script.name} (mode={script.run_mode.value})")
                self.stop_script(script_id)
        else:
            logger.info("Acquisition stopped - no running scripts to stop")

    def on_session_start(self) -> None:
        """Called when session starts - auto-start session scripts after short delay

        Session starts after acquisition is already running, so a shorter delay is used.
        """
        # Count scripts that will auto-start
        scripts_to_start = [s for s in self.scripts.values()
                           if s.enabled and s.run_mode == ScriptRunMode.SESSION]

        if not scripts_to_start:
            logger.info("Session started - no session scripts to auto-start")
            return

        logger.info(f"Session started - will auto-start {len(scripts_to_start)} scripts "
                   f"after {self.session_start_delay}s delay")

        # Schedule delayed start (shorter delay since acquisition is already running)
        def delayed_start():
            logger.info(f"Session delay complete - starting {len(scripts_to_start)} scripts")
            for script in scripts_to_start:
                if not self.is_script_running(script.id):
                    logger.info(f"  Auto-starting: {script.name}")
                    self.start_script(script.id)

        timer = threading.Timer(self.session_start_delay, delayed_start)
        timer.daemon = True
        timer.start()

    def on_session_stop(self) -> None:
        """Called when session stops - stop session scripts

        Note: Session scripts stop when session ends.
        Acquisition scripts and manual scripts keep running until acquisition stops.
        """
        for script in self.scripts.values():
            if script.run_mode == ScriptRunMode.SESSION:
                if self.is_script_running(script.id):
                    logger.info(f"Session stopped - stopping session script: {script.name}")
                    self.stop_script(script.id)

    # =========================================================================
    # API IMPLEMENTATION (called by ScriptRuntime)
    # =========================================================================

    def get_channel_value(self, name: str) -> float:
        if self.on_get_channel_value:
            return self.on_get_channel_value(name)
        return 0.0

    def get_channel_timestamp(self, name: str) -> float:
        if self.on_get_channel_timestamp:
            return self.on_get_channel_timestamp(name)
        return 0.0

    def get_channel_names(self) -> List[str]:
        if self.on_get_channel_names:
            return self.on_get_channel_names()
        return []

    def has_channel(self, name: str) -> bool:
        if self.on_has_channel:
            return self.on_has_channel(name)
        return False

    def set_output(self, channel: str, value: Any, script_id: str = None) -> bool:
        """Set output value. Returns True if command accepted.

        If another script has claimed exclusive control of this channel,
        the write will be rejected unless script_id matches the claim owner.
        """
        # Check if channel is claimed by another script
        if channel in self._output_claims:
            claim_owner = self._output_claims[channel]
            if script_id and claim_owner != script_id:
                logger.warning(f"Output {channel} blocked: claimed by script {claim_owner}, "
                             f"write attempted by {script_id}")
                return False

        # Track this channel as script-controlled for session lockout
        self._controlled_outputs.add(channel)
        if self.on_set_output:
            return self.on_set_output(channel, value)
        return False

    @property
    def controlled_outputs(self) -> Set[str]:
        """Direct access to the set of output channels controlled by scripts.

        Why this property exists:
        - Testing: Allows tests to inject controlled outputs without calling set_output()
        - Inspection: Lets external code check/modify the set directly
        - Consistency: Provides Pythonic property access alongside get_controlled_outputs()

        Note: Returns the actual set (not a copy) for direct manipulation.
        Use get_controlled_outputs() if you need a safe copy.
        """
        return self._controlled_outputs

    def get_controlled_outputs(self) -> Set[str]:
        """Get a COPY of the controlled outputs set (safe for iteration).
        Used by DAQ service to implement selective session lockout."""
        return self._controlled_outputs.copy()

    def clear_controlled_outputs(self) -> None:
        """Clear the controlled outputs tracking. Called when session ends."""
        self._controlled_outputs.clear()
        self._output_claims.clear()
        logger.debug("Cleared controlled outputs and claims")

    # =========================================================================
    # OUTPUT ARBITRATION
    # =========================================================================

    def claim_output(self, channel: str, script_id: str) -> bool:
        """Claim exclusive control of an output channel.

        Use this to prevent other scripts from writing to the same output.
        Returns True if claim succeeded, False if already claimed by another script.

        Example in script:
            if outputs.claim('HeaterRelay'):
                # We have exclusive control
                outputs.set('HeaterRelay', 1)
            else:
                print("HeaterRelay already claimed by another script!")
        """
        with self._lock:
            if channel in self._output_claims:
                existing_owner = self._output_claims[channel]
                if existing_owner != script_id:
                    logger.info(f"Output claim denied: {channel} already claimed by {existing_owner}")
                    return False
                # Already claimed by same script - that's fine
                return True

            self._output_claims[channel] = script_id
            logger.info(f"Output claimed: {channel} by script {script_id}")
            return True

    def release_output(self, channel: str, script_id: str) -> bool:
        """Release a claimed output channel.

        Only the script that claimed the output can release it.
        Returns True if released, False if not owned by this script.
        """
        with self._lock:
            if channel not in self._output_claims:
                return True  # Not claimed, consider it released

            if self._output_claims[channel] != script_id:
                logger.warning(f"Cannot release {channel}: claimed by {self._output_claims[channel]}, "
                             f"not {script_id}")
                return False

            del self._output_claims[channel]
            logger.info(f"Output released: {channel} by script {script_id}")
            return True

    def release_all_outputs(self, script_id: str) -> int:
        """Release all outputs claimed by a script. Returns count released."""
        with self._lock:
            to_release = [ch for ch, owner in self._output_claims.items() if owner == script_id]
            for channel in to_release:
                del self._output_claims[channel]
            if to_release:
                logger.info(f"Released {len(to_release)} outputs for script {script_id}: {to_release}")
            return len(to_release)

    def is_output_available(self, channel: str, script_id: str = None) -> bool:
        """Check if an output is available (not claimed by another script).

        If script_id is provided, returns True if the channel is unclaimed
        OR claimed by the specified script.
        """
        with self._lock:
            if channel not in self._output_claims:
                return True
            if script_id and self._output_claims[channel] == script_id:
                return True
            return False

    def get_output_claims(self) -> Dict[str, str]:
        """Get a copy of all current output claims (channel -> script_id)."""
        with self._lock:
            return self._output_claims.copy()

    def get_claim_owner(self, channel: str) -> Optional[str]:
        """Get the script_id that has claimed a channel, or None if unclaimed."""
        return self._output_claims.get(channel)

    def start_acquisition(self) -> None:
        if self.on_start_acquisition:
            self.on_start_acquisition()

    def stop_acquisition(self) -> None:
        if self.on_stop_acquisition:
            self.on_stop_acquisition()

    def start_recording(self, filename: Optional[str] = None) -> None:
        if self.on_start_recording:
            self.on_start_recording(filename)

    def stop_recording(self) -> None:
        if self.on_stop_recording:
            self.on_stop_recording()

    def is_session_active(self) -> bool:
        if self.on_is_session_active:
            return self.on_is_session_active()
        return False

    def get_session_elapsed(self) -> float:
        if self.on_get_session_elapsed:
            return self.on_get_session_elapsed()
        return 0.0

    def is_recording(self) -> bool:
        if self.on_is_recording:
            return self.on_is_recording()
        return False

    def get_scan_rate(self) -> float:
        if self.on_get_scan_rate:
            return self.on_get_scan_rate()
        return 10.0  # Default 10 Hz

    def publish_value(self, script_id: str, name: str, value: float, units: str = '') -> None:
        if self.on_publish_value:
            self.on_publish_value(script_id, name, value, units)

    # User Variables API (for vars.* in scripts)
    def get_variable_value(self, name: str) -> float:
        """Get user variable value by name"""
        if self.on_get_variable_value:
            return self.on_get_variable_value(name)
        return 0.0

    def set_variable_value(self, name: str, value: float) -> bool:
        """Set user variable value by name"""
        if self.on_set_variable_value:
            return self.on_set_variable_value(name, value)
        return False

    def reset_variable(self, name: str) -> bool:
        """Reset user variable by name"""
        if self.on_reset_variable:
            return self.on_reset_variable(name)
        return False

    def get_variable_names(self) -> List[str]:
        """Get all user variable names"""
        if self.on_get_variable_names:
            return self.on_get_variable_names()
        return []

    def has_variable(self, name: str) -> bool:
        """Check if user variable exists"""
        if self.on_has_variable:
            return self.on_has_variable(name)
        return False

    # PID API (for pid.* in scripts)
    def get_pid_status(self, loop_id: str) -> Optional[dict]:
        """Get PID loop status by ID"""
        if self.on_get_pid_status:
            return self.on_get_pid_status(loop_id)
        return None

    def set_pid_setpoint(self, loop_id: str, value: float) -> bool:
        """Set PID loop setpoint"""
        if self.on_set_pid_setpoint:
            return self.on_set_pid_setpoint(loop_id, value)
        return False

    def set_pid_mode(self, loop_id: str, mode: str) -> bool:
        """Set PID loop mode (auto/manual)"""
        if self.on_set_pid_mode:
            return self.on_set_pid_mode(loop_id, mode)
        return False

    def set_pid_output(self, loop_id: str, value: float) -> bool:
        """Set PID loop manual output value"""
        if self.on_set_pid_output:
            return self.on_set_pid_output(loop_id, value)
        return False

    def set_pid_enabled(self, loop_id: str, enabled: bool) -> bool:
        """Enable or disable a PID loop"""
        if self.on_set_pid_enabled:
            return self.on_set_pid_enabled(loop_id, enabled)
        return False

    def set_pid_tuning(self, loop_id: str, kp: float, ki: float, kd: float) -> bool:
        """Set PID loop tuning parameters"""
        if self.on_set_pid_tuning:
            return self.on_set_pid_tuning(loop_id, kp, ki, kd)
        return False

    def get_pid_loop_ids(self) -> List[str]:
        """Get all PID loop IDs"""
        if self.on_get_pid_loop_ids:
            return self.on_get_pid_loop_ids()
        return []

    def has_pid_loop(self, loop_id: str) -> bool:
        """Check if PID loop exists"""
        if self.on_has_pid_loop:
            return self.on_has_pid_loop(loop_id)
        return False

    def log_script_output(self, script_id: str, output_type: str, message: str) -> None:
        if self.on_script_output:
            self.on_script_output(script_id, output_type, message)
        logger.debug(f"Script {script_id}: {message}")

    def _on_script_error(self, script: Script, error: str) -> None:
        """Called when a script encounters an error"""
        self._emit_event('error', script)

    def _emit_event(self, event_type: str, script: Script) -> None:
        """Emit a script event"""
        if self.on_script_event:
            try:
                self.on_script_event(event_type, script)
            except Exception as e:
                logger.error(f"Error in script event handler: {e}")

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> dict:
        """Get script manager status"""
        running = self.get_running_scripts()
        return {
            "script_count": len(self.scripts),
            "running_count": len(running),
            "running_scripts": running,
            "scripts": {sid: s.to_dict() for sid, s in self.scripts.items()},
            "output_claims": self._output_claims.copy()
        }

    def shutdown(self) -> None:
        """Shutdown the script manager"""
        self._cancel_pending_start()  # Cancel any pending delayed starts
        self.stop_all_scripts()
        logger.info("ScriptManager shutdown")
