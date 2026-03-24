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

# Opto22 groov EPIC/RIO module database
# Maps real Opto22 GRV-series part numbers to channel capabilities.
# Source: Opto22 groov System Product Guide (Form 2250)
OPTO22_MODULES = {
    # --- AC Discrete Input ---
    'GRV-IAC-24':     {'type': 'digital_input',  'channels': 24, 'description': '24-Ch AC Digital Input (85-140 VAC)'},
    'GRV-IACS-24':    {'type': 'digital_input',  'channels': 24, 'description': '24-Ch AC Digital Input (simplified)'},
    'GRV-IACI-12':    {'type': 'digital_input',  'channels': 12, 'description': '12-Ch AC Digital Input (Ch-Ch isolated)'},
    'GRV-IACIS-12':   {'type': 'digital_input',  'channels': 12, 'description': '12-Ch AC Digital Input (isolated, simplified)'},
    'GRV-IACHV-24':   {'type': 'digital_input',  'channels': 24, 'description': '24-Ch High-Voltage AC Input (180-280 VAC)'},
    'GRV-IACHVS-24':  {'type': 'digital_input',  'channels': 24, 'description': '24-Ch High-Voltage AC Input (simplified)'},
    'GRV-IACIHV-12':  {'type': 'digital_input',  'channels': 12, 'description': '12-Ch High-Voltage AC Input (isolated)'},
    'GRV-IACIHVS-12': {'type': 'digital_input',  'channels': 12, 'description': '12-Ch High-Voltage AC Input (isolated, simplified)'},

    # --- DC Discrete Input ---
    'GRV-IDC-24':       {'type': 'digital_input',  'channels': 24, 'description': '24-Ch DC Digital Input (15-30 VDC)'},
    'GRV-IDCS-24':      {'type': 'digital_input',  'channels': 24, 'description': '24-Ch DC Digital Input (simplified)'},
    'GRV-IDCI-12':      {'type': 'digital_input',  'channels': 12, 'description': '12-Ch DC Digital Input (Ch-Ch isolated)'},
    'GRV-IDCIS-12':     {'type': 'digital_input',  'channels': 12, 'description': '12-Ch DC Digital Input (isolated, simplified)'},
    'GRV-IDCSW-12':     {'type': 'digital_input',  'channels': 12, 'description': '12-Ch Dry Contact / Switch Input'},
    'GRV-IDCIFQ-12':    {'type': 'counter_input',  'channels': 12, 'description': '12-Ch High-Speed Counter (200 kHz, quadrature)'},
    'GRV-IACDCTTL-24':  {'type': 'digital_input',  'channels': 24, 'description': '24-Ch TTL Universal Input (2-16 VAC/VDC)'},
    'GRV-IACDCTTLS-24': {'type': 'digital_input',  'channels': 24, 'description': '24-Ch TTL Universal Input (simplified)'},

    # --- Discrete Output ---
    'GRV-OAC-12':     {'type': 'digital_output', 'channels': 12, 'description': '12-Ch AC SSR Output (12-250 VAC)'},
    'GRV-OACS-12':    {'type': 'digital_output', 'channels': 12, 'description': '12-Ch AC SSR Output (simplified)'},
    'GRV-OACI-12':    {'type': 'digital_output', 'channels': 12, 'description': '12-Ch AC SSR Output (Ch-Ch isolated)'},
    'GRV-OACIS-12':   {'type': 'digital_output', 'channels': 12, 'description': '12-Ch AC SSR Output (isolated, simplified)'},
    'GRV-ODCI-12':    {'type': 'digital_output', 'channels': 12, 'description': '12-Ch DC FET Output (5-60 VDC, isolated)'},
    'GRV-ODCIS-12':   {'type': 'digital_output', 'channels': 12, 'description': '12-Ch DC FET Output (isolated, simplified)'},
    'GRV-ODCSRC-24':  {'type': 'digital_output', 'channels': 24, 'description': '24-Ch DC Sourcing Output (5-60 VDC)'},

    # --- Relay Output ---
    'GRV-OMRIS-8':    {'type': 'digital_output', 'channels': 8,  'description': '8-Ch SPDT Electromechanical Relay (5A)'},

    # --- Analog Current Input ---
    'GRV-IMA-24':     {'type': 'current_input',  'channels': 24, 'description': '24-Ch ±20mA Analog Current Input'},
    'GRV-IMAI-8':     {'type': 'current_input',  'channels': 8,  'description': '8-Ch 4-20mA Analog Current Input (Ch-Ch isolated)'},

    # --- Analog Voltage Input ---
    'GRV-IV-24':      {'type': 'voltage_input',  'channels': 24, 'description': '24-Ch ±160V Analog Voltage Input (8 ranges)'},
    'GRV-IVI-12':     {'type': 'voltage_input',  'channels': 12, 'description': '12-Ch ±160V Analog Voltage Input (Ch-Ch isolated)'},
    'GRV-IVIRMS-10':  {'type': 'voltage_input',  'channels': 10, 'description': '10-Ch 0-300 VAC/VDC True RMS Input (isolated)'},

    # --- Analog Output (multi-function: voltage or current per channel) ---
    'GRV-OVMALC-8':   {'type': 'voltage_output', 'channels': 8,  'description': '8-Ch Multi-Function AO (V or mA, chassis-powered)'},
    'GRV-OVMAILP-8':  {'type': 'voltage_output', 'channels': 8,  'description': '8-Ch Multi-Function AO (V or mA, isolated, loop-powered)'},

    # --- Temperature Input ---
    'GRV-ITM-12':     {'type': 'thermocouple',   'channels': 12, 'description': '12-Ch Thermocouple / mV Input'},
    'GRV-ITMI-8':     {'type': 'thermocouple',   'channels': 8,  'description': '8-Ch Thermocouple / mV Input (Ch-Ch isolated)'},
    'GRV-IRTD-8':     {'type': 'rtd',            'channels': 8,  'description': '8-Ch RTD / Resistance Input (group isolated)'},
    'GRV-ITR-12':     {'type': 'resistance_input','channels': 12, 'description': '12-Ch Thermistor / Resistance Input'},
    'GRV-IICTD-12':   {'type': 'voltage_input',  'channels': 12, 'description': '12-Ch IC Temperature Device Input'},

    # --- Power Monitoring ---
    'GRV-IVAPM-3':    {'type': 'voltage_input',  'channels': 3,  'description': '3-Phase Power Monitor (600V, CT)'},

    # --- Communication ---
    'GRV-CSERI-4':    {'type': 'serial',          'channels': 4,  'description': '4-Port RS-232/RS-485 Serial (Ch-Ch isolated)'},
    'GRV-CCANI-2':    {'type': 'serial',          'channels': 2,  'description': '2-Port CAN 2.0B (Ch-Ch isolated)'},

    # --- Multi-Function ---
    'GRV-MM1001-10':  {'type': 'voltage_input',  'channels': 10, 'description': '8-Ch Multi-Function + 2 Relay (software-configurable)'},
}
