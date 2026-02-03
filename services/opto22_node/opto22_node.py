#!/usr/bin/env python3
"""
Opto22 Node Service for NISystem

Standalone service that runs ON the groov EPIC/RIO and:
1. Connects to NISystem PC's MQTT broker as a client
2. Receives configuration from NISystem and saves locally
3. Reads/writes I/O via local REST API
4. Continues running even if PC disconnects
5. Executes Python scripts pushed from NISystem

Architecture:
    NISystem PC                              groov EPIC/RIO
    ┌─────────────────┐      MQTT      ┌─────────────────────┐
    │  Dashboard      │◄──────────────►│  Opto22 Node Service│
    │  Backend        │   Config/Data   │  - Local config     │
    │  Project Mgmt   │                 │  - REST API I/O     │
    └─────────────────┘                 │  - Python scripts   │
                                        └─────────────────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ I/O Modules │
                                        │ (AI,AO,DI,DO)│
                                        └─────────────┘

Safe State Behavior:
- Software watchdog monitors scan loop
- If scan loop stops, outputs go to safe state
- PAC Control on groov EPIC provides additional hardware-level safety
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
import re
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import argparse

# MQTT client
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

# HTTP client for REST API
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("WARNING: requests not available - install with: pip install requests")

# Try to import numpy for script support
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Opto22Node')

# Constants
DEFAULT_CONFIG_DIR = Path('/home/dev/nisystem')  # groov EPIC Linux path
DEFAULT_CONFIG_FILE = 'opto22_config.json'
WATCHDOG_TIMEOUT = 2.0  # seconds - outputs go safe if we don't pet watchdog
SAMPLE_RATE_HZ = 10
BUFFER_SIZE = 100
HEARTBEAT_INTERVAL = 2.0  # seconds
STATUS_PUBLISH_INTERVAL = 30.0  # seconds - periodic status for discovery

# Opto22 REST API endpoints (local)
OPTO22_API_BASE = "https://localhost"
OPTO22_ANALOG_INPUTS = "/api/v1/device/strategy/ios/analogInputs"
OPTO22_ANALOG_OUTPUTS = "/api/v1/device/strategy/ios/analogOutputs"
OPTO22_DIGITAL_INPUTS = "/api/v1/device/strategy/ios/digitalInputs"
OPTO22_DIGITAL_OUTPUTS = "/api/v1/device/strategy/ios/digitalOutputs"
OPTO22_SYSTEM_INFO = "/api/v1/device/info"
OPTO22_STRATEGY_VARS = "/api/v1/device/strategy/vars"

# OPC UA style quality code thresholds
OPEN_THERMOCOUPLE_THRESHOLD = 1e300  # Very large values indicate sensor failure
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
    Persistent state storage for scripts on Opto22.
    Stores to /var/lib/opto22_node/script_state.json
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
    """ISA-18.2 alarm states - evaluated locally on Opto22"""
    NORMAL = "normal"
    HI = "hi"           # Warning high
    HIHI = "hihi"       # Critical high (triggers safety action)
    LO = "lo"           # Warning low
    LOLO = "lolo"       # Critical low (triggers safety action)


@dataclass
class ChannelConfig:
    """Channel configuration matching NISystem format"""
    name: str
    physical_channel: str  # Opto22 path: module_index/channel_index
    channel_type: str  # analog_input, analog_output, digital_input, digital_output

    # Opto22-specific settings
    module_index: int = 0
    channel_index: int = 0

    # Output settings
    default_state: float = 0.0
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

    # Safety settings (for autonomous operation)
    safety_action: Optional[str] = None      # Name of safety action to trigger on limit violation
    safety_interlock: Optional[str] = None   # Boolean expression that must be True for writes
    expected_state: Optional[bool] = None    # For digital inputs - expected safe state


@dataclass
class SafetyActionConfig:
    """
    Safety action configuration for autonomous Opto22 operation.

    When triggered, sets specified outputs to safe values.
    This runs locally on Opto22 without PC involvement.
    """
    name: str
    description: str = ""
    actions: Dict[str, Any] = field(default_factory=dict)  # channel_name -> safe_value
    trigger_alarm: bool = False
    alarm_message: str = ""


@dataclass
class SessionState:
    """
    Session state for autonomous operation.

    Tracks test session state locally on Opto22 so it continues
    even if PC disconnects.
    """
    active: bool = False
    start_time: Optional[float] = None
    name: str = ""
    operator: str = ""
    locked_outputs: List[str] = field(default_factory=list)  # Outputs locked during session
    timeout_minutes: float = 0  # Auto-stop after N minutes (0 = no timeout)


class LatchState(Enum):
    """Safety latch states for local Opto22 operation"""
    SAFE = "safe"          # Latch is disarmed, outputs blocked
    ARMED = "armed"        # Latch is armed, outputs allowed
    TRIPPED = "tripped"    # System tripped due to safety violation


@dataclass
class LocalInterlockConfig:
    """Local interlock configuration for autonomous Opto22 operation"""
    id: str
    name: str
    enabled: bool = True
    conditions: List[Dict[str, Any]] = field(default_factory=list)  # Simplified conditions
    condition_logic: str = "AND"  # AND or OR
    output_channels: List[str] = field(default_factory=list)  # Channels blocked when failed


class LocalSafetyManager:
    """
    Local safety manager for autonomous Opto22 operation.

    Provides:
    - Local interlock evaluation based on channel values
    - Local latch state machine (SAFE → ARMED → TRIPPED)
    - Trip actions when safety limits violated while armed
    - Syncs with PC SafetyManager when connected

    This runs independently on Opto22, ensuring safety logic continues
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
            'source': 'opto22_local',
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
            logger.warning(f"Safety condition evaluation failed: {val} {op} {target}: {e}")
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


# =============================================================================
# TRIGGER ENGINE
# =============================================================================

class TriggerEngine:
    def __init__(self):
        self.triggers: Dict[str, Dict[str, Any]] = {}
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self._is_acquiring = False
        self._last_values: Dict[str, bool] = {}

    def on_acquisition_start(self): self._is_acquiring = True
    def on_acquisition_stop(self): self._is_acquiring = False

    def process_scan(self, channel_values: Dict[str, float]):
        if not self._is_acquiring: return
        for tid, trigger in self.triggers.items():
            if not trigger.get('enabled', True): continue
            cond = trigger.get('condition', {})
            channel = cond.get('channel')
            if not channel or channel not in channel_values: continue
            val = channel_values[channel]
            threshold = cond.get('threshold', 0)
            op = cond.get('operator', '>')
            met = False
            if op == '>': met = val > threshold
            elif op == '<': met = val < threshold
            elif op == '>=': met = val >= threshold
            elif op == '<=': met = val <= threshold
            elif op == '==': met = abs(val - threshold) < 0.001
            was = self._last_values.get(tid, False)
            self._last_values[tid] = met
            if met and not was:
                for action in trigger.get('actions', []):
                    self._execute_action(action, trigger)

    def _execute_action(self, action: Dict, trigger: Dict):
        atype = action.get('type', '')
        if atype == 'setOutput' and self.set_output:
            self.set_output(action.get('channel'), action.get('value'))
        elif atype == 'runSequence' and self.run_sequence:
            self.run_sequence(action.get('sequenceId'))
        elif atype == 'notification' and self.publish_notification:
            self.publish_notification('trigger', trigger.get('name', ''), action.get('message', ''))

    def load_config(self, config: Dict[str, Any]):
        self.triggers = {t['id']: t for t in config.get('triggers', [])}


# =============================================================================
# WATCHDOG ENGINE
# =============================================================================

