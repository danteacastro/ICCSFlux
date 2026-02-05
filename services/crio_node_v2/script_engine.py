"""
cRIO Node V2 - Script Execution Engine

Runs user Python scripts in isolated threads with access to:
- tags.*       Read channel values
- outputs.*    Write output values
- vars.*       Read/write shared variables (inter-script communication)
- publish()    Publish computed values to dashboard
- session.*    Read session state
- wait_for()   Sleep respecting stop requests
- wait_until() Wait for condition
- should_stop() Check if script should exit
- persist()/restore()  State persistence across restarts
"""

import ast
import json
import logging
import math
import os
import re
import statistics
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger('cRIONode.Scripts')


class SecurityError(Exception):
    """Raised when a script attempts to use blocked/unsafe functionality."""
    pass


# =============================================================================
# SCRIPT HELPER CLASSES (available in script environment)
# =============================================================================

class RateCalculator:
    """Calculate rate of change over time."""
    def __init__(self):
        self._last_value = None
        self._last_time = None

    def update(self, value: float) -> float:
        now = time.time()
        if self._last_value is None:
            self._last_value = value
            self._last_time = now
            return 0.0
        dt = now - self._last_time
        if dt <= 0:
            return 0.0
        rate = (value - self._last_value) / dt
        self._last_value = value
        self._last_time = now
        return rate


class Accumulator:
    """Track cumulative totals."""
    def __init__(self, initial: float = 0.0):
        self.total = initial
        self._last_time = time.time()

    def add(self, value: float) -> float:
        now = time.time()
        dt = now - self._last_time
        self.total += value * dt
        self._last_time = now
        return self.total

    def reset(self):
        self.total = 0.0
        self._last_time = time.time()


class EdgeDetector:
    """Detect rising/falling edges on a boolean signal."""
    def __init__(self):
        self._last = None

    def update(self, value: bool) -> str:
        if self._last is None:
            self._last = value
            return 'none'
        if value and not self._last:
            self._last = value
            return 'rising'
        if not value and self._last:
            self._last = value
            return 'falling'
        self._last = value
        return 'none'


class RollingStats:
    """Running statistics over a window."""
    def __init__(self, window: int = 100):
        self._values = deque(maxlen=window)

    def update(self, value: float):
        self._values.append(value)

    @property
    def mean(self) -> float:
        return statistics.mean(self._values) if self._values else 0.0

    @property
    def min(self) -> float:
        return min(self._values) if self._values else 0.0

    @property
    def max(self) -> float:
        return max(self._values) if self._values else 0.0

    @property
    def std(self) -> float:
        return statistics.stdev(self._values) if len(self._values) > 1 else 0.0

    @property
    def count(self) -> int:
        return len(self._values)


