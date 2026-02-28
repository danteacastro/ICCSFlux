"""
Configuration Module for Opto22 Node

Handles loading and parsing configuration from:
- JSON project files
- Command line arguments

Extends the cRIO config pattern with groov Manage MQTT-specific settings.

Config versioning:
  - All saved configs include a 'config_version' field.
  - On load, migrate_opto22_config() auto-upgrades old configs to the latest version.
  - Migration functions are idempotent (safe to run multiple times).
  - Version history:
      1.0  Initial release (groov MQTT + REST, channels, topic mapping)
      1.1  Added groov TLS fields
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .channel_types import ChannelType

logger = logging.getLogger('Opto22Node')

# Ordered list of config schema versions
OPTO22_CONFIG_VERSIONS = ["1.0", "1.1"]
CURRENT_OPTO22_CONFIG_VERSION = OPTO22_CONFIG_VERSIONS[-1]


def migrate_opto22_config(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Migrate Opto22 config data to the latest version.

    Returns (migrated_data, list_of_applied_migrations).
    Safe to call on already-current configs.
    """
    current = data.get('config_version', '1.0')
    if current not in OPTO22_CONFIG_VERSIONS:
        logger.warning(f"Unknown Opto22 config version '{current}', treating as 1.0")
        current = '1.0'

    from_idx = OPTO22_CONFIG_VERSIONS.index(current)
    to_idx = len(OPTO22_CONFIG_VERSIONS) - 1
    if from_idx >= to_idx:
        return data, []

    result = dict(data)
    applied = []

    for version in OPTO22_CONFIG_VERSIONS[from_idx + 1:to_idx + 1]:
        func_name = f"_migrate_opto22_to_{version.replace('.', '_')}"
        migrate_func = globals().get(func_name)
        if migrate_func:
            prev = result.get('config_version', '1.0')
            logger.info(f"Opto22 config migration: {prev} -> {version}")
            result = migrate_func(result)
            result['config_version'] = version
            applied.append(f"{prev}->{version}")

    return result, applied


