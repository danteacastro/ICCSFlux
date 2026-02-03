"""
Canonical channel type definitions for NISystem cRIO Node V2.

All channel types are explicit about direction (input/output).
This module provides the single source of truth for channel type mapping.
"""

from enum import Enum
from typing import Dict, Optional


class ChannelType(str, Enum):
    """All supported channel types."""
    # Analog Inputs
    VOLTAGE_INPUT = "voltage_input"
    CURRENT_INPUT = "current_input"
    THERMOCOUPLE = "thermocouple"
    RTD = "rtd"
    STRAIN_INPUT = "strain_input"
    BRIDGE_INPUT = "bridge_input"
    IEPE_INPUT = "iepe_input"
    RESISTANCE_INPUT = "resistance_input"

    # Analog Outputs
    VOLTAGE_OUTPUT = "voltage_output"
    CURRENT_OUTPUT = "current_output"

    # Digital
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"

    # Counter/Timer
    COUNTER_INPUT = "counter_input"
    COUNTER_OUTPUT = "counter_output"
    FREQUENCY_INPUT = "frequency_input"
    PULSE_OUTPUT = "pulse_output"

    # Modbus (for compatibility)
    MODBUS_REGISTER = "modbus_register"
    MODBUS_COIL = "modbus_coil"

    @classmethod
    def is_input(cls, channel_type: str) -> bool:
        """Check if channel type is an input."""
        return channel_type in [
            cls.VOLTAGE_INPUT.value, cls.CURRENT_INPUT.value, cls.THERMOCOUPLE.value,
            cls.RTD.value, cls.STRAIN_INPUT.value, cls.BRIDGE_INPUT.value,
            cls.IEPE_INPUT.value, cls.RESISTANCE_INPUT.value, cls.DIGITAL_INPUT.value,
            cls.COUNTER_INPUT.value, cls.FREQUENCY_INPUT.value,
            cls.MODBUS_REGISTER.value, cls.MODBUS_COIL.value,
            # Legacy aliases
            'analog_input', 'voltage', 'current', 'strain', 'iepe', 'counter', 'resistance',
        ]

    @classmethod
    def is_output(cls, channel_type: str) -> bool:
        """Check if channel type is an output."""
        return channel_type in [
            cls.VOLTAGE_OUTPUT.value, cls.CURRENT_OUTPUT.value, cls.DIGITAL_OUTPUT.value,
            cls.COUNTER_OUTPUT.value, cls.PULSE_OUTPUT.value,
            # Legacy aliases
            'analog_output',
        ]

    @classmethod
    def is_analog(cls, channel_type: str) -> bool:
        """Check if channel type is analog (vs digital/counter)."""
        return channel_type in [
            cls.VOLTAGE_INPUT.value, cls.CURRENT_INPUT.value, cls.THERMOCOUPLE.value,
            cls.RTD.value, cls.STRAIN_INPUT.value, cls.BRIDGE_INPUT.value,
            cls.IEPE_INPUT.value, cls.RESISTANCE_INPUT.value,
            cls.VOLTAGE_OUTPUT.value, cls.CURRENT_OUTPUT.value,
            # Legacy aliases
            'analog_input', 'analog_output', 'voltage', 'current', 'strain', 'iepe', 'resistance',
        ]

    @classmethod
    def needs_thermocouple_type(cls, channel_type: str) -> bool:
        """Check if channel type needs thermocouple_type field."""
        return channel_type == cls.THERMOCOUPLE.value

    @classmethod
    def get_internal_type(cls, channel_type: str) -> str:
        """
        Map semantic channel type to internal DAQmx task type.

        This allows the hardware layer to group channels correctly for
        NI-DAQmx task creation while config uses semantic types like
        'thermocouple', 'voltage_input', etc.

        Returns one of: 'analog_input', 'analog_output', 'digital_input',
                        'digital_output', 'counter_input', 'counter_output'
        """
        INTERNAL_MAP: Dict[str, str] = {
            # Explicit semantic types -> internal types
            cls.VOLTAGE_INPUT.value: 'analog_input',
            cls.CURRENT_INPUT.value: 'analog_input',
            cls.THERMOCOUPLE.value: 'analog_input',
            cls.RTD.value: 'analog_input',
            cls.STRAIN_INPUT.value: 'analog_input',
            cls.BRIDGE_INPUT.value: 'analog_input',
            cls.IEPE_INPUT.value: 'analog_input',
            cls.RESISTANCE_INPUT.value: 'analog_input',
            cls.VOLTAGE_OUTPUT.value: 'analog_output',
            cls.CURRENT_OUTPUT.value: 'analog_output',
            cls.DIGITAL_INPUT.value: 'digital_input',
            cls.DIGITAL_OUTPUT.value: 'digital_output',
            cls.COUNTER_INPUT.value: 'counter_input',
            cls.COUNTER_OUTPUT.value: 'counter_output',
            cls.FREQUENCY_INPUT.value: 'counter_input',
            cls.PULSE_OUTPUT.value: 'counter_output',

            # Legacy aliases (backwards compatibility)
            'voltage': 'analog_input',
            'current': 'analog_input',
            'strain': 'analog_input',
            'iepe': 'analog_input',
            'resistance': 'analog_input',
            'counter': 'counter_input',
            'analog_input': 'analog_input',
            'analog_output': 'analog_output',
        }
        return INTERNAL_MAP.get(channel_type, channel_type)


