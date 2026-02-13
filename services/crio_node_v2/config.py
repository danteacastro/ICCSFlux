"""
Configuration Module for cRIO Node V2

Handles loading and parsing configuration from:
- JSON project files
- system.ini files
- Command line arguments

Config versioning:
  - All saved configs include a 'config_version' field.
  - On load, migrate_crio_config() auto-upgrades old configs to the latest version.
  - Migration functions are idempotent (safe to run multiple times).
  - Version history:
      1.0  Initial release
      1.1  Added TLS fields (tls_enabled, tls_ca_cert)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .channel_types import ChannelType

logger = logging.getLogger('cRIONode')

# Ordered list of config schema versions
CRIO_CONFIG_VERSIONS = ["1.0", "1.1"]
CURRENT_CRIO_CONFIG_VERSION = CRIO_CONFIG_VERSIONS[-1]


def migrate_crio_config(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Migrate cRIO config data to the latest version.

    Returns (migrated_data, list_of_applied_migrations).
    Safe to call on already-current configs.
    """
    current = data.get('config_version', '1.0')
    if current not in CRIO_CONFIG_VERSIONS:
        logger.warning(f"Unknown cRIO config version '{current}', treating as 1.0")
        current = '1.0'

    from_idx = CRIO_CONFIG_VERSIONS.index(current)
    to_idx = len(CRIO_CONFIG_VERSIONS) - 1
    if from_idx >= to_idx:
        return data, []

    result = dict(data)
    applied = []

    for version in CRIO_CONFIG_VERSIONS[from_idx + 1:to_idx + 1]:
        func_name = f"_migrate_crio_to_{version.replace('.', '_')}"
        migrate_func = globals().get(func_name)
        if migrate_func:
            prev = result.get('config_version', '1.0')
            logger.info(f"cRIO config migration: {prev} -> {version}")
            result = migrate_func(result)
            result['config_version'] = version
            applied.append(f"{prev}->{version}")

    return result, applied


