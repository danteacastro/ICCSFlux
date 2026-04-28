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

# Per-module overrides — modules that are DIFF-only by physical design
# even though their channel type (e.g., voltage_input) would normally allow
# RSE/NRSE. Source: NI module specifications.
#
# Common pattern: simultaneous-sampling and isolated voltage modules use
# differential pairs by hardware design — RSE/NRSE are not selectable.
_DIFFERENTIAL_ONLY_MODULES: Set[str] = {
    # Simultaneous-sampling voltage modules (DIFF-only)
    "NI-9215",   # 4-Ch ±10V Simultaneous, 100 kS/s/ch
    "NI-9220",   # 16-Ch ±10V Simultaneous, 100 kS/s/ch
    "NI-9222",   # 4-Ch ±10V Simultaneous, 500 kS/s/ch
    "NI-9223",   # 4-Ch ±10V Simultaneous, 1 MS/s/ch
    "NI-9224",   # 4-Ch ±10V Simultaneous, 50 kS/s/ch
    "NI-9225",   # 3-Ch ±300V RMS Simultaneous
    # Isolated voltage modules (DIFF-only)
    "NI-9229",   # 4-Ch ±60V, 50 kS/s/ch, isolated
    "NI-9239",   # 4-Ch ±10V, 50 kS/s/ch, isolated
    # IEPE/Sound&Vibration modules (DIFF-only, but channel type already covers them)
    "NI-9230",   # 3-Ch IEPE, 12.8 kS/s/ch
    "NI-9231",   # 8-Ch IEPE, 12.8 kS/s/ch
    "NI-9232",   # 3-Ch IEPE, 102.4 kS/s/ch
    "NI-9234",   # 4-Ch IEPE, 51.2 kS/s/ch
    "NI-9250",   # 2-Ch IEPE, 102.4 kS/s/ch
    "NI-9251",   # 4-Ch IEPE, 102.4 kS/s/ch
    # Strain/bridge modules (DIFF-only)
    "NI-9219",   # 4-Ch universal, ±60V/RTD/Bridge/TC
    "NI-9237",   # 4-Ch ±25 mV/V Bridge
    # Thermocouple/RTD modules (DIFF-only by design)
    "NI-9211",   # 4-Ch TC, ±80 mV
    "NI-9213",   # 16-Ch TC, ±78 mV
    "NI-9214",   # 16-Ch isolated TC
    "NI-9216",   # 8-Ch RTD
    "NI-9217",   # 4-Ch RTD, 100 S/s
    "NI-9226",   # 8-Ch RTD, 24-bit
    # Current input modules (DIFF-only)
    "NI-9203",   # 8-Ch ±20mA Current, 200 kS/s
    "NI-9207",   # 16-Ch ±20mA + Voltage
    "NI-9208",   # 16-Ch ±20mA, 24-bit
    "NI-9227",   # 4-Ch ±5A RMS Current
    "NI-9246",   # 3-Ch ±50A RMS Current
    "NI-9247",   # 3-Ch ±20A RMS Current
    "NI-9253",   # 8-Ch ±20mA Current
}


def is_module_differential_only(module_type: Optional[str]) -> bool:
    """True if this module is DIFF-only by hardware design.

    Module type strings are normalized to handle every variant produced by
    different parts of the system:
      - "NI-9215" (canonical, used by _DIFFERENTIAL_ONLY_MODULES)
      - "NI 9215" (used by device_discovery.py NI_MODULE_DATABASE)
      - "ni-9215", "ni 9215" (lowercase variants)
      - "9215"   (bare model number)
    """
    if not module_type:
        return False
    normalized = module_type.strip().upper()
    # Normalize whitespace and underscores to hyphens so "NI 9207" → "NI-9207"
    normalized = normalized.replace(" ", "-").replace("_", "-")
    # Collapse double hyphens that can result from "NI - 9207" etc
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    if normalized in _DIFFERENTIAL_ONLY_MODULES:
        return True
    # Also accept bare model number (e.g., "9215" → "NI-9215")
    if not normalized.startswith("NI-"):
        return f"NI-{normalized}" in _DIFFERENTIAL_ONLY_MODULES
    return False


def normalize(value: Optional[str]) -> str:
    """Normalize a terminal config value to canonical lowercase form.

    Returns 'differential' for unknown/empty values (safest default).
    """
    if not value:
        return DIFFERENTIAL
    key = value.strip().lower()
    return TERMINAL_ALIASES.get(key, DIFFERENTIAL)


def allowed_for(channel_type: ChannelType, module_type: Optional[str] = None) -> Set[str]:
    """Return the set of terminal configs that are valid for a channel type.

    If module_type is given and that specific module is DIFF-only by design
    (e.g., NI-9215), restricts to {differential} regardless of channel type.
    """
    # Per-module override: some voltage modules are DIFF-only by hardware design
    if is_module_differential_only(module_type):
        return {DIFFERENTIAL}
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return {DIFFERENTIAL}
    if channel_type in _VOLTAGE_TYPES:
        return ALL_TERMINAL_CONFIGS
    if channel_type in _NO_TERMINAL_TYPES:
        return set()  # Empty: terminal_config is ignored for these types
    # Unknown type: allow all (be lenient)
    return ALL_TERMINAL_CONFIGS


def validate(channel_type: ChannelType, value: Optional[str],
             module_type: Optional[str] = None) -> Tuple[bool, str]:
    """Validate a terminal config value against a channel type and module.

    Returns (is_valid, error_message). On success, error_message is "".

    Rules:
    - DIFFERENTIAL_ONLY channel types: only 'differential' accepted
    - DIFFERENTIAL_ONLY modules (NI-9215 etc.): only 'differential' accepted
    - VOLTAGE types on regular modules: all four configs valid
    - NO_TERMINAL types (digital, modbus): always valid (ignored)
    """
    if channel_type in _NO_TERMINAL_TYPES:
        return True, ""

    normalized = normalize(value)
    allowed = allowed_for(channel_type, module_type)

    if normalized not in allowed:
        reason = ""
        if is_module_differential_only(module_type):
            reason = (
                f" Module {module_type} is differential-only by hardware "
                f"design — RSE/NRSE are not selectable."
            )
        return False, (
            f"Terminal config '{value}' is not supported for "
            f"{channel_type.value} channels. Allowed: {sorted(allowed)}.{reason} "
            f"Using the wrong terminal configuration causes incorrect readings — "
            f"for example, RSE on a current input module reads the shunt voltage "
            f"instead of the current."
        )

    return True, ""


def coerce(channel_type: ChannelType, value: Optional[str],
           module_type: Optional[str] = None) -> str:
    """Coerce a terminal config value to a valid one for the channel type and module.

    - DIFFERENTIAL_ONLY channel types or modules: always returns 'differential'
    - VOLTAGE types on regular modules: normalizes and returns (or 'differential')
    - NO_TERMINAL types: returns 'differential' (won't be used anyway)
    """
    if is_module_differential_only(module_type):
        return DIFFERENTIAL
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return DIFFERENTIAL
    if channel_type in _NO_TERMINAL_TYPES:
        return DIFFERENTIAL
    normalized = normalize(value)
    if normalized in ALL_TERMINAL_CONFIGS:
        return normalized
    return DIFFERENTIAL