class WatchdogEngine:
    def __init__(self):
        self.watchdogs: Dict[str, Dict[str, Any]] = {}
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self.raise_alarm: Optional[Callable[[str, str, str], None]] = None
        self._is_acquiring = False
        self._triggered: Dict[str, bool] = {}
        self._last_values: Dict[str, tuple] = {}

    def on_acquisition_start(self): self._is_acquiring = True
    def on_acquisition_stop(self): self._is_acquiring = False

    def process_scan(self, channel_values: Dict[str, float], timestamps: Dict[str, float] = None):
        if not self._is_acquiring: return
        now = time.time()
        for wid, wd in self.watchdogs.items():
            if not wd.get('enabled', True): continue
            channels = wd.get('channels', [])
            cond = wd.get('condition', {})
            ctype = cond.get('type', 'stale_data')
            triggered_chs = []
            for ch in channels:
                if ch not in channel_values: continue
                val = channel_values[ch]
                ts = timestamps.get(ch, now) if timestamps else now
                if ctype == 'stale_data':
                    max_stale = cond.get('maxStaleMs', 5000) / 1000.0
                    if now - ts > max_stale: triggered_chs.append(ch)
                elif ctype == 'out_of_range':
                    min_v, max_v = cond.get('minValue'), cond.get('maxValue')
                    if (min_v is not None and val < min_v) or (max_v is not None and val > max_v):
                        triggered_chs.append(ch)
            if triggered_chs and not self._triggered.get(wid, False):
                self._triggered[wid] = True
                for action in wd.get('actions', []):
                    self._execute_action(action, wd)
                logger.warning(f"Watchdog triggered: {wd.get('name')} on {triggered_chs}")
            elif not triggered_chs and self._triggered.get(wid, False):
                self._triggered[wid] = False
                for action in wd.get('recoveryActions', []):
                    self._execute_action(action, wd)

    def _execute_action(self, action: Dict, wd: Dict):
        atype = action.get('type', '')
        if atype == 'setOutput' and self.set_output:
            self.set_output(action.get('channel'), action.get('value'))
        elif atype == 'notification' and self.publish_notification:
            self.publish_notification('watchdog', wd.get('name', ''), action.get('message', ''))
        elif atype == 'alarm' and self.raise_alarm:
            self.raise_alarm(wd.get('id', ''), action.get('severity', 'warning'), action.get('message', ''))

    def load_config(self, config: Dict[str, Any]):
        self.watchdogs = {w['id']: w for w in config.get('watchdogs', [])}


# =============================================================================
# ENHANCED ALARM MANAGER
# =============================================================================

