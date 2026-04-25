"""
Terminal Configuration Validation and Compatibility

Different NI module types support different terminal configurations.
Picking the wrong one causes incorrect readings — for example, a current
input module (NI-9203) with terminal_config=RSE will read the shunt
voltage instead of the current, producing garbage values like 127 mA
on a 4-20 mA loop.

This module provides:
- Canonical terminal config values
- Per-channel-type compatibility rules
- Normalization (case-insensitive, alias handling)
- Validation that returns clear error messages
"""

from typing import Tuple, Set, Optional
from config_parser import ChannelType


# Canonical terminal configuration values (lowercase, frontend format)
DIFFERENTIAL = "differential"
RSE = "rse"
NRSE = "nrse"
PSEUDODIFFERENTIAL = "pseudodifferential"

ALL_TERMINAL_CONFIGS: Set[str] = {DIFFERENTIAL, RSE, NRSE, PSEUDODIFFERENTIAL}

# Aliases (case-insensitive lookups)
TERMINAL_ALIASES = {
    # Canonical
    "differential": DIFFERENTIAL,
    "rse": RSE,
    "nrse": NRSE,
    "pseudodifferential": PSEUDODIFFERENTIAL,
    # nidaqmx API names
    "diff": DIFFERENTIAL,
    "pseudo_diff": PSEUDODIFFERENTIAL,
    # Legacy
    "default": DIFFERENTIAL,  # Old configs used DEFAULT — map to safest option
}


# Channel types that REQUIRE differential mode (current shunt measurement,
# bridge measurement, thermocouple cold-junction reference, etc.)
_DIFFERENTIAL_ONLY_TYPES: Set[ChannelType] = {
    ChannelType.CURRENT_INPUT,
    ChannelType.CURRENT_OUTPUT,
    ChannelType.THERMOCOUPLE,
    ChannelType.RTD,
    ChannelType.STRAIN,
    ChannelType.STRAIN_INPUT,
    ChannelType.BRIDGE_INPUT,
    ChannelType.RESISTANCE,
    ChannelType.RESISTANCE_INPUT,
    ChannelType.IEPE,
    ChannelType.IEPE_INPUT,
}

# Channel types where terminal_config is configurable (voltage inputs)
_VOLTAGE_TYPES: Set[ChannelType] = {
    ChannelType.VOLTAGE_INPUT,
    ChannelType.VOLTAGE_OUTPUT,
}

# Channel types where terminal_config is irrelevant (digital, modbus, etc.)
_NO_TERMINAL_TYPES: Set[ChannelType] = {
    ChannelType.DIGITAL_INPUT,
    ChannelType.DIGITAL_OUTPUT,
    ChannelType.MODBUS_REGISTER,
    ChannelType.MODBUS_COIL,
    ChannelType.COUNTER,
    ChannelType.COUNTER_INPUT,
    ChannelType.COUNTER_OUTPUT,
    ChannelType.PULSE_OUTPUT,
    ChannelType.FREQUENCY_INPUT,
}


def normalize(value: Optional[str]) -> str:
    """Normalize a terminal config value to canonical lowercase form.

    Returns 'differential' for unknown/empty values (safest default).
    """
    if not value:
        return DIFFERENTIAL
    key = value.strip().lower()
    return TERMINAL_ALIASES.get(key, DIFFERENTIAL)


def allowed_for(channel_type: ChannelType) -> Set[str]:
    """Return the set of terminal configs that are valid for a channel type."""
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return {DIFFERENTIAL}
    if channel_type in _VOLTAGE_TYPES:
        return ALL_TERMINAL_CONFIGS
    if channel_type in _NO_TERMINAL_TYPES:
        return set()  # Empty: terminal_config is ignored for these types
    # Unknown type: allow all (be lenient)
    return ALL_TERMINAL_CONFIGS


def validate(channel_type: ChannelType, value: Optional[str]) -> Tuple[bool, str]:
    """Validate a terminal config value against a channel type.

    Returns (is_valid, error_message). On success, error_message is "".

    For DIFFERENTIAL_ONLY types, only 'differential' is accepted.
    For VOLTAGE types, all four configs are valid.
    For NO_TERMINAL types, value is ignored (always valid).
    """
    if channel_type in _NO_TERMINAL_TYPES:
        return True, ""

    normalized = normalize(value)
    allowed = allowed_for(channel_type)

    if normalized not in allowed:
        return False, (
            f"Terminal config '{value}' is not supported for "
            f"{channel_type.value} channels. Allowed: {sorted(allowed)}. "
            f"Using the wrong terminal configuration causes incorrect readings — "
            f"for example, RSE on a current input module reads the shunt voltage "
            f"instead of the current."
        )

    return True, ""


def coerce(channel_type: ChannelType, value: Optional[str]) -> str:
    """Coerce a terminal config value to a valid one for the channel type.

    For DIFFERENTIAL_ONLY types, always returns 'differential'.
    For VOLTAGE types, normalizes and returns (or 'differential' if invalid).
    For NO_TERMINAL types, returns 'differential' (won't be used anyway).
    """
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return DIFFERENTIAL
    if channel_type in _NO_TERMINAL_TYPES:
        return DIFFERENTIAL
    normalized = normalize(value)
    if normalized in ALL_TERMINAL_CONFIGS:
        return normalized
    return DIFFERENTIAL
