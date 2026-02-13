"""
Channel type definitions for Opto22 Node.

Matches the cRIO channel type system for consistency across
NISystem edge nodes.
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
    RESISTANCE_INPUT = "resistance_input"

    # Analog Outputs
    VOLTAGE_OUTPUT = "voltage_output"
    CURRENT_OUTPUT = "current_output"

    # Digital
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"

    # Counter/Timer
    COUNTER_INPUT = "counter_input"
    FREQUENCY_INPUT = "frequency_input"
    PULSE_OUTPUT = "pulse_output"

    @classmethod
    def is_input(cls, channel_type: str) -> bool:
        return channel_type in [
            cls.VOLTAGE_INPUT.value, cls.CURRENT_INPUT.value, cls.THERMOCOUPLE.value,
            cls.RTD.value, cls.STRAIN_INPUT.value, cls.RESISTANCE_INPUT.value,
            cls.DIGITAL_INPUT.value, cls.COUNTER_INPUT.value, cls.FREQUENCY_INPUT.value,
        ]

    @classmethod
    def is_output(cls, channel_type: str) -> bool:
        return channel_type in [
            cls.VOLTAGE_OUTPUT.value, cls.CURRENT_OUTPUT.value,
            cls.DIGITAL_OUTPUT.value, cls.PULSE_OUTPUT.value,
        ]

    @classmethod
    def is_analog(cls, channel_type: str) -> bool:
        return channel_type in [
            cls.VOLTAGE_INPUT.value, cls.CURRENT_INPUT.value, cls.THERMOCOUPLE.value,
            cls.RTD.value, cls.STRAIN_INPUT.value, cls.RESISTANCE_INPUT.value,
            cls.VOLTAGE_OUTPUT.value, cls.CURRENT_OUTPUT.value,
        ]

    @classmethod
    def is_digital(cls, channel_type: str) -> bool:
        return channel_type in [
            cls.DIGITAL_INPUT.value, cls.DIGITAL_OUTPUT.value,
        ]

    @classmethod
    def normalize(cls, type_str: str) -> str:
        """Normalize short-form channel types to explicit forms."""
        aliases = {
            'strain': cls.STRAIN_INPUT.value,
            'resistance': cls.RESISTANCE_INPUT.value,
            'counter': cls.COUNTER_INPUT.value,
        }
        return aliases.get(type_str, type_str)


# Opto22 groov EPIC module database
# Maps Opto22 module part numbers to channel capabilities
OPTO22_MODULES = {
    'GRV-IAC-24': {'type': 'digital_input', 'channels': 4, 'description': 'AC Digital Input'},
    'GRV-IDC-24': {'type': 'digital_input', 'channels': 4, 'description': 'DC Digital Input'},
    'GRV-OAC-12': {'type': 'digital_output', 'channels': 4, 'description': 'AC Digital Output'},
    'GRV-ODC-12': {'type': 'digital_output', 'channels': 4, 'description': 'DC Digital Output'},
    'GRV-ITMI-8': {'type': 'thermocouple', 'channels': 8, 'description': 'Thermocouple Input'},
    'GRV-IMA-8': {'type': 'current_input', 'channels': 8, 'description': '4-20mA Analog Input'},
    'GRV-IVE-8': {'type': 'voltage_input', 'channels': 8, 'description': '0-10V Analog Input'},
    'GRV-OVOE-8': {'type': 'voltage_output', 'channels': 8, 'description': '0-10V Analog Output'},
    'GRV-OMOE-8': {'type': 'current_output', 'channels': 8, 'description': '4-20mA Analog Output'},
    'GRV-IRTD-8': {'type': 'rtd', 'channels': 8, 'description': 'RTD Input'},
    'GRV-CSERI-4': {'type': 'serial', 'channels': 4, 'description': 'Serial Communication'},
}