def _migrate_opto22_to_1_1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.0 to 1.1.

    Changes:
    - Add groov TLS fields if missing
    """
    groov = data.get('groov', {})
    if 'mqtt_tls' not in groov:
        groov['mqtt_tls'] = False
    if 'mqtt_ca_cert' not in groov:
        groov['mqtt_ca_cert'] = None
    if groov:
        data['groov'] = groov
    return data


@dataclass
class ChannelConfig:
    """Configuration for a single channel."""
    name: str
    physical_channel: str  # groov topic suffix or REST module/channel reference
    channel_type: str

    # groov Manage MQTT topic for this channel (auto-derived if not specified)
    groov_topic: Optional[str] = None

    # groov REST API coordinates (for fallback polling)
    groov_module_index: Optional[int] = None
    groov_channel_index: Optional[int] = None

    # Scaling — linear
    scale_slope: float = 1.0
    scale_offset: float = 0.0
    scale_type: str = 'none'  # none, linear, map

    # Scaling — 4-20mA (current inputs)
    four_twenty_scaling: bool = False
    eng_units_min: Optional[float] = None
    eng_units_max: Optional[float] = None

    # Scaling — map (voltage inputs: raw range -> engineering range)
    pre_scaled_min: Optional[float] = None
    pre_scaled_max: Optional[float] = None
    scaled_min: Optional[float] = None
    scaled_max: Optional[float] = None

    # Thermocouple specific
    thermocouple_type: Optional[str] = None

    # Range
    voltage_range: float = 10.0
    current_range_ma: float = 20.0

    # Behavior
    invert: bool = False
    default_value: float = 0.0

    # Alarm limits
    hihi_limit: Optional[float] = None
    hi_limit: Optional[float] = None
    lo_limit: Optional[float] = None
    lolo_limit: Optional[float] = None
    alarm_enabled: bool = False
    alarm_deadband: float = 0.0
    alarm_delay_sec: float = 0.0
    alarm_off_delay_sec: float = 0.0
    rate_of_change_limit: Optional[float] = None
    rate_of_change_period_s: float = 60.0

    # Safety
    safety_action: Optional[Any] = None
    safety_interlock: Optional[str] = None

    # Source info
    source_type: str = 'opto22'
    source_node_id: Optional[str] = None

    def __post_init__(self):
        # Validate alarm limit ordering
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

    @staticmethod
    def apply_scaling(raw_value: float, ch_config: 'ChannelConfig') -> float:
        """Apply scaling to a raw hardware value."""
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
            if current_ma < 3.8:
                return eng_min - ((4.0 - current_ma) / 16.0) * span
            elif current_ma > 20.5:
                return eng_max + ((current_ma - 20.0) / 16.0) * span
            normalized = (current_ma - 4.0) / 16.0
            return eng_min + (normalized * span)

        # Map scaling
        if (ch_config.scale_type == 'map' and
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

        # Linear scaling
        if ch_config.scale_slope != 1.0 or ch_config.scale_offset != 0.0:
            return (raw_value * ch_config.scale_slope) + ch_config.scale_offset

        return raw_value

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ChannelConfig':
        """Create from dictionary."""
        return cls(
            name=name,
            physical_channel=data.get('physical_channel', ''),
            channel_type=data.get('channel_type', 'voltage_input'),
            groov_topic=data.get('groov_topic'),
            groov_module_index=data.get('groov_module_index'),
            groov_channel_index=data.get('groov_channel_index'),
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
            thermocouple_type=data.get('thermocouple_type'),
            voltage_range=data.get('voltage_range', 10.0),
            current_range_ma=data.get('current_range_ma', 20.0),
            invert=data.get('invert', False),
            default_value=data.get('default_value', 0.0),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
            alarm_enabled=data.get('alarm_enabled', False),
            alarm_deadband=data.get('alarm_deadband', 0.0),
            alarm_delay_sec=data.get('alarm_delay_sec', 0.0),
            alarm_off_delay_sec=data.get('alarm_off_delay_sec', 0.0),
            rate_of_change_limit=data.get('rate_of_change_limit'),
            rate_of_change_period_s=data.get('rate_of_change_period_s', 60.0),
            safety_action=data.get('safety_action'),
            safety_interlock=data.get('safety_interlock'),
            source_type=data.get('source_type', 'opto22'),
            source_node_id=data.get('source_node_id'),
        )


@dataclass
class NodeConfig:
    """Complete Opto22 Node configuration."""
    # Identity
    node_id: str = "opto22-001"
    device_name: str = "Opto22-EPIC"

    # Scan/publish rates
    scan_rate_hz: float = 4.0
    publish_rate_hz: float = 4.0

    # NISystem MQTT broker
    mqtt_broker: str = "localhost"
    mqtt_port: int = 8883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "nisystem"
    mqtt_tls_enabled: bool = True
    mqtt_tls_ca_cert: Optional[str] = None  # Path to CA certificate file

    # groov Manage MQTT broker (on the EPIC itself)
    groov_mqtt_host: str = "localhost"
    groov_mqtt_port: int = 1883
    groov_mqtt_username: Optional[str] = None
    groov_mqtt_password: Optional[str] = None
    groov_mqtt_tls: bool = False
    groov_mqtt_ca_cert: Optional[str] = None
    groov_io_topic_patterns: List[str] = field(default_factory=lambda: ["groov/io/#"])

    # groov Manage REST API (fallback)
    groov_rest_host: Optional[str] = None
    groov_rest_port: int = 443
    groov_rest_api_key: Optional[str] = None
    groov_rest_username: Optional[str] = None
    groov_rest_password: Optional[str] = None

    # Timing
    heartbeat_interval_s: float = 5.0

    # Watchdog output — toggles a digital output so external safety hardware
    # can detect the node is alive. If the pulse stops, the relay trips.
    watchdog_output_channel: Optional[str] = None
    watchdog_output_rate_hz: float = 1.0
    watchdog_output_enabled: bool = False

    # Communication watchdog — if no command/heartbeat received from PC
    # within this timeout, transition to safe state. 0 = disabled.
    comm_watchdog_timeout_s: float = 30.0

    # Channels
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    # Topic mapping: groov MQTT topic -> NISystem channel name
    topic_mapping: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeConfig':
        """Create from dictionary (e.g., from JSON project file)."""
        channels = {}
        for name, ch_data in data.get('channels', {}).items():
            channels[name] = ChannelConfig.from_dict(name, ch_data)

        system = data.get('system', {})
        groov = data.get('groov', {})

        # Build topic mapping from channels
        topic_mapping = {}
        for name, ch in channels.items():
            if ch.groov_topic:
                topic_mapping[ch.groov_topic] = name

        # Merge explicit topic_mapping from config
        topic_mapping.update(data.get('topic_mapping', {}))

        return cls(
            node_id=system.get('node_id', data.get('node_id', 'opto22-001')),
            device_name=system.get('device_name', data.get('device_name', 'Opto22-EPIC')),
            scan_rate_hz=max(0.1, min(100.0, float(system.get('scan_rate_hz', data.get('scan_rate_hz', 4.0))))),
            publish_rate_hz=max(0.1, min(100.0, float(system.get('publish_rate_hz', data.get('publish_rate_hz', 4.0))))),
            mqtt_broker=system.get('mqtt_broker', data.get('mqtt_broker', 'localhost')),
            mqtt_port=system.get('mqtt_port', data.get('mqtt_port', 8883)),
            mqtt_username=system.get('mqtt_username', data.get('mqtt_username')),
            mqtt_password=system.get('mqtt_password', data.get('mqtt_password')),
            mqtt_base_topic=system.get('mqtt_base_topic', data.get('mqtt_base_topic', 'nisystem')),
            mqtt_tls_enabled=system.get('mqtt_tls_enabled', system.get('tls_enabled',
                              data.get('mqtt_tls_enabled', data.get('tls_enabled', True)))),
            mqtt_tls_ca_cert=system.get('mqtt_tls_ca_cert', system.get('tls_ca_cert',
                              data.get('mqtt_tls_ca_cert', data.get('tls_ca_cert')))),
            groov_mqtt_host=groov.get('mqtt_host', data.get('groov_mqtt_host', 'localhost')),
            groov_mqtt_port=groov.get('mqtt_port', data.get('groov_mqtt_port', 1883)),
            groov_mqtt_username=groov.get('mqtt_username', data.get('groov_mqtt_username')),
            groov_mqtt_password=groov.get('mqtt_password', data.get('groov_mqtt_password')),
            groov_mqtt_tls=groov.get('mqtt_tls', data.get('groov_mqtt_tls', False)),
            groov_mqtt_ca_cert=groov.get('mqtt_ca_cert', data.get('groov_mqtt_ca_cert')),
            groov_io_topic_patterns=groov.get('io_topic_patterns',
                                    data.get('groov_io_topic_patterns', ['groov/io/#'])),
            groov_rest_host=groov.get('rest_host', data.get('groov_rest_host')),
            groov_rest_port=groov.get('rest_port', data.get('groov_rest_port', 443)),
            groov_rest_api_key=groov.get('rest_api_key', data.get('groov_rest_api_key')),
            groov_rest_username=groov.get('rest_username', data.get('groov_rest_username')),
            groov_rest_password=groov.get('rest_password', data.get('groov_rest_password')),
            heartbeat_interval_s=system.get('heartbeat_interval_s',
                                   data.get('heartbeat_interval_s', 5.0)),
            watchdog_output_channel=system.get('watchdog_output_channel',
                                    data.get('watchdog_output_channel')),
            watchdog_output_rate_hz=float(system.get('watchdog_output_rate_hz',
                                         data.get('watchdog_output_rate_hz', 1.0))),
            watchdog_output_enabled=system.get('watchdog_output_enabled',
                                    data.get('watchdog_output_enabled', False)),
            comm_watchdog_timeout_s=float(system.get('comm_watchdog_timeout_s',
                                         data.get('comm_watchdog_timeout_s', 30.0))),
            channels=channels,
            topic_mapping=topic_mapping,
        )

    @classmethod
    def from_json_file(cls, path: str) -> 'NodeConfig':
        """Load configuration from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)

    def get_channels_by_type(self, channel_type: str) -> Dict[str, ChannelConfig]:
        return {
            name: ch for name, ch in self.channels.items()
            if ch.channel_type == channel_type
        }

    def get_output_channels(self) -> Dict[str, ChannelConfig]:
        return {
            name: ch for name, ch in self.channels.items()
            if ChannelType.is_output(ch.channel_type)
        }

    def get_rest_channel_map(self) -> Dict[str, tuple]:
        """Get channel name -> (module_index, channel_index) for REST fallback."""
        result = {}
        for name, ch in self.channels.items():
            if ch.groov_module_index is not None and ch.groov_channel_index is not None:
                result[name] = (ch.groov_module_index, ch.groov_channel_index)
        return result