def _migrate_crio_to_1_1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.0 to 1.1.

    Changes:
    - Add TLS fields to system/mqtt section if missing
    """
    system = data.get('system', data)
    if 'tls_enabled' not in system:
        system['tls_enabled'] = False
    if 'tls_ca_cert' not in system:
        system['tls_ca_cert'] = None
    return data


@dataclass
class ChannelConfig:
    """Configuration for a single channel."""
    name: str
    physical_channel: str
    channel_type: str  # digital_input, analog_input, digital_output, analog_output

    # Scaling — linear
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    scale_type: str = 'none'  # none, linear, map

    # Scaling — 4-20mA (current inputs)
    four_twenty_scaling: bool = False
    eng_units_min: Optional[float] = None
    eng_units_max: Optional[float] = None

    # Scaling — map (voltage inputs: raw range → engineering range)
    pre_scaled_min: Optional[float] = None
    pre_scaled_max: Optional[float] = None
    scaled_min: Optional[float] = None
    scaled_max: Optional[float] = None

    # Thermocouple specific
    thermocouple_type: Optional[str] = None
    cjc_source: str = 'internal'
    cjc_value: float = 25.0  # For constant CJC (°C)

    # RTD specific
    rtd_type: str = 'Pt3850'       # Pt3750, Pt3850, Pt3851, Pt3911, Pt3916, Pt3920, Pt3928, Custom
    rtd_wiring: str = '4-wire'     # 2-wire, 3-wire, 4-wire
    rtd_current: float = 0.001     # Excitation current in Amps (1mA default)

    # Range
    voltage_range: float = 10.0
    current_range_ma: float = 20.0

    # Behavior
    invert: bool = False
    default_state: bool = False
    default_value: float = 0.0

    # Alarm limits
    hihi_limit: Optional[float] = None
    hi_limit: Optional[float] = None
    lo_limit: Optional[float] = None
    lolo_limit: Optional[float] = None
    alarm_enabled: bool = False
    alarm_deadband: float = 0.0
    alarm_delay_sec: float = 0.0

    # Safety
    safety_action: Optional[str] = None
    safety_interlock: Optional[str] = None

    # Resistance specific
    resistance_range: float = 1000.0     # Max expected resistance (Ohms)
    resistance_wiring: str = '4-wire'    # 2-wire or 4-wire

    # Counter input specific
    counter_mode: str = 'frequency'      # frequency, count, period
    counter_edge: str = 'rising'         # rising or falling
    counter_min_freq: float = 0.1        # Min expected frequency (Hz)
    counter_max_freq: float = 1000.0     # Max expected frequency (Hz)

    # Pulse/Counter output specific
    pulse_frequency: float = 1000.0      # Output frequency in Hz
    pulse_duty_cycle: float = 50.0       # Duty cycle 0-100%
    pulse_idle_state: str = 'LOW'        # LOW or HIGH (idle level)

    # Relay specific
    relay_type: str = 'none'             # none, spst, spdt, ssr (informational)
    momentary_pulse_ms: int = 0          # 0 = latching (stays ON), >0 = momentary (auto-OFF after N ms)

    # Source info (for cRIO mode)
    source_type: str = 'local'  # local, crio, opto22
    source_node_id: Optional[str] = None

    def __post_init__(self):
        """Validate and clamp fields to safe ranges."""
        # Validate momentary_pulse_ms: 0..3600000 (max 1 hour)
        if self.momentary_pulse_ms < 0:
            logger.warning(
                f"Channel {self.name}: momentary_pulse_ms={self.momentary_pulse_ms} "
                f"is negative, clamping to 0"
            )
            self.momentary_pulse_ms = 0
        elif self.momentary_pulse_ms > 3600000:
            logger.warning(
                f"Channel {self.name}: momentary_pulse_ms={self.momentary_pulse_ms} "
                f"exceeds max (3600000), clamping to 3600000"
            )
            self.momentary_pulse_ms = 3600000

        # Validate pulse_duty_cycle: 0..100
        if self.pulse_duty_cycle < 0:
            logger.warning(
                f"Channel {self.name}: pulse_duty_cycle={self.pulse_duty_cycle} "
                f"is negative, clamping to 0"
            )
            self.pulse_duty_cycle = 0.0
        elif self.pulse_duty_cycle > 100:
            logger.warning(
                f"Channel {self.name}: pulse_duty_cycle={self.pulse_duty_cycle} "
                f"exceeds 100%, clamping to 100"
            )
            self.pulse_duty_cycle = 100.0

        # Validate alarm limit ordering: lolo < lo < hi < hihi
        if self.alarm_enabled:
            limits = [(v, label) for v, label in
                      [(self.lolo_limit, 'lolo'), (self.lo_limit, 'lo'),
                       (self.hi_limit, 'hi'), (self.hihi_limit, 'hihi')]
                      if v is not None]
            for i in range(1, len(limits)):
                if limits[i][0] <= limits[i-1][0]:
                    logger.error(
                        f"Channel {self.name}: alarm limit {limits[i][1]}={limits[i][0]} "
                        f"must be > {limits[i-1][1]}={limits[i-1][0]} — disabling alarms"
                    )
                    self.alarm_enabled = False
                    break

            if self.alarm_deadband < 0:
                logger.warning(f"Channel {self.name}: alarm_deadband={self.alarm_deadband} is negative, using 0")
                self.alarm_deadband = 0.0
            if self.alarm_delay_sec < 0:
                logger.warning(f"Channel {self.name}: alarm_delay_sec={self.alarm_delay_sec} is negative, using 0")
                self.alarm_delay_sec = 0.0

        # Validate scaling configuration for inversions
        scaling_warnings = validate_scaling(self)
        for w in scaling_warnings:
            logger.warning(w)

    @staticmethod
    def apply_scaling(raw_value: float, ch_config: 'ChannelConfig') -> float:
        """
        Apply scaling to a raw hardware value based on channel configuration.

        Matches the DAQ service scaling.py logic (ISA-95 Level 1 scaling):
        1. 4-20mA scaling for current inputs (four_twenty_scaling)
        2. Map scaling for voltage inputs (scale_type == 'map')
        3. Linear scaling (slope/offset)
        4. Pass-through (no scaling)
        """
        if ch_config is None:
            return raw_value

        # 4-20mA current input scaling
        if (ch_config.channel_type == 'current_input' and
                ch_config.four_twenty_scaling and
                ch_config.eng_units_min is not None and
                ch_config.eng_units_max is not None):
            current_ma = raw_value
            eng_min = ch_config.eng_units_min
            eng_max = ch_config.eng_units_max
            span = eng_max - eng_min
            # NAMUR NE43: allow slight under/over for diagnostics
            if current_ma < 3.8:
                return eng_min - ((4.0 - current_ma) / 16.0) * span
            elif current_ma > 20.5:
                return eng_max + ((current_ma - 20.0) / 16.0) * span
            # Normal 4-20mA range
            normalized = (current_ma - 4.0) / 16.0
            return eng_min + (normalized * span)

        # Map scaling for voltage inputs (raw range -> engineering range)
        if (ch_config.channel_type == 'voltage_input' and
                ch_config.scale_type == 'map' and
                ch_config.pre_scaled_min is not None and
                ch_config.pre_scaled_max is not None and
                ch_config.scaled_min is not None and
                ch_config.scaled_max is not None):
            raw_min = ch_config.pre_scaled_min
            raw_max = ch_config.pre_scaled_max
            if raw_max == raw_min:
                return ch_config.scaled_min
            normalized = (raw_value - raw_min) / (raw_max - raw_min)
            return ch_config.scaled_min + (normalized * (ch_config.scaled_max - ch_config.scaled_min))

        # Linear scaling (y = mx + b)
        if ch_config.scale_slope != 1.0 or ch_config.scale_offset != 0.0:
            return (raw_value * ch_config.scale_slope) + ch_config.scale_offset

        # No scaling - pass through
        return raw_value

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ChannelConfig':
        """Create from dictionary."""
        channel_type = data.get('channel_type', 'voltage_input')
        tc_type = data.get('thermocouple_type')

        # Infer thermocouple type if channel is thermocouple but type not specified
        if ChannelType.needs_thermocouple_type(channel_type) and not tc_type:
            tc_type = 'K'  # Default to K-type (most common)
            logger.warning(f"Channel {name}: defaulting thermocouple_type to 'K' - verify correct TC type to avoid temperature errors")

        return cls(
            name=name,
            physical_channel=data.get('physical_channel', ''),
            channel_type=channel_type,
            scale_slope=data.get('scale_slope', 1.0),
            scale_offset=data.get('scale_offset', 0.0),
            scale_type=data.get('scale_type', 'none'),
            four_twenty_scaling=data.get('four_twenty_scaling', False),
            eng_units_min=float(data['eng_units_min']) if data.get('eng_units_min') is not None else None,
            eng_units_max=float(data['eng_units_max']) if data.get('eng_units_max') is not None else None,
            pre_scaled_min=float(data['pre_scaled_min']) if data.get('pre_scaled_min') is not None else None,
            pre_scaled_max=float(data['pre_scaled_max']) if data.get('pre_scaled_max') is not None else None,
            scaled_min=float(data['scaled_min']) if data.get('scaled_min') is not None else None,
            scaled_max=float(data['scaled_max']) if data.get('scaled_max') is not None else None,
            thermocouple_type=tc_type,
            cjc_source=data.get('cjc_source', 'internal'),
            cjc_value=float(data.get('cjc_value', 25.0)),
            rtd_type=data.get('rtd_type', 'Pt3850'),
            rtd_wiring=data.get('rtd_wiring', '4-wire'),
            rtd_current=float(data.get('rtd_current', 0.001)),
            voltage_range=data.get('voltage_range', 10.0),
            current_range_ma=data.get('current_range_ma', 20.0),
            invert=data.get('invert', False),
            default_state=data.get('default_state', False),
            default_value=data.get('default_value', 0.0),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
            alarm_enabled=data.get('alarm_enabled', False),
            alarm_deadband=data.get('alarm_deadband', 0.0),
            alarm_delay_sec=data.get('alarm_delay_sec', 0.0),
            resistance_range=data.get('resistance_range', 1000.0),
            resistance_wiring=data.get('resistance_wiring', '4-wire'),
            counter_mode=data.get('counter_mode', 'frequency'),
            counter_edge=data.get('counter_edge', 'rising'),
            counter_min_freq=data.get('counter_min_freq', 0.1),
            counter_max_freq=data.get('counter_max_freq', 1000.0),
            pulse_frequency=data.get('pulse_frequency', 1000.0),
            pulse_duty_cycle=data.get('pulse_duty_cycle', 50.0),
            pulse_idle_state=data.get('pulse_idle_state', 'LOW'),
            relay_type=data.get('relay_type', 'none'),
            momentary_pulse_ms=data.get('momentary_pulse_ms', 0),
            safety_action=data.get('safety_action'),
            safety_interlock=data.get('safety_interlock'),
            source_type=data.get('source_type', 'local'),
            source_node_id=data.get('source_node_id')
        )


@dataclass
class NodeConfig:
    """Complete cRIO Node configuration."""
    # Identity
    node_id: str = "crio-001"
    device_name: str = "cRIO1"

    # Scan rates
    scan_rate_hz: float = 4.0
    publish_rate_hz: float = 4.0

    # MQTT
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "nisystem"

    # Timing
    heartbeat_interval_s: float = 5.0

    # Hardware
    use_mock_hardware: bool = False

    # Channels
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeConfig':
        """Create from dictionary (e.g., from JSON)."""
        channels = {}

        # Parse channels
        for name, ch_data in data.get('channels', {}).items():
            channels[name] = ChannelConfig.from_dict(name, ch_data)

        # Get system settings
        system = data.get('system', {})

        return cls(
            node_id=system.get('node_id', data.get('node_id', 'crio-001')),
            device_name=system.get('device_name', data.get('device_name', 'cRIO1')),
            scan_rate_hz=system.get('scan_rate_hz', data.get('scan_rate_hz', 4.0)),
            publish_rate_hz=system.get('publish_rate_hz', data.get('publish_rate_hz', 4.0)),
            mqtt_broker=system.get('mqtt_broker', system.get('mqtt_host',
                         data.get('mqtt_broker', data.get('mqtt_host', 'localhost')))),
            mqtt_port=system.get('mqtt_port', data.get('mqtt_port', 1883)),
            mqtt_username=system.get('mqtt_username', data.get('mqtt_username')),
            mqtt_password=system.get('mqtt_password', data.get('mqtt_password')),
            mqtt_base_topic=system.get('mqtt_base_topic', data.get('mqtt_base_topic', 'nisystem')),
            heartbeat_interval_s=system.get('heartbeat_interval_s',
                                   data.get('heartbeat_interval_s', 5.0)),
            use_mock_hardware=system.get('use_mock_hardware',
                              data.get('use_mock_hardware', False)),
            channels=channels
        )

    @classmethod
    def from_json_file(cls, path: str) -> 'NodeConfig':
        """Load configuration from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'node_id': self.node_id,
            'device_name': self.device_name,
            'scan_rate_hz': self.scan_rate_hz,
            'publish_rate_hz': self.publish_rate_hz,
            'mqtt_broker': self.mqtt_broker,
            'mqtt_port': self.mqtt_port,
            'mqtt_username': self.mqtt_username,
            'mqtt_base_topic': self.mqtt_base_topic,
            'heartbeat_interval_s': self.heartbeat_interval_s,
            'use_mock_hardware': self.use_mock_hardware,
            'channels': {
                name: {
                    'physical_channel': ch.physical_channel,
                    'channel_type': ch.channel_type,
                    'scale_slope': ch.scale_slope,
                    'scale_offset': ch.scale_offset,
                    'scale_type': ch.scale_type,
                    'four_twenty_scaling': ch.four_twenty_scaling,
                    'eng_units_min': ch.eng_units_min,
                    'eng_units_max': ch.eng_units_max,
                    'pre_scaled_min': ch.pre_scaled_min,
                    'pre_scaled_max': ch.pre_scaled_max,
                    'scaled_min': ch.scaled_min,
                    'scaled_max': ch.scaled_max,
                    'thermocouple_type': ch.thermocouple_type,
                    'cjc_source': ch.cjc_source,
                    'cjc_value': ch.cjc_value,
                    'rtd_type': ch.rtd_type,
                    'rtd_wiring': ch.rtd_wiring,
                    'rtd_current': ch.rtd_current,
                    'invert': ch.invert,
                    'default_value': ch.default_value,
                    'alarm_enabled': ch.alarm_enabled,
                    'hihi_limit': ch.hihi_limit,
                    'hi_limit': ch.hi_limit,
                    'lo_limit': ch.lo_limit,
                    'lolo_limit': ch.lolo_limit,
                    'resistance_range': ch.resistance_range,
                    'resistance_wiring': ch.resistance_wiring,
                    'counter_mode': ch.counter_mode,
                    'counter_edge': ch.counter_edge,
                    'counter_min_freq': ch.counter_min_freq,
                    'counter_max_freq': ch.counter_max_freq,
                    'pulse_frequency': ch.pulse_frequency,
                    'pulse_duty_cycle': ch.pulse_duty_cycle,
                    'pulse_idle_state': ch.pulse_idle_state,
                    'relay_type': ch.relay_type,
                    'momentary_pulse_ms': ch.momentary_pulse_ms
                }
                for name, ch in self.channels.items()
            }
        }

    def get_channels_by_type(self, channel_type: str) -> Dict[str, ChannelConfig]:
        """Get channels of a specific type."""
        return {
            name: ch for name, ch in self.channels.items()
            if ch.channel_type == channel_type
        }

    def get_input_channels(self) -> Dict[str, ChannelConfig]:
        """Get all input channels."""
        return {
            name: ch for name, ch in self.channels.items()
            if 'input' in ch.channel_type
        }

    def get_output_channels(self) -> Dict[str, ChannelConfig]:
        """Get all output channels."""
        return {
            name: ch for name, ch in self.channels.items()
            if 'output' in ch.channel_type
        }


