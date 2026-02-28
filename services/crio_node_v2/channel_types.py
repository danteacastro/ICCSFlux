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
            cls.FREQUENCY_INPUT.value: 'frequency_input',
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
    '9201': ChannelType.VOLTAGE_INPUT,   # 8-Ch ±10V, 12-bit, 500 kS/s aggregate
    '9202': ChannelType.VOLTAGE_INPUT,   # 16-Ch ±10V, 24-bit, simultaneous
    '9204': ChannelType.VOLTAGE_INPUT,   # 16 SE / 8 DIFF, ±0.2V to ±10V, 16-bit, programmable gain
    '9205': ChannelType.VOLTAGE_INPUT,   # 32 SE / 16 DIFF, ±0.2V to ±10V, 16-bit
    '9206': ChannelType.VOLTAGE_INPUT,   # 16 DIFF, ±0.2V to ±10V, 16-bit, high isolation
    '9209': ChannelType.VOLTAGE_INPUT,   # 16 DIFF / 32 SE, ±10V, 24-bit, 500 S/s
    '9215': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±10V, 16-bit, simultaneous
    '9220': ChannelType.VOLTAGE_INPUT,   # 16-Ch ±10V, 16-bit, simultaneous
    '9221': ChannelType.VOLTAGE_INPUT,   # 8-Ch ±60V, 12-bit
    '9222': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±10V, 16-bit, 500 kS/s simultaneous
    '9223': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±10V, 16-bit, 1 MS/s simultaneous
    '9224': ChannelType.VOLTAGE_INPUT,   # 8-Ch ±10.5V, 16-bit
    '9225': ChannelType.VOLTAGE_INPUT,   # 3-Ch 300 Vrms, 24-bit (high-voltage power)
    '9228': ChannelType.VOLTAGE_INPUT,   # 8-Ch ±60V, 24-bit
    '9229': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±60V, 24-bit, isolated simultaneous
    '9238': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±0.5V, 24-bit (low-voltage precision)
    '9239': ChannelType.VOLTAGE_INPUT,   # 4-Ch ±10V, 24-bit, simultaneous
    '9242': ChannelType.VOLTAGE_INPUT,   # 3-Ch 250 Vrms L-N, 24-bit (3-phase power)
    '9244': ChannelType.VOLTAGE_INPUT,   # 3-Ch 400 Vrms L-N, 24-bit (high-voltage power)
    '9252': ChannelType.VOLTAGE_INPUT,   # 8-Ch voltage digitizer

    # Current input modules
    '9203': ChannelType.CURRENT_INPUT,   # 8-Ch ±20mA, 16-bit
    '9207': ChannelType.VOLTAGE_INPUT,   # Combo: ai0-ai7 voltage, ai8-ai15 current
    '9208': ChannelType.CURRENT_INPUT,   # 16-Ch ±20mA, 24-bit, high-precision
    '9227': ChannelType.CURRENT_INPUT,   # 4-Ch 5 Arms, 24-bit (AC power current)
    '9246': ChannelType.CURRENT_INPUT,   # 3-Ch 20 Arms, 24-bit (3-phase power)
    '9247': ChannelType.CURRENT_INPUT,   # 3-Ch 50 Arms, 24-bit (high-current 3-phase)
    '9253': ChannelType.CURRENT_INPUT,   # 8-Ch ±20mA, 24-bit, simultaneous

    # Thermocouple modules
    '9210': ChannelType.THERMOCOUPLE,    # 4-Ch, Ch-Ch isolated
    '9211': ChannelType.THERMOCOUPLE,    # 4-Ch, shared CJC
    '9212': ChannelType.THERMOCOUPLE,    # 8-Ch, Ch-Ch isolated, simultaneous
    '9213': ChannelType.THERMOCOUPLE,    # 16-Ch, shared CJC (highest density)
    '9214': ChannelType.THERMOCOUPLE,    # 16-Ch, isothermal (highest accuracy)

    # Universal modules (per-channel configurable measurement type)
    '9218': ChannelType.BRIDGE_INPUT,    # 2-Ch universal AI (V, I, bridge, IEPE)
    '9219': ChannelType.BRIDGE_INPUT,    # 4-Ch universal AI (V, I, TC, RTD, R, bridge)

    # RTD modules
    '9216': ChannelType.RTD,             # 8-Ch Pt100, 24-bit
    '9217': ChannelType.RTD,             # 4-Ch Pt100, 24-bit
    '9226': ChannelType.RTD,             # 8-Ch Pt1000, 24-bit

    # IEPE/Accelerometer modules
    '9230': ChannelType.IEPE_INPUT,      # 3-Ch, 24-bit, 12.8 kS/s
    '9231': ChannelType.IEPE_INPUT,      # 8-Ch, 24-bit, 51.2 kS/s
    '9232': ChannelType.IEPE_INPUT,      # 3-Ch, 24-bit, 102.4 kS/s
    '9233': ChannelType.IEPE_INPUT,      # 4-Ch, 24-bit, 50 kS/s
    '9234': ChannelType.IEPE_INPUT,      # 4-Ch, 24-bit, 51.2 kS/s (TEDS)
    '9250': ChannelType.IEPE_INPUT,      # 2-Ch, 24-bit, 102.4 kS/s (sound)
    '9251': ChannelType.IEPE_INPUT,      # 2-Ch, 24-bit, 102.4 kS/s (DSA)

    # Strain/Bridge modules
    '9235': ChannelType.STRAIN_INPUT,    # 8-Ch quarter-bridge, 120 Ω
    '9236': ChannelType.STRAIN_INPUT,    # 8-Ch quarter-bridge, 350 Ω
    '9237': ChannelType.BRIDGE_INPUT,    # 4-Ch full/half/quarter, selectable excitation

    # Voltage output modules
    '9260': ChannelType.VOLTAGE_OUTPUT,  # 2-Ch ±3 Vrms (sound exciter)
    '9262': ChannelType.VOLTAGE_OUTPUT,  # 6-Ch ±10V, 16-bit, 1 MS/s
    '9263': ChannelType.VOLTAGE_OUTPUT,  # 4-Ch ±10V, 16-bit, 100 kS/s
    '9264': ChannelType.VOLTAGE_OUTPUT,  # 16-Ch ±10V, 16-bit, 25 kS/s
    '9269': ChannelType.VOLTAGE_OUTPUT,  # 4-Ch ±10V, 16-bit, Ch-Ch isolated

    # Current output modules
    '9265': ChannelType.CURRENT_OUTPUT,  # 4-Ch 0-20mA, 16-bit
    '9266': ChannelType.CURRENT_OUTPUT,  # 8-Ch 0-20mA, 16-bit

    # Digital input modules
    '9375': ChannelType.DIGITAL_INPUT,   # 16 DI + 16 DO combo, default to input
    '9401': ChannelType.DIGITAL_INPUT,   # 8-Ch bidirectional TTL, 100 ns
    '9402': ChannelType.DIGITAL_INPUT,   # 4-Ch bidirectional LVTTL, BNC, 55 ns
    '9403': ChannelType.DIGITAL_INPUT,   # 32-Ch bidirectional TTL
    '9411': ChannelType.DIGITAL_INPUT,   # 6-Ch differential DI, 500 ns
    '9421': ChannelType.DIGITAL_INPUT,   # 8-Ch 24V sinking, 100 µs
    '9422': ChannelType.DIGITAL_INPUT,   # 8-Ch 24V/48V/60V, Ch-Ch isolated
    '9423': ChannelType.DIGITAL_INPUT,   # 8-Ch 24V, 1 µs (high-speed)
    '9425': ChannelType.DIGITAL_INPUT,   # 32-Ch 24V sinking
    '9426': ChannelType.DIGITAL_INPUT,   # 32-Ch 24V sourcing
    '9435': ChannelType.DIGITAL_INPUT,   # 4-Ch universal (5-250 VDC/VAC), Ch-Ch isolated
    '9436': ChannelType.DIGITAL_INPUT,   # 8-Ch 12-24V, 1 µs (high-speed industrial)
    '9437': ChannelType.DIGITAL_INPUT,   # 8-Ch 250 VDC/VAC (high-voltage universal)

    # Digital output modules
    '9470': ChannelType.DIGITAL_OUTPUT,  # 8-Ch 6-30V sourcing
    '9472': ChannelType.DIGITAL_OUTPUT,  # 8-Ch 6-30V sourcing, 100 µs
    '9474': ChannelType.DIGITAL_OUTPUT,  # 8-Ch 5-30V sourcing, 1 µs (high-speed)
    '9475': ChannelType.DIGITAL_OUTPUT,  # 8-Ch 5-60V sourcing
    '9476': ChannelType.DIGITAL_OUTPUT,  # 32-Ch 6-36V sourcing
    '9477': ChannelType.DIGITAL_OUTPUT,  # 32-Ch 5-60V sinking
    '9478': ChannelType.DIGITAL_OUTPUT,  # 16-Ch 5-50V sinking
    '9481': ChannelType.DIGITAL_OUTPUT,  # 4-Ch SPST relay
    '9482': ChannelType.DIGITAL_OUTPUT,  # 4-Ch SPDT relay
    '9485': ChannelType.DIGITAL_OUTPUT,  # 8-Ch SSR

    # Counter modules
    '9361': ChannelType.COUNTER_INPUT,   # 8-Ch counter/DI, 32-bit, 1 MHz
}

# Combo modules where channel type varies by channel index within the same module
# Key: module number, Value: (alt_type, index_start) — channels at index >= index_start use alt_type
COMBO_MODULE_MAP: Dict[str, tuple] = {
    '9207': (ChannelType.CURRENT_INPUT, 8),  # ai0-ai7 = voltage, ai8-ai15 = current
}


def get_combo_channel_type(model_number: str, channel_index: int) -> Optional[ChannelType]:
    """
    For combo modules (e.g., NI 9207), get the channel type based on channel index.

    Returns the alternate type if the channel index is at or above the split point,
    or None if this is not a combo module.
    """
    clean_number = ''.join(c for c in model_number if c.isdigit())
    combo = COMBO_MODULE_MAP.get(clean_number)
    if combo is None:
        return None
    alt_type, index_start = combo
    if channel_index >= index_start:
        return alt_type
    return None


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
