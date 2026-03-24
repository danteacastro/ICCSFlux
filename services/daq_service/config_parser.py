"""
Configuration Parser for NISystem
Reads INI configuration files and creates channel/module definitions
"""

import configparser
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from pathlib import Path

logger = logging.getLogger('ConfigParser')

class ChannelType(Enum):
    # Analog Inputs
    THERMOCOUPLE = "thermocouple"
    VOLTAGE_INPUT = "voltage_input"
    CURRENT_INPUT = "current_input"
    RTD = "rtd"                      # Resistance Temperature Detector
    STRAIN = "strain"                # Strain gauge / bridge (short form)
    STRAIN_INPUT = "strain_input"    # Strain gauge / bridge (explicit form)
    BRIDGE_INPUT = "bridge_input"    # Wheatstone bridge / universal bridge input
    IEPE = "iepe"                    # IEPE/ICP accelerometers/microphones (short form)
    IEPE_INPUT = "iepe_input"        # IEPE/ICP (explicit form)
    RESISTANCE = "resistance"        # Resistance measurement (short form)
    RESISTANCE_INPUT = "resistance_input"  # Resistance measurement (explicit form)

    # Analog Outputs
    VOLTAGE_OUTPUT = "voltage_output"
    CURRENT_OUTPUT = "current_output"

    # Digital
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"

    # Counter/Timer
    COUNTER = "counter"              # Pulse/frequency counter (short form)
    COUNTER_INPUT = "counter_input"  # Pulse/frequency counter (explicit form)
    COUNTER_OUTPUT = "counter_output"
    FREQUENCY_INPUT = "frequency_input"
    PULSE_OUTPUT = "pulse_output"

    # Modbus channel types
    MODBUS_REGISTER = "modbus_register"  # Modbus holding/input register
    MODBUS_COIL = "modbus_coil"          # Modbus coil/discrete input

    @classmethod
    def _missing_(cls, value):
        """Handle alternate short names for channel types."""
        alt_map = {
            "voltage": cls.VOLTAGE_INPUT,
            "current": cls.CURRENT_INPUT,
            "analog_output": cls.VOLTAGE_OUTPUT,
            "analog_input": cls.VOLTAGE_INPUT,
        }
        if value in alt_map:
            return alt_map[value]
        return None

class ThermocoupleType(Enum):
    J = "J"
    K = "K"
    T = "T"
    E = "E"
    N = "N"
    R = "R"
    S = "S"
    B = "B"

class HardwareSource(Enum):
    """
    Hardware source type for channels.

    This enum clearly identifies WHERE data comes from:
    - LOCAL_DAQ: NI-DAQmx hardware connected to THIS PC (cDAQ, PXI, USB devices)
    - CRIO: Remote cRIO controller (data arrives via MQTT, processed on cRIO)
    - OPTO22: Remote Opto22 groov EPIC/RIO (data arrives via MQTT)
    - MODBUS_TCP: Modbus TCP device (read directly by this PC)
    - MODBUS_RTU: Modbus RTU device (read directly by this PC via serial)
    - VIRTUAL: Computed/derived channel (no physical hardware)

    Safety implications:
    - LOCAL_DAQ: Safety logic runs on PC - if PC crashes, no protection
    - CRIO: Safety logic can run on cRIO - continues if PC disconnects
    - OPTO22: Safety logic can run on groov EPIC - continues if PC disconnects
    - MODBUS: Safety logic runs on PC - dependent on PC and network
    """
    LOCAL_DAQ = "local_daq"    # cDAQ, PXI, USB - read by PC via NI-DAQmx
    CRIO = "crio"              # Remote cRIO - data via MQTT, safety on cRIO
    OPTO22 = "opto22"          # Remote Opto22 - data via MQTT, safety on EPIC/RIO
    MODBUS_TCP = "modbus_tcp"  # Modbus TCP device - read by PC
    MODBUS_RTU = "modbus_rtu"  # Modbus RTU device - read by PC via serial
    VIRTUAL = "virtual"        # Computed channel - no hardware
    GC_NODE = "gc_node"        # Remote GC node in Hyper-V VM - data via MQTT

    @classmethod
    def from_channel_config(cls, channel: 'ChannelConfig') -> 'HardwareSource':
        """Determine hardware source from channel configuration."""
        # Check explicit source_type first (remote nodes)
        if channel.source_type == "crio":
            return cls.CRIO
        if channel.source_type == "opto22":
            return cls.OPTO22
        if channel.source_type == "gc":
            return cls.GC_NODE
        if channel.source_type == "cfp":
            # CFP channels use real signal types (thermocouple, voltage_input, etc.)
            # but are transported via Modbus TCP/RTU
            phys = channel.physical_channel.lower()
            if phys.startswith("rtu://") or "com" in phys:
                return cls.MODBUS_RTU
            return cls.MODBUS_TCP

        # Check for Modbus channels
        if channel.channel_type in (ChannelType.MODBUS_REGISTER, ChannelType.MODBUS_COIL):
            # Determine TCP vs RTU from physical_channel format
            # RTU format: "rtu://COM3:1:40001" or has modbus_rtu_ prefix
            phys = channel.physical_channel.lower()
            if phys.startswith("rtu://") or "com" in phys:
                return cls.MODBUS_RTU
            return cls.MODBUS_TCP

        # Check for virtual/computed channels
        if channel.physical_channel.startswith("virtual://"):
            return cls.VIRTUAL

        # Default: local DAQ (cDAQ, PXI, USB, Dev)
        return cls.LOCAL_DAQ