def load_config(path: Optional[str] = None, **overrides) -> NodeConfig:
    """
    Load configuration with priority:
    1. Explicit overrides
    2. Config file (if provided)
    3. Environment variables
    4. Defaults
    """
    config_data = {}

    # Load from file if provided
    if path and os.path.exists(path):
        logger.info(f"Loading config from {path}")
        with open(path, 'r') as f:
            config_data = json.load(f)
        # Auto-migrate older config versions
        config_data, migrations = migrate_crio_config(config_data)
        if migrations:
            logger.info(f"Config migrated: {' -> '.join(migrations)}")

    # Override from environment
    env_overrides = {
        'mqtt_broker': os.environ.get('CRIO_MQTT_BROKER'),
        'mqtt_port': os.environ.get('CRIO_MQTT_PORT'),
        'node_id': os.environ.get('CRIO_NODE_ID'),
    }

    for key, value in env_overrides.items():
        if value is not None:
            if key == 'mqtt_port':
                value = int(value)
            config_data[key] = value

    # Apply explicit overrides
    config_data.update(overrides)

    return NodeConfig.from_dict(config_data)


def apply_scaling(ch_config, raw_value: float) -> float:
    """Module-level convenience wrapper for ChannelConfig.apply_scaling."""
    return ChannelConfig.apply_scaling(raw_value, ch_config)