# =============================================================================
# UNIVERSAL COUNTER
# =============================================================================

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
        self._events: list = []  # timestamps of tick() events

        # Debounce
        self._debounce_n = max(0, int(debounce))
        self._debounce_buf: list = []
        self._debounced_state = False

        # Edge detection (for update())
        self._last_bool: Any = None

        # Totalizer (rate integration)
        self._last_value: Any = None
        self._last_update_time = time.time()

        # Duty cycle / run hours
        self._is_on = False
        self._on_accum = 0.0        # seconds ON (within window or total)
        self._total_on = 0.0        # lifetime seconds ON
        self._last_duty_time = time.time()
        self._duty_events: list = []  # (timestamp, is_on) for windowed duty

        # Cycle tracking (ON→OFF = 1 cycle)
        self._cycle_count = 0
        self._cycle_start: Any = None
        self._cycle_times: list = []  # durations of completed cycles

        # Stopwatch / laps
        self._start_time = time.time()
        self._laps: dict = {}
        self._lap_start = time.time()

    # ----- core counting ------------------------------------------------

    def increment(self, n: int = 1):
        """Add *n* to count (default 1)."""
        self._count += n
        self._total += n
        self._check_target()

    def decrement(self, n: int = 1):
        """Subtract *n* from count (default 1)."""
        self._count -= n

    def tick(self):
        """Record a timestamped event (for sliding-window rate)."""
        self._events.append(time.time())
        self.increment()

    def reset(self):
        """Reset count to 0. Total and cycles are preserved."""
        self._count = 0
        self._start_time = time.time()
        self._lap_start = time.time()

    def set(self, value):
        """Set count to a specific value (tare / preset)."""
        self._count = value

    # ----- smart update -------------------------------------------------

    def update(self, value):
        """Smart update — call once per scan with the signal value.

        * **bool / 0-1 digital**: detects rising edges → increment,
          tracks duty cycle, run hours, and cycles.
        * **float / analog rate**: integrates value over dt → totalizer.
        * **cumulative mode**: always numeric — tracks delta between readings.
        """
        now = time.time()

        # Cumulative mode: always treat as numeric (hardware counters
        # can read 0 or 1 which would otherwise route to _update_bool)
        if self._mode == 'cumulative':
            self._update_analog(float(value), now)
            return

        # Decide bool vs analog
        is_bool = isinstance(value, bool) or (isinstance(value, (int, float)) and value in (0, 1, 0.0, 1.0, True, False))

        if is_bool:
            self._update_bool(bool(value), now)
        else:
            self._update_analog(float(value), now)

    def _update_bool(self, current: bool, now: float):
        """Handle boolean/digital signal."""
        # Debounce
        if self._debounce_n > 0:
            self._debounce_buf.append(current)
            if len(self._debounce_buf) > self._debounce_n:
                self._debounce_buf.pop(0)
            if len(self._debounce_buf) >= self._debounce_n:
                if all(v == current for v in self._debounce_buf):
                    current = current
                else:
                    current = self._debounced_state  # not stable yet
        self._debounced_state = current

        # Edge detection
        if self._last_bool is not None:
            # Rising edge → increment
            if current and not self._last_bool:
                self.increment()
                self._events.append(now)
                self._cycle_start = now

            # Falling edge → cycle complete
            if not current and self._last_bool:
                if self._cycle_start is not None:
                    dt = now - self._cycle_start
                    self._cycle_times.append(dt)
                    if len(self._cycle_times) > 200:
                        self._cycle_times.pop(0)
                    self._cycle_count += 1
                    self._cycle_start = None

        self._last_bool = current

        # Duty cycle tracking
        dt = now - self._last_duty_time
        if current:
            self._on_accum += dt
            self._total_on += dt
        self._last_duty_time = now
        self._is_on = current

        # Windowed duty events
        if self._window_seconds:
            self._duty_events.append((now, current))
            cutoff = now - self._window_seconds
            self._duty_events = [(t, v) for t, v in self._duty_events if t >= cutoff]

    def _update_analog(self, value: float, now: float):
        """Handle analog signal — integrate rate or track cumulative delta."""
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
        """True when count >= target."""
        if self._target is None:
            return False
        return self._count >= self._target

    @property
    def remaining(self):
        """How many left until target (0 if no target)."""
        if self._target is None:
            return 0
        return max(0, self._target - self._count)

    @property
    def batch(self) -> int:
        """How many times target has been reached (with auto_reset)."""
        return self._batch

    # ----- core properties -----------------------------------------------

    @property
    def count(self):
        """Current count (resets with ``reset()``)."""
        return self._count

    @property
    def total(self):
        """Lifetime cumulative total (never auto-resets)."""
        return self._total

    # ----- sliding window ------------------------------------------------

    @property
    def window_count(self) -> int:
        """Number of events in the sliding window."""
        if not self._window_seconds:
            return len(self._events)
        cutoff = time.time() - self._window_seconds
        self._events = [t for t in self._events if t >= cutoff]
        return len(self._events)

    @property
    def rate(self) -> float:
        """Events per second over the sliding window."""
        wc = self.window_count
        w = self._window_seconds or (time.time() - self._start_time)
        return wc / w if w > 0 else 0.0

    # ----- debounce ------------------------------------------------------

    @property
    def state(self) -> bool:
        """Current debounced boolean state."""
        return self._debounced_state

    @property
    def stable(self) -> bool:
        """True if debounce buffer is unanimous."""
        if self._debounce_n <= 0:
            return True
        if len(self._debounce_buf) < self._debounce_n:
            return False
        return len(set(self._debounce_buf)) == 1

    # ----- duty cycle / run hours ----------------------------------------

    @property
    def duty(self) -> float:
        """Duty cycle percentage (0-100) over the window (or lifetime)."""
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
            # Handle current state for last segment
            if events[-1][1]:
                on_time += now - events[-1][0]
            return min(100.0, (on_time / self._window_seconds) * 100)
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        return min(100.0, (self._total_on / elapsed) * 100)

    @property
    def run_time(self) -> float:
        """Cumulative seconds the signal has been ON."""
        extra = 0.0
        if self._is_on:
            extra = time.time() - self._last_duty_time
        return self._total_on + extra

    @property
    def run_hours(self) -> float:
        """Cumulative hours the signal has been ON."""
        return self.run_time / 3600.0

    # ----- cycle tracking ------------------------------------------------

    @property
    def cycles(self) -> int:
        """Total completed ON→OFF cycles."""
        return self._cycle_count

    @property
    def cycle_avg(self) -> float:
        """Mean cycle duration (seconds)."""
        return sum(self._cycle_times) / len(self._cycle_times) if self._cycle_times else 0.0

    @property
    def cycle_min(self) -> float:
        """Shortest cycle duration (seconds)."""
        return min(self._cycle_times) if self._cycle_times else 0.0

    @property
    def cycle_max(self) -> float:
        """Longest cycle duration (seconds)."""
        return max(self._cycle_times) if self._cycle_times else 0.0

    # ----- stopwatch / laps ----------------------------------------------

    @property
    def elapsed(self) -> float:
        """Seconds since creation or last ``reset()``."""
        return time.time() - self._start_time

    def lap(self, name: str):
        """Record a named lap. Duration is time since last lap or start."""
        now = time.time()
        self._laps[name] = now - self._lap_start
        self._lap_start = now

    @property
    def laps(self) -> dict:
        """Dict of ``{name: duration_seconds}``."""
        return dict(self._laps)