class AlarmSeverity(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class FullAlarmState(Enum):
    NORMAL = "normal"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RETURNED = "returned"
    SHELVED = "shelved"


class LatchBehavior(Enum):
    AUTO_CLEAR = "auto_clear"
    LATCH = "latch"


@dataclass
class AlarmConfig:
    id: str
    channel: str
    name: str
    enabled: bool = True
    severity: AlarmSeverity = AlarmSeverity.MEDIUM
    high_high: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    low_low: Optional[float] = None
    deadband: float = 0.0
    latch_behavior: LatchBehavior = LatchBehavior.AUTO_CLEAR
    safety_action: Optional[str] = None

    @staticmethod
    def from_dict(d: dict) -> 'AlarmConfig':
        return AlarmConfig(id=d.get('id', ''), channel=d.get('channel', ''), name=d.get('name', ''),
                           enabled=d.get('enabled', True), severity=AlarmSeverity[d.get('severity', 'MEDIUM')],
                           high_high=d.get('high_high'), high=d.get('high'), low=d.get('low'), low_low=d.get('low_low'),
                           deadband=d.get('deadband', 0.0), latch_behavior=LatchBehavior(d.get('latch_behavior', 'auto_clear')),
                           safety_action=d.get('safety_action'))


@dataclass
class ActiveAlarm:
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
    message: str = ""

    def to_dict(self) -> dict:
        return {'alarm_id': self.alarm_id, 'channel': self.channel, 'name': self.name,
                'severity': self.severity.name, 'state': self.state.value, 'threshold_type': self.threshold_type,
                'triggered_value': self.triggered_value, 'current_value': self.current_value,
                'triggered_at': self.triggered_at.isoformat(), 'message': self.message}


class EnhancedAlarmManager:
    def __init__(self, publish_callback: Optional[Callable] = None):
        self.publish_callback = publish_callback
        self.lock = threading.RLock()
        self.alarm_configs: Dict[str, AlarmConfig] = {}
        self.active_alarms: Dict[str, ActiveAlarm] = {}

    def add_alarm_config(self, config: AlarmConfig):
        with self.lock: self.alarm_configs[config.id] = config

    def process_value(self, channel: str, value: float, timestamp: float = None):
        with self.lock:
            for config in [c for c in self.alarm_configs.values() if c.channel == channel and c.enabled]:
                met, ttype, tval = self._check_thresholds(config, value)
                current = self.active_alarms.get(config.id)
                if met:
                    if current is None:
                        self._trigger_alarm(config, value, ttype, tval)
                    else:
                        current.current_value = value
                else:
                    if current and current.state != FullAlarmState.SHELVED:
                        if self._should_clear(config, value, current.threshold_type, current.threshold_value):
                            if config.latch_behavior == LatchBehavior.AUTO_CLEAR:
                                self._clear_alarm(config.id)
                            elif current.state == FullAlarmState.ACTIVE:
                                current.state = FullAlarmState.RETURNED
                                current.current_value = value

    def _check_thresholds(self, config: AlarmConfig, value: float) -> tuple:
        if config.high_high is not None and value >= config.high_high: return True, 'high_high', config.high_high
        if config.low_low is not None and value <= config.low_low: return True, 'low_low', config.low_low
        if config.high is not None and value >= config.high: return True, 'high', config.high
        if config.low is not None and value <= config.low: return True, 'low', config.low
        return False, None, None

    def _should_clear(self, config: AlarmConfig, value: float, ttype: str, tval: float) -> bool:
        db = config.deadband
        if ttype in ('high_high', 'high'): return value < (tval - db)
        if ttype in ('low_low', 'low'): return value > (tval + db)
        return True

    def _trigger_alarm(self, config: AlarmConfig, value: float, ttype: str, tval: float):
        direction = "exceeded" if ttype.startswith('high') else "fell below"
        alarm = ActiveAlarm(alarm_id=config.id, channel=config.channel, name=config.name, severity=config.severity,
                            state=FullAlarmState.ACTIVE, threshold_type=ttype, threshold_value=tval,
                            triggered_value=value, current_value=value, triggered_at=datetime.now(),
                            message=f"{config.name} {direction} {ttype} limit: {value:.2f}")
        self.active_alarms[config.id] = alarm
        if self.publish_callback: self.publish_callback('alarm', alarm.to_dict())
        logger.warning(f"ALARM: {alarm.message}")

    def _clear_alarm(self, alarm_id: str):
        alarm = self.active_alarms.pop(alarm_id, None)
        if alarm and self.publish_callback:
            self.publish_callback('alarm_cleared', {'alarm_id': alarm_id})
            logger.info(f"ALARM CLEARED: {alarm.name}")

    def acknowledge_alarm(self, alarm_id: str, user: str = "Unknown") -> bool:
        with self.lock:
            alarm = self.active_alarms.get(alarm_id)
            if alarm and alarm.state in (FullAlarmState.ACTIVE, FullAlarmState.RETURNED):
                alarm.state = FullAlarmState.ACKNOWLEDGED
                alarm.acknowledged_at = datetime.now()
                alarm.acknowledged_by = user
                if self.publish_callback: self.publish_callback('alarm', alarm.to_dict())
                return True
            return False

    def get_active_alarms(self) -> List[ActiveAlarm]:
        with self.lock: return list(self.active_alarms.values())

    def load_config(self, config: Dict[str, Any]):
        with self.lock:
            self.alarm_configs.clear()
            for a in config.get('alarms', []):
                try: self.alarm_configs[a['id']] = AlarmConfig.from_dict(a)
                except Exception as e: logger.error(f"Failed to load alarm: {e}")


@dataclass
class Opto22Config:
    """Configuration for Opto22 node"""
    node_id: str = 'opto22-001'
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_base_topic: str = 'nisystem'
    mqtt_username: str = ''
    mqtt_password: str = ''

    # Opto22 REST API settings
    api_key: str = ''  # groov API key for authentication
    verify_ssl: bool = True  # Set False only for self-signed certs in isolated networks

    scan_rate_hz: float = 4.0
    publish_rate_hz: float = 4.0  # Rate at which to publish MQTT messages
    watchdog_timeout: float = 2.0

    channels: Dict[str, ChannelConfig] = field(default_factory=dict)
    scripts: List[Dict[str, Any]] = field(default_factory=list)
    safety_actions: Dict[str, SafetyActionConfig] = field(default_factory=dict)

    # Safe state outputs - which DO channels go LOW on watchdog expiry
    safe_state_outputs: List[str] = field(default_factory=list)


class Opto22NodeService:
    """
    Opto22 Node Service - runs independently on groov EPIC/RIO hardware
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / DEFAULT_CONFIG_FILE
        self.config: Optional[Opto22Config] = None

        # HTTP session for REST API
        self._http_session: Optional[requests.Session] = None

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

        # Watchdog
        self._watchdog_last_pet: float = 0.0
        self._watchdog_triggered: bool = False

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.watchdog_monitor_thread: Optional[threading.Thread] = None
        self._heartbeat_sequence = 0

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

        # Alarm state tracking (ISA-18.2 - evaluated locally on Opto22)
        self.alarm_states: Dict[str, AlarmState] = {}  # channel_name -> current alarm state
        self.alarm_lock = threading.Lock()

        # Session state (for autonomous operation)
        self.session = SessionState()

        # Local safety manager (for autonomous safety operation)
        self.local_safety: Optional[LocalSafetyManager] = None

        # =======================================================================
        # STANDALONE ENGINES (run autonomously on Opto22 hardware)
        # =======================================================================

        # PID Control Engine - deterministic control loops
        self.pid_engine = PIDEngine(on_set_output=self._set_output_internal)
        self.pid_engine.set_status_callback(self._publish_pid_status)

        # Sequence Manager - automated step sequences
        self.sequence_manager = SequenceManager()
        self.sequence_manager.on_set_output = self._set_output_internal
        self.sequence_manager.on_get_channel_value = self._get_channel_value
        self.sequence_manager.on_sequence_event = self._on_sequence_event

        # Trigger Engine - condition-based automation
        self.trigger_engine = TriggerEngine()
        self.trigger_engine.set_output = self._set_output_internal
        self.trigger_engine.run_sequence = lambda seq_id: self.sequence_manager.start_sequence(seq_id)

        # Watchdog Engine - channel monitoring (stale/out-of-range)
        self.channel_watchdog = WatchdogEngine()

        # Enhanced Alarm Manager - full ISA-18.2 alarm lifecycle
        self.enhanced_alarm_manager = EnhancedAlarmManager(publish_callback=self._publish_alarm_event)

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

        # Load config (if exists)
        self._load_local_config()

    # =========================================================================
    # ENGINE CALLBACK HELPERS
    # =========================================================================

    def _set_output_internal(self, channel_name: str, value: float) -> bool:
        """Internal callback for engines to set output values."""
        if not self.config:
            return False
        ch_config = self.config.channels.get(channel_name)
        if not ch_config:
            logger.warning(f"Engine set_output: unknown channel {channel_name}")
            return False
        if ch_config.channel_type not in ('analog_output', 'digital_output'):
            logger.warning(f"Engine set_output: {channel_name} is not an output")
            return False
        return self._write_channel_value(ch_config, value)

    def _get_channel_value(self, channel_name: str) -> Optional[float]:
        """Internal callback for engines to read channel values."""
        with self.values_lock:
            return self.channel_values.get(channel_name)

    def _publish_pid_status(self, loop_id: str, status: Dict[str, Any]):
        """Callback to publish PID loop status via MQTT."""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_topic_prefix}/pid/{loop_id}/status"
            try:
                self.mqtt_client.publish(topic, json.dumps(status), qos=0)
            except Exception as e:
                logger.debug(f"PID status publish failed: {e}")

    def _on_sequence_event(self, event_type: str, sequence: 'Sequence'):
        """Callback for sequence manager events."""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_topic_prefix}/sequence/{sequence.id}/{event_type}"
            payload = {
                'sequence_id': sequence.id,
                'event': event_type,
                'state': sequence.state.value if sequence.state else 'unknown',
                'current_step': sequence.current_step_index,
                'timestamp': datetime.now().isoformat()
            }
            try:
                self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            except Exception as e:
                logger.debug(f"Sequence event publish failed: {e}")

    def _publish_notification(self, notification_type: str, message: str, severity: str = 'info'):
        """Publish a notification message via MQTT."""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_topic_prefix}/notifications"
            payload = {
                'type': notification_type,
                'message': message,
                'severity': severity,
                'timestamp': datetime.now().isoformat(),
                'source': 'opto22_node'
            }
            try:
                self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            except Exception as e:
                logger.debug(f"Notification publish failed: {e}")

    def _raise_alarm(self, channel_name: str, alarm_type: str, value: float, limit: float):
        """Callback for watchdog engine to raise alarms."""
        self._publish_notification(
            'watchdog_alarm',
            f"Channel {channel_name}: {alarm_type} (value={value:.2f}, limit={limit:.2f})",
            severity='warning'
        )

    def _publish_alarm_event(self, alarm: 'ActiveAlarm', event_type: str):
        """Callback to publish alarm events via MQTT."""
        if self.mqtt_client and self._mqtt_connected.is_set():
            topic = f"{self.config.mqtt_topic_prefix}/alarms/{alarm.channel_name}/{event_type}"
            payload = {
                'channel_name': alarm.channel_name,
                'alarm_type': alarm.alarm_type,
                'event': event_type,
                'state': alarm.state.value,
                'severity': alarm.severity.value,
                'value': alarm.trigger_value,
                'limit': alarm.limit_value,
                'message': alarm.message,
                'timestamp': alarm.timestamp.isoformat(),
                'acknowledged': alarm.acknowledged,
                'shelved': alarm.shelved
            }
            try:
                self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            except Exception as e:
                logger.debug(f"Alarm event publish failed: {e}")

    # =========================================================================
    # REST API ACCESS
    # =========================================================================

    def _create_http_session(self):
        """Create HTTP session for Opto22 REST API."""
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available")
            return

        self._http_session = requests.Session()
        self._http_session.verify = self.config.verify_ssl if self.config else False

        # Set API key header if configured
        if self.config and self.config.api_key:
            self._http_session.headers['apiKey'] = self.config.api_key

        self._http_session.headers['Content-Type'] = 'application/json'
        self._http_session.headers['Accept'] = 'application/json'

    def _api_get(self, endpoint: str) -> Optional[Any]:
        """Make GET request to Opto22 REST API."""
        if not self._http_session:
            self._create_http_session()

        try:
            url = f"{OPTO22_API_BASE}{endpoint}"
            response = self._http_session.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"API GET {endpoint} failed: {e}")
            return None

    def _api_put(self, endpoint: str, value: Any) -> bool:
        """Make PUT request to Opto22 REST API."""
        if not self._http_session:
            self._create_http_session()

        try:
            url = f"{OPTO22_API_BASE}{endpoint}"
            response = self._http_session.put(url, json=value, timeout=5.0)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"API PUT {endpoint} failed: {e}")
            return False

    def _read_channel_value(self, ch_config: ChannelConfig) -> Optional[float]:
        """Read a single channel via REST API."""
        if ch_config.channel_type == 'analog_input':
            endpoint = f"{OPTO22_ANALOG_INPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
        elif ch_config.channel_type == 'analog_output':
            endpoint = f"{OPTO22_ANALOG_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
        elif ch_config.channel_type == 'digital_input':
            endpoint = f"{OPTO22_DIGITAL_INPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
        elif ch_config.channel_type == 'digital_output':
            endpoint = f"{OPTO22_DIGITAL_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
        else:
            return None

        result = self._api_get(endpoint)
        if result is not None:
            try:
                raw_value = float(result) if not isinstance(result, bool) else (1.0 if result else 0.0)
                scaled = raw_value * ch_config.scale_slope + ch_config.scale_offset
                return scaled
            except (ValueError, TypeError):
                return None
        return None

    def _write_channel_value(self, ch_config: ChannelConfig, eng_value: float) -> bool:
        """Write a value to an output channel via REST API.

        Applies reverse scaling to convert engineering units to raw output values.
        """
        # Apply REVERSE scaling: engineering units → raw output
        raw_value = self._reverse_scale_output(ch_config, eng_value)

        # Apply invert for digital outputs
        if ch_config.channel_type == 'digital_output':
            bool_value = raw_value > 0.5
            if ch_config.invert:
                bool_value = not bool_value
            endpoint = f"{OPTO22_DIGITAL_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/state"
            return self._api_put(endpoint, bool_value)
        elif ch_config.channel_type == 'analog_output':
            endpoint = f"{OPTO22_ANALOG_OUTPUTS}/{ch_config.module_index}/channels/{ch_config.channel_index}/value"
            logger.debug(f"AO {ch_config.name}: eng={eng_value} → raw={raw_value}")
            return self._api_put(endpoint, raw_value)
        return False

    def _reverse_scale_output(self, ch_config: ChannelConfig, eng_value: float) -> float:
        """
        Reverse scaling: convert engineering units to raw output value.

        For outputs, we receive values in engineering units (%, RPM, PSI, etc.)
        and need to convert to the raw value for the Opto22 API.
        """
        # 4-20mA scaling (current outputs)
        if ch_config.four_twenty_scaling and ch_config.eng_units_min is not None and ch_config.eng_units_max is not None:
            span = ch_config.eng_units_max - ch_config.eng_units_min
            if span != 0:
                normalized = (eng_value - ch_config.eng_units_min) / span
                raw_ma = 4.0 + (normalized * 16.0)  # 4-20mA range
                return raw_ma
            return 4.0  # 4mA minimum

        # Map scaling
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
            return (eng_value - ch_config.scale_offset) / ch_config.scale_slope

        # No scaling - pass through
        return eng_value

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

                self.config = Opto22Config(
                    node_id=data.get('node_id', 'opto22-001'),
                    mqtt_broker=data.get('mqtt_broker', 'localhost'),
                    mqtt_port=data.get('mqtt_port', 1883),
                    mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
                    mqtt_username=data.get('mqtt_username', ''),
                    mqtt_password=data.get('mqtt_password', ''),
                    api_key=data.get('api_key', ''),
                    verify_ssl=data.get('verify_ssl', False),
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
                self.config = Opto22Config()
        else:
            logger.info("No local config found - waiting for config from NISystem")
            self.config = Opto22Config()

    def _save_local_config(self):
        """Save configuration locally (for PC disconnect survival)"""
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
                'api_key': self.config.api_key,
                'verify_ssl': self.config.verify_ssl,
                'scan_rate_hz': self.config.scan_rate_hz,
                'publish_rate_hz': self.config.publish_rate_hz,
                'watchdog_timeout': self.config.watchdog_timeout,
                'channels': {name: asdict(ch) for name, ch in self.config.channels.items()},
                'scripts': self.config.scripts,
                'safety_actions': {name: asdict(action) for name, action in self.config.safety_actions.items()},
                'safe_state_outputs': self.config.safe_state_outputs
            }

            # Atomic write: write to temp file, then rename
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            temp_file.replace(self.config_file)
            logger.info(f"Saved config locally: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save local config: {e}")

    def _calculate_config_hash(self) -> str:
        """Calculate a hash of the current configuration for version tracking"""
        if not self.config:
            return ""

        config_data = {
            'channels': {name: asdict(ch) for name, ch in sorted(self.config.channels.items())},
            'safety_actions': {name: asdict(action) for name, action in sorted(self.config.safety_actions.items())},
            'watchdog_timeout': self.config.watchdog_timeout,
            'safe_state_outputs': sorted(self.config.safe_state_outputs)
        }

        config_json = json.dumps(config_data, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()

    def _validate_config(self) -> List[str]:
        """Validate configuration and return list of warnings/errors."""
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
                    target_config = self.config.channels[target_ch]
                    if target_config.channel_type not in ('digital_output', 'analog_output'):
                        errors.append(f"Safety action '{action_name}' targets "
                                     f"non-output channel '{target_ch}'")

        return errors

    # =========================================================================
    # HARDWARE DETECTION
    # =========================================================================

    def _get_local_ip(self) -> str:
        """Get local IP address that can reach the MQTT broker"""
        if self.config and self.config.mqtt_broker:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                s.connect((self.config.mqtt_broker, self.config.mqtt_port))
                ip = s.getsockname()[0]
                s.close()
                if ip and ip != '0.0.0.0':
                    return ip
            except Exception:
                pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        return 'unknown'

    def _detect_hardware_info(self) -> Dict[str, Any]:
        """Detect groov EPIC/RIO hardware info for status reporting."""
        if self._hardware_info is not None:
            return self._hardware_info

        info = {
            'product_type': 'groov EPIC/RIO',
            'serial_number': '',
            'firmware_version': '',
            'device_name': '',
            'ip_address': '',
            'modules': []
        }

        # Try to get system info from REST API
        sys_info = self._api_get(OPTO22_SYSTEM_INFO)
        if sys_info:
            info['product_type'] = sys_info.get('productType', 'groov EPIC/RIO')
            info['serial_number'] = sys_info.get('serialNumber', '')
            info['firmware_version'] = sys_info.get('firmwareVersion', '')
            info['device_name'] = f"{info['product_type']}-{info['serial_number']}" if info['serial_number'] else info['product_type']

        # Enumerate I/O modules
        for io_type, endpoint, ch_type in [
            ('analogInputs', OPTO22_ANALOG_INPUTS, 'analog_input'),
            ('analogOutputs', OPTO22_ANALOG_OUTPUTS, 'analog_output'),
            ('digitalInputs', OPTO22_DIGITAL_INPUTS, 'digital_input'),
            ('digitalOutputs', OPTO22_DIGITAL_OUTPUTS, 'digital_output')
        ]:
            modules = self._api_get(endpoint)
            if modules and isinstance(modules, list):
                for i, mod in enumerate(modules):
                    if isinstance(mod, dict):
                        channels = []
                        mod_channels = mod.get('channels', [])
                        for j, ch in enumerate(mod_channels if isinstance(mod_channels, list) else []):
                            channels.append({
                                'name': f"{io_type}/{i}/ch{j}",
                                'display_name': ch.get('name', f"ch{j}") if isinstance(ch, dict) else f"ch{j}",
                                'channel_type': ch_type,
                                'module_index': i,
                                'channel_index': j
                            })

                        info['modules'].append({
                            'index': i,
                            'type': io_type,
                            'name': mod.get('name', f'{io_type}_{i}'),
                            'channel_count': len(channels),
                            'channels': channels
                        })

        # Count total channels
        total_channels = sum(len(m.get('channels', [])) for m in info['modules'])
        logger.info(f"Detected hardware: {info.get('device_name', info['product_type'])} with {len(info['modules'])} modules, {total_channels} channels")

        self._hardware_info = info
        return info

    # =========================================================================
    # MQTT TOPIC HELPERS
    # =========================================================================

    def get_topic_base(self) -> str:
        """Get node-prefixed topic base"""
        base = self.config.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.node_id if self.config else 'opto22-001'
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
            client_id=f"opto22-{self.config.node_id}",
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
            json.dumps({'status': 'offline', 'node_type': 'opto22'}),
            qos=1,
            retain=True
        )

        # Connect with retry
        self._connect_mqtt()

    def _connect_mqtt(self):
        """Connect to MQTT broker with infinite retry - never give up"""
        retry_delay = 2.0
        max_delay = 30.0
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

                if self._mqtt_connected.wait(timeout=10.0):
                    logger.info("MQTT connected successfully")
                    return True
                else:
                    logger.warning("MQTT connection timeout - will retry")
                    self.mqtt_client.loop_stop()
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt} failed: {e}")

            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, max_delay)

        return False

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connected callback"""
        if reason_code == 0:
            self._mqtt_connected.set()
            self.pc_connected = True
            self.last_pc_contact = time.time()

            # Subscribe to config and command topics
            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic
            subscriptions = [
                (f"{base}/config/#", 1),
                (f"{base}/commands/#", 1),
                (f"{base}/script/#", 1),
                (f"{base}/system/#", 1),
                (f"{base}/safety/#", 1),
                (f"{base}/session/#", 1),
                (f"{base}/console/#", 1),     # Interactive console (IPython-like)
                (f"{mqtt_base}/discovery/ping", 1),
            ]
            for topic, qos in subscriptions:
                client.subscribe(topic, qos)
                logger.debug(f"Subscribed to: {topic}")

            self._publish_status()
            logger.info("MQTT connected and subscribed")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnected callback"""
        self._mqtt_connected.clear()
        self.pc_connected = False
        logger.warning(f"MQTT disconnected (reason: {reason_code}) - will attempt reconnect")
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

            base = self.get_topic_base()
            mqtt_base = self.config.mqtt_base_topic

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

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_config_message(self, topic: str, payload: Dict[str, Any]):
        """Handle configuration updates from NISystem"""
        if topic.endswith('/full'):
            logger.info("Received full configuration update")

            try:
                # Parse channels
                channels = {}
                raw_channels = payload.get('channels', {})

                if isinstance(raw_channels, list):
                    for ch_data in raw_channels:
                        name = ch_data.get('name')
                        if name:
                            channels[name] = self._parse_channel_config(ch_data)
                else:
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

                # Update config
                self.config.channels = channels
                self.config.scripts = payload.get('scripts', [])
                self.config.safety_actions = safety_actions
                self.config.safe_state_outputs = payload.get('safe_state_outputs', [])
                self.config.watchdog_timeout = payload.get('watchdog_timeout', self.config.watchdog_timeout)

                # Calculate config hash
                config_hash = self._calculate_config_hash()
                self.config_version = config_hash
                self.config_timestamp = datetime.now(timezone.utc).isoformat()

                # Validate
                validation_errors = self._validate_config()
                if validation_errors:
                    for error in validation_errors:
                        logger.warning(f"Config validation: {error}")

                # Save locally
                self._save_local_config()

                # Clear safety triggered state
                with self.safety_lock:
                    self.safety_triggered.clear()

                # Publish acknowledgment
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

                # Auto-start acquisition
                if channels and not self._acquiring.is_set():
                    logger.info("Config received - auto-starting acquisition (Opto22 is PLC)")
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

    def _parse_channel_config(self, ch_data: Dict[str, Any]) -> ChannelConfig:
        """Parse channel config from PC format to Opto22 format."""
        field_map = {
            'unit': 'engineering_units',
        }

        valid_fields = {
            'name', 'physical_channel', 'channel_type',
            'module_index', 'channel_index',
            'default_state', 'invert',
            # Scaling (linear, 4-20mA, and map scaling)
            'scale_slope', 'scale_offset', 'scale_type', 'engineering_units',
            'four_twenty_scaling', 'eng_units_min', 'eng_units_max',
            'pre_scaled_min', 'pre_scaled_max', 'scaled_min', 'scaled_max',
            # Alarms
            'alarm_enabled', 'hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit',
            'alarm_priority', 'alarm_deadband', 'alarm_delay_sec',
            'safety_action', 'safety_interlock', 'expected_state',
        }

        normalized = {}

        for key, value in ch_data.items():
            mapped_key = field_map.get(key, key)
            if mapped_key not in valid_fields:
                continue
            if value is None:
                continue
            normalized[mapped_key] = value

        # Parse physical_channel to extract module_index and channel_index
        phys_ch = normalized.get('physical_channel', '')
        if '/' in phys_ch:
            parts = phys_ch.split('/')
            try:
                normalized['module_index'] = int(parts[0]) if parts[0].isdigit() else 0
                normalized['channel_index'] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            except (ValueError, IndexError):
                pass

        # Enable alarms if any limits are set
        has_limits = any(normalized.get(f) is not None for f in ['hihi_limit', 'hi_limit', 'lo_limit', 'lolo_limit'])
        if has_limits and 'alarm_enabled' not in normalized:
            normalized['alarm_enabled'] = True

        # Ensure required fields
        if 'name' not in normalized:
            normalized['name'] = ''
        if 'physical_channel' not in normalized:
            normalized['physical_channel'] = ''
        if 'channel_type' not in normalized:
            normalized['channel_type'] = 'analog_input'

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
            hw_info = self._detect_hardware_info()
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'info': {
                    'node_id': self.config.node_id,
                    'type': 'Opto22',
                    'product_type': hw_info.get('product_type', 'groov EPIC/RIO'),
                    'serial_number': hw_info.get('serial_number', 'N/A'),
                    'device_name': hw_info.get('device_name', ''),
                    'firmware_version': hw_info.get('firmware_version', ''),
                    'ip_address': self._get_local_ip(),
                    'channels': len(self.config.channels),
                    'modules': len(hw_info.get('modules', [])),
                    'acquiring': self._acquiring.is_set(),
                    'uptime_hours': round((time.time() - getattr(self, '_start_time', time.time())) / 3600, 1)
                }
            })
            return

        elif topic.endswith('/commands/modules'):
            hw_info = self._detect_hardware_info()
            modules = []
            for mod in hw_info.get('modules', []):
                modules.append({
                    'slot': mod.get('slot', 0),
                    'name': mod.get('name', ''),
                    'type': mod.get('module_type', ''),
                    'channels': len(mod.get('channels', []))
                })
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'modules': modules
            })
            return

        elif topic.endswith('/commands/firmware'):
            hw_info = self._detect_hardware_info()
            self._publish(f"{base}/command/response", {
                'success': True,
                'request_id': request_id,
                'node_software': '1.0.0',
                'product_type': hw_info.get('product_type', 'groov EPIC/RIO'),
                'serial_number': hw_info.get('serial_number', 'N/A'),
                'firmware_version': hw_info.get('firmware_version', ''),
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
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
        if topic.endswith('/commands/output'):
            channel_name = payload.get('channel', '')
            value = payload.get('value')
        else:
            parts = topic.split('/')
            channel_name = parts[-1] if len(parts) >= 2 else ''
            value = payload.get('value')

        if not channel_name:
            return

        if channel_name not in self.config.channels:
            logger.warning(f"Unknown output channel: {channel_name}")
            return

        ch_config = self.config.channels[channel_name]

        # Check session lock
        if self.session.active and channel_name in self.session.locked_outputs:
            logger.warning(f"SESSION LOCKS output {channel_name} - manual write blocked")
            self._publish(f"{self.get_topic_base()}/session/blocked", {
                'channel': channel_name,
                'requested_value': value,
                'reason': 'session_locked',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            return

        # Check interlock
        if ch_config.safety_interlock:
            if not self._check_interlock(ch_config.safety_interlock):
                logger.warning(f"INTERLOCK BLOCKS write to {channel_name}: {ch_config.safety_interlock}")
                self._publish_interlock_blocked(channel_name, ch_config.safety_interlock, value)
                return

        self._write_output(channel_name, value)
        logger.info(f"Output command: {channel_name} = {value}")

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

    def _handle_safety_message(self, topic: str, payload: Dict[str, Any]):
        """Handle safety-related MQTT commands"""
        if topic.endswith('/trigger'):
            self._handle_safety_trigger(payload)
        elif topic.endswith('/clear'):
            channel = payload.get('channel')
            if channel:
                with self.safety_lock:
                    if channel in self.safety_triggered:
                        del self.safety_triggered[channel]
                        logger.info(f"Cleared safety trigger state for {channel}")
        # Latch commands
        elif topic.endswith('/latch/arm'):
            if self.local_safety:
                user = payload.get('user', 'remote')
                success = self.local_safety.arm_latch(user=user)
                self._publish_safety_status()
                if not success:
                    logger.warning(f"Failed to arm latch - requested by {user}")
        elif topic.endswith('/latch/disarm'):
            if self.local_safety:
                user = payload.get('user', 'remote')
                self.local_safety.disarm_latch(user=user)
                self._publish_safety_status()
        elif topic.endswith('/latch/reset'):
            if self.local_safety:
                user = payload.get('user', 'remote')
                success = self.local_safety.reset_trip(user=user)
                self._publish_safety_status()
                if not success:
                    logger.warning(f"Failed to reset trip - interlocks may still be failed")
        elif topic.endswith('/trip'):
            if self.local_safety:
                reason = payload.get('reason', 'Remote trip command')
                self.local_safety.trip_system(reason)
                self._publish_safety_status()
        # Interlock commands
        elif topic.endswith('/interlock/add'):
            self._handle_interlock_add(payload)
        elif topic.endswith('/interlock/remove'):
            interlock_id = payload.get('id')
            if interlock_id and self.local_safety:
                self.local_safety.remove_interlock(interlock_id)
                logger.info(f"Removed interlock: {interlock_id}")
        elif topic.endswith('/interlock/sync'):
            # Sync all interlocks from PC
            self._handle_interlock_sync(payload)

    def _handle_interlock_add(self, payload: Dict[str, Any]):
        """Add or update a local interlock from PC"""
        if not self.local_safety:
            return

        interlock_id = payload.get('id')
        if not interlock_id:
            return

        interlock = LocalInterlockConfig(
            id=interlock_id,
            name=payload.get('name', interlock_id),
            enabled=payload.get('enabled', True),
            conditions=payload.get('conditions', []),
            condition_logic=payload.get('conditionLogic', 'AND'),
            output_channels=payload.get('outputChannels', [])
        )
        self.local_safety.add_interlock(interlock)
        logger.info(f"Added/updated interlock: {interlock.name}")

    def _handle_interlock_sync(self, payload: Dict[str, Any]):
        """Sync all interlocks from PC"""
        if not self.local_safety:
            return

        interlocks = payload.get('interlocks', [])
        logger.info(f"Syncing {len(interlocks)} interlocks from PC")

        # Clear existing and add new
        self.local_safety.interlocks.clear()
        for interlock_data in interlocks:
            interlock = LocalInterlockConfig(
                id=interlock_data.get('id', ''),
                name=interlock_data.get('name', ''),
                enabled=interlock_data.get('enabled', True),
                conditions=interlock_data.get('conditions', []),
                condition_logic=interlock_data.get('conditionLogic', 'AND'),
                output_channels=interlock_data.get('outputChannels', [])
            )
            if interlock.id:
                self.local_safety.add_interlock(interlock)

    def _handle_session_message(self, topic: str, payload: Dict[str, Any]):
        """Handle session commands from NISystem"""
        if topic.endswith('/start'):
            self._start_session(payload)
        elif topic.endswith('/stop'):
            self._stop_session(payload.get('reason', 'command'))
        elif topic.endswith('/ping'):
            self.last_pc_contact = time.time()
            self._publish_session_status()

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

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

        # Auto-start session scripts
        self._auto_start_scripts('session')

    def _stop_session(self, reason: str = 'command'):
        """Stop the current session"""
        if not self.session.active:
            return

        # Auto-stop session scripts first
        self._auto_stop_scripts('session')

        duration = time.time() - (self.session.start_time or time.time())
        logger.info(f"SESSION STOPPED: {self.session.name} after {duration:.1f}s (reason: {reason})")

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

        Uses unified API format matching DAQ Service and cRIO for frontend compatibility.
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

            stdout_capture = io.StringIO()
            namespace = self._get_console_namespace()

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

        # Storage file location - use data directory on Opto22
        data_dir = Path('/home/dev/nisystem/data')
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
                self._service._write_output(channel, value, source='console')

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

    # =========================================================================
    # SAFETY SYSTEM
    # =========================================================================

    def _set_safe_state(self, reason: str = 'command'):
        """Set all outputs to safe state"""
        logger.info(f"Setting outputs to SAFE STATE - reason: {reason}")

        for channel_name, ch_config in self.config.channels.items():
            try:
                if ch_config.channel_type == 'digital_output':
                    self._write_output(channel_name, 0, source='safety')
                    logger.info(f"  DO {channel_name} -> 0 (OFF)")
                elif ch_config.channel_type == 'analog_output':
                    self._write_output(channel_name, 0.0, source='safety')
                    logger.info(f"  AO {channel_name} -> 0.0")
            except Exception as e:
                logger.error(f"  Failed to set {channel_name} safe: {e}")

        self._publish(f"{self.get_topic_base()}/status/safe-state", {
            'success': True,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _execute_safety_action(self, action_name: str, trigger_source: str):
        """Execute a named safety action"""
        if not self.config or action_name not in self.config.safety_actions:
            logger.critical(f"SAFETY FAILURE: Unknown safety action '{action_name}' "
                          f"triggered by {trigger_source}")
            return

        action = self.config.safety_actions[action_name]
        logger.warning(f"SAFETY: Executing action '{action_name}' triggered by {trigger_source}")

        executed = []
        failed = []

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

        if failed:
            logger.critical(f"SAFETY ACTION '{action_name}' INCOMPLETE! Failed: {failed}")

        self._publish(f"{self.get_topic_base()}/safety/triggered", {
            'action': action_name,
            'trigger_source': trigger_source,
            'executed': executed,
            'failed': failed,
            'success': len(failed) == 0,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

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

    def _check_safety_limits(self, channel_name: str, value: float):
        """Check ISA-18.2 safety limits and trigger action if needed."""
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.safety_action:
            return

        triggered = False
        trigger_reason = ""

        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            triggered = True
            trigger_reason = f"HIHI: {value:.2f} >= {ch_config.hihi_limit}"
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            triggered = True
            trigger_reason = f"LOLO: {value:.2f} <= {ch_config.lolo_limit}"

        if ch_config.channel_type == 'digital_input' and ch_config.expected_state is not None:
            actual_state = bool(value)
            if actual_state != ch_config.expected_state:
                triggered = True
                trigger_reason = f"DI unexpected: {actual_state} != expected {ch_config.expected_state}"

        with self.safety_lock:
            was_triggered = self.safety_triggered.get(channel_name, False)

            if triggered and not was_triggered:
                self.safety_triggered[channel_name] = True
                logger.warning(f"SAFETY LIMIT VIOLATION: {channel_name} - {trigger_reason}")
                self._execute_safety_action(ch_config.safety_action, channel_name)

            elif not triggered and was_triggered:
                del self.safety_triggered[channel_name]
                logger.info(f"Safety condition cleared: {channel_name}")
                self._publish(f"{self.get_topic_base()}/safety/cleared", {
                    'channel': channel_name,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })

    def _check_alarms(self, channel_name: str, value: float):
        """Evaluate ISA-18.2 alarms and publish alarm events."""
        if not self.config:
            return

        ch_config = self.config.channels.get(channel_name)
        if not ch_config or not ch_config.alarm_enabled:
            return

        deadband = ch_config.alarm_deadband if ch_config.alarm_deadband else 0.0

        new_state = AlarmState.NORMAL

        if ch_config.hihi_limit is not None and value >= ch_config.hihi_limit:
            new_state = AlarmState.HIHI
        elif ch_config.lolo_limit is not None and value <= ch_config.lolo_limit:
            new_state = AlarmState.LOLO
        elif ch_config.hi_limit is not None and value >= ch_config.hi_limit:
            new_state = AlarmState.HI
        elif ch_config.lo_limit is not None and value <= ch_config.lo_limit:
            new_state = AlarmState.LO

        with self.alarm_lock:
            prev_state = self.alarm_states.get(channel_name, AlarmState.NORMAL)

            if new_state != prev_state:
                if new_state == AlarmState.NORMAL and deadband > 0:
                    if prev_state in (AlarmState.HI, AlarmState.HIHI):
                        threshold = ch_config.hi_limit or ch_config.hihi_limit
                        if threshold and value > (threshold - deadband):
                            return
                    elif prev_state in (AlarmState.LO, AlarmState.LOLO):
                        threshold = ch_config.lo_limit or ch_config.lolo_limit
                        if threshold and value < (threshold + deadband):
                            return

                self.alarm_states[channel_name] = new_state
                self._publish_alarm_event(channel_name, prev_state, new_state, value)

                if new_state == AlarmState.NORMAL:
                    logger.info(f"ALARM CLEARED: {channel_name}")
                else:
                    severity = "CRITICAL" if new_state in (AlarmState.HIHI, AlarmState.LOLO) else "WARNING"
                    logger.warning(f"ALARM {severity}: {channel_name} - {new_state.value} at {value:.2f}")

    def _publish_alarm_event(self, channel: str, prev_state: AlarmState, new_state: AlarmState, value: float):
        """Publish alarm state change event"""
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

    def _init_local_safety(self):
        """Initialize the local safety manager for autonomous operation"""
        logger.info("[LocalSafety] Initializing local safety manager...")

        def get_channel_value(channel: str) -> Optional[float]:
            """Get current value of a channel"""
            with self.values_lock:
                return self.channel_values.get(channel)

        def set_output(channel: str, value: float) -> bool:
            """Set an output channel value"""
            return self._write_output(channel, value, source='local_safety')

        def stop_session():
            """Stop the current session"""
            self._stop_session('safety_trip')

        def publish(topic: str, payload: Dict[str, Any]):
            """Publish to MQTT"""
            self._publish(f"{self.get_topic_base()}/{topic}", payload)

        self.local_safety = LocalSafetyManager(
            get_channel_value=get_channel_value,
            set_output=set_output,
            stop_session=stop_session,
            publish=publish
        )
        logger.info("[LocalSafety] Local safety manager initialized")

    def _publish_safety_status(self):
        """Publish current safety status"""
        if not self.local_safety:
            return

        status = self.local_safety.get_status()
        status['node_id'] = self.config.node_id if self.config else 'unknown'

        self._publish(f"{self.get_topic_base()}/safety/status", status)

    # =========================================================================
    # INTERLOCK LOGIC
    # =========================================================================

    def _check_interlock(self, interlock_expr: str) -> bool:
        """Evaluate a safety interlock expression safely."""
        if not interlock_expr:
            return True

        try:
            with self.values_lock:
                values = dict(self.channel_values)

            return self._safe_eval_interlock(interlock_expr.strip(), values)

        except Exception as e:
            logger.error(f"Interlock evaluation failed: {e}")
            return False

    def _safe_eval_interlock(self, expr: str, values: Dict[str, float]) -> bool:
        """Recursive descent parser for interlock expressions."""
        expr = expr.strip()

        if expr.startswith('(') and expr.endswith(')'):
            depth = 0
            for i, c in enumerate(expr):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                if depth == 0 and i == len(expr) - 1:
                    return self._safe_eval_interlock(expr[1:-1], values)
                elif depth == 0 and i < len(expr) - 1:
                    break

        or_parts = self._split_by_operator(expr, ' OR ')
        if len(or_parts) > 1:
            return any(self._safe_eval_interlock(part, values) for part in or_parts)

        and_parts = self._split_by_operator(expr, ' AND ')
        if len(and_parts) > 1:
            return all(self._safe_eval_interlock(part, values) for part in and_parts)

        if expr.upper().startswith('NOT '):
            return not self._safe_eval_interlock(expr[4:], values)

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
        """Resolve a token to its value"""
        token = token.strip()

        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False

        try:
            if '.' in token:
                return float(token)
            return int(token)
        except ValueError:
            pass

        if token in values:
            return values[token]

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
    # WATCHDOG
    # =========================================================================

    def _pet_watchdog(self):
        """Pet the software watchdog"""
        self._watchdog_last_pet = time.time()
        self._watchdog_triggered = False

    def _check_watchdog_timeout(self) -> bool:
        """Check if watchdog has expired"""
        if not self.config or self.config.watchdog_timeout <= 0:
            return False

        if self._watchdog_last_pet == 0:
            return False

        elapsed = time.time() - self._watchdog_last_pet

        if elapsed > self.config.watchdog_timeout:
            if not self._watchdog_triggered:
                logger.critical(
                    f"WATCHDOG TIMEOUT: {elapsed:.1f}s > {self.config.watchdog_timeout}s - "
                    f"TRIGGERING SAFE STATE"
                )
                self._watchdog_triggered = True
                self._set_safe_state("watchdog_timeout")

                self._publish(f"{self.get_topic_base()}/safety/watchdog", {
                    'event': 'timeout',
                    'elapsed_s': elapsed,
                    'timeout_s': self.config.watchdog_timeout,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return True

        return False

    def _watchdog_monitor_loop(self):
        """Independent watchdog monitor thread"""
        logger.info("Watchdog monitor thread started")

        check_interval = max(0.25, (self.config.watchdog_timeout / 4) if self.config else 0.5)

        while self._running.is_set():
            try:
                if self._acquiring.is_set():
                    self._check_watchdog_timeout()
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")

            time.sleep(check_interval)

        logger.info("Watchdog monitor thread stopped")

    # =========================================================================
    # DATA ACQUISITION
    # =========================================================================

    def _start_acquisition(self):
        """Start data acquisition"""
        if self._acquiring.is_set():
            logger.info("Acquisition already running")
            return

        logger.info("Starting acquisition...")
        self._acquiring.set()

        self.scan_thread = threading.Thread(
            target=self._scan_loop,
            name="ScanLoop",
            daemon=True
        )
        self.scan_thread.start()

        self._publish_status()
        logger.info("Acquisition started")

        # Notify engines of acquisition start
        self.pid_engine.on_acquisition_start()
        self.sequence_manager.on_acquisition_start()
        self.trigger_engine.on_acquisition_start()
        self.channel_watchdog.on_acquisition_start()

        # Auto-start acquisition scripts
        self._auto_start_scripts('acquisition')

    def _stop_acquisition(self):
        """Stop data acquisition"""
        if not self._acquiring.is_set():
            return

        # Notify engines of acquisition stop
        self.pid_engine.on_acquisition_stop()
        self.sequence_manager.on_acquisition_stop()
        self.trigger_engine.on_acquisition_stop()
        self.channel_watchdog.on_acquisition_stop()

        # Auto-stop acquisition scripts first
        self._auto_stop_scripts('acquisition')

        logger.info("Stopping acquisition...")
        self._acquiring.clear()

        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

        self._publish_status()
        logger.info("Acquisition stopped")

    def _scan_loop(self):
        """Main data acquisition loop"""
        logger.info("Scan loop started")

        scan_interval = 1.0 / self.config.scan_rate_hz
        publish_interval = 1.0 / self.config.publish_rate_hz

        while self._acquiring.is_set():
            loop_start = time.time()

            try:
                self._pet_watchdog()

                now = time.time()

                # Read all channels via REST API
                for channel_name, ch_config in self.config.channels.items():
                    try:
                        value = self._read_channel_value(ch_config)
                        if value is not None:
                            with self.values_lock:
                                self.channel_values[channel_name] = value
                                self.channel_timestamps[channel_name] = now
                    except Exception as e:
                        logger.warning(f"Error reading {channel_name}: {e}")

                # Include output values
                with self.values_lock:
                    for name, value in self.output_values.items():
                        self.channel_values[name] = value
                        self.channel_timestamps[name] = now

                # Publish at publish_rate_hz
                if now - self._last_publish_time >= publish_interval:
                    self._publish_channel_values()
                    self._last_publish_time = now

                # Check alarms and safety limits
                with self.values_lock:
                    values_snapshot = dict(self.channel_values)

                for ch_name, ch_value in values_snapshot.items():
                    try:
                        self._check_alarms(ch_name, ch_value)
                        self._check_safety_limits(ch_name, ch_value)
                    except Exception as e:
                        logger.error(f"Alarm/safety check error for {ch_name}: {e}")

                # Evaluate local safety interlocks
                if self.local_safety:
                    try:
                        self.local_safety.evaluate_all()
                    except Exception as e:
                        logger.error(f"Local safety evaluation error: {e}")

                # ===============================================================
                # STANDALONE ENGINE PROCESSING
                # ===============================================================

                # Get timestamps snapshot for watchdog
                with self.values_lock:
                    timestamps_snapshot = dict(self.channel_timestamps)

                # Calculate dt for PID
                dt = time.time() - loop_start

                # PID Control - must run before outputs are published
                try:
                    pid_outputs = self.pid_engine.process_scan(values_snapshot, dt)
                    # PID outputs are written directly via callback
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

            except Exception as e:
                logger.error(f"Scan loop error: {e}")

            elapsed = time.time() - loop_start
            sleep_time = scan_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Scan loop stopped")

    def _write_output(self, channel_name: str, value: Any, source: str = 'manual') -> bool:
        """Write to an output channel"""
        if channel_name not in self.config.channels:
            logger.warning(f"Output channel not found: {channel_name}")
            return False

        ch_config = self.config.channels[channel_name]

        if source != 'safety' and self.session.active and channel_name in self.session.locked_outputs:
            logger.warning(f"Write blocked - channel '{channel_name}' is session-locked")
            return False

        # SIL 1: Redundant interlock check at edge node (PC SafetyManager also validates)
        # Safety source bypasses this - safety actions ARE the interlock response
        if source != 'safety' and self.local_safety and self.local_safety.is_output_blocked(channel_name):
            logger.warning(f"Write blocked - channel '{channel_name}' blocked by interlock (SIL 1)")
            return False

        try:
            float_value = float(value) if value is not None else 0.0
            success = self._write_channel_value(ch_config, float_value)

            if success:
                self.output_values[channel_name] = float_value
                logger.debug(f"Wrote {channel_name} = {float_value}")

            return success

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
        """Auto-stop scripts matching the given run_mode"""
        for script_id, script in self.scripts.items():
            script_run_mode = script.get('run_mode', 'manual')
            if script_run_mode == run_mode:
                if script_id in self.script_threads and self.script_threads[script_id].is_alive():
                    logger.info(f"Auto-stopping {run_mode} script: {script_id}")
                    self._stop_script(script_id)

    def _start_script(self, script_id: str, max_runtime_seconds: float = 300.0):
        """Start executing a Python script with timeout"""
        if script_id not in self.scripts:
            logger.warning(f"Script not found: {script_id}")
            return

        script = self.scripts[script_id]

        if script_id in self.script_threads and self.script_threads[script_id].is_alive():
            logger.warning(f"Script already running: {script_id}")
            return

        script['_start_time'] = time.time()
        script['_max_runtime'] = max_runtime_seconds

        thread = threading.Thread(
            target=self._run_script,
            args=(script_id, script),
            name=f"Script-{script_id}",
            daemon=True
        )
        self.script_threads[script_id] = thread
        thread.start()

        monitor = threading.Thread(
            target=self._monitor_script_timeout,
            args=(script_id, max_runtime_seconds),
            name=f"ScriptMonitor-{script_id}",
            daemon=True
        )
        monitor.start()

        logger.info(f"Started script: {script_id} (max runtime: {max_runtime_seconds}s)")

    def _monitor_script_timeout(self, script_id: str, timeout_seconds: float):
        """Monitor script for timeout"""
        start_time = time.time()
        check_interval = 1.0

        while script_id in self.script_threads:
            thread = self.script_threads.get(script_id)
            if not thread or not thread.is_alive():
                return

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"SCRIPT TIMEOUT: {script_id} exceeded {timeout_seconds}s - forcing stop")
                if script_id in self.scripts:
                    self.scripts[script_id]['_stop_requested'] = True
                    self.scripts[script_id]['_timeout_exceeded'] = True

                time.sleep(2.0)

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
        if script_id in self.script_threads:
            self.scripts[script_id]['_stop_requested'] = True
            logger.info(f"Stop requested for script: {script_id}")
            self._publish_script_status()

    def _run_script(self, script_id: str, script: Dict[str, Any]):
        """Execute a Python script with enhanced environment"""
        code = script.get('code', '')

        def wait_for(seconds: float) -> bool:
            """Sleep for given seconds, respecting stop request."""
            interval = 0.1
            elapsed = 0.0
            while elapsed < seconds:
                if script.get('_stop_requested', False):
                    return True
                time.sleep(min(interval, seconds - elapsed))
                elapsed += interval
            return False

        def wait_until(condition_fn, timeout: float = 60.0) -> bool:
            """Wait until condition returns True."""
            start = time.time()
            while time.time() - start < timeout:
                if script.get('_stop_requested', False):
                    return False
                if condition_fn():
                    return True
                time.sleep(0.1)
            return False

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

            # Standard library
            'time': time,
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            # Scientific computing
            'numpy': np if NUMPY_AVAILABLE else None,
            'np': np if NUMPY_AVAILABLE else None,

            # Built-ins
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

            '__builtins__': {},
        }

        try:
            code = code.replace('await ', '')
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
                return self._parent._write_output(name, value, source='script')

            def is_locked(self, name: str) -> bool:
                return self._parent.session.active and name in self._parent.session.locked_outputs

        return OutputsAPI(self)

    def _create_publish_api(self):
        """Create publish API for scripts"""
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
                if self._parent.session.start_time:
                    return time.time() - self._parent.session.start_time
                return 0.0

            def is_output_locked(self, channel: str) -> bool:
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
        """Publish system status with hardware info"""
        hw_info = self._detect_hardware_info()
        status = {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'opto22',
            'node_id': self.config.node_id,
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'ip_address': self._get_local_ip(),
            'product_type': hw_info['product_type'],
            'serial_number': hw_info['serial_number'],
            'firmware_version': hw_info.get('firmware_version', ''),
            'device_name': hw_info.get('device_name', ''),
            'modules': hw_info['modules'],
            'config_version': self.config_version,
            'config_timestamp': self.config_timestamp
        }
        self._publish(self.get_topic('status', 'system'), status, retain=True)

    def _publish_channel_values(self):
        """Publish channel values as batched message"""
        with self.values_lock:
            # Batch all channel values into a single message to reduce MQTT load
            # Format: { "channel_name": {"value": x, "timestamp": t, "acquisition_ts_us": us, "quality": q}, ... }
            batch = {}
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
        """Publish heartbeat"""
        self._heartbeat_sequence += 1
        self._publish(
            self.get_topic('heartbeat'),
            {
                'seq': self._heartbeat_sequence,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'acquiring': self._acquiring.is_set(),
                'pc_connected': self.pc_connected,
                'node_type': 'opto22',
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
    # AUTO-DISCOVERY
    # =========================================================================

    def _auto_create_channels_from_hardware(self):
        """Auto-create channel configs for all detected hardware channels."""
        hw_info = self._detect_hardware_info()

        created_count = 0
        for module in hw_info.get('modules', []):
            for ch in module.get('channels', []):
                ch_name = ch.get('name', '')
                if not ch_name:
                    continue

                if ch_name in self.config.channels:
                    continue

                channel_config = ChannelConfig(
                    name=ch_name,
                    physical_channel=f"{ch.get('module_index', 0)}/{ch.get('channel_index', 0)}",
                    channel_type=ch.get('channel_type', 'analog_input'),
                    module_index=ch.get('module_index', 0),
                    channel_index=ch.get('channel_index', 0),
                )

                self.config.channels[ch_name] = channel_config
                created_count += 1
                logger.debug(f"Auto-created channel: {ch_name} type={ch.get('channel_type')}")

        if created_count > 0:
            logger.info(f"Auto-created {created_count} channel configs from detected hardware")

    # =========================================================================
    # MAIN SERVICE LIFECYCLE
    # =========================================================================

    def _reset(self):
        """Reset service to initial state"""
        logger.info("Resetting Opto22 node...")
        self._stop_acquisition()

        with self.values_lock:
            self.channel_values.clear()
            self.channel_timestamps.clear()

        for name, ch_config in self.config.channels.items():
            if ch_config.channel_type in ('digital_output', 'analog_output'):
                self._write_output(name, ch_config.default_state)

        self._publish_status()
        logger.info("Reset complete")

    def run(self):
        """Main service entry point"""
        logger.info("="*60)
        logger.info("Opto22 Node Service Starting")
        logger.info("="*60)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running.set()

        # Create HTTP session for REST API
        self._create_http_session()

        # Detect hardware
        logger.info("Detecting hardware...")
        self._detect_hardware_info()

        # Auto-create channels if none configured
        if not self.config.channels:
            self._auto_create_channels_from_hardware()

        # Setup MQTT
        self._setup_mqtt()

        # Start heartbeat
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Heartbeat",
            daemon=True
        )
        self.heartbeat_thread.start()

        # Start watchdog monitor
        self.watchdog_monitor_thread = threading.Thread(
            target=self._watchdog_monitor_loop,
            name="WatchdogMonitor",
            daemon=True
        )
        self.watchdog_monitor_thread.start()

        # Initialize local safety manager
        self._init_local_safety()

        # Auto-start acquisition if we have channels
        if self.config.channels:
            self._start_acquisition()

        self._publish_status()

        logger.info("Opto22 Node Service running")
        logger.info(f"Node ID: {self.config.node_id}")
        logger.info(f"Channels: {len(self.config.channels)}")
        logger.info(f"MQTT: {self.config.mqtt_broker}:{self.config.mqtt_port}")

        # Main loop
        try:
            while self._running.is_set():
                time.sleep(1.0)

                if not self._mqtt_connected.is_set():
                    logger.info("MQTT disconnected - attempting reconnect...")
                    self._connect_mqtt()

                if time.time() - self.last_pc_contact > 30:
                    if self.pc_connected:
                        logger.warning("Lost contact with PC - continuing in standalone mode")
                        self.pc_connected = False

                self._check_session_timeout()

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
        logger.info("Shutting down Opto22 Node Service...")

        self._running.clear()
        self._stop_acquisition()

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            logger.debug("Waiting for heartbeat thread to stop...")
            self.heartbeat_thread.join(timeout=3.0)

        if self.watchdog_monitor_thread and self.watchdog_monitor_thread.is_alive():
            logger.debug("Waiting for watchdog monitor thread to stop...")
            self.watchdog_monitor_thread.join(timeout=3.0)

        self._publish(
            self.get_topic('status', 'system'),
            {'status': 'offline', 'node_type': 'opto22'},
            retain=True
        )

        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        if self._http_session:
            self._http_session.close()

        logger.info("Opto22 Node Service stopped")


def main():
    parser = argparse.ArgumentParser(description='Opto22 Node Service for NISystem')
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
    parser.add_argument(
        '--api-key',
        type=str,
        help='groov API key (overrides config and env)'
    )

    args = parser.parse_args()

    service = Opto22NodeService(config_dir=Path(args.config_dir))

    # Priority: command-line args > environment variables > config file
    broker = args.broker or os.environ.get('MQTT_BROKER')
    if broker:
        service.config.mqtt_broker = broker

    port = args.port or os.environ.get('MQTT_PORT')
    if port:
        service.config.mqtt_port = int(port) if isinstance(port, str) else port

    node_id = args.node_id or os.environ.get('NODE_ID')
    if node_id:
        service.config.node_id = node_id

    api_key = args.api_key or os.environ.get('API_KEY')
    if api_key:
        service.config.api_key = api_key

    service.run()


if __name__ == '__main__':
    main()
