"""
Hardware Abstraction Layer for cRIO Node V2

Provides a clean interface to NI-DAQmx hardware.
Supports mocking for unit tests.

Key design:
- Per-module reader threads: each module type (DI, fast AI, TC) has
  its own thread polling at its natural rate.  The main loop calls
  read_latest() which returns instantly (no I/O).
- Write operations are immediate
- All errors are caught and logged
"""

import logging
import math
import threading
import time
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod

from .channel_types import ChannelType, get_module_channel_type, get_module_hardware_limits, get_combo_channel_type
from .config import ChannelConfig, apply_scaling

def _get_physical_channel_index(physical_channel: str) -> int:
    """
    Extract the channel index from a physical_channel string.

    Examples:
        'Mod1/ai0' -> 0
        'Mod5/ai15' -> 15
        'Mod3/port0/line7' -> 7

    This is CRITICAL for correct DAQmx value mapping.
    DAQmx returns values in the order channels are added to the task.
    Channels must be added in physical index order to map correctly.
    """
    # Extract the last number from the path
    match = re.search(r'(\d+)$', physical_channel)
    return int(match.group(1)) if match else 0

logger = logging.getLogger('cRIONode')

# ---------------------------------------------------------------------------
# Hardware constants (extracted from inline magic numbers)
# ---------------------------------------------------------------------------
SLOW_READ_MIN_INTERVAL_S = 1.0      # Physical floor: TC autozero takes ~1s per read
MIN_BUFFER_SAMPLES = 100            # Minimum DAQmx buffer size (samples)
BUFFER_DURATION_S = 10              # Buffer duration for continuous acquisition (seconds)
RESISTANCE_EXCITATION_A = 0.001     # Resistance channel excitation current (1 mA)
DI_READ_TIMEOUT_S = 0.01           # Digital input on-demand read timeout (seconds)
AI_TIMED_READ_TIMEOUT_S = 1.0      # Analog input timed/continuous read timeout (seconds)
AI_ONDEMAND_READ_TIMEOUT_S = 1.0   # Analog input on-demand read timeout (seconds)
AI_SLOW_READ_TIMEOUT_S = 5.0       # Analog input slow-device read timeout (TC with 16 ch @ 75ms/ch = 1.2s + margin)
CTR_READ_TIMEOUT_S = 0.1           # Counter input read timeout (seconds)
DEFAULT_MIN_PERIOD_S = 0.001       # Default min period for period counters (seconds)
DEFAULT_MAX_PERIOD_S = 10.0        # Default max period for period counters (seconds)
DEFAULT_DI_POLL_HZ = 20.0          # Default DI polling rate (Hz)
MAX_DI_POLL_HZ = 100.0             # Maximum DI polling rate (Hz)
DEFAULT_TC_POLL_HZ = 0.0           # TC: 0 = no artificial delay, hardware read time is the rate limiter

@dataclass
class _ReaderStats:
    """Per-module reader timing statistics."""
    read_count: int = 0
    error_count: int = 0
    last_read_ms: float = 0.0
    total_read_ms: float = 0.0  # for computing avg

    @property
    def avg_read_ms(self) -> float:
        return self.total_read_ms / self.read_count if self.read_count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            'read_count': self.read_count,
            'error_count': self.error_count,
            'last_read_ms': round(self.last_read_ms, 2),
            'avg_read_ms': round(self.avg_read_ms, 2),
        }

class _ReaderThread:
    """Dedicated reader thread for one module/task group.

    Polls hardware at a configurable rate, stores latest values under a lock.
    The main loop retrieves values via read_latest() — zero I/O, instant return.
    """

    # After this many consecutive read errors, replace cached values with NaN
    # so downstream sees 'bad' quality instead of frozen stale values.
    ERRORS_BEFORE_NAN = 3

    def __init__(self, name: str, read_fn, poll_hz: float):
        self.name = name
        self._read_fn = read_fn   # callable() -> Dict[str, Tuple[float, float]]
        self._poll_hz = min(poll_hz, MAX_DI_POLL_HZ)
        self._latest: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stats = _ReaderStats()
        self._nan_applied = False  # True once values have been set to NaN for this error streak

    @property
    def poll_hz(self) -> float:
        return self._poll_hz

    def start(self):
        """Launch the reader thread."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"Reader-{self.name}",
            daemon=True
        )
        self._thread.start()
        logger.info(f"[READER] {self.name} started at {self._poll_hz:.1f} Hz")

    def stop(self):
        """Signal and join the reader thread."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            # Slow readers (TC at 1-2 Hz) may block in task.read() for up to
            # 1/poll_hz seconds.  Give at least 2x the read period + 2s margin.
            join_timeout = max(3.0, 2.0 / max(self._poll_hz, 0.1) + 2.0)
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                logger.warning(f"[READER] {self.name} did not stop within "
                               f"{join_timeout:.1f}s")
        self._thread = None

    def read_latest(self) -> Dict[str, Tuple[float, float]]:
        """Return a snapshot of the latest values (no I/O)."""
        with self._lock:
            return dict(self._latest)

    def get_stats(self) -> dict:
        """Return timing statistics."""
        d = self._stats.to_dict()
        d['poll_hz'] = self._poll_hz
        d['name'] = self.name
        return d

    def _loop(self):
        """Main reader loop — polls at self._poll_hz with epoch-anchored timing."""
        interval = 1.0 / self._poll_hz if self._poll_hz > 0 else 0.0
        next_time = time.monotonic()
        first_read_logged = False
        consecutive_errors = 0
        last_error_log_time = 0.0

        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                values = self._read_fn()
                elapsed_ms = (time.monotonic() - t0) * 1000.0

                with self._lock:
                    self._latest.update(values)

                self._stats.read_count += 1
                self._stats.last_read_ms = elapsed_ms
                self._stats.total_read_ms += elapsed_ms
                consecutive_errors = 0  # reset on success
                self._nan_applied = False  # reset NaN flag on successful read

                if not first_read_logged:
                    n = len(values)
                    logger.info(f"[READER] {self.name}: first read -> {n} values in {elapsed_ms:.1f}ms")
                    first_read_logged = True

            except Exception as e:
                self._stats.error_count += 1
                consecutive_errors += 1
                # Throttle error logging: log first error, then every 10s
                now = time.monotonic()
                if consecutive_errors == 1 or (now - last_error_log_time) > 10.0:
                    logger.error(
                        f"[READER] {self.name}: read error (x{consecutive_errors}): {e}"
                    )
                    last_error_log_time = now

                # After N consecutive errors, replace ALL cached values with NaN
                # so the dashboard shows 'bad' quality instead of a frozen value
                if consecutive_errors >= self.ERRORS_BEFORE_NAN and not self._nan_applied:
                    nan_ts = time.time()
                    with self._lock:
                        for ch_name in list(self._latest.keys()):
                            self._latest[ch_name] = (float('nan'), nan_ts)
                    self._nan_applied = True
                    logger.warning(
                        f"[READER] {self.name}: {consecutive_errors} consecutive errors "
                        f"— set {len(self._latest)} channels to NaN"
                    )

            # Epoch-anchored sleep to prevent cumulative drift
            next_time += interval
            sleep_s = next_time - time.monotonic()
            if sleep_s > 0:
                self._stop.wait(sleep_s)
            else:
                # Overrun — reset anchor to avoid burst reads
                next_time = time.monotonic()

# Try to import NI-DAQmx, fall back to mock for testing
try:
    import nidaqmx
    from nidaqmx.constants import TerminalConfiguration, AcquisitionType
    from nidaqmx.stream_readers import AnalogMultiChannelReader
    import numpy as np
    DAQMX_AVAILABLE = True
except ImportError:
    DAQMX_AVAILABLE = False
    logger.warning("NI-DAQmx not available - using mock hardware")

@dataclass
class HardwareConfig:
    """Hardware configuration."""
    device_name: str = "cRIO1"
    scan_rate_hz: float = 4.0
    di_poll_rate_hz: float = DEFAULT_DI_POLL_HZ
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