class ProjectMode(Enum):
    """
    Defines the system architecture mode.

    CDAQ: PC is the "PLC" - reads hardware directly, evaluates alarms,
          executes safety actions, runs scripts. Traditional single-PC architecture.

    CRIO: cRIO is the PLC, PC is HMI only. cRIO reads hardware, evaluates alarms,
          executes safety, runs scripts autonomously. PC displays values, sends
          commands (forwarded to cRIO), logs data, handles user auth.
          Like Allen Bradley PLC with FactoryTalk HMI.

    OPTO22: Opto22 groov EPIC/RIO is the PLC, PC is HMI only. Same architecture
            as CRIO mode but using Opto22 hardware instead of NI cRIO.

    CFP: CompactFieldPoint (cFP-18xx/20xx) hardware read via Modbus TCP/RTU.
         PC handles all control logic (scripts, safety, PID) — same architecture
         as CDAQ but I/O is over Modbus instead of NI-DAQmx. Channels use their
         real signal types (thermocouple, voltage_input, etc.) with source_type='cfp'
         so the backend routes them through ModbusReader.
    """
    CDAQ = "cdaq"     # PC does everything (legacy/simple mode)
    CRIO = "crio"     # cRIO is PLC, PC is HMI (robust/industrial mode)
    OPTO22 = "opto22" # Opto22 is PLC, PC is HMI (like CRIO but different hardware)
    CFP = "cfp"       # CompactFieldPoint via Modbus — PC handles all control (like cDAQ)

@dataclass
class SystemConfig:
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_base_topic: str = "nisystem"
    scan_rate_hz: float = 4.0      # Scan rate (capped at 100Hz)
    publish_rate_hz: float = 4.0   # Publish rate (capped at 10Hz)
    simulation_mode: bool = False
    log_directory: str = "./logs"
    config_reload_topic: str = "nisystem/config/reload"
    # Multi-node support
    node_id: str = "node-001"      # Unique node identifier
    node_name: str = "Default Node"  # Human-readable node name
    # Default project to load on startup
    default_project: str = ""      # Absolute path to default project JSON
    # Project mode: determines cDAQ (PC is PLC) vs cRIO (cRIO is PLC, PC is HMI)
    project_mode: ProjectMode = ProjectMode.CDAQ
    # Watchdog output: toggles a digital output so external safety relay can
    # detect the cRIO is alive. If pulse stops, the external relay trips.
    watchdog_output_enabled: bool = False
    watchdog_output_channel: str = ""
    watchdog_output_rate_hz: float = 1.0
    # Logging (per-project, defaults from system.ini [logging])
    log_level: str = "INFO"
    log_max_file_size_mb: int = 50
    log_backup_count: int = 3
    # Service timing (per-project, defaults from system.ini [service])
    service_heartbeat_interval_sec: float = 2.0
    service_health_timeout_sec: float = 10.0
    service_shutdown_timeout_sec: float = 10.0
    service_command_ack_timeout_sec: float = 5.0
    # Data viewer retention (per-project, defaults from system.ini [dataviewer])
    dataviewer_retention_days: int = 30

@dataclass
class DataViewerConfig:
    retention_days: int = 30

@dataclass
class ChassisConfig:
    name: str
    chassis_type: str
    serial: str = ""
    connection: str = "USB"
    ip_address: str = ""
    description: str = ""
    enabled: bool = True
    # NI MAX device name (e.g., "cDAQ1" or "cDAQ9189-1234567")
    # If not specified, will attempt auto-discovery by serial or slot
    device_name: str = ""

    # Modbus TCP settings
    modbus_port: int = 502              # TCP port (default 502)

    # Modbus RTU settings (serial)
    modbus_baudrate: int = 9600         # Baud rate: 9600, 19200, 38400, 57600, 115200
    modbus_parity: str = "E"            # N=None, E=Even, O=Odd
    modbus_stopbits: int = 1            # Stop bits: 1 or 2
    modbus_bytesize: int = 8            # Data bits: 7 or 8

    # Modbus common settings
    modbus_timeout: float = 1.0         # Response timeout in seconds
    modbus_retries: int = 3             # Number of retries on failure

@dataclass
class ModuleConfig:
    name: str
    module_type: str
    chassis: str
    slot: int
    description: str = ""
    enabled: bool = True

