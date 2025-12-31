"""
Scaling utilities for NISystem
Applies NI MAX-style scaling to raw values from hardware

Supports:
- Linear scaling (y = mx + b)
- 4-20mA scaling (maps 4-20mA to engineering units)
- Map/range scaling (maps one range to another)
- Counter/pulse scaling (pulses or frequency to engineering units)
"""

from typing import Optional, Tuple
from config_parser import ChannelConfig, ChannelType


def apply_scaling(channel: ChannelConfig, raw_value: float) -> float:
    """
    Apply scaling to a raw value based on channel configuration.

    This mimics NI MAX behavior where you can configure:
    - 4-20mA sensors to display engineering units
    - Voltage inputs with linear or map scaling
    - Counter inputs with pulse-to-engineering-unit conversion
    - Raw pass-through for unscaled channels

    Args:
        channel: The channel configuration with scaling parameters
        raw_value: The raw value from hardware (mA, V, pulses, Hz, etc.)

    Returns:
        The scaled engineering value
    """
    # For counter channels - convert pulses/frequency to engineering units
    if channel.channel_type == ChannelType.COUNTER:
        return scale_counter(raw_value, channel.pulses_per_unit, channel.counter_mode)

    # For 4-20mA current inputs with scaling enabled
    if channel.channel_type == ChannelType.CURRENT and channel.four_twenty_scaling:
        if channel.eng_units_min is not None and channel.eng_units_max is not None:
            return scale_four_twenty(raw_value, channel.eng_units_min, channel.eng_units_max)

    # For voltage inputs with map scaling
    if channel.channel_type == ChannelType.VOLTAGE and channel.scale_type == 'map':
        if (channel.pre_scaled_min is not None and channel.pre_scaled_max is not None and
            channel.scaled_min is not None and channel.scaled_max is not None):
            return scale_map(
                raw_value,
                channel.pre_scaled_min, channel.pre_scaled_max,
                channel.scaled_min, channel.scaled_max
            )

    # Linear scaling (y = mx + b) - applies to any channel type
    if channel.scale_type == 'linear' or (channel.scale_slope != 1.0 or channel.scale_offset != 0.0):
        return scale_linear(raw_value, channel.scale_slope, channel.scale_offset)

    # No scaling - return raw value
    return raw_value


def scale_counter(raw_value: float, pulses_per_unit: float, mode: str = 'frequency') -> float:
    """
    Scale counter/pulse values to engineering units.

    Modes:
    - 'frequency': raw_value is Hz (pulses/sec), convert to units/time
    - 'count': raw_value is total pulses, convert to total units
    - 'period': raw_value is period in seconds, convert to frequency then units

    Example:
        Flow meter: 100 pulses per gallon, reading 500 Hz
        pulses_per_unit = 100
        mode = 'frequency'
        Result: 500 / 100 = 5.0 GPM (gallons per minute would need *60)

    For flow rate in GPM with pulses_per_gallon:
        Set pulses_per_unit = pulses_per_gallon / 60
        Then Hz input gives GPM output

    Args:
        raw_value: Raw counter value (Hz, count, or period)
        pulses_per_unit: Number of pulses per engineering unit
        mode: 'frequency', 'count', or 'period'

    Returns:
        Scaled engineering value
    """
    if pulses_per_unit == 0:
        return 0.0

    if mode == 'frequency':
        # raw_value is Hz (pulses/sec), output is units/sec
        return raw_value / pulses_per_unit
    elif mode == 'count':
        # raw_value is total pulses, output is total units
        return raw_value / pulses_per_unit
    elif mode == 'period':
        # raw_value is period in seconds, convert to frequency first
        if raw_value == 0:
            return 0.0
        frequency = 1.0 / raw_value
        return frequency / pulses_per_unit
    else:
        # Unknown mode, return raw
        return raw_value


def scale_linear(raw_value: float, slope: float, offset: float) -> float:
    """
    Apply linear scaling: scaled = (raw * slope) + offset

    Example:
        A voltage output from a current transducer (0.1V/A):
        slope = 10.0 (10 Amps per Volt)
        offset = 0.0
        1.5V input -> 15.0 Amps
    """
    return (raw_value * slope) + offset


