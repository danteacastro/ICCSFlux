"""
Hardware Abstraction Layer for cRIO Node V2

Provides a clean interface to NI-DAQmx hardware.
Supports mocking for unit tests.

Key design:
- Tasks are created once at startup
- Read operations are non-blocking (timeout=0)
- Write operations are immediate
- All errors are caught and logged
"""

import logging
import threading
import time
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod

from .channel_types import ChannelType, get_module_channel_type
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

# Try to import NI-DAQmx, fall back to mock for testing
try:
    import nidaqmx
    from nidaqmx.constants import TerminalConfiguration, AcquisitionType
    DAQMX_AVAILABLE = True
except ImportError:
    DAQMX_AVAILABLE = False
    logger.warning("NI-DAQmx not available - using mock hardware")


@dataclass
class HardwareConfig:
    """Hardware configuration."""
    device_name: str = "cRIO1"
    scan_rate_hz: float = 4.0
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)


class HardwareInterface(ABC):
    """Abstract base class for hardware interface."""

    @abstractmethod
    def start(self) -> bool:
        """Start all tasks. Returns True on success."""
        pass

    @abstractmethod
    def stop(self):
        """Stop all tasks and set outputs to safe state."""
        pass

    @abstractmethod
    def read_all(self) -> Dict[str, Tuple[float, float]]:
        """
        Read all input channels.
        Returns: {channel_name: (value, timestamp)}
        """
        pass

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


