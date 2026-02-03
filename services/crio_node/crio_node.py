#!/usr/bin/env python3
"""
cRIO Node Service for NISystem

Standalone service that runs ON the cRIO-9056 and:
1. Connects to NISystem PC's MQTT broker as a client
2. Receives configuration from NISystem and saves locally
3. Runs DAQ loop with NI-DAQmx watchdog for safe state on failure
4. Continues running even if PC disconnects
5. Executes Python scripts pushed from NISystem

Architecture:
    NISystem PC                              cRIO-9056
    ┌─────────────────┐      MQTT      ┌─────────────────────┐
    │  Dashboard      │◄──────────────►│  cRIO Node Service  │
    │  Backend        │   Config/Data   │  - Local config     │
    │  Project Mgmt   │                 │  - DAQmx watchdog   │
    └─────────────────┘                 │  - Python scripts   │
                                        └─────────────────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ C-Series    │
                                        │ Modules     │
                                        │ (TC,DI,DO)  │
                                        └─────────────┘

Safe State Behavior:
- NI-DAQmx hardware watchdog monitors RT task
- If Python stops petting watchdog, outputs go to safe state (LOW)
- Independent of PC connection - purely local hardware mechanism
"""

import json
import os
import time
import signal
import sys
import logging
import threading
import subprocess
import socket
import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Callable, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import argparse

# MQTT client
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

# Try to import nidaqmx
try:
    import nidaqmx
    from nidaqmx.constants import (
        TerminalConfiguration, ThermocoupleType as NI_TCType,
        AcquisitionType
    )
    from nidaqmx.stream_readers import AnalogMultiChannelReader
    import numpy as np
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    print("WARNING: nidaqmx not available - running in simulation mode")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cRIONode')

# Constants
DEFAULT_CONFIG_DIR = Path('/home/admin/nisystem')  # cRIO Linux path
DEFAULT_CONFIG_FILE = 'crio_config.json'
WATCHDOG_TIMEOUT = 2.0  # seconds - outputs go safe if we don't pet watchdog
SAMPLE_RATE_HZ = 10
BUFFER_SIZE = 100
HEARTBEAT_INTERVAL = 2.0  # seconds
STATUS_PUBLISH_INTERVAL = 30.0  # seconds - periodic status for discovery

# OPC UA style quality code thresholds
OPEN_THERMOCOUPLE_THRESHOLD = 1e300  # NI returns huge values for open TC
MAX_REASONABLE_VALUE = 1e15  # Values beyond this are suspect


def get_value_quality(value: Any) -> str:
    """
    Get OPC UA style quality status for a value.

    Returns:
        'good' - Valid, reliable value
        'bad' - NaN, Inf, None, or open thermocouple
        'uncertain' - Value exceeds reasonable bounds
    """
    if value is None:
        return 'bad'
    if not isinstance(value, (int, float)):
        return 'bad'
    if math.isnan(value):
        return 'bad'
    if math.isinf(value):
        return 'bad'
    if abs(value) > OPEN_THERMOCOUPLE_THRESHOLD:
        return 'bad'
    if abs(value) > MAX_REASONABLE_VALUE:
        return 'uncertain'
    return 'good'


# =============================================================================
# STATE PERSISTENCE FOR SCRIPTS
# =============================================================================

class StatePersistence:
    """
    Persistent state storage for scripts on cRIO.
    Stores to /var/lib/crio_node/script_state.json
    """
    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    self._state = json.load(f)
                logger.info(f"Loaded script state: {len(self._state)} scripts")
        except Exception as e:
            logger.warning(f"Failed to load script state: {e}")
            self._state = {}

    def _save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(self._state, f, indent=2)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to save script state: {e}")

    def persist(self, script_id: str, key: str, value: Any) -> bool:
        with self._lock:
            if script_id not in self._state:
                self._state[script_id] = {}
            self._state[script_id][key] = value
            self._save()
            return True

    def restore(self, script_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(script_id, {}).get(key, default)


# =============================================================================
# HELPER CLASSES FOR SCRIPTS
# =============================================================================

class RateCalculator:
    """Calculate rate of change over a time window."""
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._history: List[tuple] = []

    def update(self, value: float) -> float:
        now = time.time()
        self._history.append((now, value))
        cutoff = now - self.window_seconds
        self._history = [(t, v) for t, v in self._history if t >= cutoff]
        if len(self._history) < 2:
            return 0.0
        t0, v0 = self._history[0]
        t1, v1 = self._history[-1]
        dt = t1 - t0
        return (v1 - v0) / dt if dt > 0 else 0.0

    def reset(self):
        self._history.clear()


class Accumulator:
    """Track cumulative totals from counter values."""
    def __init__(self, initial: float = 0.0):
        self._total = initial
        self._last_value: Optional[float] = None

    def update(self, value: float) -> float:
        if self._last_value is not None:
            delta = value - self._last_value
            if delta < 0:
                delta = value
            self._total += delta
        self._last_value = value
        return self._total

    def reset(self, initial: float = 0.0):
        self._total = initial
        self._last_value = None

    @property
    def total(self) -> float:
        return self._total


class EdgeDetector:
    """Detect rising and falling edges."""
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._last_state: Optional[bool] = None

    def update(self, value: float) -> tuple:
        current_state = value > self.threshold
        rising = falling = False
        if self._last_state is not None:
            rising = current_state and not self._last_state
            falling = not current_state and self._last_state
        self._last_state = current_state
        return (rising, falling, current_state)

    def reset(self):
        self._last_state = None


class RollingStats:
    """Calculate running statistics over a sample window."""
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._buffer: List[float] = []

    def update(self, value: float) -> dict:
        self._buffer.append(value)
        if len(self._buffer) > self.window_size:
            self._buffer = self._buffer[-self.window_size:]
        if not self._buffer:
            return {'mean': 0, 'min': 0, 'max': 0, 'std': 0, 'count': 0}
        n = len(self._buffer)
        mean = sum(self._buffer) / n
        if n > 1:
            variance = sum((x - mean) ** 2 for x in self._buffer) / (n - 1)
            std = variance ** 0.5
        else:
            std = 0.0
        return {'mean': mean, 'min': min(self._buffer), 'max': max(self._buffer), 'std': std, 'count': n}

    def reset(self):
        self._buffer.clear()


class Scheduler:
    """Simple job scheduler for timed operations."""
    def __init__(self):
        self._jobs: Dict[str, dict] = {}

    def add_interval(self, job_id: str, func, seconds: float = 0, minutes: float = 0, hours: float = 0):
        interval = seconds + minutes * 60 + hours * 3600
        self._jobs[job_id] = {'func': func, 'type': 'interval', 'interval': interval,
                              'next_run': time.time() + interval, 'paused': False}

    def add_cron(self, job_id: str, func, minute: int = None, hour: int = None, day_of_week: int = None):
        self._jobs[job_id] = {'func': func, 'type': 'cron', 'minute': minute, 'hour': hour,
                              'day_of_week': day_of_week, 'last_run': None, 'paused': False}

    def add_once(self, job_id: str, func, delay: float):
        self._jobs[job_id] = {'func': func, 'type': 'once', 'run_at': time.time() + delay, 'done': False, 'paused': False}

    def tick(self):
        now = time.time()
        for job_id, job in list(self._jobs.items()):
            if job.get('paused'):
                continue
            if job['type'] == 'interval' and now >= job['next_run']:
                job['func']()
                job['next_run'] = now + job['interval']
            elif job['type'] == 'once' and not job.get('done') and now >= job['run_at']:
                job['func']()
                job['done'] = True
            elif job['type'] == 'cron':
                dt = datetime.now()
                if ((job['minute'] is None or dt.minute == job['minute']) and
                    (job['hour'] is None or dt.hour == job['hour']) and
                    (job['day_of_week'] is None or dt.weekday() == job['day_of_week'])):
                    if job['last_run'] != (dt.hour, dt.minute):
                        job['func']()
                        job['last_run'] = (dt.hour, dt.minute)

    def pause(self, job_id: str):
        if job_id in self._jobs:
            self._jobs[job_id]['paused'] = True

    def resume(self, job_id: str):
        if job_id in self._jobs:
            self._jobs[job_id]['paused'] = False

    def remove(self, job_id: str):
        self._jobs.pop(job_id, None)

    def is_paused(self, job_id: str) -> bool:
        return self._jobs.get(job_id, {}).get('paused', False)


# =============================================================================
# UNIT CONVERSIONS
# =============================================================================

def F_to_C(f: float) -> float: return (f - 32) * 5 / 9
def C_to_F(c: float) -> float: return c * 9 / 5 + 32
def GPM_to_LPM(gpm: float) -> float: return gpm * 3.78541
def LPM_to_GPM(lpm: float) -> float: return lpm / 3.78541
def PSI_to_bar(psi: float) -> float: return psi * 0.0689476
def bar_to_PSI(bar: float) -> float: return bar / 0.0689476
def gal_to_L(gal: float) -> float: return gal * 3.78541
def L_to_gal(l: float) -> float: return l / 3.78541
def BTU_to_kJ(btu: float) -> float: return btu * 1.055056
def kJ_to_BTU(kj: float) -> float: return kj / 1.055056
def lb_to_kg(lb: float) -> float: return lb * 0.453592
def kg_to_lb(kg: float) -> float: return kg / 0.453592


# =============================================================================
# TIME FUNCTIONS
# =============================================================================

def now() -> float: return time.time()
def now_ms() -> int: return int(time.time() * 1000)
def now_iso() -> str: return datetime.now().isoformat()
def time_of_day() -> str: return datetime.now().strftime('%H:%M:%S')
def elapsed_since(start_ts: float) -> float: return time.time() - start_ts
def format_timestamp(ts_ms: int, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    return datetime.fromtimestamp(ts_ms / 1000).strftime(fmt)


class AlarmState(Enum):
    """ISA-18.2 alarm states - evaluated locally on cRIO"""
    NORMAL = "normal"
    HI = "hi"           # Warning high
    HIHI = "hihi"       # Critical high (triggers safety action)
    LO = "lo"           # Warning low
    LOLO = "lolo"       # Critical low (triggers safety action)


@dataclass
class ChannelConfig:
    """Channel configuration matching NISystem format"""
    name: str
    physical_channel: str
    channel_type: str  # thermocouple, voltage, current, digital_input, digital_output, counter

    # Type-specific settings
    thermocouple_type: str = 'K'
    voltage_range: float = 10.0
    current_range_ma: float = 20.0
    terminal_config: str = 'RSE'
    cjc_source: str = 'BUILT_IN'

    # Output settings
    default_state: bool = False
    invert: bool = False

    # Scaling (supports linear, 4-20mA, and map scaling)
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    scale_type: str = 'none'  # 'none', 'linear', 'four_twenty', 'map'
    engineering_units: str = ''
    # 4-20mA scaling (current inputs/outputs)
    four_twenty_scaling: bool = False
    eng_units_min: Optional[float] = None  # Engineering value at 4mA
    eng_units_max: Optional[float] = None  # Engineering value at 20mA
    # Map scaling (voltage inputs/outputs)
    pre_scaled_min: Optional[float] = None
    pre_scaled_max: Optional[float] = None
    scaled_min: Optional[float] = None
    scaled_max: Optional[float] = None

    # ISA-18.2 Alarm Configuration (matches PC daq_service)
    alarm_enabled: bool = False
    hihi_limit: Optional[float] = None       # Critical high (triggers safety action)
    hi_limit: Optional[float] = None         # Warning high
    lo_limit: Optional[float] = None         # Warning low
    lolo_limit: Optional[float] = None       # Critical low (triggers safety action)
    alarm_priority: str = 'medium'           # low, medium, high, critical
    alarm_deadband: float = 0.0              # Hysteresis to prevent alarm chatter
    alarm_delay_sec: float = 0.0             # Delay before alarm triggers
    # Legacy alarm fields (for backwards compatibility with old config files)
    alarm_high: Optional[float] = None       # Deprecated: use hi_limit instead
    alarm_low: Optional[float] = None        # Deprecated: use lo_limit instead

    # Safety settings (for autonomous cRIO operation)
    safety_action: Optional[str] = None      # Name of safety action to trigger on limit violation
    safety_interlock: Optional[str] = None   # Boolean expression that must be True for writes
    expected_state: Optional[bool] = None    # For digital inputs - expected safe state


@dataclass
class SafetyActionConfig:
    """
    Safety action configuration for autonomous cRIO operation.

    When triggered, sets specified outputs to safe values.
    This runs locally on cRIO without PC involvement.
    """
    name: str
    description: str = ""
    actions: Dict[str, Any] = field(default_factory=dict)  # channel_name -> safe_value
    trigger_alarm: bool = False
    alarm_message: str = ""


@dataclass
class SessionState:
    """
    Session state for autonomous cRIO operation.

    Tracks test session state locally on cRIO so it continues
    even if PC disconnects.
    """
    active: bool = False
    start_time: Optional[float] = None
    name: str = ""
    operator: str = ""
    locked_outputs: List[str] = field(default_factory=list)  # Outputs locked during session
    timeout_minutes: float = 0  # Auto-stop after N minutes (0 = no timeout)


class LatchState(Enum):
    """Safety latch states for local cRIO operation"""
    SAFE = "safe"          # Latch is disarmed, outputs blocked
    ARMED = "armed"        # Latch is armed, outputs allowed
    TRIPPED = "tripped"    # System tripped due to safety violation


@dataclass
class LocalInterlockConfig:
    """Local interlock configuration for autonomous cRIO operation"""
    id: str
    name: str
    enabled: bool = True
    conditions: List[Dict[str, Any]] = field(default_factory=list)  # Simplified conditions
    condition_logic: str = "AND"  # AND or OR
    output_channels: List[str] = field(default_factory=list)  # Channels blocked when failed


class LocalSafetyManager:
    """
    Local safety manager for autonomous cRIO operation.

    Provides:
    - Local interlock evaluation based on channel values
    - Local latch state machine (SAFE → ARMED → TRIPPED)
    - Trip actions when safety limits violated while armed
    - Syncs with PC SafetyManager when connected

    This runs independently on cRIO, ensuring safety logic continues
    even when PC is disconnected.
    """

    def __init__(self, get_channel_value, set_output, stop_session, publish):
        self.get_channel_value = get_channel_value
        self.set_output = set_output
        self.stop_session = stop_session
        self.publish = publish

        self.lock = threading.RLock()

        # Latch state
        self.latch_state = LatchState.SAFE
        self.is_tripped = False
        self.last_trip_time: Optional[str] = None
        self.last_trip_reason: Optional[str] = None

        # Local interlocks (simplified version of PC interlocks)
        self.interlocks: Dict[str, LocalInterlockConfig] = {}

        # Previous interlock states for state change detection
        self._previous_states: Dict[str, bool] = {}

    def arm_latch(self, user: str = "local") -> bool:
        """Arm the safety latch"""
        with self.lock:
            if self.is_tripped:
                logger.warning("[LocalSafety] Cannot arm - system is tripped")
                return False

            if self._has_failed_interlocks():
                logger.warning("[LocalSafety] Cannot arm - interlocks failed")
                return False

            self.latch_state = LatchState.ARMED
            self._publish_latch_state(user=user)
            logger.info(f"[LocalSafety] Latch armed by {user}")
            return True

    def disarm_latch(self, user: str = "local"):
        """Disarm the safety latch"""
        with self.lock:
            self.latch_state = LatchState.SAFE
            self._publish_latch_state(user=user)
            logger.info(f"[LocalSafety] Latch disarmed by {user}")

    def trip_system(self, reason: str):
        """Trip the system - set outputs to safe state"""
        with self.lock:
            logger.critical(f"[LocalSafety] SYSTEM TRIP: {reason}")

            self.is_tripped = True
            self.last_trip_time = datetime.now(timezone.utc).isoformat()
            self.last_trip_reason = reason
            self.latch_state = LatchState.TRIPPED

            # Stop session
            if self.stop_session:
                try:
                    self.stop_session()
                except Exception as e:
                    logger.error(f"[LocalSafety] Failed to stop session: {e}")

            # Publish trip event
            if self.publish:
                self.publish('safety/trip', {
                    'reason': reason,
                    'timestamp': self.last_trip_time
                })

            self._publish_latch_state(tripped=True, trip_reason=reason)

    def reset_trip(self, user: str = "local") -> bool:
        """Reset the trip state"""
        with self.lock:
            if self._has_failed_interlocks():
                logger.warning("[LocalSafety] Cannot reset - interlocks still failed")
                return False

            self.is_tripped = False
            self.last_trip_reason = None
            self.latch_state = LatchState.SAFE
            self._publish_latch_state(user=user)
            logger.info(f"[LocalSafety] Trip reset by {user}")
            return True

    def add_interlock(self, interlock: LocalInterlockConfig):
        """Add or update a local interlock"""
        with self.lock:
            self.interlocks[interlock.id] = interlock
            logger.info(f"[LocalSafety] Interlock added: {interlock.name}")

    def remove_interlock(self, interlock_id: str):
        """Remove a local interlock"""
        with self.lock:
            if interlock_id in self.interlocks:
                del self.interlocks[interlock_id]

    def evaluate_interlock(self, interlock: LocalInterlockConfig) -> bool:
        """Evaluate a local interlock and return True if satisfied"""
        if not interlock.enabled:
            return True

        results = []
        for condition in interlock.conditions:
            satisfied = self._evaluate_condition(condition)
            results.append(satisfied)

        if interlock.condition_logic == 'OR':
            return any(results) if results else True
        else:  # AND
            return all(results) if results else True

    def _evaluate_condition(self, condition: Dict[str, Any]) -> bool:
        """Evaluate a single interlock condition"""
        cond_type = condition.get('type', 'channel_value')

        if cond_type == 'channel_value':
            channel = condition.get('channel')
            operator = condition.get('operator')
            threshold = condition.get('value')

            if not channel or operator is None or threshold is None:
                return True  # Invalid condition - assume satisfied

            value = self.get_channel_value(channel)
            if value is None:
                return False  # No value - assume not satisfied

            return self._compare_values(float(value), operator, float(threshold))

        elif cond_type == 'digital_input':
            channel = condition.get('channel')
            expected = condition.get('value', True)
            invert = condition.get('invert', False)

            value = self.get_channel_value(channel)
            if value is None:
                return False

            raw_state = value != 0
            actual_state = not raw_state if invert else raw_state
            return actual_state == expected

        return True  # Unknown condition type - assume satisfied

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Compare values using the specified operator"""
        if operator == '<':
            return current < threshold
        elif operator == '<=':
            return current <= threshold
        elif operator == '>':
            return current > threshold
        elif operator == '>=':
            return current >= threshold
        elif operator in ('=', '=='):
            return current == threshold
        elif operator in ('!=', '<>'):
            return current != threshold
        return False

    def _has_failed_interlocks(self) -> bool:
        """Check if any interlocks have failed"""
        for interlock in self.interlocks.values():
            if interlock.enabled and not self.evaluate_interlock(interlock):
                return True
        return False

    def get_failed_interlocks(self) -> List[LocalInterlockConfig]:
        """Get list of failed interlocks"""
        failed = []
        for interlock in self.interlocks.values():
            if interlock.enabled and not self.evaluate_interlock(interlock):
                failed.append(interlock)
        return failed

    def evaluate_all(self):
        """Evaluate all interlocks and update latch state"""
        with self.lock:
            any_failed = self._has_failed_interlocks()

            # Check if we should trip (armed + interlock failed)
            if any_failed and self.latch_state == LatchState.ARMED and not self.is_tripped:
                failed = self.get_failed_interlocks()
                reason = f"Interlock failed: {', '.join([i.name for i in failed])}"
                self.trip_system(reason)

    def is_output_blocked(self, channel: str) -> bool:
        """Check if an output channel is blocked by any interlock"""
        for interlock in self.interlocks.values():
            if not interlock.enabled:
                continue
            if not self.evaluate_interlock(interlock):
                if channel in interlock.output_channels:
                    return True
        return False

    def _publish_latch_state(self, user: str = None, tripped: bool = False, trip_reason: str = None):
        """Publish latch state via MQTT"""
        if not self.publish:
            return

        self.publish('safety/latch/state', {
            'latchId': 'local',
            'state': self.latch_state.value,
            'armed': self.latch_state == LatchState.ARMED,
            'tripped': tripped,
            'tripReason': trip_reason,
            'user': user,
            'source': 'crio_local',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def get_status(self) -> Dict[str, Any]:
        """Get current safety status"""
        with self.lock:
            failed = self.get_failed_interlocks()
            return {
                'latchState': self.latch_state.value,
                'isTripped': self.is_tripped,
                'lastTripTime': self.last_trip_time,
                'lastTripReason': self.last_trip_reason,
                'hasFailedInterlocks': len(failed) > 0,
                'failedInterlockNames': [i.name for i in failed],
                'interlockCount': len(self.interlocks),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }


# =============================================================================
# PID CONTROL ENGINE
# =============================================================================

class PIDMode(str, Enum):
    """PID loop operating mode"""
    AUTO = "auto"
    MANUAL = "manual"
    CASCADE = "cascade"


class AntiWindupMethod(str, Enum):
    """Anti-windup strategy for integral term"""
    NONE = "none"
    CLAMPING = "clamping"
    BACK_CALCULATION = "back_calculation"


class DerivativeMode(str, Enum):
    """Derivative calculation mode"""
    ON_ERROR = "on_error"
    ON_PV = "on_pv"


@dataclass
class PIDLoop:
    """PID control loop configuration and state"""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    pv_channel: str = ""
    pv_engineering_units: str = ""
    cv_channel: Optional[str] = None
    cv_engineering_units: str = "%"
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
    # Runtime state
    output: float = 0.0
    error: float = 0.0
    p_term: float = 0.0
    i_term: float = 0.0
    d_term: float = 0.0
    last_pv: Optional[float] = None
    last_error: Optional[float] = None
    last_output: float = 0.0
    last_update_time: float = 0.0

    def to_config_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'enabled': self.enabled, 'pv_channel': self.pv_channel,
            'cv_channel': self.cv_channel, 'setpoint': self.setpoint,
            'setpoint_min': self.setpoint_min, 'setpoint_max': self.setpoint_max,
            'kp': self.kp, 'ki': self.ki, 'kd': self.kd,
            'output_min': self.output_min, 'output_max': self.output_max,
            'output_rate_limit': self.output_rate_limit,
            'reverse_action': self.reverse_action,
            'derivative_mode': self.derivative_mode.value,
            'anti_windup': self.anti_windup.value, 'deadband': self.deadband,
            'mode': self.mode.value, 'manual_output': self.manual_output,
            'bumpless_transfer': self.bumpless_transfer,
        }

    def to_status_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id, 'name': self.name, 'enabled': self.enabled,
            'mode': self.mode.value,
            'pv': self.last_pv if self.last_pv is not None else 0.0,
            'pv_channel': self.pv_channel, 'setpoint': self.setpoint,
            'output': self.output, 'cv_channel': self.cv_channel,
            'error': self.error, 'p_term': round(self.p_term, 4),
            'i_term': round(self.i_term, 4), 'd_term': round(self.d_term, 4),
            'output_saturated': self.output <= self.output_min or self.output >= self.output_max,
            'timestamp': datetime.now().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PIDLoop':
        if 'derivative_mode' in data and isinstance(data['derivative_mode'], str):
            data['derivative_mode'] = DerivativeMode(data['derivative_mode'])
        if 'anti_windup' in data and isinstance(data['anti_windup'], str):
            data['anti_windup'] = AntiWindupMethod(data['anti_windup'])
        if 'mode' in data and isinstance(data['mode'], str):
            data['mode'] = PIDMode(data['mode'])
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)


class PIDEngine:
    """PID Control Engine - manages multiple PID loops"""

    def __init__(self, on_set_output: Optional[Callable[[str, float], bool]] = None):
        self.loops: Dict[str, PIDLoop] = {}
        self._lock = threading.RLock()
        self._on_set_output = on_set_output
        self._status_callback: Optional[Callable[[str, Dict], None]] = None

    def set_status_callback(self, callback: Callable[[str, Dict], None]):
        self._status_callback = callback

    def set_output_callback(self, callback: Callable[[str, float], bool]):
        self._on_set_output = callback

    def add_loop(self, loop: PIDLoop) -> bool:
        with self._lock:
            if loop.id in self.loops:
                return False
            self.loops[loop.id] = loop
            return True

    def update_loop(self, loop_id: str, updates: Dict[str, Any]) -> bool:
        with self._lock:
            if loop_id not in self.loops:
                return False
            loop = self.loops[loop_id]
            old_mode = loop.mode
            for key, value in updates.items():
                if hasattr(loop, key):
                    if key == 'mode' and isinstance(value, str):
                        value = PIDMode(value)
                    elif key == 'derivative_mode' and isinstance(value, str):
                        value = DerivativeMode(value)
                    elif key == 'anti_windup' and isinstance(value, str):
                        value = AntiWindupMethod(value)
                    setattr(loop, key, value)
            if loop.bumpless_transfer and old_mode != loop.mode:
                self._handle_mode_change(loop, old_mode, loop.mode)
            return True

    def remove_loop(self, loop_id: str) -> bool:
        with self._lock:
            if loop_id not in self.loops:
                return False
            del self.loops[loop_id]
            return True

    def get_loop(self, loop_id: str) -> Optional[PIDLoop]:
        with self._lock:
            return self.loops.get(loop_id)

    def get_all_loops(self) -> List[PIDLoop]:
        with self._lock:
            return list(self.loops.values())

    def clear_loops(self):
        with self._lock:
            self.loops.clear()

    def set_setpoint(self, loop_id: str, setpoint: float) -> bool:
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False
            setpoint = max(loop.setpoint_min, min(loop.setpoint_max, setpoint))
            loop.setpoint = setpoint
            loop.setpoint_source = "manual"
            return True

    def set_mode(self, loop_id: str, mode: str) -> bool:
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
            return True

    def set_manual_output(self, loop_id: str, output: float) -> bool:
        with self._lock:
            loop = self.loops.get(loop_id)
            if not loop:
                return False
            output = max(loop.output_min, min(loop.output_max, output))
            loop.manual_output = output
            if loop.mode == PIDMode.MANUAL:
                loop.output = output
            return True

    def process_scan(self, channel_values: Dict[str, float], dt: float) -> Dict[str, float]:
        """Process all PID loops for one scan cycle"""
        outputs = {}
        with self._lock:
            for loop in self.loops.values():
                if not loop.enabled:
                    continue
                pv = channel_values.get(loop.pv_channel)
                if pv is None:
                    continue
                sp = self._get_setpoint(loop, channel_values)
                output = self._compute_pid(loop, pv, sp, dt)
                if loop.cv_channel:
                    outputs[loop.cv_channel] = output
                    if self._on_set_output:
                        self._on_set_output(loop.cv_channel, output)
                if self._status_callback:
                    self._status_callback(loop.id, loop.to_status_dict())
        return outputs

    def _get_setpoint(self, loop: PIDLoop, channel_values: Dict[str, float]) -> float:
        if loop.setpoint_source == "manual":
            return loop.setpoint
        elif loop.setpoint_source == "channel" and loop.setpoint_channel:
            sp = channel_values.get(loop.setpoint_channel, loop.setpoint)
            return max(loop.setpoint_min, min(loop.setpoint_max, sp))
        elif loop.setpoint_source in self.loops:
            return self.loops[loop.setpoint_source].output
        return loop.setpoint

    def _compute_pid(self, loop: PIDLoop, pv: float, sp: float, dt: float) -> float:
        if loop.mode == PIDMode.MANUAL:
            loop.output = loop.manual_output
            loop.last_pv = pv
            loop.last_error = sp - pv
            return loop.output

        error = sp - pv
        if loop.reverse_action:
            error = -error
        if abs(error) < loop.deadband:
            error = 0.0
        loop.error = error

        if loop.last_pv is None:
            loop.last_pv = pv
            loop.last_error = error
            loop.last_output = loop.output
            loop.i_term = loop.output

        loop.p_term = loop.kp * error

        if loop.ki > 0 and dt > 0:
            integral_contribution = loop.ki * error * dt
            if loop.anti_windup == AntiWindupMethod.CLAMPING:
                sat_high = loop.output >= loop.output_max and integral_contribution > 0
                sat_low = loop.output <= loop.output_min and integral_contribution < 0
                if not (sat_high or sat_low):
                    loop.i_term += integral_contribution
            else:
                loop.i_term += integral_contribution

        if loop.kd > 0 and dt > 0:
            if loop.derivative_mode == DerivativeMode.ON_PV:
                d_input = -(pv - loop.last_pv) / dt
            else:
                d_input = (error - loop.last_error) / dt
            loop.d_term = loop.kd * d_input
        else:
            loop.d_term = 0.0

        output = loop.p_term + loop.i_term + loop.d_term

        if loop.output_rate_limit > 0 and dt > 0:
            max_change = loop.output_rate_limit * dt
            output_change = output - loop.last_output
            if abs(output_change) > max_change:
                output = loop.last_output + max_change * (1 if output_change > 0 else -1)

        output = max(loop.output_min, min(loop.output_max, output))

        if loop.anti_windup == AntiWindupMethod.BACK_CALCULATION:
            unclamped = loop.p_term + loop.i_term + loop.d_term
            if output != unclamped:
                loop.i_term = output - loop.p_term - loop.d_term

        loop.output = output
        loop.last_pv = pv
        loop.last_error = error
        loop.last_output = output
        loop.last_update_time = time.time()
        return output

    def _handle_mode_change(self, loop: PIDLoop, old_mode: PIDMode, new_mode: PIDMode):
        if new_mode == PIDMode.AUTO and old_mode == PIDMode.MANUAL:
            loop.i_term = loop.output - loop.p_term - loop.d_term
        elif new_mode == PIDMode.MANUAL and old_mode == PIDMode.AUTO:
            loop.manual_output = loop.output

    def load_config(self, config: Dict[str, Any]):
        with self._lock:
            self.loops.clear()
            for loop_data in config.get('loops', []):
                try:
                    loop = PIDLoop.from_dict(loop_data)
                    self.loops[loop.id] = loop
                except Exception as e:
                    logger.error(f"Failed to load PID loop: {e}")

    def to_config_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {'loops': [loop.to_config_dict() for loop in self.loops.values()]}


# =============================================================================
# SEQUENCE MANAGER
# =============================================================================

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
    CONDITIONAL = "conditional"


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
    true_step_index: Optional[int] = None
    false_step_index: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

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
    error_message: Optional[str] = None
    loop_counters: Dict[str, int] = field(default_factory=dict)
    loop_start_indices: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "enabled": self.enabled, "steps": [s.to_dict() for s in self.steps],
            "state": self.state.value, "current_step_index": self.current_step_index,
            "start_time": self.start_time, "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Sequence':
        steps = [SequenceStep.from_dict(s) for s in data.get("steps", [])]
        state = SequenceState(data.get("state", "idle"))
        return cls(id=data["id"], name=data["name"], description=data.get("description", ""),
                   enabled=data.get("enabled", True), steps=steps, state=state,
                   current_step_index=data.get("current_step_index", 0))


class SequenceManager:
    """Manages automation sequence execution"""

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

    def remove_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if sequence_id in self.sequences and self._running_sequence_id != sequence_id:
                del self.sequences[sequence_id]
                return True
            return False

    def get_sequence(self, sequence_id: str) -> Optional[Sequence]:
        return self.sequences.get(sequence_id)

    def get_all_sequences(self) -> List[Sequence]:
        return list(self.sequences.values())

    def start_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            seq = self.sequences.get(sequence_id)
            if not seq or not seq.enabled or self._running_sequence_id:
                return False
            seq.state = SequenceState.RUNNING
            seq.current_step_index = 0
            seq.start_time = time.time()
            seq.error_message = None
            seq.loop_counters = {}
            seq.loop_start_indices = {}
            self._running_sequence_id = sequence_id
            self._stop_event.clear()
            self._pause_event.set()
            self._execution_thread = threading.Thread(target=self._execute_sequence, args=(seq,), daemon=True)
            self._execution_thread.start()
            self._emit_event("started", seq)
            return True

    def pause_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False
            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.PAUSED
                self._pause_event.clear()
                self._emit_event("paused", seq)
                return True
            return False

    def resume_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False
            seq = self.sequences.get(sequence_id)
            if seq and seq.state == SequenceState.PAUSED:
                seq.state = SequenceState.RUNNING
                self._pause_event.set()
                self._emit_event("resumed", seq)
                return True
            return False

    def abort_sequence(self, sequence_id: str) -> bool:
        with self._lock:
            if self._running_sequence_id != sequence_id:
                return False
            seq = self.sequences.get(sequence_id)
            if seq and seq.state in (SequenceState.RUNNING, SequenceState.PAUSED):
                seq.state = SequenceState.ABORTED
                self._stop_event.set()
                self._pause_event.set()
                self._emit_event("aborted", seq)
                return True
            return False

    def _execute_sequence(self, seq: Sequence):
        try:
            while seq.current_step_index < len(seq.steps):
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break
                step = seq.steps[seq.current_step_index]
                try:
                    self._execute_step(seq, step)
                except Exception as e:
                    seq.state = SequenceState.ERROR
                    seq.error_message = str(e)
                    self._emit_event("error", seq)
                    break
                if seq.state == SequenceState.RUNNING:
                    seq.current_step_index += 1
            if seq.state == SequenceState.RUNNING:
                seq.state = SequenceState.COMPLETED
                self._emit_event("completed", seq)
        finally:
            with self._lock:
                self._running_sequence_id = None

    def _execute_step(self, seq: Sequence, step: SequenceStep):
        if step.type == StepType.SET_OUTPUT.value:
            if self.on_set_output and step.channel is not None:
                self.on_set_output(step.channel, step.value)
        elif step.type == StepType.WAIT_DURATION.value:
            self._wait_with_check((step.duration_ms or 0) / 1000.0)
        elif step.type == StepType.WAIT_CONDITION.value:
            self._wait_for_condition(step)
        elif step.type == StepType.LOG_MESSAGE.value:
            logger.info(f"Sequence log: {step.message}")
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
        elif step.type == StepType.CONDITIONAL.value:
            if self._evaluate_condition(step):
                if step.true_step_index is not None:
                    seq.current_step_index = step.true_step_index - 1
            else:
                if step.false_step_index is not None:
                    seq.current_step_index = step.false_step_index - 1

    def _wait_with_check(self, duration_s: float):
        end_time = time.time() + duration_s
        while time.time() < end_time:
            if self._stop_event.is_set():
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            time.sleep(0.1)

    def _wait_for_condition(self, step: SequenceStep):
        if not self.on_get_channel_value or not step.condition_channel:
            return
        timeout_s = (step.condition_timeout_ms or 30000) / 1000.0
        end_time = time.time() + timeout_s
        while time.time() < end_time:
            if self._stop_event.is_set():
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            if self._evaluate_condition(step):
                return
            time.sleep(0.1)

    def _evaluate_condition(self, step: SequenceStep) -> bool:
        if not self.on_get_channel_value or not step.condition_channel:
            return True
        current_value = self.on_get_channel_value(step.condition_channel)
        if current_value is None:
            return False
        target = step.condition_value
        op = step.condition_operator or "=="
        try:
            if op == "==": return current_value == target
            elif op == "!=": return current_value != target
            elif op == "<": return float(current_value) < float(target)
            elif op == ">": return float(current_value) > float(target)
            elif op == "<=": return float(current_value) <= float(target)
            elif op == ">=": return float(current_value) >= float(target)
        except (ValueError, TypeError):
            return False
        return False

    def _emit_event(self, event_type: str, seq: Sequence):
        if self.on_sequence_event:
            try:
                self.on_sequence_event(event_type, seq)
            except Exception as e:
                logger.error(f"Error in sequence event handler: {e}")

    def load_config(self, config: Dict[str, Any]):
        with self._lock:
            self.sequences.clear()
            for seq_data in config.get('sequences', []):
                try:
                    seq = Sequence.from_dict(seq_data)
                    seq.state = SequenceState.IDLE
                    self.sequences[seq.id] = seq
                except Exception as e:
                    logger.error(f"Failed to load sequence: {e}")


# =============================================================================
# TRIGGER ENGINE
# =============================================================================

class TriggerType(str, Enum):
    VALUE_REACHED = "valueReached"
    TIME_ELAPSED = "timeElapsed"
    STATE_CHANGE = "stateChange"


class TriggerActionType(str, Enum):
    START_SEQUENCE = "startSequence"
    STOP_SEQUENCE = "stopSequence"
    SET_OUTPUT = "setOutput"
    NOTIFICATION = "notification"
    LOG = "log"


@dataclass
class TriggerAction:
    action_type: TriggerActionType
    sequence_id: Optional[str] = None
    channel: Optional[str] = None
    value: Optional[float] = None
    message: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TriggerAction':
        action_type_str = data.get('type', 'notification')
        if action_type_str == 'runSequence':
            action_type_str = 'startSequence'
        return TriggerAction(
            action_type=TriggerActionType(action_type_str),
            sequence_id=data.get('sequenceId'),
            channel=data.get('channel'),
            value=data.get('value'),
            message=data.get('message')
        )


@dataclass
class TriggerCondition:
    trigger_type: TriggerType
    channel: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    hysteresis: Optional[float] = 0.0
    duration_ms: Optional[int] = None
    start_event: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TriggerCondition':
        return TriggerCondition(
            trigger_type=TriggerType(data.get('type', 'valueReached')),
            channel=data.get('channel'),
            operator=data.get('operator'),
            threshold=data.get('value'),
            hysteresis=data.get('hysteresis', 0.0),
            duration_ms=data.get('durationMs'),
            start_event=data.get('startEvent')
        )


@dataclass
class AutomationTrigger:
    id: str
    name: str
    description: str
    enabled: bool
    one_shot: bool
    cooldown_ms: int
    condition: TriggerCondition
    actions: List[TriggerAction]
    last_triggered: Optional[float] = None
    has_fired: bool = False
    last_value_state: Optional[bool] = None
    start_time: Optional[float] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'AutomationTrigger':
        condition = TriggerCondition.from_dict(data.get('trigger', {}))
        actions = [TriggerAction.from_dict(a) for a in data.get('actions', [])]
        return AutomationTrigger(
            id=data.get('id', ''), name=data.get('name', ''),
            description=data.get('description', ''), enabled=data.get('enabled', True),
            one_shot=data.get('oneShot', False), cooldown_ms=data.get('cooldownMs', 5000),
            condition=condition, actions=actions
        )


class TriggerEngine:
    """Evaluates automation triggers each scan"""

    def __init__(self):
        self.triggers: Dict[str, AutomationTrigger] = {}
        self.lock = threading.Lock()
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self._acquisition_start_time: Optional[float] = None
        self._is_acquiring: bool = False

    def load_from_config(self, config: Dict[str, Any]) -> int:
        with self.lock:
            self.triggers.clear()
            triggers_data = config.get('scripts', {}).get('triggers', [])
            for trigger_data in triggers_data:
                try:
                    trigger = AutomationTrigger.from_dict(trigger_data)
                    self.triggers[trigger.id] = trigger
                except Exception as e:
                    logger.error(f"Failed to load trigger: {e}")
            return len(self.triggers)

    def clear(self):
        with self.lock:
            self.triggers.clear()

    def on_acquisition_start(self):
        self._acquisition_start_time = time.time()
        self._is_acquiring = True

    def on_acquisition_stop(self):
        self._acquisition_start_time = None
        self._is_acquiring = False

    def process_scan(self, channel_values: Dict[str, float]):
        if not self._is_acquiring:
            return
        now = time.time()
        with self.lock:
            for trigger in self.triggers.values():
                if not trigger.enabled:
                    continue
                if trigger.one_shot and trigger.has_fired:
                    continue
                if trigger.last_triggered:
                    elapsed = (now - trigger.last_triggered) * 1000
                    if elapsed < trigger.cooldown_ms:
                        continue
                should_fire = self._evaluate_condition(trigger, channel_values, now)
                if should_fire:
                    self._fire_trigger(trigger, now)

    def _evaluate_condition(self, trigger: AutomationTrigger, channel_values: Dict[str, float], now: float) -> bool:
        cond = trigger.condition
        if cond.trigger_type == TriggerType.VALUE_REACHED:
            return self._evaluate_value_reached(trigger, channel_values)
        elif cond.trigger_type == TriggerType.TIME_ELAPSED:
            return self._evaluate_time_elapsed(trigger, now)
        return False

    def _evaluate_value_reached(self, trigger: AutomationTrigger, channel_values: Dict[str, float]) -> bool:
        cond = trigger.condition
        if not cond.channel or cond.channel not in channel_values:
            return False
        value = channel_values[cond.channel]
        threshold = cond.threshold or 0
        operator = cond.operator or '=='
        if math.isnan(value):
            return False
        condition_met = False
        if operator == '>': condition_met = value > threshold
        elif operator == '<': condition_met = value < threshold
        elif operator == '>=': condition_met = value >= threshold
        elif operator == '<=': condition_met = value <= threshold
        elif operator == '==': condition_met = abs(value - threshold) < 0.001
        elif operator == '!=': condition_met = abs(value - threshold) >= 0.001
        was_met = trigger.last_value_state
        trigger.last_value_state = condition_met
        if was_met is None:
            return condition_met
        return not was_met and condition_met

    def _evaluate_time_elapsed(self, trigger: AutomationTrigger, now: float) -> bool:
        cond = trigger.condition
        if not cond.duration_ms:
            return False
        start_time = self._acquisition_start_time if cond.start_event == 'acquisitionStart' else trigger.start_time
        if start_time is None:
            return False
        elapsed_ms = (now - start_time) * 1000
        return elapsed_ms >= cond.duration_ms

    def _fire_trigger(self, trigger: AutomationTrigger, now: float):
        logger.info(f"Trigger fired: {trigger.name}")
        trigger.last_triggered = now
        if trigger.one_shot:
            trigger.has_fired = True
        for action in trigger.actions:
            try:
                self._execute_action(action, trigger)
            except Exception as e:
                logger.error(f"Failed to execute trigger action: {e}")

    def _execute_action(self, action: TriggerAction, trigger: AutomationTrigger):
        if action.action_type == TriggerActionType.START_SEQUENCE:
            if self.run_sequence and action.sequence_id:
                self.run_sequence(action.sequence_id)
        elif action.action_type == TriggerActionType.STOP_SEQUENCE:
            if self.stop_sequence and action.sequence_id:
                self.stop_sequence(action.sequence_id)
        elif action.action_type == TriggerActionType.SET_OUTPUT:
            if self.set_output and action.channel is not None:
                self.set_output(action.channel, action.value)
        elif action.action_type == TriggerActionType.NOTIFICATION:
            if self.publish_notification and action.message:
                self.publish_notification('trigger', trigger.name, action.message)
        elif action.action_type == TriggerActionType.LOG:
            if action.message:
                logger.info(f"Trigger {trigger.name} LOG: {action.message}")


# =============================================================================
# WATCHDOG ENGINE
# =============================================================================

class WatchdogConditionType(str, Enum):
    STALE_DATA = "stale_data"
    OUT_OF_RANGE = "out_of_range"
    RATE_EXCEEDED = "rate_exceeded"
    STUCK_VALUE = "stuck_value"


class WatchdogActionType(str, Enum):
    NOTIFICATION = "notification"
    ALARM = "alarm"
    SET_OUTPUT = "setOutput"
    STOP_SEQUENCE = "stopSequence"
    RUN_SEQUENCE = "runSequence"


@dataclass
class WatchdogCondition:
    condition_type: WatchdogConditionType
    max_stale_ms: int = 5000
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_rate_per_min: Optional[float] = None
    stuck_duration_ms: int = 30000
    stuck_tolerance: float = 0.001

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WatchdogCondition':
        return WatchdogCondition(
            condition_type=WatchdogConditionType(data.get('type', 'stale_data')),
            max_stale_ms=data.get('maxStaleMs', 5000),
            min_value=data.get('minValue'),
            max_value=data.get('maxValue'),
            max_rate_per_min=data.get('maxRatePerMin'),
            stuck_duration_ms=data.get('stuckDurationMs', 30000),
            stuck_tolerance=data.get('stuckTolerance', 0.001)
        )


@dataclass
class WatchdogAction:
    action_type: WatchdogActionType
    message: Optional[str] = None
    channel: Optional[str] = None
    value: Optional[float] = None
    sequence_id: Optional[str] = None
    alarm_severity: str = "warning"

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WatchdogAction':
        return WatchdogAction(
            action_type=WatchdogActionType(data.get('type', 'notification')),
            message=data.get('message'),
            channel=data.get('channel'),
            value=data.get('value'),
            sequence_id=data.get('sequenceId'),
            alarm_severity=data.get('alarmSeverity', 'warning')
        )


@dataclass
class Watchdog:
    id: str
    name: str
    description: str
    enabled: bool
    channels: List[str]
    condition: WatchdogCondition
    actions: List[WatchdogAction]
    recovery_actions: List[WatchdogAction] = field(default_factory=list)
    auto_recover: bool = True
    cooldown_ms: int = 10000
    is_triggered: bool = False
    triggered_at: Optional[float] = None
    triggered_channels: List[str] = field(default_factory=list)
    last_triggered: Optional[float] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Watchdog':
        condition = WatchdogCondition.from_dict(data.get('condition', {}))
        actions = [WatchdogAction.from_dict(a) for a in data.get('actions', [])]
        recovery_actions = [WatchdogAction.from_dict(a) for a in data.get('recoveryActions', [])]
        return Watchdog(
            id=data.get('id', ''), name=data.get('name', ''),
            description=data.get('description', ''), enabled=data.get('enabled', True),
            channels=data.get('channels', []), condition=condition,
            actions=actions, recovery_actions=recovery_actions,
            auto_recover=data.get('autoRecover', True), cooldown_ms=data.get('cooldownMs', 10000)
        )


@dataclass
class ChannelTracker:
    last_value: Optional[float] = None
    last_update_time: Optional[float] = None
    stuck_since: Optional[float] = None
    rate_history: List[tuple] = field(default_factory=list)


class WatchdogEngine:
    """Monitors channels for abnormal conditions"""

    def __init__(self):
        self.watchdogs: Dict[str, Watchdog] = {}
        self.channel_trackers: Dict[str, ChannelTracker] = {}
        self.lock = threading.Lock()
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self.raise_alarm: Optional[Callable[[str, str, str], None]] = None
        self._is_acquiring: bool = False

    def on_acquisition_start(self):
        self._is_acquiring = True

    def on_acquisition_stop(self):
        self._is_acquiring = False

    def load_from_config(self, config: Dict[str, Any]) -> int:
        with self.lock:
            self.watchdogs.clear()
            self.channel_trackers.clear()
            watchdogs_data = config.get('scripts', {}).get('watchdogs', [])
            for wd_data in watchdogs_data:
                try:
                    wd = Watchdog.from_dict(wd_data)
                    self.watchdogs[wd.id] = wd
                    for ch in wd.channels:
                        if ch not in self.channel_trackers:
                            self.channel_trackers[ch] = ChannelTracker()
                except Exception as e:
                    logger.error(f"Failed to load watchdog: {e}")
            return len(self.watchdogs)

    def clear(self):
        with self.lock:
            self.watchdogs.clear()
            self.channel_trackers.clear()

    def process_scan(self, channel_values: Dict[str, float], channel_timestamps: Dict[str, float] = None):
        if not self._is_acquiring:
            return
        if channel_timestamps is None:
            channel_timestamps = {}
        now = time.time()
        for channel, value in channel_values.items():
            if channel not in self.channel_trackers:
                self.channel_trackers[channel] = ChannelTracker()
            tracker = self.channel_trackers[channel]
            timestamp = channel_timestamps.get(channel, now)
            tracker.rate_history.append((now, value))
            cutoff = now - 60
            tracker.rate_history = [(t, v) for t, v in tracker.rate_history if t >= cutoff]
            if tracker.last_value is not None:
                if abs(value - tracker.last_value) <= 0.001:
                    if tracker.stuck_since is None:
                        tracker.stuck_since = now
                else:
                    tracker.stuck_since = None
            tracker.last_value = value
            tracker.last_update_time = timestamp

        with self.lock:
            for wd in self.watchdogs.values():
                if not wd.enabled:
                    continue
                triggered_channels = self._evaluate_watchdog(wd, channel_values, now)
                if triggered_channels:
                    if not wd.is_triggered:
                        if wd.last_triggered:
                            elapsed = (now - wd.last_triggered) * 1000
                            if elapsed < wd.cooldown_ms:
                                continue
                        self._trigger_watchdog(wd, triggered_channels, now)
                elif wd.is_triggered and wd.auto_recover:
                    self._recover_watchdog(wd, now)

    def _evaluate_watchdog(self, wd: Watchdog, channel_values: Dict[str, float], now: float) -> List[str]:
        triggered = []
        cond = wd.condition
        for channel in wd.channels:
            if channel not in channel_values:
                continue
            tracker = self.channel_trackers.get(channel)
            if not tracker:
                continue
            value = channel_values[channel]
            if cond.condition_type == WatchdogConditionType.STALE_DATA:
                if tracker.last_update_time:
                    age_ms = (now - tracker.last_update_time) * 1000
                    if age_ms > cond.max_stale_ms:
                        triggered.append(channel)
            elif cond.condition_type == WatchdogConditionType.OUT_OF_RANGE:
                if not math.isnan(value):
                    if cond.min_value is not None and value < cond.min_value:
                        triggered.append(channel)
                    elif cond.max_value is not None and value > cond.max_value:
                        triggered.append(channel)
            elif cond.condition_type == WatchdogConditionType.RATE_EXCEEDED:
                if cond.max_rate_per_min and len(tracker.rate_history) >= 2:
                    old_t, old_v = tracker.rate_history[0]
                    new_t, new_v = tracker.rate_history[-1]
                    if new_t > old_t:
                        rate_per_min = abs(new_v - old_v) / (new_t - old_t) * 60
                        if rate_per_min > cond.max_rate_per_min:
                            triggered.append(channel)
            elif cond.condition_type == WatchdogConditionType.STUCK_VALUE:
                if tracker.stuck_since:
                    stuck_ms = (now - tracker.stuck_since) * 1000
                    if stuck_ms > cond.stuck_duration_ms:
                        triggered.append(channel)
        return triggered

    def _trigger_watchdog(self, wd: Watchdog, triggered_channels: List[str], now: float):
        logger.warning(f"Watchdog triggered: {wd.name} on channels: {triggered_channels}")
        wd.is_triggered = True
        wd.triggered_at = now
        wd.triggered_channels = triggered_channels
        wd.last_triggered = now
        for action in wd.actions:
            try:
                self._execute_action(action, wd)
            except Exception as e:
                logger.error(f"Failed to execute watchdog action: {e}")

    def _recover_watchdog(self, wd: Watchdog, now: float):
        logger.info(f"Watchdog recovered: {wd.name}")
        wd.is_triggered = False
        wd.triggered_at = None
        wd.triggered_channels = []
        for action in wd.recovery_actions:
            try:
                self._execute_action(action, wd)
            except Exception as e:
                logger.error(f"Failed to execute watchdog recovery action: {e}")

    def _execute_action(self, action: WatchdogAction, wd: Watchdog):
        if action.action_type == WatchdogActionType.NOTIFICATION:
            if self.publish_notification:
                message = action.message or f"Watchdog '{wd.name}' triggered"
                self.publish_notification('watchdog', wd.name, message)
        elif action.action_type == WatchdogActionType.ALARM:
            if self.raise_alarm:
                message = action.message or f"Watchdog alarm: {wd.name}"
                self.raise_alarm(wd.id, action.alarm_severity, message)
        elif action.action_type == WatchdogActionType.SET_OUTPUT:
            if self.set_output and action.channel is not None:
                self.set_output(action.channel, action.value)
        elif action.action_type == WatchdogActionType.STOP_SEQUENCE:
            if self.stop_sequence and action.sequence_id:
                self.stop_sequence(action.sequence_id)
        elif action.action_type == WatchdogActionType.RUN_SEQUENCE:
            if self.run_sequence and action.sequence_id:
                self.run_sequence(action.sequence_id)

    def manual_clear(self, watchdog_id: str) -> bool:
        with self.lock:
            if watchdog_id not in self.watchdogs:
                return False
            wd = self.watchdogs[watchdog_id]
            if wd.is_triggered:
                wd.is_triggered = False
                wd.triggered_at = None
                wd.triggered_channels = []
                return True
            return False


# =============================================================================
# ENHANCED ALARM MANAGER
# =============================================================================

class AlarmSeverity(Enum):
    """Alarm severity levels (ISA-18.2 style)"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class FullAlarmState(Enum):
    """Alarm lifecycle states"""
    NORMAL = "normal"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RETURNED = "returned"
    SHELVED = "shelved"
    OUT_OF_SERVICE = "out_of_service"


class LatchBehavior(Enum):
    AUTO_CLEAR = "auto_clear"
    LATCH = "latch"
    TIMED_LATCH = "timed_latch"


@dataclass
class AlarmConfig:
    """Configuration for a single alarm point"""
    id: str
    channel: str
    name: str
    description: str = ""
    enabled: bool = True
    severity: AlarmSeverity = AlarmSeverity.MEDIUM
    high_high: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    low_low: Optional[float] = None
    deadband: float = 0.0
    on_delay_s: float = 0.0
    off_delay_s: float = 0.0
    latch_behavior: LatchBehavior = LatchBehavior.AUTO_CLEAR
    timed_latch_s: float = 60.0
    actions: List[str] = field(default_factory=list)
    safety_action: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id, 'channel': self.channel, 'name': self.name,
            'description': self.description, 'enabled': self.enabled,
            'severity': self.severity.name,
            'high_high': self.high_high, 'high': self.high,
            'low': self.low, 'low_low': self.low_low,
            'deadband': self.deadband, 'on_delay_s': self.on_delay_s,
            'off_delay_s': self.off_delay_s,
            'latch_behavior': self.latch_behavior.value,
            'timed_latch_s': self.timed_latch_s,
            'actions': self.actions, 'safety_action': self.safety_action
        }

    @staticmethod
    def from_dict(d: dict) -> 'AlarmConfig':
        return AlarmConfig(
            id=d.get('id', ''), channel=d.get('channel', ''),
            name=d.get('name', ''), description=d.get('description', ''),
            enabled=d.get('enabled', True),
            severity=AlarmSeverity[d.get('severity', 'MEDIUM')],
            high_high=d.get('high_high'), high=d.get('high'),
            low=d.get('low'), low_low=d.get('low_low'),
            deadband=d.get('deadband', 0.0),
            on_delay_s=d.get('on_delay_s', 0.0),
            off_delay_s=d.get('off_delay_s', 0.0),
            latch_behavior=LatchBehavior(d.get('latch_behavior', 'auto_clear')),
            timed_latch_s=d.get('timed_latch_s', 60.0),
            actions=d.get('actions', []),
            safety_action=d.get('safety_action')
        )


@dataclass
class ActiveAlarm:
    """Runtime state of an active alarm"""
    alarm_id: str
    channel: str
    name: str
    severity: AlarmSeverity
    state: FullAlarmState
    threshold_type: str
    threshold_value: float
    triggered_value: float
    current_value: float
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    cleared_at: Optional[datetime] = None
    sequence_number: int = 0
    is_first_out: bool = False
    shelved_at: Optional[datetime] = None
    shelved_by: Optional[str] = None
    shelve_reason: str = ""
    message: str = ""
    safety_action: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'alarm_id': self.alarm_id, 'channel': self.channel, 'name': self.name,
            'severity': self.severity.name, 'state': self.state.value,
            'threshold_type': self.threshold_type, 'threshold_value': self.threshold_value,
            'triggered_value': self.triggered_value, 'current_value': self.current_value,
            'triggered_at': self.triggered_at.isoformat(),
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'acknowledged_by': self.acknowledged_by,
            'cleared_at': self.cleared_at.isoformat() if self.cleared_at else None,
            'sequence_number': self.sequence_number, 'is_first_out': self.is_first_out,
            'shelved_at': self.shelved_at.isoformat() if self.shelved_at else None,
            'shelved_by': self.shelved_by, 'shelve_reason': self.shelve_reason,
            'message': self.message, 'safety_action': self.safety_action,
            'duration_seconds': (datetime.now() - self.triggered_at).total_seconds()
        }