# =============================================================================
# UNIT CONVERSIONS
# =============================================================================

def F_to_C(f): return (f - 32) * 5 / 9
def C_to_F(c): return c * 9 / 5 + 32
def GPM_to_LPM(gpm): return gpm * 3.78541
def LPM_to_GPM(lpm): return lpm / 3.78541
def PSI_to_bar(psi): return psi * 0.0689476
def bar_to_PSI(bar): return bar / 0.0689476
def gal_to_L(gal): return gal * 3.78541
def L_to_gal(l): return l / 3.78541
def BTU_to_kJ(btu): return btu * 1.05506
def kJ_to_BTU(kj): return kj / 1.05506
def lb_to_kg(lb): return lb * 0.453592
def kg_to_lb(kg): return kg / 0.453592


# =============================================================================
# TIME HELPERS
# =============================================================================

def now(): return time.time()
def now_ms(): return int(time.time() * 1000)
def now_iso(): return datetime.now().isoformat()
def time_of_day(): return datetime.now().strftime('%H:%M:%S')
def elapsed_since(start_ts): return time.time() - start_ts
def format_timestamp(ts_ms, fmt='%Y-%m-%d %H:%M:%S'):
    return datetime.fromtimestamp(ts_ms / 1000).strftime(fmt)


# =============================================================================
# STATE PERSISTENCE
# =============================================================================

class StatePersistence:
    """Persist script state to disk (survives hot-reload and restart)."""

    def __init__(self, state_dir: str = '/home/admin/nisystem'):
        self._state_dir = state_dir
        self._state_file = os.path.join(state_dir, 'script_state.json')
        self._state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    self._state = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load script state: {e}")
            self._state = {}

    def _save(self):
        try:
            os.makedirs(self._state_dir, exist_ok=True)
            with open(self._state_file, 'w') as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save script state: {e}")

    def persist(self, script_id: str, key: str, value: Any):
        with self._lock:
            if script_id not in self._state:
                self._state[script_id] = {}
            self._state[script_id][key] = value
            self._save()

    def restore(self, script_id: str, key: str, default=None) -> Any:
        with self._lock:
            return self._state.get(script_id, {}).get(key, default)