class MockHardware(HardwareInterface):
    """
    Mock hardware for testing without real NI-DAQmx.
    Simulates channel values and output writes.
    """

    def __init__(self, config: HardwareConfig):
        self.config = config
        self._running = False
        self._values: Dict[str, float] = {}
        self._outputs: Dict[str, float] = {}

        # Initialize with default values
        for name, ch in config.channels.items():
            if ChannelType.is_input(ch.channel_type):
                self._values[name] = 0.0
            else:
                self._outputs[name] = ch.default_value

    def start(self) -> bool:
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

        now = time.time()
        result = {}

        for name, ch in self.config.channels.items():
            if ChannelType.is_input(ch.channel_type):
                # Simulate slowly varying values
                import math
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

        logger.debug(f"[MockHW] Write {channel} = {value}")
        self._outputs[channel] = value
        return True

    def set_safe_state(self):
        for name, ch in self.config.channels.items():
            if ChannelType.is_output(ch.channel_type):
                self._outputs[name] = ch.default_value
        logger.info("[MockHW] Outputs set to safe state")

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

        # Channel mappings: task_key -> [channel_names]
        self._di_channels: Dict[str, List[str]] = {}
        self._ai_channels: Dict[str, List[str]] = {}
        self._do_channels: Dict[str, List[str]] = {}
        self._ao_channels: Dict[str, List[str]] = {}

        # Output state tracking
        self._output_values: Dict[str, float] = {}

        # Momentary pulse timers (for relay auto-revert)
        self._momentary_timers: Dict[str, threading.Timer] = {}

        # Slow channel caching (for TC modules that take ~1s to read)
        self._slow_tasks: set = set()  # Task keys that are slow (TC modules)
        self._cached_values: Dict[str, Tuple[float, float]] = {}  # channel -> (value, timestamp)
        self._last_slow_read: Dict[str, float] = {}  # task_key -> last read time
        self._slow_read_interval: float = 1.0  # Min seconds between slow task reads

        # Timed tasks (modules that require sample clock timing)
        self._timed_tasks: set = set()  # Task keys that use continuous acquisition

        # Hardware-detected module types (module_name -> ChannelType)
        # This is the SINGLE SOURCE OF TRUTH for channel types
        self._detected_module_types: Dict[str, str] = {}
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

                logger.info(f"[HW DETECT] {module_name}: {product_type} -> {detected_type.value}")

        except Exception as e:
            logger.warning(f"Could not auto-detect module types: {e}")
            # Continue without detection - will use config types as fallback

    def _get_actual_channel_type(self, ch: ChannelConfig) -> str:
        """
        Get the ACTUAL channel type from hardware detection.

        If hardware detection found the module, use that type.
        Otherwise fall back to config type (with warning).
        """
        # Extract module name from physical channel
        module = ch.physical_channel.split('/')[0] if '/' in ch.physical_channel else None

        if module and module in self._detected_module_types:
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
        """Create and start all DAQmx tasks."""
        try:
            self._create_tasks()
            self._start_tasks()
            self._running = True
            logger.info("NI-DAQmx hardware started")
            return True
        except Exception as e:
            logger.error(f"Failed to start hardware: {e}")
            self.stop()
            return False

    def stop(self):
        """Stop all tasks and clean up."""
        self._running = False
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

        # Clear slow task caching
        self._slow_tasks.clear()
        self._cached_values.clear()
        self._last_slow_read.clear()

        # Clear timed tasks tracking
        self._timed_tasks.clear()

        # Cancel momentary timers
        for timer in self._momentary_timers.values():
            timer.cancel()
        self._momentary_timers.clear()

        logger.info("NI-DAQmx hardware stopped")

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
            elif internal_type == 'counter_input':
                ctr_in_channels.append(ch)
            elif internal_type == 'counter_output':
                ctr_out_channels.append(ch)
            else:
                logger.warning(f"Unknown channel type '{ch.channel_type}' for {name}, skipping")

        # Create digital input tasks (one per module)
        for module, channels in di_by_module.items():
            task_key = f"DI_{module}"
            task = nidaqmx.Task(task_key)
            self._di_channels[task_key] = []

            # CRITICAL: Sort channels by physical index before adding to task
            # DAQmx returns values in the order channels are added
            sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

            for ch in sorted_channels:
                full_path = self._get_physical_path(ch.physical_channel)
                task.di_channels.add_di_chan(full_path)
                self._di_channels[task_key].append(ch.name)

            self._di_tasks[task_key] = task
            logger.debug(f"Created DI task {task_key} with {len(sorted_channels)} channels: {self._di_channels[task_key]}")

        # Create analog input tasks (one per module)
        for module, channels in ai_by_module.items():
            task_key = f"AI_{module}"
            task = nidaqmx.Task(task_key)
            self._ai_channels[task_key] = []

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
                    tc_type_str = ch.thermocouple_type or 'K'
                    tc_type = getattr(nidaqmx.constants.ThermocoupleType,
                                      tc_type_str.upper(), nidaqmx.constants.ThermocoupleType.K)
                    logger.info(f"Creating TC channel: {ch.name} ({full_path}) type={tc_type_str}")
                    task.ai_channels.add_ai_thrmcpl_chan(
                        full_path,
                        thermocouple_type=tc_type,
                        cjc_source=nidaqmx.constants.CJCSource.BUILT_IN
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
                    logger.info(f"Creating RTD channel: {ch.name} ({full_path})")
                    task.ai_channels.add_ai_rtd_chan(
                        full_path,
                        resistance_config=nidaqmx.constants.ResistanceConfiguration.FOUR_WIRE,
                        rtd_type=nidaqmx.constants.RTDType.PT_3850
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
                        current_excit_val=0.001,  # 1mA excitation
                        min_val=0.0,
                        max_val=ch.resistance_range
                    )
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

            # Determine if this module supports on-demand reading or requires timing
            # TC and RTD modules support software-timed (on-demand) acquisition
            # Most voltage/current input modules require sample clock timing
            module_type = self._detected_module_types.get(module, '')

            # CRITICAL: Log exactly what we're checking
            logger.info(f"[TC_FIX] Task {task_key}: module_type='{module_type}' from _detected_module_types")
            logger.info(f"[TC_FIX] Task {task_key}: channels={self._ai_channels[task_key]}")

            # Check by channel TYPE (thermocouple, rtd), NOT model number
            on_demand_types = ['thermocouple', 'rtd']
            supports_on_demand = module_type in on_demand_types

            logger.info(f"[TC_FIX] Task {task_key}: '{module_type}' in {on_demand_types} = {supports_on_demand}")

            if supports_on_demand:
                # On-demand mode - no timing config needed
                # CRITICAL: TC and RTD modules MUST use on-demand, NOT continuous
                logger.info(f"[TC_FIX] Task {task_key}: USING ON-DEMAND MODE (module_type={module_type})")

                # TC modules are slow due to autozero - cache their values
                if module_type == 'thermocouple':
                    self._slow_tasks.add(task_key)
                    logger.info(f"[TC_FIX] Task {task_key}: marked as SLOW (TC with autozero)")
            else:
                # This module requires sample clock timing (continuous acquisition)
                # Do NOT use this for TC or RTD modules!
                logger.info(f"[TC_FIX] Task {task_key}: USING CONTINUOUS MODE (module_type={module_type})")
                # Buffer for 10 seconds to handle MQTT/processing delays
                buffer_size = max(100, int(self.config.scan_rate_hz * 10))
                task.timing.cfg_samp_clk_timing(
                    rate=self.config.scan_rate_hz,
                    sample_mode=AcquisitionType.CONTINUOUS,
                    samps_per_chan=buffer_size
                )
                logger.info(f"[BUFFER] Task {task_key}: buffer={buffer_size} samples")
                self._timed_tasks.add(task_key)

            self._ai_tasks[task_key] = task
            logger.debug(f"Created AI task {task_key} with {len(channels)} channels")

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
                min_period = 1.0 / max_freq if max_freq > 0 else 0.001
                max_period = 1.0 / min_freq if min_freq > 0 else 10.0
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
            logger.error(f"Failed to create counter input task for {ch.name}: {e}")

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
            logger.error(f"Failed to create pulse output task for {ch.name}: {e}")

    def _start_tasks(self):
        """Start all input tasks."""
        # Start timed AI tasks (continuous acquisition)
        # On-demand tasks don't need explicit start
        for task_key in self._timed_tasks:
            if task_key in self._ai_tasks:
                try:
                    self._ai_tasks[task_key].start()
                    logger.debug(f"Started timed task: {task_key}")
                except Exception as e:
                    logger.error(f"Failed to start task {task_key}: {e}")

    def read_all(self) -> Dict[str, Tuple[float, float]]:
        """Read all input channels."""
        if not self._running:
            return {}

        now = time.time()
        result = {}

        # Read digital inputs (on-demand, immediate)
        for task_key, task in self._di_tasks.items():
            try:
                # Log periodically (every ~10 seconds based on scan rate)
                log_this_read = (int(now) % 10 == 0) and (now - getattr(self, '_last_di_log', 0) > 5)
                if log_this_read:
                    self._last_di_log = now
                    logger.info(f"[DI_READ] {task_key}: reading {len(self._di_channels.get(task_key, []))} channels...")

                values = task.read(timeout=0.01)
                if not isinstance(values, list):
                    values = [values]

                if log_this_read:
                    logger.info(f"[DI_READ] {task_key}: raw values = {values[:5]}{'...' if len(values) > 5 else ''}")

                for i, ch_name in enumerate(self._di_channels[task_key]):
                    ch_config = self.config.channels.get(ch_name)
                    value = 1.0 if values[i] else 0.0
                    if ch_config and ch_config.invert:
                        value = 1.0 - value
                    result[ch_name] = (value, now)
            except Exception as e:
                logger.warning(f"[DI_READ] Error reading {task_key}: {e}")

        # Read analog inputs
        for task_key, task in self._ai_tasks.items():
            # Check if this is a slow task that should use caching
            is_slow = task_key in self._slow_tasks
            is_timed = task_key in self._timed_tasks
            last_read = self._last_slow_read.get(task_key, 0)
            should_read = not is_slow or (now - last_read) >= self._slow_read_interval

            # Log TC task state periodically
            if is_slow and should_read:
                logger.info(f"[TC_READ] {task_key}: is_slow={is_slow}, is_timed={is_timed}, channels={len(self._ai_channels.get(task_key, []))}")

            if should_read:
                try:
                    # Different read method for timed vs on-demand tasks
                    if is_timed:
                        # Timed (continuous) task - read latest sample from buffer
                        # Returns [[v1], [v2], ...] for multi-channel with 1 sample
                        raw_values = task.read(number_of_samples_per_channel=1, timeout=1.0)
                        # Flatten: [[v1], [v2], ...] -> [v1, v2, ...]
                        if isinstance(raw_values[0], list):
                            values = [v[0] for v in raw_values]
                        else:
                            # Single channel returns [v1] not [[v1]]
                            values = raw_values if isinstance(raw_values, list) else [raw_values]
                        if is_slow:
                            logger.warning(f"[TC_READ] {task_key}: TC task using TIMED mode - THIS IS WRONG!")
                    else:
                        # On-demand read - returns single value or list of values
                        # TC modules should use this path with longer timeout
                        values = task.read(timeout=2.0 if is_slow else 1.0)
                        if not isinstance(values, list):
                            values = [values]
                        if is_slow:
                            logger.info(f"[TC_READ] {task_key}: ON-DEMAND read returned {len(values)} values")
                            # Log first few values for debugging
                            if len(values) >= 2:
                                logger.info(f"[TC_READ] {task_key}: First 3 values: {values[:3]}")

                    # Verify we got the expected number of values
                    expected = len(self._ai_channels.get(task_key, []))
                    if len(values) != expected:
                        logger.error(f"[TC_READ] {task_key}: Expected {expected} values, got {len(values)}!")

                    if is_slow:
                        self._last_slow_read[task_key] = now

                    for i, ch_name in enumerate(self._ai_channels[task_key]):
                        ch_config = self.config.channels.get(ch_name)
                        raw_value = values[i]

                        # Apply scaling (4-20mA, map, linear, or pass-through)
                        value = apply_scaling(ch_config, raw_value)

                        result[ch_name] = (value, now)

                        # Cache value for slow tasks
                        if is_slow:
                            self._cached_values[ch_name] = (value, now)
                except Exception as e:
                    logger.error(f"[TC_READ] Error reading {task_key}: {e}", exc_info=True)
                    # For slow tasks, use cached values on error
                    if is_slow:
                        for ch_name in self._ai_channels.get(task_key, []):
                            if ch_name in self._cached_values:
                                result[ch_name] = self._cached_values[ch_name]
            else:
                # Use cached values for slow tasks between reads
                for ch_name in self._ai_channels.get(task_key, []):
                    if ch_name in self._cached_values:
                        result[ch_name] = self._cached_values[ch_name]

        # Read counter inputs (on-demand, per-channel)
        for ch_name, task in self._ctr_in_tasks.items():
            try:
                value = task.read(timeout=0.1)
                ch_config = self.config.channels.get(ch_name)
                # Period mode: convert period to frequency for display
                if ch_config and ch_config.counter_mode == 'period' and value > 0:
                    value = 1.0 / value
                result[ch_name] = (value, now)
            except Exception as e:
                logger.warning(f"Error reading counter {ch_name}: {e}")

        return result

    def write_output(self, channel: str, value: float) -> bool:
        """Write to output channel."""
        if not self._running:
            return False

        ch_config = self.config.channels.get(channel)
        if not ch_config:
            logger.warning(f"Unknown output channel: {channel}")
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
                        task.write(bool_value)
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
                        task.write(float(value))
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
                        self._output_values[channel] = new_freq
                        logger.debug(f"Pulse output {channel}: freq={new_freq}Hz")
                        return True
                    else:
                        task.stop()
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

    def get_output_values(self) -> Dict[str, float]:
        """Get current output values."""
        return dict(self._output_values)


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
