"""
Hardware Reader for NISystem - CONTINUOUS BUFFERED ACQUISITION

Uses continuous buffered acquisition for reliable, fast data collection.
The hardware samples continuously at a set rate, and software reads from
a FIFO buffer. This eliminates blocking on ADC settling time.

Architecture:
  Hardware Layer:           Software Layer:
  ┌──────────────┐          ┌──────────────┐
  │ DAQ samples  │   FIFO   │ Background   │
  │ continuously │ ──────→  │ thread reads │ → latest_values dict
  │ at 10 Hz     │  Buffer  │ buffer       │
  └──────────────┘          └──────────────┘
                                    ↓
                            read_all() returns
                            latest values INSTANTLY

This is how LabVIEW DAQmx works - hardware timing, software just grabs latest.
"""

import logging
import threading
import time
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from queue import Queue


def _get_physical_channel_index(physical_channel: str) -> int:
    """
    Extract the channel index from a physical_channel string.

    Examples:
        'cDAQ1Mod1/ai0' -> 0
        'cDAQ1Mod2/ai15' -> 15
        'Mod3/port0/line7' -> 7

    This is CRITICAL for correct DAQmx value mapping.
    DAQmx returns values in the order channels are added to the task.
    Channels must be added in physical index order to map correctly.
    """
    match = re.search(r'(\d+)$', physical_channel)
    return int(match.group(1)) if match else 0

from config_parser import NISystemConfig, ChannelConfig, ChannelType, ThermocoupleType, ModuleConfig
from scaling import reverse_scaling

# Try to import nidaqmx
try:
    import nidaqmx
    from nidaqmx.constants import (
        TerminalConfiguration,
        ThermocoupleType as NI_TCType,
        AcquisitionType,
        Edge,
        Level,
        CountDirection,
        CounterFrequencyMethod,
        FrequencyUnits,
        READ_ALL_AVAILABLE,
        SampleTimingType
    )
    from nidaqmx.stream_readers import (
        AnalogMultiChannelReader,
        DigitalMultiChannelReader,
        CounterReader
    )
    import numpy as np
    NIDAQMX_AVAILABLE = True
except Exception:
    NIDAQMX_AVAILABLE = False

logger = logging.getLogger('HardwareReader')

# Configuration for continuous acquisition
SAMPLE_RATE_HZ = 10  # Hardware sample rate (samples per second per channel)
BUFFER_SIZE = 100    # Hardware buffer size (samples per channel)


# Mapping from our ThermocoupleType enum to nidaqmx constants
TC_TYPE_MAP = {
    ThermocoupleType.J: 'J',
    ThermocoupleType.K: 'K',
    ThermocoupleType.T: 'T',
    ThermocoupleType.E: 'E',
    ThermocoupleType.N: 'N',
    ThermocoupleType.R: 'R',
    ThermocoupleType.S: 'S',
    ThermocoupleType.B: 'B',
}


def get_terminal_config(config_str: str):
    """
    Map terminal configuration string to nidaqmx TerminalConfiguration constant.
    Validates the configuration string against supported options.

    Note: nidaqmx uses DIFFERENTIAL (not PSEUDO_DIFF). We accept both for compatibility.
    """
    if not NIDAQMX_AVAILABLE:
        return None

    # nidaqmx API uses DIFF and PSEUDO_DIFF (not DIFFERENTIAL/PSEUDODIFFERENTIAL)
    config_map = {
        'RSE': TerminalConfiguration.RSE,
        'DIFF': TerminalConfiguration.DIFF,
        'DIFFERENTIAL': TerminalConfiguration.DIFF,
        'NRSE': TerminalConfiguration.NRSE,
        'PSEUDO_DIFF': TerminalConfiguration.PSEUDO_DIFF,
        'PSEUDODIFFERENTIAL': TerminalConfiguration.PSEUDO_DIFF,
        'DEFAULT': TerminalConfiguration.DEFAULT,
    }

    config_upper = config_str.upper().strip()
    if config_upper not in config_map:
        logger.warning(f"Unknown terminal config '{config_str}', defaulting to DEFAULT. "
                      f"Valid options: DEFAULT, RSE, DIFF, NRSE, PSEUDO_DIFF")
        return TerminalConfiguration.DEFAULT

    return config_map[config_upper]


def get_cjc_source(config_str: str):
    """
    Map CJC source configuration string to nidaqmx CJCSource constant.
    """
    if not NIDAQMX_AVAILABLE:
        return None

    from nidaqmx.constants import CJCSource

    config_map = {
        'INTERNAL': CJCSource.BUILT_IN,
        'BUILT_IN': CJCSource.BUILT_IN,
        'CONSTANT': CJCSource.CONSTANT_USER_VALUE,
        'CONST_VAL': CJCSource.CONSTANT_USER_VALUE,
        'CHANNEL': CJCSource.SCANNABLE_CHANNEL,
        'SCANNABLE_CHANNEL': CJCSource.SCANNABLE_CHANNEL,
    }

    config_upper = config_str.upper().strip()
    if config_upper not in config_map:
        logger.warning(f"Unknown CJC source '{config_str}', defaulting to BUILT_IN")
        return CJCSource.BUILT_IN

    return config_map[config_upper]


@dataclass
class TaskGroup:
    """Groups channels by module for efficient reading"""
    task: Any  # nidaqmx.Task
    channel_names: List[str]
    module_name: str
    channel_type: ChannelType  # Primary type (for single-type tasks)
    is_continuous: bool = False  # Whether using continuous acquisition
    reader: Any = None  # Stream reader for continuous acquisition
    channel_types: Dict[str, Any] = field(default_factory=dict)  # Per-channel types for mixed tasks


