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
    edge_type: str = 'increment'  # 'increment', 'rising', 'falling', 'rate'
    scale_factor: float = 1.0  # Multiply by this
    source_rate_unit: str = 'per_second'  # For rate integration: 'per_second', 'per_minute', 'per_hour', 'per_day'

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
    _rate_samples: List[tuple] = field(default_factory=list, repr=False)  # For rate integration: [(timestamp, value), ...]
    _last_rate_calc: Optional[float] = field(default=None, repr=False)  # Last time we calculated rate total

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
            'source_rate_unit': self.source_rate_unit,
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
            source_rate_unit=data.get('source_rate_unit', 'per_second'),
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
class FormulaBlock:
    """
    A formula block defines multiple output variables from a single code block.

    Scientists write Python-like expressions with assignments:

        # Pressure differential check
        A_BAD_VALUE = PT102 - 70 if PT101 > PT102 + 3 else None

        # Temperature deviation
        TEMP_DRIFT = abs(TC101 - TC102) if abs(TC101 - TC102) > 5 else None

        # Combined alarm condition
        SYSTEM_FAULT = 1 if (A_BAD_VALUE is not None or TEMP_DRIFT is not None) else 0

    Each assignment creates a variable. None values → NaN (stale).
    Variables can reference channels, other user variables, and earlier assignments.
    """
    id: str
    name: str
    description: str = ""
    code: str = ""  # Multi-line Python-like code
    enabled: bool = True

    # Output variable definitions extracted from code
    # Maps variable_name -> {units, description}
    outputs: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Last validation result
    last_error: Optional[str] = None
    last_validated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'code': self.code,
            'enabled': self.enabled,
            'outputs': self.outputs,
            'last_error': self.last_error,
            'last_validated': self.last_validated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FormulaBlock':
        return cls(
            id=data['id'],
            name=data.get('name', data['id']),
            description=data.get('description', ''),
            code=data.get('code', ''),
            enabled=data.get('enabled', True),
            outputs=data.get('outputs', {}),
            last_error=data.get('last_error'),
            last_validated=data.get('last_validated'),
        )