class SharedVariableStore:
    """Thread-safe shared variable store for inter-script communication.

    All scripts share a single instance. Variables are simple key-value pairs.
    Optionally persists to disk and publishes changes via MQTT.
    """

    MAX_VARIABLES = 500

    def __init__(self, persistence: StatePersistence,
                 publish_fn: Optional[Callable] = None):
        self._data: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._persistence = persistence
        self._publish_fn = publish_fn
        self._dirty = False
        self._load()

    def _load(self):
        with self._lock:
            saved = self._persistence.restore('__shared_vars__', 'all', {})
            if isinstance(saved, dict):
                self._data = saved
                if self._data:
                    logger.info(f"Loaded {len(self._data)} shared variables from disk")

    def _save(self):
        self._persistence.persist('__shared_vars__', 'all', dict(self._data))
        self._dirty = False

    def _publish_change(self, name: str, value: Any):
        if self._publish_fn:
            try:
                self._publish_fn({name: value})
            except Exception as e:
                logger.warning(f"Failed to publish var change {name}: {e}")

    def get(self, name: str, default=None) -> Any:
        with self._lock:
            return self._data.get(name, default)

    def set(self, name: str, value: Any, persist: bool = True) -> bool:
        with self._lock:
            if name not in self._data and len(self._data) >= self.MAX_VARIABLES:
                logger.warning(f"Shared variable limit reached ({self.MAX_VARIABLES}), "
                               f"cannot create '{name}'")
                return False
            self._data[name] = value
            if persist:
                self._save()
            else:
                self._dirty = True
        self._publish_change(name, value)
        return True

    def reset(self, name: str) -> bool:
        with self._lock:
            if name not in self._data:
                return False
            old = self._data[name]
            self._data[name] = '' if isinstance(old, str) else 0
            self._save()
            reset_value = self._data[name]
        self._publish_change(name, reset_value)
        return True

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._data:
                return False
            del self._data[name]
            self._save()
        return True

    def keys(self) -> list:
        with self._lock:
            return list(self._data.keys())

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._data

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def flush(self):
        with self._lock:
            if self._dirty:
                self._save()


# =============================================================================
# SCRIPT API CLASSES
# =============================================================================

class TagsAPI:
    """Read-only access to channel values."""
    def __init__(self, get_values_fn: Callable):
        self._get_values = get_values_fn

    def get(self, name: str) -> float:
        values = self._get_values()
        entry = values.get(name, {})
        if isinstance(entry, dict):
            return entry.get('value', 0.0)
        return float(entry) if entry is not None else 0.0

    def __getattr__(self, name: str) -> float:
        if name.startswith('_'):
            raise AttributeError(name)
        return self.get(name)


class OutputsAPI:
    """Write output values."""
    def __init__(self, write_fn: Callable, is_locked_fn: Callable):
        self._write = write_fn
        self._is_locked = is_locked_fn

    def set(self, name: str, value: Any) -> bool:
        return self._write(name, value)

    def is_locked(self, name: str) -> bool:
        return self._is_locked(name)


class SessionAPI:
    """Read-only access to session state."""
    def __init__(self, get_state_fn: Callable):
        self._get_state = get_state_fn

    @property
    def active(self) -> bool:
        return self._get_state().get('session_active', False)

    @property
    def name(self) -> str:
        return self._get_state().get('session_name', '')

    @property
    def operator(self) -> str:
        return self._get_state().get('operator', '')

    @property
    def duration(self) -> float:
        state = self._get_state()
        start = state.get('start_time', 0)
        if start:
            return time.time() - start
        return 0.0

    def is_output_locked(self, channel: str) -> bool:
        state = self._get_state()
        return channel in state.get('locked_outputs', [])