class EnhancedAlarmManager:
    """Enhanced alarm management with full lifecycle support"""

    def __init__(self, publish_callback: Optional[Callable] = None):
        self.publish_callback = publish_callback
        self.lock = threading.RLock()
        self.alarm_configs: Dict[str, AlarmConfig] = {}
        self.active_alarms: Dict[str, ActiveAlarm] = {}
        self.on_delay_timers: Dict[str, float] = {}
        self.off_delay_timers: Dict[str, float] = {}
        self.timed_latch_timers: Dict[str, float] = {}
        self.value_history: Dict[str, List[tuple]] = {}
        self.alarm_sequence = 0
        self.first_out_alarm_id: Optional[str] = None
        self.cascade_start_time: Optional[float] = None
        self.CASCADE_WINDOW_S = 5.0
        self.history: List[Dict[str, Any]] = []
        self.max_history = 1000

    def add_alarm_config(self, config: AlarmConfig):
        with self.lock:
            self.alarm_configs[config.id] = config

    def remove_alarm_config(self, alarm_id: str):
        with self.lock:
            self.alarm_configs.pop(alarm_id, None)
            self.active_alarms.pop(alarm_id, None)

    def get_configs_for_channel(self, channel: str) -> List[AlarmConfig]:
        return [c for c in self.alarm_configs.values() if c.channel == channel]

    def process_value(self, channel: str, value: float, timestamp: Optional[float] = None):
        if timestamp is None:
            timestamp = time.time()
        with self.lock:
            self._update_rate_history(channel, value, timestamp)
            for config in self.get_configs_for_channel(channel):
                if not config.enabled:
                    continue
                self._evaluate_alarm(config, value, timestamp)
            self._check_timed_latches(timestamp)

    def _update_rate_history(self, channel: str, value: float, timestamp: float):
        if channel not in self.value_history:
            self.value_history[channel] = []
        self.value_history[channel].append((timestamp, value))
        cutoff = timestamp - 60.0
        self.value_history[channel] = [(t, v) for t, v in self.value_history[channel] if t >= cutoff]

    def _evaluate_alarm(self, config: AlarmConfig, value: float, timestamp: float):
        alarm_id = config.id
        current = self.active_alarms.get(alarm_id)
        condition_met, threshold_type, threshold_value = self._check_thresholds(config, value)

        if condition_met:
            self.off_delay_timers.pop(alarm_id, None)
            self.timed_latch_timers.pop(alarm_id, None)
            if current is None:
                if config.on_delay_s > 0:
                    if alarm_id not in self.on_delay_timers:
                        self.on_delay_timers[alarm_id] = timestamp
                        return
                    if timestamp - self.on_delay_timers[alarm_id] < config.on_delay_s:
                        return
                self._trigger_alarm(config, value, threshold_type, threshold_value)
                self.on_delay_timers.pop(alarm_id, None)
            elif current.state != FullAlarmState.SHELVED:
                current.current_value = value
                if current.state == FullAlarmState.RETURNED:
                    current.state = FullAlarmState.ACKNOWLEDGED if current.acknowledged_at else FullAlarmState.ACTIVE
        else:
            self.on_delay_timers.pop(alarm_id, None)
            if current is not None and current.state != FullAlarmState.SHELVED:
                if self._should_clear(config, value, current.threshold_type, current.threshold_value):
                    self._handle_clear(config, current, value, timestamp)

    def _check_thresholds(self, config: AlarmConfig, value: float) -> tuple:
        if config.high_high is not None and value >= config.high_high:
            return True, 'high_high', config.high_high
        if config.low_low is not None and value <= config.low_low:
            return True, 'low_low', config.low_low
        if config.high is not None and value >= config.high:
            return True, 'high', config.high
        if config.low is not None and value <= config.low:
            return True, 'low', config.low
        return False, None, None

    def _should_clear(self, config: AlarmConfig, value: float, threshold_type: str, threshold_value: float) -> bool:
        deadband = config.deadband
        if threshold_type in ('high_high', 'high'):
            return value < (threshold_value - deadband)
        elif threshold_type in ('low_low', 'low'):
            return value > (threshold_value + deadband)
        return True

    def _handle_clear(self, config: AlarmConfig, current: ActiveAlarm, value: float, timestamp: float):
        alarm_id = config.id
        if config.latch_behavior == LatchBehavior.AUTO_CLEAR:
            if config.off_delay_s > 0:
                if alarm_id not in self.off_delay_timers:
                    self.off_delay_timers[alarm_id] = timestamp
                if timestamp - self.off_delay_timers[alarm_id] < config.off_delay_s:
                    current.current_value = value
                    return
            self._clear_alarm(alarm_id, "Auto-cleared")
            self.off_delay_timers.pop(alarm_id, None)
        elif config.latch_behavior == LatchBehavior.LATCH:
            if current.state == FullAlarmState.ACTIVE:
                current.state = FullAlarmState.RETURNED
            current.current_value = value
            current.cleared_at = datetime.now()
        elif config.latch_behavior == LatchBehavior.TIMED_LATCH:
            if current.state == FullAlarmState.ACTIVE:
                current.state = FullAlarmState.RETURNED
                current.cleared_at = datetime.now()
            if alarm_id not in self.timed_latch_timers:
                self.timed_latch_timers[alarm_id] = timestamp
            current.current_value = value

    def _check_timed_latches(self, timestamp: float):
        expired = []
        for alarm_id, clear_time in self.timed_latch_timers.items():
            config = self.alarm_configs.get(alarm_id)
            if config and timestamp - clear_time >= config.timed_latch_s:
                expired.append(alarm_id)
        for alarm_id in expired:
            self._clear_alarm(alarm_id, "Timed latch expired")
            self.timed_latch_timers.pop(alarm_id, None)

    def _trigger_alarm(self, config: AlarmConfig, value: float, threshold_type: str, threshold_value: float):
        now = datetime.now()
        is_first_out = False
        if self.first_out_alarm_id is None or \
           (self.cascade_start_time and time.time() - self.cascade_start_time > self.CASCADE_WINDOW_S):
            self.alarm_sequence += 1
            self.first_out_alarm_id = config.id
            self.cascade_start_time = time.time()
            is_first_out = True
        self.alarm_sequence += 1
        direction = "exceeded" if threshold_type.startswith('high') else "fell below"
        message = f"{config.name} {direction} {threshold_type.replace('_', ' ')} limit: {value:.2f} (limit: {threshold_value})"
        alarm = ActiveAlarm(
            alarm_id=config.id, channel=config.channel, name=config.name,
            severity=config.severity, state=FullAlarmState.ACTIVE,
            threshold_type=threshold_type, threshold_value=threshold_value,
            triggered_value=value, current_value=value, triggered_at=now,
            sequence_number=self.alarm_sequence, is_first_out=is_first_out,
            message=message, safety_action=config.safety_action
        )
        self.active_alarms[config.id] = alarm
        self._log_event(alarm, 'triggered', value, threshold_value, None)
        self._publish_alarm(alarm)
        if config.safety_action and self.publish_callback:
            self.publish_callback('safety_action', {'action_id': config.safety_action, 'alarm_id': alarm.alarm_id})
        logger.warning(f"ALARM TRIGGERED: {message}")

    def _clear_alarm(self, alarm_id: str, reason: str = "Cleared"):
        alarm = self.active_alarms.get(alarm_id)
        if alarm is None:
            return
        self._log_event(alarm, 'cleared', alarm.current_value, alarm.threshold_value, None)
        del self.active_alarms[alarm_id]
        if alarm_id == self.first_out_alarm_id:
            self.first_out_alarm_id = None
            self.cascade_start_time = None
        self._publish_alarm_cleared(alarm_id)
        logger.info(f"ALARM CLEARED: {alarm.name} - {reason}")

    def acknowledge_alarm(self, alarm_id: str, user: str = "Unknown") -> bool:
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm and alarm.state in (FullAlarmState.ACTIVE, FullAlarmState.RETURNED):
                alarm.state = FullAlarmState.ACKNOWLEDGED
                alarm.acknowledged_at = datetime.now()
                alarm.acknowledged_by = user
                self._log_event(alarm, 'acknowledged', alarm.current_value, alarm.threshold_value, user)
                self._publish_alarm(alarm)
                return True
            return False

    def acknowledge_all(self, user: str = "Unknown") -> int:
        with self.lock:
            count = 0
            for alarm_id, alarm in list(self.active_alarms.items()):
                if alarm.state in (FullAlarmState.ACTIVE, FullAlarmState.RETURNED):
                    self.acknowledge_alarm(alarm_id, user)
                    count += 1
            return count

    def reset_alarm(self, alarm_id: str, user: str = "Unknown") -> bool:
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm:
                self._log_event(alarm, 'reset', alarm.current_value, alarm.threshold_value, user)
                self._clear_alarm(alarm_id, f"Reset by {user}")
                return True
            return False

    def shelve_alarm(self, alarm_id: str, user: str, reason: str = "", duration_s: float = 3600.0) -> bool:
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm:
                alarm.state = FullAlarmState.SHELVED
                alarm.shelved_at = datetime.now()
                alarm.shelved_by = user
                alarm.shelve_reason = reason
                self._log_event(alarm, 'shelved', alarm.current_value, alarm.threshold_value, user)
                self._publish_alarm(alarm)
                return True
            return False

    def unshelve_alarm(self, alarm_id: str, user: str) -> bool:
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm and alarm.state == FullAlarmState.SHELVED:
                alarm.state = FullAlarmState.ACKNOWLEDGED if alarm.acknowledged_at else FullAlarmState.ACTIVE
                alarm.shelved_at = None
                alarm.shelved_by = None
                alarm.shelve_reason = ""
                self._log_event(alarm, 'unshelved', alarm.current_value, alarm.threshold_value, user)
                self._publish_alarm(alarm)
                return True
            return False

    def _log_event(self, alarm: ActiveAlarm, event_type: str, value: float, threshold: float, user: Optional[str]):
        entry = {
            'timestamp': datetime.now().isoformat(), 'alarm_id': alarm.alarm_id,
            'channel': alarm.channel, 'event_type': event_type,
            'severity': alarm.severity.name, 'value': value,
            'threshold': threshold, 'user': user, 'message': alarm.message
        }
        self.history.append(entry)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def _publish_alarm(self, alarm: ActiveAlarm):
        if self.publish_callback:
            self.publish_callback('alarm', alarm.to_dict())

    def _publish_alarm_cleared(self, alarm_id: str):
        if self.publish_callback:
            self.publish_callback('alarm_cleared', {'alarm_id': alarm_id})

    def get_active_alarms(self) -> List[ActiveAlarm]:
        with self.lock:
            alarms = list(self.active_alarms.values())
            alarms.sort(key=lambda a: (a.severity.value, a.sequence_number))
            return alarms

    def get_alarm_counts(self) -> Dict[str, int]:
        with self.lock:
            counts = {'total': len(self.active_alarms), 'active': 0, 'acknowledged': 0,
                      'returned': 0, 'shelved': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
            for alarm in self.active_alarms.values():
                counts[alarm.state.value] = counts.get(alarm.state.value, 0) + 1
                counts[alarm.severity.name.lower()] = counts.get(alarm.severity.name.lower(), 0) + 1
            return counts

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.lock:
            return list(reversed(self.history[-limit:]))

    def load_config(self, config: Dict[str, Any]):
        with self.lock:
            self.alarm_configs.clear()
            for alarm_data in config.get('alarms', []):
                try:
                    ac = AlarmConfig.from_dict(alarm_data)
                    self.alarm_configs[ac.id] = ac
                except Exception as e:
                    logger.error(f"Failed to load alarm config: {e}")

    def clear_all(self):
        with self.lock:
            self.active_alarms.clear()
            self.on_delay_timers.clear()
            self.off_delay_timers.clear()
            self.timed_latch_timers.clear()
            self.first_out_alarm_id = None
            self.cascade_start_time = None


@dataclass
class CRIOConfig:
    """Configuration for cRIO node"""
    node_id: str = 'crio-001'
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883  # Standard MQTT port (matches mosquitto.conf)
    mqtt_base_topic: str = 'nisystem'
    mqtt_username: str = ''
    mqtt_password: str = ''

    scan_rate_hz: float = 4.0
    publish_rate_hz: float = 4.0  # Rate at which to publish MQTT messages (separate from scan rate)
    watchdog_timeout: float = 2.0

    channels: Dict[str, ChannelConfig] = field(default_factory=dict)
    scripts: List[Dict[str, Any]] = field(default_factory=list)
    safety_actions: Dict[str, SafetyActionConfig] = field(default_factory=dict)

    # Safe state outputs - which DO channels go LOW on watchdog expiry
    safe_state_outputs: List[str] = field(default_factory=list)


class CRIONodeService:
    """
    cRIO Node Service - runs independently on cRIO hardware
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / DEFAULT_CONFIG_FILE
        self.config: Optional[CRIOConfig] = None

        # MQTT
        self.mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_connected = threading.Event()

        # Thread control
        self._running = threading.Event()
        self._acquiring = threading.Event()

        # Channel values
        self.channel_values: Dict[str, float] = {}
        self.channel_timestamps: Dict[str, float] = {}
        self.values_lock = threading.Lock()

        # Output state
        self.output_values: Dict[str, float] = {}

        # NI-DAQmx tasks
        self.input_tasks: Dict[str, Any] = {}
        self.output_tasks: Dict[str, Any] = {}
        self.watchdog_task: Optional[Any] = None
        self._watchdog_channels: List[str] = []  # For software watchdog fallback
        self._watchdog_last_pet: float = 0.0
        self._task_swap_lock = threading.Lock()  # Lock for seamless task swap
        self._task_swap_in_progress = False  # Flag to pause scan loop during swap

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.watchdog_monitor_thread: Optional[threading.Thread] = None
        self._heartbeat_sequence = 0
        self._watchdog_triggered = False  # Prevent repeated safe state triggers

        # Script execution
        self.scripts: Dict[str, Dict[str, Any]] = {}
        self.script_threads: Dict[str, threading.Thread] = {}

        # Interactive console (IPython-like REPL) - persistent namespace
        self._console_namespace: Optional[Dict[str, Any]] = None

        # Script state persistence
        state_dir = config_dir / 'state'
        self.script_persistence = StatePersistence(state_dir / 'script_state.json')

        # Safety state tracking (for autonomous operation)
        self.safety_triggered: Dict[str, bool] = {}  # channel_name -> triggered state
        self.safety_lock = threading.Lock()

        # Alarm state tracking (ISA-18.2 - evaluated locally on cRIO)
        self.alarm_states: Dict[str, AlarmState] = {}  # channel_name -> current alarm state
        self.alarm_lock = threading.Lock()

        # Session state (for autonomous operation)
        self.session = SessionState()

        # Local safety manager (interlocks, latch state, trip logic)
        self.local_safety: Optional[LocalSafetyManager] = None

        # Status
        self.last_pc_contact = time.time()
        self.pc_connected = False
        self._last_status_time = 0.0  # For periodic status publishing
        self._last_publish_time = 0.0  # For rate-limited channel publishing
        self._start_time = time.time()  # For uptime tracking

        # Config version tracking (for PC sync)
        self.config_version = ''  # Hash of current config
        self.config_timestamp = ''  # ISO timestamp of last config update

        # Hardware info cache (detected once at startup)
        self._hardware_info: Optional[Dict[str, Any]] = None

        # =================================================================
        # NEW ENGINES (Standalone DAQ capability)
        # =================================================================

        # PID Control Engine
        self.pid_engine = PIDEngine(on_set_output=self._set_output_internal)
        self.pid_engine.set_status_callback(self._publish_pid_status)

        # Sequence Manager
        self.sequence_manager = SequenceManager()
        self.sequence_manager.on_set_output = self._set_output_internal
        self.sequence_manager.on_get_channel_value = self._get_channel_value
        self.sequence_manager.on_sequence_event = self._on_sequence_event

        # Trigger Engine
        self.trigger_engine = TriggerEngine()
        self.trigger_engine.set_output = self._set_output_internal
        self.trigger_engine.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id)
        self.trigger_engine.stop_sequence = lambda seq_id: self.sequence_manager.abort_sequence(seq_id)
        self.trigger_engine.publish_notification = self._publish_notification

        # Watchdog Engine (channel monitoring)
        self.channel_watchdog = WatchdogEngine()
        self.channel_watchdog.set_output = self._set_output_internal
        self.channel_watchdog.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id)
        self.channel_watchdog.stop_sequence = lambda seq_id: self.sequence_manager.abort_sequence(seq_id)
        self.channel_watchdog.publish_notification = self._publish_notification
        self.channel_watchdog.raise_alarm = self._raise_alarm

        # Enhanced Alarm Manager
        self.enhanced_alarm_manager = EnhancedAlarmManager(publish_callback=self._publish_alarm_event)

        # Last scan time for dt calculation
        self._last_scan_time: float = 0.0

        # Load config (if exists)
        self._load_local_config()

    # =========================================================================
    # ENGINE CALLBACK METHODS
    # =========================================================================

    def _set_output_internal(self, channel: str, value: Any) -> bool:
        """Internal callback for setting outputs from engines"""
        try:
            return self._write_output(channel, float(value))
        except Exception as e:
            logger.error(f"Failed to set output {channel}: {e}")
            return False

    def _get_channel_value(self, channel: str) -> Optional[float]:
        """Get current channel value"""
        with self.values_lock:
            return self.channel_values.get(channel)

    def _publish_pid_status(self, loop_id: str, status: Dict[str, Any]):
        """Publish PID loop status via MQTT"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_base_topic}/node/{self.config.node_id}/pid/loop/{loop_id}/status"
            try:
                self.mqtt_client.publish(topic, json.dumps(status), qos=0)
            except Exception as e:
                logger.error(f"Failed to publish PID status: {e}")

    def _on_sequence_event(self, event_type: str, sequence: Sequence):
        """Handle sequence events"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_base_topic}/node/{self.config.node_id}/sequence/event"
            try:
                self.mqtt_client.publish(topic, json.dumps({
                    'event': event_type,
                    'sequence': sequence.to_dict()
                }), qos=1)
            except Exception as e:
                logger.error(f"Failed to publish sequence event: {e}")

    def _publish_notification(self, source: str, name: str, message: str):
        """Publish notification via MQTT"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_base_topic}/node/{self.config.node_id}/notification"
            try:
                self.mqtt_client.publish(topic, json.dumps({
                    'source': source, 'name': name, 'message': message,
                    'timestamp': datetime.now().isoformat()
                }), qos=1)
            except Exception as e:
                logger.error(f"Failed to publish notification: {e}")

    def _raise_alarm(self, alarm_id: str, severity: str, message: str):
        """Raise an alarm from watchdog engine"""
        logger.warning(f"Watchdog alarm {alarm_id}: [{severity}] {message}")
        self._publish_notification('watchdog_alarm', alarm_id, message)

    def _publish_alarm_event(self, event_type: str, data: Dict[str, Any]):
        """Publish alarm event via MQTT"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_base_topic}/node/{self.config.node_id}/alarm/{event_type}"
            try:
                self.mqtt_client.publish(topic, json.dumps(data), qos=1)
            except Exception as e:
                logger.error(f"Failed to publish alarm event: {e}")

    # =========================================================================
    # CONFIGURATION PERSISTENCE
    # =========================================================================

    def _load_local_config(self):
        """Load configuration from local file (survives PC disconnect)"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)

                # Parse channels
                channels = {}
                for name, ch_data in data.get('channels', {}).items():
                    channels[name] = ChannelConfig(**ch_data)

                # Parse safety actions
                safety_actions = {}
                for name, action_data in data.get('safety_actions', {}).items():
                    safety_actions[name] = SafetyActionConfig(**action_data)

                self.config = CRIOConfig(
                    node_id=data.get('node_id', 'crio-001'),
                    mqtt_broker=data.get('mqtt_broker', 'localhost'),
                    mqtt_port=data.get('mqtt_port', 1883),
                    mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
                    mqtt_username=data.get('mqtt_username', ''),
                    mqtt_password=data.get('mqtt_password', ''),
                    scan_rate_hz=data.get('scan_rate_hz', 4.0),
                    publish_rate_hz=data.get('publish_rate_hz', 4.0),
                    watchdog_timeout=data.get('watchdog_timeout', 2.0),
                    channels=channels,
                    scripts=data.get('scripts', []),
                    safety_actions=safety_actions,
                    safe_state_outputs=data.get('safe_state_outputs', [])
                )
                logger.info(f"Loaded local config: {len(channels)} channels, "
                           f"{len(safety_actions)} safety actions")
            except Exception as e:
                logger.error(f"Failed to load local config: {e}")
                self.config = CRIOConfig()
        else:
            logger.info("No local config found - waiting for config from NISystem")
            self.config = CRIOConfig()

    def _save_local_config(self):
        """Save configuration locally (for PC disconnect survival)

        Uses atomic write pattern: write to temp file, then rename.
        This prevents corruption if power fails mid-write.
        """
        if not self.config:
            return

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Convert to serializable dict
            data = {
                'node_id': self.config.node_id,
                'mqtt_broker': self.config.mqtt_broker,
                'mqtt_port': self.config.mqtt_port,
                'mqtt_base_topic': self.config.mqtt_base_topic,
                'mqtt_username': self.config.mqtt_username,
                'mqtt_password': self.config.mqtt_password,
                'scan_rate_hz': self.config.scan_rate_hz,
                'publish_rate_hz': self.config.publish_rate_hz,
                'watchdog_timeout': self.config.watchdog_timeout,
                'channels': {name: asdict(ch) for name, ch in self.config.channels.items()},
                'scripts': self.config.scripts,
                'safety_actions': {name: asdict(action) for name, action in self.config.safety_actions.items()},
                'safe_state_outputs': self.config.safe_state_outputs
            }

            # Atomic write: write to temp file, then rename
            # This prevents corruption if power fails during write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            # Atomic rename (on POSIX systems this is atomic)
            temp_file.replace(self.config_file)

            logger.info(f"Saved config locally: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save local config: {e}")

    def _calculate_config_hash(self) -> str:
        """Calculate a hash of the current configuration for version tracking"""
        if not self.config:
            return ""

        # Create a deterministic representation of config
        config_data = {
            'channels': {name: asdict(ch) for name, ch in sorted(self.config.channels.items())},
            'safety_actions': {name: asdict(action) for name, action in sorted(self.config.safety_actions.items())},
            'watchdog_timeout': self.config.watchdog_timeout,
            'safe_state_outputs': sorted(self.config.safe_state_outputs)
        }

        config_json = json.dumps(config_data, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()

    def _validate_config(self) -> List[str]:
        """
        Validate configuration and return list of warnings/errors.

        This catches common misconfigurations before they cause runtime failures.
        """
        errors = []

        if not self.config:
            return ["No configuration loaded"]

        # Check safety action references
        for ch_name, ch_config in self.config.channels.items():
            if ch_config.safety_action:
                if ch_config.safety_action not in self.config.safety_actions:
                    errors.append(f"Channel '{ch_name}' references non-existent "
                                 f"safety action '{ch_config.safety_action}'")

        # Check safety action target channels exist
        for action_name, action in self.config.safety_actions.items():
            for target_ch in action.actions.keys():
                if target_ch not in self.config.channels:
                    errors.append(f"Safety action '{action_name}' targets "
                                 f"non-existent channel '{target_ch}'")
                else:
                    # Check target is an output
                    target_config = self.config.channels[target_ch]
                    if target_config.channel_type not in ('digital_output', 'analog_output'):
                        errors.append(f"Safety action '{action_name}' targets "
                                     f"non-output channel '{target_ch}'")

        # Check channels with limits have safety actions
        for ch_name, ch_config in self.config.channels.items():
            has_limits = (ch_config.hihi_limit is not None or ch_config.hi_limit is not None or
                         ch_config.lo_limit is not None or ch_config.lolo_limit is not None)
            if has_limits:
                if not ch_config.safety_action:
                    errors.append(f"Channel '{ch_name}' has limits but no safety action")

        # Check interlock expressions reference existing channels
        for ch_name, ch_config in self.config.channels.items():
            if ch_config.safety_interlock:
                # Extract channel names from expression (simple heuristic)
                expr = ch_config.safety_interlock
                for word in expr.replace('(', ' ').replace(')', ' ').split():
                    # Skip operators and numbers
                    if word.upper() in ('AND', 'OR', 'NOT', 'TRUE', 'FALSE'):
                        continue
                    if word in ('==', '!=', '<', '>', '<=', '>='):
                        continue
                    try:
                        float(word)
                        continue
                    except ValueError:
                        pass
                    # Assume it's a channel name
                    if word not in self.config.channels:
                        errors.append(f"Interlock for '{ch_name}' references "
                                     f"unknown channel '{word}'")

        return errors

    # =========================================================================
    # HARDWARE DETECTION
    # =========================================================================

    def _get_local_ip(self) -> str:
        """Get local IP address that can reach the MQTT broker"""
        # First try: connect to the MQTT broker to determine our local IP
        if self.config and self.config.mqtt_broker:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                # Connect to MQTT broker (doesn't send data, just gets routing info)
                s.connect((self.config.mqtt_broker, self.config.mqtt_port))
                ip = s.getsockname()[0]
                s.close()
                if ip and ip != '0.0.0.0':
                    return ip
            except Exception:
                pass

        # Fallback: try common external address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        # Last resort: hostname lookup
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip != '127.0.0.1':
                return ip
        except Exception:
            pass

        return 'unknown'

    def _detect_hardware_info(self) -> Dict[str, Any]:
        """
        Detect cRIO hardware info for status reporting.
        Caches result since hardware doesn't change at runtime.
        Includes full channel enumeration for Scan feature.

        Channel names are reported with full NI-DAQmx paths (e.g., cRIO-9056-12345678/Mod1/ai0)
        so they can be used directly when accessing this cRIO as a remote target from NISystem PC.
        """
        if self._hardware_info is not None:
            return self._hardware_info

        info = {
            'product_type': 'cRIO',
            'serial_number': '',
            'device_name': '',  # Full NI-DAQmx device name (e.g., cRIO-9056-12345678)
            'ip_address': '',  # Will be populated fresh each time in _publish_status
            'modules': []
        }

        # Try multiple methods to get cRIO serial number
        # Method 1: Read from ni-rt.ini (most reliable on NI Linux RT)
        try:
            ini_path = Path('/etc/natinst/share/ni-rt.ini')
            if ini_path.exists():
                ini_content = ini_path.read_text()
                for line in ini_content.split('\n'):
                    if line.startswith('serial=') or line.startswith('SerialNumber='):
                        serial = line.split('=', 1)[1].strip().strip('"')
                        if serial:
                            info['serial_number'] = serial
                            logger.debug(f"Got serial from ni-rt.ini: {serial}")
                            break
        except Exception as e:
            logger.debug(f"ni-rt.ini read failed: {e}")

        # Method 2: Try nisyscfg command
        if not info['serial_number']:
            try:
                result = subprocess.run(
                    ['nisyscfg', '-l'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Serial' in line and ':' in line:
                            serial = line.split(':', 1)[1].strip()
                            if serial:
                                info['serial_number'] = serial
                                logger.debug(f"Got serial from nisyscfg: {serial}")
                                break
            except Exception as e:
                logger.debug(f"nisyscfg failed: {e}")

        # Method 3: Try nilsdev command for modules and possibly serial
        try:
            result = subprocess.run(
                ['nilsdev', '--verbose'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                current_module = None
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('ProductType:'):
                        product = line.split(':', 1)[1].strip()
                        if 'cRIO' in product and info['product_type'] == 'cRIO':
                            info['product_type'] = product
                        elif current_module is not None:
                            current_module['product_type'] = product
                    elif line.startswith('DevSerialNum:') or line.startswith('SerialNum:'):
                        serial = line.split(':', 1)[1].strip()
                        if serial and not info['serial_number']:
                            info['serial_number'] = serial
                    elif line.startswith('Mod'):
                        # New module entry
                        if current_module is not None:
                            info['modules'].append(current_module)
                        mod_name = line.strip()
                        current_module = {
                            'name': mod_name,
                            'product_type': '',
                            'slot': int(mod_name.replace('Mod', '')) if mod_name.replace('Mod', '').isdigit() else 0,
                            'channels': []  # Will be populated by nidaqmx
                        }
                    elif line.startswith('CompactDAQ.SlotNum:') and current_module:
                        current_module['slot'] = int(line.split(':', 1)[1].strip())
                if current_module is not None:
                    info['modules'].append(current_module)
        except Exception as e:
            logger.debug(f"nilsdev detection failed: {e}")

        # Method 4: Use hostname as fallback (often set to serial on cRIO)
        if not info['serial_number']:
            try:
                hostname = socket.gethostname()
                # cRIO hostnames are often like "cRIO-9056-XXXXXXXX" or just the serial
                if hostname and hostname != 'localhost':
                    # If hostname contains the model, extract serial part
                    if '-' in hostname and any(c.isdigit() for c in hostname):
                        parts = hostname.split('-')
                        # Last part is often the serial
                        if len(parts) >= 2 and len(parts[-1]) >= 6:
                            info['serial_number'] = parts[-1]
                            logger.debug(f"Got serial from hostname: {parts[-1]}")
            except Exception as e:
                logger.debug(f"hostname fallback failed: {e}")

        # Use nidaqmx to enumerate physical channels for each module
        if NIDAQMX_AVAILABLE:
            try:
                system = nidaqmx.system.System.local()

                # Get device list once to avoid repeated iteration
                device_list = list(system.devices)

                # If no modules from nilsdev, get them from nidaqmx
                if not info['modules']:
                    for device in device_list:
                        if 'cRIO' in device.product_type:
                            info['product_type'] = device.product_type
                            try:
                                info['serial_number'] = str(device.dev_serial_num)
                            except Exception:
                                pass
                        elif 'NI 9' in device.product_type:
                            info['modules'].append({
                                'name': device.name,
                                'product_type': device.product_type,
                                'slot': 0,
                                'channels': []
                            })

                # Build the full device name for remote access from PC
                if info['product_type'] and info['serial_number']:
                    info['device_name'] = f"{info['product_type']}-{info['serial_number']}"
                elif info['product_type']:
                    info['device_name'] = info['product_type']

                device_prefix = info['device_name']

                # Enumerate channels for each module
                for device in device_list:
                    # Skip the cRIO chassis itself
                    if 'cRIO' in device.product_type:
                        continue

                    # Find matching module in our list
                    module = next((m for m in info['modules'] if m['name'] == device.name), None)
                    if module is None:
                        continue

                    channels = []
                    product_type = module['product_type']

                    # Analog Input channels
                    try:
                        ai_chans = list(device.ai_physical_chans)
                        category = self._get_channel_category(product_type, 'ai')
                        for ch in ai_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'analog_input',
                                'category': category
                            })
                    except Exception:
                        pass

                    # Analog Output channels
                    try:
                        ao_chans = list(device.ao_physical_chans)
                        category = self._get_channel_category(product_type, 'ao')
                        for ch in ao_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'analog_output',
                                'category': category
                            })
                    except Exception:
                        pass

                    # Digital Input lines
                    try:
                        di_lines = list(device.di_lines)
                        for ch in di_lines:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'digital_input',
                                'category': 'digital'
                            })
                    except Exception:
                        pass

                    # Digital Output lines
                    try:
                        do_lines = list(device.do_lines)
                        for ch in do_lines:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'digital_output',
                                'category': 'digital'
                            })
                    except Exception:
                        pass

                    # Counter channels
                    try:
                        ci_chans = list(device.ci_physical_chans)
                        for ch in ci_chans:
                            channels.append({
                                'name': ch.name,
                                'display_name': f"{device_prefix}/{ch.name}" if device_prefix else ch.name,
                                'channel_type': 'counter_input',
                                'category': 'counter'
                            })
                    except Exception:
                        pass

                    module['channels'] = channels

            except Exception as e:
                logger.warning(f"nidaqmx channel enumeration failed: {e}")

        # Count total channels
        total_channels = sum(len(m.get('channels', [])) for m in info['modules'])

        self._hardware_info = info
        logger.info(f"Detected hardware: {info.get('device_name', info['product_type'])} with {len(info['modules'])} modules, {total_channels} channels")
        return info

    def _get_channel_category(self, product_type: str, channel_type: str) -> str:
        """
        Determine channel category based on module type.

        Returns the signal type category (thermocouple, voltage, current, rtd, digital)
        which is separate from channel_type (analog_input, analog_output, etc.)

        Supports all C-series modules compatible with cRIO-9056.
        """
        # Extract module number from product type (e.g., "NI 9213" -> "9213")
        import re
        match = re.search(r'9\d{3}', product_type)
        module_num = match.group() if match else ''

        # =====================================================================
        # THERMOCOUPLE MODULES (AI)
        # =====================================================================
        tc_modules = ['9210', '9211', '9212', '9213', '9214', '9219']
        if module_num in tc_modules:
            return 'thermocouple'

        # =====================================================================
        # RTD / RESISTANCE MODULES (AI)
        # =====================================================================
        rtd_modules = ['9216', '9217', '9226']
        if module_num in rtd_modules:
            return 'rtd'

        # =====================================================================
        # CURRENT INPUT MODULES (AI)
        # =====================================================================
        current_in_modules = ['9203', '9207', '9208', '9227']
        if module_num in current_in_modules:
            return 'current'

        # =====================================================================
        # CURRENT OUTPUT MODULES (AO)
        # =====================================================================
        current_out_modules = ['9265', '9266']
        if module_num in current_out_modules:
            return 'current_output'

        # =====================================================================
        # STRAIN / BRIDGE MODULES (AI)
        # =====================================================================
        strain_modules = ['9235', '9236', '9237', '9219']
        if module_num in strain_modules and channel_type == 'ai':
            return 'strain'

        # =====================================================================
        # IEPE / ACCELEROMETER MODULES (AI)
        # =====================================================================
        iepe_modules = ['9230', '9231', '9232', '9234']
        if module_num in iepe_modules:
            return 'iepe'

        # =====================================================================
        # DIGITAL INPUT MODULES
        # =====================================================================
        di_modules = ['9401', '9402', '9411', '9421', '9422', '9423', '9425', '9426', '9435']
        if module_num in di_modules:
            return 'digital'

        # =====================================================================
        # DIGITAL OUTPUT MODULES
        # =====================================================================
        do_modules = ['9472', '9474', '9475', '9476', '9477', '9478']
        if module_num in do_modules:
            return 'digital'

        # =====================================================================
        # DIGITAL I/O (BIDIRECTIONAL) MODULES
        # =====================================================================
        dio_modules = ['9375', '9403']
        if module_num in dio_modules:
            return 'digital'

        # =====================================================================
        # RELAY MODULES
        # =====================================================================
        relay_modules = ['9481', '9482', '9485']
        if module_num in relay_modules:
            return 'relay'

        # =====================================================================
        # VOLTAGE INPUT MODULES (AI) - Most common, listed explicitly
        # =====================================================================
        voltage_in_modules = [
            '9201', '9202', '9205', '9206', '9215', '9220', '9221', '9222',
            '9223', '9229', '9233', '9238', '9239', '9242', '9243', '9244',
            '9246', '9247', '9250', '9251', '9252', '9253'
        ]
        if module_num in voltage_in_modules:
            return 'voltage'

        # =====================================================================
        # VOLTAGE OUTPUT MODULES (AO)
        # =====================================================================
        voltage_out_modules = ['9260', '9263', '9264', '9269']
        if module_num in voltage_out_modules:
            return 'voltage'

        # =====================================================================
        # DEFAULT FALLBACK - Based on channel type
        # =====================================================================
        if channel_type == 'ai':
            return 'voltage'
        elif channel_type == 'ao':
            return 'voltage'
        else:
            return 'unknown'

    # =========================================================================
    # MQTT TOPIC HELPERS
    # =========================================================================

    def get_topic_base(self) -> str:
        """Get node-prefixed topic base"""
        base = self.config.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.node_id if self.config else 'crio-001'
        return f"{base}/nodes/{node_id}"

    def get_topic(self, category: str, entity: str = "") -> str:
        """Build full MQTT topic"""
        base = self.get_topic_base()
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    # =========================================================================
    # MQTT CONNECTION
    # =========================================================================

    def _setup_mqtt(self):
        """Setup MQTT connection to NISystem broker"""
        if not self.config:
            return

        self.mqtt_client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"crio-{self.config.node_id}",
            clean_session=True
        )

        # Authentication
        if self.config.mqtt_username and self.config.mqtt_password:
            self.mqtt_client.username_pw_set(
                self.config.mqtt_username,
                self.config.mqtt_password
            )

        # Callbacks
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        # Last will - notify if we disconnect unexpectedly
        self.mqtt_client.will_set(
            self.get_topic('status', 'system'),
            json.dumps({'status': 'offline', 'node_type': 'crio'}),
            qos=1,
            retain=True
        )

        # Connect with retry
        self._connect_mqtt()

    def _connect_mqtt(self):
        """Connect to MQTT broker with infinite retry - never give up"""
        retry_delay = 2.0
        max_delay = 30.0  # Cap at 30 seconds
        attempt = 0

        while self._running.is_set():
            attempt += 1
            try:
                logger.info(f"Connecting to MQTT broker {self.config.mqtt_broker}:{self.config.mqtt_port} (attempt {attempt})...")
                self.mqtt_client.connect(
                    self.config.mqtt_broker,
                    self.config.mqtt_port,
                    keepalive=60
                )
                self.mqtt_client.loop_start()

                # Wait for connection
                if self._mqtt_connected.wait(timeout=10.0):
                    logger.info("MQTT connected successfully")
                    return True
                else:
                    logger.warning("MQTT connection timeout - will retry")
                    self.mqtt_client.loop_stop()
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt} failed: {e}")

            # Exponential backoff with cap
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

        return False  # Only if _running cleared (shutdown)

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connected callback"""
        if reason_code == 0:
            self._mqtt_connected.set()
            self.pc_connected = True
            self.last_pc_contact = time.time()

            # Subscribe to config and command topics
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic  # e.g., "nisystem"
            subscriptions = [
                (f"{base}/config/#", 1),      # Configuration updates
                (f"{base}/commands/#", 1),    # Output commands
                (f"{base}/script/#", 1),      # Script management
                (f"{base}/system/#", 1),      # System commands
                (f"{base}/safety/#", 1),      # Safety commands (trigger, clear)
                (f"{base}/session/#", 1),     # Session commands (start, stop)
                (f"{base}/console/#", 1),     # Interactive console (IPython-like)
                (f"{base}/discovery/#", 1),   # Discovery requests (available channels)
                # Global discovery ping - respond when PC scans for devices
                (f"{mqtt_base}/discovery/ping", 1),
            ]
            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
                logger.debug(f"Subscribed to: {topic}")

            # Publish online status
            self._publish_status()

            logger.info("MQTT connected and subscribed")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnected callback"""
        self._mqtt_connected.clear()
        self.pc_connected = False
        logger.warning(f"MQTT disconnected (reason: {reason_code}) - will attempt reconnect")
        # Stop the loop - main loop will handle reconnection
        try:
            self.mqtt_client.loop_stop()
        except Exception as e:
            logger.debug(f"Error stopping MQTT loop on disconnect: {e}")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            self.last_pc_contact = time.time()
            self.pc_connected = True

            # Route by topic
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic

            # Global discovery ping - respond immediately with full status
            if topic == f"{mqtt_base}/discovery/ping":
                logger.info("Received discovery ping - publishing status")
                self._publish_status()
                return

            if topic.startswith(f"{base}/config/"):
                self._handle_config_message(topic, payload)
            elif topic.startswith(f"{base}/commands/"):
                self._handle_command_message(topic, payload)
            elif topic.startswith(f"{base}/script/"):
                self._handle_script_message(topic, payload)
            elif topic.startswith(f"{base}/system/"):
                self._handle_system_message(topic, payload)
            elif topic.startswith(f"{base}/safety/"):
                self._handle_safety_message(topic, payload)
            elif topic.startswith(f"{base}/session/"):
                self._handle_session_message(topic, payload)
            elif topic.startswith(f"{base}/console/"):
                self._handle_console_message(topic, payload)
            elif topic.startswith(f"{base}/discovery/"):
                self._handle_discovery_message(topic, payload)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_config_message(self, topic: str, payload: Dict[str, Any]):
        """Handle configuration updates from NISystem"""
        if topic.endswith('/full'):
            # Full configuration update
            logger.info("Received full configuration update")

            try:
                # Parse channels - handle both array and dict formats
                channels = {}
                raw_channels = payload.get('channels', {})

                # If channels is a list (from frontend), convert to dict using 'name' field
                if isinstance(raw_channels, list):
                    for ch_data in raw_channels:
                        name = ch_data.get('name')
                        if name:
                            channels[name] = self._parse_channel_config(ch_data)
                else:
                    # Already a dict
                    for name, ch_data in raw_channels.items():
                        channels[name] = self._parse_channel_config(ch_data)

                # Parse safety actions
                safety_actions = {}
                raw_safety = payload.get('safety_actions', {})
                for name, action_data in raw_safety.items():
                    safety_actions[name] = SafetyActionConfig(
                        name=name,
                        description=action_data.get('description', ''),
                        actions=action_data.get('actions', {}),
                        trigger_alarm=action_data.get('trigger_alarm', False),
                        alarm_message=action_data.get('alarm_message', '')
                    )

                # Save old channels for incremental reconfiguration
                old_channels = dict(self.config.channels) if self.config.channels else {}

                # Update config
                self.config.channels = channels
                self.config.scripts = payload.get('scripts', [])
                self.config.safety_actions = safety_actions
                self.config.safe_state_outputs = payload.get('safe_state_outputs', [])
                self.config.watchdog_timeout = payload.get('watchdog_timeout', self.config.watchdog_timeout)

                # Use config version from PC if provided, otherwise calculate locally
                # (PC uses md5[:8], we use sha256 - must use PC's version for matching)
                config_hash = payload.get('config_version', '')
                if not config_hash:
                    config_hash = self._calculate_config_hash()

                # Check if config actually changed (avoid unnecessary hardware reconfig)
                config_unchanged = (config_hash == self.config_version and self.config_version)

                self.config_version = config_hash
                self.config_timestamp = datetime.now(timezone.utc).isoformat()

                # Validate configuration
                validation_errors = self._validate_config()
                if validation_errors:
                    for error in validation_errors:
                        logger.warning(f"Config validation: {error}")

                # Save locally
                self._save_local_config()

                # Reconfigure hardware only if config changed (prevents output toggling)
                # Pass old_channels for incremental reconfiguration (only changed outputs affected)
                if config_unchanged:
                    logger.info(f"Config unchanged (version: {config_hash}), skipping hardware reconfiguration")
                else:
                    self._configure_hardware(old_channels=old_channels)

                # Clear safety triggered state (config changed)
                with self.safety_lock:
                    self.safety_triggered.clear()

                # Publish acknowledgment with config hash
                self._publish(
                    self.get_topic('config', 'response'),
                    {
                        'status': 'ok',
                        'channels': len(channels),
                        'safety_actions': len(safety_actions),
                        'config_hash': config_hash,
                        'config_timestamp': self.config_timestamp,
                        'validation_warnings': validation_errors
                    }
                )
                logger.info(f"Config updated: {len(channels)} channels, "
                           f"{len(safety_actions)} safety actions, hash: {config_hash[:8]}...")

                # AUTO-START: cRIO is the PLC - start acquisition immediately after config
                if channels and not self._acquiring.is_set():
                    logger.info("Config received - auto-starting acquisition (cRIO is PLC)")
                    self._start_acquisition()

            except Exception as e:
                logger.error(f"Config update failed: {e}")
                self._publish(
                    self.get_topic('config', 'response'),
                    {
                        'status': 'error',
                        'error': str(e),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                )

        elif topic.endswith('/channel/update'):
            # Single channel update
            channel_data = payload
            name = channel_data.get('name')
            if name:
                self.config.channels[name] = self._parse_channel_config(channel_data)
                self._save_local_config()
                logger.info(f"Updated channel: {name}")

    def _parse_channel_config(self, ch_data: Dict[str, Any]) -> ChannelConfig:
        """
        Parse channel config from PC (daq_service) format to cRIO format.

        Handles:
        - Field name mapping (PC uses 'unit', cRIO uses 'engineering_units')
        - Case normalization (PC 'internal' -> cRIO 'BUILT_IN')
        - ISA-18.2 alarm fields (hihi_limit, hi_limit, lo_limit, lolo_limit)
        - Safety fields (safety_action, safety_interlock, expected_state)
        """
        # Map PC field names to cRIO field names
        field_map = {
            'unit': 'engineering_units',
        }

        # CJC source mapping (PC uses lowercase, cRIO uses NI-DAQmx constants)
        cjc_map = {
            'internal': 'BUILT_IN',
            'constant': 'CONST_VAL',
            'channel': 'CHAN',
            'built_in': 'BUILT_IN',
        }

        # Terminal config normalization (ensure uppercase)
        terminal_map = {
            'differential': 'DIFF',
            'rse': 'RSE',
            'nrse': 'NRSE',
            'pseudo_diff': 'PSEUDO_DIFF',
            'diff': 'DIFF',
        }

        # All fields that ChannelConfig accepts (matches the dataclass)
        valid_fields = {
            # Core fields
            'name', 'physical_channel', 'channel_type',
            # Type-specific settings
            'thermocouple_type', 'voltage_range', 'current_range_ma',
            'terminal_config', 'cjc_source',
            # Output settings
            'default_state', 'invert',
            # Scaling (linear, 4-20mA, and map scaling)
            'scale_slope', 'scale_offset', 'scale_type', 'engineering_units',
            'four_twenty_scaling', 'eng_units_min', 'eng_units_max',
            'pre_scaled_min', 'pre_scaled_max', 'scaled_min', 'scaled_max',
            # ISA-18.2 Alarm Configuration (full support)
            'alarm_enabled', 'hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit',
            'alarm_priority', 'alarm_deadband', 'alarm_delay_sec',
            # Safety settings
            'safety_action', 'safety_interlock', 'expected_state',
        }

        normalized = {}

        # Copy all valid fields with mapping
        for key, value in ch_data.items():
            mapped_key = field_map.get(key, key)

            # Skip fields not in ChannelConfig
            if mapped_key not in valid_fields:
                continue

            # Skip None values for optional fields
            if value is None:
                continue

            # Normalize specific fields
            if mapped_key == 'cjc_source' and isinstance(value, str):
                value = cjc_map.get(value.lower(), value.upper())
            elif mapped_key == 'terminal_config' and isinstance(value, str):
                value = terminal_map.get(value.lower(), value.upper())

            normalized[mapped_key] = value

        # Enable alarms if any limits are set (default to True if limits present)
        has_limits = any(normalized.get(f) is not None for f in ['hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit'])
        if has_limits and 'alarm_enabled' not in normalized:
            normalized['alarm_enabled'] = True

        # Ensure required fields have defaults
        if 'name' not in normalized:
            normalized['name'] = ''
        if 'physical_channel' not in normalized:
            normalized['physical_channel'] = ''
        if 'channel_type' not in normalized:
            normalized['channel_type'] = 'voltage'

        return ChannelConfig(**normalized)

    def _handle_command_message(self, topic: str, payload: Dict[str, Any]):
        """Handle commands from NISystem (device CLI and output commands)"""
        request_id = payload.get('request_id', '')
        base = self.get_topic_base()

        # Device CLI commands (ping, info, modules, firmware, reboot)
        if topic.endswith('/commands/ping'):
            self._publish(f"{base}/command/response", {
                'success': True,
                'command': 'ping',
                'request_id': request_id,
                'node_id': self.config.node_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            return

        elif topic.endswith('/commands/info'):
            hw_info = getattr(self, '_hardware_info', {})
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'info': {
                    'node_id': self.config.node_id,
                    'type': 'cRIO',
                    'product_type': hw_info.get('product_type', 'cRIO'),
                    'serial_number': hw_info.get('serial_number', 'N/A'),
                    'device_name': hw_info.get('device_name', ''),
                    'ip_address': self._get_local_ip(),
                    'channels': len(self.config.channels),
                    'modules': len(hw_info.get('modules', [])),
                    'acquiring': self._acquiring.is_set(),
                    'uptime_hours': round((time.time() - getattr(self, '_start_time', time.time())) / 3600, 1)
                }
            })
            return

        elif topic.endswith('/commands/modules'):
            hw_info = getattr(self, '_hardware_info', {})
            modules = []
            for mod in hw_info.get('modules', []):
                modules.append({
                    'slot': mod.get('slot', 0),
                    'name': mod.get('name', ''),
                    'type': mod.get('product_type', ''),
                    'channels': len(mod.get('channels', []))
                })
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'modules': modules
            })
            return

        elif topic.endswith('/commands/firmware'):
            hw_info = getattr(self, '_hardware_info', {})
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'node_software': '1.0.0',
                'product_type': hw_info.get('product_type', 'cRIO'),
                'serial_number': hw_info.get('serial_number', 'N/A'),
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                'nidaqmx_available': 'nidaqmx' in sys.modules
            })
            return

        elif topic.endswith('/commands/reboot'):
            logger.warning("Received reboot command from device CLI")
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'message': 'Reboot initiated'
            })
            # Schedule reboot after response is sent
            def do_reboot():
                time.sleep(1)
                logger.info("Executing reboot...")
                import subprocess
                subprocess.run(['reboot'], check=False)
            threading.Thread(target=do_reboot, daemon=True).start()
            return

        # Output commands
        # New format: topic ends with /commands/output, TAG name in payload
        # Old format: topic ends with /commands/{channel_name}
        if topic.endswith('/commands/output'):
            # New format - TAG name in payload (must match channel name in output_tasks)
            channel_name = payload.get('channel', '')
            value = payload.get('value')
            # PC may include physical_channel for fallback when config not pushed
            physical_channel = payload.get('physical_channel', '')
        else:
            # Old format - channel name from topic (legacy support)
            parts = topic.split('/')
            channel_name = parts[-1] if len(parts) >= 2 else ''
            value = payload.get('value')
            physical_channel = ''

        if not channel_name:
            return

        # Try to find the output task by various lookups
        task_key = None

        # 1. Direct match (works if config pushed with TAG names)
        if channel_name in self.output_tasks:
            task_key = channel_name

        # 2. Look up physical_channel from config and try that
        if not task_key and channel_name in self.config.channels:
            physical_ch = self.config.channels[channel_name].physical_channel
            if physical_ch and physical_ch in self.output_tasks:
                task_key = physical_ch
                logger.debug(f"Mapped {channel_name} -> {physical_ch} via config")

        # 3. Build reverse lookup: physical_channel -> TAG name from config
        if not task_key:
            for cfg_name, cfg in self.config.channels.items():
                if cfg.physical_channel and cfg.physical_channel in self.output_tasks:
                    if cfg_name == channel_name:
                        task_key = cfg.physical_channel
                        logger.debug(f"Reverse mapped {channel_name} -> {task_key}")
                        break

        # 4. Fallback: use physical_channel from payload directly (for when config not pushed)
        if not task_key and physical_channel and physical_channel in self.output_tasks:
            task_key = physical_channel
            logger.debug(f"Using physical_channel fallback: {channel_name} -> {physical_channel}")

        if task_key:
            # Check session output locking (prevents manual writes during session)
            if self.session.active and channel_name in self.session.locked_outputs:
                logger.warning(f"SESSION LOCKS output {channel_name} - manual write blocked")
                self._publish(f"{self.get_topic_base()}/session/blocked", {
                    'channel': channel_name,
                    'requested_value': value,
                    'reason': 'session_locked',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return  # Reject command

            # Check interlock BEFORE writing (safety first!)
            ch_config = self.config.channels.get(channel_name) or self.config.channels.get(task_key)
            if ch_config and ch_config.safety_interlock:
                if not self._check_interlock(ch_config.safety_interlock):
                    logger.warning(f"INTERLOCK BLOCKS write to {channel_name}: {ch_config.safety_interlock}")
                    self._publish_interlock_blocked(channel_name, ch_config.safety_interlock, value)
                    return  # Reject command

            success = self._write_output(task_key, value)
            logger.info(f"Output command: {channel_name} -> {task_key} = {value} (success={success})")

            # Publish acknowledgment so dashboard knows command completed
            base = self.get_topic_base()
            self._publish(f"{base}/command/ack", {
                'success': success,
                'command': 'output',
                'channel': channel_name,
                'value': value,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

            # Also publish the channel value immediately so dashboard updates
            if success and channel_name in self.output_values:
                self._publish(f"{base}/channels/{channel_name}", {
                    'value': self.output_values[channel_name],
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'quality': 'good',
                    'type': 'output'
                })
        else:
            logger.warning(f"Unknown output channel: {channel_name} (physical={physical_channel}, available: {list(self.output_tasks.keys())})")
            # Publish failure acknowledgment
            base = self.get_topic_base()
            self._publish(f"{base}/command/ack", {
                'success': False,
                'command': 'output',
                'channel': channel_name,
                'error': f"Unknown output channel: {channel_name}",
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

    def _handle_script_message(self, topic: str, payload: Dict[str, Any]):
        """Handle script commands from NISystem"""
        if topic.endswith('/add'):
            script_id = payload.get('id')
            self.scripts[script_id] = payload
            logger.info(f"Added script: {script_id}")
            self._publish_script_status()

        elif topic.endswith('/start'):
            script_id = payload.get('id')
            self._start_script(script_id)

        elif topic.endswith('/stop'):
            script_id = payload.get('id')
            self._stop_script(script_id)

        elif topic.endswith('/remove'):
            script_id = payload.get('id')
            self._stop_script(script_id)
            self.scripts.pop(script_id, None)
            logger.info(f"Removed script: {script_id}")
            self._publish_script_status()

        elif topic.endswith('/update'):
            # Update script code (does not affect running instance)
            script_id = payload.get('id')
            if script_id and script_id in self.scripts:
                if 'code' in payload:
                    self.scripts[script_id]['code'] = payload['code']
                if 'name' in payload:
                    self.scripts[script_id]['name'] = payload['name']
                if 'run_mode' in payload:
                    self.scripts[script_id]['run_mode'] = payload['run_mode']
                if 'enabled' in payload:
                    self.scripts[script_id]['enabled'] = payload['enabled']
                logger.info(f"Updated script: {script_id}")
                self._publish_script_status()

        elif topic.endswith('/reload'):
            # Hot-reload: stop running script, update code, restart
            script_id = payload.get('id')
            new_code = payload.get('code')
            self._reload_script(script_id, new_code)

    def _reload_script(self, script_id: str, new_code: str = None):
        """Hot-reload a script without losing persisted state.

        This enables live code updates while acquisition continues running.
        The script's persisted state (via persist()/restore() API) is preserved.

        Process:
        1. Script's persisted state is already on disk
        2. Stop the running script gracefully
        3. Update the code if provided
        4. Restart the script
        5. Script calls restore() to recover its state
        """
        if script_id not in self.scripts:
            logger.warning(f"Hot-reload failed: Script not found: {script_id}")
            return

        script = self.scripts[script_id]
        was_running = script_id in self.script_threads and self.script_threads[script_id].is_alive()

        logger.info(f"Hot-reload: {script.get('name', script_id)} (was_running={was_running})")

        # Step 1: Stop if running (state is already persisted to disk)
        if was_running:
            logger.info(f"Hot-reload: Stopping script for code swap")
            self._stop_script(script_id)

            # Wait for thread to stop
            thread = self.script_threads.get(script_id)
            if thread:
                thread.join(timeout=5.0)
            time.sleep(0.1)

        # Step 2: Update code if provided
        if new_code is not None:
            script['code'] = new_code
            logger.info(f"Hot-reload: Updated code for {script.get('name', script_id)}")

        # Step 3: Clear stop flag for restart
        script['_stop_requested'] = False
        script['_timeout_exceeded'] = False

        # Step 4: Restart if it was running
        if was_running:
            logger.info(f"Hot-reload: Restarting script")
            self._start_script(script_id)
            logger.info(f"Hot-reload: {script.get('name', script_id)} restarted successfully")

        self._publish_script_status()

    def _handle_system_message(self, topic: str, payload: Dict[str, Any]):
        """Handle system commands from NISystem"""
        if topic.endswith('/acquire/start'):
            self._start_acquisition()
        elif topic.endswith('/acquire/stop'):
            self._stop_acquisition()
        elif topic.endswith('/reset'):
            self._reset()
        elif topic.endswith('/safe-state'):
            self._set_safe_state(payload.get('reason', 'command'))
        elif topic.endswith('/channel/add'):
            # Dynamic channel addition (seamless task swap)
            success, message = self.add_channel_dynamic(payload)
            self._publish(f"{self.get_topic_base()}/channel/response", {
                'action': 'add',
                'success': success,
                'channel': payload.get('name', ''),
                'message': message
            })
        elif topic.endswith('/channel/remove'):
            # Dynamic channel removal (seamless task swap)
            channel_name = payload.get('name', payload.get('channel', ''))
            success = self.remove_channel_dynamic(channel_name)
            self._publish(f"{self.get_topic_base()}/channel/response", {
                'action': 'remove',
                'success': success,
                'channel': channel_name,
                'message': 'Channel removed' if success else 'Failed to remove channel'
            })
        elif topic.endswith('/channels/update'):
            # Full channel reconfiguration (seamless task swap)
            channels_data = payload.get('channels', [])
            new_channels = []
            for ch_data in channels_data:
                try:
                    ch = ChannelConfig(
                        name=ch_data['name'],
                        channel_type=ch_data.get('channel_type', 'voltage'),
                        physical_channel=ch_data.get('physical_channel', ''),
                        enabled=ch_data.get('enabled', True),
                        units=ch_data.get('units', ''),
                        min_value=ch_data.get('min_value', 0),
                        max_value=ch_data.get('max_value', 100),
                        thermocouple_type=ch_data.get('thermocouple_type', 'K'),
                        voltage_range=ch_data.get('voltage_range', 10.0),
                        terminal_config=ch_data.get('terminal_config', 'DIFF')
                    )
                    new_channels.append(ch)
                except Exception as e:
                    logger.warning(f"Invalid channel config: {e}")

            success = self.seamless_task_swap(new_channels)
            self._publish(f"{self.get_topic_base()}/channel/response", {
                'action': 'update',
                'success': success,
                'count': len(new_channels),
                'message': f'Updated {len(new_channels)} channels' if success else 'Failed to update channels'
            })

    def _handle_safety_message(self, topic: str, payload: Dict[str, Any]):
        """Handle safety-related MQTT commands"""
        if topic.endswith('/trigger'):
            # Manual safety action trigger
            self._handle_safety_trigger(payload)
        elif topic.endswith('/clear'):
            # Clear safety triggered state for a channel
            channel = payload.get('channel')
            if channel:
                with self.safety_lock:
                    if channel in self.safety_triggered:
                        del self.safety_triggered[channel]
                        logger.info(f"Cleared safety trigger state for {channel}")
        elif topic.endswith('/latch/arm'):
            # Arm the local safety latch
            if self.local_safety:
                user = payload.get('user', 'remote')
                self.local_safety.arm_latch(user)
        elif topic.endswith('/latch/disarm'):
            # Disarm the local safety latch
            if self.local_safety:
                user = payload.get('user', 'remote')
                self.local_safety.disarm_latch(user)
        elif topic.endswith('/trip/reset'):
            # Reset trip state
            if self.local_safety:
                user = payload.get('user', 'remote')
                self.local_safety.reset_trip(user)
        elif topic.endswith('/status/request'):
            # Publish current safety status
            self._publish_safety_status()
        elif topic.endswith('/interlock/sync'):
            # Sync an interlock from PC
            if self.local_safety:
                interlock = LocalInterlockConfig(
                    id=payload.get('id', ''),
                    name=payload.get('name', ''),
                    enabled=payload.get('enabled', True),
                    conditions=payload.get('conditions', []),
                    condition_logic=payload.get('conditionLogic', 'AND'),
                    output_channels=payload.get('outputChannels', [])
                )
                self.local_safety.add_interlock(interlock)
        elif topic.endswith('/interlock/remove'):
            # Remove an interlock
            if self.local_safety:
                interlock_id = payload.get('id')
                if interlock_id:
                    self.local_safety.remove_interlock(interlock_id)

    def _publish_safety_status(self):
        """Publish current local safety status"""
        if self.local_safety:
            status = self.local_safety.get_status()
            status['nodeId'] = self.config.node_id
            self._publish(f"{self.get_topic_base()}/safety/status", status)

    def _handle_session_message(self, topic: str, payload: Dict[str, Any]):
        """Handle session commands from NISystem"""
        if topic.endswith('/start'):
            self._start_session(payload)
        elif topic.endswith('/stop'):
            self._stop_session(payload.get('reason', 'command'))
        elif topic.endswith('/ping'):
            # Session keepalive from PC - update last contact
            self.last_pc_contact = time.time()
            self._publish_session_status()

    def _start_session(self, payload: Dict[str, Any]):
        """Start a test session"""
        if self.session.active:
            logger.warning("Session already active - ignoring start command")
            return

        self.session.active = True
        self.session.start_time = time.time()
        self.session.name = payload.get('name', '')
        self.session.operator = payload.get('operator', '')
        self.session.locked_outputs = payload.get('locked_outputs', [])
        self.session.timeout_minutes = payload.get('timeout_minutes', 0)

        logger.info(f"SESSION STARTED: {self.session.name} by {self.session.operator}")
        logger.info(f"  Locked outputs: {self.session.locked_outputs}")

        self._publish_session_status()

        # Auto-start scripts with run_mode='session'
        self._auto_start_scripts('session')

    def _stop_session(self, reason: str = 'command'):
        """Stop the current session"""
        if not self.session.active:
            return

        duration = time.time() - (self.session.start_time or time.time())
        logger.info(f"SESSION STOPPED: {self.session.name} after {duration:.1f}s (reason: {reason})")

        # Auto-stop session scripts
        self._auto_stop_scripts('session')

        self.session.active = False
        self.session.locked_outputs = []
        self.session.start_time = None

        self._publish_session_status()

    def _publish_session_status(self):
        """Publish session state"""
        self._publish(f"{self.get_topic_base()}/session/status", {
            'active': self.session.active,
            'name': self.session.name,
            'operator': self.session.operator,
            'start_time': self.session.start_time,
            'duration_s': time.time() - self.session.start_time if self.session.start_time else 0,
            'locked_outputs': self.session.locked_outputs,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _publish_config_response(self, request_type: str, success: bool,
                                   data: Optional[Dict[str, Any]] = None,
                                   error: Optional[str] = None):
        """
        Publish config operation response.

        Uses unified API format matching DAQ Service for frontend compatibility.
        """
        payload = {
            'request_type': request_type,
            'success': success,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        if data:
            payload['data'] = data
        if error:
            payload['error'] = error

        self._publish(f"{self.get_topic_base()}/config/response", payload, qos=1)

    def _check_session_timeout(self):
        """Check if session has timed out (PC disconnect protection)"""
        if not self.session.active:
            return

        if self.session.timeout_minutes > 0 and self.session.start_time:
            elapsed = time.time() - self.session.start_time
            if elapsed > self.session.timeout_minutes * 60:
                logger.warning(f"Session timeout after {elapsed/60:.1f} minutes")
                self._stop_session('timeout')

    # =========================================================================
    # INTERACTIVE CONSOLE (IPython-like REPL with Persistent Namespace)
    # =========================================================================

    # Names that are part of the base API (not user-defined variables)
    _CONSOLE_BUILTINS = {
        # Core API
        'tags', 'outputs', 'session', 'time', 'math', 'datetime', 'json',
        'np', 'numpy', 'scipy', 'statistics', 're',
        # Math builtins
        'abs', 'min', 'max', 'sum', 'round', 'pow',
        'sin', 'cos', 'tan', 'sqrt', 'log', 'log10', 'pi', 'e',
        # Python builtins
        'print', 'len', 'range', 'list', 'dict', 'tuple', 'set',
        'str', 'int', 'float', 'bool', 'True', 'False', 'None',
        'sorted', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
        'isinstance', 'type', 'dir', 'help', 'getattr', 'setattr', 'hasattr',
        '__builtins__', '__name__', '__doc__',
        # Helper classes
        'RateCalculator', 'Accumulator', 'EdgeDetector', 'RollingStats', 'Scheduler',
        # Unit conversion functions
        'F_to_C', 'C_to_F', 'GPM_to_LPM', 'LPM_to_GPM', 'PSI_to_bar', 'bar_to_PSI',
        'gal_to_L', 'L_to_gal', 'BTU_to_kJ', 'kJ_to_BTU', 'lb_to_kg', 'kg_to_lb',
        # Time utility functions
        'now', 'now_ms', 'now_iso', 'time_of_day', 'elapsed_since', 'format_timestamp',
    }

    def _get_console_namespace(self) -> dict:
        """Get or create the persistent console namespace."""
        if self._console_namespace is None:
            self._console_namespace = self._build_console_namespace()
        return self._console_namespace

    def _handle_console_message(self, topic: str, payload: Dict[str, Any]):
        """Handle interactive console commands"""
        if topic.endswith('/execute'):
            self._handle_console_execute(payload)
        elif topic.endswith('/variables'):
            self._handle_console_variables(payload)
        elif topic.endswith('/complete'):
            self._handle_console_complete(payload)
        elif topic.endswith('/reset'):
            self._handle_console_reset(payload)

    def _handle_discovery_message(self, topic: str, payload: Dict[str, Any]):
        """Handle discovery requests (available channels, etc.)"""
        if topic.endswith('/channels'):
            self._publish_available_channels()

    def _publish_available_channels(self):
        """
        Publish available physical channels from this cRIO node.

        This allows the frontend to show a dropdown of available channels
        when manually adding channels from a remote cRIO node.
        """
        base = self.get_topic_base()

        # Get hardware info (this includes enumerated channels)
        if not self._hardware_info:
            self._detect_hardware()

        # Build flat list of available channels with their types
        available_channels = []
        used_physical_channels = {ch.physical_channel for ch in self.channels.values() if ch.physical_channel}

        for module in self._hardware_info.get('modules', []):
            module_name = module.get('name', '')
            module_type = module.get('product_type', '')

            for ch in module.get('channels', []):
                physical_name = ch.get('name', '')
                display_name = ch.get('display_name', physical_name)
                channel_type = ch.get('channel_type', 'unknown')
                category = ch.get('category', channel_type)

                # Mark if already in use
                in_use = physical_name in used_physical_channels

                # Map generic types to specific types based on module
                specific_type = self._map_channel_type(channel_type, category, module_type)

                available_channels.append({
                    'physical_channel': physical_name,
                    'display_name': display_name,
                    'channel_type': specific_type,
                    'category': category,
                    'module': module_name,
                    'module_type': module_type,
                    'in_use': in_use,
                    'used_by': self._get_channel_using_physical(physical_name) if in_use else None
                })

        # Publish response
        self._publish(f"{base}/discovery/channels/response", {
            'node_id': self.config.node_id,
            'node_type': 'crio',
            'device_name': self._hardware_info.get('device_name', ''),
            'channels': available_channels,
            'total_available': len([c for c in available_channels if not c['in_use']]),
            'total_in_use': len([c for c in available_channels if c['in_use']]),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

        logger.info(f"Published {len(available_channels)} available channels for discovery")

    def _map_channel_type(self, generic_type: str, category: str, module_type: str) -> str:
        """Map generic channel types to specific types based on module."""
        # NI Module type mapping for common modules
        module_type_lower = module_type.lower()

        if 'analog_input' in generic_type or category == 'ai':
            # Thermocouples
            if '9213' in module_type or '9211' in module_type or '9212' in module_type:
                return 'thermocouple'
            # RTD
            if '9217' in module_type or '9226' in module_type:
                return 'rtd'
            # Current input
            if '9203' in module_type or '9227' in module_type:
                return 'current_input'
            # Voltage input (default for analog input)
            return 'voltage_input'

        if 'analog_output' in generic_type or category == 'ao':
            # Current output
            if '9265' in module_type:
                return 'current_output'
            # Voltage output (default for analog output)
            return 'voltage_output'

        if 'digital_input' in generic_type:
            return 'digital_input'

        if 'digital_output' in generic_type:
            return 'digital_output'

        if 'counter' in generic_type:
            return 'counter'

        return generic_type

    def _get_channel_using_physical(self, physical_channel: str) -> Optional[str]:
        """Get the tag name using a physical channel."""
        for name, ch in self.channels.items():
            if getattr(ch, 'physical_channel', '') == physical_channel:
                return name
        return None

    def _handle_console_execute(self, payload: dict) -> None:
        """Execute a single Python command from the interactive console widget."""
        code = payload.get('code', '').strip()
        if not code:
            return

        base = self.get_topic_base()
        result = {'success': False, 'output': '', 'result': '', 'error': ''}

        # Handle magic commands
        if code.startswith('%'):
            result = self._handle_magic_command(code)
            self._publish(f"{base}/console/result", result)
            return

        try:
            import io
            import contextlib

            # Capture stdout
            stdout_capture = io.StringIO()

            # Get persistent namespace
            namespace = self._get_console_namespace()

            # Execute with stdout capture
            with contextlib.redirect_stdout(stdout_capture):
                try:
                    compiled = compile(code, '<console>', 'eval')
                    exec_result = eval(compiled, namespace)
                    result['result'] = repr(exec_result) if exec_result is not None else ''
                except SyntaxError:
                    compiled = compile(code, '<console>', 'exec')
                    exec(compiled, namespace)
                    result['result'] = ''

            result['output'] = stdout_capture.getvalue()
            result['success'] = True

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False
            logger.debug(f"Console error: {e}")

        self._publish(f"{base}/console/result", result)

    def _handle_magic_command(self, code: str) -> dict:
        """Handle IPython-like magic commands."""
        result = {'success': True, 'output': '', 'result': '', 'error': ''}

        parts = code.split(None, 1)
        magic = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''

        try:
            if magic == '%who':
                namespace = self._get_console_namespace()
                user_vars = [k for k in namespace.keys() if k not in self._CONSOLE_BUILTINS]
                if user_vars:
                    result['output'] = '  '.join(sorted(user_vars)) + '\n'
                else:
                    result['output'] = 'No user-defined variables.\n'

            elif magic == '%whos':
                namespace = self._get_console_namespace()
                user_vars = {k: v for k, v in namespace.items() if k not in self._CONSOLE_BUILTINS}
                if user_vars:
                    lines = ['Variable     Type        Value']
                    lines.append('-' * 50)
                    for name, value in sorted(user_vars.items()):
                        type_name = type(value).__name__
                        val_str = repr(value)
                        if len(val_str) > 30:
                            val_str = val_str[:27] + '...'
                        lines.append(f'{name:<12} {type_name:<10} {val_str}')
                    result['output'] = '\n'.join(lines) + '\n'
                else:
                    result['output'] = 'No user-defined variables.\n'

            elif magic == '%reset':
                self._console_namespace = None
                result['output'] = 'Namespace reset. All user variables cleared.\n'

            elif magic == '%time':
                if not args:
                    result['error'] = 'Usage: %time <statement>'
                    result['success'] = False
                else:
                    import io
                    import contextlib

                    namespace = self._get_console_namespace()
                    stdout_capture = io.StringIO()

                    start = time.perf_counter()
                    with contextlib.redirect_stdout(stdout_capture):
                        try:
                            compiled = compile(args, '<console>', 'eval')
                            exec_result = eval(compiled, namespace)
                        except SyntaxError:
                            compiled = compile(args, '<console>', 'exec')
                            exec(compiled, namespace)
                            exec_result = None
                    elapsed = time.perf_counter() - start

                    output = stdout_capture.getvalue()
                    if output:
                        result['output'] = output

                    if elapsed < 0.001:
                        time_str = f'{elapsed * 1000000:.1f} us'
                    elif elapsed < 1:
                        time_str = f'{elapsed * 1000:.2f} ms'
                    else:
                        time_str = f'{elapsed:.3f} s'

                    result['result'] = f'Wall time: {time_str}'
                    if exec_result is not None:
                        result['result'] += f'\nResult: {repr(exec_result)}'

            elif magic == '%vars':
                return self._handle_magic_command('%whos')

            elif magic == '%store':
                result = self._handle_store_command(args)

            elif magic == '%help':
                help_text = """Available magic commands:
  %who     - List user-defined variable names
  %whos    - Detailed variable list (name, type, value)
  %vars    - Alias for %whos
  %reset   - Clear all user-defined variables
  %time    - Time execution of a statement
  %store   - Persist variables across sessions
             %store          - List stored variables
             %store x y      - Store variables x and y
             %store -r       - Restore all stored variables
             %store -r x     - Restore variable x
             %store -d x     - Delete stored variable x
             %store -z       - Clear all stored variables
  %help    - Show this help message

Available APIs:
  tags     - Read channel values: tags.Temperature or tags['Temperature']
  outputs  - Set outputs: outputs.set('Relay1', True)
  session  - Session state: session.active

Helper classes:
  RateCalculator, Accumulator, EdgeDetector, RollingStats, Scheduler

Unit conversions:
  F_to_C, C_to_F, GPM_to_LPM, LPM_to_GPM, PSI_to_bar, bar_to_PSI, etc.

Time functions:
  now, now_ms, now_iso, time_of_day, elapsed_since, format_timestamp
"""
                result['output'] = help_text

            else:
                result['error'] = f"Unknown magic command: {magic}\nType %help for available commands."
                result['success'] = False

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False

        return result

    def _handle_store_command(self, args: str) -> dict:
        """Handle %store magic command for persisting variables.

        Like Spyder's %store:
        - %store          - List stored variables
        - %store x y      - Store variables x and y
        - %store -r       - Restore all stored variables
        - %store -r x     - Restore variable x
        - %store -d x     - Delete stored variable x
        - %store -z       - Clear all stored variables
        """
        import pickle
        import base64
        from pathlib import Path

        result = {'success': True, 'output': '', 'result': '', 'error': ''}

        # Storage file location - use data directory on cRIO
        data_dir = Path('/home/admin/nisystem/data')
        store_file = data_dir / 'console_store.json'

        # Load existing stored data
        stored_data = {}
        if store_file.exists():
            try:
                with open(store_file, 'r') as f:
                    stored_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load stored variables: {e}")

        def save_store():
            """Save stored data to file"""
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                with open(store_file, 'w') as f:
                    json.dump(stored_data, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save stored variables: {e}")

        def serialize_value(value):
            """Serialize a Python value to storable format"""
            # Try JSON first for simple types
            try:
                json.dumps(value)
                return {'type': 'json', 'data': value}
            except (TypeError, ValueError):
                pass

            # Fall back to pickle for complex types (numpy arrays, etc.)
            try:
                pickled = pickle.dumps(value)
                return {'type': 'pickle', 'data': base64.b64encode(pickled).decode('ascii')}
            except Exception as e:
                raise ValueError(f"Cannot serialize: {e}")

        def deserialize_value(stored):
            """Deserialize a stored value back to Python"""
            if stored['type'] == 'json':
                return stored['data']
            elif stored['type'] == 'pickle':
                pickled = base64.b64decode(stored['data'])
                return pickle.loads(pickled)
            else:
                raise ValueError(f"Unknown storage type: {stored['type']}")

        args_parts = args.split()
        namespace = self._get_console_namespace()

        try:
            if not args_parts:
                # List stored variables
                if not stored_data:
                    result['output'] = 'No stored variables.\n'
                else:
                    lines = ['Stored variables:']
                    for name, info in sorted(stored_data.items()):
                        type_hint = info.get('type_hint', 'unknown')
                        lines.append(f'  {name} ({type_hint})')
                    result['output'] = '\n'.join(lines) + '\n'

            elif args_parts[0] == '-r':
                # Restore variables
                var_names = args_parts[1:] if len(args_parts) > 1 else list(stored_data.keys())

                if not var_names:
                    result['output'] = 'No stored variables to restore.\n'
                else:
                    restored = []
                    for name in var_names:
                        if name in stored_data:
                            try:
                                value = deserialize_value(stored_data[name])
                                namespace[name] = value
                                restored.append(name)
                            except Exception as e:
                                result['output'] += f"Failed to restore '{name}': {e}\n"
                        else:
                            result['output'] += f"Variable '{name}' not found in store.\n"

                    if restored:
                        result['output'] += f"Restored: {', '.join(restored)}\n"

            elif args_parts[0] == '-d':
                # Delete stored variables
                if len(args_parts) < 2:
                    result['error'] = 'Usage: %store -d <varname>'
                    result['success'] = False
                else:
                    deleted = []
                    for name in args_parts[1:]:
                        if name in stored_data:
                            del stored_data[name]
                            deleted.append(name)
                        else:
                            result['output'] += f"Variable '{name}' not in store.\n"

                    if deleted:
                        save_store()
                        result['output'] += f"Deleted from store: {', '.join(deleted)}\n"

            elif args_parts[0] == '-z':
                # Clear all stored variables
                count = len(stored_data)
                stored_data.clear()
                save_store()
                result['output'] = f'Cleared {count} stored variable(s).\n'

            else:
                # Store variables
                stored = []
                for name in args_parts:
                    if name.startswith('-'):
                        result['error'] = f"Unknown option: {name}"
                        result['success'] = False
                        return result

                    if name not in namespace:
                        result['output'] += f"Variable '{name}' not found in namespace.\n"
                        continue

                    if name in self._CONSOLE_BUILTINS:
                        result['output'] += f"Cannot store built-in '{name}'.\n"
                        continue

                    try:
                        value = namespace[name]
                        stored_data[name] = serialize_value(value)
                        stored_data[name]['type_hint'] = type(value).__name__
                        stored.append(name)
                    except ValueError as e:
                        result['output'] += f"Cannot store '{name}': {e}\n"

                if stored:
                    save_store()
                    result['output'] += f"Stored: {', '.join(stored)}\n"

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['success'] = False

        return result

    def _handle_console_variables(self, payload: dict) -> None:
        """Return list of variables in the console namespace for Variable Explorer."""
        base = self.get_topic_base()

        try:
            namespace = self._get_console_namespace()
            variables = []

            for name, value in namespace.items():
                if name in self._CONSOLE_BUILTINS:
                    continue

                var_info = {
                    'name': name,
                    'type': type(value).__name__,
                    'value': None,
                    'size': None,
                    'shape': None,
                    'dtype': None,
                }

                try:
                    if hasattr(value, 'shape') and hasattr(value, 'dtype'):
                        var_info['shape'] = list(value.shape)
                        var_info['dtype'] = str(value.dtype)
                        var_info['size'] = value.nbytes if hasattr(value, 'nbytes') else None
                        if value.size <= 10:
                            var_info['value'] = value.tolist()
                        else:
                            var_info['value'] = f'array({value.shape}, dtype={value.dtype})'
                    elif isinstance(value, (list, tuple)):
                        var_info['size'] = len(value)
                        if len(value) <= 10:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = f'{type(value).__name__}[{len(value)} items]'
                    elif isinstance(value, dict):
                        var_info['size'] = len(value)
                        if len(value) <= 5:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = f'dict({len(value)} keys)'
                    elif isinstance(value, str):
                        var_info['size'] = len(value)
                        if len(value) <= 50:
                            var_info['value'] = repr(value)
                        else:
                            var_info['value'] = repr(value[:47] + '...')
                    else:
                        var_info['value'] = repr(value)
                        if len(str(var_info['value'])) > 100:
                            var_info['value'] = str(var_info['value'])[:97] + '...'
                except Exception:
                    var_info['value'] = '<error reading value>'

                variables.append(var_info)

            variables.sort(key=lambda v: v['name'])

            self._publish(f"{base}/console/variables/result", {'success': True, 'variables': variables})

        except Exception as e:
            self._publish(f"{base}/console/variables/result", {'success': False, 'error': str(e), 'variables': []})

    def _handle_console_complete(self, payload: dict) -> None:
        """Provide tab completion suggestions for console input."""
        base = self.get_topic_base()
        text = payload.get('text', '')
        cursor_pos = payload.get('cursor_pos', len(text))

        try:
            completions = []

            word_start = cursor_pos
            while word_start > 0 and text[word_start - 1] not in ' \t\n.([{=+-*/%<>!&|^~,':
                word_start -= 1
            partial = text[word_start:cursor_pos]

            if word_start > 0 and text[word_start - 1] == '.':
                obj_end = word_start - 1
                obj_start = obj_end
                while obj_start > 0 and text[obj_start - 1] not in ' \t\n([{=+-*/%<>!&|^~,':
                    obj_start -= 1
                obj_name = text[obj_start:obj_end]

                namespace = self._get_console_namespace()
                if obj_name in namespace:
                    obj = namespace[obj_name]
                    for attr in dir(obj):
                        if not attr.startswith('_') and attr.lower().startswith(partial.lower()):
                            completions.append({
                                'text': attr,
                                'type': 'attribute',
                                'start': word_start,
                                'end': cursor_pos
                            })
            else:
                namespace = self._get_console_namespace()
                for name in namespace.keys():
                    if name.lower().startswith(partial.lower()) and not name.startswith('_'):
                        comp_type = 'variable'
                        if callable(namespace[name]):
                            comp_type = 'function'
                        elif name in ('tags', 'outputs', 'session'):
                            comp_type = 'api'
                        completions.append({
                            'text': name,
                            'type': comp_type,
                            'start': word_start,
                            'end': cursor_pos
                        })

                keywords = ['if', 'else', 'elif', 'for', 'while', 'try', 'except',
                           'finally', 'with', 'def', 'class', 'return', 'yield',
                           'import', 'from', 'as', 'lambda', 'and', 'or', 'not',
                           'in', 'is', 'True', 'False', 'None', 'pass', 'break',
                           'continue', 'raise', 'assert', 'del', 'global', 'nonlocal']
                for kw in keywords:
                    if kw.lower().startswith(partial.lower()):
                        completions.append({
                            'text': kw,
                            'type': 'keyword',
                            'start': word_start,
                            'end': cursor_pos
                        })

            completions.sort(key=lambda c: c['text'].lower())
            completions = completions[:50]

            self._publish(f"{base}/console/complete/result", {'success': True, 'completions': completions})

        except Exception as e:
            self._publish(f"{base}/console/complete/result", {'success': False, 'error': str(e), 'completions': []})

    def _handle_console_reset(self, payload: dict) -> None:
        """Reset the console namespace."""
        base = self.get_topic_base()
        self._console_namespace = None
        self._publish(f"{base}/console/result", {
            'success': True,
            'output': 'Namespace reset. All user variables cleared.\n',
            'result': '',
            'error': ''
        })

    def _build_console_namespace(self) -> dict:
        """Build the initial namespace for console commands."""
        import math
        from datetime import datetime

        service = self

        class TagsAPI:
            def __init__(self, svc):
                self._service = svc

            def __getattr__(self, name: str):
                return self._service.channel_values.get(name, 0.0)

            def __getitem__(self, name: str):
                return self._service.channel_values.get(name, 0.0)

            def keys(self):
                return list(self._service.channel_values.keys())

            def values(self):
                return list(self._service.channel_values.values())

            def items(self):
                return list(self._service.channel_values.items())

            def get(self, name: str, default=0.0):
                return self._service.channel_values.get(name, default)

            def __repr__(self):
                return f'<TagsAPI: {len(self.keys())} channels>'

        class OutputsAPI:
            def __init__(self, svc):
                self._service = svc

            def set(self, channel: str, value):
                self._service._write_output(channel, value)

            def __setitem__(self, name: str, value):
                self.set(name, value)

            def __repr__(self):
                return '<OutputsAPI: outputs.set(channel, value)>'

        class SessionAPI:
            def __init__(self, svc):
                self._service = svc

            @property
            def active(self):
                return self._service.session.active

            @property
            def elapsed(self):
                if self._service.session.start_time:
                    return time.time() - self._service.session.start_time
                return 0.0

            def __repr__(self):
                return f'<SessionAPI: active={self.active}>'

        namespace = {
            'tags': TagsAPI(service),
            'outputs': OutputsAPI(service),
            'session': SessionAPI(service),
            'time': time,
            'math': math,
            'datetime': datetime,
            'json': json,
            're': __import__('re'),
            'statistics': __import__('statistics'),
            'abs': abs, 'min': min, 'max': max, 'sum': sum,
            'round': round, 'pow': pow,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'sqrt': math.sqrt, 'log': math.log, 'log10': math.log10,
            'pi': math.pi, 'e': math.e,
            'print': print,
            'len': len, 'range': range, 'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
            'str': str, 'int': int, 'float': float, 'bool': bool,
            'True': True, 'False': False, 'None': None,
            'sorted': sorted, 'enumerate': enumerate, 'zip': zip,
            'map': map, 'filter': filter, 'any': any, 'all': all,
            'isinstance': isinstance, 'type': type, 'dir': dir, 'help': help,
            'getattr': getattr, 'setattr': setattr, 'hasattr': hasattr,
        }

        try:
            import numpy as np
            namespace['np'] = np
            namespace['numpy'] = np
        except ImportError:
            pass

        try:
            import scipy
            namespace['scipy'] = scipy
        except ImportError:
            pass

        # =====================================================================
        # Helper Classes (available in console for interactive use)
        # =====================================================================

        class RateCalculator:
            """Calculate rate of change over a time window."""
            def __init__(self, window_seconds: float = 60.0):
                self.window_seconds = window_seconds
                self._history = []

            def update(self, value: float) -> float:
                """Update with new value and return rate (units per second)."""
                now = time.time()
                self._history.append((now, value))
                cutoff = now - self.window_seconds
                self._history = [(t, v) for t, v in self._history if t >= cutoff]
                if len(self._history) < 2:
                    return 0.0
                t0, v0 = self._history[0]
                t1, v1 = self._history[-1]
                dt = t1 - t0
                return (v1 - v0) / dt if dt > 0 else 0.0

            def reset(self):
                self._history.clear()

        class Accumulator:
            """Track cumulative totals from counter values."""
            def __init__(self, initial: float = 0.0):
                self._total = initial
                self._last_value = None

            def update(self, value: float) -> float:
                if self._last_value is not None:
                    delta = value - self._last_value
                    if delta < 0:
                        delta = value
                    self._total += delta
                self._last_value = value
                return self._total

            def reset(self, initial: float = 0.0):
                self._total = initial
                self._last_value = None

            @property
            def total(self) -> float:
                return self._total

        class EdgeDetector:
            """Detect rising and falling edges."""
            def __init__(self, threshold: float = 0.5):
                self.threshold = threshold
                self._last_state = None

            def update(self, value: float) -> tuple:
                current_state = value > self.threshold
                rising = falling = False
                if self._last_state is not None:
                    rising = current_state and not self._last_state
                    falling = not current_state and self._last_state
                self._last_state = current_state
                return (rising, falling, current_state)

            def reset(self):
                self._last_state = None

        class RollingStats:
            """Calculate running statistics over a sample window."""
            def __init__(self, window_size: int = 100):
                self.window_size = window_size
                self._buffer = []

            def update(self, value: float) -> dict:
                self._buffer.append(value)
                if len(self._buffer) > self.window_size:
                    self._buffer = self._buffer[-self.window_size:]
                if not self._buffer:
                    return {'mean': 0, 'min': 0, 'max': 0, 'std': 0, 'count': 0}
                n = len(self._buffer)
                mean = sum(self._buffer) / n
                min_val = min(self._buffer)
                max_val = max(self._buffer)
                if n > 1:
                    variance = sum((x - mean) ** 2 for x in self._buffer) / (n - 1)
                    std = variance ** 0.5
                else:
                    std = 0.0
                return {'mean': mean, 'min': min_val, 'max': max_val, 'std': std, 'count': n}

            def reset(self):
                self._buffer.clear()

        class Scheduler:
            """Simple job scheduler for timed operations."""
            def __init__(self):
                self._jobs = {}

            def add_interval(self, job_id: str, func, seconds: float = 0,
                           minutes: float = 0, hours: float = 0):
                interval = seconds + (minutes * 60) + (hours * 3600)
                self._jobs[job_id] = {
                    'type': 'interval', 'func': func, 'interval': interval,
                    'last_run': 0, 'paused': False, 'run_count': 0
                }

            def tick(self):
                now = time.time()
                for job_id, job in self._jobs.items():
                    if job['paused']:
                        continue
                    if job['type'] == 'interval':
                        if now - job['last_run'] >= job['interval']:
                            try:
                                job['func']()
                                job['run_count'] += 1
                            except Exception as e:
                                logger.debug(f"Scheduler job {job_id} error: {e}")
                            job['last_run'] = now

            def pause(self, job_id: str):
                if job_id in self._jobs:
                    self._jobs[job_id]['paused'] = True

            def resume(self, job_id: str):
                if job_id in self._jobs:
                    self._jobs[job_id]['paused'] = False

            def remove(self, job_id: str):
                self._jobs.pop(job_id, None)

        namespace.update({
            'RateCalculator': RateCalculator,
            'Accumulator': Accumulator,
            'EdgeDetector': EdgeDetector,
            'RollingStats': RollingStats,
            'Scheduler': Scheduler,
        })

        # =====================================================================
        # Unit Conversion Functions
        # =====================================================================

        def F_to_C(f: float) -> float:
            return (f - 32) * 5 / 9

        def C_to_F(c: float) -> float:
            return c * 9 / 5 + 32

        def GPM_to_LPM(gpm: float) -> float:
            return gpm * 3.78541

        def LPM_to_GPM(lpm: float) -> float:
            return lpm / 3.78541

        def PSI_to_bar(psi: float) -> float:
            return psi * 0.0689476

        def bar_to_PSI(bar: float) -> float:
            return bar / 0.0689476

        def gal_to_L(gal: float) -> float:
            return gal * 3.78541

        def L_to_gal(l: float) -> float:
            return l / 3.78541

        def BTU_to_kJ(btu: float) -> float:
            return btu * 1.05506

        def kJ_to_BTU(kj: float) -> float:
            return kj / 1.05506

        def lb_to_kg(lb: float) -> float:
            return lb * 0.453592

        def kg_to_lb(kg: float) -> float:
            return kg / 0.453592

        namespace.update({
            'F_to_C': F_to_C, 'C_to_F': C_to_F,
            'GPM_to_LPM': GPM_to_LPM, 'LPM_to_GPM': LPM_to_GPM,
            'PSI_to_bar': PSI_to_bar, 'bar_to_PSI': bar_to_PSI,
            'gal_to_L': gal_to_L, 'L_to_gal': L_to_gal,
            'BTU_to_kJ': BTU_to_kJ, 'kJ_to_BTU': kJ_to_BTU,
            'lb_to_kg': lb_to_kg, 'kg_to_lb': kg_to_lb,
        })

        # =====================================================================
        # Time Utility Functions
        # =====================================================================

        def now() -> float:
            return time.time()

        def now_ms() -> int:
            return int(time.time() * 1000)

        def now_iso() -> str:
            return datetime.now().isoformat()

        def time_of_day() -> str:
            return datetime.now().strftime('%H:%M:%S')

        def elapsed_since(start_ts: float) -> float:
            return time.time() - start_ts

        def format_timestamp(ts_ms: int, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
            return datetime.fromtimestamp(ts_ms / 1000).strftime(fmt)

        namespace.update({
            'now': now, 'now_ms': now_ms, 'now_iso': now_iso,
            'time_of_day': time_of_day, 'elapsed_since': elapsed_since,
            'format_timestamp': format_timestamp,
        })

        return namespace

    def _set_safe_state(self, reason: str = 'command'):
        """Set all outputs to safe state (DO=0, AO=0)"""
        logger.info(f"Setting outputs to SAFE STATE - reason: {reason}")

        # Reset all digital outputs to OFF (0)
        for channel_name, task in self.output_tasks.items():
            try:
                ch_config = self.config.channels.get(channel_name)
                if ch_config and ch_config.channel_type == 'digital_output':
                    self._write_output(channel_name, 0)
                    logger.info(f"  DO {channel_name} -> 0 (OFF)")
                elif ch_config and ch_config.channel_type in ('analog_output', 'voltage_output', 'current_output'):
                    # AO safe state: default to 0.0 (voltage outputs)
                    # For 4-20mA current outputs, use SafetyAction with explicit safe_value
                    safe_value = 0.0
                    self._write_output(channel_name, safe_value)
                    logger.info(f"  AO {channel_name} -> {safe_value}")
            except Exception as e:
                logger.error(f"  Failed to set {channel_name} safe: {e}")

        # Publish confirmation
        self._publish(f"{self.get_topic_base()}/status/safe-state", {
            'success': True,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _execute_safety_action(self, action_name: str, trigger_source: str):
        """
        Execute a named safety action - set specified outputs to safe values.

        This is the core of autonomous cRIO safety - it runs locally without
        needing PC involvement.

        Args:
            action_name: Name of the safety action to execute
            trigger_source: What triggered this action (channel name, watchdog, etc.)
        """
        if not self.config or action_name not in self.config.safety_actions:
            logger.critical(f"SAFETY FAILURE: Unknown safety action '{action_name}' "
                          f"triggered by {trigger_source}")
            return

        action = self.config.safety_actions[action_name]
        logger.warning(f"SAFETY: Executing action '{action_name}' triggered by {trigger_source}")

        executed = []
        failed = []

        # Execute each channel in the action
        # Note: source='safety' bypasses session locks - safety MUST always work
        for channel_name, safe_value in action.actions.items():
            if channel_name in self.config.channels:
                try:
                    success = self._write_output(channel_name, safe_value, source='safety')
                    if success:
                        executed.append(f"{channel_name}={safe_value}")
                        logger.info(f"  SAFETY: {channel_name} -> {safe_value}")
                    else:
                        failed.append(f"{channel_name}: write failed")
                except Exception as e:
                    failed.append(f"{channel_name}: {e}")
                    logger.error(f"  SAFETY FAILURE: {channel_name}: {e}")
            else:
                failed.append(f"{channel_name}: not found")
                logger.critical(f"  SAFETY FAILURE: Action references non-existent channel '{channel_name}'")

        # Log results
        if failed:
            logger.critical(f"SAFETY ACTION '{action_name}' INCOMPLETE! Failed: {failed}")

        # Publish safety action event
        self._publish(f"{self.get_topic_base()}/safety/triggered", {
            'action': action_name,
            'trigger_source': trigger_source,
            'executed': executed,
            'failed': failed,
            'success': len(failed) == 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

        # Publish alarm if configured
        if action.trigger_alarm and action.alarm_message:
            self._publish(f"{self.get_topic_base()}/alarms/active", {
                'channel': trigger_source,
                'type': 'SAFETY',
                'message': action.alarm_message,
                'action': action_name,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

    def _handle_safety_trigger(self, payload: Dict[str, Any]):
        """Handle manual safety trigger command from MQTT"""
        action_name = payload.get('action')
        reason = payload.get('reason', 'manual_command')

        if not action_name:
            logger.warning("Safety trigger received without action name")
            return

        logger.info(f"Manual safety trigger: {action_name} (reason: {reason})")
        self._execute_safety_action(action_name, f"manual:{reason}")

    def _init_local_safety(self):
        """Initialize the local safety manager for autonomous operation"""
        def get_channel_value(channel: str) -> Optional[float]:
            with self.values_lock:
                return self.channel_values.get(channel)

        def set_output(channel: str, value: Any):
            self._set_output(channel, value)

        def stop_session():
            self._stop_session()

        def publish(topic: str, data: Dict[str, Any]):
            self._publish(f"{self.get_topic_base()}/{topic}", data)

        self.local_safety = LocalSafetyManager(
            get_channel_value=get_channel_value,
            set_output=set_output,
            stop_session=stop_session,
            publish=publish
        )
        logger.info("[LocalSafety] Local safety manager initialized")

    def _check_safety_limits(self, channel_name: str, value: float):
        """
        Check ISA-18.2 safety limits for a channel and trigger action if needed.

        Safety actions trigger on CRITICAL limits (HIHI/LOLO), not warning limits (HI/LO).
        This is the core safety evaluation that runs in the scan loop.
        It implements one-shot triggering - action fires only on transition
        from safe to unsafe, preventing repeated execution.

        Args:
            channel_name: Name of the channel being checked
            value: Current value of the channel
        """
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.safety_action:
            return  # No safety action configured for this channel

        triggered = False
        trigger_reason = ""

        # Check ISA-18.2 critical limits (HIHI/LOLO trigger safety actions)
        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            triggered = True
            trigger_reason = f"HIHI: {value:.2f} >= {ch_config.hihi_limit}"
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            triggered = True
            trigger_reason = f"LOLO: {value:.2f} <= {ch_config.lolo_limit}"

        # Check digital input expected state
        if ch_config.channel_type == 'digital_input' and ch_config.expected_state is not None:
            # Convert value to boolean (0 = False, non-zero = True)
            actual_state = bool(value)
            if actual_state != ch_config.expected_state:
                triggered = True
                trigger_reason = f"DI unexpected: {actual_state} != expected {ch_config.expected_state}"

        # One-shot execution (only on transition from safe to unsafe)
        with self.safety_lock:
            was_triggered = self.safety_triggered.get(channel_name, False)

            if triggered and not was_triggered:
                # Transition to unsafe - execute safety action
                self.safety_triggered[channel_name] = True
                logger.warning(f"SAFETY LIMIT VIOLATION: {channel_name} - {trigger_reason}")
                self._execute_safety_action(ch_config.safety_action, channel_name)

            elif not triggered and was_triggered:
                # Transition back to safe - clear triggered state
                del self.safety_triggered[channel_name]
                logger.info(f"Safety condition cleared: {channel_name}")

                # Publish clear event
                self._publish(f"{self.get_topic_base()}/safety/cleared", {
                    'channel': channel_name,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })

    def _check_alarms(self, channel_name: str, value: float):
        """
        Evaluate ISA-18.2 alarms for a channel and publish alarm events.

        This runs locally on cRIO for autonomous alarm evaluation.
        Alarm events are published to PC for display/logging, but
        evaluation happens here regardless of PC connection.

        Alarm levels (from most severe to least):
        - HIHI: Critical high (also triggers safety action if configured)
        - HI: Warning high
        - LO: Warning low
        - LOLO: Critical low (also triggers safety action if configured)
        - NORMAL: Within all limits

        Args:
            channel_name: Name of the channel being checked
            value: Current value of the channel
        """
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.alarm_enabled:
            return

        # Apply deadband for alarm clearing (not triggering)
        deadband = ch_config.alarm_deadband if ch_config.alarm_deadband else 0.0

        # Determine new alarm state (check in priority order: most severe first)
        new_state = AlarmState.NORMAL

        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            new_state = AlarmState.HIHI
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            new_state = AlarmState.LOLO
        elif ch_config.hi_limit is not None and value >= ch_config.hi_limit:
            new_state = AlarmState.HI
        elif ch_config.lo_limit is not None and value <= ch_config.lo_limit:
            new_state = AlarmState.LO

        # Check for state change
        with self.alarm_lock:
            prev_state = self.alarm_states.get(channel_name, AlarmState.NORMAL)

            if new_state != prev_state:
                # Apply deadband for clearing (returning to normal)
                if new_state == AlarmState.NORMAL and deadband > 0:
                    # Check if we're clearly within bounds (with deadband)
                    if prev_state in (AlarmState.HI, AlarmState.HIHI):
                        threshold = ch_config.hi_limit or ch_config.hihi_limit
                        if threshold and value > (threshold - deadband):
                            return  # Still in deadband zone, don't clear yet
                    elif prev_state in (AlarmState.LO, AlarmState.LOLO):
                        threshold = ch_config.lo_limit or ch_config.lolo_limit
                        if threshold and value < (threshold + deadband):
                            return  # Still in deadband zone, don't clear yet

                # State change confirmed
                self.alarm_states[channel_name] = new_state
                self._publish_alarm_event(channel_name, prev_state, new_state, value)

                # Log alarm
                if new_state == AlarmState.NORMAL:
                    logger.info(f"ALARM CLEARED: {channel_name}")
                else:
                    severity = "CRITICAL" if new_state in (AlarmState.HIHI, AlarmState.LOLO) else "WARNING"
                    logger.warning(f"ALARM {severity}: {channel_name} - {new_state.value} at {value:.2f}")

    def _publish_alarm_event(self, channel: str, prev_state: AlarmState, new_state: AlarmState, value: float):
        """Publish alarm state change event for PC display/logging"""
        ch_config = self.config.channels.get(channel)

        event = {
            'channel': channel,
            'previous_state': prev_state.value,
            'state': new_state.value,
            'value': value,
            'priority': ch_config.alarm_priority if ch_config else 'medium',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'node_id': self.config.node_id
        }

        # Include limit info for context
        if ch_config:
            if new_state == AlarmState.HIHI:
                event['limit'] = ch_config.hihi_limit
            elif new_state == AlarmState.HI:
                event['limit'] = ch_config.hi_limit
            elif new_state == AlarmState.LO:
                event['limit'] = ch_config.lo_limit
            elif new_state == AlarmState.LOLO:
                event['limit'] = ch_config.lolo_limit

        self._publish(f"{self.get_topic_base()}/alarms/event", event)

    # =========================================================================
    # INTERLOCK LOGIC
    # =========================================================================

    def _check_interlock(self, interlock_expr: str) -> bool:
        """
        Evaluate a safety interlock expression safely (no eval).

        Interlocks are boolean expressions that must evaluate to True
        before a write to an output is allowed.

        Example expressions:
            "temp < 100"
            "pressure > 10 AND flow_rate > 5"
            "NOT emergency_stop"
            "pump_running OR bypass_enabled"

        Returns True if interlock passes (write allowed), False if blocked.
        On any error, returns False (fail-safe).
        """
        if not interlock_expr:
            return True  # No interlock = always allowed

        try:
            with self.values_lock:
                values = dict(self.channel_values)

            return self._safe_eval_interlock(interlock_expr.strip(), values)

        except Exception as e:
            logger.error(f"Interlock evaluation failed: {e}")
            return False  # Fail safe - don't allow write

    def _safe_eval_interlock(self, expr: str, values: Dict[str, float]) -> bool:
        """
        Recursive descent parser for interlock expressions.

        Supports:
            - Comparisons: ==, !=, <, >, <=, >=
            - Logical operators: AND, OR, NOT
            - Parentheses for grouping
            - Channel names and numeric literals
            - Boolean literals: true, false
        """
        expr = expr.strip()

        # Handle parentheses
        if expr.startswith('(') and expr.endswith(')'):
            # Find matching closing paren
            depth = 0
            for i, c in enumerate(expr):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                if depth == 0 and i == len(expr) - 1:
                    return self._safe_eval_interlock(expr[1:-1], values)
                elif depth == 0 and i < len(expr) - 1:
                    break  # Not a simple (expr) - has stuff after

        # Handle OR (lowest precedence)
        or_parts = self._split_by_operator(expr, ' OR ')
        if len(or_parts) > 1:
            return any(self._safe_eval_interlock(part, values) for part in or_parts)

        # Handle AND
        and_parts = self._split_by_operator(expr, ' AND ')
        if len(and_parts) > 1:
            return all(self._safe_eval_interlock(part, values) for part in and_parts)

        # Handle NOT
        if expr.upper().startswith('NOT '):
            return not self._safe_eval_interlock(expr[4:], values)

        # Handle comparisons
        for op in ['<=', '>=', '!=', '==', '<', '>']:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = self._resolve_value(parts[0].strip(), values)
                    right = self._resolve_value(parts[1].strip(), values)

                    if op == '==':
                        return left == right
                    elif op == '!=':
                        return left != right
                    elif op == '<':
                        return left < right
                    elif op == '>':
                        return left > right
                    elif op == '<=':
                        return left <= right
                    elif op == '>=':
                        return left >= right

        # Bare value (boolean check)
        value = self._resolve_value(expr, values)
        return bool(value)

    def _split_by_operator(self, expr: str, op: str) -> List[str]:
        """Split expression by operator, respecting parentheses"""
        parts = []
        depth = 0
        current = ""

        i = 0
        while i < len(expr):
            c = expr[i]

            if c == '(':
                depth += 1
                current += c
            elif c == ')':
                depth -= 1
                current += c
            elif depth == 0 and expr[i:].upper().startswith(op):
                parts.append(current.strip())
                current = ""
                i += len(op) - 1
            else:
                current += c
            i += 1

        if current.strip():
            parts.append(current.strip())

        return parts if len(parts) > 1 else [expr]

    def _resolve_value(self, token: str, values: Dict[str, float]) -> Any:
        """Resolve a token to its value (channel, number, or boolean)"""
        token = token.strip()

        # Boolean literals
        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False

        # Numeric literals
        try:
            if '.' in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        # Channel name - get value from dict
        if token in values:
            return values[token]

        # Unknown token - log warning and return False (fail-safe)
        logger.warning(f"Interlock: unknown token '{token}' - treating as False")
        return False

    def _publish_interlock_blocked(self, channel_name: str, interlock_expr: str, requested_value: Any):
        """Publish event when a write is blocked by interlock"""
        self._publish(f"{self.get_topic_base()}/interlock/blocked", {
            'channel': channel_name,
            'interlock': interlock_expr,
            'requested_value': requested_value,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # =========================================================================
    # HARDWARE CONFIGURATION
    # =========================================================================

    def _configure_hardware(self, old_channels: Dict[str, ChannelConfig] = None):
        """Configure NI-DAQmx tasks based on current config.

        Args:
            old_channels: Previous channel config for incremental updates.
                         If provided, only changed channels will be reconfigured.
        """
        if not NIDAQMX_AVAILABLE:
            logger.warning("NI-DAQmx not available - using simulation")
            return

        # Track if we need to restart tasks after reconfiguration
        was_acquiring = self._acquiring.is_set()

        # Determine what changed (for incremental reconfiguration)
        if old_channels:
            changed_outputs, removed_outputs, new_outputs = self._diff_output_channels(
                old_channels, self.config.channels
            )

            # PAUSE SCAN LOOP during reconfiguration to prevent race conditions
            if was_acquiring:
                logger.info("Pausing scan loop for reconfiguration...")
                self._task_swap_in_progress = True
                time.sleep(0.05)  # Allow current scan iteration to complete

            # SAFETY FIRST: Set outputs to safe state BEFORE closing tasks
            # This prevents undefined output states during reconfiguration
            if changed_outputs or removed_outputs:
                logger.info(f"Setting {len(changed_outputs) + len(removed_outputs)} outputs to safe state before reconfiguration")
                for ch_name in list(changed_outputs) + list(removed_outputs):
                    if ch_name in self.output_tasks:
                        try:
                            # Get safe value (0 for DO, 0.0 for AO)
                            old_ch = old_channels.get(ch_name)
                            if old_ch and old_ch.channel_type == 'digital_output':
                                self.output_tasks[ch_name].write(False)
                            elif old_ch and old_ch.channel_type in ('analog_output', 'voltage_output', 'current_output'):
                                self.output_tasks[ch_name].write(0.0)
                            logger.debug(f"  {ch_name} -> SAFE")
                        except Exception as e:
                            logger.warning(f"Failed to set {ch_name} to safe state: {e}")

            # Close only output tasks that need to be closed
            # Input tasks are grouped, so we still need to close and recreate them
            self._close_tasks_selective(changed_outputs | removed_outputs)
            self._close_input_tasks()  # Input tasks must be recreated

            # For outputs, only create tasks for new/changed channels
            outputs_to_create = changed_outputs | new_outputs
        else:
            # Full reconfiguration (first startup or forced)
            self._close_tasks()
            outputs_to_create = None  # Create all

        # Group channels by type
        tc_channels = []
        voltage_channels = []
        current_channels = []
        rtd_channels = []
        counter_channels = []
        strain_channels = []
        iepe_channels = []
        di_channels = []
        do_channels = []
        ao_channels = []

        for name, ch in self.config.channels.items():
            if ch.channel_type == 'thermocouple':
                tc_channels.append(ch)
            elif ch.channel_type in ('voltage', 'voltage_input'):
                voltage_channels.append(ch)
            elif ch.channel_type in ('current', 'current_input'):
                current_channels.append(ch)
            elif ch.channel_type == 'rtd':
                rtd_channels.append(ch)
            elif ch.channel_type == 'counter':
                counter_channels.append(ch)
            elif ch.channel_type == 'strain':
                strain_channels.append(ch)
            elif ch.channel_type == 'iepe':
                iepe_channels.append(ch)
            elif ch.channel_type == 'digital_input':
                di_channels.append(ch)
            elif ch.channel_type == 'digital_output':
                do_channels.append(ch)
            elif ch.channel_type in ('analog_output', 'voltage_output', 'current_output'):
                ao_channels.append(ch)

        # Create input tasks (always recreated since they're grouped by type)
        if tc_channels:
            self._create_thermocouple_task(tc_channels)
        if voltage_channels:
            self._create_voltage_task(voltage_channels)
        if current_channels:
            self._create_current_task(current_channels)
        if rtd_channels:
            self._create_rtd_task(rtd_channels)
        if counter_channels:
            self._create_counter_tasks(counter_channels)
        if strain_channels:
            self._create_strain_task(strain_channels)
        if iepe_channels:
            self._create_iepe_task(iepe_channels)
        if di_channels:
            self._create_digital_input_task(di_channels)

        # Create output tasks (incremental: only new/changed, full: all)
        if ao_channels:
            ao_to_create = [ch for ch in ao_channels
                           if outputs_to_create is None or ch.name in outputs_to_create]
            if ao_to_create:
                self._create_analog_output_tasks(ao_to_create)
        if do_channels:
            do_to_create = [ch for ch in do_channels
                           if outputs_to_create is None or ch.name in outputs_to_create]
            if do_to_create:
                self._create_digital_output_tasks(do_to_create)
            self._setup_watchdog(do_channels)  # Watchdog always uses all DO channels

        logger.info(f"Hardware configured: {len(self.input_tasks)} input tasks, {len(self.output_tasks)} output tasks")

        # If acquisition was running, start the new input tasks and resume scan loop
        if was_acquiring and self.input_tasks:
            logger.info("Restarting input tasks after reconfiguration...")
            for name, task_info in self.input_tasks.items():
                try:
                    task_info['task'].start()
                    logger.debug(f"Started task: {name}")
                except Exception as e:
                    logger.error(f"Failed to start task {name}: {e}")

            # Resume scan loop
            self._task_swap_in_progress = False
            logger.info("Scan loop resumed")

    def _create_thermocouple_task(self, channels: List[ChannelConfig]):
        """Create thermocouple input task"""
        task = nidaqmx.Task('TC_Input')
        channel_names = []

        try:
            for ch in channels:
                tc_type_map = {
                    'J': NI_TCType.J, 'K': NI_TCType.K, 'T': NI_TCType.T,
                    'E': NI_TCType.E, 'N': NI_TCType.N, 'R': NI_TCType.R,
                    'S': NI_TCType.S, 'B': NI_TCType.B
                }
                tc_type = tc_type_map.get(ch.thermocouple_type.upper(), NI_TCType.K)

                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.ai_channels.add_ai_thrmcpl_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    thermocouple_type=tc_type
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added TC channel: {ch.name} -> {ch.physical_channel}")

            # Configure continuous acquisition
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['thermocouple'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create TC task: {e}")

    def _create_voltage_task(self, channels: List[ChannelConfig]):
        """Create voltage input task"""
        task = nidaqmx.Task('Voltage_Input')
        channel_names = []

        try:
            for ch in channels:
                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')

                # Try preferred terminal config first, fallback to DIFF if not supported
                term_configs_to_try = []
                if ch.terminal_config.upper() == 'RSE':
                    term_configs_to_try = [TerminalConfiguration.RSE, TerminalConfiguration.DIFF]
                elif ch.terminal_config.upper() == 'DIFF':
                    term_configs_to_try = [TerminalConfiguration.DIFF]
                elif ch.terminal_config.upper() == 'NRSE':
                    term_configs_to_try = [TerminalConfiguration.NRSE, TerminalConfiguration.DIFF]
                else:
                    term_configs_to_try = [TerminalConfiguration.DIFF]  # Default to DIFF

                added = False
                for term_config in term_configs_to_try:
                    try:
                        task.ai_channels.add_ai_voltage_chan(
                            ch.physical_channel,
                            name_to_assign_to_channel=safe_name,
                            terminal_config=term_config,
                            min_val=-ch.voltage_range,
                            max_val=ch.voltage_range
                        )
                        channel_names.append(ch.name)  # Keep original name for our tracking
                        logger.info(f"Added voltage channel: {ch.name} -> {ch.physical_channel} ({term_config.name})")
                        added = True
                        break
                    except Exception as e:
                        if 'DAQmx_Val_Diff' in str(e) or 'TermCfg' in str(e):
                            continue  # Try next terminal config
                        raise  # Re-raise if different error

                if not added:
                    logger.warning(f"Could not add voltage channel: {ch.name}")

            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['voltage'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create voltage task: {e}")

    def _create_current_task(self, channels: List[ChannelConfig]):
        """Create current (4-20mA) input task"""
        from nidaqmx.constants import CurrentShuntResistorLocation

        task = nidaqmx.Task('Current_Input')
        channel_names = []

        try:
            for ch in channels:
                max_current = ch.current_range_ma / 1000.0  # Convert to Amps

                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.ai_channels.add_ai_current_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    min_val=0.0,
                    max_val=max_current,
                    shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added current channel: {ch.name} -> {ch.physical_channel}")

            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['current'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create current task: {e}")

    def _create_digital_input_task(self, channels: List[ChannelConfig]):
        """Create digital input task with on-demand reads for safety responsiveness.

        SAFETY ARCHITECTURE NOTE:
        Digital inputs are often used for safety interlocks (E-stops, limit switches,
        door interlocks, pressure switches). On-demand reads provide IMMEDIATE state
        with microsecond latency - critical for safety response.

        Hardware-timed buffered reads would introduce unacceptable latency
        (up to buffer_size/sample_rate = 100/10 = 10 seconds worst case).

        The different read methods are intentional:
        - Analog (TC, Voltage, Current): Hardware-timed for precision/anti-aliasing
        - Digital (DI for safeties): On-demand for immediate response
        """
        task = nidaqmx.Task('DI_Input')
        channel_names = []

        try:
            for ch in channels:
                # Sanitize channel name - NI-DAQmx doesn't allow / in names
                safe_name = ch.name.replace('/', '_')
                task.di_channels.add_di_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=safe_name
                )
                channel_names.append(ch.name)  # Keep original name for our tracking
                logger.info(f"Added DI channel: {ch.name} -> {ch.physical_channel}")

            # On-demand reads (no hardware timing) - REQUIRED for safety applications
            # This gives immediate current state with no buffer delay
            self.input_tasks['digital_input'] = {
                'task': task,
                'reader': None,  # On-demand read for immediate safety response
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create DI task: {e}")

    def _create_rtd_task(self, channels: List[ChannelConfig]):
        """Create RTD (Resistance Temperature Detector) input task"""
        from nidaqmx.constants import RTDType, ResistanceConfiguration, ExcitationSource

        task = nidaqmx.Task('RTD_Input')
        channel_names = []

        try:
            # Map RTD type string to nidaqmx constant
            rtd_type_map = {
                'Pt100': RTDType.PT_3750, 'PT100': RTDType.PT_3750,
                'Pt385': RTDType.PT_3851, 'PT385': RTDType.PT_3851,
                'Pt3851': RTDType.PT_3851, 'PT3851': RTDType.PT_3851,
                'Pt3916': RTDType.PT_3916, 'PT3916': RTDType.PT_3916,
                'Pt500': RTDType.PT_3750, 'PT500': RTDType.PT_3750,
                'Pt1000': RTDType.PT_3750, 'PT1000': RTDType.PT_3750,
            }

            # Map wiring configuration
            wiring_map = {
                '2-wire': ResistanceConfiguration.TWO_WIRE,
                '3-wire': ResistanceConfiguration.THREE_WIRE,
                '4-wire': ResistanceConfiguration.FOUR_WIRE,
                '2_wire': ResistanceConfiguration.TWO_WIRE,
                '3_wire': ResistanceConfiguration.THREE_WIRE,
                '4_wire': ResistanceConfiguration.FOUR_WIRE,
            }

            for ch in channels:
                safe_name = ch.name.replace('/', '_')

                # Get RTD type (default to Pt100)
                rtd_type_str = getattr(ch, 'rtd_type', 'Pt100') or 'Pt100'
                rtd_type = rtd_type_map.get(rtd_type_str, RTDType.PT_3750)

                # Get wiring configuration (default to 4-wire)
                wiring_str = getattr(ch, 'rtd_wiring', '4-wire') or '4-wire'
                wiring = wiring_map.get(wiring_str, ResistanceConfiguration.FOUR_WIRE)

                # Get R0 resistance (default 100 ohms for Pt100)
                r0 = getattr(ch, 'rtd_resistance', 100.0) or 100.0

                # Get excitation current (default 1mA)
                current = getattr(ch, 'rtd_current', 0.001) or 0.001

                task.ai_channels.add_ai_rtd_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    rtd_type=rtd_type,
                    resistance_config=wiring,
                    current_excit_source=ExcitationSource.INTERNAL,
                    current_excit_val=current,
                    r_0=r0
                )
                channel_names.append(ch.name)
                logger.info(f"Added RTD channel: {ch.name} -> {ch.physical_channel} "
                           f"(type={rtd_type_str}, wiring={wiring_str}, R0={r0})")

            # Configure continuous acquisition
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['rtd'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create RTD task: {e}")

    def _create_counter_tasks(self, channels: List[ChannelConfig]):
        """Create counter/frequency input tasks (one per channel)"""
        from nidaqmx.constants import Edge, CountDirection
        from nidaqmx.stream_readers import CounterReader

        for ch in channels:
            try:
                safe_task_name = f"Counter_{ch.name.replace('/', '_')}"
                task = nidaqmx.Task(safe_task_name)

                # Get counter configuration
                counter_mode = getattr(ch, 'counter_mode', 'frequency') or 'frequency'
                min_freq = getattr(ch, 'counter_min_freq', 0.1) or 0.1
                max_freq = getattr(ch, 'counter_max_freq', 1000.0) or 1000.0
                edge_str = getattr(ch, 'counter_edge', 'rising') or 'rising'
                edge = Edge.RISING if edge_str.lower() == 'rising' else Edge.FALLING

                if counter_mode == 'frequency':
                    # Frequency measurement
                    task.ci_channels.add_ci_freq_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=ch.name.replace('/', '_'),
                        min_val=min_freq,
                        max_val=max_freq,
                        edge=edge
                    )
                    logger.info(f"Added frequency counter: {ch.name} -> {ch.physical_channel} "
                               f"(range={min_freq}-{max_freq}Hz)")

                elif counter_mode == 'count':
                    # Edge counting
                    task.ci_channels.add_ci_count_edges_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=ch.name.replace('/', '_'),
                        edge=edge,
                        initial_count=0,
                        count_direction=CountDirection.COUNT_UP
                    )
                    logger.info(f"Added edge counter: {ch.name} -> {ch.physical_channel}")

                elif counter_mode == 'period':
                    # Period measurement
                    min_period = 1.0 / max_freq if max_freq > 0 else 0.001
                    max_period = 1.0 / min_freq if min_freq > 0 else 10.0
                    task.ci_channels.add_ci_period_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=ch.name.replace('/', '_'),
                        min_val=min_period,
                        max_val=max_period,
                        edge=edge
                    )
                    logger.info(f"Added period counter: {ch.name} -> {ch.physical_channel}")

                # Store task (counters are read on-demand, not continuous)
                self.input_tasks[f'counter_{ch.name}'] = {
                    'task': task,
                    'reader': CounterReader(task.in_stream),
                    'channels': [ch.name],
                    'mode': counter_mode
                }

            except Exception as e:
                logger.error(f"Failed to create counter task for {ch.name}: {e}")
                try:
                    task.close()
                except Exception as e:
                    logger.warning(f"Failed to close counter task for {ch.name} during cleanup: {e}")

    def _create_strain_task(self, channels: List[ChannelConfig]):
        """Create strain gauge input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import (
            StrainGageBridgeType, BridgeConfiguration, ExcitationSource
        )

        task = nidaqmx.Task('Strain_Input')
        channel_names = []

        # Map bridge config
        bridge_map = {
            'full-bridge': BridgeConfiguration.FULL_BRIDGE,
            'full_bridge': BridgeConfiguration.FULL_BRIDGE,
            'half-bridge': BridgeConfiguration.HALF_BRIDGE,
            'half_bridge': BridgeConfiguration.HALF_BRIDGE,
            'quarter-bridge': BridgeConfiguration.QUARTER_BRIDGE,
            'quarter_bridge': BridgeConfiguration.QUARTER_BRIDGE,
        }

        try:
            for ch in channels:
                safe_name = ch.name.replace('/', '_')

                # Get strain configuration
                strain_config = getattr(ch, 'strain_config', 'full-bridge') or 'full-bridge'
                bridge_config = bridge_map.get(strain_config.lower(), BridgeConfiguration.FULL_BRIDGE)

                # Get strain parameters
                excit_voltage = getattr(ch, 'strain_excitation_voltage', 2.5) or 2.5
                gage_factor = getattr(ch, 'strain_gage_factor', 2.0) or 2.0
                resistance = getattr(ch, 'strain_resistance', 350.0) or 350.0

                task.ai_channels.add_ai_strain_gage_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    strain_config=bridge_config,
                    voltage_excit_source=ExcitationSource.INTERNAL,
                    voltage_excit_val=excit_voltage,
                    gage_factor=gage_factor,
                    nominal_gage_resistance=resistance
                )
                channel_names.append(ch.name)
                logger.info(f"Added strain channel: {ch.name} -> {ch.physical_channel} "
                           f"(config={strain_config}, GF={gage_factor})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['strain'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create strain task: {e}")

    def _create_iepe_task(self, channels: List[ChannelConfig]):
        """Create IEPE (accelerometer/microphone) input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import ExcitationSource, Coupling

        task = nidaqmx.Task('IEPE_Input')
        channel_names = []

        try:
            for ch in channels:
                safe_name = ch.name.replace('/', '_')

                # Get IEPE configuration
                sensitivity = getattr(ch, 'iepe_sensitivity', 100.0) or 100.0  # mV/g
                coupling_str = getattr(ch, 'iepe_coupling', 'AC') or 'AC'
                coupling = Coupling.AC if coupling_str.upper() == 'AC' else Coupling.DC
                current = getattr(ch, 'iepe_current', 0.002) or 0.002  # 2mA default

                # Add accelerometer channel with IEPE excitation
                task.ai_channels.add_ai_accel_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    sensitivity=sensitivity,
                    current_excit_source=ExcitationSource.INTERNAL,
                    current_excit_val=current
                )
                # Set coupling
                task.ai_channels[safe_name].ai_coupling = coupling

                channel_names.append(ch.name)
                logger.info(f"Added IEPE channel: {ch.name} -> {ch.physical_channel} "
                           f"(sensitivity={sensitivity} mV/g, coupling={coupling_str})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            reader = AnalogMultiChannelReader(task.in_stream)
            self.input_tasks['iepe'] = {
                'task': task,
                'reader': reader,
                'channels': channel_names
            }

        except Exception as e:
            task.close()
            logger.error(f"Failed to create IEPE task: {e}")

    def _create_analog_output_tasks(self, channels: List[ChannelConfig]):
        """Create analog output tasks (one per channel for independent control)"""
        for ch in channels:
            try:
                # Sanitize task name - NI-DAQmx doesn't allow / in task names
                safe_task_name = f"AO_{ch.name.replace('/', '_')}"
                safe_chan_name = ch.name.replace('/', '_')
                task = nidaqmx.Task(safe_task_name)

                # Check if we have a preserved value from before reconfiguration
                preserved_value = self.output_values.get(ch.name)

                # Check if this is a current output module by trying voltage first
                # then falling back to current if that fails
                try:
                    task.ao_channels.add_ao_voltage_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=safe_chan_name,
                        min_val=-10.0,
                        max_val=10.0
                    )
                    self.output_tasks[ch.name] = task

                    # Preserve existing state or use default
                    if preserved_value is not None:
                        task.write(preserved_value)
                        logger.info(f"Added AO voltage channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_value})")
                    else:
                        task.write(0.0)
                        self.output_values[ch.name] = 0.0
                        logger.info(f"Added AO voltage channel: {ch.name} -> {ch.physical_channel} (default=0.0)")

                except Exception as voltage_error:
                    # If voltage fails, try current output (for modules like NI 9266)
                    if 'DAQmx_Val_Current' in str(voltage_error):
                        task.close()
                        task = nidaqmx.Task(safe_task_name)
                        task.ao_channels.add_ao_current_chan(
                            ch.physical_channel,
                            name_to_assign_to_channel=safe_chan_name,
                            min_val=0.0,
                            max_val=0.020  # 20mA max
                        )
                        self.output_tasks[ch.name] = task

                        # Preserve existing state or use default 4mA
                        if preserved_value is not None:
                            task.write(preserved_value)
                            logger.info(f"Added AO current channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_value})")
                        else:
                            task.write(0.004)  # Start at 4mA (typical 4-20mA range)
                            self.output_values[ch.name] = 0.004
                            logger.info(f"Added AO current channel: {ch.name} -> {ch.physical_channel} (default=4mA)")
                    else:
                        raise voltage_error

            except Exception as e:
                logger.error(f"Failed to create AO task for {ch.name}: {e}")

    def _create_digital_output_tasks(self, channels: List[ChannelConfig]):
        """Create digital output tasks (one per channel for independent control)"""
        for ch in channels:
            try:
                # Sanitize task name - NI-DAQmx doesn't allow / in task names
                safe_task_name = f"DO_{ch.name.replace('/', '_')}"
                task = nidaqmx.Task(safe_task_name)
                task.do_channels.add_do_chan(
                    ch.physical_channel,
                    name_to_assign_to_lines=ch.name.replace('/', '_')  # Also sanitize line name
                )

                self.output_tasks[ch.name] = task

                # Preserve existing output state across reconfiguration
                # Only use default_state if this is truly the first time
                if ch.name in self.output_values:
                    # Restore previous state
                    preserved_state = bool(self.output_values[ch.name])
                    if ch.invert:
                        preserved_state = not preserved_state
                    task.write(preserved_state)
                    logger.info(f"Added DO channel: {ch.name} -> {ch.physical_channel} (preserved={preserved_state})")
                else:
                    # First time - use default state
                    initial_state = ch.default_state
                    if ch.invert:
                        initial_state = not initial_state
                    task.write(initial_state)
                    self.output_values[ch.name] = 1.0 if initial_state else 0.0
                    logger.info(f"Added DO channel: {ch.name} -> {ch.physical_channel} (default={initial_state})")

            except Exception as e:
                logger.error(f"Failed to create DO task for {ch.name}: {e}")

    def _setup_watchdog(self, do_channels: List[ChannelConfig]):
        """
        Setup watchdog for digital outputs.

        On cRIO, hardware watchdog support varies by module. We use a software
        watchdog approach that tracks the last scan time and can trigger safe
        state if the scan loop stops.

        Note: True hardware watchdog requires specific NI FPGA configuration
        which is beyond the scope of this Python service.
        """
        if not NIDAQMX_AVAILABLE:
            return

        try:
            # Get safe state outputs (or default to all DO)
            safe_outputs = self.config.safe_state_outputs or [ch.name for ch in do_channels]

            # Build physical channel list for watchdog
            phys_channels = []
            for ch in do_channels:
                if ch.name in safe_outputs:
                    phys_channels.append(ch.physical_channel)

            if not phys_channels:
                logger.info("No safe state outputs configured - skipping watchdog")
                return

            # Use software watchdog - track channels for safe state on failure
            self._watchdog_channels = phys_channels
            self._watchdog_last_pet = time.time()
            self.watchdog_task = None  # No hardware watchdog

            logger.info(f"Software watchdog configured: timeout={self.config.watchdog_timeout}s, "
                       f"safe_outputs={len(phys_channels)} DO channels")

        except Exception as e:
            logger.warning(f"Watchdog setup skipped: {e}")
            self.watchdog_task = None

    def _pet_watchdog(self):
        """
        Pet the software watchdog to indicate RT task is running normally.
        Called in scan loop to track that acquisition is active.
        """
        # Software watchdog - just update the last pet time
        self._watchdog_last_pet = time.time()
        self._watchdog_triggered = False  # Reset trigger flag when petted

    def _check_watchdog_timeout(self) -> bool:
        """
        Check if watchdog has expired and trigger safe state.
        Returns True if watchdog expired and safe state was triggered.

        This is the CRITICAL safety function - if the scan loop hangs,
        this will force outputs to safe state.
        """
        if not self.config or self.config.watchdog_timeout <= 0:
            return False  # Watchdog disabled

        if self._watchdog_last_pet == 0:
            return False  # Never started

        elapsed = time.time() - self._watchdog_last_pet

        if elapsed > self.config.watchdog_timeout:
            if not self._watchdog_triggered:
                logger.critical(
                    f"WATCHDOG TIMEOUT: {elapsed:.1f}s > {self.config.watchdog_timeout}s - "
                    f"TRIGGERING SAFE STATE"
                )
                self._watchdog_triggered = True
                self._set_safe_state("watchdog_timeout")

                # Publish watchdog alarm
                self._publish(f"{self.get_topic_base()}/safety/watchdog", {
                    'event': 'timeout',
                    'elapsed_s': elapsed,
                    'timeout_s': self.config.watchdog_timeout,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return True

        return False

    def _watchdog_monitor_loop(self):
        """
        Independent watchdog monitor thread.

        This runs separately from the scan loop and checks the watchdog timeout.
        If the scan loop hangs (infinite loop, deadlock, etc.), this thread
        will detect it and force outputs to safe state.

        This is defense-in-depth - the primary scan loop should never hang,
        but if it does, this thread ensures safety.
        """
        logger.info("Watchdog monitor thread started")

        # Check at 2x the watchdog rate for responsiveness
        check_interval = max(0.25, (self.config.watchdog_timeout / 4) if self.config else 0.5)

        while self._running.is_set():
            try:
                # Only check if acquisition is supposed to be running
                if self._acquiring.is_set():
                    self._check_watchdog_timeout()
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")

            time.sleep(check_interval)

        logger.info("Watchdog monitor thread stopped")

    def _close_tasks(self):
        """Close all NI-DAQmx tasks"""
        # Close input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].close()
            except Exception as e:
                logger.warning(f"Error closing input task {name}: {e}")
        self.input_tasks.clear()

        # Close output tasks
        for name, task in self.output_tasks.items():
            try:
                task.close()
            except Exception as e:
                logger.warning(f"Error closing output task {name}: {e}")
        self.output_tasks.clear()

        # Close watchdog
        if self.watchdog_task:
            try:
                self.watchdog_task.close()
            except Exception as e:
                logger.warning(f"Error closing watchdog task: {e}")
            self.watchdog_task = None

    def _close_tasks_selective(self, channels_to_close: set):
        """Close only specific output tasks (for incremental reconfiguration)"""
        if not channels_to_close:
            return

        # Close specified output tasks
        for ch_name in channels_to_close:
            if ch_name in self.output_tasks:
                try:
                    self.output_tasks[ch_name].close()
                    del self.output_tasks[ch_name]
                    logger.debug(f"Closed output task: {ch_name}")
                except Exception as e:
                    logger.warning(f"Error closing output task {ch_name}: {e}")

    def _close_input_tasks(self):
        """Close all input tasks (they're grouped by type, so must be fully recreated)"""
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].close()
            except Exception as e:
                logger.warning(f"Error closing input task {name}: {e}")
        self.input_tasks.clear()

        # Also close watchdog since it's tied to DO channel set
        if self.watchdog_task:
            try:
                self.watchdog_task.close()
            except Exception as e:
                logger.warning(f"Error closing watchdog task: {e}")
            self.watchdog_task = None

    def _diff_output_channels(self, old_channels: Dict[str, ChannelConfig],
                               new_channels: Dict[str, ChannelConfig]) -> tuple:
        """Compare old and new configs to find changed output channels.

        Returns:
            Tuple of (changed_outputs, removed_outputs, new_outputs) as sets of channel names
        """
        output_types = {'digital_output', 'analog_output'}

        # Get old and new output channels
        old_outputs = {name: ch for name, ch in old_channels.items()
                       if ch.channel_type in output_types}
        new_outputs = {name: ch for name, ch in new_channels.items()
                       if ch.channel_type in output_types}

        old_names = set(old_outputs.keys())
        new_names = set(new_outputs.keys())

        # Removed channels (in old but not in new)
        removed = old_names - new_names

        # New channels (in new but not in old)
        added = new_names - old_names

        # Changed channels (in both but config differs)
        changed = set()
        for name in old_names & new_names:
            old_ch = old_outputs[name]
            new_ch = new_outputs[name]
            # Compare relevant fields for outputs
            if (old_ch.physical_channel != new_ch.physical_channel or
                old_ch.channel_type != new_ch.channel_type):
                changed.add(name)

        if removed or added or changed:
            logger.info(f"Output channel diff: {len(changed)} changed, "
                       f"{len(removed)} removed, {len(added)} new")

        return changed, removed, added

    # =========================================================================
    # DATA ACQUISITION
    # =========================================================================

    def _start_acquisition(self):
        """Start data acquisition"""
        if self._acquiring.is_set():
            logger.info("Acquisition already running")
            return

        logger.info("Starting acquisition...")

        # Start input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].start()
                logger.debug(f"Started task: {name}")
            except Exception as e:
                logger.error(f"Failed to start task {name}: {e}")

        # Start scan thread
        self._acquiring.set()
        self.scan_thread = threading.Thread(
            target=self._scan_loop,
            name="ScanLoop",
            daemon=True
        )
        self.scan_thread.start()

        # Notify engines that acquisition started
        self.trigger_engine.on_acquisition_start()
        self.channel_watchdog.on_acquisition_start()

        # Publish status
        self._publish_status()
        logger.info("Acquisition started")

        # Auto-start scripts with run_mode='acquisition'
        self._auto_start_scripts('acquisition')

    def _stop_acquisition(self):
        """Stop data acquisition"""
        if not self._acquiring.is_set():
            return

        logger.info("Stopping acquisition...")
        self._acquiring.clear()

        # CRITICAL: Stop session first if active - session scripts depend on acquisition
        # Without acquisition, outputs can't be controlled safely
        if self.session.active:
            logger.info("Stopping active session (acquisition stopping)")
            self._stop_session('acquisition_stopped')

        # Notify engines that acquisition stopped
        self.trigger_engine.on_acquisition_stop()
        self.channel_watchdog.on_acquisition_stop()

        # Wait for scan thread
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

        # Stop input tasks
        for name, task_info in self.input_tasks.items():
            try:
                task_info['task'].stop()
            except Exception as e:
                logger.debug(f"Error stopping task {name}: {e}")

        # Auto-stop acquisition scripts
        self._auto_stop_scripts('acquisition')

        # Set outputs to safe state when stopping
        self._set_safe_state('acquisition_stopped')

        # Publish status
        self._publish_status()
        logger.info("Acquisition stopped")

    # =========================================================================
    # SEAMLESS TASK SWAP - Dynamic channel reconfiguration
    # =========================================================================

    def _rebuild_input_task(self, task_type: str, channels: List['ChannelConfig']) -> Optional[Dict[str, Any]]:
        """Build a new input task without starting it.

        This creates a task in parallel while acquisition continues,
        preparing for seamless swap.

        Args:
            task_type: Type of task ('thermocouple', 'voltage', 'current', 'digital_input')
            channels: List of channel configurations

        Returns:
            Task info dict or None if creation failed
        """
        if not channels:
            return None

        if not NIDAQMX_AVAILABLE:
            logger.warning(f"Cannot rebuild {task_type} task - nidaqmx not available")
            return None

        try:
            if task_type == 'thermocouple':
                return self._build_thermocouple_task(channels)
            elif task_type == 'voltage':
                return self._build_voltage_task(channels)
            elif task_type == 'current':
                return self._build_current_task(channels)
            elif task_type == 'rtd':
                return self._build_rtd_task(channels)
            elif task_type == 'counter':
                return self._build_counter_tasks(channels)
            elif task_type == 'strain':
                return self._build_strain_task(channels)
            elif task_type == 'iepe':
                return self._build_iepe_task(channels)
            elif task_type == 'digital_input':
                return self._build_digital_input_task(channels)
            else:
                logger.error(f"Unknown task type: {task_type}")
                return None
        except Exception as e:
            logger.error(f"Failed to rebuild {task_type} task: {e}")
            return None

    def _build_thermocouple_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build thermocouple task (internal helper for rebuild)"""
        task = nidaqmx.Task(f'TC_Input_{int(time.time()*1000)}')
        channel_names = []

        for ch in channels:
            tc_type_map = {
                'J': NI_TCType.J, 'K': NI_TCType.K, 'T': NI_TCType.T,
                'E': NI_TCType.E, 'N': NI_TCType.N, 'R': NI_TCType.R,
                'S': NI_TCType.S, 'B': NI_TCType.B
            }
            tc_type = tc_type_map.get(ch.thermocouple_type.upper(), NI_TCType.K)
            safe_name = ch.name.replace('/', '_')
            task.ai_channels.add_ai_thrmcpl_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name,
                thermocouple_type=tc_type
            )
            channel_names.append(ch.name)

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_voltage_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build voltage task (internal helper for rebuild)"""
        task = nidaqmx.Task(f'Voltage_Input_{int(time.time()*1000)}')
        channel_names = []

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            term_configs_to_try = []
            if ch.terminal_config.upper() == 'RSE':
                term_configs_to_try = [TerminalConfiguration.RSE, TerminalConfiguration.DIFF]
            elif ch.terminal_config.upper() == 'DIFF':
                term_configs_to_try = [TerminalConfiguration.DIFF]
            elif ch.terminal_config.upper() == 'NRSE':
                term_configs_to_try = [TerminalConfiguration.NRSE, TerminalConfiguration.DIFF]
            else:
                term_configs_to_try = [TerminalConfiguration.DIFF]

            for term_config in term_configs_to_try:
                try:
                    task.ai_channels.add_ai_voltage_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=safe_name,
                        terminal_config=term_config,
                        min_val=-ch.voltage_range,
                        max_val=ch.voltage_range
                    )
                    channel_names.append(ch.name)
                    break
                except Exception:
                    continue

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_current_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build current (4-20mA) task (internal helper for rebuild)"""
        from nidaqmx.constants import CurrentShuntResistorLocation
        task = nidaqmx.Task(f'Current_Input_{int(time.time()*1000)}')
        channel_names = []

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            task.ai_channels.add_ai_current_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name,
                min_val=0.004,
                max_val=0.020,
                shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
            )
            channel_names.append(ch.name)

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_digital_input_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build digital input task (internal helper for rebuild)"""
        from nidaqmx.stream_readers import DigitalMultiChannelReader
        task = nidaqmx.Task(f'DI_Input_{int(time.time()*1000)}')
        channel_names = []

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            task.di_channels.add_di_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name
            )
            channel_names.append(ch.name)

        reader = DigitalMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_rtd_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build RTD task (internal helper for rebuild)"""
        from nidaqmx.constants import RTDType, ResistanceConfiguration, ExcitationSource

        task = nidaqmx.Task(f'RTD_Input_{int(time.time()*1000)}')
        channel_names = []

        rtd_type_map = {
            'Pt100': RTDType.PT_3750, 'PT100': RTDType.PT_3750,
            'Pt385': RTDType.PT_3851, 'PT385': RTDType.PT_3851,
            'Pt3851': RTDType.PT_3851, 'PT3851': RTDType.PT_3851,
            'Pt3916': RTDType.PT_3916, 'PT3916': RTDType.PT_3916,
        }

        wiring_map = {
            '2-wire': ResistanceConfiguration.TWO_WIRE,
            '3-wire': ResistanceConfiguration.THREE_WIRE,
            '4-wire': ResistanceConfiguration.FOUR_WIRE,
        }

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            rtd_type = rtd_type_map.get(getattr(ch, 'rtd_type', 'Pt100'), RTDType.PT_3750)
            wiring = wiring_map.get(getattr(ch, 'rtd_wiring', '4-wire'), ResistanceConfiguration.FOUR_WIRE)
            r0 = getattr(ch, 'rtd_resistance', 100.0) or 100.0
            current = getattr(ch, 'rtd_current', 0.001) or 0.001

            task.ai_channels.add_ai_rtd_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name,
                rtd_type=rtd_type,
                resistance_config=wiring,
                current_excit_source=ExcitationSource.INTERNAL,
                current_excit_val=current,
                r_0=r0
            )
            channel_names.append(ch.name)

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_strain_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build strain gauge task (internal helper for rebuild)"""
        from nidaqmx.constants import (
            StrainGageBridgeType, BridgeConfiguration, ExcitationSource
        )

        task = nidaqmx.Task(f'Strain_Input_{int(time.time()*1000)}')
        channel_names = []

        bridge_map = {
            'full-bridge': BridgeConfiguration.FULL_BRIDGE,
            'full_bridge': BridgeConfiguration.FULL_BRIDGE,
            'half-bridge': BridgeConfiguration.HALF_BRIDGE,
            'half_bridge': BridgeConfiguration.HALF_BRIDGE,
            'quarter-bridge': BridgeConfiguration.QUARTER_BRIDGE,
            'quarter_bridge': BridgeConfiguration.QUARTER_BRIDGE,
        }

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            strain_config = getattr(ch, 'strain_config', 'full-bridge') or 'full-bridge'
            bridge_config = bridge_map.get(strain_config.lower(), BridgeConfiguration.FULL_BRIDGE)
            excit_voltage = getattr(ch, 'strain_excitation_voltage', 2.5) or 2.5
            gage_factor = getattr(ch, 'strain_gage_factor', 2.0) or 2.0
            resistance = getattr(ch, 'strain_resistance', 350.0) or 350.0

            task.ai_channels.add_ai_strain_gage_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name,
                strain_config=bridge_config,
                voltage_excit_source=ExcitationSource.INTERNAL,
                voltage_excit_val=excit_voltage,
                gage_factor=gage_factor,
                nominal_gage_resistance=resistance
            )
            channel_names.append(ch.name)

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_iepe_task(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build IEPE (accelerometer) task (internal helper for rebuild)"""
        from nidaqmx.constants import ExcitationSource, Coupling

        task = nidaqmx.Task(f'IEPE_Input_{int(time.time()*1000)}')
        channel_names = []

        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            sensitivity = getattr(ch, 'iepe_sensitivity', 100.0) or 100.0
            coupling_str = getattr(ch, 'iepe_coupling', 'AC') or 'AC'
            coupling = Coupling.AC if coupling_str.upper() == 'AC' else Coupling.DC
            current = getattr(ch, 'iepe_current', 0.002) or 0.002

            task.ai_channels.add_ai_accel_chan(
                ch.physical_channel,
                name_to_assign_to_channel=safe_name,
                sensitivity=sensitivity,
                current_excit_source=ExcitationSource.INTERNAL,
                current_excit_val=current
            )
            task.ai_channels[safe_name].ai_coupling = coupling
            channel_names.append(ch.name)

        task.timing.cfg_samp_clk_timing(
            rate=self.config.scan_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=BUFFER_SIZE
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        return {'task': task, 'reader': reader, 'channels': channel_names}

    def _build_counter_tasks(self, channels: List['ChannelConfig']) -> Dict[str, Any]:
        """Build counter tasks (internal helper for rebuild) - returns dict of tasks"""
        from nidaqmx.constants import Edge, CountDirection
        from nidaqmx.stream_readers import CounterReader

        # Counter tasks are individual per channel, return a dict
        tasks = {}
        for ch in channels:
            safe_name = ch.name.replace('/', '_')
            task = nidaqmx.Task(f'Counter_{safe_name}_{int(time.time()*1000)}')

            counter_mode = getattr(ch, 'counter_mode', 'frequency') or 'frequency'
            min_freq = getattr(ch, 'counter_min_freq', 0.1) or 0.1
            max_freq = getattr(ch, 'counter_max_freq', 1000.0) or 1000.0
            edge_str = getattr(ch, 'counter_edge', 'rising') or 'rising'
            edge = Edge.RISING if edge_str.lower() == 'rising' else Edge.FALLING

            if counter_mode == 'frequency':
                task.ci_channels.add_ci_freq_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    min_val=min_freq,
                    max_val=max_freq,
                    edge=edge
                )
            elif counter_mode == 'count':
                task.ci_channels.add_ci_count_edges_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    edge=edge,
                    initial_count=0,
                    count_direction=CountDirection.COUNT_UP
                )
            elif counter_mode == 'period':
                min_period = 1.0 / max_freq if max_freq > 0 else 0.001
                max_period = 1.0 / min_freq if min_freq > 0 else 10.0
                task.ci_channels.add_ci_period_chan(
                    ch.physical_channel,
                    name_to_assign_to_channel=safe_name,
                    min_val=min_period,
                    max_val=max_period,
                    edge=edge
                )

            tasks[f'counter_{ch.name}'] = {
                'task': task,
                'reader': CounterReader(task.in_stream),
                'channels': [ch.name],
                'mode': counter_mode
            }

        return tasks

    def seamless_task_swap(self, new_channels: List['ChannelConfig']) -> bool:
        """Perform a seamless task swap with minimal acquisition downtime.

        This method:
        1. Builds new tasks in parallel (while acquisition continues)
        2. Briefly pauses the scan loop
        3. Stops old tasks
        4. Swaps in new tasks
        5. Starts new tasks
        6. Resumes scan loop

        Total downtime is typically <100ms.

        Args:
            new_channels: Complete list of channel configurations

        Returns:
            True if swap succeeded, False otherwise
        """
        logger.info(f"Seamless task swap requested with {len(new_channels)} channels")

        with self._task_swap_lock:
            try:
                # Step 1: Group channels by type
                tc_channels = [ch for ch in new_channels if ch.channel_type.upper() in ('TC', 'THERMOCOUPLE')]
                voltage_channels = [ch for ch in new_channels if ch.channel_type.upper() in ('VOLTAGE', 'VOLTAGE_INPUT', 'ANALOG')]
                current_channels = [ch for ch in new_channels if ch.channel_type.upper() in ('CURRENT', 'CURRENT_INPUT', '4-20MA')]
                rtd_channels = [ch for ch in new_channels if ch.channel_type.upper() == 'RTD']
                counter_channels = [ch for ch in new_channels if ch.channel_type.upper() == 'COUNTER']
                strain_channels = [ch for ch in new_channels if ch.channel_type.upper() == 'STRAIN']
                iepe_channels = [ch for ch in new_channels if ch.channel_type.upper() == 'IEPE']
                di_channels = [ch for ch in new_channels if ch.channel_type.upper() in ('DI', 'DIGITAL_INPUT')]

                # Step 2: Build new tasks in parallel (acquisition still running)
                logger.info("Building new tasks...")
                new_tasks = {}

                if tc_channels:
                    task_info = self._rebuild_input_task('thermocouple', tc_channels)
                    if task_info:
                        new_tasks['thermocouple'] = task_info

                if voltage_channels:
                    task_info = self._rebuild_input_task('voltage', voltage_channels)
                    if task_info:
                        new_tasks['voltage'] = task_info

                if current_channels:
                    task_info = self._rebuild_input_task('current', current_channels)
                    if task_info:
                        new_tasks['current'] = task_info

                if rtd_channels:
                    task_info = self._rebuild_input_task('rtd', rtd_channels)
                    if task_info:
                        new_tasks['rtd'] = task_info

                if counter_channels:
                    # Counter returns a dict of tasks (one per channel)
                    counter_tasks = self._build_counter_tasks(counter_channels)
                    if counter_tasks:
                        new_tasks.update(counter_tasks)

                if strain_channels:
                    task_info = self._rebuild_input_task('strain', strain_channels)
                    if task_info:
                        new_tasks['strain'] = task_info

                if iepe_channels:
                    task_info = self._rebuild_input_task('iepe', iepe_channels)
                    if task_info:
                        new_tasks['iepe'] = task_info

                if di_channels:
                    task_info = self._rebuild_input_task('digital_input', di_channels)
                    if task_info:
                        new_tasks['digital_input'] = task_info

                # Step 3: Signal scan loop to pause
                logger.info("Pausing scan loop for swap...")
                self._task_swap_in_progress = True
                time.sleep(0.05)  # Allow current scan iteration to complete

                # Step 4: Stop and close old tasks
                old_tasks = self.input_tasks
                for name, task_info in old_tasks.items():
                    try:
                        task_info['task'].stop()
                        task_info['task'].close()
                    except Exception as e:
                        logger.warning(f"Error closing old task {name}: {e}")

                # Step 5: Swap in new tasks
                self.input_tasks = new_tasks

                # Step 6: Start new tasks
                for name, task_info in self.input_tasks.items():
                    try:
                        task_info['task'].start()
                        logger.debug(f"Started new task: {name}")
                    except Exception as e:
                        logger.error(f"Failed to start new task {name}: {e}")

                # Step 7: Resume scan loop
                self._task_swap_in_progress = False
                logger.info(f"Seamless task swap complete: {len(self.input_tasks)} input tasks active")

                # Update channel configurations
                self.channels = {ch.name: ch for ch in new_channels}

                # Publish updated status
                self._publish_status()
                return True

            except Exception as e:
                logger.error(f"Seamless task swap failed: {e}")
                self._task_swap_in_progress = False
                return False

    def _check_physical_channel_collision(
        self,
        physical_channel: str,
        exclude_channel: Optional[str] = None
    ) -> Optional[str]:
        """
        Check if a physical channel is already in use by another tag.

        Args:
            physical_channel: The physical channel path (e.g., "Mod1/ai0")
            exclude_channel: Channel name to exclude from check (for updates)

        Returns:
            Name of the conflicting channel, or None if no collision
        """
        if not physical_channel:
            return None

        for name, ch in self.channels.items():
            # Skip the channel being updated
            if exclude_channel and name == exclude_channel:
                continue

            # Check if same physical channel
            ch_physical = getattr(ch, 'physical_channel', '') or ''
            if ch_physical == physical_channel:
                return name

        return None

    def add_channel_dynamic(self, channel_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Add a channel dynamically without stopping acquisition.

        This is a convenience method that adds a single channel to the
        existing configuration and performs a seamless task swap.

        Args:
            channel_config: Channel configuration dict

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            channel_name = channel_config.get('name', '')
            physical_channel = channel_config.get('physical_channel', '')

            # Check for channel name collision
            if channel_name in self.channels:
                return False, f"Channel '{channel_name}' already exists"

            # Check for physical channel collision
            collision = self._check_physical_channel_collision(physical_channel)
            if collision:
                return False, f"Physical channel '{physical_channel}' is already used by tag '{collision}'"

            # Create ChannelConfig from dict
            new_ch = ChannelConfig(
                name=channel_config['name'],
                channel_type=channel_config.get('channel_type', 'voltage'),
                physical_channel=channel_config.get('physical_channel', ''),
                enabled=channel_config.get('enabled', True),
                units=channel_config.get('units', ''),
                min_value=channel_config.get('min_value', 0),
                max_value=channel_config.get('max_value', 100),
                thermocouple_type=channel_config.get('thermocouple_type', 'K'),
                voltage_range=channel_config.get('voltage_range', 10.0),
                terminal_config=channel_config.get('terminal_config', 'DIFF')
            )

            # Add to existing channels
            current_channels = list(self.channels.values())
            current_channels.append(new_ch)

            # Perform seamless swap
            if self.seamless_task_swap(current_channels):
                return True, f"Channel '{channel_name}' added successfully"
            else:
                return False, "Failed to reconfigure DAQ tasks"

        except Exception as e:
            logger.error(f"Failed to add channel dynamically: {e}")
            return False, str(e)

    def remove_channel_dynamic(self, channel_name: str) -> bool:
        """Remove a channel dynamically without stopping acquisition.

        Args:
            channel_name: Name of channel to remove

        Returns:
            True if channel was removed successfully
        """
        try:
            if channel_name not in self.channels:
                logger.warning(f"Channel not found for removal: {channel_name}")
                return False

            # Remove from current channels
            current_channels = [ch for ch in self.channels.values() if ch.name != channel_name]

            # Perform seamless swap
            return self.seamless_task_swap(current_channels)

        except Exception as e:
            logger.error(f"Failed to remove channel dynamically: {e}")
            return False

    def _scan_loop(self):
        """Main data acquisition loop"""
        logger.info("Scan loop started")

        scan_interval = 1.0 / self.config.scan_rate_hz
        publish_interval = 1.0 / self.config.publish_rate_hz

        while self._acquiring.is_set():
            loop_start = time.time()

            # Pause during seamless task swap
            if self._task_swap_in_progress:
                time.sleep(0.01)  # Brief sleep while swap completes
                continue

            try:
                # Pet the hardware watchdog
                self._pet_watchdog()

                # Read all inputs
                now = time.time()

                # Read all inputs (take snapshot of tasks to avoid race condition)
                current_input_tasks = dict(self.input_tasks)
                for task_name, task_info in current_input_tasks.items():
                    # Digital inputs - on-demand read for immediate safety response
                    # (no buffering delay - critical for E-stops, interlocks, etc.)
                    if task_name == 'digital_input':
                        try:
                            task = task_info['task']
                            channels = task_info['channels']
                            # On-demand read gives IMMEDIATE current state (microseconds)
                            raw_data = task.read(timeout=0.01)

                            with self.values_lock:
                                if isinstance(raw_data, list):
                                    for i, name in enumerate(channels):
                                        self.channel_values[name] = 1.0 if raw_data[i] else 0.0
                                        self.channel_timestamps[name] = now
                                else:
                                    self.channel_values[channels[0]] = 1.0 if raw_data else 0.0
                                    self.channel_timestamps[channels[0]] = now
                        except Exception as e:
                            logger.warning(f"Error reading {task_name}: {e}")
                    elif task_info['reader'] is not None:
                        # Analog inputs with hardware-timed continuous sampling
                        try:
                            task = task_info['task']
                            reader = task_info['reader']
                            channels = task_info['channels']

                            available = task.in_stream.avail_samp_per_chan
                            if available > 0:
                                num_channels = len(channels)
                                samples_to_read = min(available, BUFFER_SIZE)
                                buffer = np.zeros((num_channels, samples_to_read), dtype=np.float64)

                                reader.read_many_sample(buffer, number_of_samples_per_channel=samples_to_read, timeout=0.1)

                                with self.values_lock:
                                    for i, name in enumerate(channels):
                                        value = buffer[i, -1]  # Latest sample

                                        # Apply scaling
                                        ch_config = self.config.channels.get(name)
                                        if ch_config:
                                            value = value * ch_config.scale_slope + ch_config.scale_offset

                                            # Convert current from A to mA
                                            if ch_config.channel_type in ('current', 'current_input'):
                                                value = value * 1000.0

                                        self.channel_values[name] = value
                                        self.channel_timestamps[name] = now
                        except Exception as e:
                            logger.warning(f"Error reading {task_name}: {e}")
                    else:
                        # Fallback on-demand read for any other task without reader
                        try:
                            task = task_info['task']
                            channels = task_info['channels']
                            raw_data = task.read(timeout=0.01)

                            with self.values_lock:
                                if isinstance(raw_data, (list, tuple)):
                                    for i, name in enumerate(channels):
                                        val = raw_data[i] if i < len(raw_data) else 0
                                        self.channel_values[name] = float(val) if isinstance(val, (int, float, bool)) else (1.0 if val else 0.0)
                                        self.channel_timestamps[name] = now
                                else:
                                    self.channel_values[channels[0]] = float(raw_data) if isinstance(raw_data, (int, float)) else (1.0 if raw_data else 0.0)
                                    self.channel_timestamps[channels[0]] = now
                        except Exception as e:
                            logger.warning(f"Error reading {task_name}: {e}")

                # Include output values
                with self.values_lock:
                    for name, value in self.output_values.items():
                        self.channel_values[name] = value
                        self.channel_timestamps[name] = now

                # Get values snapshot for engine processing
                with self.values_lock:
                    values_snapshot = dict(self.channel_values)
                    timestamps_snapshot = dict(self.channel_timestamps)

                # Calculate dt for PID
                dt = now - self._last_scan_time if self._last_scan_time > 0 else scan_interval
                self._last_scan_time = now

                # =====================================================
                # PROCESS ENGINES
                # =====================================================

                # PID Control - must run before outputs are published
                try:
                    pid_outputs = self.pid_engine.process_scan(values_snapshot, dt)
                    # PID outputs are written via the callback
                except Exception as e:
                    logger.error(f"PID engine error: {e}")

                # Trigger Engine - evaluate automation triggers
                try:
                    self.trigger_engine.process_scan(values_snapshot)
                except Exception as e:
                    logger.error(f"Trigger engine error: {e}")

                # Watchdog Engine - monitor for stale/out-of-range values
                try:
                    self.channel_watchdog.process_scan(values_snapshot, timestamps_snapshot)
                except Exception as e:
                    logger.error(f"Watchdog engine error: {e}")

                # Enhanced Alarm Manager - process all channels
                try:
                    for ch_name, ch_value in values_snapshot.items():
                        self.enhanced_alarm_manager.process_value(ch_name, ch_value, now)
                except Exception as e:
                    logger.error(f"Enhanced alarm manager error: {e}")

                # Publish channel values at publish_rate_hz (not scan_rate_hz)
                # This reduces MQTT message load significantly
                if now - self._last_publish_time >= publish_interval:
                    self._publish_channel_values()
                    self._last_publish_time = now

                # Check alarms and safety limits (autonomous operation)
                # This evaluates ISA-18.2 alarms and triggers safety actions locally

                for ch_name, ch_value in values_snapshot.items():
                    try:
                        # Alarm evaluation (HI/LO/HIHI/LOLO) - publishes events to PC
                        self._check_alarms(ch_name, ch_value)
                        # Safety limit evaluation - triggers safety actions for HIHI/LOLO
                        self._check_safety_limits(ch_name, ch_value)
                    except Exception as e:
                        logger.error(f"Alarm/safety check error for {ch_name}: {e}")

                # Evaluate local interlocks (trips if armed + interlock failed)
                if self.local_safety:
                    try:
                        self.local_safety.evaluate_all()
                    except Exception as e:
                        logger.error(f"Local safety evaluation error: {e}")

            except Exception as e:
                logger.error(f"Scan loop error: {e}")

            # Maintain scan rate
            elapsed = time.time() - loop_start
            sleep_time = scan_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Scan loop stopped")

    def _reverse_scale_output(self, ch_config: ChannelConfig, eng_value: float) -> float:
        """
        Reverse scaling: convert engineering units to raw output value (V or mA).

        For outputs, we receive values in engineering units (%, RPM, PSI, etc.)
        and need to convert to the raw electrical signal (0-10V, 4-20mA, etc.)

        Examples:
            - 50% → 5.0V (linear 0-100% to 0-10V)
            - 250 RPM → 5.0V (map 0-500 RPM to 0-10V)
            - 75 PSI → 16mA (4-20mA scaling 0-100 PSI)
        """
        # 4-20mA scaling (current outputs)
        if ch_config.four_twenty_scaling and ch_config.eng_units_min is not None and ch_config.eng_units_max is not None:
            span = ch_config.eng_units_max - ch_config.eng_units_min
            if span != 0:
                normalized = (eng_value - ch_config.eng_units_min) / span
                raw_ma = 4.0 + (normalized * 16.0)  # 4-20mA range
                return raw_ma / 1000.0  # Convert mA to A if needed, or return mA directly
            return 0.004  # 4mA minimum

        # Map scaling (voltage outputs)
        if ch_config.scale_type == 'map':
            if (ch_config.scaled_min is not None and ch_config.scaled_max is not None and
                ch_config.pre_scaled_min is not None and ch_config.pre_scaled_max is not None):
                scaled_span = ch_config.scaled_max - ch_config.scaled_min
                if scaled_span != 0:
                    normalized = (eng_value - ch_config.scaled_min) / scaled_span
                    raw = ch_config.pre_scaled_min + (normalized * (ch_config.pre_scaled_max - ch_config.pre_scaled_min))
                    return raw
            return ch_config.pre_scaled_min or 0.0

        # Linear scaling (y = mx + b → x = (y - b) / m)
        if ch_config.scale_slope != 0:
            raw = (eng_value - ch_config.scale_offset) / ch_config.scale_slope
            return raw

        # No scaling - pass through
        return eng_value

    def _write_output(self, channel_name: str, value: Any, source: str = 'manual') -> bool:
        """Write to an output channel (digital or analog)

        Args:
            channel_name: Name of output channel
            value: Value to write
            source: Source of write ('manual', 'script', 'safety', 'session')
                   - 'safety' bypasses session locks for safety actions
                   - Other sources respect session locks
        """
        if channel_name not in self.output_tasks:
            logger.warning(f"Output channel not found: {channel_name}")
            return False

        # Enforce session locks (except for safety actions which must always work)
        if source != 'safety' and self.session.active and channel_name in self.session.locked_outputs:
            logger.warning(f"Write blocked - channel '{channel_name}' is session-locked")
            return False

        # SIL 1: Redundant interlock check at edge node (PC SafetyManager also validates)
        # Safety source bypasses this - safety actions ARE the interlock response
        if source != 'safety' and self.local_safety and self.local_safety.is_output_blocked(channel_name):
            logger.warning(f"Write blocked - channel '{channel_name}' blocked by interlock (SIL 1)")
            return False

        try:
            task = self.output_tasks[channel_name]
            ch_config = self.config.channels.get(channel_name)

            if ch_config and ch_config.channel_type in ('analog_output', 'voltage_output', 'current_output'):
                # Analog output - apply REVERSE scaling (engineering units → raw V/mA)
                eng_value = float(value) if value is not None else 0.0
                raw_value = self._reverse_scale_output(ch_config, eng_value)

                # Clamp to hardware range
                v_range = ch_config.voltage_range or 10.0
                raw_value = max(0.0, min(v_range, raw_value))

                task.write(raw_value)
                self.output_values[channel_name] = eng_value  # Store engineering value for display
                logger.debug(f"Wrote AO {channel_name}: eng={eng_value} → raw={raw_value:.4f}")
            else:
                # Digital output - write boolean
                bool_value = bool(value) if not isinstance(value, bool) else value

                # Apply invert
                if ch_config and ch_config.invert:
                    bool_value = not bool_value

                task.write(bool_value)
                self.output_values[channel_name] = 1.0 if bool_value else 0.0
                logger.debug(f"Wrote DO {channel_name} = {bool_value}")

            return True

        except Exception as e:
            logger.error(f"Failed to write {channel_name}: {e}")
            return False

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def _auto_start_scripts(self, run_mode: str):
        """Auto-start scripts matching the given run_mode (acquisition or session)"""
        for script_id, script in self.scripts.items():
            script_run_mode = script.get('run_mode', 'manual')
            enabled = script.get('enabled', True)
            if enabled and script_run_mode == run_mode:
                logger.info(f"Auto-starting {run_mode} script: {script_id}")
                self._start_script(script_id)

    def _auto_stop_scripts(self, run_mode: str):
        """Auto-stop scripts matching the given run_mode and wait for them to stop"""
        scripts_to_stop = []
        for script_id, script in self.scripts.items():
            script_run_mode = script.get('run_mode', 'manual')
            if script_run_mode == run_mode:
                if script_id in self.script_threads and self.script_threads[script_id].is_alive():
                    logger.info(f"Auto-stopping {run_mode} script: {script_id}")
                    self._stop_script(script_id)
                    scripts_to_stop.append(script_id)

        # Wait for all scripts to actually stop (max 5 seconds)
        if scripts_to_stop:
            logger.info(f"Waiting for {len(scripts_to_stop)} scripts to stop...")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                still_running = [sid for sid in scripts_to_stop
                                if sid in self.script_threads and self.script_threads[sid].is_alive()]
                if not still_running:
                    logger.info("All scripts stopped")
                    break
                time.sleep(0.1)
            else:
                still_running = [sid for sid in scripts_to_stop
                                if sid in self.script_threads and self.script_threads[sid].is_alive()]
                if still_running:
                    logger.warning(f"Scripts did not stop in time: {still_running}")

    def _start_script(self, script_id: str, max_runtime_seconds: float = 300.0):
        """Start executing a Python script with timeout

        Args:
            script_id: ID of script to start
            max_runtime_seconds: Maximum runtime before forced stop (default 5 min)
        """
        if script_id not in self.scripts:
            logger.warning(f"Script not found: {script_id}")
            return

        script = self.scripts[script_id]

        if script_id in self.script_threads and self.script_threads[script_id].is_alive():
            logger.warning(f"Script already running: {script_id}")
            return

        # Store start time for timeout tracking
        script['_start_time'] = time.time()
        script['_max_runtime'] = max_runtime_seconds

        # Start script in thread
        thread = threading.Thread(
            target=self._run_script,
            args=(script_id, script),
            name=f"Script-{script_id}",
            daemon=True
        )
        self.script_threads[script_id] = thread
        thread.start()

        # Start timeout monitor thread
        monitor = threading.Thread(
            target=self._monitor_script_timeout,
            args=(script_id, max_runtime_seconds),
            name=f"ScriptMonitor-{script_id}",
            daemon=True
        )
        monitor.start()

        logger.info(f"Started script: {script_id} (max runtime: {max_runtime_seconds}s)")

    def _monitor_script_timeout(self, script_id: str, timeout_seconds: float):
        """Monitor script for timeout and force stop if exceeded"""
        start_time = time.time()
        check_interval = 1.0  # Check every second

        while script_id in self.script_threads:
            thread = self.script_threads.get(script_id)
            if not thread or not thread.is_alive():
                return  # Script finished normally

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"SCRIPT TIMEOUT: {script_id} exceeded {timeout_seconds}s - forcing stop")
                # Signal script to stop
                if script_id in self.scripts:
                    self.scripts[script_id]['_stop_requested'] = True
                    self.scripts[script_id]['_timeout_exceeded'] = True

                # Wait a bit for graceful stop
                time.sleep(2.0)

                # If still running, we can't kill the thread but we log and publish error
                if thread.is_alive():
                    logger.error(f"Script {script_id} did not respond to stop request after timeout")
                    self._publish(f"{self.get_topic_base()}/scripts/error", {
                        'script_id': script_id,
                        'error': f'Script timeout after {timeout_seconds}s - not responding to stop',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                return

            time.sleep(check_interval)
        self._publish_script_status()

    def _stop_script(self, script_id: str):
        """Stop a running script"""
        # Scripts should check self._running flag periodically
        if script_id in self.script_threads:
            # Mark for stop (scripts should poll this)
            self.scripts[script_id]['_stop_requested'] = True
            logger.info(f"Stop requested for script: {script_id}")
            self._publish_script_status()

    def _run_script(self, script_id: str, script: Dict[str, Any]):
        """Execute a Python script with enhanced environment"""
        code = script.get('code', '')

        # Helper function for wait_for (sleep that respects stop event)
        def wait_for(seconds: float) -> bool:
            """Sleep for given seconds, respecting stop request. Returns True if stopped."""
            interval = 0.1  # Check stop flag every 100ms
            elapsed = 0.0
            while elapsed < seconds:
                if script.get('_stop_requested', False):
                    return True
                time.sleep(min(interval, seconds - elapsed))
                elapsed += interval
            return False

        # Helper function for wait_until (wait for condition)
        def wait_until(condition_fn, timeout: float = 60.0) -> bool:
            """Wait until condition returns True. Returns False if timeout."""
            start = time.time()
            while time.time() - start < timeout:
                if script.get('_stop_requested', False):
                    return False
                if condition_fn():
                    return True
                time.sleep(0.1)
            return False

        # Create execution environment with expanded API
        env = {
            # Core script APIs
            'tags': self._create_tags_api(),
            'outputs': self._create_outputs_api(),
            'publish': self._create_publish_api(),
            'session': self._create_session_api(),

            # Control flow
            'next_scan': lambda: time.sleep(1.0 / self.config.scan_rate_hz),
            'wait_for': wait_for,
            'wait_until': wait_until,
            'should_stop': lambda: script.get('_stop_requested', False),

            # State persistence
            'persist': lambda key, value: self.script_persistence.persist(script_id, key, value),
            'restore': lambda key, default=None: self.script_persistence.restore(script_id, key, default),

            # Helper classes
            'RateCalculator': RateCalculator,
            'Accumulator': Accumulator,
            'EdgeDetector': EdgeDetector,
            'RollingStats': RollingStats,
            'Scheduler': Scheduler,

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
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            # Scientific computing (matches browser Pyodide environment)
            'numpy': np if NIDAQMX_AVAILABLE else None,
            'np': np if NIDAQMX_AVAILABLE else None,

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
            'print': lambda *args: logger.info(f"[Script {script_id}] {' '.join(str(a) for a in args)}"),
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
            'True': True,
            'False': False,
            'None': None,

            # Safety functions
            'trigger_safe_state': lambda reason='script': self._set_safe_state(reason),
            'execute_safety_action': lambda action, source='script': self._execute_safety_action(action, source),
            'check_interlock': self._check_interlock,

            # SECURITY: Restrict access to Python builtins
            # This prevents access to __import__, eval, exec, open, etc.
            '__builtins__': {},
        }

        try:
            # Strip 'await' keywords for sync execution
            code = code.replace('await ', '')

            # Execute with restricted environment
            exec(code, env, env)
            logger.info(f"Script completed: {script_id}")
        except Exception as e:
            logger.error(f"Script error ({script_id}): {e}")
        finally:
            script['_stop_requested'] = False
            self._publish_script_status()

    def _create_tags_api(self):
        """Create tags API for scripts"""
        class TagsAPI:
            def __init__(self, parent):
                self._parent = parent

            def get(self, name: str) -> float:
                with self._parent.values_lock:
                    return self._parent.channel_values.get(name, 0.0)

            def __getattr__(self, name: str) -> float:
                return self.get(name)

        return TagsAPI(self)

    def _create_outputs_api(self):
        """Create outputs API for scripts"""
        class OutputsAPI:
            def __init__(self, parent):
                self._parent = parent

            def set(self, name: str, value: Any) -> bool:
                """Set output value. Returns False if session-locked."""
                return self._parent._write_output(name, value, source='script')

            def is_locked(self, name: str) -> bool:
                """Check if an output is session-locked"""
                return self._parent.session.active and name in self._parent.session.locked_outputs

        return OutputsAPI(self)

    def _create_publish_api(self):
        """Create publish API for scripts to send values to dashboard"""
        def publish(name: str, value: Any):
            self._publish(
                self.get_topic('script', 'values'),
                {name: value}
            )
        return publish

    def _create_session_api(self):
        """Create session API for scripts"""
        class SessionAPI:
            def __init__(self, parent):
                self._parent = parent

            @property
            def active(self) -> bool:
                return self._parent.session.active

            @property
            def name(self) -> str:
                return self._parent.session.name

            @property
            def operator(self) -> str:
                return self._parent.session.operator

            @property
            def duration(self) -> float:
                """Session duration in seconds"""
                if self._parent.session.start_time:
                    return time.time() - self._parent.session.start_time
                return 0.0

            def is_output_locked(self, channel: str) -> bool:
                """Check if output is locked by session"""
                return channel in self._parent.session.locked_outputs

        return SessionAPI(self)

    # =========================================================================
    # MQTT PUBLISHING
    # =========================================================================

    def _publish(self, topic: str, payload: Dict[str, Any], retain: bool = False):
        """Publish message to MQTT"""
        if self.mqtt_client and self._mqtt_connected.is_set():
            try:
                self.mqtt_client.publish(
                    topic,
                    json.dumps(payload),
                    qos=0,
                    retain=retain
                )
            except Exception as e:
                logger.warning(f"Publish failed: {e}")

    def _publish_status(self):
        """Publish system status with hardware info for discovery"""
        hw_info = self._detect_hardware_info()
        status = {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'crio',
            'node_id': self.config.node_id,
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            # Hardware info for discovery
            'ip_address': self._get_local_ip(),  # Get fresh each time (config may not be ready at startup)
            'product_type': hw_info['product_type'],
            'serial_number': hw_info['serial_number'],
            'device_name': hw_info.get('device_name', ''),  # Full NI-DAQmx device name for remote access
            'modules': hw_info['modules'],
            # Config version for sync tracking (PC can detect stale config)
            'config_version': self.config_version,
            'config_timestamp': self.config_timestamp
        }
        self._publish(self.get_topic('status', 'system'), status, retain=True)

    def _publish_channel_values(self):
        """Publish channel values to MQTT as a single batched message"""
        with self.values_lock:
            # Batch all channel values into a single message to reduce MQTT load
            # Format: { "channel_name": {"value": x, "timestamp": t, "acquisition_ts_us": us, "quality": q}, ... }
            batch = {}

            # Include INPUT channel values
            for name, value in self.channel_values.items():
                timestamp = self.channel_timestamps.get(name, 0)
                batch[name] = {
                    'value': value,
                    'timestamp': timestamp,
                    # SOE: Source timestamp in microseconds for sequence-of-events analysis
                    'acquisition_ts_us': int(timestamp * 1_000_000),
                    # OPC UA style quality code
                    'quality': get_value_quality(value)
                }

            # Include OUTPUT channel values so dashboard shows current output state
            for name, value in self.output_values.items():
                if name not in batch:  # Don't overwrite if already present
                    batch[name] = {
                        'value': value,
                        'timestamp': time.time(),
                        'acquisition_ts_us': int(time.time() * 1_000_000),
                        'quality': 'good',
                        'type': 'output'  # Mark as output for dashboard
                    }

            if batch:
                self._publish(
                    self.get_topic('channels', 'batch'),
                    batch
                )

    def _publish_script_status(self):
        """Publish script status"""
        status = {}
        for script_id, script in self.scripts.items():
            thread = self.script_threads.get(script_id)
            status[script_id] = {
                'name': script.get('name', script_id),
                'running': thread is not None and thread.is_alive(),
                'stop_requested': script.get('_stop_requested', False)
            }
        self._publish(self.get_topic('script', 'status'), status)

    def _publish_heartbeat(self):
        """Publish heartbeat with node info for discovery fallback"""
        self._heartbeat_sequence += 1
        self._publish(
            self.get_topic('heartbeat'),
            {
                'seq': self._heartbeat_sequence,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'acquiring': self._acquiring.is_set(),
                'pc_connected': self.pc_connected,
                # Include node info so DAQ service can use heartbeat for discovery
                'node_type': 'crio',
                'node_id': self.config.node_id,
                'channels': len(self.config.channels),
            }
        )

    # =========================================================================
    # HEARTBEAT
    # =========================================================================

    def _heartbeat_loop(self):
        """Heartbeat thread"""
        while self._running.is_set():
            self._publish_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    # =========================================================================
    # AUTO-DISCOVERY CHANNEL CREATION
    # =========================================================================

    def _auto_create_channels_from_hardware(self):
        """
        Auto-create channel configs for all detected hardware channels.
        This enables "magic" mode where the cRIO reads everything automatically
        without requiring explicit configuration from NISystem.
        """
        hw_info = self._detect_hardware_info()

        created_count = 0
        for module in hw_info.get('modules', []):
            for ch in module.get('channels', []):
                # Use local_name for the physical channel (what nidaqmx uses locally)
                local_name = ch.get('local_name', ch.get('name', ''))
                if not local_name:
                    continue

                # Skip if already configured
                if local_name in self.config.channels:
                    continue

                # Get category and hardware channel type
                category = ch.get('category', 'voltage')
                hw_channel_type = ch.get('channel_type', 'analog_input')

                # Map category + hw_channel_type to our channel_type
                if hw_channel_type == 'digital_input':
                    channel_type = 'digital_input'
                elif hw_channel_type == 'digital_output':
                    channel_type = 'digital_output'
                elif hw_channel_type == 'analog_output':
                    channel_type = 'analog_output'
                elif hw_channel_type == 'counter_input':
                    channel_type = 'counter'
                elif category == 'thermocouple':
                    channel_type = 'thermocouple'
                elif category == 'rtd':
                    channel_type = 'rtd'
                elif category == 'current':
                    channel_type = 'current'
                elif category == 'current_output':
                    channel_type = 'analog_output'  # Current output is still AO
                else:
                    channel_type = 'voltage'  # Default for analog inputs

                # Create channel config
                tc_type = 'K' if channel_type == 'thermocouple' else 'K'

                channel_config = ChannelConfig(
                    name=local_name,  # Use local path as name (e.g., "Mod1/ai0")
                    physical_channel=local_name,
                    channel_type=channel_type,
                    thermocouple_type=tc_type,
                )

                self.config.channels[local_name] = channel_config
                created_count += 1
                logger.debug(f"Auto-created channel: {local_name} type={channel_type}")

        if created_count > 0:
            logger.info(f"Auto-created {created_count} channel configs from detected hardware")

    # =========================================================================
    # MAIN SERVICE LIFECYCLE
    # =========================================================================

    def _reset(self):
        """Reset service to initial state"""
        logger.info("Resetting cRIO node...")
        self._stop_acquisition()

        # Clear values
        with self.values_lock:
            self.channel_values.clear()
            self.channel_timestamps.clear()

        # Reset outputs to safe state
        for name, ch_config in self.config.channels.items():
            if ch_config.channel_type == 'digital_output':
                self._write_output(name, ch_config.default_state)

        self._publish_status()
        logger.info("Reset complete")

    def run(self):
        """Main service entry point"""
        logger.info("="*60)
        logger.info("cRIO Node Service Starting")
        logger.info("="*60)

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running.set()

        # Detect hardware FIRST (before MQTT to avoid race conditions)
        # This caches the hardware info for later use
        logger.info("Detecting hardware...")
        self._detect_hardware_info()

        # Auto-create channels from detected hardware if none configured
        # This enables "magic" mode - cRIO reads everything automatically
        if not self.config.channels:
            self._auto_create_channels_from_hardware()

        # Setup MQTT (will retry on failure)
        # Hardware info is already cached, so callbacks won't trigger detection
        self._setup_mqtt()

        # Configure hardware
        if self.config.channels:
            self._configure_hardware()

        # Initialize local safety manager
        self._init_local_safety()

        # Start heartbeat
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Heartbeat",
            daemon=True
        )
        self.heartbeat_thread.start()

        # Start watchdog monitor (independent safety thread)
        self.watchdog_monitor_thread = threading.Thread(
            target=self._watchdog_monitor_loop,
            name="WatchdogMonitor",
            daemon=True
        )
        self.watchdog_monitor_thread.start()

        # Auto-start acquisition if we have channels
        if self.config.channels:
            self._start_acquisition()

        # Publish online status
        self._publish_status()

        logger.info("cRIO Node Service running")
        logger.info(f"Node ID: {self.config.node_id}")
        logger.info(f"Channels: {len(self.config.channels)}")
        logger.info(f"MQTT: {self.config.mqtt_broker}:{self.config.mqtt_port}")

        # Main loop - just keep alive
        try:
            while self._running.is_set():
                time.sleep(1.0)

                # Check MQTT connection - attempt reconnect if disconnected
                if not self._mqtt_connected.is_set():
                    logger.info("MQTT disconnected - attempting reconnect...")
                    self._connect_mqtt()

                # Check PC connection timeout (30 seconds)
                if time.time() - self.last_pc_contact > 30:
                    if self.pc_connected:
                        logger.warning("Lost contact with PC - continuing in standalone mode")
                        self.pc_connected = False

                # Check session timeout (for autonomous operation)
                self._check_session_timeout()

                # Periodic status publish for discovery (every STATUS_PUBLISH_INTERVAL)
                # This ensures NISystem can discover us even if it starts after we do
                if time.time() - self._last_status_time > STATUS_PUBLISH_INTERVAL:
                    self._publish_status()
                    self._last_status_time = time.time()
        except KeyboardInterrupt:
            pass

        self.shutdown()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self._running.clear()

    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down cRIO Node Service...")

        self._running.clear()
        self._stop_acquisition()

        # Wait for background threads to stop
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            logger.debug("Waiting for heartbeat thread to stop...")
            self.heartbeat_thread.join(timeout=3.0)
            if self.heartbeat_thread.is_alive():
                logger.warning("Heartbeat thread did not stop in time")

        if self.watchdog_monitor_thread and self.watchdog_monitor_thread.is_alive():
            logger.debug("Waiting for watchdog monitor thread to stop...")
            self.watchdog_monitor_thread.join(timeout=3.0)
            if self.watchdog_monitor_thread.is_alive():
                logger.warning("Watchdog monitor thread did not stop in time")

        # Publish offline status
        self._publish(
            self.get_topic('status', 'system'),
            {'status': 'offline', 'node_type': 'crio'},
            retain=True
        )

        # Close tasks
        self._close_tasks()

        # Disconnect MQTT
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        logger.info("cRIO Node Service stopped")


def main():
    parser = argparse.ArgumentParser(description='cRIO Node Service for NISystem')
    parser.add_argument(
        '-c', '--config-dir',
        type=str,
        default=str(DEFAULT_CONFIG_DIR),
        help=f'Configuration directory (default: {DEFAULT_CONFIG_DIR})'
    )
    parser.add_argument(
        '--broker',
        type=str,
        help='MQTT broker address (overrides config and env)'
    )
    parser.add_argument(
        '--port',
        type=int,
        help='MQTT broker port (overrides config and env)'
    )
    parser.add_argument(
        '--node-id',
        type=str,
        help='Node ID (overrides config and env)'
    )

    args = parser.parse_args()

    service = CRIONodeService(config_dir=Path(args.config_dir))

    # Priority: command-line args > environment variables > config file > defaults
    # This allows systemd to set env vars from .env file

    # MQTT Broker
    broker = args.broker or os.environ.get('MQTT_BROKER')
    if broker:
        service.config.mqtt_broker = broker

    # MQTT Port
    port = args.port or os.environ.get('MQTT_PORT')
    if port:
        service.config.mqtt_port = int(port) if isinstance(port, str) else port

    # Node ID
    node_id = args.node_id or os.environ.get('NODE_ID')
    if node_id:
        service.config.node_id = node_id

    service.run()


if __name__ == '__main__':
    main()
