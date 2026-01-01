#!/usr/bin/env python3
"""
User Variables Manager for NISystem
Handles user-defined variables (accumulators, counters, timers, manual values)
with persistence and test session coordination.
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger('UserVariables')


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class UserVariable:
    """User-defined variable with persistence and edge detection

    Variable Types:
    - constant: Fixed value for use in formulas (calibration factors, setpoints, etc.)
    - manual: User sets value directly
    - accumulator: Watches counter channel for increments, adds to running total
    - counter: Counts edge transitions (rising/falling)
    - timer: Elapsed time since start
    - sum: Running sum of channel values (resets per config)
    - average: Running average of channel values
    - min: Minimum value seen since last reset
    - max: Maximum value seen since last reset
    - expression: Calculated from formula (like existing CalculatedParam but persistent)
    - rolling: Sliding window accumulator (e.g., last 24 hours) - stores timestamped samples
    """
    id: str
    name: str
    display_name: str
    variable_type: str  # 'constant', 'manual', 'accumulator', 'timer', 'counter', 'sum', 'average', 'min', 'max', 'expression'
    description: str = ""  # User description of the variable
    value: float = 0.0
    units: str = ""
    persistent: bool = True  # Survives restarts

    # Accumulator/Counter config
    source_channel: Optional[str] = None  # Channel to watch
    edge_type: str = 'increment'  # 'increment', 'rising', 'falling'
    scale_factor: float = 1.0  # Multiply by this

    # Reset config
    reset_mode: str = 'manual'  # 'manual', 'time_of_day', 'elapsed', 'test_session', 'never'
    reset_time: Optional[str] = None  # HH:MM for time_of_day reset
    reset_elapsed_s: Optional[int] = None  # Seconds for elapsed reset
    last_reset: Optional[str] = None  # ISO timestamp of last reset

    # Timer-specific
    timer_running: bool = False
    timer_start_time: Optional[float] = None  # Unix timestamp when timer started

    # Statistics tracking (for sum/average/min/max)
    sample_count: int = 0  # Number of samples collected (for average)

    # Expression-specific
    formula: Optional[str] = None  # Formula string like "TC101 * 1.8 + 32"

    # Rolling window config (for 'rolling' type)
    rolling_window_s: int = 86400  # Window size in seconds (default 24 hours)
    rolling_samples: Optional[List[Dict[str, float]]] = None  # List of {timestamp, value} pairs

    # Runtime state (not persisted)
    _last_source_value: Optional[float] = field(default=None, repr=False)
    _last_update: Optional[float] = field(default=None, repr=False)
    _sum_accumulator: float = field(default=0.0, repr=False)  # For average calculation
    _rolling_buffer: List[tuple] = field(default_factory=list, repr=False)  # Runtime: [(timestamp, value), ...]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for persistence (excludes runtime state)"""
        d = {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'variable_type': self.variable_type,
            'description': self.description,
            'value': self.value,
            'units': self.units,
            'persistent': self.persistent,
            'source_channel': self.source_channel,
            'edge_type': self.edge_type,
            'scale_factor': self.scale_factor,
            'reset_mode': self.reset_mode,
            'reset_time': self.reset_time,
            'reset_elapsed_s': self.reset_elapsed_s,
            'last_reset': self.last_reset,
            'timer_running': self.timer_running,
            'timer_start_time': self.timer_start_time,
            'sample_count': self.sample_count,
            'formula': self.formula,
            'rolling_window_s': self.rolling_window_s,
        }
        # Only persist rolling samples for rolling type variables
        if self.variable_type == 'rolling' and self._rolling_buffer:
            # Store as list of dicts for JSON serialization
            d['rolling_samples'] = [{'t': t, 'v': v} for t, v in self._rolling_buffer]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserVariable':
        """Create from dictionary"""
        var = cls(
            id=data['id'],
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            variable_type=data['variable_type'],
            description=data.get('description', ''),
            value=data.get('value', 0.0),
            units=data.get('units', ''),
            persistent=data.get('persistent', True),
            source_channel=data.get('source_channel'),
            edge_type=data.get('edge_type', 'increment'),
            scale_factor=data.get('scale_factor', 1.0),
            reset_mode=data.get('reset_mode', 'manual'),
            reset_time=data.get('reset_time'),
            reset_elapsed_s=data.get('reset_elapsed_s'),
            last_reset=data.get('last_reset'),
            timer_running=data.get('timer_running', False),
            timer_start_time=data.get('timer_start_time'),
            sample_count=data.get('sample_count', 0),
            formula=data.get('formula'),
            rolling_window_s=data.get('rolling_window_s', 86400),
        )
        # Restore rolling samples if present
        if 'rolling_samples' in data and data['rolling_samples']:
            var._rolling_buffer = [(s['t'], s['v']) for s in data['rolling_samples']]
        return var


