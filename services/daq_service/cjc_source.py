"""
Cold Junction Compensation (CJC) Source Validation

CJC source applies only to thermocouple channels. NI thermocouple modules
(NI-9211, 9213, 9214, 9219) compensate for the cold junction (the point
where the thermocouple wire connects to copper) using one of:

- BUILT_IN  — module's onboard temperature sensor (most common, NI-9213)
- CONSTANT  — user-supplied fixed temperature (e.g., known ice bath at 0°C)
- CHANNEL   — another channel reads CJC temperature (external RTD)

Picking the wrong CJC source produces a constant temperature offset.
"""

from typing import Tuple, Set, Optional
from config_parser import ChannelType


# Canonical lowercase names (frontend format)
INTERNAL = "internal"
CONSTANT = "constant"
CHANNEL = "channel"

ALL_CJC_SOURCES: Set[str] = {INTERNAL, CONSTANT, CHANNEL}

# Aliases — accept what the user might enter
CJC_ALIASES = {
    # Frontend (canonical)
    "internal": INTERNAL,
    "constant": CONSTANT,
    "channel": CHANNEL,
    # nidaqmx names
    "built_in": INTERNAL,
    "builtin": INTERNAL,
    "const_val": CONSTANT,
    "constant_user_value": CONSTANT,
    "scannable_channel": CHANNEL,
    "external": CHANNEL,
    "ext": CHANNEL,
}


def normalize(value: Optional[str]) -> str:
    """Normalize a CJC source value to canonical lowercase form.

    Returns 'internal' for unknown/empty values (safest default — most
    NI thermocouple modules have a built-in CJC sensor).
    """
    if not value:
        return INTERNAL
    key = value.strip().lower()
    return CJC_ALIASES.get(key, INTERNAL)


def is_relevant(channel_type: ChannelType) -> bool:
    """CJC source is only meaningful for thermocouple channels."""
    return channel_type == ChannelType.THERMOCOUPLE


def validate(channel_type: ChannelType, value: Optional[str]) -> Tuple[bool, str]:
    """Validate a CJC source value against a channel type.

    Returns (is_valid, error_message).

    For non-thermocouple channels, CJC source is ignored (always valid).
    For thermocouples, the value must be one of internal/constant/channel.
    """
    if not is_relevant(channel_type):
        return True, ""

    normalized = normalize(value)
    if normalized not in ALL_CJC_SOURCES:
        return False, (
            f"CJC source '{value}' is not valid for thermocouple channels. "
            f"Allowed: {sorted(ALL_CJC_SOURCES)}"
        )

    return True, ""


def coerce(channel_type: ChannelType, value: Optional[str]) -> str:
    """Coerce a CJC source value to a valid one for the channel type.

    For thermocouples, normalizes and returns (or 'internal' if invalid).
    For non-thermocouples, returns 'internal' (won't be used anyway).
    """
    if not is_relevant(channel_type):
        return INTERNAL
    return normalize(value)