class HardwareReader:
    """
    Reads from real NI hardware using nidaqmx with CONTINUOUS BUFFERED ACQUISITION.

    Instead of on-demand reads (which block on ADC settling), this uses:
    - Hardware-timed continuous sampling at SAMPLE_RATE_HZ
    - Background thread reads from hardware FIFO buffer
    - read_all() returns latest cached values INSTANTLY

    This matches LabVIEW's recommended DAQmx architecture.
    """

    def __init__(self, config: NISystemConfig, sample_rate: float = SAMPLE_RATE_HZ,
                 initial_output_values: Optional[Dict[str, float]] = None):
        if not NIDAQMX_AVAILABLE:
            raise RuntimeError("nidaqmx library not available - cannot use HardwareReader")

        self.config = config
        self.sample_rate = sample_rate
        self.tasks: Dict[str, TaskGroup] = {}  # task_name -> TaskGroup
        self.output_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task
        self.counter_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task
        self._counter_rollover: Dict[str, Dict] = {}  # rollover tracking for edge count mode
        self._momentary_timers: Dict[str, threading.Timer] = {}  # Relay momentary pulse timers

        # Output state cache (for read-back) - preserve values across reinit
        self.output_values: Dict[str, float] = initial_output_values.copy() if initial_output_values else {}

        # CONTINUOUS ACQUISITION: Latest values from background thread
        self.latest_values: Dict[str, float] = {}
        self.value_timestamps: Dict[str, float] = {}  # When each value was last updated

        # Background reader thread control
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._error_count = 0
        self._max_errors = 10  # Stop after this many consecutive errors
        self._reader_died = False  # Flag set when reader exits due to errors
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3
        self._error_callback: Optional[callable] = None  # Callback when reader dies

        # Software watchdog for output safety
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_interval_s: float = 2.0  # Check health every 2 seconds
        self._watchdog_triggered = False

        # Lock for thread safety
        self.lock = threading.Lock()

        # Initialize tasks
        self._create_tasks()

        # Start continuous acquisition
        self._start_continuous_acquisition()

        # Start software watchdog (monitors reader health, sets outputs safe if it dies)
        self._start_watchdog()

    def _is_crio_channel(self, physical_channel: str) -> bool:
        """
        Check if a channel is a cRIO channel (remote, not local NI-DAQmx).

        cRIO channels have physical_channel starting directly with "Mod" (e.g., "Mod4/port0/line0")
        Local channels have a chassis prefix (e.g., "cDAQ-9189-DHWSIMMod1/ai0")
        """
        import re
        # cRIO: starts with "Mod" followed by digit (e.g., "Mod4/port0/line0")
        # Local: starts with chassis name like "cDAQ-", "cDAQ9189-", etc.
        return bool(re.match(r'^Mod\d', physical_channel))

    def _get_physical_channel_path(self, channel: ChannelConfig) -> str:
        """
        Build the full physical channel path from module and channel config.
        E.g., "cDAQ1Mod1/ai0" from module in slot 1 with physical_channel "ai0"

        If physical_channel already contains '/' (full path), return it directly.
        This supports both:
        - Legacy: module reference + short physical_channel (e.g., "ai0")
        - New: full physical_channel path (e.g., "cDAQ-9189-DHWSIMMod1/ai0")
        """
        # Check if physical_channel is already a full path (contains '/')
        if '/' in channel.physical_channel:
            logger.debug(f"Using direct physical channel path: {channel.physical_channel}")
            return channel.physical_channel

        # Legacy mode: build path from module/chassis config
        module = self.config.modules.get(channel.module)
        if not module:
            raise ValueError(f"Module {channel.module} not found for channel {channel.name}")

        chassis = self.config.chassis.get(module.chassis)
        if not chassis:
            raise ValueError(f"Chassis {module.chassis} not found for module {module.name}")

        # Build the device name based on chassis type and slot
        # For cDAQ: "cDAQ1Mod1", "cDAQ1Mod2", etc.
        # The actual device name depends on how NI MAX has it configured
        # We'll use a pattern that matches typical NI naming

        # Try to use chassis serial or name to find the device
        # In practice, you might need to enumerate devices and match
        device_prefix = self._get_device_prefix(chassis, module)

        return f"{device_prefix}/{channel.physical_channel}"

    def _get_device_prefix(self, chassis, module: ModuleConfig) -> str:
        """
        Get the device prefix for a module.
        For cDAQ systems: "cDAQ1Mod1", "cDAQ2Mod3", etc.

        Priority:
        1. Use chassis.device_name if explicitly configured
        2. Try to match by chassis serial number
        3. Auto-discover by slot number
        4. Fallback to default naming convention
        """
        # Priority 1: Explicit device_name in chassis config
        if chassis.device_name:
            logger.info(f"Using configured device name: {chassis.device_name} for slot {module.slot}")
            return f"{chassis.device_name}Mod{module.slot}"

        system = nidaqmx.system.System.local()

        # Priority 2: Try to match by serial number if provided
        if chassis.serial:
            for device in system.devices:
                device_name = device.name
                try:
                    # Check if device serial matches
                    if hasattr(device, 'serial_num') and str(device.serial_num) == chassis.serial:
                        if 'Mod' in device_name:
                            base_name = device_name[:device_name.index('Mod')]
                            return f"{base_name}Mod{module.slot}"
                except Exception:
                    continue

        # Priority 3: Auto-discover by slot number
        for device in system.devices:
            device_name = device.name
            # Check if this looks like a cDAQ module
            if 'cDAQ' in device_name and 'Mod' in device_name:
                # Extract slot number from device name (e.g., "cDAQ1Mod3" -> slot 3)
                try:
                    mod_idx = device_name.index('Mod')
                    slot_str = device_name[mod_idx + 3:]
                    slot_num = int(''.join(c for c in slot_str if c.isdigit()))
                    if slot_num == module.slot:
                        logger.info(f"Auto-discovered device: {device_name} for slot {module.slot}")
                        return device_name
                except (ValueError, IndexError):
                    continue

        # Priority 4: Fallback to default naming convention
        fallback = f"cDAQ1Mod{module.slot}"
        logger.warning(f"Using fallback device name: {fallback} - configure 'device_name' in chassis config for reliability")
        return fallback

    def _extract_module_from_path(self, physical_channel: str) -> str:
        """
        Extract module/device name from a full physical channel path.
        E.g., "cDAQ-9189-DHWSIMMod1/ai0" -> "cDAQ-9189-DHWSIMMod1"
        """
        if '/' in physical_channel:
            return physical_channel.split('/')[0]
        return ""

    def _create_tasks(self):
        """
        Create nidaqmx tasks for all input channels.

        IMPORTANT: NI-DAQmx only allows ONE continuous acquisition task per module.
        Therefore, we group ALL analog input channels on the same module into a
        SINGLE task, regardless of channel type (voltage, current, thermocouple, etc.).

        This is valid because NI-DAQmx allows mixing different add_ai_*_chan methods
        in the same task.
        """

        # Group channels by module
        # For channels with direct paths (containing '/'), extract module from path
        module_channels: Dict[str, List[ChannelConfig]] = {}
        direct_path_modules: set = set()  # Track modules that come from direct paths

        # Analog input types that can share a continuous task
        ANALOG_INPUT_TYPES = {
            ChannelType.THERMOCOUPLE, ChannelType.VOLTAGE_INPUT, ChannelType.CURRENT_INPUT,
            ChannelType.RTD,
            ChannelType.STRAIN, ChannelType.STRAIN_INPUT, ChannelType.BRIDGE_INPUT,
            ChannelType.IEPE, ChannelType.IEPE_INPUT,
            ChannelType.RESISTANCE, ChannelType.RESISTANCE_INPUT,
        }

        for name, channel in self.config.channels.items():
            # Skip remote channels (cRIO) - they are not read via local NI-DAQmx
            # Remote channels receive values via MQTT from the cRIO node service
            # Check both source_type attribute AND physical_channel format
            if getattr(channel, 'source_type', 'local') == 'crio':
                logger.debug(f"Skipping remote cRIO channel: {name} (source_node: {getattr(channel, 'source_node_id', 'unknown')})")
                continue

            # Also skip channels where physical_channel starts with "Mod" (cRIO format)
            # Local channels have chassis prefix like "cDAQ-9189-DHWSIMMod1/ai0"
            if self._is_crio_channel(channel.physical_channel):
                logger.debug(f"Skipping cRIO channel {name}: physical_channel {channel.physical_channel} is remote")
                continue

            # Determine the module key for grouping
            if '/' in channel.physical_channel:
                # Direct path - extract module from physical_channel
                module_key = self._extract_module_from_path(channel.physical_channel)
                direct_path_modules.add(module_key)
            else:
                # Legacy - use configured module reference
                module_key = channel.module

            if module_key not in module_channels:
                module_channels[module_key] = []
            module_channels[module_key].append(channel)

        # Create tasks for each module
        for module_name, channels in module_channels.items():
            # For direct-path modules, skip the module config check
            if module_name not in direct_path_modules:
                module = self.config.modules.get(module_name)
                if not module or not module.enabled:
                    logger.debug(f"Skipping module {module_name} - not found or not enabled")
                    continue

            # Separate analog inputs (which share a task) from other types
            analog_channels = [c for c in channels if c.channel_type in ANALOG_INPUT_TYPES]
            digital_in_channels = [c for c in channels if c.channel_type == ChannelType.DIGITAL_INPUT]
            digital_out_channels = [c for c in channels if c.channel_type == ChannelType.DIGITAL_OUTPUT]
            voltage_out_channels = [c for c in channels if c.channel_type == ChannelType.VOLTAGE_OUTPUT]
            current_out_channels = [c for c in channels if c.channel_type == ChannelType.CURRENT_OUTPUT]
            counter_channels = [c for c in channels if c.channel_type in (
                ChannelType.COUNTER, ChannelType.COUNTER_INPUT, ChannelType.FREQUENCY_INPUT)]
            pulse_out_channels = [c for c in channels if c.channel_type in (
                ChannelType.PULSE_OUTPUT, ChannelType.COUNTER_OUTPUT)]

            # Create ONE continuous task for ALL analog inputs on this module
            if analog_channels:
                try:
                    self._create_combined_analog_task(module_name, analog_channels)
                except Exception as e:
                    logger.error(f"Failed to create analog task for {module_name}: {e}")

            # Digital inputs (not continuous, separate task OK)
            if digital_in_channels:
                try:
                    task_name = f"{module_name}_digital_input"
                    self._create_digital_input_task(task_name, module_name, digital_in_channels)
                except Exception as e:
                    logger.error(f"Failed to create digital input task for {module_name}: {e}")

            # Digital outputs (individual tasks per channel)
            if digital_out_channels:
                self._create_digital_output_tasks(digital_out_channels)

            # Voltage outputs (individual tasks per channel)
            if voltage_out_channels:
                self._create_voltage_output_tasks(voltage_out_channels)

            # Current outputs (individual tasks per channel)
            if current_out_channels:
                self._create_current_output_tasks(current_out_channels)

            # Counters (individual tasks per channel)
            if counter_channels:
                self._create_counter_tasks(counter_channels)

            # Pulse/counter outputs (individual tasks per channel)
            if pulse_out_channels:
                self._create_pulse_output_tasks(pulse_out_channels)

    def _create_combined_analog_task(self, module_name: str, channels: List[ChannelConfig]):
        """
        Create a SINGLE continuous acquisition task for ALL analog input channels on a module.

        NI-DAQmx allows mixing different channel types (voltage, current, thermocouple, RTD, etc.)
        in the same task. This is essential because NI-DAQmx only allows ONE continuous
        acquisition task per module.
        """
        from nidaqmx.constants import (
            CurrentShuntResistorLocation, RTDType, ResistanceConfiguration,
            ExcitationSource, StrainGageBridgeType, BridgeConfiguration, Coupling, CJCSource
        )

        task_name = f"{module_name}_analog"
        task = nidaqmx.Task(task_name)
        channel_names = []
        channel_types: Dict[str, ChannelType] = {}  # Track type per channel for post-processing

        # CRITICAL: Sort channels by physical index before adding to task
        # DAQmx returns values in the order channels are added
        sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

        try:
            for channel in sorted_channels:
                phys_chan = self._get_physical_channel_path(channel)

                if channel.channel_type == ChannelType.THERMOCOUPLE:
                    # Thermocouple
                    tc_type = NI_TCType.K  # Default
                    if channel.thermocouple_type:
                        tc_type_str = TC_TYPE_MAP.get(channel.thermocouple_type, 'K')
                        tc_type = getattr(NI_TCType, tc_type_str, NI_TCType.K)
                    cjc = get_cjc_source(channel.cjc_source)
                    cjc_val = getattr(channel, 'cjc_value', 25.0)

                    ai_chan = task.ai_channels.add_ai_thrmcpl_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        thermocouple_type=tc_type,
                        cjc_source=cjc,
                        cjc_val=cjc_val
                    )

                    # Enable open thermocouple detection
                    # When TC is open/broken, NI-DAQmx will return a very large value (~1e308)
                    # which our validation layer will detect and convert to NaN
                    try:
                        ai_chan.ai_open_thrmcpl_detect_enable = True
                        logger.info(f"Added thermocouple: {channel.name} -> {phys_chan} (cjc={channel.cjc_source}, open TC detection enabled)")
                    except Exception as e:
                        logger.warning(f"Could not enable open TC detection for {channel.name}: {e}")
                        logger.info(f"Added thermocouple: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.VOLTAGE_INPUT:
                    # Voltage input
                    v_range = channel.voltage_range or 10.0
                    term_config = get_terminal_config(channel.terminal_config)

                    task.ai_channels.add_ai_voltage_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        terminal_config=term_config,
                        min_val=-v_range,
                        max_val=v_range
                    )
                    logger.info(f"Added voltage input: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.CURRENT_INPUT:
                    # Current input (4-20mA)
                    max_current = (channel.current_range_ma or 20.0) / 1000.0  # Convert to Amps
                    term_config = get_terminal_config(channel.terminal_config)

                    task.ai_channels.add_ai_current_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        terminal_config=term_config,
                        min_val=0.0,
                        max_val=max_current,
                        shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
                    )
                    logger.info(f"Added current input: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.RTD:
                    # RTD
                    rtd_type_map = {
                        'Pt100': RTDType.PT_3750, 'PT100': RTDType.PT_3750,
                        'Pt385': RTDType.PT_3851, 'PT385': RTDType.PT_3851,
                        'Pt3851': RTDType.PT_3851, 'PT3851': RTDType.PT_3851,
                        'Pt3916': RTDType.PT_3916, 'PT3916': RTDType.PT_3916,
                    }
                    wiring_map = {
                        '2-wire': ResistanceConfiguration.TWO_WIRE,
                        '2Wire': ResistanceConfiguration.TWO_WIRE,
                        '3-wire': ResistanceConfiguration.THREE_WIRE,
                        '3Wire': ResistanceConfiguration.THREE_WIRE,
                        '4-wire': ResistanceConfiguration.FOUR_WIRE,
                        '4Wire': ResistanceConfiguration.FOUR_WIRE,
                    }
                    rtd_type = rtd_type_map.get(channel.rtd_type, RTDType.PT_3851)
                    wiring = wiring_map.get(channel.rtd_wiring,
                                           ResistanceConfiguration.FOUR_WIRE)

                    task.ai_channels.add_ai_rtd_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        rtd_type=rtd_type,
                        resistance_config=wiring,
                        current_excit_source=ExcitationSource.INTERNAL,
                        current_excit_val=channel.rtd_current or 0.001,
                        r_0=channel.rtd_resistance or 100.0
                    )
                    logger.info(f"Added RTD: {channel.name} -> {phys_chan}")

                elif channel.channel_type in (ChannelType.STRAIN, ChannelType.STRAIN_INPUT, ChannelType.BRIDGE_INPUT):
                    # Strain gauge
                    bridge_map = {
                        'full-bridge': BridgeConfiguration.FULL_BRIDGE,
                        'half-bridge': BridgeConfiguration.HALF_BRIDGE,
                        'quarter-bridge': BridgeConfiguration.QUARTER_BRIDGE,
                    }
                    bridge_config = bridge_map.get(channel.strain_config, BridgeConfiguration.FULL_BRIDGE)

                    task.ai_channels.add_ai_strain_gage_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        strain_config=bridge_config,
                        voltage_excit_source=ExcitationSource.INTERNAL,
                        voltage_excit_val=channel.strain_excitation_voltage or 2.5,
                        gage_factor=channel.strain_gage_factor or 2.0,
                        nominal_gage_resistance=channel.strain_resistance or 350.0
                    )
                    logger.info(f"Added strain: {channel.name} -> {phys_chan}")

                elif channel.channel_type in (ChannelType.IEPE, ChannelType.IEPE_INPUT):
                    # IEPE accelerometer
                    coupling = Coupling.AC if (channel.iepe_coupling or 'AC').upper() == 'AC' else Coupling.DC

                    task.ai_channels.add_ai_accel_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        sensitivity=channel.iepe_sensitivity or 100.0,
                        current_excit_source=ExcitationSource.INTERNAL,
                        current_excit_val=channel.iepe_current or 0.004
                    )
                    task.ai_channels[channel.name].ai_coupling = coupling
                    logger.info(f"Added IEPE: {channel.name} -> {phys_chan}")

                elif channel.channel_type in (ChannelType.RESISTANCE, ChannelType.RESISTANCE_INPUT):
                    # Resistance
                    wiring_map = {
                        '2-wire': ResistanceConfiguration.TWO_WIRE,
                        '4-wire': ResistanceConfiguration.FOUR_WIRE,
                    }
                    wiring = wiring_map.get(channel.resistance_wiring, ResistanceConfiguration.FOUR_WIRE)

                    task.ai_channels.add_ai_resistance_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        resistance_config=wiring,
                        current_excit_source=ExcitationSource.INTERNAL,
                        current_excit_val=0.001,
                        min_val=0.0,
                        max_val=channel.resistance_range or 10000.0
                    )
                    logger.info(f"Added resistance: {channel.name} -> {phys_chan}")

                channel_names.append(channel.name)
                channel_types[channel.name] = channel.channel_type

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            # Store task with channel type info for the reader thread
            task_group = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.VOLTAGE_INPUT,  # Generic - we track per-channel in channel_types
                is_continuous=True,
                reader=reader,
                channel_types=channel_types  # Per-channel types for post-processing (e.g., current mA conversion)
            )

            self.tasks[task_name] = task_group
            logger.info(f"Created combined analog task {task_name} with {len(channel_names)} channels at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_thermocouple_task(self, task_name: str, module_name: str,
                                   channels: List[ChannelConfig]):
        """Create thermocouple input task with CONTINUOUS acquisition"""
        task = nidaqmx.Task(task_name)
        channel_names = []

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)

                # Map thermocouple type
                tc_type = NI_TCType.K  # Default
                if channel.thermocouple_type:
                    tc_type_str = TC_TYPE_MAP.get(channel.thermocouple_type, 'K')
                    tc_type = getattr(NI_TCType, tc_type_str, NI_TCType.K)

                # Map CJC source from config
                cjc = get_cjc_source(channel.cjc_source)
                cjc_val = getattr(channel, 'cjc_value', 25.0)

                ai_chan = task.ai_channels.add_ai_thrmcpl_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    thermocouple_type=tc_type,
                    cjc_source=cjc,
                    cjc_val=cjc_val
                )
                channel_names.append(channel.name)

                # Enable open thermocouple detection
                try:
                    ai_chan.ai_open_thrmcpl_detect_enable = True
                    logger.info(f"Added thermocouple channel: {channel.name} -> {phys_chan} "
                               f"(type={tc_type_str}, cjc={channel.cjc_source}, open TC detection enabled)")
                except Exception as e:
                    logger.warning(f"Could not enable open TC detection for {channel.name}: {e}")
                    logger.info(f"Added thermocouple channel: {channel.name} -> {phys_chan} "
                               f"(type={tc_type_str}, cjc={channel.cjc_source})")

            # Configure CONTINUOUS acquisition with hardware timing
            # Note: TC modules may have lower max sample rates (check NI specs)
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.THERMOCOUPLE,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_voltage_task(self, task_name: str, module_name: str,
                              channels: List[ChannelConfig]):
        """Create voltage input task with CONTINUOUS acquisition"""
        task = nidaqmx.Task(task_name)
        channel_names = []

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                v_range = channel.voltage_range or 10.0
                term_config = get_terminal_config(channel.terminal_config)

                task.ai_channels.add_ai_voltage_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    terminal_config=term_config,
                    min_val=-v_range,
                    max_val=v_range
                )
                channel_names.append(channel.name)
                logger.info(f"Added voltage channel: {channel.name} -> {phys_chan} (terminal={channel.terminal_config})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.VOLTAGE_INPUT,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_current_task(self, task_name: str, module_name: str,
                              channels: List[ChannelConfig]):
        """Create current input task (4-20mA) with CONTINUOUS acquisition"""
        from nidaqmx.constants import CurrentShuntResistorLocation

        task = nidaqmx.Task(task_name)
        channel_names = []

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                # NI current modules typically read in Amps, we want mA
                # Most 4-20mA modules have 0-20mA or 0-25mA range
                max_current = (channel.current_range_ma or 20.0) / 1000.0  # Convert to Amps
                term_config = get_terminal_config(channel.terminal_config)

                # NI-9203 and similar modules have internal shunt resistors
                task.ai_channels.add_ai_current_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    terminal_config=term_config,
                    min_val=0.0,
                    max_val=max_current,
                    shunt_resistor_loc=CurrentShuntResistorLocation.INTERNAL
                )
                channel_names.append(channel.name)
                logger.info(f"Added current channel: {channel.name} -> {phys_chan} "
                           f"(terminal={channel.terminal_config}, range=0-{channel.current_range_ma}mA)")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.CURRENT_INPUT,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_rtd_task(self, task_name: str, module_name: str,
                          channels: List[ChannelConfig]):
        """Create RTD (Resistance Temperature Detector) input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import (
            RTDType, ResistanceConfiguration, ExcitationSource
        )

        task = nidaqmx.Task(task_name)
        channel_names = []

        # Map RTD type string to nidaqmx constant
        rtd_type_map = {
            'Pt100': RTDType.PT_3750,
            'PT100': RTDType.PT_3750,
            'Pt385': RTDType.PT_3851,
            'PT385': RTDType.PT_3851,
            'Pt3916': RTDType.PT_3916,
            'PT3916': RTDType.PT_3916,
            'Pt500': RTDType.PT_3750,  # Use same as Pt100
            'PT500': RTDType.PT_3750,
            'Pt1000': RTDType.PT_3750,
            'PT1000': RTDType.PT_3750,
            'custom': RTDType.CUSTOM,
        }

        # Map wiring config
        wiring_map = {
            '2-wire': ResistanceConfiguration.TWO_WIRE,
            '3-wire': ResistanceConfiguration.THREE_WIRE,
            '4-wire': ResistanceConfiguration.FOUR_WIRE,
        }

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                rtd_type = rtd_type_map.get(channel.rtd_type, RTDType.PT_3750)
                wiring = wiring_map.get(channel.rtd_wiring, ResistanceConfiguration.FOUR_WIRE)

                task.ai_channels.add_ai_rtd_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    rtd_type=rtd_type,
                    resistance_config=wiring,
                    current_excit_source=ExcitationSource.INTERNAL,
                    current_excit_val=channel.rtd_current,
                    r_0=channel.rtd_resistance  # Note: r_0 not r0 in newer nidaqmx
                )
                channel_names.append(channel.name)
                logger.info(f"Added RTD channel: {channel.name} -> {phys_chan} "
                           f"(type={channel.rtd_type}, wiring={channel.rtd_wiring}, R0={channel.rtd_resistance})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.RTD,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_strain_task(self, task_name: str, module_name: str,
                             channels: List[ChannelConfig]):
        """Create strain gauge input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import (
            StrainGageBridgeType, BridgeConfiguration, ExcitationSource
        )

        task = nidaqmx.Task(task_name)
        channel_names = []

        # Map bridge config
        bridge_map = {
            'full-bridge': BridgeConfiguration.FULL_BRIDGE,
            'half-bridge': BridgeConfiguration.HALF_BRIDGE,
            'quarter-bridge': BridgeConfiguration.QUARTER_BRIDGE,
        }

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                bridge_config = bridge_map.get(channel.strain_config, BridgeConfiguration.FULL_BRIDGE)

                task.ai_channels.add_ai_strain_gage_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    strain_config=bridge_config,
                    voltage_excit_source=ExcitationSource.INTERNAL,
                    voltage_excit_val=channel.strain_excitation_voltage,
                    gage_factor=channel.strain_gage_factor,
                    nominal_gage_resistance=channel.strain_resistance
                )
                channel_names.append(channel.name)
                logger.info(f"Added strain channel: {channel.name} -> {phys_chan} "
                           f"(config={channel.strain_config}, GF={channel.strain_gage_factor})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.STRAIN,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_iepe_task(self, task_name: str, module_name: str,
                           channels: List[ChannelConfig]):
        """Create IEPE (accelerometer/microphone) input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import ExcitationSource, Coupling

        task = nidaqmx.Task(task_name)
        channel_names = []

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                coupling = Coupling.AC if channel.iepe_coupling.upper() == 'AC' else Coupling.DC

                # Add accelerometer channel with IEPE excitation
                task.ai_channels.add_ai_accel_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    sensitivity=channel.iepe_sensitivity,
                    current_excit_source=ExcitationSource.INTERNAL,
                    current_excit_val=channel.iepe_current
                )
                # Set coupling
                task.ai_channels[channel.name].ai_coupling = coupling

                channel_names.append(channel.name)
                logger.info(f"Added IEPE channel: {channel.name} -> {phys_chan} "
                           f"(sensitivity={channel.iepe_sensitivity} mV/g, coupling={channel.iepe_coupling})")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.IEPE,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_resistance_task(self, task_name: str, module_name: str,
                                  channels: List[ChannelConfig]):
        """Create resistance measurement input task with CONTINUOUS acquisition"""
        from nidaqmx.constants import ResistanceConfiguration, ExcitationSource

        task = nidaqmx.Task(task_name)
        channel_names = []

        wiring_map = {
            '2-wire': ResistanceConfiguration.TWO_WIRE,
            '4-wire': ResistanceConfiguration.FOUR_WIRE,
        }

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)
                wiring = wiring_map.get(channel.resistance_wiring, ResistanceConfiguration.FOUR_WIRE)

                task.ai_channels.add_ai_resistance_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    resistance_config=wiring,
                    current_excit_source=ExcitationSource.INTERNAL,
                    current_excit_val=0.001,  # 1mA typical
                    min_val=0.0,
                    max_val=channel.resistance_range
                )
                channel_names.append(channel.name)
                logger.info(f"Added resistance channel: {channel.name} -> {phys_chan} "
                           f"(wiring={channel.resistance_wiring}, range=0-{channel.resistance_range}Ω)")

            # Configure CONTINUOUS acquisition with hardware timing
            task.timing.cfg_samp_clk_timing(
                rate=self.sample_rate,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=BUFFER_SIZE
            )

            # Create stream reader for efficient buffer reading
            reader = AnalogMultiChannelReader(task.in_stream)

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.RESISTANCE,
                is_continuous=True,
                reader=reader
            )
            logger.info(f"Configured {task_name} for continuous acquisition at {self.sample_rate} Hz")

        except Exception as e:
            task.close()
            raise

    def _create_digital_input_task(self, task_name: str, module_name: str,
                                    channels: List[ChannelConfig]):
        """Create digital input task"""
        task = nidaqmx.Task(task_name)
        channel_names = []

        # CRITICAL: Sort channels by physical index before adding to task
        sorted_channels = sorted(channels, key=lambda ch: _get_physical_channel_index(ch.physical_channel))

        try:
            for channel in sorted_channels:
                phys_chan = self._get_physical_channel_path(channel)

                task.di_channels.add_di_chan(
                    phys_chan,
                    name_to_assign_to_lines=channel.name  # Note: lines not channel in nidaqmx
                )
                channel_names.append(channel.name)
                logger.info(f"Added digital input channel: {channel.name} -> {phys_chan}")

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.DIGITAL_INPUT
            )
        except Exception as e:
            task.close()
            raise

    def _create_digital_output_tasks(self, channels: List[ChannelConfig]):
        """Create individual digital output tasks (one per channel for independent control)"""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"DO_{channel.name}")

                task.do_channels.add_do_chan(
                    phys_chan,
                    name_to_assign_to_lines=channel.name  # Note: lines not channel in nidaqmx
                )

                self.output_tasks[channel.name] = task

                # Preserve existing output state across reinitializations
                # Only use default_state if this is truly the first initialization
                if channel.name in self.output_values:
                    # Restore previous state
                    preserved_value = bool(self.output_values[channel.name])
                    task.write(preserved_value)
                    logger.info(f"Added digital output channel: {channel.name} -> {phys_chan} (preserved state: {preserved_value})")
                else:
                    # First time - use default state
                    self.output_values[channel.name] = 1.0 if channel.default_state else 0.0
                    task.write(channel.default_state)
                    logger.info(f"Added digital output channel: {channel.name} -> {phys_chan} (default: {channel.default_state})")

            except Exception as e:
                logger.error(f"Failed to create DO task for {channel.name}: {e}")

    def _create_voltage_output_tasks(self, channels: List[ChannelConfig]):
        """Create individual voltage output tasks (0-10V, ±10V modules like NI 9263, NI 9264)"""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"VO_{channel.name}")

                v_range = channel.voltage_range or 10.0
                task.ao_channels.add_ao_voltage_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    min_val=0.0,  # Most AO modules are 0-10V
                    max_val=v_range
                )

                self.output_tasks[channel.name] = task

                # Preserve existing output state across reinitializations
                if channel.name in self.output_values:
                    # Restore previous state
                    preserved_value = self.output_values[channel.name]
                    task.write(preserved_value)
                    logger.info(f"Added voltage output channel: {channel.name} -> {phys_chan} (preserved value: {preserved_value})")
                else:
                    # First time - use default value
                    self.output_values[channel.name] = channel.default_value or 0.0
                    task.write(channel.default_value or 0.0)
                    logger.info(f"Added voltage output channel: {channel.name} -> {phys_chan} (default: {channel.default_value or 0.0})")

            except Exception as e:
                logger.error(f"Failed to create voltage output task for {channel.name}: {e}")

    def _create_current_output_tasks(self, channels: List[ChannelConfig]):
        """Create individual current output tasks (0-20mA, 4-20mA modules like NI 9265, NI 9266)"""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"CO_{channel.name}")

                # Current outputs are typically 0-20mA or 0-24mA
                max_current = (channel.current_range_ma or 20.0) / 1000.0  # Convert to Amps

                task.ao_channels.add_ao_current_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    min_val=0.0,
                    max_val=max_current
                )

                self.output_tasks[channel.name] = task

                # Preserve existing output state across reinitializations
                if channel.name in self.output_values:
                    # Restore previous state (stored in mA)
                    preserved_value = self.output_values[channel.name]
                    task.write(preserved_value / 1000.0)  # Convert mA to Amps for hardware
                    logger.info(f"Added current output channel: {channel.name} -> {phys_chan} (preserved value: {preserved_value}mA)")
                else:
                    # First time - use default value
                    default_ma = channel.default_value or 0.0
                    self.output_values[channel.name] = default_ma
                    task.write(default_ma / 1000.0)  # Convert mA to Amps for hardware
                    logger.info(f"Added current output channel: {channel.name} -> {phys_chan} (default: {default_ma}mA)")

            except Exception as e:
                logger.error(f"Failed to create current output task for {channel.name}: {e}")

    def _create_counter_tasks(self, channels: List[ChannelConfig]):
        """Create counter/frequency input tasks"""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"CTR_{channel.name}")

                # Use configured min/max frequency from channel config
                min_freq = channel.counter_min_freq  # Default 0.1 Hz
                max_freq = channel.counter_max_freq  # Default 1000.0 Hz

                # Convert frequency to period for period mode
                min_period = 1.0 / max_freq if max_freq > 0 else 0.001
                max_period = 1.0 / min_freq if min_freq > 0 else 10.0

                edge = Edge.RISING if channel.counter_edge == "rising" else Edge.FALLING

                if channel.counter_mode == "frequency":
                    # Frequency measurement - try default method, fall back to DynAvg
                    try:
                        task.ci_channels.add_ci_freq_chan(
                            phys_chan,
                            name_to_assign_to_channel=channel.name,
                            min_val=min_freq,
                            max_val=max_freq,
                            units=FrequencyUnits.HZ,
                            edge=edge
                        )
                    except Exception:
                        task.close()
                        task = nidaqmx.Task(f"CTR_{channel.name}")
                        task.ci_channels.add_ci_freq_chan(
                            phys_chan,
                            name_to_assign_to_channel=channel.name,
                            min_val=min_freq,
                            max_val=max_freq,
                            units=FrequencyUnits.HZ,
                            edge=edge,
                            meas_method=CounterFrequencyMethod.DYNAMIC_AVERAGING
                        )
                        logger.info(f"Counter {channel.name}: using DynAvg measurement method")
                elif channel.counter_mode == "count":
                    # Edge counting
                    task.ci_channels.add_ci_count_edges_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        edge=edge,
                        initial_count=0,
                        count_direction=CountDirection.COUNT_UP
                    )
                elif channel.counter_mode == "period":
                    # Period measurement
                    task.ci_channels.add_ci_period_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        min_val=min_period,
                        max_val=max_period,
                        edge=edge
                    )

                self.counter_tasks[channel.name] = task
                logger.info(f"Added counter channel: {channel.name} -> {phys_chan} "
                           f"(mode={channel.counter_mode}, freq={min_freq}-{max_freq}Hz)")

            except Exception as e:
                logger.error(f"Failed to create counter task for {channel.name}: {e}")

    def _create_pulse_output_tasks(self, channels: List[ChannelConfig]):
        """Create pulse/counter output tasks (one per channel)."""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"CTR_OUT_{channel.name}")

                idle_state = Level.LOW
                if getattr(channel, 'pulse_idle_state', 'LOW') == 'HIGH':
                    idle_state = Level.HIGH

                freq = getattr(channel, 'pulse_frequency', 1000.0)
                duty = getattr(channel, 'pulse_duty_cycle', 50.0) / 100.0  # 0-100% to 0.0-1.0

                task.co_channels.add_co_pulse_chan_freq(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    freq=freq,
                    duty_cycle=duty,
                    idle_state=idle_state
                )

                # Configure for continuous generation
                task.timing.cfg_implicit_timing(
                    sample_mode=AcquisitionType.CONTINUOUS
                )

                task.start()
                self.output_tasks[channel.name] = task
                self.output_values[channel.name] = freq
                logger.info(f"Created pulse output: {channel.name} -> {phys_chan} "
                           f"(freq={freq}Hz, duty={duty*100}%, idle={channel.pulse_idle_state})")

            except Exception as e:
                logger.error(f"Failed to create pulse output task for {channel.name}: {e}")

    # =========================================================================
    # CONTINUOUS ACQUISITION MANAGEMENT
    # =========================================================================

    def _start_continuous_acquisition(self):
        """Start all continuous acquisition tasks and the background reader thread"""
        logger.info("Starting continuous acquisition...")

        # Start all continuous tasks
        for task_name, task_group in self.tasks.items():
            if task_group.is_continuous:
                try:
                    task_group.task.start()
                    logger.info(f"Started continuous task: {task_name}")
                except Exception as e:
                    logger.error(f"Failed to start task {task_name}: {e}")

        # Start background reader thread
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_thread_func,
            name="HardwareReader-Continuous",
            daemon=True
        )
        self._reader_thread.start()
        logger.info("Continuous acquisition started")

    def _stop_continuous_acquisition(self):
        """Stop the background reader thread and all continuous tasks"""
        logger.info("Stopping continuous acquisition...")
        self._running = False

        # Wait for reader thread to finish
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

        # Stop all continuous tasks
        for task_name, task_group in self.tasks.items():
            if task_group.is_continuous:
                try:
                    task_group.task.stop()
                    logger.info(f"Stopped continuous task: {task_name}")
                except Exception as e:
                    logger.error(f"Failed to stop task {task_name}: {e}")

        logger.info("Continuous acquisition stopped")

    # =========================================================================
    # SOFTWARE WATCHDOG (monitors reader health, forces outputs safe)
    # =========================================================================

    def _start_watchdog(self):
        """Start independent watchdog thread that monitors reader health."""
        if not self.output_tasks:
            logger.info("No output tasks configured - watchdog not started")
            return

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="HardwareReader-Watchdog",
            daemon=True
        )
        self._watchdog_thread.start()
        logger.info(f"Hardware watchdog started (interval={self._watchdog_interval_s}s, "
                    f"monitoring {len(self.output_tasks)} outputs)")

    def _watchdog_loop(self):
        """Watchdog loop - runs independently of reader thread.

        Checks reader health every interval. If the reader thread dies
        or becomes unhealthy, forces all outputs to safe state (0/OFF).
        """
        while self._running:
            time.sleep(self._watchdog_interval_s)

            if not self._running:
                break

            # Check reader thread health
            if not self.is_healthy() and not self._watchdog_triggered:
                logger.critical(
                    "[WATCHDOG] Reader thread unhealthy! "
                    f"running={self._running}, died={self._reader_died}, "
                    f"thread_alive={self._reader_thread.is_alive() if self._reader_thread else False}"
                )
                self._set_all_outputs_safe("watchdog_trip")
                self._watchdog_triggered = True

                # Notify via error callback
                if self._error_callback:
                    try:
                        self._error_callback("watchdog_trip", {
                            "message": "Watchdog set outputs to safe state",
                            "output_count": len(self.output_tasks)
                        })
                    except Exception as e:
                        logger.warning(f"Watchdog error callback failed: {e}")

        logger.info("Watchdog thread stopped")

    def _set_all_outputs_safe(self, reason: str = "unknown"):
        """Set all output channels to safe state (0/OFF).

        Called by watchdog when reader thread dies. Writes directly to
        hardware tasks to ensure outputs are zeroed even if the main
        service loop is stalled.
        """
        logger.critical(f"[SAFE STATE] Setting all outputs to safe state - reason: {reason}")

        with self.lock:
            for name, task in self.output_tasks.items():
                channel = None
                for ch_name, ch_config in self.config.channels.items():
                    if ch_name == name:
                        channel = ch_config
                        break

                try:
                    if channel and channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                        task.write(False)
                    elif channel and channel.channel_type in (ChannelType.PULSE_OUTPUT, ChannelType.COUNTER_OUTPUT):
                        task.stop()
                    else:
                        # Voltage or current output: write 0
                        task.write(0.0)

                    self.output_values[name] = 0.0
                    logger.warning(f"[SAFE STATE] {name} -> 0 (safe)")
                except Exception as e:
                    logger.error(f"[SAFE STATE] Failed to set {name}: {e}")

    def _reader_thread_func(self):
        """
        Background thread that continuously reads from hardware buffers.
        Updates self.latest_values with the most recent samples.
        """
        logger.info("Background reader thread started")

        # Pre-allocate numpy arrays for each task (for efficiency)
        task_buffers: Dict[str, np.ndarray] = {}
        for task_name, task_group in self.tasks.items():
            if task_group.is_continuous:
                num_channels = len(task_group.channel_names)
                # Read a small batch each iteration (latest samples only)
                task_buffers[task_name] = np.zeros((num_channels, 1), dtype=np.float64)

        while self._running:
            try:
                now = time.time()

                # Read from each continuous task
                for task_name, task_group in self.tasks.items():
                    if not task_group.is_continuous or task_group.reader is None:
                        continue

                    try:
                        # Check how many samples are available
                        available = task_group.task.in_stream.avail_samp_per_chan

                        if available > 0:
                            # Read all available samples, keep only the latest
                            num_channels = len(task_group.channel_names)
                            samples_to_read = min(available, BUFFER_SIZE)
                            buffer = np.zeros((num_channels, samples_to_read), dtype=np.float64)

                            # Read using stream reader (more efficient than task.read())
                            task_group.reader.read_many_sample(
                                buffer,
                                number_of_samples_per_channel=samples_to_read,
                                timeout=0.1  # Short timeout since data should be ready
                            )

                            # Update latest values (last sample from each channel)
                            with self.lock:
                                for i, name in enumerate(task_group.channel_names):
                                    value = buffer[i, -1]  # Last sample

                                    # Convert current from Amps to mA
                                    # Use per-channel type from channel_types dict if available
                                    ch_type = task_group.channel_types.get(name, task_group.channel_type)
                                    if ch_type == ChannelType.CURRENT_INPUT:
                                        value = value * 1000.0

                                    self.latest_values[name] = value
                                    self.value_timestamps[name] = now

                            self._error_count = 0  # Reset error count on success

                    except Exception as e:
                        self._error_count += 1
                        if self._error_count <= 3:  # Only log first few errors
                            logger.warning(f"Error reading {task_name}: {e}")
                        # Set NaN for all channels in this task
                        with self.lock:
                            for name in task_group.channel_names:
                                self.latest_values[name] = float('nan')

                # Read digital inputs (on-demand, they're fast)
                for task_name, task_group in self.tasks.items():
                    if task_group.channel_type == ChannelType.DIGITAL_INPUT:
                        try:
                            raw_data = task_group.task.read(timeout=0.1)
                            with self.lock:
                                if isinstance(raw_data, list):
                                    for i, name in enumerate(task_group.channel_names):
                                        value = 1.0 if raw_data[i] else 0.0
                                        # Apply invert flag if set in config
                                        ch_config = self.config.channels.get(name)
                                        if ch_config and getattr(ch_config, 'invert', False):
                                            value = 1.0 - value
                                        self.latest_values[name] = value
                                else:
                                    value = 1.0 if raw_data else 0.0
                                    name = task_group.channel_names[0]
                                    ch_config = self.config.channels.get(name)
                                    if ch_config and getattr(ch_config, 'invert', False):
                                        value = 1.0 - value
                                    self.latest_values[name] = value
                        except Exception as e:
                            logger.warning(f"Error reading digital inputs {task_name}: {e}")

                # Read counters (on-demand)
                for name, task in self.counter_tasks.items():
                    try:
                        value = task.read(timeout=0.1)
                        channel = self.config.channels.get(name)
                        if channel and channel.counter_mode == "period" and value > 0:
                            value = 1.0 / value
                        elif channel and channel.counter_mode == "count":
                            # Handle 32-bit rollover for edge counting
                            if name not in self._counter_rollover:
                                self._counter_rollover[name] = {'prev': 0, 'offset': 0}
                            state = self._counter_rollover[name]
                            raw = int(value)
                            if raw < state['prev']:
                                # Rollover detected — add 2^32
                                state['offset'] += 0x100000000
                                logger.info(f"Counter rollover detected on {name}: "
                                           f"raw {state['prev']} -> {raw}, "
                                           f"total offset now {state['offset']}")
                            state['prev'] = raw
                            value = raw + state['offset']
                        with self.lock:
                            self.latest_values[name] = value
                    except Exception as e:
                        with self.lock:
                            self.latest_values[name] = float('nan')

                # Check for too many errors
                if self._error_count >= self._max_errors:
                    logger.error(f"Too many consecutive errors ({self._error_count}), attempting recovery...")
                    self._reader_died = True

                    # Notify via callback if registered
                    if self._error_callback:
                        try:
                            self._error_callback("reader_error", {
                                "error_count": self._error_count,
                                "recovery_attempt": self._recovery_attempts
                            })
                        except Exception as cb_err:
                            logger.error(f"Error callback failed: {cb_err}")

                    # Attempt auto-recovery
                    if self._recovery_attempts < self._max_recovery_attempts:
                        self._recovery_attempts += 1
                        logger.warning(f"Recovery attempt {self._recovery_attempts}/{self._max_recovery_attempts}")
                        try:
                            # Close and recreate tasks
                            self._close_tasks()
                            time.sleep(1.0)  # Brief pause before recreating
                            self._create_tasks()
                            self._error_count = 0
                            self._reader_died = False
                            logger.info("Hardware reader recovery successful")
                            continue  # Resume reading
                        except Exception as recovery_err:
                            logger.error(f"Recovery failed: {recovery_err}")

                    # Max recovery attempts reached - stop for good
                    logger.critical(f"HARDWARE READER FAILED after {self._max_recovery_attempts} recovery attempts")
                    if self._error_callback:
                        try:
                            self._error_callback("reader_failed", {
                                "error_count": self._error_count,
                                "message": "Maximum recovery attempts exceeded"
                            })
                        except Exception as e:
                            logger.warning(f"Recovery error callback failed: {e}")
                    break

                # Small sleep to prevent CPU spinning (10Hz effective read rate)
                time.sleep(0.05)

            except Exception as e:
                logger.error(f"Reader thread error: {e}")
                self._error_count += 1
                time.sleep(0.1)

        self._reader_died = True
        logger.info("Background reader thread stopped")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def set_error_callback(self, callback: callable):
        """Set callback for reader errors. Callback receives (event_type, details_dict)"""
        self._error_callback = callback

    def is_healthy(self) -> bool:
        """Check if the hardware reader is healthy and running"""
        return (
            self._running and
            not self._reader_died and
            self._reader_thread is not None and
            self._reader_thread.is_alive()
        )

    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status of the hardware reader"""
        return {
            'running': self._running,
            'thread_alive': self._reader_thread.is_alive() if self._reader_thread else False,
            'reader_died': self._reader_died,
            'error_count': self._error_count,
            'recovery_attempts': self._recovery_attempts,
            'healthy': self.is_healthy(),
            'watchdog_triggered': self._watchdog_triggered,
            'watchdog_active': self._watchdog_thread.is_alive() if self._watchdog_thread else False,
        }

    def read_channel(self, channel_name: str) -> Optional[float]:
        """Read a single channel value (returns cached value)"""
        with self.lock:
            return self.latest_values.get(channel_name)

    def read_all(self) -> Dict[str, float]:
        """
        Read all channels and return raw values.
        This returns CACHED values from the background reader thread - INSTANT!
        No hardware blocking here.
        """
        with self.lock:
            # Copy latest values
            values = dict(self.latest_values)

            # Include current output states
            for name, value in self.output_values.items():
                values[name] = value

        return values

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """
        Write a value to an output channel with hardware readback verification.
        Matches HardwareSimulator.write_channel() interface.

        Industrial-grade: After writing, we read back the actual hardware state
        to verify the write succeeded. This ensures displayed values match reality.
        """
        if channel_name not in self.output_tasks:
            logger.warning(f"Channel {channel_name} is not a writable output")
            return False

        channel = self.config.channels.get(channel_name)
        if not channel:
            return False

        with self.lock:
            try:
                task = self.output_tasks[channel_name]

                if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                    # Convert to boolean
                    bool_value = bool(value) if not isinstance(value, bool) else value
                    if channel.invert:
                        bool_value = not bool_value
                    task.write(bool_value)

                    # READBACK: Verify actual hardware state
                    try:
                        actual_state = task.read()
                        # Apply invert for display (show logical state, not physical)
                        if channel.invert:
                            actual_state = not actual_state
                        self.output_values[channel_name] = 1.0 if actual_state else 0.0
                        logger.debug(f"DO {channel_name}: wrote={bool_value}, readback={actual_state}")
                    except Exception as rb_err:
                        # Readback failed - use commanded value as fallback
                        logger.warning(f"DO readback failed for {channel_name}: {rb_err}")
                        self.output_values[channel_name] = 1.0 if bool_value else 0.0

                    # Momentary pulse: auto-revert after delay (relay feature)
                    momentary_ms = getattr(channel, 'momentary_pulse_ms', 0)
                    if momentary_ms > 0 and bool_value:
                        # Cancel any existing timer for this channel
                        if channel_name in self._momentary_timers:
                            self._momentary_timers[channel_name].cancel()
                        timer = threading.Timer(
                            momentary_ms / 1000.0,
                            self._revert_momentary,
                            args=(channel_name,)
                        )
                        timer.daemon = True
                        timer.start()
                        self._momentary_timers[channel_name] = timer

                elif channel.channel_type == ChannelType.VOLTAGE_OUTPUT:
                    eng_value = float(value)  # Engineering units from user (%, RPM, PSI, etc.)

                    # Apply REVERSE scaling: convert engineering units → raw voltage
                    # Example: 50% → 5.0V (if 0-100% maps to 0-10V)
                    raw_value = reverse_scaling(channel, eng_value)

                    # Clamp raw output to valid hardware range
                    v_range = channel.voltage_range or 10.0
                    raw_value = max(0.0, min(v_range, raw_value))
                    task.write(raw_value)

                    logger.debug(f"VO {channel_name}: eng={eng_value} → raw={raw_value:.4f}V")

                    # READBACK: Verify actual hardware state
                    try:
                        actual_raw = task.read()
                        # Store engineering value for display (what user sees)
                        self.output_values[channel_name] = eng_value
                        # Check for significant mismatch (tolerance for DAC precision)
                        if abs(actual_raw - raw_value) > 0.01:
                            logger.warning(f"VO mismatch {channel_name}: commanded={raw_value:.4f}V, actual={actual_raw:.4f}V")
                        else:
                            logger.debug(f"VO {channel_name}: wrote={raw_value:.4f}V, readback={actual_raw:.4f}V")
                    except Exception as rb_err:
                        # Readback failed - use commanded engineering value as fallback
                        logger.warning(f"VO readback failed for {channel_name}: {rb_err}")
                        self.output_values[channel_name] = eng_value

                elif channel.channel_type == ChannelType.CURRENT_OUTPUT:
                    eng_value = float(value)  # Engineering units from user (%, RPM, PSI, etc.)

                    # Apply REVERSE scaling: convert engineering units → raw mA
                    raw_ma = reverse_scaling(channel, eng_value)

                    # Clamp raw output to valid hardware range (in mA)
                    max_ma = channel.current_range_ma or 20.0
                    raw_ma = max(0.0, min(max_ma, raw_ma))
                    raw_amps = raw_ma / 1000.0  # Convert to Amps for hardware
                    task.write(raw_amps)

                    logger.debug(f"CO {channel_name}: eng={eng_value} → raw={raw_ma:.3f}mA")

                    # READBACK: Verify actual hardware state
                    try:
                        actual_amps = task.read()
                        actual_ma = actual_amps * 1000.0
                        # Store engineering value for display (what user sees)
                        self.output_values[channel_name] = eng_value
                        # Check for significant mismatch (tolerance for DAC precision)
                        if abs(actual_ma - raw_ma) > 0.05:  # 0.05mA tolerance
                            logger.warning(f"CO mismatch {channel_name}: commanded={raw_ma:.3f}mA, actual={actual_ma:.3f}mA")
                        else:
                            logger.debug(f"CO {channel_name}: wrote={raw_ma:.3f}mA, readback={actual_ma:.3f}mA")
                    except Exception as rb_err:
                        # Readback failed - use commanded engineering value as fallback
                        logger.warning(f"CO readback failed for {channel_name}: {rb_err}")
                        self.output_values[channel_name] = eng_value

                elif channel.channel_type in (ChannelType.PULSE_OUTPUT, ChannelType.COUNTER_OUTPUT):
                    # Pulse/counter output: update frequency
                    new_freq = float(value)
                    if new_freq > 0:
                        task.stop()
                        task.co_channels.all.co_pulse_freq = new_freq
                        task.start()
                        self.output_values[channel_name] = new_freq
                        logger.debug(f"PLS {channel_name}: freq={new_freq}Hz")
                    else:
                        task.stop()
                        self.output_values[channel_name] = 0.0
                        logger.debug(f"PLS {channel_name}: stopped (freq=0)")

                logger.debug(f"Wrote {value} to {channel_name}")
                return True

            except Exception as e:
                logger.error(f"Error writing to {channel_name}: {e}")
                return False

    def refresh_output_states(self) -> Dict[str, float]:
        """
        Read back actual hardware state for all output channels.

        Industrial-grade: Periodically refresh output states from hardware
        to detect external changes, hardware faults, or communication issues.
        This ensures the dashboard always shows true hardware state.

        Returns:
            Dict mapping channel name -> actual hardware value
        """
        refreshed = {}

        with self.lock:
            for channel_name, task in self.output_tasks.items():
                channel = self.config.channels.get(channel_name)
                if not channel:
                    continue

                try:
                    actual_value = task.read()

                    if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                        # Apply invert for logical display
                        if channel.invert:
                            actual_value = not actual_value
                        refreshed[channel_name] = 1.0 if actual_value else 0.0

                    elif channel.channel_type == ChannelType.VOLTAGE_OUTPUT:
                        refreshed[channel_name] = float(actual_value)

                    elif channel.channel_type == ChannelType.CURRENT_OUTPUT:
                        # Convert Amps to mA for display
                        refreshed[channel_name] = float(actual_value) * 1000.0

                    # Check for drift from cached value
                    cached = self.output_values.get(channel_name)
                    if cached is not None:
                        if channel.channel_type == ChannelType.DIGITAL_OUTPUT:
                            if (cached > 0.5) != (refreshed[channel_name] > 0.5):
                                logger.warning(f"DO state drift detected: {channel_name} cached={cached}, actual={refreshed[channel_name]}")
                        elif abs(cached - refreshed[channel_name]) > 0.1:
                            logger.warning(f"AO drift detected: {channel_name} cached={cached:.3f}, actual={refreshed[channel_name]:.3f}")

                    # Update cache with actual value
                    self.output_values[channel_name] = refreshed[channel_name]

                except Exception as e:
                    logger.error(f"Failed to read back {channel_name}: {e}")
                    # Keep cached value on error
                    if channel_name in self.output_values:
                        refreshed[channel_name] = self.output_values[channel_name]

        return refreshed

    def set_temperature_target(self, channel_name: str, target: float):
        """
        For compatibility with simulator interface.
        Real hardware doesn't have temperature targets - this is a no-op.
        """
        pass

    def add_channel(self, channel: ChannelConfig):
        """
        Add a new channel dynamically.
        Note: This requires recreating tasks, which is expensive.
        For now, log a warning - full implementation would need task recreation.
        """
        logger.warning(f"Dynamic channel addition not fully supported in HardwareReader. "
                      f"Channel {channel.name} will need service restart to take effect.")

    def remove_channel(self, channel_name: str):
        """
        Remove a channel dynamically.
        Similar to add_channel - requires task recreation.
        """
        logger.warning(f"Dynamic channel removal not fully supported in HardwareReader. "
                      f"Channel {channel_name} removal will need service restart to take effect.")

    def trigger_event(self, event_type: str):
        """
        For compatibility with simulator interface.
        Real hardware doesn't have simulated events - this is a no-op.
        """
        pass

    def close(self):
        """Close all tasks and release hardware"""
        logger.info("Closing hardware reader tasks...")

        # Stop continuous acquisition first (stops background thread)
        self._stop_continuous_acquisition()

        # Stop watchdog thread (exits when _running = False)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=3.0)

        with self.lock:
            # Close input tasks
            for task_name, task_group in self.tasks.items():
                try:
                    task_group.task.close()
                    logger.debug(f"Closed task: {task_name}")
                except Exception as e:
                    logger.error(f"Error closing task {task_name}: {e}")
            self.tasks.clear()

            # Close output tasks
            for name, task in self.output_tasks.items():
                try:
                    task.close()
                    logger.debug(f"Closed output task: {name}")
                except Exception as e:
                    logger.error(f"Error closing output task {name}: {e}")
            self.output_tasks.clear()

            # Close counter tasks
            for name, task in self.counter_tasks.items():
                try:
                    task.close()
                    logger.debug(f"Closed counter task: {name}")
                except Exception as e:
                    logger.error(f"Error closing counter task {name}: {e}")
            self.counter_tasks.clear()

            # Cancel momentary pulse timers
            for timer in self._momentary_timers.values():
                timer.cancel()
            self._momentary_timers.clear()

        logger.info("Hardware reader closed")

    def reset_counter(self, channel_name: str):
        """Reset a counter channel to zero (if supported by hardware)"""
        if channel_name not in self.counter_tasks:
            logger.warning(f"Cannot reset counter {channel_name} - task not found")
            return

        # Note: NI-DAQmx counter reset is typically done by recreating the task
        # or using specific hardware counter reset functions
        # For now, we log that a reset was requested
        # The actual counter value is typically managed in software for totalizers
        logger.info(f"Hardware counter reset requested for {channel_name}")

    def _revert_momentary(self, channel_name: str):
        """Auto-revert a momentary relay/digital output to its default state."""
        try:
            channel = self.config.channels.get(channel_name)
            if not channel:
                return
            default_val = channel.default_value
            logger.info(f"Momentary revert: {channel_name} -> {default_val} "
                       f"(after {channel.momentary_pulse_ms}ms)")

            if channel_name in self.output_tasks:
                task = self.output_tasks[channel_name]
                bool_value = bool(default_val)
                if channel.invert:
                    bool_value = not bool_value
                with self.lock:
                    task.write(bool_value)
                    self.output_values[channel_name] = default_val
        except Exception as e:
            logger.error(f"Error reverting momentary output {channel_name}: {e}")
        finally:
            self._momentary_timers.pop(channel_name, None)

        # For count mode counters, we could potentially recreate the task
        # For frequency mode, the counter is always reading current frequency
        # Most use cases track the accumulated value in software (DAQ service)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# Test code
if __name__ == "__main__":
    import sys
    from pathlib import Path
    from config_parser import load_config

    if not NIDAQMX_AVAILABLE:
        print("nidaqmx not available - cannot test HardwareReader")
        sys.exit(1)

    config_path = Path(__file__).parent.parent.parent / "config" / "system.ini"
    config = load_config(str(config_path))

    # Force non-simulation mode for testing
    config.system.simulation_mode = False

    print("Creating HardwareReader...")
    try:
        with HardwareReader(config) as reader:
            print("Hardware reader created successfully")
            print(f"Input tasks: {list(reader.tasks.keys())}")
            print(f"Output tasks: {list(reader.output_tasks.keys())}")
            print(f"Counter tasks: {list(reader.counter_tasks.keys())}")

            print("\nReading all channels...")
            for i in range(3):
                values = reader.read_all()
                print(f"\nSample {i + 1}:")
                for name, value in sorted(values.items()):
                    print(f"  {name}: {value}")
                time.sleep(0.5)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