# NI C Series module number to default channel type mapping
MODULE_TYPE_MAP: Dict[str, ChannelType] = {
    # Voltage input modules
    '9201': ChannelType.VOLTAGE_INPUT,
    '9202': ChannelType.VOLTAGE_INPUT,
    '9205': ChannelType.VOLTAGE_INPUT,
    '9206': ChannelType.VOLTAGE_INPUT,
    '9215': ChannelType.VOLTAGE_INPUT,
    '9220': ChannelType.VOLTAGE_INPUT,
    '9221': ChannelType.VOLTAGE_INPUT,
    '9222': ChannelType.VOLTAGE_INPUT,
    '9223': ChannelType.VOLTAGE_INPUT,
    '9229': ChannelType.VOLTAGE_INPUT,
    '9239': ChannelType.VOLTAGE_INPUT,

    # Current input modules
    '9203': ChannelType.CURRENT_INPUT,
    '9207': ChannelType.CURRENT_INPUT,  # Combo module, default to current
    '9208': ChannelType.CURRENT_INPUT,
    '9227': ChannelType.CURRENT_INPUT,
    '9246': ChannelType.CURRENT_INPUT,
    '9247': ChannelType.CURRENT_INPUT,
    '9253': ChannelType.CURRENT_INPUT,

    # Thermocouple modules
    '9210': ChannelType.THERMOCOUPLE,
    '9211': ChannelType.THERMOCOUPLE,
    '9212': ChannelType.THERMOCOUPLE,
    '9213': ChannelType.THERMOCOUPLE,
    '9214': ChannelType.THERMOCOUPLE,

    # Universal module (often used for TC)
    '9219': ChannelType.BRIDGE_INPUT,

    # RTD modules
    '9216': ChannelType.RTD,
    '9217': ChannelType.RTD,
    '9226': ChannelType.RTD,

    # IEPE/Accelerometer modules
    '9230': ChannelType.IEPE_INPUT,
    '9231': ChannelType.IEPE_INPUT,
    '9232': ChannelType.IEPE_INPUT,
    '9233': ChannelType.IEPE_INPUT,
    '9234': ChannelType.IEPE_INPUT,
    '9250': ChannelType.IEPE_INPUT,
    '9251': ChannelType.IEPE_INPUT,

    # Strain/Bridge modules
    '9235': ChannelType.STRAIN_INPUT,
    '9236': ChannelType.STRAIN_INPUT,
    '9237': ChannelType.BRIDGE_INPUT,

    # Voltage output modules
    '9260': ChannelType.VOLTAGE_OUTPUT,
    '9262': ChannelType.VOLTAGE_OUTPUT,
    '9263': ChannelType.VOLTAGE_OUTPUT,
    '9264': ChannelType.VOLTAGE_OUTPUT,
    '9269': ChannelType.VOLTAGE_OUTPUT,

    # Current output modules
    '9265': ChannelType.CURRENT_OUTPUT,
    '9266': ChannelType.CURRENT_OUTPUT,

    # Digital input modules
    '9375': ChannelType.DIGITAL_INPUT,  # 16 DI + 16 DO combo, default to input
    '9401': ChannelType.DIGITAL_INPUT,  # Bidirectional, default to input
    '9402': ChannelType.DIGITAL_INPUT,  # Bidirectional, default to input
    '9403': ChannelType.DIGITAL_INPUT,  # Bidirectional, default to input
    '9411': ChannelType.DIGITAL_INPUT,
    '9421': ChannelType.DIGITAL_INPUT,
    '9422': ChannelType.DIGITAL_INPUT,
    '9423': ChannelType.DIGITAL_INPUT,
    '9425': ChannelType.DIGITAL_INPUT,
    '9426': ChannelType.DIGITAL_INPUT,
    '9435': ChannelType.DIGITAL_INPUT,

    # Digital output modules
    '9470': ChannelType.DIGITAL_OUTPUT,
    '9472': ChannelType.DIGITAL_OUTPUT,
    '9474': ChannelType.DIGITAL_OUTPUT,
    '9475': ChannelType.DIGITAL_OUTPUT,
    '9476': ChannelType.DIGITAL_OUTPUT,
    '9477': ChannelType.DIGITAL_OUTPUT,
    '9478': ChannelType.DIGITAL_OUTPUT,
    '9481': ChannelType.DIGITAL_OUTPUT,  # Relay
    '9482': ChannelType.DIGITAL_OUTPUT,  # Relay
    '9485': ChannelType.DIGITAL_OUTPUT,  # SSR

    # Counter modules
    '9361': ChannelType.COUNTER_INPUT,
}