@dataclass
class ChannelConfig:
    name: str
    physical_channel: str
    channel_type: ChannelType
    module: str = ""  # Optional - empty for channels with full physical_channel paths (e.g., "cDAQ-9189-DHWSIMMod1/ai0")
    description: str = ""
    units: str = ""

    # Visibility - hidden channels still collect data but don't appear in UI
    visible: bool = True

    # Group for organization in UI
    group: str = ""

    # Scaling - Linear (y = mx + b)
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    scale_type: str = "none"  # none, linear, map, four_twenty

    # 4-20mA scaling (for current inputs)
    four_twenty_scaling: bool = False
    eng_units_min: Optional[float] = None  # Value at 4mA
    eng_units_max: Optional[float] = None  # Value at 20mA

    # Map scaling (for voltage inputs)
    pre_scaled_min: Optional[float] = None  # Raw voltage min
    pre_scaled_max: Optional[float] = None  # Raw voltage max
    scaled_min: Optional[float] = None      # Scaled output min
    scaled_max: Optional[float] = None      # Scaled output max

    # Ranges
    voltage_range: float = 10.0
    current_range_ma: float = 20.0
    shunt_resistor_loc: str = "internal"  # internal or external (for current input modules)

    # Terminal configuration for analog inputs (DEFAULT, RSE, DIFF, NRSE, PSEUDO_DIFF)
    # DEFAULT = Let DAQmx auto-select (recommended - works with all modules)
    # RSE = Referenced Single-Ended
    # DIFF = Differential (better noise rejection, uses 2 channels)
    # NRSE = Non-Referenced Single-Ended
    # PSEUDO_DIFF = Pseudo-Differential
    terminal_config: str = "DEFAULT"

    # Thermocouple specific
    thermocouple_type: Optional[ThermocoupleType] = None
    cjc_source: str = "internal"
    cjc_value: float = 25.0          # Constant CJC temperature in °C (when cjc_source='constant')
    open_detect: bool = True         # Open thermocouple detection (default: enabled)
    auto_zero: bool = False          # Auto-zero for improved accuracy

    # RTD specific
    rtd_type: str = "Pt100"          # Pt100, Pt500, Pt1000, custom
    rtd_resistance: float = 100.0    # Nominal resistance at 0°C
    rtd_wiring: str = "4-wire"       # 2-wire, 3-wire, 4-wire
    rtd_current: float = 0.001       # Excitation current in Amps (default 1mA)

    # Strain gauge specific
    strain_config: str = "full-bridge"  # full-bridge, half-bridge[-I/-II/-III], quarter-bridge[-I/-II]
    strain_excitation_voltage: float = 2.5  # Bridge excitation voltage
    strain_gage_factor: float = 2.0  # Gage factor (typically 2.0 for foil gages)
    strain_resistance: float = 350.0 # Nominal gage resistance in Ohms
    poisson_ratio: float = 0.30      # Poisson ratio (for quarter-bridge compensation)

    # IEPE specific (accelerometers, microphones)
    iepe_sensitivity: float = 100.0  # mV/g or mV/Pa
    iepe_current: float = 0.004      # Excitation current in Amps (default 4mA)
    iepe_coupling: str = "AC"        # AC or DC coupling

    # Resistance specific
    resistance_range: float = 1000.0 # Maximum expected resistance in Ohms
    resistance_wiring: str = "4-wire"  # 2-wire, 4-wire

    # Counter specific
    counter_mode: str = "frequency"  # frequency, count, period, position (encoder)
    pulses_per_unit: float = 1.0     # e.g., 100 pulses = 1 gallon → pulses_per_unit = 100
    counter_edge: str = "rising"     # rising, falling, both
    counter_reset_on_read: bool = False  # For totalizer mode
    counter_min_freq: float = 0.1    # Minimum expected frequency in Hz
    counter_max_freq: float = 1000.0 # Maximum expected frequency in Hz
    # Encoder-specific (position mode)
    decoding_type: str = "X4"        # X1, X2, X4, two_pulse
    pulses_per_revolution: int = 1024  # Encoder resolution
    z_index_enable: bool = False     # Z-index (home) pulse enable

    # Pulse/Counter output specific
    pulse_frequency: float = 1000.0       # Output frequency in Hz
    pulse_duty_cycle: float = 50.0        # Duty cycle 0-100%
    pulse_idle_state: str = "LOW"         # LOW or HIGH (idle level)

    # Relay specific
    relay_type: str = "none"              # none, spst, spdt, ssr (informational)
    momentary_pulse_ms: int = 0           # 0 = latching (stays ON), >0 = momentary (auto-OFF after N ms)

    # Modbus specific
    modbus_register_type: str = "holding"  # holding, input, coil, discrete
    modbus_address: int = 0                # Register/coil address
    modbus_data_type: str = "float32"      # int16, uint16, int32, uint32, float32, float64, bool
    modbus_byte_order: str = "big"         # big or little endian
    modbus_word_order: str = "big"         # For 32/64-bit: big or little (word swap)
    modbus_scale: float = 1.0              # Scale factor: value = raw * scale + offset
    modbus_offset: float = 0.0             # Offset: value = raw * scale + offset
    modbus_slave_id: Optional[int] = None  # Explicit slave ID (overrides module slot)
    # Batch reading: read multiple registers at once, extract value at specific index
    modbus_register_count: Optional[int] = None  # Registers to read (None = auto from data_type)
    modbus_register_index: int = 0               # Index within batch to extract value from

    # Digital specific
    invert: bool = False
    default_state: bool = False
    default_value: float = 0.0

    # Limits and warnings (legacy - use ISA-18.2 fields below)
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None
    low_warning: Optional[float] = None
    high_warning: Optional[float] = None

    # ISA-18.2 Alarm Configuration
    alarm_enabled: bool = False              # Master enable for alarm checking
    hihi_limit: Optional[float] = None       # High-High (critical)
    hi_limit: Optional[float] = None         # High (warning)
    lo_limit: Optional[float] = None         # Low (warning)
    lolo_limit: Optional[float] = None       # Low-Low (critical)
    alarm_priority: str = "medium"           # diagnostic, low, medium, high, critical
    alarm_deadband: float = 1.0              # Hysteresis to prevent chatter
    alarm_delay_sec: float = 0.0             # On-delay before triggering

    # Digital Input Alarm Configuration
    digital_alarm_enabled: bool = False      # Enable alarm for digital inputs
    digital_expected_state: str = "HIGH"     # Expected state: HIGH or LOW
    digital_debounce_ms: int = 100           # Debounce time in milliseconds
    digital_invert: bool = False             # Invert logic for NC sensors

    # Safety
    safety_action: Optional[str] = None
    safety_interlock: Optional[str] = None

    # Logging
    log: bool = True
    log_interval_ms: int = 1000

    # Data source tracking (for multi-node systems)
    # source_type: 'local' (read via local HardwareReader), 'crio' (receive via MQTT from cRIO node)
    source_type: str = "local"
    source_node_id: str = ""  # Node ID for remote sources (e.g., "crio-001")

    # === Hardware Source Helper Properties ===

    @property
    def hardware_source(self) -> HardwareSource:
        """Get the hardware source type for this channel."""
        return HardwareSource.from_channel_config(self)

    @property
    def is_crio(self) -> bool:
        """True if this channel is on a remote cRIO controller."""
        return self.hardware_source == HardwareSource.CRIO

    @property
    def is_opto22(self) -> bool:
        """True if this channel is on a remote Opto22 groov EPIC/RIO."""
        return self.hardware_source == HardwareSource.OPTO22

    @property
    def is_gc_node(self) -> bool:
        """True if this channel is on a remote GC node VM."""
        return self.hardware_source == HardwareSource.GC_NODE

    @property
    def is_remote_node(self) -> bool:
        """True if this channel is on any remote node (cRIO, Opto22, or GC)."""
        return self.hardware_source in (HardwareSource.CRIO, HardwareSource.OPTO22, HardwareSource.GC_NODE)

    @property
    def is_local_daq(self) -> bool:
        """True if this channel is on local NI-DAQmx hardware (cDAQ/PXI/USB)."""
        return self.hardware_source == HardwareSource.LOCAL_DAQ

    @property
    def is_modbus(self) -> bool:
        """True if this channel is a Modbus device."""
        return self.hardware_source in (HardwareSource.MODBUS_TCP, HardwareSource.MODBUS_RTU)

    @property
    def is_virtual(self) -> bool:
        """True if this channel is a computed/virtual channel."""
        return self.hardware_source == HardwareSource.VIRTUAL

    @property
    def safety_can_run_locally(self) -> bool:
        """
        True if safety logic for this channel can run independent of PC.

        cRIO and Opto22 channels have true local safety - hardware watchdog
        continues even if PC crashes or network disconnects.
        """
        return self.is_crio or self.is_opto22

    @property
    def hardware_source_display(self) -> str:
        """Human-readable hardware source for UI display."""
        source = self.hardware_source
        if source == HardwareSource.CRIO:
            node = self.source_node_id or "cRIO"
            return f"cRIO ({node})"
        elif source == HardwareSource.LOCAL_DAQ:
            # Extract chassis name from physical_channel
            phys = self.physical_channel
            if "/" in phys:
                chassis = phys.split("/")[0]
                return f"Local DAQ ({chassis})"
            return "Local DAQ"
        elif source == HardwareSource.MODBUS_TCP:
            return "Modbus TCP"
        elif source == HardwareSource.MODBUS_RTU:
            return "Modbus RTU"
        elif source == HardwareSource.VIRTUAL:
            return "Virtual"
        return "Unknown"