def load_config(payload: Dict[str, Any], existing_config: Optional['NodeConfig'] = None) -> 'NodeConfig':
    """Load configuration from an MQTT payload dict, using existing config as defaults.

    Called when the node receives a full config push from NISystem.
    Validates scan/publish rate bounds (0.1-100 Hz).
    """
    # Auto-migrate older config versions
    payload, migrations = migrate_opto22_config(payload)
    if migrations:
        logger.info(f"Config payload migrated: {' -> '.join(migrations)}")

    # Start from existing config values as defaults
    if existing_config:
        # Merge: payload overrides existing config
        system = payload.get('system', {})
        groov = payload.get('groov', {})

        # Use existing values as fallback for system settings
        merged = {
            'system': {
                'node_id': system.get('node_id', existing_config.node_id),
                'device_name': system.get('device_name', existing_config.device_name),
                'scan_rate_hz': system.get('scan_rate_hz', payload.get('scan_rate_hz', existing_config.scan_rate_hz)),
                'publish_rate_hz': system.get('publish_rate_hz', payload.get('publish_rate_hz', existing_config.publish_rate_hz)),
                'mqtt_broker': system.get('mqtt_broker', existing_config.mqtt_broker),
                'mqtt_port': system.get('mqtt_port', existing_config.mqtt_port),
                'mqtt_username': system.get('mqtt_username', existing_config.mqtt_username),
                'mqtt_password': system.get('mqtt_password', existing_config.mqtt_password),
                'mqtt_base_topic': system.get('mqtt_base_topic', existing_config.mqtt_base_topic),
                'mqtt_tls_enabled': system.get('mqtt_tls_enabled', existing_config.mqtt_tls_enabled),
                'mqtt_tls_ca_cert': system.get('mqtt_tls_ca_cert', existing_config.mqtt_tls_ca_cert),
                'heartbeat_interval_s': system.get('heartbeat_interval_s', existing_config.heartbeat_interval_s),
                'watchdog_output_channel': system.get('watchdog_output_channel', existing_config.watchdog_output_channel),
                'watchdog_output_rate_hz': system.get('watchdog_output_rate_hz', existing_config.watchdog_output_rate_hz),
                'watchdog_output_enabled': system.get('watchdog_output_enabled', existing_config.watchdog_output_enabled),
            },
            'groov': {
                'mqtt_host': groov.get('mqtt_host', existing_config.groov_mqtt_host),
                'mqtt_port': groov.get('mqtt_port', existing_config.groov_mqtt_port),
                'mqtt_username': groov.get('mqtt_username', existing_config.groov_mqtt_username),
                'mqtt_password': groov.get('mqtt_password', existing_config.groov_mqtt_password),
                'mqtt_tls': groov.get('mqtt_tls', existing_config.groov_mqtt_tls),
                'mqtt_ca_cert': groov.get('mqtt_ca_cert', existing_config.groov_mqtt_ca_cert),
                'io_topic_patterns': groov.get('io_topic_patterns', existing_config.groov_io_topic_patterns),
                'rest_host': groov.get('rest_host', existing_config.groov_rest_host),
                'rest_port': groov.get('rest_port', existing_config.groov_rest_port),
                'rest_api_key': groov.get('rest_api_key', existing_config.groov_rest_api_key),
                'rest_username': groov.get('rest_username', existing_config.groov_rest_username),
                'rest_password': groov.get('rest_password', existing_config.groov_rest_password),
            },
            'channels': payload.get('channels', {}),
            'topic_mapping': payload.get('topic_mapping', {}),
        }
        config = NodeConfig.from_dict(merged)
    else:
        config = NodeConfig.from_dict(payload)

    # Validate rate bounds (0.1-100 Hz) — matches cRIO and PC DAQ
    if config.scan_rate_hz > 100.0:
        logger.warning(f"scan_rate_hz={config.scan_rate_hz} capped to 100.0 Hz")
        config.scan_rate_hz = 100.0
    if config.scan_rate_hz < 0.1:
        logger.warning(f"scan_rate_hz={config.scan_rate_hz} floored to 0.1 Hz")
        config.scan_rate_hz = 0.1
    if config.publish_rate_hz > 100.0:
        logger.warning(f"publish_rate_hz={config.publish_rate_hz} capped to 100.0 Hz")
        config.publish_rate_hz = 100.0
    if config.publish_rate_hz < 0.1:
        logger.warning(f"publish_rate_hz={config.publish_rate_hz} floored to 0.1 Hz")
        config.publish_rate_hz = 0.1

    return config