class VarsAPI:
    """Shared variable API for inter-script communication.

    Interface matches DAQ service VarsAPI for script portability:
        vars.get('name')           # Get with default
        vars.set('name', value)    # Set value
        vars.reset('name')         # Reset to 0/empty
        vars.keys()                # List all variable names
        vars.MyVar                 # Attribute access (read)
        vars['MyVar']              # Index access (read)
        'MyVar' in vars            # Membership test

    Example:
        # Script A (producer)
        vars.set('shared_temp', tags.TC001)

        # Script B (consumer)
        temp = vars.shared_temp
    """

    def __init__(self, store: SharedVariableStore):
        object.__setattr__(self, '_store', store)

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        value = self._store.get(name)
        return 0.0 if value is None else value

    def __getitem__(self, name: str):
        value = self._store.get(name)
        return 0.0 if value is None else value

    def __contains__(self, name: str) -> bool:
        return self._store.has(name)

    def get(self, name: str, default=0.0):
        if self._store.has(name):
            return self._store.get(name)
        return default

    def set(self, name: str, value, persist: bool = True) -> bool:
        return self._store.set(name, value, persist=persist)

    def reset(self, name: str) -> bool:
        return self._store.reset(name)

    def keys(self) -> list:
        return self._store.keys()

    def delete(self, name: str) -> bool:
        return self._store.delete(name)

    def flush(self):
        self._store.flush()


# =============================================================================
# SCRIPT ENGINE
# =============================================================================