# Relay module subtype metadata (for informational use — these remain DIGITAL_OUTPUT in DAQmx)
RELAY_MODULES: Dict[str, str] = {
    '9481': 'spst',   # 4-Ch SPST (Single Pole Single Throw) Relay
    '9482': 'spdt',   # 4-Ch SPDT (Single Pole Double Throw) Relay
    '9485': 'ssr',    # 8-Ch Solid State Relay
}


def get_relay_type(model_number: str) -> str:
    """Get relay subtype for a module, or 'none' if not a relay module."""
    clean_number = ''.join(c for c in model_number if c.isdigit())
    return RELAY_MODULES.get(clean_number, 'none')




# Absolute hardware limits per NI C Series output module.
# These are physical maxima that CANNOT be overridden by user config.
# Source: NI hardware datasheets.
MODULE_HARDWARE_LIMITS: Dict[str, Dict[str, float]] = {
    # Voltage output modules (all +/-10V max)
    '9260': {'voltage_min': -10.0, 'voltage_max': 10.0},
    '9262': {'voltage_min': -10.0, 'voltage_max': 10.0},
    '9263': {'voltage_min': -10.0, 'voltage_max': 10.0},
    '9264': {'voltage_min': -10.0, 'voltage_max': 10.0},
    '9269': {'voltage_min': -10.0, 'voltage_max': 10.0},
    # Current output modules (0-20mA max)
    '9265': {'current_min_ma': 0.0, 'current_max_ma': 20.0},
    '9266': {'current_min_ma': 0.0, 'current_max_ma': 20.0},
}


def get_module_hardware_limits(model_number: str) -> Optional[Dict[str, float]]:
    """Get absolute hardware limits for an output module.

    Returns None if module is not in the limits database (non-output or unknown).
    These limits represent physical hardware maximums and must not be exceeded.
    """
    clean_number = ''.join(c for c in model_number if c.isdigit())
    return MODULE_HARDWARE_LIMITS.get(clean_number)



def get_module_channel_type(model_number: str) -> ChannelType:
    """
    Get the default channel type for a given NI module model number.

    Args:
        model_number: NI module model (e.g., '9213', 'NI 9213', 'NI-9213')

    Returns:
        ChannelType for the module, or VOLTAGE_INPUT as default
    """
    # Extract just the number part
    clean_number = ''.join(c for c in model_number if c.isdigit())

    return MODULE_TYPE_MAP.get(clean_number, ChannelType.VOLTAGE_INPUT)
