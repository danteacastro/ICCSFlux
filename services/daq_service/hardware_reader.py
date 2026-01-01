"""
Hardware Reader for NISystem
Reads from real NI hardware using nidaqmx library
Provides the same interface as HardwareSimulator for drop-in replacement
"""

import logging
import threading
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

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
        READ_ALL_AVAILABLE
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

    config_map = {
        'RSE': TerminalConfiguration.RSE,
        'DIFF': TerminalConfiguration.DIFFERENTIAL,
        'DIFFERENTIAL': TerminalConfiguration.DIFFERENTIAL,
        'NRSE': TerminalConfiguration.NRSE,
        'PSEUDO_DIFF': TerminalConfiguration.PSEUDODIFFERENTIAL,
        'PSEUDODIFFERENTIAL': TerminalConfiguration.PSEUDODIFFERENTIAL,
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
    channel_type: ChannelType


class HardwareReader:
    """
    Reads from real NI hardware using nidaqmx.
    Provides the same interface as HardwareSimulator.
    """

    def __init__(self, config: NISystemConfig):
        if not NIDAQMX_AVAILABLE:
            raise RuntimeError("nidaqmx library not available - cannot use HardwareReader")

        self.config = config
        self.tasks: Dict[str, TaskGroup] = {}  # module_name -> TaskGroup
        self.output_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task
        self.counter_tasks: Dict[str, Any] = {}  # channel_name -> nidaqmx.Task

        # Output state cache (for read-back)
        self.output_values: Dict[str, float] = {}

        # Lock for thread safety
        self.lock = threading.Lock()

        # Initialize tasks
        self._create_tasks()

    def _get_physical_channel_path(self, channel: ChannelConfig) -> str:
        """
        Build the full physical channel path from module and channel config.
        E.g., "cDAQ1Mod1/ai0" from module in slot 1 with physical_channel "ai0"
        """
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

    def _create_tasks(self):
        """Create nidaqmx tasks for all input channels, grouped by module"""

        # Group channels by module and type
        module_channels: Dict[str, Dict[ChannelType, List[ChannelConfig]]] = {}

        for name, channel in self.config.channels.items():
            if channel.module not in module_channels:
                module_channels[channel.module] = {}
            if channel.channel_type not in module_channels[channel.module]:
                module_channels[channel.module][channel.channel_type] = []
            module_channels[channel.module][channel.channel_type].append(channel)

        # Create tasks for each module/type combination
        for module_name, type_channels in module_channels.items():
            module = self.config.modules.get(module_name)
            if not module or not module.enabled:
                continue

            for channel_type, channels in type_channels.items():
                try:
                    self._create_task_for_type(module_name, channel_type, channels)
                except Exception as e:
                    logger.error(f"Failed to create task for {module_name}/{channel_type}: {e}")

    def _create_task_for_type(self, module_name: str, channel_type: ChannelType,
                              channels: List[ChannelConfig]):
        """Create a task for a specific channel type on a module"""

        task_name = f"{module_name}_{channel_type.value}"

        if channel_type == ChannelType.THERMOCOUPLE:
            self._create_thermocouple_task(task_name, module_name, channels)
        elif channel_type == ChannelType.VOLTAGE:
            self._create_voltage_task(task_name, module_name, channels)
        elif channel_type == ChannelType.CURRENT:
            self._create_current_task(task_name, module_name, channels)
        elif channel_type == ChannelType.RTD:
            self._create_rtd_task(task_name, module_name, channels)
        elif channel_type == ChannelType.STRAIN:
            self._create_strain_task(task_name, module_name, channels)
        elif channel_type == ChannelType.IEPE:
            self._create_iepe_task(task_name, module_name, channels)
        elif channel_type == ChannelType.RESISTANCE:
            self._create_resistance_task(task_name, module_name, channels)
        elif channel_type == ChannelType.DIGITAL_INPUT:
            self._create_digital_input_task(task_name, module_name, channels)
        elif channel_type == ChannelType.DIGITAL_OUTPUT:
            self._create_digital_output_tasks(channels)
        elif channel_type == ChannelType.ANALOG_OUTPUT:
            self._create_analog_output_tasks(channels)
        elif channel_type == ChannelType.COUNTER:
            self._create_counter_tasks(channels)

    def _create_thermocouple_task(self, task_name: str, module_name: str,
                                   channels: List[ChannelConfig]):
        """Create thermocouple input task"""
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

                task.ai_channels.add_ai_thrmcpl_chan(
                    phys_chan,
                    name_to_assign_to_channel=channel.name,
                    thermocouple_type=tc_type,
                    cjc_source=cjc
                )
                channel_names.append(channel.name)
                logger.info(f"Added thermocouple channel: {channel.name} -> {phys_chan} "
                           f"(type={tc_type_str}, cjc={channel.cjc_source})")

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.THERMOCOUPLE
            )
        except Exception as e:
            task.close()
            raise

    def _create_voltage_task(self, task_name: str, module_name: str,
                              channels: List[ChannelConfig]):
        """Create voltage input task"""
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

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.VOLTAGE
            )
        except Exception as e:
            task.close()
            raise

    def _create_current_task(self, task_name: str, module_name: str,
                              channels: List[ChannelConfig]):
        """Create current input task (4-20mA)"""
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

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.CURRENT
            )
        except Exception as e:
            task.close()
            raise

    def _create_rtd_task(self, task_name: str, module_name: str,
                          channels: List[ChannelConfig]):
        """Create RTD (Resistance Temperature Detector) input task"""
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
                    r0=channel.rtd_resistance
                )
                channel_names.append(channel.name)
                logger.info(f"Added RTD channel: {channel.name} -> {phys_chan} "
                           f"(type={channel.rtd_type}, wiring={channel.rtd_wiring}, R0={channel.rtd_resistance})")

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.RTD
            )
        except Exception as e:
            task.close()
            raise

    def _create_strain_task(self, task_name: str, module_name: str,
                             channels: List[ChannelConfig]):
        """Create strain gauge input task"""
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

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.STRAIN
            )
        except Exception as e:
            task.close()
            raise

    def _create_iepe_task(self, task_name: str, module_name: str,
                           channels: List[ChannelConfig]):
        """Create IEPE (accelerometer/microphone) input task"""
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

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.IEPE
            )
        except Exception as e:
            task.close()
            raise

    def _create_resistance_task(self, task_name: str, module_name: str,
                                  channels: List[ChannelConfig]):
        """Create resistance measurement input task"""
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

            self.tasks[task_name] = TaskGroup(
                task=task,
                channel_names=channel_names,
                module_name=module_name,
                channel_type=ChannelType.RESISTANCE
            )
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
                    name_to_assign_to_channel=channel.name
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
                    name_to_assign_to_channel=channel.name
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

    def read_channel(self, channel_name: str) -> Optional[float]:
        """Read a single channel value"""
        values = self.read_all()
        return values.get(channel_name)

    def read_all(self) -> Dict[str, float]:
        """
        Read all channels and return raw values.
        This matches the HardwareSimulator.read_all() interface.
        """
        values = {}

        with self.lock:
            # Read from grouped input tasks
            for task_name, task_group in self.tasks.items():
                try:
                    if task_group.channel_type == ChannelType.DIGITAL_INPUT:
                        # Digital reads return booleans
                        raw_data = task_group.task.read()
                        if isinstance(raw_data, list):
                            for i, name in enumerate(task_group.channel_names):
                                values[name] = 1.0 if raw_data[i] else 0.0
                        else:
                            # Single channel
                            values[task_group.channel_names[0]] = 1.0 if raw_data else 0.0
                    else:
                        # Analog reads return floats
                        raw_data = task_group.task.read()
                        if isinstance(raw_data, list):
                            for i, name in enumerate(task_group.channel_names):
                                value = raw_data[i]
                                # Convert current from Amps to mA
                                if task_group.channel_type == ChannelType.CURRENT:
                                    value = value * 1000.0
                                values[name] = value
                        else:
                            # Single channel
                            value = raw_data
                            if task_group.channel_type == ChannelType.CURRENT:
                                value = value * 1000.0
                            values[task_group.channel_names[0]] = value

                except Exception as e:
                    logger.error(f"Error reading task {task_name}: {e}")
                    # Return NaN for failed channels
                    for name in task_group.channel_names:
                        values[name] = float('nan')

            # Read counter tasks individually
            for name, task in self.counter_tasks.items():
                try:
                    value = task.read()
                    channel = self.config.channels.get(name)

                    # For period mode, convert to frequency
                    if channel and channel.counter_mode == "period" and value > 0:
                        value = 1.0 / value  # Convert period to frequency

                    values[name] = value
                except Exception as e:
                    logger.error(f"Error reading counter {name}: {e}")
                    values[name] = 0.0

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