@dataclass
class SafetyActionConfig:
    name: str
    description: str = ""
    actions: Dict[str, Any] = field(default_factory=dict)
    trigger_alarm: bool = False
    alarm_message: str = ""

@dataclass
class NISystemConfig:
    system: SystemConfig
    dataviewer: DataViewerConfig
    chassis: Dict[str, ChassisConfig]
    modules: Dict[str, ModuleConfig]
    channels: Dict[str, ChannelConfig]
    safety_actions: Dict[str, SafetyActionConfig]

class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed with {len(errors)} error(s):\n" + "\n".join(f"  - {e}" for e in errors))

@dataclass
class ValidationResult:
    """Result of configuration validation"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

def parse_bool(value: str) -> bool:
    """Parse boolean from string"""
    return value.lower() in ('true', 'yes', '1', 'on')

def parse_actions(actions_str: str) -> Dict[str, Any]:
    """Parse safety actions string like 'channel1:false, channel2:true'"""
    actions = {}
    if not actions_str:
        return actions

    for action in actions_str.split(','):
        action = action.strip()
        if ':' in action:
            channel, value = action.split(':', 1)
            channel = channel.strip()
            value = value.strip()

            # Try to parse as bool, then float, then string
            if value.lower() in ('true', 'false'):
                actions[channel] = parse_bool(value)
            else:
                try:
                    actions[channel] = float(value)
                except ValueError:
                    actions[channel] = value

    return actions

def _get_system_ini_path(config_path: str) -> Path:
    """Get the path to system.ini based on the config file location"""
    config_dir = Path(config_path).resolve().parent
    # If config is in a subdirectory of config/, go up to config/
    if config_dir.name != 'config':
        config_dir = config_dir.parent
    return config_dir / 'system.ini'

def load_config(config_path: str) -> NISystemConfig:
    """Load and parse the INI configuration file

    System settings (MQTT, logging, etc.) are always read from config/system.ini
    Channel definitions are read from the specified config file.
    """

    # Use RawConfigParser to avoid interpolation issues with % characters
    parser = configparser.RawConfigParser()

    # First, load system.ini for system-wide settings
    system_ini_path = _get_system_ini_path(config_path)
    if system_ini_path.exists():
        parser.read(system_ini_path)
        logger.info(f"Loaded system settings from {system_ini_path}")
    else:
        logger.warning(f"system.ini not found at {system_ini_path}, using defaults")

    # Then load the project-specific config (channels, etc.)
    project_parser = configparser.RawConfigParser()
    project_parser.read(config_path)

    # Merge project config into parser (skip [system] - always use system.ini)
    for section in project_parser.sections():
        if section == 'system':
            logger.debug(f"Ignoring [system] section in {config_path} - using system.ini")
            continue
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in project_parser.items(section):
            parser.set(section, key, value)

    # Parse system config (from system.ini)
    system = SystemConfig()
    if 'system' in parser:
        sys_section = parser['system']
        system.mqtt_broker = sys_section.get('mqtt_broker', system.mqtt_broker)
        system.mqtt_port = int(sys_section.get('mqtt_port', system.mqtt_port))
        system.mqtt_base_topic = sys_section.get('mqtt_base_topic', system.mqtt_base_topic)

        # Parse scan/publish rates (reasonable limits: scan up to 100Hz, publish up to 10Hz)
        scan_rate = float(sys_section.get('scan_rate_hz', system.scan_rate_hz))
        publish_rate = float(sys_section.get('publish_rate_hz', system.publish_rate_hz))
        system.scan_rate_hz = min(scan_rate, 100.0)  # Cap at 100Hz
        system.publish_rate_hz = min(publish_rate, 10.0)  # Cap at 10Hz
        if scan_rate > 100.0 or publish_rate > 10.0:
            logger.warning(f"Scan/publish rates capped (requested: scan={scan_rate}Hz, publish={publish_rate}Hz)")

        system.simulation_mode = parse_bool(sys_section.get('simulation_mode', 'true'))
        system.log_directory = sys_section.get('log_directory', system.log_directory)
        system.config_reload_topic = sys_section.get('config_reload_topic', system.config_reload_topic)
        # Multi-node support
        system.node_id = sys_section.get('node_id', system.node_id)
        system.node_name = sys_section.get('node_name', system.node_name)
        # Default project
        system.default_project = sys_section.get('default_project', system.default_project)
        # Project mode (cdaq = PC is PLC, crio = cRIO is PLC)
        mode_str = sys_section.get('project_mode', 'cdaq').lower()
        try:
            system.project_mode = ProjectMode(mode_str)
        except ValueError:
            logger.warning(f"Unknown project_mode '{mode_str}', defaulting to 'cdaq'")
            system.project_mode = ProjectMode.CDAQ

    # Parse logging config (from system.ini [logging] section) into SystemConfig
    if 'logging' in parser:
        log_section = parser['logging']
        system.log_level = log_section.get('level', system.log_level).upper()
        system.log_max_file_size_mb = int(log_section.get('max_file_size_mb', system.log_max_file_size_mb))
        system.log_backup_count = int(log_section.get('backup_count', system.log_backup_count))

    # Parse service config (from system.ini [service] section) into SystemConfig
    if 'service' in parser:
        svc_section = parser['service']
        system.service_heartbeat_interval_sec = float(svc_section.get('heartbeat_interval_sec', system.service_heartbeat_interval_sec))
        system.service_health_timeout_sec = float(svc_section.get('health_timeout_sec', system.service_health_timeout_sec))
        system.service_shutdown_timeout_sec = float(svc_section.get('shutdown_timeout_sec', system.service_shutdown_timeout_sec))
        system.service_command_ack_timeout_sec = float(svc_section.get('command_ack_timeout_sec', system.service_command_ack_timeout_sec))

    # Parse dataviewer config (from system.ini [dataviewer] section)
    dataviewer = DataViewerConfig()
    if 'dataviewer' in parser:
        dv_section = parser['dataviewer']
        dataviewer.retention_days = int(dv_section.get('retention_days', dataviewer.retention_days))
        system.dataviewer_retention_days = dataviewer.retention_days

    # Parse chassis configs
    chassis = {}
    for section in parser.sections():
        if section.startswith('chassis:'):
            name = section.split(':', 1)[1]
            sec = parser[section]
            chassis[name] = ChassisConfig(
                name=name,
                chassis_type=sec.get('type', ''),
                serial=sec.get('serial', ''),
                connection=sec.get('connection', 'USB'),
                ip_address=sec.get('ip_address', ''),
                description=sec.get('description', ''),
                enabled=parse_bool(sec.get('enabled', 'true')),
                device_name=sec.get('device_name', ''),
                # Modbus TCP
                modbus_port=int(sec.get('modbus_port', sec.get('port', 502))),
                # Modbus RTU
                modbus_baudrate=int(sec.get('modbus_baudrate', sec.get('baudrate', 9600))),
                modbus_parity=sec.get('modbus_parity', sec.get('parity', 'E')),
                modbus_stopbits=int(sec.get('modbus_stopbits', sec.get('stopbits', 1))),
                modbus_bytesize=int(sec.get('modbus_bytesize', sec.get('bytesize', 8))),
                # Modbus common
                modbus_timeout=float(sec.get('modbus_timeout', sec.get('timeout', 1.0))),
                modbus_retries=int(sec.get('modbus_retries', sec.get('retries', 3)))
            )

    # Parse module configs
    modules = {}
    for section in parser.sections():
        if section.startswith('module:'):
            name = section.split(':', 1)[1]
            sec = parser[section]
            modules[name] = ModuleConfig(
                name=name,
                module_type=sec.get('type', ''),
                chassis=sec.get('chassis', ''),
                slot=int(sec.get('slot', 1)),
                description=sec.get('description', ''),
                enabled=parse_bool(sec.get('enabled', 'true'))
            )

    # Parse channel configs
    channels = {}
    for section in parser.sections():
        if section.startswith('channel:'):
            name = section.split(':', 1)[1]
            sec = parser[section]

            channel_type = ChannelType(sec.get('channel_type', 'voltage'))

            tc_type = None
            if 'thermocouple_type' in sec:
                tc_type = ThermocoupleType(sec['thermocouple_type'])

            channels[name] = ChannelConfig(
                name=name,
                module=sec.get('module', ''),
                physical_channel=sec.get('physical_channel', ''),
                channel_type=channel_type,
                description=sec.get('description', ''),
                units=sec.get('units', ''),
                visible=parse_bool(sec.get('visible', 'true')),
                group=sec.get('group', ''),
                scale_slope=float(sec.get('scale_slope', 1.0)),
                scale_offset=float(sec.get('scale_offset', 0.0)),
                scale_type=sec.get('scale_type', 'none'),
                four_twenty_scaling=parse_bool(sec.get('four_twenty_scaling', 'false')),
                eng_units_min=float(sec['eng_units_min']) if 'eng_units_min' in sec else None,
                eng_units_max=float(sec['eng_units_max']) if 'eng_units_max' in sec else None,
                pre_scaled_min=float(sec['pre_scaled_min']) if 'pre_scaled_min' in sec else None,
                pre_scaled_max=float(sec['pre_scaled_max']) if 'pre_scaled_max' in sec else None,
                scaled_min=float(sec['scaled_min']) if 'scaled_min' in sec else None,
                scaled_max=float(sec['scaled_max']) if 'scaled_max' in sec else None,
                voltage_range=float(sec.get('voltage_range', 10.0)),
                current_range_ma=float(sec.get('current_range_ma', 20.0)),
                terminal_config=sec.get('terminal_config', 'DEFAULT'),
                thermocouple_type=tc_type,
                cjc_source=sec.get('cjc_source', 'internal'),
                # RTD
                rtd_type=sec.get('rtd_type', 'Pt100'),
                rtd_resistance=float(sec.get('rtd_resistance', 100.0)),
                rtd_wiring=sec.get('rtd_wiring', '4-wire'),
                rtd_current=float(sec.get('rtd_current', 0.001)),
                # Strain
                strain_config=sec.get('strain_config', 'full-bridge'),
                strain_excitation_voltage=float(sec.get('strain_excitation_voltage', 2.5)),
                strain_gage_factor=float(sec.get('strain_gage_factor', 2.0)),
                strain_resistance=float(sec.get('strain_resistance', 350.0)),
                # IEPE
                iepe_sensitivity=float(sec.get('iepe_sensitivity', 100.0)),
                iepe_current=float(sec.get('iepe_current', 0.004)),
                iepe_coupling=sec.get('iepe_coupling', 'AC'),
                # Resistance
                resistance_range=float(sec.get('resistance_range', 1000.0)),
                resistance_wiring=sec.get('resistance_wiring', '4-wire'),
                counter_mode={'count_edges': 'count', 'edge_count': 'count'}.get(
                    sec.get('counter_mode', 'frequency'), sec.get('counter_mode', 'frequency')),
                pulses_per_unit=float(sec.get('pulses_per_unit', 1.0)),
                counter_edge=sec.get('counter_edge', 'rising'),
                counter_reset_on_read=parse_bool(sec.get('counter_reset_on_read', 'false')),
                counter_min_freq=float(sec.get('counter_min_freq', 0.1)),
                counter_max_freq=float(sec.get('counter_max_freq', 1000.0)),
                # Pulse/Counter output
                pulse_frequency=float(sec.get('pulse_frequency', 1000.0)),
                pulse_duty_cycle=float(sec.get('pulse_duty_cycle', 50.0)),
                pulse_idle_state=sec.get('pulse_idle_state', 'LOW'),
                # Relay
                relay_type=sec.get('relay_type', 'none'),
                momentary_pulse_ms=int(sec.get('momentary_pulse_ms', 0)),
                # Modbus
                modbus_register_type=sec.get('modbus_register_type', 'holding'),
                modbus_address=int(sec.get('modbus_address', 0)),
                modbus_data_type=sec.get('modbus_data_type', 'float32'),
                modbus_byte_order=sec.get('modbus_byte_order', 'big'),
                modbus_word_order=sec.get('modbus_word_order', 'big'),
                modbus_scale=float(sec.get('modbus_scale', 1.0)),
                modbus_offset=float(sec.get('modbus_offset', 0.0)),
                modbus_slave_id=int(sec['modbus_slave_id']) if 'modbus_slave_id' in sec else None,
                modbus_register_count=int(sec['modbus_register_count']) if 'modbus_register_count' in sec else None,
                modbus_register_index=int(sec.get('modbus_register_index', 0)),
                invert=parse_bool(sec.get('invert', 'false')),
                default_state=parse_bool(sec.get('default_state', 'false')),
                default_value=float(sec.get('default_value', 0.0)),
                low_limit=float(sec['low_limit']) if 'low_limit' in sec else None,
                high_limit=float(sec['high_limit']) if 'high_limit' in sec else None,
                low_warning=float(sec['low_warning']) if 'low_warning' in sec else None,
                high_warning=float(sec['high_warning']) if 'high_warning' in sec else None,
                safety_action=sec.get('safety_action'),
                safety_interlock=sec.get('safety_interlock'),
                log=parse_bool(sec.get('log', 'true')),
                log_interval_ms=int(sec.get('log_interval_ms', 1000)),
                # Multi-node / cRIO support
                source_type=sec.get('source_type', 'local'),
                source_node_id=sec.get('source_node_id', sec.get('node_id', ''))
            )

    # Parse safety actions
    safety_actions = {}
    for section in parser.sections():
        if section.startswith('safety_action:'):
            name = section.split(':', 1)[1]
            sec = parser[section]
            safety_actions[name] = SafetyActionConfig(
                name=name,
                description=sec.get('description', ''),
                actions=parse_actions(sec.get('actions', '')),
                trigger_alarm=parse_bool(sec.get('trigger_alarm', 'false')),
                alarm_message=sec.get('alarm_message', '')
            )

    return NISystemConfig(
        system=system,
        dataviewer=dataviewer,
        chassis=chassis,
        modules=modules,
        channels=channels,
        safety_actions=safety_actions
    )

def get_channels_by_module(config: NISystemConfig, module_name: str) -> List[ChannelConfig]:
    """Get all channels belonging to a specific module"""
    return [ch for ch in config.channels.values() if ch.module == module_name]

def get_channels_by_type(config: NISystemConfig, channel_type: ChannelType) -> List[ChannelConfig]:
    """Get all channels of a specific type"""
    return [ch for ch in config.channels.values() if ch.channel_type == channel_type]

def get_input_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all input channels (AI, DI, thermocouple, current, RTD, etc.)"""
    input_types = [
        ChannelType.THERMOCOUPLE,
        ChannelType.VOLTAGE_INPUT,
        ChannelType.CURRENT_INPUT,
        ChannelType.RTD,
        ChannelType.STRAIN, ChannelType.STRAIN_INPUT, ChannelType.BRIDGE_INPUT,
        ChannelType.IEPE, ChannelType.IEPE_INPUT,
        ChannelType.RESISTANCE, ChannelType.RESISTANCE_INPUT,
        ChannelType.COUNTER, ChannelType.COUNTER_INPUT, ChannelType.FREQUENCY_INPUT,
        ChannelType.DIGITAL_INPUT,
        ChannelType.MODBUS_REGISTER,
        ChannelType.MODBUS_COIL,
    ]
    return [ch for ch in config.channels.values() if ch.channel_type in input_types]