def scale_four_twenty(current_ma: float, eng_min: float, eng_max: float) -> float:
    """
    Scale a 4-20mA signal to engineering units.

    Standard 4-20mA scaling:
    - 4mA = minimum engineering value
    - 20mA = maximum engineering value

    Formula:
        eng_value = eng_min + ((current_ma - 4) / 16) * (eng_max - eng_min)

    Example:
        Pressure transmitter 0-100 PSI:
        eng_min = 0, eng_max = 100
        At 4mA: 0 PSI
        At 12mA: 50 PSI
        At 20mA: 100 PSI

    Args:
        current_ma: The raw current in mA (typically 4-20)
        eng_min: Engineering value at 4mA
        eng_max: Engineering value at 20mA

    Returns:
        The scaled engineering value
    """
    # Clamp to valid 4-20mA range to prevent wild extrapolation
    # But allow slight under/over for diagnostics (3.8-20.5mA)
    if current_ma < 3.8:
        # Under-range condition (wire break or sensor error)
        return eng_min - ((4 - current_ma) / 16) * (eng_max - eng_min)
    elif current_ma > 20.5:
        # Over-range condition
        return eng_max + ((current_ma - 20) / 16) * (eng_max - eng_min)

    # Normal scaling
    span = eng_max - eng_min
    normalized = (current_ma - 4.0) / 16.0  # 0.0 at 4mA, 1.0 at 20mA
    return eng_min + (normalized * span)


def scale_map(raw_value: float,
              raw_min: float, raw_max: float,
              scaled_min: float, scaled_max: float) -> float:
    """
    Map one range to another (linear interpolation).

    Example:
        Voltage input 0-10V mapped to 0-500 RPM:
        raw_min = 0, raw_max = 10
        scaled_min = 0, scaled_max = 500
        5V input -> 250 RPM

    Args:
        raw_value: The raw input value
        raw_min: Minimum of the input range
        raw_max: Maximum of the input range
        scaled_min: Minimum of the output range
        scaled_max: Maximum of the output range

    Returns:
        The scaled value
    """
    if raw_max == raw_min:
        return scaled_min  # Avoid division by zero

    normalized = (raw_value - raw_min) / (raw_max - raw_min)
    return scaled_min + (normalized * (scaled_max - scaled_min))


def reverse_scaling(channel: ChannelConfig, eng_value: float) -> float:
    """
    Reverse scaling: convert engineering value back to raw value.
    Useful for setpoints and validation.

    Args:
        channel: The channel configuration
        eng_value: The engineering value to convert

    Returns:
        The raw value (mA, V, etc.)
    """
    # For 4-20mA with scaling
    if channel.channel_type == ChannelType.CURRENT and channel.four_twenty_scaling:
        if channel.eng_units_min is not None and channel.eng_units_max is not None:
            span = channel.eng_units_max - channel.eng_units_min
            if span != 0:
                normalized = (eng_value - channel.eng_units_min) / span
                return 4.0 + (normalized * 16.0)
            return 4.0

    # For map scaling
    if channel.channel_type == ChannelType.VOLTAGE and channel.scale_type == 'map':
        if (channel.pre_scaled_min is not None and channel.pre_scaled_max is not None and
            channel.scaled_min is not None and channel.scaled_max is not None):
            scaled_span = channel.scaled_max - channel.scaled_min
            if scaled_span != 0:
                normalized = (eng_value - channel.scaled_min) / scaled_span
                return channel.pre_scaled_min + (normalized * (channel.pre_scaled_max - channel.pre_scaled_min))
            return channel.pre_scaled_min

    # For linear scaling: reverse is (value - offset) / slope
    if channel.scale_slope != 0:
        return (eng_value - channel.scale_offset) / channel.scale_slope

    return eng_value