def save_config(config: 'NodeConfig', path: str) -> None:
    """Save configuration to a JSON file for PC disconnect survival."""
    data = {
        'config_version': CURRENT_OPTO22_CONFIG_VERSION,
        'system': {
            'node_id': config.node_id,
            'device_name': config.device_name,
            'scan_rate_hz': config.scan_rate_hz,
            'publish_rate_hz': config.publish_rate_hz,
            'mqtt_broker': config.mqtt_broker,
            'mqtt_port': config.mqtt_port,
            'mqtt_username': config.mqtt_username,
            'mqtt_password': config.mqtt_password,
            'mqtt_base_topic': config.mqtt_base_topic,
            'mqtt_tls_enabled': config.mqtt_tls_enabled,
            'mqtt_tls_ca_cert': config.mqtt_tls_ca_cert,
            'heartbeat_interval_s': config.heartbeat_interval_s,
            'watchdog_output_channel': config.watchdog_output_channel,
            'watchdog_output_rate_hz': config.watchdog_output_rate_hz,
            'watchdog_output_enabled': config.watchdog_output_enabled,
        },
        'groov': {
            'mqtt_host': config.groov_mqtt_host,
            'mqtt_port': config.groov_mqtt_port,
            'mqtt_username': config.groov_mqtt_username,
            'mqtt_password': config.groov_mqtt_password,
            'mqtt_tls': config.groov_mqtt_tls,
            'mqtt_ca_cert': config.groov_mqtt_ca_cert,
            'io_topic_patterns': config.groov_io_topic_patterns,
            'rest_host': config.groov_rest_host,
            'rest_port': config.groov_rest_port,
            'rest_api_key': config.groov_rest_api_key,
            'rest_username': config.groov_rest_username,
            'rest_password': config.groov_rest_password,
        },
        'channels': {
            name: {
                'physical_channel': ch.physical_channel,
                'channel_type': ch.channel_type,
                'groov_topic': ch.groov_topic,
                'groov_module_index': ch.groov_module_index,
                'groov_channel_index': ch.groov_channel_index,
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
                'voltage_range': ch.voltage_range,
                'current_range_ma': ch.current_range_ma,
                'invert': ch.invert,
                'default_value': ch.default_value,
                'hihi_limit': ch.hihi_limit,
                'hi_limit': ch.hi_limit,
                'lo_limit': ch.lo_limit,
                'lolo_limit': ch.lolo_limit,
                'alarm_enabled': ch.alarm_enabled,
                'alarm_deadband': ch.alarm_deadband,
                'alarm_delay_sec': ch.alarm_delay_sec,
                'alarm_off_delay_sec': ch.alarm_off_delay_sec,
                'rate_of_change_limit': ch.rate_of_change_limit,
                'rate_of_change_period_s': ch.rate_of_change_period_s,
                'safety_action': ch.safety_action,
                'safety_interlock': ch.safety_interlock,
                'source_type': ch.source_type,
                'source_node_id': ch.source_node_id,
            }
            for name, ch in config.channels.items()
        },
        'topic_mapping': config.topic_mapping,
    }

    # Filter out None values from channel dicts for cleaner JSON
    for ch_name in data['channels']:
        data['channels'][ch_name] = {
            k: v for k, v in data['channels'][ch_name].items() if v is not None
        }

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(path_obj, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"Config saved to {path}")
