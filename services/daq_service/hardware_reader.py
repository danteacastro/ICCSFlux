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
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from queue import Queue

from config_parser import NISystemConfig, ChannelConfig, ChannelType, ThermocoupleType, ModuleConfig

# Try to import nidaqmx
try:
    import nidaqmx
    from nidaqmx.constants import (
        TerminalConfiguration,
        ThermocoupleType as NI_TCType,
        AcquisitionType,
        Edge,
        CountDirection,
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
except ImportError:
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
        logger.warning(f"Unknown terminal config '{config_str}', defaulting to RSE. "
                      f"Valid options: RSE, DIFF, NRSE, PSEUDO_DIFF, DEFAULT")
        return TerminalConfiguration.RSE

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

    def __init__(self, config: NISystemConfig, sample_rate: float = SAMPLE_RATE_HZ):
        if not NIDAQMX_AVAILABLE:
            raise RuntimeError("nidaqmx library not available - cannot use HardwareReader")

        self.config = config
        self.sample_rate = sample_rate
        self.tasks: Dict[str, TaskGroup] = {}  # task_name -> TaskGroup
        self.output_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task
        self.counter_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task

        # Output state cache (for read-back)
        self.output_values: Dict[str, float] = {}

        # CONTINUOUS ACQUISITION: Latest values from background thread
        self.latest_values: Dict[str, float] = {}
        self.value_timestamps: Dict[str, float] = {}  # When each value was last updated

        # Background reader thread control
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._error_count = 0
        self._max_errors = 10  # Stop after this many consecutive errors

        # Lock for thread safety
        self.lock = threading.Lock()

        # Initialize tasks
        self._create_tasks()

        # Start continuous acquisition
        self._start_continuous_acquisition()

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
            ChannelType.THERMOCOUPLE, ChannelType.VOLTAGE, ChannelType.CURRENT,
            ChannelType.RTD, ChannelType.STRAIN, ChannelType.IEPE, ChannelType.RESISTANCE
        }

        for name, channel in self.config.channels.items():
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
            analog_out_channels = [c for c in channels if c.channel_type == ChannelType.ANALOG_OUTPUT]
            counter_channels = [c for c in channels if c.channel_type == ChannelType.COUNTER]

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

            # Analog outputs (individual tasks per channel)
            if analog_out_channels:
                self._create_analog_output_tasks(analog_out_channels)

            # Counters (individual tasks per channel)
            if counter_channels:
                self._create_counter_tasks(counter_channels)

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

        try:
            for channel in channels:
                phys_chan = self._get_physical_channel_path(channel)

                if channel.channel_type == ChannelType.THERMOCOUPLE:
                    # Thermocouple
                    tc_type = NI_TCType.K  # Default
                    if channel.thermocouple_type:
                        tc_type_str = TC_TYPE_MAP.get(channel.thermocouple_type, 'K')
                        tc_type = getattr(NI_TCType, tc_type_str, NI_TCType.K)
                    cjc = get_cjc_source(channel.cjc_source)

                    ai_chan = task.ai_channels.add_ai_thrmcpl_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        thermocouple_type=tc_type,
                        cjc_source=cjc
                    )

                    # Enable open thermocouple detection
                    # When TC is open/broken, NI-DAQmx will return a very large value (~1e308)
                    # which our validation layer will detect and convert to NaN
                    try:
                        ai_chan.ai_open_thrmcpl_detect_enable = True
                        logger.info(f"Added thermocouple: {channel.name} -> {phys_chan} (open TC detection enabled)")
                    except Exception as e:
                        logger.warning(f"Could not enable open TC detection for {channel.name}: {e}")
                        logger.info(f"Added thermocouple: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.VOLTAGE:
                    # Voltage
                    v_range = channel.voltage_range or 10.0
                    term_config = get_terminal_config(channel.terminal_config)

                    task.ai_channels.add_ai_voltage_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        terminal_config=term_config,
                        min_val=-v_range,
                        max_val=v_range
                    )
                    logger.info(f"Added voltage: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.CURRENT:
                    # Current (4-20mA)
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
                    logger.info(f"Added current: {channel.name} -> {phys_chan}")

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
                    wiring = wiring_map.get(channel.resistance_config or channel.rtd_wiring,
                                           ResistanceConfiguration.THREE_WIRE)

                    task.ai_channels.add_ai_rtd_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        rtd_type=rtd_type,
                        resistance_config=wiring,
                        current_excit_source=ExcitationSource.INTERNAL,
                        current_excit_val=channel.excitation_current or channel.rtd_current or 0.001,
                        r_0=channel.rtd_resistance or 100.0
                    )
                    logger.info(f"Added RTD: {channel.name} -> {phys_chan}")

                elif channel.channel_type == ChannelType.STRAIN:
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

                elif channel.channel_type == ChannelType.IEPE:
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

                elif channel.channel_type == ChannelType.RESISTANCE:
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
                channel_type=ChannelType.VOLTAGE,  # Generic - we track per-channel in channel_types
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

                ai_chan = task.ai_channels.add_ai_thrmcpl_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    thermocouple_type=tc_type,
                    cjc_source=cjc
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
                channel_type=ChannelType.VOLTAGE,
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
                channel_type=ChannelType.CURRENT,
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

        try:
            for channel in channels:
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
                self.output_values[channel.name] = 1.0 if channel.default_state else 0.0

                # Set initial state
                task.write(channel.default_state)
                logger.info(f"Added digital output channel: {channel.name} -> {phys_chan}")

            except Exception as e:
                logger.error(f"Failed to create DO task for {channel.name}: {e}")

    def _create_analog_output_tasks(self, channels: List[ChannelConfig]):
        """Create individual analog output tasks"""
        for channel in channels:
            try:
                phys_chan = self._get_physical_channel_path(channel)
                task = nidaqmx.Task(f"AO_{channel.name}")

                v_range = channel.voltage_range or 10.0
                task.ao_channels.add_ao_voltage_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    min_val=0.0,  # Most AO modules are 0-10V
                    max_val=v_range
                )

                self.output_tasks[channel.name] = task
                self.output_values[channel.name] = channel.default_value or 0.0

                # Set initial value
                task.write(channel.default_value or 0.0)
                logger.info(f"Added analog output channel: {channel.name} -> {phys_chan}")

            except Exception as e:
                logger.error(f"Failed to create AO task for {channel.name}: {e}")

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
                    # Frequency measurement
                    task.ci_channels.add_ci_freq_chan(
                        phys_chan,
                        name_to_assign_to_channel=channel.name,
                        min_val=min_freq,
                        max_val=max_freq,
                        units=FrequencyUnits.HZ,
                        edge=edge
                    )
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
                                    if ch_type == ChannelType.CURRENT:
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
                                        self.latest_values[name] = 1.0 if raw_data[i] else 0.0
                                else:
                                    self.latest_values[task_group.channel_names[0]] = 1.0 if raw_data else 0.0
                        except Exception as e:
                            logger.warning(f"Error reading digital inputs {task_name}: {e}")

                # Read counters (on-demand)
                for name, task in self.counter_tasks.items():
                    try:
                        value = task.read(timeout=0.1)
                        channel = self.config.channels.get(name)
                        if channel and channel.counter_mode == "period" and value > 0:
                            value = 1.0 / value
                        with self.lock:
                            self.latest_values[name] = value
                    except Exception as e:
                        with self.lock:
                            self.latest_values[name] = float('nan')

                # Check for too many errors
                if self._error_count >= self._max_errors:
                    logger.error(f"Too many consecutive errors ({self._error_count}), stopping reader")
                    break

                # Small sleep to prevent CPU spinning (10Hz effective read rate)
                time.sleep(0.05)

            except Exception as e:
                logger.error(f"Reader thread error: {e}")
                self._error_count += 1
                time.sleep(0.1)

        logger.info("Background reader thread stopped")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

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
        Write a value to an output channel.
        Matches HardwareSimulator.write_channel() interface.
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
                    self.output_values[channel_name] = 1.0 if bool_value else 0.0

                elif channel.channel_type == ChannelType.ANALOG_OUTPUT:
                    float_value = float(value)
                    # Clamp to valid range
                    v_range = channel.voltage_range or 10.0
                    float_value = max(0.0, min(v_range, float_value))
                    task.write(float_value)
                    self.output_values[channel_name] = float_value

                logger.debug(f"Wrote {value} to {channel_name}")
                return True

            except Exception as e:
                logger.error(f"Error writing to {channel_name}: {e}")
                return False

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
