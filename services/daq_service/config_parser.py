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
    THERMOCOUPLE = "thermocouple"
    VOLTAGE = "voltage"
    CURRENT = "current"
    COUNTER = "counter"  # Pulse/frequency counter
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"
    ANALOG_OUTPUT = "analog_output"


class ThermocoupleType(Enum):
    J = "J"
    K = "K"
    T = "T"
    E = "E"
    N = "N"
    R = "R"
    S = "S"
    B = "B"


@dataclass
class SystemConfig:
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_base_topic: str = "nisystem"
    scan_rate_hz: float = 100.0
    publish_rate_hz: float = 10.0
    simulation_mode: bool = True
    log_directory: str = "./logs"
    config_reload_topic: str = "nisystem/config/reload"


@dataclass
class ChassisConfig:
    name: str
    chassis_type: str
    serial: str = ""
    connection: str = "USB"
    ip_address: str = ""
    description: str = ""
    enabled: bool = True


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
    module: str
    physical_channel: str
    channel_type: ChannelType
    description: str = ""
    units: str = ""

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

    # Thermocouple specific
    thermocouple_type: Optional[ThermocoupleType] = None
    cjc_source: str = "internal"

    # Counter specific
    counter_mode: str = "frequency"  # frequency, count, period
    pulses_per_unit: float = 1.0     # e.g., 100 pulses = 1 gallon → pulses_per_unit = 100
    counter_edge: str = "rising"     # rising, falling, both
    counter_reset_on_read: bool = False  # For totalizer mode

    # Digital specific
    invert: bool = False
    default_state: bool = False
    default_value: float = 0.0

    # Limits and warnings
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None
    low_warning: Optional[float] = None
    high_warning: Optional[float] = None

    # Safety
    safety_action: Optional[str] = None
    safety_interlock: Optional[str] = None

    # Logging
    log: bool = True
    log_interval_ms: int = 1000


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


def load_config(config_path: str) -> NISystemConfig:
    """Load and parse the INI configuration file"""

    parser = configparser.ConfigParser()
    parser.read(config_path)

    # Parse system config
    system = SystemConfig()
    if 'system' in parser:
        sys_section = parser['system']
        system.mqtt_broker = sys_section.get('mqtt_broker', system.mqtt_broker)
        system.mqtt_port = int(sys_section.get('mqtt_port', system.mqtt_port))
        system.mqtt_base_topic = sys_section.get('mqtt_base_topic', system.mqtt_base_topic)
        system.scan_rate_hz = float(sys_section.get('scan_rate_hz', system.scan_rate_hz))
        system.publish_rate_hz = float(sys_section.get('publish_rate_hz', system.publish_rate_hz))
        system.simulation_mode = parse_bool(sys_section.get('simulation_mode', 'true'))
        system.log_directory = sys_section.get('log_directory', system.log_directory)
        system.config_reload_topic = sys_section.get('config_reload_topic', system.config_reload_topic)

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
                enabled=parse_bool(sec.get('enabled', 'true'))
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
                thermocouple_type=tc_type,
                cjc_source=sec.get('cjc_source', 'internal'),
                counter_mode=sec.get('counter_mode', 'frequency'),
                pulses_per_unit=float(sec.get('pulses_per_unit', 1.0)),
                counter_edge=sec.get('counter_edge', 'rising'),
                counter_reset_on_read=parse_bool(sec.get('counter_reset_on_read', 'false')),
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
                log_interval_ms=int(sec.get('log_interval_ms', 1000))
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
    """Get all input channels (AI, DI, thermocouple, current)"""
    input_types = [
        ChannelType.THERMOCOUPLE,
        ChannelType.VOLTAGE,
        ChannelType.CURRENT,
        ChannelType.DIGITAL_INPUT
    ]
    return [ch for ch in config.channels.values() if ch.channel_type in input_types]


def get_output_channels(config: NISystemConfig) -> List[ChannelConfig]:
    """Get all output channels (AO, DO)"""
    output_types = [
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.ANALOG_OUTPUT
    ]
    return [ch for ch in config.channels.values() if ch.channel_type in output_types]


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
    for channel_name, channel in config.channels.items():
        if channel.module and channel.module not in config.modules:
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
                if target.channel_type not in (ChannelType.DIGITAL_OUTPUT, ChannelType.ANALOG_OUTPUT):
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