def get_output_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all output channels (voltage/current outputs, digital outputs)"""
    output_types = [
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.VOLTAGE_OUTPUT,
        ChannelType.CURRENT_OUTPUT,
        ChannelType.COUNTER_OUTPUT,
        ChannelType.PULSE_OUTPUT,
    ]
    return [ch for ch in config.channels.values() if ch.channel_type in output_types]

# =============================================================================
# Hardware Source Helper Functions
# =============================================================================

def get_channels_by_hardware_source(config: NISystemConfig, source: HardwareSource) -> List[ChannelConfig]:
    """Get all channels from a specific hardware source."""
    return [ch for ch in config.channels.values() if ch.hardware_source == source]

def get_crio_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all channels that are on remote cRIO controllers."""
    return [ch for ch in config.channels.values() if ch.is_crio]

def get_local_daq_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all channels that are on local NI-DAQmx hardware (cDAQ/PXI/USB)."""
    return [ch for ch in config.channels.values() if ch.is_local_daq]

def get_modbus_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all Modbus channels (TCP and RTU)."""
    return [ch for ch in config.channels.values() if ch.is_modbus]

def get_safety_critical_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """
    Get channels where safety logic can run independently of PC.

    Only cRIO channels qualify - they have hardware watchdog that continues
    operating even if PC crashes or network disconnects.
    """
    return [ch for ch in config.channels.values() if ch.safety_can_run_locally]

