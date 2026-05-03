"""
Terminal Configuration Validation and Compatibility

Different NI module types support different terminal configurations.
The validator picks the right value per (channel_type, module) so the
saved JSON matches what DAQmx will actually use.

A subtle case worth flagging: NI's current-input modules (NI-9203,
NI-9207's current section, NI-9208, NI-9227, NI-9246, NI-9247, NI-9253)
are PHYSICALLY differential — they read the voltage across an internal
shunt. But the DAQmx software API exposes them as RSE; calling
``add_ai_current_chan(terminal_config=DIFF)`` on these modules raises
DaqError -200077 ("Possible Values: RSE"). Older docstrings here claimed
"RSE on a current input module reads the shunt voltage instead of the
current" — that is correct for ``add_ai_voltage_chan`` (where the caller
measures the shunt manually) but wrong for ``add_ai_current_chan``
(where DAQmx handles the shunt internally). For add_ai_current_chan,
RSE is the only DAQmx-accepted value on these modules.

This module provides:
- Canonical terminal config values
- Per-channel-type compatibility rules
- Per-module overrides — DIFF-only voltage modules AND RSE-required
  current modules
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


# Channel types that REQUIRE differential mode (TC cold-junction reference,
# bridge measurement, strain, IEPE, RTD, resistance — all physically
# differential by sensor design and exposed as DIFF in the DAQmx API).
#
# CURRENT_INPUT is INTENTIONALLY NOT in this set — see
# _CURRENT_INPUT_RSE_MODULES below. CURRENT_OUTPUT stays for legacy
# completeness but the DAQmx ao path doesn't accept terminal_config anyway.
_DIFFERENTIAL_ONLY_TYPES: Set[ChannelType] = {
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

# Modules where add_ai_current_chan REQUIRES terminal_config=RSE — DAQmx
# rejects DIFF with -200077. The measurement is physically differential
# through a built-in shunt, but the DAQmx software API treats each channel
# as the shunt voltage referenced to ground (RSE).
# Confirmed against real hardware (NI 9208) returning -200077 with
# "Possible Values: DAQmx_Val_RSE".
_CURRENT_INPUT_RSE_MODULES: Set[str] = {
    "NI-9203",   # 8-Ch ±20mA Current
    "NI-9207",   # 16-Ch — current section ai8..ai15 (voltage section is DIFF-only)
    "NI-9208",   # 16-Ch ±20mA, 24-bit
    "NI-9227",   # 4-Ch ±5A RMS Current
    "NI-9246",   # 3-Ch ±50A RMS Current
    "NI-9247",   # 3-Ch ±20A RMS Current
    "NI-9253",   # 8-Ch ±20mA Current
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


def _normalize_module_key(module_type: Optional[str]) -> Optional[str]:
    """Normalize "NI 9208" / "NI-9208" / "ni 9208" / "9208" → "NI-9208".

    Returns None for empty/None input.
    """
    if not module_type:
        return None
    n = module_type.strip().upper().replace(" ", "-").replace("_", "-")
    while "--" in n:
        n = n.replace("--", "-")
    if not n.startswith("NI-"):
        n = f"NI-{n}"
    return n


def is_module_differential_only(module_type: Optional[str]) -> bool:
    """True if this module's voltage channels are DIFF-only by hardware.

    Note: this only governs voltage-type channels. For current channels on
    the same module (e.g., NI-9207's current section), the per-module RSE
    rule in is_module_current_rse takes precedence.
    """
    n = _normalize_module_key(module_type)
    return bool(n) and n in _DIFFERENTIAL_ONLY_MODULES


def is_module_current_rse(module_type: Optional[str]) -> bool:
    """True if add_ai_current_chan on this module requires terminal_config=RSE.

    DAQmx rejects DIFF with -200077 on these modules. Confirmed against
    real NI 9208 hardware.
    """
    n = _normalize_module_key(module_type)
    return bool(n) and n in _CURRENT_INPUT_RSE_MODULES


def normalize(value: Optional[str]) -> str:
    """Normalize a terminal config value to canonical lowercase form.

    Returns 'differential' for unknown/empty values (safest default).
    """
    if not value:
        return DIFFERENTIAL
    key = value.strip().lower()
    return TERMINAL_ALIASES.get(key, DIFFERENTIAL)


def allowed_for(channel_type: ChannelType, module_type: Optional[str] = None) -> Set[str]:
    """Return the set of terminal configs that are valid for a (channel_type, module).

    Rule order (current is checked BEFORE the diff-only-module rule because
    a single module like NI-9207 needs DIFF for its voltage section AND RSE
    for its current section):
    - NO_TERMINAL types (digital, modbus, counter): empty (ignored).
    - CURRENT_INPUT on a known RSE-required module: {rse}.
    - CURRENT_INPUT on an unknown module: all (let DAQmx default).
    - Any other type on a DIFF-only voltage module (NI-9215 etc.): {differential}.
    - DIFF-only channel types (TC/RTD/strain/IEPE/...): {differential}.
    - VOLTAGE types on a regular module: all four configs.
    """
    if channel_type in _NO_TERMINAL_TYPES:
        return set()

    if channel_type == ChannelType.CURRENT_INPUT:
        if is_module_current_rse(module_type):
            return {RSE}
        return ALL_TERMINAL_CONFIGS  # unknown current module — be permissive

    if is_module_differential_only(module_type):
        return {DIFFERENTIAL}
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return {DIFFERENTIAL}
    if channel_type in _VOLTAGE_TYPES:
        return ALL_TERMINAL_CONFIGS
    return ALL_TERMINAL_CONFIGS  # unknown type — be permissive


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
        if (channel_type == ChannelType.CURRENT_INPUT
                and is_module_current_rse(module_type)):
            reason = (
                f" Module {module_type}'s current channels REQUIRE RSE in "
                f"the DAQmx API (DIFF raises -200077)."
            )
        elif is_module_differential_only(module_type):
            reason = (
                f" Module {module_type} is differential-only by hardware "
                f"design — RSE/NRSE are not selectable."
            )
        return False, (
            f"Terminal config '{value}' is not supported for "
            f"{channel_type.value} channels. Allowed: {sorted(allowed)}.{reason}"
        )

    return True, ""


def coerce(channel_type: ChannelType, value: Optional[str],
           module_type: Optional[str] = None) -> str:
    """Coerce a terminal config value to one valid for (channel_type, module_type).

    Returns the canonical string we want stored in JSON / passed to DAQmx.
    Order of rules matches allowed_for so JSON round-trips cleanly.
    """
    if channel_type in _NO_TERMINAL_TYPES:
        return DIFFERENTIAL  # value is ignored; pick something canonical

    if channel_type == ChannelType.CURRENT_INPUT:
        if is_module_current_rse(module_type):
            return RSE
        # Unknown current module: trust the caller's value if it's a known
        # config; else default to RSE (the most common DAQmx requirement
        # for current modules — safer than DIFF, which fails on -200077
        # modules).
        normalized = normalize(value) if value else RSE
        return normalized if normalized in ALL_TERMINAL_CONFIGS else RSE

    if is_module_differential_only(module_type):
        return DIFFERENTIAL
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return DIFFERENTIAL
    normalized = normalize(value)
    return normalized if normalized in ALL_TERMINAL_CONFIGS else DIFFERENTIAL
