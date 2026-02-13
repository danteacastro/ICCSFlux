"""
Configuration Module for Opto22 Node

Handles loading and parsing configuration from:
- JSON project files
- Command line arguments

Extends the cRIO config pattern with groov Manage MQTT-specific settings.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List

from .channel_types import ChannelType

logger = logging.getLogger('Opto22Node')


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
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "nisystem"

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
            scan_rate_hz=system.get('scan_rate_hz', data.get('scan_rate_hz', 4.0)),
            publish_rate_hz=system.get('publish_rate_hz', data.get('publish_rate_hz', 4.0)),
            mqtt_broker=system.get('mqtt_broker', data.get('mqtt_broker', 'localhost')),
            mqtt_port=system.get('mqtt_port', data.get('mqtt_port', 1883)),
            mqtt_username=system.get('mqtt_username', data.get('mqtt_username')),
            mqtt_password=system.get('mqtt_password', data.get('mqtt_password')),
            mqtt_base_topic=system.get('mqtt_base_topic', data.get('mqtt_base_topic', 'nisystem')),
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