class HardwareInterface(ABC):
    """Abstract base class for hardware interface."""

    @abstractmethod
    def start(self) -> bool:
        """Start all tasks (and reader threads). Returns True on success."""
        pass

    @abstractmethod
    def stop(self):
        """Stop all tasks and set outputs to safe state."""
        pass

    @abstractmethod
    def read_all(self) -> Dict[str, Tuple[float, float]]:
        """Read all input channels (legacy — calls read_latest internally).
        Returns: {channel_name: (value, timestamp)}
        """
        pass

    def read_latest(self) -> Dict[str, Tuple[float, float]]:
        """Return latest cached values from all reader threads (no I/O).
        Default implementation falls back to read_all() for subclasses
        that haven't been updated yet.
        """
        return self.read_all()

    def get_reader_stats(self) -> Dict[str, dict]:
        """Return per-module reader timing statistics."""
        return {}

    @abstractmethod
    def write_output(self, channel: str, value: float) -> bool:
        """
        Write to output channel.
        Returns: True on success
        """
        pass

    @abstractmethod
    def set_safe_state(self):
        """Set all outputs to their default/safe values."""
        pass

    def read_output_from_hardware(self, channel: str) -> Optional[float]:
        """Read back the actual physical value from an output channel.

        Returns None if readback is not supported or fails.
        Subclasses should override for hardware-specific implementation.
        """
        return None

class MockHardware(HardwareInterface):
    """
    Mock hardware for testing without real NI-DAQmx.
    Simulates channel values and output writes.
    Supports fault injection for testing error-handling paths.
    """

    def __init__(self, config: HardwareConfig):
        self.config = config
        self._running = False
        self._values: Dict[str, float] = {}
        self._outputs: Dict[str, float] = {}

        # Fault injection controls (test helpers)
        self._simulate_read_error: bool = False       # read_all() raises on next call
        self._simulate_write_error: bool = False      # write_output() returns False
        self._simulate_nan_channels: set = set()      # channels that return NaN
        self._simulate_start_failure: bool = False    # start() returns False

        # Initialize with default values
        for name, ch in config.channels.items():
            if ChannelType.is_input(ch.channel_type):
                self._values[name] = 0.0
            else:
                self._outputs[name] = ch.default_value

    def start(self) -> bool:
        if self._simulate_start_failure:
            logger.warning("[MockHW] Simulated start failure")
            return False
        logger.info("[MockHW] Starting mock hardware")
        self._running = True
        return True

    def stop(self):
        logger.info("[MockHW] Stopping mock hardware")
        self._running = False
        self.set_safe_state()

    def read_all(self) -> Dict[str, Tuple[float, float]]:
        if not self._running:
            return {}

        if self._simulate_read_error:
            self._simulate_read_error = False  # One-shot
            raise RuntimeError("[MockHW] Simulated read error")

        now = time.time()
        result = {}

        for name, ch in self.config.channels.items():
            if ChannelType.is_input(ch.channel_type):
                # Fault injection: return NaN for specific channels
                if name in self._simulate_nan_channels:
                    result[name] = (float('nan'), now)
                    continue
                # Simulate slowly varying values
                base = math.sin(now * 0.1) * 5  # Oscillate between -5 and 5
                internal_type = ChannelType.get_internal_type(ch.channel_type)
                if internal_type == 'digital_input':
                    value = 1.0 if base > 0 else 0.0
                else:
                    value = base + ch.scale_offset
                self._values[name] = value
                result[name] = (value, now)

        return result

    def write_output(self, channel: str, value: float) -> bool:
        if channel not in self._outputs and channel not in self.config.channels:
            logger.warning(f"[MockHW] Unknown output channel: {channel}")
            return False

        if self._simulate_write_error:
            logger.warning(f"[MockHW] Simulated write error on {channel}")
            return False

        logger.debug(f"[MockHW] Write {channel} = {value}")
        self._outputs[channel] = value
        return True

    def set_safe_state(self):
        for name, ch in self.config.channels.items():
            if ChannelType.is_output(ch.channel_type):
                self._outputs[name] = ch.default_value
        logger.info("[MockHW] Outputs set to safe state")

    def read_latest(self) -> Dict[str, Tuple[float, float]]:
        """MockHardware: same as read_all() — no background threads in mock."""
        return self.read_all()

    def get_reader_stats(self) -> Dict[str, dict]:
        """MockHardware: no reader threads — return empty stats."""
        return {}

    def read_output_from_hardware(self, channel: str) -> Optional[float]:
        """Mock: return stored output value (simulates hardware readback)."""
        return self._outputs.get(channel)

    def set_input_value(self, channel: str, value: float):
        """Test helper: Set a specific input value."""
        self._values[channel] = value

    def get_output_value(self, channel: str) -> Optional[float]:
        """Test helper: Get current output value."""
        return self._outputs.get(channel)