@dataclass
class TestSessionConfig:
    """Configuration for test session behavior"""
    enable_scheduler: bool = True
    start_recording: bool = False  # Don't auto-start recording with session by default
    enable_triggers: bool = True
    reset_variables: List[str] = field(default_factory=list)  # Variable IDs to reset on start
    run_sequence_id: Optional[str] = None  # Optional sequence to run at start
    stop_sequence_id: Optional[str] = None  # Optional sequence to run at stop
    # Safety interlock requirements
    require_latch_armed: bool = False  # If True, all latched alarms must be cleared to start
    require_no_active_alarms: bool = False  # If True, no active alarms allowed to start

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestSessionConfig':
        return cls(
            enable_scheduler=data.get('enable_scheduler', True),
            start_recording=data.get('start_recording', False),  # Default to False
            enable_triggers=data.get('enable_triggers', True),
            reset_variables=data.get('reset_variables', []),
            run_sequence_id=data.get('run_sequence_id'),
            stop_sequence_id=data.get('stop_sequence_id'),
            require_latch_armed=data.get('require_latch_armed', False),
            require_no_active_alarms=data.get('require_no_active_alarms', False),
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
        self.formula_blocks_file = self.data_dir / "formula_blocks.json"
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
        self.formula_blocks: Dict[str, FormulaBlock] = {}
        self.session = TestSession()
        self.lock = threading.Lock()

        # Formula block computed values (updated each scan)
        # Maps block_id -> {output_name: value or NaN}
        self._formula_values: Dict[str, Dict[str, float]] = {}

        # Track last reset check time for time-of-day resets
        self._last_reset_check_date: Optional[str] = None

        # Load persisted state
        self._load_state()

        logger.info(f"UserVariableManager initialized with {len(self.variables)} variables")

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _load_state(self):
        """Load variables, formula blocks, and session from disk"""
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

        # Load formula blocks
        if self.formula_blocks_file.exists():
            try:
                with open(self.formula_blocks_file, 'r') as f:
                    data = json.load(f)
                for block_data in data.get('blocks', []):
                    block = FormulaBlock.from_dict(block_data)
                    self.formula_blocks[block.id] = block
                logger.info(f"Loaded {len(self.formula_blocks)} formula blocks from disk")
            except Exception as e:
                logger.error(f"Failed to load formula blocks: {e}")

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

    def _save_formula_blocks(self):
        """Save formula blocks to disk"""
        try:
            data = {
                'blocks': [b.to_dict() for b in self.formula_blocks.values()]
            }
            with open(self.formula_blocks_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save formula blocks: {e}")

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

    # Rate unit conversion factors (to seconds)
    RATE_UNIT_DIVISORS = {
        'per_second': 1.0,
        'per_minute': 60.0,
        'per_hour': 3600.0,
        'per_day': 86400.0,
    }

    def _check_accumulator_edge(self, var: UserVariable, current_value: float) -> float:
        """
        Check for edge/increment on source channel (for counter-type signals).
        Returns the increment to add (0 if no edge detected).

        For rate-based signals (4-20mA, etc.), use _integrate_rate() instead.
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

    def _integrate_rate(self, var: UserVariable, current_value: float, now_ts: float) -> float:
        """
        Integrate a rate signal over time using rolling average (for 4-20mA, voltage, etc.).

        Uses a 1-second rolling window of samples to calculate average rate,
        then integrates once per second. This approach is robust against
        scan rate variations and timing jitter.

        For a signal like GPM (gallons per minute):
          - Collect samples over 1 second window
          - Calculate average: e.g., 9.0 GPM
          - Every second, add: avg_rate * 1.0 / 60 = 0.15 gallons

        Returns the increment to add to the accumulator.
        """
        SAMPLE_WINDOW_S = 1.0  # Rolling window for averaging samples
        CALC_INTERVAL_S = 1.0  # How often to calculate and add to total

        # Add current sample to buffer
        var._rate_samples.append((now_ts, current_value))

        # Prune samples older than the window
        cutoff = now_ts - SAMPLE_WINDOW_S
        var._rate_samples = [(t, v) for t, v in var._rate_samples if t > cutoff]

        # Initialize last calculation time if needed
        if var._last_rate_calc is None:
            var._last_rate_calc = now_ts
            return 0.0

        # Calculate time since last integration
        time_since_calc = now_ts - var._last_rate_calc

        # Only calculate every CALC_INTERVAL_S (approximately)
        if time_since_calc < CALC_INTERVAL_S:
            return 0.0

        # Calculate average rate from samples in window
        if len(var._rate_samples) == 0:
            var._last_rate_calc = now_ts
            return 0.0

        avg_rate = sum(v for _, v in var._rate_samples) / len(var._rate_samples)

        # Get the divisor for the rate unit
        divisor = self.RATE_UNIT_DIVISORS.get(var.source_rate_unit, 60.0)

        # Integrate: avg_rate * time_since_calc / rate_period * scale_factor
        # Example: 9 GPM * 1.0s / 60s * 1.0 = 0.15 gallons per second
        increment = avg_rate * (time_since_calc / divisor) * var.scale_factor

        # Update last calculation time
        var._last_rate_calc = now_ts

        return increment

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

        Supports both counter-based (edge detection) and rate-based (time integration)
        signals. Maintains a timestamped ring buffer of increments. The value is the
        sum of all samples within the rolling window.

        This is useful for "last 24 hours" totals that continuously update,
        unlike time_of_day reset which only resets at a specific time.
        """
        # Use rate integration for 4-20mA/analog rate signals, edge detection for counters
        if var.edge_type == 'rate':
            increment = self._integrate_rate(var, current_value, now_ts)
        else:
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
                        # Use rate integration for 4-20mA/analog rate signals
                        if var.edge_type == 'rate':
                            increment = self._integrate_rate(var, source_value, now_ts)
                        else:
                            # Use edge detection for counter/pulse signals
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

    def start_session(self, acquiring: bool, started_by: str = "user",
                       latched_alarm_count: int = 0, active_alarm_count: int = 0,
                       require_no_latched: bool = False, require_no_active: bool = False) -> Dict[str, Any]:
        """
        Start a test session with state validation.

        Args:
            acquiring: Whether DAQ is currently acquiring data
            started_by: User/operator identifier
            latched_alarm_count: Number of latched alarms requiring reset
            active_alarm_count: Number of active (unacknowledged) alarms
            require_no_latched: If True, reject start if any latched alarms exist
                               (set True only when a safety latch widget is configured)
            require_no_active: If True, reject start if any active alarms exist

        Returns status dict with success/error info.
        """
        with self.lock:
            # STATE VALIDATION
            logger.info(f"[STATE MACHINE] Session start requested (active={self.session.active}, acquiring={acquiring}, latched={latched_alarm_count}, active_alarms={active_alarm_count})")

            if self.session.active:
                logger.warning("[STATE MACHINE] Session start rejected - already active")
                return {'success': False, 'error': 'Session already active'}

            if not acquiring:
                logger.error("[STATE MACHINE] Session start rejected - acquisition not running (PREREQUISITE FAILED)")
                return {'success': False, 'error': 'Acquisition must be running to start session'}

            # Check for latched alarms - these must be cleared before session start
            if require_no_latched and latched_alarm_count > 0:
                logger.error(f"[STATE MACHINE] Session start rejected - {latched_alarm_count} latched alarm(s) require reset")
                return {'success': False, 'error': f'{latched_alarm_count} latched alarm(s) must be reset before starting session'}

            # Optionally check for active alarms
            if require_no_active and active_alarm_count > 0:
                logger.error(f"[STATE MACHINE] Session start rejected - {active_alarm_count} active alarm(s)")
                return {'success': False, 'error': f'{active_alarm_count} active alarm(s) must be acknowledged before starting session'}

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

        logger.info(f"[STATE MACHINE] Session started successfully by {started_by} at {self.session.started_at}")
        return {'success': True, 'started_at': self.session.started_at}

    def stop_session(self) -> Dict[str, Any]:
        """Stop the current test session with state validation"""
        with self.lock:
            # STATE VALIDATION
            logger.info(f"[STATE MACHINE] Session stop requested (active={self.session.active})")

            if not self.session.active:
                logger.warning("[STATE MACHINE] Session stop rejected - not active")
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

        # Callbacks (outside lock) - wrap each individually so one failure doesn't prevent others
        # Stop any running sequences
        try:
            if self.stop_sequence:
                self.stop_sequence()
        except Exception as e:
            logger.error(f"Error stopping sequence: {e}")

        # Run stop sequence if configured
        try:
            if self.session.config.stop_sequence_id and self.run_sequence:
                self.run_sequence(self.session.config.stop_sequence_id)
        except Exception as e:
            logger.error(f"Error running stop sequence: {e}")

        # Stop recording if session started it
        try:
            if self.session.config.start_recording and self.recording_stop:
                self.recording_stop()
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")

        # Disable scheduler
        try:
            if self.session.config.enable_scheduler and self.scheduler_enable:
                self.scheduler_enable(False)
                logger.info("Scheduler disabled by session stop")
        except Exception as e:
            logger.error(f"Error disabling scheduler: {e}")

        # Custom callback
        try:
            if self.on_session_stop:
                self.on_session_stop()
        except Exception as e:
            logger.error(f"Error in on_session_stop callback: {e}")

        # Mark session inactive
        with self.lock:
            self.session.active = False
            stopped_at = datetime.now().isoformat()
            self.session.started_at = None
            self.session.started_by = None

        logger.info(f"[STATE MACHINE] Session stopped successfully at {stopped_at}")
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

    # =========================================================================
    # FORMULA BLOCK MANAGEMENT
    # =========================================================================

    def validate_formula_code(self, code: str, channel_names: List[str] = None) -> Dict[str, Any]:
        """
        Validate formula block code syntax and extract output variable names.

        Returns:
            {
                'valid': bool,
                'outputs': ['VAR1', 'VAR2', ...],  # Variable names that will be created
                'error': str or None,
                'error_line': int or None,
            }
        """
        import ast
        import math

        if not code.strip():
            return {'valid': False, 'outputs': [], 'error': 'Code is empty', 'error_line': None}

        outputs = []
        errors = []

        # Parse line by line for assignments
        lines = code.split('\n')
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith('#'):
                continue

            # Check for assignment pattern
            if '=' not in stripped or stripped.startswith('==') or '==' in stripped.split('=')[0]:
                # Could be a pure expression or comparison - skip for now
                # We only care about assignments
                continue

            # Find the first '=' that's not part of ==, !=, <=, >=
            try:
                # Use ast to parse and validate
                tree = ast.parse(stripped, mode='exec')

                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                var_name = target.id
                                # Valid variable name check
                                if var_name.isidentifier() and not var_name.startswith('_'):
                                    if var_name not in outputs:
                                        outputs.append(var_name)
                    elif isinstance(node, ast.AugAssign):
                        # +=, -=, etc.
                        if isinstance(node.target, ast.Name):
                            var_name = node.target.id
                            if var_name.isidentifier() and not var_name.startswith('_'):
                                if var_name not in outputs:
                                    outputs.append(var_name)

            except SyntaxError as e:
                errors.append({
                    'line': line_num,
                    'message': str(e.msg) if hasattr(e, 'msg') else str(e),
                })

        if errors:
            first_error = errors[0]
            return {
                'valid': False,
                'outputs': outputs,
                'error': f"Line {first_error['line']}: {first_error['message']}",
                'error_line': first_error['line'],
            }

        if not outputs:
            return {
                'valid': False,
                'outputs': [],
                'error': 'No output variables defined. Use VAR_NAME = expression syntax.',
                'error_line': None,
            }

        return {'valid': True, 'outputs': outputs, 'error': None, 'error_line': None}

    def create_formula_block(self, block_data: Dict[str, Any], channel_names: List[str] = None) -> Dict[str, Any]:
        """
        Create a new formula block.

        Args:
            block_data: {id, name, description, code, outputs: {name: {units, description}}}
            channel_names: List of available channel names for validation

        Returns:
            {success: bool, block: FormulaBlock or None, error: str or None}
        """
        with self.lock:
            code = block_data.get('code', '')

            # Validate code
            validation = self.validate_formula_code(code, channel_names)
            if not validation['valid']:
                return {
                    'success': False,
                    'block': None,
                    'error': validation['error'],
                    'error_line': validation.get('error_line'),
                }

            block = FormulaBlock.from_dict(block_data)
            block.last_validated = datetime.now().isoformat()
            block.last_error = None

            # Ensure outputs dict has entries for all detected outputs
            for out_name in validation['outputs']:
                if out_name not in block.outputs:
                    block.outputs[out_name] = {'units': '', 'description': ''}

            self.formula_blocks[block.id] = block
            self._save_formula_blocks()

            logger.info(f"Created formula block: {block.name} with outputs: {validation['outputs']}")
            return {'success': True, 'block': block, 'outputs': validation['outputs']}

    def update_formula_block(self, block_id: str, updates: Dict[str, Any], channel_names: List[str] = None) -> Dict[str, Any]:
        """Update an existing formula block"""
        with self.lock:
            if block_id not in self.formula_blocks:
                return {'success': False, 'error': f'Formula block not found: {block_id}'}

            block = self.formula_blocks[block_id]

            # If code is being updated, validate it
            if 'code' in updates:
                validation = self.validate_formula_code(updates['code'], channel_names)
                if not validation['valid']:
                    return {
                        'success': False,
                        'error': validation['error'],
                        'error_line': validation.get('error_line'),
                    }

                block.code = updates['code']
                block.last_validated = datetime.now().isoformat()
                block.last_error = None

                # Update outputs
                for out_name in validation['outputs']:
                    if out_name not in block.outputs:
                        block.outputs[out_name] = {'units': '', 'description': ''}
                # Remove outputs no longer in code
                block.outputs = {k: v for k, v in block.outputs.items() if k in validation['outputs']}

            # Update other fields
            if 'name' in updates:
                block.name = updates['name']
            if 'description' in updates:
                block.description = updates['description']
            if 'enabled' in updates:
                block.enabled = updates['enabled']
            if 'outputs' in updates and isinstance(updates['outputs'], dict):
                # Merge output metadata (units, description)
                for out_name, metadata in updates['outputs'].items():
                    if out_name in block.outputs:
                        block.outputs[out_name].update(metadata)

            self._save_formula_blocks()
            logger.info(f"Updated formula block: {block.name}")

            return {'success': True, 'block': block}

    def delete_formula_block(self, block_id: str) -> bool:
        """Delete a formula block"""
        with self.lock:
            if block_id not in self.formula_blocks:
                return False

            block = self.formula_blocks.pop(block_id)
            # Also clean up cached values
            if block_id in self._formula_values:
                del self._formula_values[block_id]

            self._save_formula_blocks()
            logger.info(f"Deleted formula block: {block.name}")
            return True

    def get_formula_blocks_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get all formula blocks for MQTT publishing"""
        with self.lock:
            return {b.id: b.to_dict() for b in self.formula_blocks.values()}

    def load_formulas_from_project(self, project_data: Dict[str, Any], channel_names: List[str] = None) -> int:
        """
        Load formulas/calculated params from project data.

        Handles two formats:
        1. scripts.calculatedParams - Simple single-formula params from frontend
        2. scripts.formulaBlocks - Multi-line formula blocks (if present)

        Args:
            project_data: Project JSON dict
            channel_names: List of available channel names for validation

        Returns:
            Number of formulas loaded
        """
        with self.lock:
            # Clear existing formula blocks
            self.formula_blocks.clear()
            self._formula_values.clear()

            scripts_data = project_data.get('scripts', {})
            loaded_count = 0

            # Load calculatedParams (simple formulas)
            calc_params = scripts_data.get('calculatedParams', [])
            for param in calc_params:
                try:
                    # Convert CalculatedParam format to FormulaBlock
                    # CalculatedParam: id, name, displayName, formula, unit, enabled
                    param_id = param.get('id', f'cp-{loaded_count}')
                    name = param.get('name', param.get('displayName', f'Formula {loaded_count}'))
                    formula = param.get('formula', '')
                    unit = param.get('unit', '')
                    enabled = param.get('enabled', True)

                    if not formula:
                        continue

                    # Create a formula block with single output
                    # Convert simple formula to assignment: OUTPUT_NAME = formula
                    output_name = name.upper().replace(' ', '_').replace('-', '_')
                    code = f"{output_name} = {formula}"

                    block = FormulaBlock(
                        id=param_id,
                        name=name,
                        description=param.get('description', f'Calculated parameter: {name}'),
                        code=code,
                        enabled=enabled,
                        outputs={output_name: {'units': unit, 'description': ''}},
                        last_error=None,
                        last_validated=None
                    )
                    self.formula_blocks[block.id] = block
                    loaded_count += 1
                    logger.debug(f"Loaded calculated param as formula block: {name}")

                except Exception as e:
                    logger.error(f"Failed to load calculated param: {e}")

            # Also load explicit formulaBlocks if present (multi-line code blocks)
            formula_blocks = scripts_data.get('formulaBlocks', [])
            for block_data in formula_blocks:
                try:
                    block = FormulaBlock.from_dict(block_data)
                    self.formula_blocks[block.id] = block
                    loaded_count += 1
                    logger.debug(f"Loaded formula block: {block.name}")
                except Exception as e:
                    logger.error(f"Failed to load formula block: {e}")

            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} formulas from project")
                # Don't save to disk - project is the source of truth
            else:
                logger.debug("No formulas found in project")

            return loaded_count

    def clear_formulas(self):
        """Clear all formula blocks (used when loading new project)"""
        with self.lock:
            self.formula_blocks.clear()
            self._formula_values.clear()
            logger.info("Cleared all formula blocks")

    def get_formula_values_dict(self) -> Dict[str, Dict[str, Any]]:
        """Get all formula block output values for MQTT publishing"""
        with self.lock:
            return dict(self._formula_values)

    def evaluate_formula_block(self, block: FormulaBlock, channel_values: Dict[str, float]) -> Dict[str, float]:
        """
        Evaluate a formula block and return computed output values.

        Returns: {output_name: value} where value is float or NaN
        """
        import math

        if not block.enabled or not block.code.strip():
            return {}

        # Build evaluation namespace
        namespace = dict(channel_values)

        # Add user variables (so formulas can reference them)
        for var in self.variables.values():
            namespace[var.name] = var.value

        # Add previously computed formula block outputs (for inter-block dependencies)
        for block_id, block_values in self._formula_values.items():
            for out_name, out_val in block_values.items():
                if out_name not in namespace:  # Don't override channels
                    namespace[out_name] = out_val

        # Add math functions
        namespace.update({
            'abs': abs, 'min': min, 'max': max, 'sum': sum,
            'sqrt': math.sqrt, 'pow': pow,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'asin': math.asin, 'acos': math.acos, 'atan': math.atan, 'atan2': math.atan2,
            'log': math.log, 'log10': math.log10, 'log2': math.log2, 'exp': math.exp,
            'floor': math.floor, 'ceil': math.ceil, 'round': round,
            'pi': math.pi, 'e': math.e,
            'nan': float('nan'), 'inf': float('inf'),
            'isnan': math.isnan, 'isinf': math.isinf,
            'degrees': math.degrees, 'radians': math.radians,
            'hypot': math.hypot, 'fabs': math.fabs,
        })

        results = {}

        try:
            # Execute the code block
            # The exec will populate namespace with assigned variables
            exec(block.code, {"__builtins__": {'None': None, 'True': True, 'False': False}}, namespace)

            # Extract outputs (variables defined in block.outputs)
            for out_name in block.outputs.keys():
                if out_name in namespace:
                    value = namespace[out_name]
                    if value is None:
                        # None → NaN (stale indicator)
                        results[out_name] = float('nan')
                    elif isinstance(value, (int, float)):
                        results[out_name] = float(value)
                    elif isinstance(value, bool):
                        results[out_name] = 1.0 if value else 0.0
                    else:
                        # Can't convert - mark as NaN
                        results[out_name] = float('nan')
                else:
                    # Output not computed
                    results[out_name] = float('nan')

            block.last_error = None

        except Exception as e:
            # Evaluation failed - all outputs are NaN
            block.last_error = str(e)
            logger.debug(f"Formula block '{block.name}' evaluation error: {e}")
            for out_name in block.outputs.keys():
                results[out_name] = float('nan')

        return results

    def process_formula_blocks(self, channel_values: Dict[str, float]):
        """
        Process all enabled formula blocks.
        Call this from the DAQ scan loop after process_scan().
        """
        with self.lock:
            for block in self.formula_blocks.values():
                if block.enabled:
                    results = self.evaluate_formula_block(block, channel_values)
                    self._formula_values[block.id] = results