def validate_scaling(ch_config: 'ChannelConfig') -> List[str]:
    """Validate scaling configuration and return list of warnings.

    Detects conditions where scaling inverts signal direction, which can
    confuse safety limits (e.g., a high raw value producing a low engineering
    value would trigger a LO alarm instead of HI).

    Returns list of warning strings. Empty list means no issues.
    """
    warnings = []

    # Check linear scaling inversion
    if ch_config.scale_slope < 0:
        warnings.append(
            f"Channel {ch_config.name}: negative scale_slope ({ch_config.scale_slope}) "
            f"inverts signal direction. Verify safety limits account for inversion."
        )
    if ch_config.scale_slope == 0 and ch_config.scale_type == 'linear':
        warnings.append(
            f"Channel {ch_config.name}: scale_slope is 0 — all values will "
            f"map to {ch_config.scale_offset}. Check if this is intentional."
        )

    # Check map scaling inversion
    if (ch_config.scale_type == 'map' and
            ch_config.pre_scaled_min is not None and
            ch_config.pre_scaled_max is not None and
            ch_config.scaled_min is not None and
            ch_config.scaled_max is not None):
        raw_inverted = ch_config.pre_scaled_min > ch_config.pre_scaled_max
        eng_inverted = ch_config.scaled_min > ch_config.scaled_max
        if raw_inverted or eng_inverted:
            warnings.append(
                f"Channel {ch_config.name}: map scaling has inverted range "
                f"(raw: {ch_config.pre_scaled_min}->{ch_config.pre_scaled_max}, "
                f"eng: {ch_config.scaled_min}->{ch_config.scaled_max}). "
                f"Verify safety limits account for inversion."
            )

    # Check 4-20mA scaling inversion
    if (ch_config.four_twenty_scaling and
            ch_config.eng_units_min is not None and
            ch_config.eng_units_max is not None):
        if ch_config.eng_units_min > ch_config.eng_units_max:
            warnings.append(
                f"Channel {ch_config.name}: 4-20mA scaling is inverted "
                f"(min={ch_config.eng_units_min} > max={ch_config.eng_units_max}). "
                f"Verify safety limits account for inversion."
            )

    return warnings


def find_config_file() -> Optional[str]:
    """Find configuration file in standard locations."""
    search_paths = [
        '/home/admin/nisystem/crio_config.json',  # Primary - matches save location
        '/home/admin/nisystem/config.json',        # Legacy fallback
        '/home/admin/config.json',
        './crio_config.json',
        './config.json',
    ]

    for path in search_paths:
        if os.path.exists(path):
            return path

    return None
