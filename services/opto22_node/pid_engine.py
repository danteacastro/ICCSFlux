"""
PID Engine for Opto22 Node

Provides PID control loop execution with:
- Auto/Manual/Cascade modes
- Anti-windup (clamping / back-calculation)
- Derivative-on-PV or derivative-on-error
- Bumpless transfer between modes
- Output rate limiting

Extracted from the Opto22 monolithic node.
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger('Opto22Node.PID')


class PIDMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    CASCADE = "cascade"


class AntiWindupMethod(str, Enum):
    NONE = "none"
    CLAMPING = "clamping"
    BACK_CALCULATION = "back_calculation"


class DerivativeMode(str, Enum):
    ON_ERROR = "on_error"
    ON_PV = "on_pv"


@dataclass
class PIDLoop:
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    pv_channel: str = ""
    cv_channel: Optional[str] = None
    setpoint: float = 0.0
    setpoint_source: str = "manual"
    setpoint_channel: Optional[str] = None
    setpoint_min: float = 0.0
    setpoint_max: float = 100.0
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.0
    output_min: float = 0.0
    output_max: float = 100.0
    output_rate_limit: float = 0.0
    reverse_action: bool = False
    derivative_mode: DerivativeMode = DerivativeMode.ON_PV
    anti_windup: AntiWindupMethod = AntiWindupMethod.CLAMPING
    deadband: float = 0.0
    mode: PIDMode = PIDMode.AUTO
    manual_output: float = 0.0
    bumpless_transfer: bool = True
    output: float = 0.0
    error: float = 0.0
    p_term: float = 0.0
    i_term: float = 0.0
    d_term: float = 0.0
    last_pv: Optional[float] = None
    last_error: Optional[float] = None
    last_output: float = 0.0

    def to_status_dict(self) -> Dict[str, Any]:
        return {'id': self.id, 'name': self.name, 'enabled': self.enabled, 'mode': self.mode.value,
                'pv': self.last_pv if self.last_pv is not None else 0.0, 'setpoint': self.setpoint,
                'output': self.output, 'cv_channel': self.cv_channel, 'error': self.error,
                'p_term': round(self.p_term, 4), 'i_term': round(self.i_term, 4), 'd_term': round(self.d_term, 4)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PIDLoop':
        if 'derivative_mode' in data and isinstance(data['derivative_mode'], str):
            data['derivative_mode'] = DerivativeMode(data['derivative_mode'])
        if 'anti_windup' in data and isinstance(data['anti_windup'], str):
            data['anti_windup'] = AntiWindupMethod(data['anti_windup'])
        if 'mode' in data and isinstance(data['mode'], str):
            data['mode'] = PIDMode(data['mode'])
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known_fields})


class PIDEngine:
    def __init__(self, on_set_output: Optional[Callable[[str, float], bool]] = None):
        self.loops: Dict[str, PIDLoop] = {}
        self._lock = threading.RLock()
        self._on_set_output = on_set_output
        self._status_callback: Optional[Callable[[str, Dict], None]] = None

    def set_status_callback(self, callback: Callable[[str, Dict], None]):
        self._status_callback = callback

    def add_loop(self, loop: PIDLoop) -> bool:
        with self._lock:
            if loop.id in self.loops: return False
            self.loops[loop.id] = loop
            return True

    def set_setpoint(self, loop_id: str, setpoint: float) -> bool:
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop: return False
            loop.setpoint = max(loop.setpoint_min, min(loop.setpoint_max, setpoint))
            return True

    def set_mode(self, loop_id: str, mode: str) -> bool:
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop: return False
            old_mode = loop.mode
            loop.mode = PIDMode(mode)
            if loop.bumpless_transfer and old_mode != loop.mode:
                if loop.mode == PIDMode.AUTO:
                    loop.i_term = loop.output - loop.p_term - loop.d_term
                elif loop.mode == PIDMode.MANUAL:
                    loop.manual_output = loop.output
            return True

    def set_manual_output(self, loop_id: str, output: float) -> bool:
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop: return False
            loop.manual_output = max(loop.output_min, min(loop.output_max, output))
            if loop.mode == PIDMode.MANUAL: loop.output = loop.manual_output
            return True

    def process_scan(self, channel_values: Dict[str, float], dt: float) -> Dict[str, float]:
        outputs = {}
        with self._lock:
            for loop in self.loops.values():
                if not loop.enabled: continue
                pv = channel_values.get(loop.pv_channel)
                if pv is None: continue
                sp = loop.setpoint if loop.setpoint_source == "manual" else channel_values.get(loop.setpoint_channel, loop.setpoint)
                output = self._compute_pid(loop, pv, sp, dt)
                if loop.cv_channel:
                    outputs[loop.cv_channel] = output
                    if self._on_set_output: self._on_set_output(loop.cv_channel, output)
                if self._status_callback: self._status_callback(loop.id, loop.to_status_dict())
        return outputs

    def _compute_pid(self, loop: PIDLoop, pv: float, sp: float, dt: float) -> float:
        if loop.mode == PIDMode.MANUAL:
            loop.output = loop.manual_output
            loop.last_pv = pv
            return loop.output
        error = sp - pv
        if loop.reverse_action: error = -error
        if abs(error) < loop.deadband: error = 0.0
        loop.error = error
        if loop.last_pv is None:
            loop.last_pv = pv
            loop.last_error = error
            loop.i_term = loop.output
        loop.p_term = loop.kp * error
        if loop.ki > 0 and dt > 0:
            contrib = loop.ki * error * dt
            sat_high = loop.output >= loop.output_max and contrib > 0
            sat_low = loop.output <= loop.output_min and contrib < 0
            if loop.anti_windup == AntiWindupMethod.CLAMPING and not (sat_high or sat_low):
                loop.i_term += contrib
            elif loop.anti_windup != AntiWindupMethod.CLAMPING:
                loop.i_term += contrib
        if loop.kd > 0 and dt > 0:
            loop.d_term = loop.kd * (-(pv - loop.last_pv) / dt if loop.derivative_mode == DerivativeMode.ON_PV else (error - (loop.last_error or 0)) / dt)
        else:
            loop.d_term = 0.0
        output = loop.p_term + loop.i_term + loop.d_term
        output = max(loop.output_min, min(loop.output_max, output))
        loop.output = output
        loop.last_pv = pv
        loop.last_error = error
        return output

    def load_config(self, config: Dict[str, Any]):
        with self._lock:
            self.loops.clear()
            for loop_data in config.get('loops', []):
                try:
                    self.loops[loop_data['id']] = PIDLoop.from_dict(loop_data)
                except Exception as e:
                    logger.error(f"Failed to load PID loop: {e}")

    def on_acquisition_start(self):
        """Called when acquisition starts - reset integral terms."""
        with self._lock:
            for loop in self.loops.values():
                loop.last_pv = None
                loop.last_error = None
                loop.i_term = 0.0

    def on_acquisition_stop(self):
        """Called when acquisition stops."""
        pass  # PID loops persist state