def get_scaling_info(channel: ChannelConfig) -> dict:
    """
    Get human-readable scaling information for a channel.
    Useful for UI display and validation feedback.

    Returns dict with:
        - type: The scaling type used
        - formula: Human-readable formula
        - raw_range: The expected raw input range
        - scaled_range: The resulting scaled range
        - example: An example conversion
    """
    info = {
        'type': 'none',
        'formula': 'value = raw',
        'raw_range': None,
        'scaled_range': None,
        'example': None
    }

    if channel.channel_type == ChannelType.CURRENT and channel.four_twenty_scaling:
        if channel.eng_units_min is not None and channel.eng_units_max is not None:
            info['type'] = '4-20mA'
            info['formula'] = f'value = {channel.eng_units_min} + ((mA - 4) / 16) * {channel.eng_units_max - channel.eng_units_min}'
            info['raw_range'] = (4.0, 20.0)
            info['scaled_range'] = (channel.eng_units_min, channel.eng_units_max)
            # Example at midpoint (12mA)
            mid_eng = (channel.eng_units_min + channel.eng_units_max) / 2
            info['example'] = f'12mA -> {mid_eng} {channel.units}'
            return info

    if channel.channel_type == ChannelType.VOLTAGE and channel.scale_type == 'map':
        if (channel.pre_scaled_min is not None and channel.pre_scaled_max is not None and
            channel.scaled_min is not None and channel.scaled_max is not None):
            info['type'] = 'map'
            info['formula'] = f'{channel.pre_scaled_min}V-{channel.pre_scaled_max}V -> {channel.scaled_min}-{channel.scaled_max} {channel.units}'
            info['raw_range'] = (channel.pre_scaled_min, channel.pre_scaled_max)
            info['scaled_range'] = (channel.scaled_min, channel.scaled_max)
            mid_raw = (channel.pre_scaled_min + channel.pre_scaled_max) / 2
            mid_scaled = (channel.scaled_min + channel.scaled_max) / 2
            info['example'] = f'{mid_raw}V -> {mid_scaled} {channel.units}'
            return info

    if channel.scale_slope != 1.0 or channel.scale_offset != 0.0:
        info['type'] = 'linear'
        info['formula'] = f'value = (raw * {channel.scale_slope}) + {channel.scale_offset}'
        if channel.channel_type == ChannelType.VOLTAGE:
            info['raw_range'] = (-channel.voltage_range, channel.voltage_range)
        elif channel.channel_type == ChannelType.CURRENT:
            info['raw_range'] = (0, channel.current_range_ma)
        # Example at 1 unit input
        example_val = apply_scaling(channel, 1.0)
        info['example'] = f'1 raw -> {example_val} {channel.units}'
        return info

    return info


def validate_scaling_config(channel: ChannelConfig) -> Tuple[bool, str]:
    """
    Validate that a channel's scaling configuration is valid.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if channel.channel_type == ChannelType.CURRENT and channel.four_twenty_scaling:
        if channel.eng_units_min is None or channel.eng_units_max is None:
            return False, "4-20mA scaling enabled but eng_units_min/max not set"
        if channel.eng_units_min == channel.eng_units_max:
            return False, "4-20mA scaling: min and max cannot be equal"

    if channel.scale_type == 'map':
        if channel.pre_scaled_min is None or channel.pre_scaled_max is None:
            return False, "Map scaling: pre_scaled_min/max not set"
        if channel.scaled_min is None or channel.scaled_max is None:
            return False, "Map scaling: scaled_min/max not set"
        if channel.pre_scaled_min == channel.pre_scaled_max:
            return False, "Map scaling: input min and max cannot be equal"

    if channel.scale_type == 'linear' and channel.scale_slope == 0:
        return False, "Linear scaling: slope cannot be zero"

    return True, ""


if __name__ == "__main__":
    # Test scaling functions
    print("Testing 4-20mA Scaling:")
    print("-" * 40)
    print(f"  4mA  -> {scale_four_twenty(4, 0, 100):.2f} (expect 0)")
    print(f"  12mA -> {scale_four_twenty(12, 0, 100):.2f} (expect 50)")
    print(f"  20mA -> {scale_four_twenty(20, 0, 100):.2f} (expect 100)")
    print(f"  3.5mA -> {scale_four_twenty(3.5, 0, 100):.2f} (under-range)")
    print(f"  21mA -> {scale_four_twenty(21, 0, 100):.2f} (over-range)")

    print("\nTesting Map Scaling:")
    print("-" * 40)
    print(f"  0V -> {scale_map(0, 0, 10, 0, 500):.1f} RPM (expect 0)")
    print(f"  5V -> {scale_map(5, 0, 10, 0, 500):.1f} RPM (expect 250)")
    print(f"  10V -> {scale_map(10, 0, 10, 0, 500):.1f} RPM (expect 500)")

    print("\nTesting Linear Scaling:")
    print("-" * 40)
    print(f"  1V @ 10A/V -> {scale_linear(1, 10, 0):.1f} A (expect 10)")
    print(f"  2.5V @ 10A/V -> {scale_linear(2.5, 10, 0):.1f} A (expect 25)")