class ScriptEngine:
    """
    Manages Python script execution on the cRIO.

    Scripts run in daemon threads with a sandboxed environment.
    Supports manual, acquisition, and session run modes.
    """

    def __init__(self, node):
        """
        Initialize the script engine.

        Args:
            node: CRIONodeV2 instance (provides channel values, MQTT, state, etc.)
        """
        self._node = node
        self.scripts: Dict[str, Dict[str, Any]] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._persistence = StatePersistence()
        self._shared_vars = SharedVariableStore(
            persistence=self._persistence,
            publish_fn=self._publish_vars
        )

    # =========================================================================
    # MQTT COMMAND HANDLER
    # =========================================================================

    def handle_command(self, topic: str, payload: Dict[str, Any]):
        """Route script MQTT commands."""
        if topic.endswith('/add'):
            self._cmd_add(payload)
        elif topic.endswith('/start'):
            self._cmd_start(payload)
        elif topic.endswith('/stop'):
            self._cmd_stop(payload)
        elif topic.endswith('/remove'):
            self._cmd_remove(payload)
        elif topic.endswith('/update'):
            self._cmd_update(payload)
        elif topic.endswith('/reload'):
            self._cmd_reload(payload)
        elif topic.endswith('/list') or topic.endswith('/status'):
            self.publish_status()
        elif topic.endswith('/clear-all'):
            self._cmd_clear_all()

    # =========================================================================
    # COMMAND IMPLEMENTATIONS
    # =========================================================================

    def _cmd_add(self, payload: Dict[str, Any]):
        """Add a new script."""
        script_id = payload.get('id')
        if not script_id:
            return

        self.scripts[script_id] = payload
        logger.info(f"Script added: {script_id} ({payload.get('name', 'unnamed')})")
        self.publish_status()

    def _cmd_start(self, payload: Dict[str, Any]):
        """Start a script."""
        script_id = payload.get('id')
        if not script_id:
            return

        self._start_script(script_id)

    def _cmd_stop(self, payload: Dict[str, Any]):
        """Stop a script."""
        script_id = payload.get('id')
        if not script_id:
            return

        self._stop_script(script_id)

    def _cmd_remove(self, payload: Dict[str, Any]):
        """Remove a script."""
        script_id = payload.get('id')
        if not script_id:
            return

        self._stop_script(script_id)
        self.scripts.pop(script_id, None)
        logger.info(f"Script removed: {script_id}")
        self.publish_status()

    def _cmd_update(self, payload: Dict[str, Any]):
        """Update script properties (does not affect running instance)."""
        script_id = payload.get('id')
        if not script_id or script_id not in self.scripts:
            return

        script = self.scripts[script_id]
        if 'code' in payload:
            script['code'] = payload['code']
        if 'name' in payload:
            script['name'] = payload['name']
        if 'run_mode' in payload:
            script['run_mode'] = payload['run_mode']
        if 'runMode' in payload:
            script['run_mode'] = payload['runMode']
        if 'enabled' in payload:
            script['enabled'] = payload['enabled']

        logger.info(f"Script updated: {script_id}")
        self.publish_status()

    def _cmd_reload(self, payload: Dict[str, Any]):
        """Hot-reload: stop, update code, restart if was running."""
        script_id = payload.get('id')
        new_code = payload.get('code')

        if not script_id or script_id not in self.scripts:
            logger.warning(f"Hot-reload: script not found: {script_id}")
            return

        script = self.scripts[script_id]
        was_running = self._is_running(script_id)

        logger.info(f"Hot-reload: {script.get('name', script_id)} (was_running={was_running})")

        # Stop if running
        if was_running:
            self._stop_script(script_id)
            thread = self._threads.get(script_id)
            if thread:
                thread.join(timeout=5.0)
            time.sleep(0.1)

        # Update code
        if new_code is not None:
            script['code'] = new_code

        # Clear stop flag
        script['_stop_requested'] = False

        # Restart if was running
        if was_running:
            self._start_script(script_id)

        self.publish_status()

    def _cmd_clear_all(self):
        """Stop and remove all scripts."""
        for script_id in list(self.scripts.keys()):
            self._stop_script(script_id)
        self.scripts.clear()
        logger.info("All scripts cleared")
        self.publish_status()

    # =========================================================================
    # SCRIPT LIFECYCLE
    # =========================================================================

    def _start_script(self, script_id: str):
        """Start executing a script in a daemon thread."""
        if script_id not in self.scripts:
            logger.warning(f"Script not found: {script_id}")
            return

        if self._is_running(script_id):
            logger.warning(f"Script already running: {script_id}")
            return

        script = self.scripts[script_id]
        script['_start_time'] = time.time()
        script['_stop_requested'] = False

        # Execution thread
        thread = threading.Thread(
            target=self._run_script,
            args=(script_id, script),
            name=f"Script-{script_id}",
            daemon=True
        )
        self._threads[script_id] = thread
        thread.start()

        logger.info(f"Started script: {script_id}")
        self.publish_status()
        self._publish_output(script_id, f"Script started: {script.get('name', script_id)}")

    def _stop_script(self, script_id: str):
        """Request a script to stop."""
        if script_id in self.scripts:
            self.scripts[script_id]['_stop_requested'] = True
            logger.info(f"Stop requested: {script_id}")
            self.publish_status()

    def _is_running(self, script_id: str) -> bool:
        """Check if a script is currently running."""
        thread = self._threads.get(script_id)
        return thread is not None and thread.is_alive()

    # =========================================================================
    # RUN MODE AUTO-START/STOP
    # =========================================================================

    def auto_start(self, run_mode: str):
        """Auto-start scripts matching the given run_mode."""
        for script_id, script in self.scripts.items():
            script_mode = script.get('run_mode') or script.get('runMode', 'manual')
            enabled = script.get('enabled', True)
            if enabled and script_mode == run_mode:
                logger.info(f"Auto-starting {run_mode} script: {script_id}")
                self._start_script(script_id)

    def auto_stop(self, run_mode: str):
        """Auto-stop scripts matching the given run_mode and wait."""
        to_stop = []
        for script_id, script in self.scripts.items():
            script_mode = script.get('run_mode') or script.get('runMode', 'manual')
            if script_mode == run_mode and self._is_running(script_id):
                logger.info(f"Auto-stopping {run_mode} script: {script_id}")
                self._stop_script(script_id)
                to_stop.append(script_id)

        if to_stop:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                still_running = [s for s in to_stop if self._is_running(s)]
                if not still_running:
                    logger.info("All auto-stopped scripts finished")
                    break
                time.sleep(0.1)
            else:
                still = [s for s in to_stop if self._is_running(s)]
                if still:
                    logger.warning(f"Scripts did not stop in time: {still}")

    def stop_all(self):
        """Stop all running scripts."""
        for script_id in list(self.scripts.keys()):
            if self._is_running(script_id):
                self._stop_script(script_id)

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def _run_script(self, script_id: str, script: Dict[str, Any]):
        """Execute a Python script with sandboxed environment."""
        code = script.get('code', '')
        scan_rate = self._node.config.scan_rate_hz

        # --- Helper functions available to scripts ---

        def wait_for(seconds: float) -> bool:
            """Sleep for given seconds, respecting stop request. Returns True if stopped."""
            interval = 0.1
            elapsed = 0.0
            while elapsed < seconds:
                if script.get('_stop_requested', False):
                    return True
                time.sleep(min(interval, seconds - elapsed))
                elapsed += interval
            return False

        def wait_until(condition_fn, timeout: float = 60.0) -> bool:
            """Wait until condition returns True. Returns False on timeout."""
            start = time.time()
            while time.time() - start < timeout:
                if script.get('_stop_requested', False):
                    return False
                if condition_fn():
                    return True
                time.sleep(0.1)
            return False

        def get_channel_values():
            with self._node.values_lock:
                return dict(self._node.channel_values)

        def write_output(name: str, value: Any) -> bool:
            if self._node.state.is_output_locked(name):
                return False
            # Block writes to outputs held by safety actions
            if self._node.safety.is_safety_held(name):
                hold_info = self._node.safety.get_safety_hold_info(name)
                alarm_ch = hold_info.get('alarm_channel', '?') if hold_info else '?'
                logger.warning(f"Script write blocked: {name} is safety-held "
                              f"(held by alarm on {alarm_ch})")
                return False
            success = self._node.hardware.write_output(name, value)
            if success:
                # Use timeout on lock to avoid blocking safety-critical operations
                if self._node.values_lock.acquire(timeout=0.5):
                    try:
                        self._node.output_values[name] = value
                    finally:
                        self._node.values_lock.release()
                else:
                    logger.warning(f"Script write_output: could not acquire values_lock for {name} (timeout)")
                self._node._publish_single_channel(name, value, 'output')
            return success

        def is_output_locked(name: str) -> bool:
            return self._node.state.is_output_locked(name)

        def publish_value(name: str, value: Any):
            self._node.mqtt.publish("script/values", {name: value})

        def get_session_state() -> dict:
            status = self._node.state.get_status()
            return status

        def script_print(*args):
            msg = ' '.join(str(a) for a in args)
            logger.info(f"[Script {script_id}] {msg}")
            self._publish_output(script_id, msg)

        # Build execution environment
        env = {
            # Core APIs
            'tags': TagsAPI(get_channel_values),
            'outputs': OutputsAPI(write_output, is_output_locked),
            'publish': publish_value,
            'session': SessionAPI(get_session_state),
            'vars': VarsAPI(self._shared_vars),

            # Control flow
            'next_scan': lambda: time.sleep(1.0 / scan_rate),
            'wait_for': wait_for,
            'wait_until': wait_until,
            'should_stop': lambda: script.get('_stop_requested', False),

            # State persistence
            'persist': lambda key, value: self._persistence.persist(script_id, key, value),
            'restore': lambda key, default=None: self._persistence.restore(script_id, key, default),

            # Helper classes
            'Counter': Counter,
            'RateCalculator': RateCalculator,
            'Accumulator': Accumulator,
            'EdgeDetector': EdgeDetector,
            'RollingStats': RollingStats,

            # Unit conversions
            'F_to_C': F_to_C, 'C_to_F': C_to_F,
            'GPM_to_LPM': GPM_to_LPM, 'LPM_to_GPM': LPM_to_GPM,
            'PSI_to_bar': PSI_to_bar, 'bar_to_PSI': bar_to_PSI,
            'gal_to_L': gal_to_L, 'L_to_gal': L_to_gal,
            'BTU_to_kJ': BTU_to_kJ, 'kJ_to_BTU': kJ_to_BTU,
            'lb_to_kg': lb_to_kg, 'kg_to_lb': kg_to_lb,

            # Time functions
            'now': now, 'now_ms': now_ms, 'now_iso': now_iso,
            'time_of_day': time_of_day, 'elapsed_since': elapsed_since,
            'format_timestamp': format_timestamp,

            # Standard library (safe subset)
            'time': time,
            'math': math,
            'datetime': datetime,
            'json': json,
            're': re,
            'statistics': statistics,

            # Built-ins (safe subset)
            'abs': abs,
            'all': all,
            'any': any,
            'bool': bool,
            'dict': dict,
            'enumerate': enumerate,
            'filter': filter,
            'float': float,
            'int': int,
            'isinstance': isinstance,
            'len': len,
            'list': list,
            'map': map,
            'max': max,
            'min': min,
            'pow': pow,
            'print': script_print,
            'range': range,
            'reversed': reversed,
            'round': round,
            'set': set,
            'sorted': sorted,
            'str': str,
            'sum': sum,
            'tuple': tuple,
            'zip': zip,
            'True': True,
            'False': False,
            'None': None,

            # Restrict dangerous builtins
            '__builtins__': {},
        }

        try:
            # Strip 'await' keywords for sync execution
            code = code.replace('await ', '')

            # AST-based sandbox validation
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

            class _ScriptValidator(ast.NodeVisitor):
                def visit_Import(self, node):
                    raise SecurityError(
                        "Import statements are not allowed for safety reasons"
                    )

                def visit_ImportFrom(self, node):
                    raise SecurityError(
                        "Import statements are not allowed for safety reasons"
                    )

                def visit_Attribute(self, node):
                    if node.attr in _blocked_dunder_attrs:
                        raise SecurityError(
                            f"Access to '{node.attr}' is not allowed for safety reasons"
                        )
                    self.generic_visit(node)

                def visit_Call(self, node):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in _blocked_func_names:
                            raise SecurityError(
                                f"Call to '{node.func.id}()' is not allowed for safety reasons"
                            )
                    self.generic_visit(node)

                def visit_Name(self, node):
                    if node.id in _blocked_module_names:
                        raise SecurityError(
                            f"Access to '{node.id}' module is not allowed for safety reasons"
                        )
                    self.generic_visit(node)

            tree = ast.parse(code, mode='exec')
            _ScriptValidator().visit(tree)

            exec(code, env, env)
            logger.info(f"Script completed: {script_id}")
            self._publish_output(script_id, "Script completed")
        except Exception as e:
            logger.error(f"Script error ({script_id}): {e}")
            self._publish_output(script_id, f"ERROR: {e}", is_error=True)
        finally:
            script['_stop_requested'] = False
            self.publish_status()

    # =========================================================================
    # STATUS PUBLISHING
    # =========================================================================

    def publish_status(self):
        """Publish status of all scripts."""
        status = {}
        for script_id, script in self.scripts.items():
            status[script_id] = {
                'id': script_id,
                'name': script.get('name', script_id),
                'running': self._is_running(script_id),
                'run_mode': script.get('run_mode') or script.get('runMode', 'manual'),
                'enabled': script.get('enabled', True),
                'stop_requested': script.get('_stop_requested', False),
                'code': script.get('code', ''),
            }
        self._node.mqtt.publish("script/status", status)

    def _publish_vars(self, changed: Dict[str, Any]):
        """Publish shared variable changes to dashboard via MQTT."""
        self._node.mqtt.publish("script/values", changed)

    def _publish_output(self, script_id: str, message: str, is_error: bool = False):
        """Publish script console output."""
        self._node.mqtt.publish("script/output", {
            'script_id': script_id,
            'message': message,
            'is_error': is_error,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
