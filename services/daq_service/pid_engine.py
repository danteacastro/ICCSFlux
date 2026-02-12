"""
PID Control Engine for NISystem

Provides deterministic PID control loops that run synchronously with the DAQ scan loop.
Supports multiple concurrent loops with auto/manual modes, anti-windup, and cascade control.

Integration:
    Called from DAQService._scan_loop() after channel values are read, before outputs are written.
    This ensures consistent timing at the configured scan rate (10-100 Hz).

MQTT Topics:
    {base}/pid/loops              - List all configured loops
    {base}/pid/loop/{id}/config   - Get/set loop configuration
    {base}/pid/loop/{id}/setpoint - Set setpoint value
    {base}/pid/loop/{id}/mode     - Set mode (auto/manual)
    {base}/pid/loop/{id}/output   - Set manual output value
    {base}/pid/loop/{id}/status   - Published loop status (PV, SP, CV, error, terms)

Copyright (c) 2026 NISystem
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PIDMode(str, Enum):
    """PID loop operating mode"""
    AUTO = "auto"           # Automatic control - PID calculates output
    MANUAL = "manual"       # Manual control - operator sets output directly
    CASCADE = "cascade"     # Cascade - setpoint comes from another channel


class AntiWindupMethod(str, Enum):
    """Anti-windup strategy for integral term"""
    NONE = "none"                    # No anti-windup (not recommended)
    CLAMPING = "clamping"            # Clamp integral when output saturates
    BACK_CALCULATION = "back_calculation"  # Back-calculate integral term


class DerivativeMode(str, Enum):
    """Derivative calculation mode"""
    ON_ERROR = "on_error"     # Derivative of error (classic, but causes kick on SP change)
    ON_PV = "on_pv"           # Derivative of PV only (no derivative kick)


@dataclass
class PIDLoop:
    """
    Configuration and state for a single PID control loop.

    Industrial PID implementation with:
    - Bumpless transfer between auto/manual modes
    - Anti-windup protection
    - Derivative on PV option to avoid derivative kick
    - Cascade mode for advanced control strategies
    - Output rate limiting
    """
    # Identification
    id: str
    name: str
    description: str = ""
    enabled: bool = True

    # Process Variable (input)
    pv_channel: str = ""              # Channel name for process variable
    pv_engineering_units: str = ""    # Units for display (e.g., "degC", "PSI")

    # Control Variable (output)
    cv_channel: Optional[str] = None  # Channel name for control output (optional)
    cv_engineering_units: str = "%"   # Units for display

    # Setpoint Configuration
    setpoint: float = 0.0             # Current setpoint value
    setpoint_source: str = "manual"   # "manual", "channel", or loop ID for cascade
    setpoint_channel: Optional[str] = None  # Channel for remote setpoint
    setpoint_min: float = 0.0         # Minimum allowed setpoint
    setpoint_max: float = 100.0       # Maximum allowed setpoint

    # PID Tuning Parameters
    kp: float = 1.0                   # Proportional gain
    ki: float = 0.1                   # Integral gain (1/sec)
    kd: float = 0.0                   # Derivative gain (sec)

    # Output Configuration
    output_min: float = 0.0           # Minimum output value
    output_max: float = 100.0         # Maximum output value
    output_rate_limit: float = 0.0    # Max output change per second (0 = unlimited)

    # Control Direction
    reverse_action: bool = False      # True for reverse acting (cooling)

    # Advanced Settings
    derivative_mode: DerivativeMode = DerivativeMode.ON_PV
    anti_windup: AntiWindupMethod = AntiWindupMethod.CLAMPING
    deadband: float = 0.0             # Error deadband (no action if |error| < deadband)

    # Operating Mode
    mode: PIDMode = PIDMode.AUTO
    manual_output: float = 0.0        # Output value in manual mode
    bumpless_transfer: bool = True    # Enable bumpless auto/manual transitions

    # Runtime State (not persisted to config)
    output: float = 0.0               # Current output value
    error: float = 0.0                # Current error (SP - PV)
    p_term: float = 0.0               # Proportional term
    i_term: float = 0.0               # Integral term (accumulated)
    d_term: float = 0.0               # Derivative term
    last_pv: Optional[float] = None   # Previous PV for derivative calculation
    last_error: Optional[float] = None  # Previous error
    last_output: float = 0.0          # Previous output for rate limiting
    last_update_time: float = 0.0     # Timestamp of last update

    def to_config_dict(self) -> Dict[str, Any]:
        """Convert to configuration dict (excludes runtime state)"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'enabled': self.enabled,
            'pv_channel': self.pv_channel,
            'pv_engineering_units': self.pv_engineering_units,
            'cv_channel': self.cv_channel,
            'cv_engineering_units': self.cv_engineering_units,
            'setpoint': self.setpoint,
            'setpoint_source': self.setpoint_source,
            'setpoint_channel': self.setpoint_channel,
            'setpoint_min': self.setpoint_min,
            'setpoint_max': self.setpoint_max,
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'output_min': self.output_min,
            'output_max': self.output_max,
            'output_rate_limit': self.output_rate_limit,
            'reverse_action': self.reverse_action,
            'derivative_mode': self.derivative_mode.value,
            'anti_windup': self.anti_windup.value,
            'deadband': self.deadband,
            'mode': self.mode.value,
            'manual_output': self.manual_output,
            'bumpless_transfer': self.bumpless_transfer,
        }

    def to_status_dict(self) -> Dict[str, Any]:
        """Convert to status dict for MQTT publishing"""
        return {
            'id': self.id,
            'name': self.name,
            'enabled': self.enabled,
            'mode': self.mode.value,
            'pv': self.last_pv if self.last_pv is not None else 0.0,
            'pv_channel': self.pv_channel,
            'setpoint': self.setpoint,
            'output': self.output,
            'cv_channel': self.cv_channel,
            'error': self.error,
            'p_term': round(self.p_term, 4),
            'i_term': round(self.i_term, 4),
            'd_term': round(self.d_term, 4),
            'output_saturated': self.output <= self.output_min or self.output >= self.output_max,
            'timestamp': datetime.now().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PIDLoop':
        """Create PIDLoop from configuration dict"""
        # Handle enum conversions
        if 'derivative_mode' in data and isinstance(data['derivative_mode'], str):
            data['derivative_mode'] = DerivativeMode(data['derivative_mode'])
        if 'anti_windup' in data and isinstance(data['anti_windup'], str):
            data['anti_windup'] = AntiWindupMethod(data['anti_windup'])
        if 'mode' in data and isinstance(data['mode'], str):
            data['mode'] = PIDMode(data['mode'])

        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        return cls(**filtered_data)


class PIDEngine:
    """
    PID Control Engine - manages multiple PID loops with deterministic execution.

    Designed to be called from the DAQ scan loop for consistent timing.
    All loops are processed each scan cycle.

    Features:
    - Multiple concurrent PID loops
    - Auto/manual/cascade modes
    - Anti-windup protection
    - Bumpless mode transfers
    - Rate-limited outputs
    - Thread-safe configuration updates
    """

    def __init__(self, on_set_output: Optional[Callable[[str, float], bool]] = None):
        """
        Initialize PID Engine.

        Args:
            on_set_output: Callback to write output values to hardware.
                          Signature: (channel_name, value) -> success
        """
        self.loops: Dict[str, PIDLoop] = {}
        self._lock = threading.RLock()
        self._on_set_output = on_set_output
        self._status_callback: Optional[Callable[[str, Dict], None]] = None
        self._initialized = False

        logger.info("PID Engine initialized")

    def set_status_callback(self, callback: Callable[[str, Dict], None]):
        """Set callback for publishing loop status via MQTT"""
        self._status_callback = callback

    def set_output_callback(self, callback: Callable[[str, float], bool]):
        """Set callback for writing output values"""
        self._on_set_output = callback

    # =========================================================================
    # Loop Management
    # =========================================================================

    def _validate_loop_config(self, loop: PIDLoop) -> Optional[str]:
        """Validate PID loop configuration. Returns error message or None if valid."""
        if loop.output_min >= loop.output_max:
            return f"output_min ({loop.output_min}) must be less than output_max ({loop.output_max})"
        if loop.setpoint_min >= loop.setpoint_max:
            return f"setpoint_min ({loop.setpoint_min}) must be less than setpoint_max ({loop.setpoint_max})"
        if loop.kp < 0 or loop.ki < 0 or loop.kd < 0:
            return f"PID gains must be non-negative (kp={loop.kp}, ki={loop.ki}, kd={loop.kd})"
        if loop.output_rate_limit < 0:
            return f"output_rate_limit must be non-negative ({loop.output_rate_limit})"
        if loop.deadband < 0:
            return f"deadband must be non-negative ({loop.deadband})"
        return None

    def add_loop(self, loop: PIDLoop) -> bool:
        """Add a new PID loop"""
        with self._lock:
            if loop.id in self.loops:
                logger.warning(f"PID loop '{loop.id}' already exists")
                return False

            error = self._validate_loop_config(loop)
            if error:
                logger.error(f"PID loop '{loop.id}' invalid config: {error}")
                return False

            self.loops[loop.id] = loop
            logger.info(f"Added PID loop: {loop.id} ({loop.name})")
            return True

    def update_loop(self, loop_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing PID loop configuration"""
        with self._lock:
            if loop_id not in self.loops:
                logger.warning(f"PID loop '{loop_id}' not found")
                return False

            loop = self.loops[loop_id]

            # Track mode change for bumpless transfer
            old_mode = loop.mode

            # Apply updates
            for key, value in updates.items():
                if hasattr(loop, key):
                    # Handle enum conversions
                    if key == 'mode' and isinstance(value, str):
                        value = PIDMode(value)
                    elif key == 'derivative_mode' and isinstance(value, str):
                        value = DerivativeMode(value)
                    elif key == 'anti_windup' and isinstance(value, str):
                        value = AntiWindupMethod(value)

                    setattr(loop, key, value)

            # Handle bumpless transfer on mode change
            if loop.bumpless_transfer and old_mode != loop.mode:
                self._handle_mode_change(loop, old_mode, loop.mode)

            logger.info(f"Updated PID loop: {loop_id}")
            return True

    def remove_loop(self, loop_id: str) -> bool:
        """Remove a PID loop"""
        with self._lock:
            if loop_id not in self.loops:
                return False

            del self.loops[loop_id]
            logger.info(f"Removed PID loop: {loop_id}")
            return True

    def get_loop(self, loop_id: str) -> Optional[PIDLoop]:
        """Get a PID loop by ID"""
        with self._lock:
            return self.loops.get(loop_id)

    def get_all_loops(self) -> List[PIDLoop]:
        """Get all PID loops"""
        with self._lock:
            return list(self.loops.values())

    def clear_loops(self):
        """Remove all PID loops"""
        with self._lock:
            self.loops.clear()
            logger.info("Cleared all PID loops")

    # =========================================================================
    # Setpoint Control
    # =========================================================================

    def set_setpoint(self, loop_id: str, setpoint: float) -> bool:
        """Set the setpoint for a loop"""
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False

            # Clamp to limits
            setpoint = max(loop.setpoint_min, min(loop.setpoint_max, setpoint))
            loop.setpoint = setpoint
            loop.setpoint_source = "manual"

            logger.debug(f"PID {loop_id}: setpoint = {setpoint}")
            return True

    def set_mode(self, loop_id: str, mode: str) -> bool:
        """Set the operating mode for a loop"""
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False

            old_mode = loop.mode
            new_mode = PIDMode(mode)

            if old_mode == new_mode:
                return True

            if loop.bumpless_transfer:
                self._handle_mode_change(loop, old_mode, new_mode)

            loop.mode = new_mode
            logger.info(f"PID {loop_id}: mode changed {old_mode.value} -> {new_mode.value}")
            return True

    def set_manual_output(self, loop_id: str, output: float) -> bool:
        """Set the manual output value for a loop"""
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False

            # Clamp to limits
            output = max(loop.output_min, min(loop.output_max, output))
            loop.manual_output = output

            # If in manual mode, apply immediately
            if loop.mode == PIDMode.MANUAL:
                loop.output = output

            logger.debug(f"PID {loop_id}: manual_output = {output}")
            return True

    def set_tuning(self, loop_id: str, kp: float, ki: float, kd: float) -> bool:
        """Set PID tuning parameters"""
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False

            loop.kp = kp
            loop.ki = ki
            loop.kd = kd

            logger.info(f"PID {loop_id}: tuning Kp={kp}, Ki={ki}, Kd={kd}")
            return True

    # =========================================================================
    # PID Calculation
    # =========================================================================

    def process_scan(self, channel_values: Dict[str, float], dt: float) -> Dict[str, float]:
        """
        Process all PID loops for one scan cycle.

        Called from DAQ scan loop with precise timing.

        Args:
            channel_values: Current channel values {channel_name: value}
            dt: Time delta since last scan (seconds)

        Returns:
            Dict of {cv_channel: output_value} for loops with cv_channel configured
        """
        outputs = {}

        with self._lock:
            for loop in self.loops.values():
                if not loop.enabled:
                    continue

                # Get process variable
                pv = channel_values.get(loop.pv_channel)
                if pv is None:
                    continue

                # Get setpoint (may come from another channel in cascade mode)
                sp = self._get_setpoint(loop, channel_values)

                # Calculate PID output
                output = self._compute_pid(loop, pv, sp, dt)

                # Store output for channels with cv_channel configured
                if loop.cv_channel:
                    outputs[loop.cv_channel] = output

                    # Write to hardware if callback is set
                    if self._on_set_output:
                        self._on_set_output(loop.cv_channel, output)

                # Publish status
                if self._status_callback:
                    self._status_callback(loop.id, loop.to_status_dict())

        return outputs

    def _get_setpoint(self, loop: PIDLoop, channel_values: Dict[str, float]) -> float:
        """Get the setpoint value based on setpoint source"""
        if loop.setpoint_source == "manual":
            return loop.setpoint
        elif loop.setpoint_source == "channel" and loop.setpoint_channel:
            sp = channel_values.get(loop.setpoint_channel, loop.setpoint)
            return max(loop.setpoint_min, min(loop.setpoint_max, sp))
        elif loop.setpoint_source in self.loops:
            # Cascade mode - use output of another loop as setpoint
            master_loop = self.loops[loop.setpoint_source]
            output = master_loop.output
            # Guard against NaN propagation from master loop
            if output is None or (isinstance(output, float) and (output != output)):
                logger.warning(f"PID cascade: master loop '{loop.setpoint_source}' output is NaN, using manual setpoint")
                return loop.setpoint
            return output
        else:
            return loop.setpoint

    def _compute_pid(self, loop: PIDLoop, pv: float, sp: float, dt: float) -> float:
        """
        Compute PID output using velocity algorithm with anti-windup.

        Implements ISA standard PID with:
        - Proportional on error
        - Integral with anti-windup
        - Derivative on PV or error (configurable)
        - Output rate limiting
        - Bumpless manual/auto transfer
        """
        # Manual mode - use manual output directly
        if loop.mode == PIDMode.MANUAL:
            loop.output = loop.manual_output
            loop.last_pv = pv
            loop.last_error = sp - pv
            return loop.output

        # Calculate error
        error = sp - pv

        # Reverse action (for cooling loops)
        if loop.reverse_action:
            error = -error

        # Apply deadband
        if abs(error) < loop.deadband:
            error = 0.0

        loop.error = error

        # Initialize on first run
        if loop.last_pv is None:
            loop.last_pv = pv
            loop.last_error = error
            loop.last_output = loop.output
            loop.i_term = loop.output  # Initialize integral to current output

        # Proportional term
        loop.p_term = loop.kp * error

        # Integral term with anti-windup
        if loop.ki > 0 and dt > 0:
            integral_contribution = loop.ki * error * dt

            # Anti-windup: don't accumulate if output is saturated
            if loop.anti_windup == AntiWindupMethod.CLAMPING:
                # Only accumulate if not saturated, or if accumulation would reduce saturation
                output_saturated_high = loop.output >= loop.output_max and integral_contribution > 0
                output_saturated_low = loop.output <= loop.output_min and integral_contribution < 0

                if not (output_saturated_high or output_saturated_low):
                    loop.i_term += integral_contribution
            elif loop.anti_windup == AntiWindupMethod.BACK_CALCULATION:
                # Back-calculation: adjust integral based on saturation
                loop.i_term += integral_contribution
                # This is handled in output clamping below
            else:
                loop.i_term += integral_contribution

        # Derivative term (clamp dt to avoid spike from near-zero timer resolution)
        if loop.kd > 0 and dt > 0:
            safe_dt = max(dt, 1e-3)  # Minimum 1ms to prevent derivative amplification
            if loop.derivative_mode == DerivativeMode.ON_PV:
                # Derivative on PV (avoids derivative kick on setpoint change)
                d_input = -(pv - loop.last_pv) / safe_dt
            else:
                # Derivative on error
                d_input = (error - loop.last_error) / safe_dt

            loop.d_term = loop.kd * d_input
        else:
            loop.d_term = 0.0

        # Calculate total output
        output = loop.p_term + loop.i_term + loop.d_term

        # Rate limiting
        if loop.output_rate_limit > 0 and dt > 0:
            max_change = loop.output_rate_limit * dt
            output_change = output - loop.last_output
            if abs(output_change) > max_change:
                output = loop.last_output + max_change * (1 if output_change > 0 else -1)

        # Clamp output to limits
        output = max(loop.output_min, min(loop.output_max, output))

        # Back-calculation anti-windup: adjust integral if output was clamped
        if loop.anti_windup == AntiWindupMethod.BACK_CALCULATION:
            clamped_output = output
            unclamped_output = loop.p_term + loop.i_term + loop.d_term
            if clamped_output != unclamped_output:
                # Adjust integral term to match clamped output
                loop.i_term = clamped_output - loop.p_term - loop.d_term

        # Store state for next iteration
        loop.output = output
        loop.last_pv = pv
        loop.last_error = error
        loop.last_output = output
        loop.last_update_time = time.time()

        return output

    def _handle_mode_change(self, loop: PIDLoop, old_mode: PIDMode, new_mode: PIDMode):
        """Handle bumpless transfer between modes"""
        if new_mode == PIDMode.AUTO and old_mode == PIDMode.MANUAL:
            # Switching from manual to auto: set integral term to achieve current output
            # This prevents output jump when switching to auto
            loop.i_term = loop.output - loop.p_term - loop.d_term
            logger.debug(f"PID {loop.id}: bumpless transfer M->A, i_term = {loop.i_term}")

        elif new_mode == PIDMode.MANUAL and old_mode == PIDMode.AUTO:
            # Switching from auto to manual: set manual output to current output
            loop.manual_output = loop.output
            logger.debug(f"PID {loop.id}: bumpless transfer A->M, manual_output = {loop.manual_output}")

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_config_dict(self) -> Dict[str, Any]:
        """Export all loops as configuration dict"""
        with self._lock:
            return {
                'loops': [loop.to_config_dict() for loop in self.loops.values()]
            }

    def load_config(self, config: Dict[str, Any]):
        """Load loops from configuration dict"""
        with self._lock:
            self.loops.clear()

            for loop_data in config.get('loops', []):
                try:
                    loop = PIDLoop.from_dict(loop_data)
                    self.loops[loop.id] = loop
                    logger.info(f"Loaded PID loop: {loop.id}")
                except Exception as e:
                    logger.error(f"Failed to load PID loop: {e}")

            logger.info(f"Loaded {len(self.loops)} PID loops from config")

    def to_json(self) -> str:
        """Export configuration as JSON string"""
        return json.dumps(self.to_config_dict(), indent=2)

    def load_json(self, json_str: str):
        """Load configuration from JSON string"""
        config = json.loads(json_str)
        self.load_config(config)