class NIDAQmxHardware(HardwareInterface):
    """
    Real NI-DAQmx hardware interface.
    Creates and manages DAQmx tasks for all channels.
    """

    def __init__(self, config: HardwareConfig):
        if not DAQMX_AVAILABLE:
            raise RuntimeError("NI-DAQmx not available on this system")

        self.config = config
        self._running = False

        # Tasks by type
        self._di_tasks: Dict[str, Any] = {}  # Digital input tasks
        self._ai_tasks: Dict[str, Any] = {}  # Analog input tasks
        self._do_tasks: Dict[str, Any] = {}  # Digital output tasks
        self._ao_tasks: Dict[str, Any] = {}  # Analog output tasks
        self._ctr_in_tasks: Dict[str, Any] = {}   # Counter input tasks (per-channel)
        self._ctr_out_tasks: Dict[str, Any] = {}  # Counter/pulse output tasks (per-channel)
        self._counter_rollover: Dict[str, Dict] = {}  # rollover tracking for edge count mode

        # Channel mappings: task_key -> [channel_names]
        self._di_channels: Dict[str, List[str]] = {}
        self._ai_channels: Dict[str, List[str]] = {}
        self._do_channels: Dict[str, List[str]] = {}
        self._ao_channels: Dict[str, List[str]] = {}

        # Output state tracking
        self._output_values: Dict[str, float] = {}
        self._output_lock = threading.Lock()

        # Channels that failed during task creation
        self._failed_channels: set = set()

        # Momentary pulse timers (for relay auto-revert)
        self._momentary_timers: Dict[str, threading.Timer] = {}

        # Slow tasks (TC modules that take ~1s to read due to autozero)
        self._slow_tasks: set = set()

        # Timed tasks (modules that require sample clock timing)
        self._timed_tasks: set = set()

        # Stream readers for fast NumPy-based continuous reads (task_key -> AnalogMultiChannelReader)
        self._stream_readers: Dict[str, Any] = {}

        # DI tasks with change detection timing (event-driven, not polling)
        self._change_detect_tasks: set = set()

        # Per-module reader threads — each module type polls at its natural rate
        self._reader_threads: List[_ReaderThread] = []

        # Hardware-detected module types (module_name -> ChannelType)
        # This is the SINGLE SOURCE OF TRUTH for channel types
        self._detected_module_types: Dict[str, str] = {}

        # Hardware-detected product types (module_name -> product_type string)
        # Used for combo module lookup (e.g., NI 9207)
        self._detected_product_types: Dict[str, str] = {}

        # Per-channel hardware limits cache (populated during module detection)
        self._channel_hw_limits: Dict[str, Dict[str, float]] = {}

        self._detect_module_types()

    def _detect_module_types(self):
        """
        Query NI-DAQmx for actual hardware module types.

        This makes the HARDWARE the single source of truth for channel types,
        not the config file. If Mod6 is an NI 9265 (current output), we use
        current_output regardless of what the config says.
        """
        try:
            system = nidaqmx.system.System.local()
            for device in system.devices:
                module_name = device.name  # e.g., "Mod1", "Mod2"
                product_type = device.product_type  # e.g., "NI 9213", "NI 9265"

                # Use channel_types.py MODULE_TYPE_MAP to get correct type
                detected_type = get_module_channel_type(product_type)
                self._detected_module_types[module_name] = detected_type.value
                self._detected_product_types[module_name] = product_type

                # Cache hardware limits for output modules
                hw_limits = get_module_hardware_limits(product_type)
                if hw_limits:
                    # Apply limits to all channels on this module
                    for ch_name, ch_cfg in self.config.channels.items():
                        if ch_cfg.physical_channel.startswith(module_name + '/'):
                            self._channel_hw_limits[ch_name] = hw_limits

                logger.info(f"[HW DETECT] {module_name}: {product_type} -> {detected_type.value}")

        except Exception as e:
            logger.warning(f"Could not auto-detect module types: {e}")
            # Continue without detection - will use config types as fallback

    def _get_actual_channel_type(self, ch: ChannelConfig) -> str:
        """
        Get the ACTUAL channel type from hardware detection.

        If hardware detection found the module, use that type.
        For combo modules (e.g., NI 9207), the type depends on channel index.
        Otherwise fall back to config type (with warning).
        """
        # Extract module name from physical channel
        module = ch.physical_channel.split('/')[0] if '/' in ch.physical_channel else None

        if module and module in self._detected_module_types:
            # Check if this is a combo module where type depends on channel index
            product_type = self._detected_product_types.get(module, '')
            if product_type:
                ch_index = _get_physical_channel_index(ch.physical_channel)
                combo_type = get_combo_channel_type(product_type, ch_index)
                if combo_type is not None:
                    return combo_type.value

            detected = self._detected_module_types[module]
            if detected != ch.channel_type:
                logger.warning(
                    f"[HW OVERRIDE] {ch.name}: config says '{ch.channel_type}' "
                    f"but hardware is '{detected}' - using hardware type"
                )
            return detected

        # No hardware detection available, use config
        return ch.channel_type

    def start(self) -> bool:
        """Create DAQmx tasks, then launch per-module reader threads."""
        try:
            self._create_tasks()
            self._start_tasks()
            self._running = True
            self._start_reader_threads()
            logger.info(f"NI-DAQmx hardware started (scan={self.config.scan_rate_hz} Hz, "
                        f"DI poll={self.config.di_poll_rate_hz} Hz, "
                        f"readers={len(self._reader_threads)})")
            return True
        except Exception as e:
            logger.error(f"Failed to start hardware: {e}")
            self.stop()
            return False

    def _start_reader_threads(self):
        """Create and start a _ReaderThread for each task group."""
        self._stop_reader_threads()

        di_poll_hz = min(self.config.di_poll_rate_hz, MAX_DI_POLL_HZ)
        ai_poll_hz = self.config.scan_rate_hz
        tc_poll_hz = DEFAULT_TC_POLL_HZ

        # DI reader threads (one per DI task/module)
        for task_key, task in self._di_tasks.items():
            ch_names = self._di_channels[task_key]
            reader = _ReaderThread(
                name=task_key,
                read_fn=self._make_di_read_fn(task_key, task, ch_names),
                poll_hz=di_poll_hz,
            )
            self._reader_threads.append(reader)

        # AI reader threads (one per AI task/module)
        for task_key, task in self._ai_tasks.items():
            ch_names = self._ai_channels[task_key]
            is_slow = task_key in self._slow_tasks
            is_timed = task_key in self._timed_tasks
            reader = _ReaderThread(
                name=task_key,
                read_fn=self._make_ai_read_fn(task_key, task, ch_names, is_slow, is_timed),
                poll_hz=tc_poll_hz if is_slow else ai_poll_hz,
            )
            self._reader_threads.append(reader)

        # Counter reader threads (one per counter channel)
        for ch_name, task in self._ctr_in_tasks.items():
            reader = _ReaderThread(
                name=f"CTR_{ch_name}",
                read_fn=self._make_ctr_read_fn(ch_name, task),
                poll_hz=ai_poll_hz,
            )
            self._reader_threads.append(reader)

        # Start all reader threads
        for reader in self._reader_threads:
            reader.start()

    def _stop_reader_threads(self):
        """Stop all reader threads."""
        for reader in self._reader_threads:
            reader.stop()
        self._reader_threads.clear()

    # -- Reader function factories (closures for _ReaderThread) ---------------

    def _make_di_read_fn(self, task_key: str, task, ch_names: List[str]):
        """Return a callable that reads one DI task and returns {name: (value, ts)}.

        If change detection timing is configured, task.read() blocks until a
        line changes state (like LabVIEW's change detection event).  On timeout
        the last known values are returned — the hardware hasn't changed.
        """
        config_channels = self.config.channels
        is_change_detect = task_key in self._change_detect_tasks
        # Cache for change-detection mode: holds the last valid read so we can
        # return it on timeout (no state change) instead of erroring.
        last_result: Dict[str, Tuple[float, float]] = {}

        def _parse_values(values, now) -> Dict[str, Tuple[float, float]]:
            if not isinstance(values, list):
                values = [values]
            result = {}
            for i, ch_name in enumerate(ch_names):
                if i >= len(values):
                    result[ch_name] = (float('nan'), now)
                    continue
                ch_config = config_channels.get(ch_name)
                value = 1.0 if values[i] else 0.0
                if ch_config and ch_config.invert:
                    value = 1.0 - value
                result[ch_name] = (value, now)
            return result

        def _read() -> Dict[str, Tuple[float, float]]:
            nonlocal last_result
            try:
                values = task.read(timeout=DI_READ_TIMEOUT_S)
            except Exception as e:
                err_str = str(e).lower()
                if is_change_detect and last_result and ('timeout' in err_str or '-50400' in err_str):
                    # Change detection timeout — no lines changed, values are still valid.
                    # Update timestamps so stale detection doesn't fire.
                    now = time.time()
                    return {ch: (val, now) for ch, (val, _) in last_result.items()}
                raise  # Real error — let _ReaderThread NaN handler deal with it
            now = time.time()
            result = _parse_values(values, now)
            last_result = result
            return result

        return _read

    def _make_ai_read_fn(self, task_key: str, task, ch_names: List[str],
                          is_slow: bool, is_timed: bool):
        """Return a callable that reads one AI task and returns {name: (value, ts)}.

        For timed (continuous) tasks, uses AnalogMultiChannelReader with
        pre-allocated NumPy arrays for zero-copy reads — same fast path as
        cDAQ hardware_reader.py.

        For on-demand tasks (TC/RTD), uses task.read() since those modules
        don't support continuous buffered acquisition.
        """
        config_channels = self.config.channels
        n_channels = len(ch_names)
        stream_reader = self._stream_readers.get(task_key)

        def _read() -> Dict[str, Tuple[float, float]]:
            if is_timed and stream_reader is not None:
                # FAST PATH: AnalogMultiChannelReader with NumPy (same as cDAQ)
                available = task.in_stream.avail_samp_per_chan
                if available <= 0:
                    return {}  # No samples ready yet

                # Read all available samples into pre-allocated NumPy array
                samples_to_read = min(available, MIN_BUFFER_SAMPLES)
                buffer = np.zeros((n_channels, samples_to_read), dtype=np.float64)
                stream_reader.read_many_sample(
                    buffer,
                    number_of_samples_per_channel=samples_to_read,
                    timeout=0.1  # Short timeout — data should be ready
                )

                # Extract latest sample from each channel (last column)
                now = time.time()
                result = {}
                for i, ch_name in enumerate(ch_names):
                    raw_value = buffer[i, -1]  # Last sample = most recent
                    ch_config = config_channels.get(ch_name)
                    # DAQmx current input tasks return Amperes; channel unit is mA
                    if ch_config and ch_config.channel_type == 'current_input':
                        raw_value *= 1000.0
                    value = apply_scaling(ch_config, raw_value)
                    result[ch_name] = (value, now)
                return result
            else:
                # SLOW PATH: on-demand task.read() for TC/RTD modules
                timeout = AI_SLOW_READ_TIMEOUT_S if is_slow else AI_ONDEMAND_READ_TIMEOUT_S
                values = task.read(timeout=timeout)
                if not isinstance(values, list):
                    values = [values]

                now = time.time()
                result = {}
                for i, ch_name in enumerate(ch_names):
                    if i >= len(values):
                        result[ch_name] = (float('nan'), now)
                        continue
                    ch_config = config_channels.get(ch_name)
                    raw_value = values[i]
                    # DAQmx current input tasks return Amperes; channel unit is mA
                    if ch_config and ch_config.channel_type == 'current_input':
                        raw_value *= 1000.0
                    value = apply_scaling(ch_config, raw_value)
                    result[ch_name] = (value, now)
                return result

        return _read

    def _make_ctr_read_fn(self, ch_name: str, task):
        """Return a callable that reads one counter task and returns {name: (value, ts)}."""
        config_channels = self.config.channels
        rollover = self._counter_rollover

        def _read() -> Dict[str, Tuple[float, float]]:
            value = task.read(timeout=CTR_READ_TIMEOUT_S)
            ch_config = config_channels.get(ch_name)
            if ch_config and ch_config.counter_mode == 'period' and value > 0:
                value = 1.0 / value
            elif ch_config and ch_config.counter_mode == 'count':
                if ch_name not in rollover:
                    rollover[ch_name] = {'prev': 0, 'offset': 0}
                state = rollover[ch_name]
                raw = int(value)
                if raw < state['prev']:
                    state['offset'] += 0x100000000
                    logger.info(f"Counter rollover on {ch_name}: {state['prev']} -> {raw}")
                state['prev'] = raw
                value = raw + state['offset']
            return {ch_name: (value, time.time())}

        return _read

    def stop(self):
        """Stop all tasks and clean up."""
        self._running = False

        # Stop reader threads FIRST (before closing the tasks they use)
        self._stop_reader_threads()

        self.set_safe_state()

        # Stop and close all tasks
        for tasks in [self._di_tasks, self._ai_tasks, self._do_tasks, self._ao_tasks]:
            for task in tasks.values():
                try:
                    task.stop()
                    task.close()
                except Exception as e:
                    logger.warning(f"Error stopping task: {e}")

        # Stop and close counter/pulse tasks (per-channel)
        for name, task in self._ctr_in_tasks.items():
            try:
                task.stop()
                task.close()
                logger.debug(f"Closed counter input task: {name}")
            except Exception as e:
                logger.warning(f"Error stopping counter input {name}: {e}")

        for name, task in self._ctr_out_tasks.items():
            try:
                task.stop()
                task.close()
                logger.debug(f"Closed pulse output task: {name}")
            except Exception as e:
                logger.warning(f"Error stopping pulse output {name}: {e}")

        self._di_tasks.clear()
        self._ai_tasks.clear()
        self._do_tasks.clear()
        self._ao_tasks.clear()
        self._ctr_in_tasks.clear()
        self._ctr_out_tasks.clear()

        # Clear channel mappings to allow reconfiguration
        self._di_channels.clear()
        self._ai_channels.clear()
        self._do_channels.clear()
        self._ao_channels.clear()

        # Clear task tracking
        self._slow_tasks.clear()
        self._timed_tasks.clear()
        self._stream_readers.clear()
        self._change_detect_tasks.clear()

        # Cancel momentary timers
        for timer in self._momentary_timers.values():
            timer.cancel()
        self._momentary_timers.clear()

        # Clear counter rollover tracking to prevent stale offsets on reconfiguration
        self._counter_rollover.clear()

        logger.info("NI-DAQmx hardware stopped")

    def reinit_sample_rate(self) -> bool:
        """Reinitialize DAQmx tasks for a new sample rate WITHOUT resetting outputs.

        Used when scan_rate_hz changes at runtime. Preserves output values
        across the teardown/rebuild so heaters/valves/solenoids are not interrupted.

        Returns True on success, False on failure (outputs remain at last known state).
        """
        # 1. Preserve current output values
        with self._output_lock:
            preserved_outputs = dict(self._output_values)
        logger.info(f"Reinit sample rate: preserving {len(preserved_outputs)} output values")

        # Stop reader threads before closing tasks
        self._stop_reader_threads()

        # 2. Stop tasks WITHOUT safe state — just close DAQmx resources
        self._running = False
        for tasks in [self._di_tasks, self._ai_tasks, self._do_tasks, self._ao_tasks]:
            for task in tasks.values():
                try:
                    task.stop()
                    task.close()
                except Exception as e:
                    logger.warning(f"Error stopping task during reinit: {e}")

        for name, task in self._ctr_in_tasks.items():
            try:
                task.stop()
                task.close()
            except Exception as e:
                logger.warning(f"Error stopping counter input {name} during reinit: {e}")

        for name, task in self._ctr_out_tasks.items():
            try:
                task.stop()
                task.close()
            except Exception as e:
                logger.warning(f"Error stopping pulse output {name} during reinit: {e}")

        # Clear task/channel maps
        self._di_tasks.clear()
        self._ai_tasks.clear()
        self._do_tasks.clear()
        self._ao_tasks.clear()
        self._ctr_in_tasks.clear()
        self._ctr_out_tasks.clear()
        self._di_channels.clear()
        self._ai_channels.clear()
        self._do_channels.clear()
        self._ao_channels.clear()
        self._slow_tasks.clear()
        self._timed_tasks.clear()
        self._stream_readers.clear()
        self._change_detect_tasks.clear()
        for timer in self._momentary_timers.values():
            timer.cancel()
        self._momentary_timers.clear()
        self._counter_rollover.clear()

        # 3. Recreate and start tasks with new sample rate
        try:
            self._create_tasks()
            self._start_tasks()
            self._running = True
            self._start_reader_threads()

            # 4. Restore preserved output values
            for ch_name, value in preserved_outputs.items():
                try:
                    self.write_output(ch_name, value)
                except Exception as e:
                    logger.error(f"Failed to restore output {ch_name}={value} after reinit: {e}")

            logger.info(f"Hardware reinit complete (sample rate: {self.config.scan_rate_hz} Hz, "
                        f"restored {len(preserved_outputs)} outputs)")
            return True

        except Exception as e:
            logger.error(f"Hardware reinit failed: {e}")
            # Attempt recovery — try to restart with old tasks
            try:
                self._create_tasks()
                self._start_tasks()
                self._running = True
                self._start_reader_threads()
                for ch_name, value in preserved_outputs.items():
                    try:
                        self.write_output(ch_name, value)
                    except Exception:
                        pass
                logger.warning("Hardware reinit recovery: tasks restarted but sample rate may not have changed")
            except Exception as e2:
                logger.critical(f"Hardware reinit recovery also failed: {e2} — hardware is stopped!")
            return False

    def _get_physical_path(self, physical_channel: str) -> str:
        """
        Get the correct NI-DAQmx physical channel path.

        For cRIO modules (Mod1, Mod2, etc.), the path is used directly.
        For other devices, the device_name prefix is added.
        """
        # cRIO module channels start with "Mod" and are already fully qualified
        if physical_channel.startswith('Mod'):
            return physical_channel
        # For other devices, prepend the device name
        return f"{self.config.device_name}/{physical_channel}"

    def _create_tasks(self):
        """Create DAQmx tasks grouped by module/type."""
        # Clean up any leftover tasks from a previous failed start
        for tasks_dict in [self._di_tasks, self._ai_tasks, self._do_tasks, self._ao_tasks]:
            for task in tasks_dict.values():
                try:
                    task.close()
                except Exception:
                    pass
            tasks_dict.clear()
        for task in list(self._ctr_in_tasks.values()) + list(self._ctr_out_tasks.values()):
            try:
                task.close()
            except Exception:
                pass
        self._ctr_in_tasks.clear()
        self._ctr_out_tasks.clear()

        # Group channels by module and type
        di_by_module: Dict[str, List[ChannelConfig]] = {}
        ai_by_module: Dict[str, List[ChannelConfig]] = {}
        do_by_module: Dict[str, List[ChannelConfig]] = {}
        ao_by_module: Dict[str, List[ChannelConfig]] = {}
        ctr_in_channels: List[ChannelConfig] = []   # Counter inputs (per-channel tasks)
        ctr_out_channels: List[ChannelConfig] = []  # Counter/pulse outputs (per-channel tasks)

        for name, ch in self.config.channels.items():
            # Extract module from physical channel (e.g., "Mod1/ai0" -> "Mod1")
            module = ch.physical_channel.split('/')[0] if '/' in ch.physical_channel else 'default'

            # Get ACTUAL channel type from hardware detection (single source of truth)
            actual_type = self._get_actual_channel_type(ch)

            # Map semantic channel type to internal DAQmx type
            internal_type = ChannelType.get_internal_type(actual_type)
            logger.debug(f"Channel {name}: config={ch.channel_type} actual={actual_type} -> internal={internal_type}")

            if internal_type == 'digital_input':
                di_by_module.setdefault(module, []).append(ch)
            elif internal_type == 'analog_input':
                ai_by_module.setdefault(module, []).append(ch)
            elif internal_type == 'digital_output':
                do_by_module.setdefault(module, []).append(ch)
            elif internal_type == 'analog_output':
                ao_by_module.setdefault(module, []).append(ch)
            elif internal_type in ('counter_input', 'frequency_input'):
                ctr_in_channels.append(ch)
            elif internal_type == 'counter_output':
                ctr_out_channels.append(ch)
            else:
                logger.warning(f"Unknown channel type '{ch.channel_type}' for {name}, skipping")

        # Create digital input tasks (one per module)
        # Each module is isolated — a failure on one module does not prevent others
        for module, channels in di_by_module.items():
            task_key = f"DI_{module}"
            try:
                task = nidaqmx.Task(task_key)
                self._di_channels[task_key] = []

                # CRITICAL: Sort channels by physical index before adding to task
                # DAQmx returns values in the order channels are added
                sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

                for ch in sorted_channels:
                    full_path = self._get_physical_path(ch.physical_channel)
                    task.di_channels.add_di_chan(full_path)
                    self._di_channels[task_key].append(ch.name)

                # Attempt change detection timing (like LabVIEW).
                # Some modules (e.g. NI 9425 on cRIO) accept the config call but
                # fail at read-time with error -201020.  We verify by doing a test
                # read immediately — if it fails, we recreate the task as plain polling.
                change_detect_ok = False
                try:
                    all_lines = ", ".join(
                        self._get_physical_path(ch.physical_channel) for ch in sorted_channels
                    )
                    task.timing.cfg_change_detection_timing(
                        rising_edge_chan=all_lines,
                        falling_edge_chan=all_lines,
                    )
                    # Test read to verify change detection actually works.
                    # Use a very short timeout — we expect a timeout (no change)
                    # or actual data, both are OK.  Error -201020 means it's broken.
                    try:
                        task.read(timeout=0.05)
                        change_detect_ok = True
                    except Exception as test_e:
                        err_str = str(test_e)
                        if 'timeout' in err_str.lower() or '-50400' in err_str:
                            # Timeout is expected (no state change yet) — change detection works
                            change_detect_ok = True
                        else:
                            # Error -201020 or similar — module doesn't actually support it
                            logger.info(
                                f"[DI] {task_key}: change detection configured but test read "
                                f"failed ({test_e}), recreating as polling task"
                            )
                except Exception as e:
                    logger.info(f"[DI] {task_key}: change detection not supported ({e}), using polling")

                if change_detect_ok:
                    self._change_detect_tasks.add(task_key)
                    logger.info(
                        f"[DI] {task_key}: change detection timing verified OK "
                        f"({len(sorted_channels)} lines)"
                    )
                else:
                    # Recreate the task without change detection
                    try:
                        task.close()
                    except Exception:
                        pass
                    task = nidaqmx.Task(task_key)
                    self._di_channels[task_key] = []
                    for ch in sorted_channels:
                        full_path = self._get_physical_path(ch.physical_channel)
                        task.di_channels.add_di_chan(full_path)
                        self._di_channels[task_key].append(ch.name)
                    logger.info(f"[DI] {task_key}: using polling mode ({len(sorted_channels)} lines)")

                self._di_tasks[task_key] = task
                logger.debug(f"Created DI task {task_key} with {len(sorted_channels)} channels: {self._di_channels[task_key]}")
            except Exception as e:
                logger.error(f"[TASK] Failed to create DI task {task_key}: {e} — skipping module {module}")
                try:
                    task.close()
                except Exception:
                    pass

        # Create analog input tasks (one per module)
        # Each module is isolated — a TC module failure does not prevent voltage modules
        for module, channels in ai_by_module.items():
            task_key = f"AI_{module}"
            try:
                self._create_ai_task(module, channels)
            except Exception as e:
                logger.error(f"[TASK] Failed to create AI task {task_key}: {e} — skipping module {module}")

        # Create output and counter tasks (also isolated per-module)
        self._create_output_and_counter_tasks(
            do_by_module, ao_by_module, ctr_in_channels, ctr_out_channels
        )

    def _create_ai_task(self, module: str, channels):
        """Create a single AI task for one module. Isolated so failures don't cascade."""
        task_key = f"AI_{module}"
        task = nidaqmx.Task(task_key)
        self._ai_channels[task_key] = []

        try:
            # CRITICAL: Sort channels by physical index before adding to task
            # DAQmx returns values in the order channels are added
            sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))
            logger.info(f"Creating AI task {task_key} with channels: {[ch.name for ch in sorted_channels]}")

            for ch in sorted_channels:
                full_path = self._get_physical_path(ch.physical_channel)

                # Get ACTUAL type from hardware (single source of truth)
                actual_type = self._get_actual_channel_type(ch)

                # Use detected hardware type, not config type
                if actual_type == 'thermocouple':
                    # Thermocouple channel - default to K type if not specified
                    VALID_TC_TYPES = {'B', 'E', 'J', 'K', 'N', 'R', 'S', 'T'}
                    tc_type_str = ch.thermocouple_type or 'K'
                    if tc_type_str.upper() not in VALID_TC_TYPES:
                        logger.warning(
                            f"Channel {ch.name}: invalid thermocouple type '{tc_type_str}' "
                            f"(valid: {sorted(VALID_TC_TYPES)}), defaulting to K-type"
                        )
                        tc_type_str = 'K'
                    tc_type = getattr(nidaqmx.constants.ThermocoupleType,
                                      tc_type_str.upper(), nidaqmx.constants.ThermocoupleType.K)
                    # Map CJC source from config
                    cjc_map = {
                        'INTERNAL': nidaqmx.constants.CJCSource.BUILT_IN,
                        'BUILT_IN': nidaqmx.constants.CJCSource.BUILT_IN,
                        'CONSTANT': nidaqmx.constants.CJCSource.CONSTANT_USER_VALUE,
                        'CHANNEL': nidaqmx.constants.CJCSource.SCANNABLE_CHANNEL,
                    }
                    cjc_str = (ch.cjc_source or 'internal').upper().strip()
                    cjc_source = cjc_map.get(cjc_str, nidaqmx.constants.CJCSource.BUILT_IN)
                    cjc_val = getattr(ch, 'cjc_value', 25.0) if cjc_str == 'CONSTANT' else 25.0

                    logger.info(f"Creating TC channel: {ch.name} ({full_path}) type={tc_type_str} cjc={ch.cjc_source}")
                    task.ai_channels.add_ai_thrmcpl_chan(
                        full_path,
                        thermocouple_type=tc_type,
                        cjc_source=cjc_source,
                        cjc_val=cjc_val
                    )
                elif actual_type == 'current_input':
                    # Current input (e.g., NI 9203, 9207, 9208) - typically ±20mA
                    # cRIO C Series modules have fixed terminal config - use DEFAULT
                    max_current = ch.current_range_ma / 1000.0  # Convert mA to A
                    logger.info(f"Creating current input channel: {ch.name} ({full_path}) range=±{ch.current_range_ma}mA")
                    task.ai_channels.add_ai_current_chan(
                        full_path,
                        min_val=-max_current,
                        max_val=max_current,
                        terminal_config=TerminalConfiguration.DEFAULT
                    )
                elif actual_type == 'rtd':
                    # RTD channel (e.g., NI 9216, 9217, 9226)
                    # Map RTD wiring from config
                    rtd_wiring_map = {
                        '2-wire': nidaqmx.constants.ResistanceConfiguration.TWO_WIRE,
                        '3-wire': nidaqmx.constants.ResistanceConfiguration.THREE_WIRE,
                        '4-wire': nidaqmx.constants.ResistanceConfiguration.FOUR_WIRE,
                    }
                    rtd_wiring = rtd_wiring_map.get(
                        getattr(ch, 'rtd_wiring', '4-wire'),
                        nidaqmx.constants.ResistanceConfiguration.FOUR_WIRE
                    )
                    # Map RTD type from config
                    rtd_type_map = {
                        'PT3750': nidaqmx.constants.RTDType.PT_3750,
                        'PT3850': nidaqmx.constants.RTDType.PT_3850,
                        'PT3851': nidaqmx.constants.RTDType.PT_3851,
                        'PT3911': nidaqmx.constants.RTDType.PT_3911,
                        'PT3916': nidaqmx.constants.RTDType.PT_3916,
                        'PT3920': nidaqmx.constants.RTDType.PT_3920,
                        'PT3928': nidaqmx.constants.RTDType.PT_3928,
                        'CUSTOM': nidaqmx.constants.RTDType.CUSTOM,
                    }
                    rtd_type_str = getattr(ch, 'rtd_type', 'Pt3850')
                    rtd_type = rtd_type_map.get(
                        rtd_type_str.upper().replace('_', ''),
                        nidaqmx.constants.RTDType.PT_3850
                    )
                    logger.info(f"Creating RTD channel: {ch.name} ({full_path}) "
                               f"type={rtd_type_str} wiring={getattr(ch, 'rtd_wiring', '4-wire')}")
                    task.ai_channels.add_ai_rtd_chan(
                        full_path,
                        resistance_config=rtd_wiring,
                        rtd_type=rtd_type
                    )
                elif actual_type == 'resistance_input':
                    # Resistance measurement (e.g., NI 9219 in resistance mode)
                    wiring_map = {
                        '2-wire': nidaqmx.constants.ResistanceConfiguration.TWO_WIRE,
                        '4-wire': nidaqmx.constants.ResistanceConfiguration.FOUR_WIRE,
                    }
                    wiring = wiring_map.get(
                        ch.resistance_wiring,
                        nidaqmx.constants.ResistanceConfiguration.FOUR_WIRE
                    )
                    logger.info(f"Creating resistance channel: {ch.name} ({full_path}) "
                               f"wiring={ch.resistance_wiring}, range=0-{ch.resistance_range}Ω")
                    task.ai_channels.add_ai_resistance_chan(
                        full_path,
                        resistance_config=wiring,
                        current_excit_source=nidaqmx.constants.ExcitationSource.INTERNAL,
                        current_excit_val=RESISTANCE_EXCITATION_A,
                        min_val=0.0,
                        max_val=ch.resistance_range
                    )
                elif actual_type in ('iepe', 'iepe_input'):
                    # IEPE accelerometer/microphone channel (e.g., NI 9230-9234, 9250, 9251)
                    try:
                        logger.info(f"Creating IEPE channel: {ch.name} ({full_path}) "
                                   f"sensitivity={getattr(ch, 'sensitivity', 100.0)}mV/g")
                        task.ai_channels.add_ai_accel_chan(
                            full_path,
                            sensitivity=getattr(ch, 'sensitivity', 100.0),
                            sensitivity_units=nidaqmx.constants.AccelSensitivityUnits.M_VOLTS_PER_G,
                            current_excit_source=nidaqmx.constants.ExcitationSource.INTERNAL,
                            current_excit_val=getattr(ch, 'excitation_current', 0.002),
                        )
                    except Exception:
                        # Fallback to voltage if IEPE not supported
                        logger.warning(f"IEPE setup failed for {ch.name}, falling back to voltage")
                        task.ai_channels.add_ai_voltage_chan(full_path, min_val=-5.0, max_val=5.0)
                elif actual_type == 'bridge_input':
                    # Bridge/Wheatstone bridge input (e.g., NI 9237, 9219)
                    try:
                        logger.info(f"Creating bridge channel: {ch.name} ({full_path}) "
                                   f"excitation={getattr(ch, 'excitation_voltage', 2.5)}V")
                        task.ai_channels.add_ai_bridge_chan(
                            full_path,
                            min_val=-0.002,
                            max_val=0.002,
                            units=nidaqmx.constants.BridgeUnits.M_VOLTS_PER_VOLT,
                            bridge_config=nidaqmx.constants.BridgeConfiguration.FULL_BRIDGE,
                            voltage_excit_source=nidaqmx.constants.ExcitationSource.INTERNAL,
                            voltage_excit_val=getattr(ch, 'excitation_voltage', 2.5),
                        )
                    except Exception:
                        # Fallback to voltage if bridge not supported
                        logger.warning(f"Bridge setup failed for {ch.name}, falling back to voltage")
                        task.ai_channels.add_ai_voltage_chan(full_path, min_val=-0.1, max_val=0.1)
                else:
                    # Voltage input (default for voltage_input, strain_input, etc.)
                    # cRIO C Series modules have fixed terminal config - use DEFAULT
                    logger.info(f"Creating voltage channel: {ch.name} ({full_path}) actual_type={actual_type}")
                    task.ai_channels.add_ai_voltage_chan(
                        full_path,
                        min_val=-ch.voltage_range,
                        max_val=ch.voltage_range,
                        terminal_config=TerminalConfiguration.DEFAULT
                    )

                self._ai_channels[task_key].append(ch.name)

            # Detect module type for logging and rate coercion awareness
            module_type = self._detected_module_types.get(module, '')

            # FALLBACK: If hardware detection missed this module, check channel config types
            on_demand_types = ['thermocouple', 'rtd']
            if not module_type:
                for ch in sorted_channels:
                    ch_type = ch.channel_type
                    if ch_type in on_demand_types:
                        module_type = ch_type
                        logger.warning(
                            f"[TC_FIX] Task {task_key}: hardware detection missed module "
                            f"'{module}', using channel config type '{ch_type}' as fallback"
                        )
                        break

            logger.info(f"[TC_FIX] Task {task_key}: module_type='{module_type}', channels={self._ai_channels[task_key]}")

            # ALL module types use continuous buffered acquisition with
            # AnalogMultiChannelReader + NumPy (NI's recommended fast path).
            # TC/RTD modules support continuous mode — NI's own example
            # (cont_thrmcpl_samples_int_clk.py) demonstrates this.
            # The hardware will coerce the rate to what it can actually achieve.
            buffer_size = max(MIN_BUFFER_SAMPLES, int(self.config.scan_rate_hz * BUFFER_DURATION_S))
            task.timing.cfg_samp_clk_timing(
                rate=self.config.scan_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=buffer_size
            )
            # Check what rate the hardware actually accepted (TC modules coerce lower)
            actual_rate = task.timing.samp_clk_rate
            if abs(actual_rate - self.config.scan_rate_hz) > 0.01:
                logger.warning(
                    f"[RATE COERCED] {task_key}: requested {self.config.scan_rate_hz} Hz, "
                    f"hardware accepted {actual_rate:.4f} Hz ({module_type})"
                )
            logger.info(f"[CONTINUOUS] Task {task_key}: buffer={buffer_size}, rate={actual_rate:.4f} Hz, type={module_type}")
            self._timed_tasks.add(task_key)

            # Create AnalogMultiChannelReader for fast NumPy-based reads
            # (same approach as cDAQ hardware_reader.py — zero-copy into pre-allocated arrays)
            stream_reader = AnalogMultiChannelReader(task.in_stream)
            stream_reader.verify_array_shape = False  # Skip shape check in hot loop (NI perf recommendation)
            self._stream_readers[task_key] = stream_reader
            logger.info(f"[STREAM] {task_key}: AnalogMultiChannelReader created ({len(self._ai_channels[task_key])} channels)")

            self._ai_tasks[task_key] = task
            logger.debug(f"Created AI task {task_key} with {len(channels)} channels")
        except Exception:
            try:
                task.close()
            except Exception:
                pass
            raise

    def _create_output_and_counter_tasks(self, do_by_module, ao_by_module,
                                          ctr_in_channels, ctr_out_channels):
        """Create output and counter tasks (called from _create_tasks)."""
        # Create digital output tasks
        for module, channels in do_by_module.items():
            task_key = f"DO_{module}"
            task = nidaqmx.Task(task_key)
            self._do_channels[task_key] = []

            # CRITICAL: Sort channels by physical index
            sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

            for ch in sorted_channels:
                full_path = self._get_physical_path(ch.physical_channel)
                task.do_channels.add_do_chan(full_path)
                self._do_channels[task_key].append(ch.name)
                self._output_values[ch.name] = ch.default_value

            self._do_tasks[task_key] = task
            logger.debug(f"Created DO task {task_key} with {len(sorted_channels)} channels: {self._do_channels[task_key]}")

        # Create analog output tasks
        for module, channels in ao_by_module.items():
            task_key = f"AO_{module}"
            task = nidaqmx.Task(task_key)
            self._ao_channels[task_key] = []

            # CRITICAL: Sort channels by physical index
            sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

            for ch in sorted_channels:
                full_path = self._get_physical_path(ch.physical_channel)

                # Get ACTUAL type from hardware (single source of truth)
                actual_type = self._get_actual_channel_type(ch)

                if actual_type == 'current_output':
                    # Current output (e.g., NI 9265, 9266) - typically 0-20mA
                    max_current = ch.current_range_ma / 1000.0  # Convert mA to A
                    logger.info(f"Creating current output channel: {ch.name} ({full_path}) range=0-{ch.current_range_ma}mA")
                    task.ao_channels.add_ao_current_chan(
                        full_path,
                        min_val=0.0,
                        max_val=max_current
                    )
                else:
                    # Voltage output (default)
                    logger.info(f"Creating voltage output channel: {ch.name} ({full_path}) actual_type={actual_type}")
                    task.ao_channels.add_ao_voltage_chan(
                        full_path,
                        min_val=-ch.voltage_range,
                        max_val=ch.voltage_range
                    )
                self._ao_channels[task_key].append(ch.name)
                self._output_values[ch.name] = ch.default_value

            self._ao_tasks[task_key] = task
            logger.debug(f"Created AO task {task_key} with {len(sorted_channels)} channels: {self._ao_channels[task_key]}")

        # Create counter input tasks (one per channel — DAQmx counter requirement)
        for ch in ctr_in_channels:
            self._create_counter_input_task(ch)

        # Create pulse/counter output tasks (one per channel)
        for ch in ctr_out_channels:
            self._create_pulse_output_task(ch)

    def _create_counter_input_task(self, ch: ChannelConfig):
        """Create a counter input task for a single channel."""
        try:
            full_path = self._get_physical_path(ch.physical_channel)
            task_key = f"CTR_IN_{ch.name}"
            task = nidaqmx.Task(task_key)

            edge = nidaqmx.constants.Edge.RISING
            if ch.counter_edge == 'falling':
                edge = nidaqmx.constants.Edge.FALLING

            min_freq = ch.counter_min_freq
            max_freq = ch.counter_max_freq

            if ch.counter_mode == 'frequency':
                task.ci_channels.add_ci_freq_chan(
                    full_path,
                    min_val=min_freq,
                    max_val=max_freq,
                    edge=edge
                )
            elif ch.counter_mode == 'count':
                task.ci_channels.add_ci_count_edges_chan(
                    full_path,
                    edge=edge
                )
            elif ch.counter_mode == 'period':
                min_period = 1.0 / max_freq if max_freq > 0 else DEFAULT_MIN_PERIOD_S
                max_period = 1.0 / min_freq if min_freq > 0 else DEFAULT_MAX_PERIOD_S
                task.ci_channels.add_ci_period_chan(
                    full_path,
                    min_val=min_period,
                    max_val=max_period,
                    edge=edge
                )

            self._ctr_in_tasks[ch.name] = task
            logger.info(f"Created counter input: {ch.name} -> {full_path} "
                       f"(mode={ch.counter_mode}, freq={min_freq}-{max_freq}Hz)")

        except Exception as e:
            logger.warning(f"Failed to create counter input task for {ch.name}: {e}")
            self._failed_channels.add(ch.name)

    def _create_pulse_output_task(self, ch: ChannelConfig):
        """Create a pulse/counter output task for a single channel."""
        try:
            full_path = self._get_physical_path(ch.physical_channel)
            task_key = f"CTR_OUT_{ch.name}"
            task = nidaqmx.Task(task_key)

            idle_state = nidaqmx.constants.Level.LOW
            if ch.pulse_idle_state == 'HIGH':
                idle_state = nidaqmx.constants.Level.HIGH

            duty_cycle = ch.pulse_duty_cycle / 100.0  # Convert 0-100% to 0.0-1.0

            task.co_channels.add_co_pulse_chan_freq(
                full_path,
                freq=ch.pulse_frequency,
                duty_cycle=duty_cycle,
                idle_state=idle_state
            )

            # Configure for continuous generation
            task.timing.cfg_implicit_timing(
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )

            task.start()
            self._ctr_out_tasks[ch.name] = task
            self._output_values[ch.name] = ch.pulse_frequency
            logger.info(f"Created pulse output: {ch.name} -> {full_path} "
                       f"(freq={ch.pulse_frequency}Hz, duty={ch.pulse_duty_cycle}%, idle={ch.pulse_idle_state})")

        except Exception as e:
            logger.warning(f"Failed to create pulse output task for {ch.name}: {e}")
            self._failed_channels.add(ch.name)

    def _start_tasks(self):
        """Start all input tasks that require explicit start."""
        # Start timed AI tasks (continuous acquisition)
        # On-demand tasks don't need explicit start
        for task_key in self._timed_tasks:
            if task_key in self._ai_tasks:
                try:
                    self._ai_tasks[task_key].start()
                    logger.debug(f"Started timed task: {task_key}")
                except Exception as e:
                    logger.error(f"Failed to start AI task {task_key}: {e}")

        # Start DI tasks with change detection timing
        # Change detection tasks must be explicitly started to arm the hardware
        for task_key in self._change_detect_tasks:
            if task_key in self._di_tasks:
                try:
                    self._di_tasks[task_key].start()
                    logger.debug(f"Started change detection task: {task_key}")
                except Exception as e:
                    logger.error(f"Failed to start DI task {task_key}: {e}")

    def read_all(self) -> Dict[str, Tuple[float, float]]:
        """Read all input channels (legacy — delegates to read_latest)."""
        return self.read_latest()

    def read_latest(self) -> Dict[str, Tuple[float, float]]:
        """Return latest cached values from all reader threads (no I/O).

        This is the primary read method.  Each reader thread polls its
        hardware task at the appropriate rate and caches the result.
        This method simply merges the latest snapshots — instant return.
        """
        if not self._running:
            return {}

        result: Dict[str, Tuple[float, float]] = {}
        for reader in self._reader_threads:
            result.update(reader.read_latest())
        return result

    def get_reader_stats(self) -> Dict[str, dict]:
        """Return per-module reader timing statistics."""
        return {reader.name: reader.get_stats() for reader in self._reader_threads}

    def _validate_output_value(self, channel: str, value: float, ch_config) -> tuple:
        """Validate and clamp output value to safe range. Returns (valid, clamped_value, reason)."""
        if not isinstance(value, (int, float)):
            return False, value, f"Non-numeric value type: {type(value).__name__}"
        if isinstance(value, float) and (value != value):  # NaN check
            return False, value, "NaN value rejected"
        if math.isinf(value):
            return False, value, "Infinity value rejected"

        if ch_config.channel_type in ('analog_output', 'voltage_output'):
            max_v = ch_config.voltage_range
            if value < -max_v or value > max_v:
                logger.warning(f"Output {channel}: value {value} outside voltage range [-{max_v}, {max_v}], clamping")
                value = max(-max_v, min(max_v, value))
        elif ch_config.channel_type == 'current_output':
            max_ma = ch_config.current_range_ma
            if value < 0 or value > max_ma:
                logger.warning(f"Output {channel}: value {value} outside current range [0, {max_ma}], clamping")
                value = max(0.0, min(max_ma, value))
        elif ch_config.channel_type in ('pulse_output', 'counter_output'):
            max_freq = ch_config.counter_max_freq or 1000000.0
            min_freq = ch_config.counter_min_freq or 0.0
            if value < 0:
                return False, value, f"Negative frequency rejected: {value}"
            if value > 0 and (value < min_freq or value > max_freq):
                logger.warning(f"Output {channel}: freq {value} outside range [{min_freq}, {max_freq}], clamping")
                value = max(min_freq, min(max_freq, value))
        elif ch_config.channel_type == 'digital_output':
            pass  # Boolean coercion handled downstream

        # Cross-check against absolute module hardware limits (cannot be overridden by config)
        hw_limits = self._channel_hw_limits.get(channel)
        if hw_limits:
            if ch_config.channel_type in ('analog_output', 'voltage_output'):
                hw_min = hw_limits.get('voltage_min', -10.0)
                hw_max = hw_limits.get('voltage_max', 10.0)
                if value < hw_min or value > hw_max:
                    logger.error(
                        f"Output {channel}: value {value} exceeds HARDWARE limit "
                        f"[{hw_min}, {hw_max}], clamping"
                    )
                    value = max(hw_min, min(hw_max, value))
            elif ch_config.channel_type == 'current_output':
                hw_min = hw_limits.get('current_min_ma', 0.0)
                hw_max = hw_limits.get('current_max_ma', 20.0)
                if value < hw_min or value > hw_max:
                    logger.error(
                        f"Output {channel}: value {value} exceeds HARDWARE limit "
                        f"[{hw_min}, {hw_max}], clamping"
                    )
                    value = max(hw_min, min(hw_max, value))

        return True, value, ""

    def write_output(self, channel: str, value: float) -> bool:
        """Write to output channel."""
        if not self._running:
            return False

        ch_config = self.config.channels.get(channel)
        if not ch_config:
            logger.warning(f"Unknown output channel: {channel}")
            return False

        # Validate and clamp value to safe hardware range
        valid, value, reason = self._validate_output_value(channel, value, ch_config)
        if not valid:
            logger.error(f"Output {channel} rejected: {reason}")
            return False

        try:
            if ch_config.channel_type == 'digital_output':
                # Find the task containing this channel
                for task_key, channels in self._do_channels.items():
                    if channel in channels:
                        task = self._do_tasks[task_key]
                        bool_value = bool(value)
                        if ch_config.invert:
                            bool_value = not bool_value

                        if len(channels) == 1:
                            # Single-channel task — scalar write is correct
                            task.write(bool_value)
                        else:
                            # Multi-channel task — must write array to avoid
                            # overwriting other channels on the same module
                            ch_idx = channels.index(channel)
                            with self._output_lock:
                                values_array = []
                                for ch_name in channels:
                                    if ch_name == channel:
                                        values_array.append(bool_value)
                                    else:
                                        # Use current known output state
                                        cur = self._output_values.get(ch_name, 0.0)
                                        ch_cfg = self.config.channels.get(ch_name)
                                        cur_bool = bool(cur)
                                        if ch_cfg and ch_cfg.invert:
                                            cur_bool = not cur_bool
                                        values_array.append(cur_bool)
                            task.write(values_array)

                        with self._output_lock:
                            self._output_values[channel] = 1.0 if value else 0.0

                        # Momentary pulse: auto-revert after delay (relay feature)
                        if ch_config.momentary_pulse_ms > 0 and bool_value:
                            # Cancel any existing timer for this channel
                            if channel in self._momentary_timers:
                                self._momentary_timers[channel].cancel()
                            timer = threading.Timer(
                                ch_config.momentary_pulse_ms / 1000.0,
                                self._revert_momentary,
                                args=(channel, ch_config)
                            )
                            timer.daemon = True
                            timer.start()
                            self._momentary_timers[channel] = timer

                        return True

            elif ch_config.channel_type in ('analog_output', 'voltage_output', 'current_output'):
                for task_key, channels in self._ao_channels.items():
                    if channel in channels:
                        task = self._ao_tasks[task_key]
                        # Current output: stored/config values are in mA, DAQmx expects Amperes
                        is_current_out = ch_config.channel_type == 'current_output'
                        write_val = float(value) / 1000.0 if is_current_out else float(value)
                        if len(channels) == 1:
                            # Single-channel task — scalar write
                            task.write(write_val)
                        else:
                            # Multi-channel task — must write array to avoid
                            # overwriting other channels on the same module
                            with self._output_lock:
                                values_array = []
                                for ch_name in channels:
                                    if ch_name == channel:
                                        values_array.append(write_val)
                                    else:
                                        stored = float(self._output_values.get(ch_name, 0.0))
                                        other_cfg = self.config.channels.get(ch_name)
                                        if other_cfg and other_cfg.channel_type == 'current_output':
                                            stored = stored / 1000.0
                                        values_array.append(stored)
                            task.write(values_array)
                        with self._output_lock:
                            self._output_values[channel] = value
                        return True

            elif ch_config.channel_type in ('pulse_output', 'counter_output'):
                if channel in self._ctr_out_tasks:
                    task = self._ctr_out_tasks[channel]
                    # Update frequency by stopping, reconfiguring, restarting
                    new_freq = float(value)
                    if new_freq > 0:
                        task.stop()
                        task.co_channels.all.co_pulse_freq = new_freq
                        task.start()
                        with self._output_lock:
                            self._output_values[channel] = new_freq
                        logger.debug(f"Pulse output {channel}: freq={new_freq}Hz")
                        return True
                    else:
                        task.stop()
                        with self._output_lock:
                            self._output_values[channel] = 0.0
                        logger.debug(f"Pulse output {channel}: stopped (freq=0)")
                        return True

            logger.warning(f"Channel {channel} not found in output tasks")
            return False

        except Exception as e:
            logger.error(f"Error writing {channel}: {e}")
            return False

    def _revert_momentary(self, channel: str, ch_config):
        """Auto-revert a momentary relay/digital output to its default state."""
        try:
            default_val = ch_config.default_value
            logger.info(f"Momentary revert: {channel} -> {default_val} (after {ch_config.momentary_pulse_ms}ms)")
            # Write the default state (typically OFF/False)
            for task_key, channels in self._do_channels.items():
                if channel in channels:
                    task = self._do_tasks[task_key]
                    bool_value = bool(default_val)
                    if ch_config.invert:
                        bool_value = not bool_value
                    task.write(bool_value)
                    with self._output_lock:
                        self._output_values[channel] = default_val
                    break
        except Exception as e:
            logger.error(f"Error reverting momentary output {channel}: {e}")
        finally:
            self._momentary_timers.pop(channel, None)

    def set_safe_state(self):
        """Set all outputs to their default values."""
        # Cancel any pending momentary timers
        for timer in self._momentary_timers.values():
            timer.cancel()
        self._momentary_timers.clear()

        for ch_name, ch_config in self.config.channels.items():
            if 'output' in ch_config.channel_type:
                try:
                    self.write_output(ch_name, ch_config.default_value)
                except Exception as e:
                    logger.error(f"Error setting safe state for {ch_name}: {e}")

        logger.info("Outputs set to safe state")

    def read_output(self, channel: str) -> Optional[float]:
        """Read back the last written value for an output channel."""
        with self._output_lock:
            return self._output_values.get(channel)

    def get_output_values(self) -> Dict[str, float]:
        """Get current output values."""
        with self._output_lock:
            return dict(self._output_values)

    def read_output_values(self) -> Dict[str, float]:
        """Return a copy of all output values under the lock (thread-safe)."""
        with self._output_lock:
            return dict(self._output_values)

    def read_output_from_hardware(self, channel: str) -> Optional[float]:
        """Read back actual physical value from an analog output via DAQmx.

        Only works for analog outputs (AO). Digital outputs do not support
        readback on most NI C-series modules.

        Returns None if readback is not supported or fails.
        """
        ch_config = self.config.channels.get(channel)
        if not ch_config:
            return None

        # Only AO channels support readback via DAQmx
        if ch_config.channel_type not in ('analog_output', 'voltage_output', 'current_output'):
            return None

        for task_key, channels in self._ao_channels.items():
            if channel in channels:
                task = self._ao_tasks.get(task_key)
                if not task:
                    return None
                try:
                    idx = channels.index(channel)
                    values = task.read()
                    if isinstance(values, list):
                        raw = values[idx] if idx < len(values) else None
                    else:
                        raw = values if idx == 0 else None
                    # Current output tasks return Amperes; convert back to mA
                    if raw is not None and ch_config.channel_type == 'current_output':
                        raw *= 1000.0
                    return raw
                except Exception as e:
                    logger.warning(f"Hardware readback failed for {channel}: {e}")
                    return None

        return None

    @property
    def failed_channels(self) -> set:
        """Return the set of channels that failed during task creation."""
        return set(self._failed_channels)

def create_hardware(config: HardwareConfig, use_mock: bool = False) -> HardwareInterface:
    """
    Factory function to create appropriate hardware interface.

    Args:
        config: Hardware configuration
        use_mock: Force mock hardware (for testing)

    Returns:
        HardwareInterface implementation
    """
    if use_mock or not DAQMX_AVAILABLE:
        logger.info("Using mock hardware interface")
        return MockHardware(config)
    else:
        logger.info("Using NI-DAQmx hardware interface")
        return NIDAQmxHardware(config)