@dataclass
class TestSessionConfig:
    """Configuration for test session behavior"""
    enable_scheduler: bool = True
    start_recording: bool = True
    enable_triggers: bool = True
    reset_variables: List[str] = field(default_factory=list)  # Variable IDs to reset on start
    run_sequence_id: Optional[str] = None  # Optional sequence to run at start
    stop_sequence_id: Optional[str] = None  # Optional sequence to run at stop

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestSessionConfig':
        return cls(
            enable_scheduler=data.get('enable_scheduler', True),
            start_recording=data.get('start_recording', True),
            enable_triggers=data.get('enable_triggers', True),
            reset_variables=data.get('reset_variables', []),
            run_sequence_id=data.get('run_sequence_id'),
            stop_sequence_id=data.get('stop_sequence_id'),
        )


@dataclass
class TestSession:
    """Test session state"""
    active: bool = False
    started_at: Optional[str] = None  # ISO timestamp
    started_by: Optional[str] = None
    config: TestSessionConfig = field(default_factory=TestSessionConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'active': self.active,
            'started_at': self.started_at,
            'started_by': self.started_by,
            'config': self.config.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestSession':
        return cls(
            active=data.get('active', False),
            started_at=data.get('started_at'),
            started_by=data.get('started_by'),
            config=TestSessionConfig.from_dict(data.get('config', {})),
        )


# =============================================================================
# USER VARIABLE MANAGER
# =============================================================================

class UserVariableManager:
    """
    Manages user-defined variables with:
    - Edge detection for accumulators/counters
    - Timer tracking
    - Automatic reset conditions
    - Persistence to disk
    - Test session coordination
    """

    def __init__(
        self,
        data_dir: str = "data",
        on_session_start: Optional[Callable[[], None]] = None,
        on_session_stop: Optional[Callable[[], None]] = None,
        scheduler_enable: Optional[Callable[[bool], None]] = None,
        recording_start: Optional[Callable[[], None]] = None,
        recording_stop: Optional[Callable[[], None]] = None,
        run_sequence: Optional[Callable[[str], None]] = None,
        stop_sequence: Optional[Callable[[], None]] = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.variables_file = self.data_dir / "user_variables.json"
        self.session_file = self.data_dir / "test_session.json"

        # Callbacks for test session coordination
        self.on_session_start = on_session_start
        self.on_session_stop = on_session_stop
        self.scheduler_enable = scheduler_enable
        self.recording_start = recording_start
        self.recording_stop = recording_stop
        self.run_sequence = run_sequence
        self.stop_sequence = stop_sequence

        # State
        self.variables: Dict[str, UserVariable] = {}
        self.session = TestSession()
        self.lock = threading.Lock()

        # Track last reset check time for time-of-day resets
        self._last_reset_check_date: Optional[str] = None

        # Load persisted state
        self._load_state()

        logger.info(f"UserVariableManager initialized with {len(self.variables)} variables")

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _load_state(self):
        """Load variables and session from disk"""
        # Load variables
        if self.variables_file.exists():
            try:
                with open(self.variables_file, 'r') as f:
                    data = json.load(f)
                for var_data in data.get('variables', []):
                    var = UserVariable.from_dict(var_data)
                    self.variables[var.id] = var
                logger.info(f"Loaded {len(self.variables)} user variables from disk")
            except Exception as e:
                logger.error(f"Failed to load user variables: {e}")

        # Load session config (but not active state - session doesn't survive restart)
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
                self.session.config = TestSessionConfig.from_dict(data.get('config', {}))
                # Don't restore active state - session must be explicitly started
                self.session.active = False
                self.session.started_at = None
                logger.info("Loaded test session config from disk")
            except Exception as e:
                logger.error(f"Failed to load test session config: {e}")

    def _save_variables(self):
        """Save variables to disk"""
        try:
            data = {
                'variables': [v.to_dict() for v in self.variables.values() if v.persistent]
            }
            with open(self.variables_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user variables: {e}")

    def _save_session_config(self):
        """Save session config to disk"""
        try:
            data = {'config': self.session.config.to_dict()}
            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save test session config: {e}")

    # =========================================================================
    # VARIABLE CRUD
    # =========================================================================

    def create_variable(self, var_data: Dict[str, Any]) -> UserVariable:
        """Create a new user variable"""
        with self.lock:
            var = UserVariable.from_dict(var_data)
            var.last_reset = datetime.now().isoformat()
            self.variables[var.id] = var
            self._save_variables()
            logger.info(f"Created user variable: {var.name} ({var.variable_type})")
            return var

    def update_variable(self, var_id: str, updates: Dict[str, Any]) -> Optional[UserVariable]:
        """Update an existing variable's configuration"""
        with self.lock:
            if var_id not in self.variables:
                logger.warning(f"Variable not found: {var_id}")
                return None

            var = self.variables[var_id]
            for key, value in updates.items():
                if hasattr(var, key) and not key.startswith('_'):
                    setattr(var, key, value)

            self._save_variables()
            logger.info(f"Updated user variable: {var.name}")
            return var

    def delete_variable(self, var_id: str) -> bool:
        """Delete a user variable"""
        with self.lock:
            if var_id not in self.variables:
                return False

            var = self.variables.pop(var_id)
            self._save_variables()
            logger.info(f"Deleted user variable: {var.name}")
            return True

    def get_variable(self, var_id: str) -> Optional[UserVariable]:
        """Get a variable by ID"""
        return self.variables.get(var_id)

    def get_all_variables(self) -> List[UserVariable]:
        """Get all variables"""
        return list(self.variables.values())

    def set_variable_value(self, var_id: str, value: float) -> bool:
        """Manually set a variable's value (for manual type or override)"""
        with self.lock:
            if var_id not in self.variables:
                return False

            var = self.variables[var_id]
            var.value = value
            var._last_update = datetime.now().timestamp()

            if var.persistent:
                self._save_variables()

            return True

    def reset_variable(self, var_id: str) -> bool:
        """Reset a variable to 0"""
        with self.lock:
            if var_id not in self.variables:
                return False

            var = self.variables[var_id]
            var.value = 0.0
            var.last_reset = datetime.now().isoformat()
            var._last_source_value = None  # Reset edge detection

            # Reset timer if applicable
            if var.variable_type == 'timer':
                var.timer_running = False
                var.timer_start_time = None

            # Reset statistics tracking
            if var.variable_type in ('sum', 'average', 'min', 'max'):
                var.sample_count = 0
                var._sum_accumulator = 0.0

            # Reset rolling buffer
            if var.variable_type == 'rolling':
                var._rolling_buffer = []
                var.sample_count = 0

            if var.persistent:
                self._save_variables()

            logger.info(f"Reset variable: {var.name}")
            return True

    def reset_all_variables(self, var_ids: Optional[List[str]] = None):
        """Reset multiple variables (or all if no IDs provided)"""
        with self.lock:
            ids_to_reset = var_ids if var_ids else list(self.variables.keys())
            for var_id in ids_to_reset:
                if var_id in self.variables:
                    var = self.variables[var_id]
                    var.value = 0.0
                    var.last_reset = datetime.now().isoformat()
                    var._last_source_value = None
                    if var.variable_type == 'timer':
                        var.timer_running = False
                        var.timer_start_time = None
                    if var.variable_type in ('sum', 'average', 'min', 'max'):
                        var.sample_count = 0
                        var._sum_accumulator = 0.0
                    if var.variable_type == 'rolling':
                        var._rolling_buffer = []
                        var.sample_count = 0

            self._save_variables()
            logger.info(f"Reset {len(ids_to_reset)} variables")

    # =========================================================================
    # EDGE DETECTION & PROCESSING
    # =========================================================================

    def _check_accumulator_edge(self, var: UserVariable, current_value: float) -> float:
        """
        Check for edge/increment on source channel.
        Returns the increment to add (0 if no edge detected).
        """
        if var._last_source_value is None:
            # First reading - initialize but don't count
            var._last_source_value = current_value
            return 0.0

        last = var._last_source_value
        var._last_source_value = current_value

        if var.edge_type == 'increment':
            # Counter went up by any amount (handles 0→1 after reset)
            if current_value > last:
                return (current_value - last) * var.scale_factor
            # Counter reset detected (value dropped), ignore
            return 0.0

        elif var.edge_type == 'rising':
            # Boolean: was 0, now 1
            if last == 0 and current_value == 1:
                return 1.0 * var.scale_factor
            return 0.0

        elif var.edge_type == 'falling':
            # Boolean: was 1, now 0
            if last == 1 and current_value == 0:
                return 1.0 * var.scale_factor
            return 0.0

        return 0.0

    def _check_reset_conditions(self, var: UserVariable, now: datetime):
        """Check and apply automatic reset conditions"""
        if var.reset_mode == 'manual' or var.reset_mode == 'never':
            return  # No automatic reset

        if var.reset_mode == 'test_session':
            return  # Only reset on session start, handled elsewhere

        if var.reset_mode == 'time_of_day' and var.reset_time:
            # Reset at specific time of day (once per day)
            try:
                reset_hour, reset_minute = map(int, var.reset_time.split(':'))
                reset_time = dt_time(reset_hour, reset_minute)
                current_time = now.time()
                today_str = now.strftime('%Y-%m-%d')

                # Check if we've already reset today
                last_reset_date = None
                if var.last_reset:
                    try:
                        last_reset_date = var.last_reset[:10]  # YYYY-MM-DD
                    except:
                        pass

                # Reset if: current time >= reset time AND we haven't reset today
                if (current_time >= reset_time and last_reset_date != today_str):
                    var.value = 0.0
                    var.last_reset = now.isoformat()
                    var._last_source_value = None
                    logger.info(f"Time-of-day reset triggered for: {var.name}")
            except ValueError:
                logger.warning(f"Invalid reset_time format for {var.name}: {var.reset_time}")

        elif var.reset_mode == 'elapsed' and var.reset_elapsed_s:
            # Reset after elapsed time
            if var.last_reset:
                try:
                    last_reset_dt = datetime.fromisoformat(var.last_reset)
                    elapsed = (now - last_reset_dt).total_seconds()
                    if elapsed >= var.reset_elapsed_s:
                        var.value = 0.0
                        var.last_reset = now.isoformat()
                        var._last_source_value = None
                        logger.info(f"Elapsed time reset triggered for: {var.name}")
                except:
                    pass

    def _update_timer(self, var: UserVariable, now: float):
        """Update timer variable value"""
        if var.timer_running and var.timer_start_time is not None:
            # Timer value is elapsed seconds since start
            var.value = now - var.timer_start_time

    def _update_statistics(self, var: UserVariable, current_value: float):
        """Update statistical variables (sum, average, min, max)"""
        if var.variable_type == 'sum':
            # Running sum
            var.value += current_value * var.scale_factor
            var.sample_count += 1

        elif var.variable_type == 'average':
            # Running average (incremental formula)
            var.sample_count += 1
            var._sum_accumulator += current_value * var.scale_factor
            var.value = var._sum_accumulator / var.sample_count

        elif var.variable_type == 'min':
            # Track minimum
            scaled = current_value * var.scale_factor
            if var.sample_count == 0:
                var.value = scaled
            else:
                var.value = min(var.value, scaled)
            var.sample_count += 1

        elif var.variable_type == 'max':
            # Track maximum
            scaled = current_value * var.scale_factor
            if var.sample_count == 0:
                var.value = scaled
            else:
                var.value = max(var.value, scaled)
            var.sample_count += 1

    def _update_rolling(self, var: UserVariable, current_value: float, now_ts: float):
        """
        Update rolling window accumulator (sliding 24-hour total).

        Uses edge detection on the source channel (like accumulator) but maintains
        a timestamped ring buffer of increments. The value is the sum of all samples
        within the rolling window.

        This is useful for "last 24 hours" totals that continuously update,
        unlike time_of_day reset which only resets at a specific time.
        """
        # Check for increment using same edge detection as accumulator
        increment = self._check_accumulator_edge(var, current_value)

        if increment != 0:
            # Add new sample with timestamp
            var._rolling_buffer.append((now_ts, increment))

        # Prune samples outside the rolling window
        cutoff = now_ts - var.rolling_window_s
        var._rolling_buffer = [(t, v) for t, v in var._rolling_buffer if t > cutoff]

        # Calculate sum of all samples in window
        var.value = sum(v for _, v in var._rolling_buffer)
        var.sample_count = len(var._rolling_buffer)

    def _evaluate_expression(self, var: UserVariable, channel_values: Dict[str, float]) -> Optional[float]:
        """Evaluate expression formula with channel values and user variables"""
        if not var.formula:
            return None

        try:
            # Build namespace with channel values
            namespace = dict(channel_values)

            # Add user variables (constants and other variables) to namespace
            # Use variable name as the key so formulas can reference them
            for v in self.variables.values():
                if v.id != var.id:  # Don't include self to avoid circular refs
                    namespace[v.name] = v.value

            # Add math functions
            import math
            namespace.update({
                'abs': abs, 'min': min, 'max': max, 'sum': sum,
                'sqrt': math.sqrt, 'pow': pow,
                'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
                'log': math.log, 'log10': math.log10, 'exp': math.exp,
                'pi': math.pi, 'e': math.e,
            })

            result = eval(var.formula, {"__builtins__": {}}, namespace)
            return float(result) * var.scale_factor
        except Exception as e:
            logger.debug(f"Expression evaluation error for {var.name}: {e}")
            return None

    def process_scan(self, channel_values: Dict[str, float]):
        """
        Process a scan cycle - update all variables based on channel values.
        Call this from the DAQ scan loop.
        """
        now = datetime.now()
        now_ts = now.timestamp()

        with self.lock:
            for var in self.variables.values():
                # Check reset conditions first
                self._check_reset_conditions(var, now)

                if var.variable_type == 'accumulator' or var.variable_type == 'counter':
                    if var.source_channel and var.source_channel in channel_values:
                        source_value = channel_values[var.source_channel]
                        increment = self._check_accumulator_edge(var, source_value)
                        if increment != 0:
                            var.value += increment
                            var._last_update = now_ts

                elif var.variable_type == 'timer':
                    self._update_timer(var, now_ts)
                    var._last_update = now_ts

                elif var.variable_type in ('sum', 'average', 'min', 'max'):
                    if var.source_channel and var.source_channel in channel_values:
                        source_value = channel_values[var.source_channel]
                        self._update_statistics(var, source_value)
                        var._last_update = now_ts

                elif var.variable_type == 'expression':
                    result = self._evaluate_expression(var, channel_values)
                    if result is not None:
                        var.value = result
                        var._last_update = now_ts

                elif var.variable_type == 'rolling':
                    # Rolling/sliding window accumulator (e.g., last 24 hours)
                    if var.source_channel and var.source_channel in channel_values:
                        source_value = channel_values[var.source_channel]
                        self._update_rolling(var, source_value, now_ts)
                        var._last_update = now_ts

                # Manual variables don't update automatically

            # Periodically save persistent variables (not every scan)
            # This is handled by save being called on value changes

    def start_timer(self, var_id: str) -> bool:
        """Start a timer variable"""
        with self.lock:
            if var_id not in self.variables:
                return False
            var = self.variables[var_id]
            if var.variable_type != 'timer':
                return False

            if not var.timer_running:
                var.timer_running = True
                var.timer_start_time = datetime.now().timestamp() - var.value  # Resume from current value
                logger.info(f"Started timer: {var.name}")
            return True

    def stop_timer(self, var_id: str) -> bool:
        """Stop a timer variable (preserves accumulated time)"""
        with self.lock:
            if var_id not in self.variables:
                return False
            var = self.variables[var_id]
            if var.variable_type != 'timer':
                return False

            if var.timer_running:
                # Capture final elapsed time
                if var.timer_start_time:
                    var.value = datetime.now().timestamp() - var.timer_start_time
                var.timer_running = False
                var.timer_start_time = None
                if var.persistent:
                    self._save_variables()
                logger.info(f"Stopped timer: {var.name}")
            return True

    # =========================================================================
    # TEST SESSION MANAGEMENT
    # =========================================================================

    def update_session_config(self, config_data: Dict[str, Any]):
        """Update test session configuration"""
        with self.lock:
            self.session.config = TestSessionConfig.from_dict(config_data)
            self._save_session_config()
            logger.info("Updated test session configuration")

    def get_session_config(self) -> Dict[str, Any]:
        """Get current session configuration"""
        return self.session.config.to_dict()

    def start_session(self, acquiring: bool, started_by: str = "user") -> Dict[str, Any]:
        """
        Start a test session.
        Returns status dict with success/error info.
        """
        with self.lock:
            if self.session.active:
                return {'success': False, 'error': 'Session already active'}

            if not acquiring:
                return {'success': False, 'error': 'Acquisition must be running to start session'}

            # Reset configured variables
            if self.session.config.reset_variables:
                for var_id in self.session.config.reset_variables:
                    if var_id in self.variables:
                        var = self.variables[var_id]
                        var.value = 0.0
                        var.last_reset = datetime.now().isoformat()
                        var._last_source_value = None
                        if var.variable_type == 'timer':
                            var.timer_running = False
                            var.timer_start_time = None

            # Reset all variables with reset_mode='test_session'
            for var in self.variables.values():
                if var.reset_mode == 'test_session':
                    var.value = 0.0
                    var.last_reset = datetime.now().isoformat()
                    var._last_source_value = None

            # Start all timers
            now_ts = datetime.now().timestamp()
            for var in self.variables.values():
                if var.variable_type == 'timer' and var.reset_mode == 'test_session':
                    var.timer_running = True
                    var.timer_start_time = now_ts

            self._save_variables()

        # Callbacks (outside lock to avoid deadlock)
        try:
            # Enable scheduler
            if self.session.config.enable_scheduler and self.scheduler_enable:
                self.scheduler_enable(True)

            # Start recording
            if self.session.config.start_recording and self.recording_start:
                self.recording_start()

            # Run startup sequence
            if self.session.config.run_sequence_id and self.run_sequence:
                self.run_sequence(self.session.config.run_sequence_id)

            # Custom callback
            if self.on_session_start:
                self.on_session_start()
        except Exception as e:
            logger.error(f"Error in session start callbacks: {e}")

        # Mark session active
        with self.lock:
            self.session.active = True
            self.session.started_at = datetime.now().isoformat()
            self.session.started_by = started_by

        logger.info(f"Test session started by {started_by}")
        return {'success': True, 'started_at': self.session.started_at}

    def stop_session(self) -> Dict[str, Any]:
        """Stop the current test session"""
        with self.lock:
            if not self.session.active:
                return {'success': False, 'error': 'No active session'}

            # Stop all timers
            for var in self.variables.values():
                if var.variable_type == 'timer' and var.timer_running:
                    if var.timer_start_time:
                        var.value = datetime.now().timestamp() - var.timer_start_time
                    var.timer_running = False
                    var.timer_start_time = None

            self._save_variables()

            started_at = self.session.started_at

        # Callbacks (outside lock)
        try:
            # Stop any running sequences
            if self.stop_sequence:
                self.stop_sequence()

            # Run stop sequence if configured
            if self.session.config.stop_sequence_id and self.run_sequence:
                self.run_sequence(self.session.config.stop_sequence_id)

            # Stop recording
            if self.session.config.start_recording and self.recording_stop:
                self.recording_stop()

            # Disable scheduler
            if self.session.config.enable_scheduler and self.scheduler_enable:
                self.scheduler_enable(False)

            # Custom callback
            if self.on_session_stop:
                self.on_session_stop()
        except Exception as e:
            logger.error(f"Error in session stop callbacks: {e}")

        # Mark session inactive
        with self.lock:
            self.session.active = False
            stopped_at = datetime.now().isoformat()
            self.session.started_at = None
            self.session.started_by = None

        logger.info("Test session stopped")
        return {
            'success': True,
            'stopped_at': stopped_at,
            'session_started_at': started_at,
        }

    def get_session_status(self) -> Dict[str, Any]:
        """Get current session status"""
        with self.lock:
            status = self.session.to_dict()
            if self.session.active and self.session.started_at:
                try:
                    started = datetime.fromisoformat(self.session.started_at)
                    elapsed = (datetime.now() - started).total_seconds()
                    status['elapsed_seconds'] = elapsed
                    # Format as HH:MM:SS
                    hours, remainder = divmod(int(elapsed), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    status['elapsed_formatted'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except:
                    pass
            return status

    # =========================================================================
    # DATA EXPORT
    # =========================================================================

    def get_values_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get all variable values as a dictionary for MQTT publishing"""
        with self.lock:
            result = {}
            for var in self.variables.values():
                result[var.id] = {
                    'name': var.name,
                    'display_name': var.display_name,
                    'value': var.value,
                    'units': var.units,
                    'variable_type': var.variable_type,
                    'last_reset': var.last_reset,
                    'last_update': var._last_update,
                }
                if var.variable_type == 'timer':
                    result[var.id]['timer_running'] = var.timer_running
                    # Format timer as HH:MM:SS
                    total_seconds = int(var.value)
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    result[var.id]['formatted'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            return result

    def get_config_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get all variable configurations for MQTT publishing"""
        with self.lock:
            return {var.id: var.to_dict() for var in self.variables.values()}