def get_hardware_source_summary(config: NISystemConfig) -> Dict[str, int]:
    """
    Get a summary of channels by hardware source.

    Returns:
        Dict mapping source name to channel count, e.g.:
        {'local_daq': 12, 'crio': 8, 'modbus_tcp': 2}
    """
    summary: Dict[str, int] = {}
    for ch in config.channels.values():
        source = ch.hardware_source.value
        summary[source] = summary.get(source, 0) + 1
    return summary

def validate_config(config: NISystemConfig, strict: bool = True) -> ValidationResult:
    """
    Validate configuration for consistency and safety.

    Args:
        config: The loaded configuration to validate
        strict: If True, treats safety-related issues as errors (raises exception).
                If False, returns warnings instead.

    Returns:
        ValidationResult with errors and warnings

    Raises:
        ConfigValidationError: If strict=True and critical errors found
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Validate module references to chassis
    for module_name, module in config.modules.items():
        if module.chassis and module.chassis not in config.chassis:
            errors.append(f"Module '{module_name}' references non-existent chassis '{module.chassis}'")

    # 2. Validate channel references to modules
    # Skip validation for channels with direct physical paths (contain '/')
    for channel_name, channel in config.channels.items():
        if channel.module and channel.module not in config.modules:
            # Check if channel uses direct path - if so, module reference is not needed
            if '/' not in channel.physical_channel:
                errors.append(f"Channel '{channel_name}' references non-existent module '{channel.module}'")

    # 3. CRITICAL: Validate safety action references from channels
    for channel_name, channel in config.channels.items():
        if channel.safety_action:
            if channel.safety_action not in config.safety_actions:
                errors.append(
                    f"SAFETY CRITICAL: Channel '{channel_name}' references non-existent "
                    f"safety_action '{channel.safety_action}' - safety trigger will fail silently!"
                )

    # 4. CRITICAL: Validate channels referenced in safety actions exist
    for action_name, action in config.safety_actions.items():
        for target_channel in action.actions.keys():
            if target_channel not in config.channels:
                errors.append(
                    f"SAFETY CRITICAL: Safety action '{action_name}' targets non-existent "
                    f"channel '{target_channel}' - emergency shutdown will be incomplete!"
                )
            else:
                # Verify target is an output channel
                target = config.channels[target_channel]
                output_types = (ChannelType.DIGITAL_OUTPUT, ChannelType.VOLTAGE_OUTPUT, ChannelType.CURRENT_OUTPUT)
                if target.channel_type not in output_types:
                    errors.append(
                        f"SAFETY CRITICAL: Safety action '{action_name}' targets input channel "
                        f"'{target_channel}' (type={target.channel_type.value}) - cannot write to inputs!"
                    )

    # 5. Validate safety interlocks reference valid channels
    for channel_name, channel in config.channels.items():
        if channel.safety_interlock:
            # Extract channel names from interlock expression
            # Simple parsing - look for words that might be channel names
            interlock_expr = channel.safety_interlock
            for potential_channel in config.channels.keys():
                if potential_channel in interlock_expr:
                    # Channel is referenced - that's fine
                    pass
            # Check for obvious issues
            if '==' not in interlock_expr and '>' not in interlock_expr and '<' not in interlock_expr:
                warnings.append(
                    f"Channel '{channel_name}' has safety_interlock '{channel.safety_interlock}' "
                    f"which may be malformed (no comparison operators found)"
                )

    # 6. Validate limits are sensible
    for channel_name, channel in config.channels.items():
        if channel.low_limit is not None and channel.high_limit is not None:
            if channel.low_limit >= channel.high_limit:
                errors.append(
                    f"Channel '{channel_name}': low_limit ({channel.low_limit}) >= high_limit ({channel.high_limit})"
                )
        if channel.low_warning is not None and channel.high_warning is not None:
            if channel.low_warning >= channel.high_warning:
                warnings.append(
                    f"Channel '{channel_name}': low_warning ({channel.low_warning}) >= high_warning ({channel.high_warning})"
                )
        # Warning limits should be inside alarm limits
        if channel.low_limit is not None and channel.low_warning is not None:
            if channel.low_warning < channel.low_limit:
                warnings.append(
                    f"Channel '{channel_name}': low_warning ({channel.low_warning}) < low_limit ({channel.low_limit})"
                )
        if channel.high_limit is not None and channel.high_warning is not None:
            if channel.high_warning > channel.high_limit:
                warnings.append(
                    f"Channel '{channel_name}': high_warning ({channel.high_warning}) > high_limit ({channel.high_limit})"
                )

    # 7. Validate 4-20mA scaling has required parameters
    for channel_name, channel in config.channels.items():
        if channel.four_twenty_scaling:
            if channel.eng_units_min is None or channel.eng_units_max is None:
                errors.append(
                    f"Channel '{channel_name}': four_twenty_scaling enabled but eng_units_min/max not set"
                )
            elif channel.eng_units_min == channel.eng_units_max:
                errors.append(
                    f"Channel '{channel_name}': eng_units_min == eng_units_max (would cause division by zero)"
                )

    # 8. Validate map scaling has required parameters
    for channel_name, channel in config.channels.items():
        if channel.scale_type == 'map':
            missing = []
            if channel.pre_scaled_min is None:
                missing.append('pre_scaled_min')
            if channel.pre_scaled_max is None:
                missing.append('pre_scaled_max')
            if channel.scaled_min is None:
                missing.append('scaled_min')
            if channel.scaled_max is None:
                missing.append('scaled_max')
            if missing:
                errors.append(
                    f"Channel '{channel_name}': scale_type='map' but missing: {', '.join(missing)}"
                )

    # 9. Validate channels have safety action if they have limits (warning only)
    for channel_name, channel in config.channels.items():
        has_limits = channel.low_limit is not None or channel.high_limit is not None
        if has_limits and not channel.safety_action:
            warnings.append(
                f"Channel '{channel_name}' has limits but no safety_action configured"
            )

    # 10. Check for empty safety actions
    for action_name, action in config.safety_actions.items():
        if not action.actions:
            warnings.append(
                f"Safety action '{action_name}' has no actions defined"
            )

    # Build result
    result = ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )

    # Log all issues
    for warning in warnings:
        logger.warning(f"Config validation: {warning}")
    for error in errors:
        logger.error(f"Config validation: {error}")

    # In strict mode, raise exception for critical errors
    if strict and errors:
        raise ConfigValidationError(errors)

    return result

def load_config_safe(config_path: str, strict: bool = True) -> Tuple[NISystemConfig, ValidationResult]:
    """
    Load and validate configuration file.

    Args:
        config_path: Path to INI file
        strict: If True, raises exception on critical errors

    Returns:
        Tuple of (config, validation_result)

    Raises:
        FileNotFoundError: If config file doesn't exist
        ConfigValidationError: If strict=True and validation fails
    """
    # Check file exists
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    if not path.is_file():
        raise ValueError(f"Configuration path is not a file: {config_path}")

    # Load config
    config = load_config(config_path)

    # Validate
    result = validate_config(config, strict=strict)

    return config, result

if __name__ == "__main__":
    # Test loading the config
    config_path = Path(__file__).parent.parent.parent / "config" / "system.ini"

    try:
        config, validation = load_config_safe(str(config_path), strict=False)

        print(f"System Config:")
        print(f"  MQTT Broker: {config.system.mqtt_broker}:{config.system.mqtt_port}")
        print(f"  Simulation Mode: {config.system.simulation_mode}")
        print(f"  Scan Rate: {config.system.scan_rate_hz} Hz")

        print(f"\nChassis ({len(config.chassis)}):")
        for name, chassis in config.chassis.items():
            print(f"  {name}: {chassis.chassis_type}")

        print(f"\nModules ({len(config.modules)}):")
        for name, module in config.modules.items():
            print(f"  {name}: {module.module_type} in slot {module.slot}")

        print(f"\nChannels ({len(config.channels)}):")
        for name, channel in config.channels.items():
            print(f"  {name}: {channel.channel_type.value} ({channel.description})")

        print(f"\nSafety Actions ({len(config.safety_actions)}):")
        for name, action in config.safety_actions.items():
            print(f"  {name}: {action.description}")

        print(f"\n=== Validation Results ===")
        print(f"Valid: {validation.valid}")
        if validation.warnings:
            print(f"\nWarnings ({len(validation.warnings)}):")
            for w in validation.warnings:
                print(f"  ⚠ {w}")
        if validation.errors:
            print(f"\nErrors ({len(validation.errors)}):")
            for e in validation.errors:
                print(f"  ✗ {e}")

    except ConfigValidationError as e:
        print(f"Configuration validation failed!")
        for err in e.errors:
            print(f"  ✗ {err}")
    except FileNotFoundError as e:
        print(f"File not found: {e}")
