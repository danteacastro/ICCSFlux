"""
Configuration Module for CFP Node V2

Handles loading and parsing configuration from:
- JSON config files (cfp_config.json)
- Config push from DAQ service (MQTT config/full)
- Command line arguments / environment variables

Config versioning:
  1.0  Initial release (legacy monolithic format)
  2.0  Modular architecture (v2 format, TLS/auth fields, alarm limits)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger('CFPNode')

CFP_CONFIG_VERSIONS = ["1.0", "2.0"]
CURRENT_CFP_CONFIG_VERSION = "2.0"

@dataclass
class CFPChannelConfig:
    """Configuration for a single CFP channel (Modbus-based)."""
    name: str
    address: int                        # Modbus register/coil address
    register_type: str = 'holding'      # holding, input, coil, discrete
    data_type: str = 'int16'            # int16, uint16, int32, uint32, float32, bool
    slave_id: int = 1                   # Modbus slave/unit ID

    # Scaling (linear: y = mx + b)
    scale: float = 1.0
    offset: float = 0.0

    # Channel characteristics
    unit: str = ''
    writable: bool = False
    channel_type: str = 'voltage_input'  # For safety manager compatibility
    default_value: float = 0.0

    # Alarm limits (ISA-18.2)
    hihi_limit: Optional[float] = None
    hi_limit: Optional[float] = None
    lo_limit: Optional[float] = None
    lolo_limit: Optional[float] = None
    alarm_enabled: bool = False
    alarm_deadband: float = 0.0
    alarm_delay_sec: float = 0.0

    # Safety
    safety_action: Optional[str] = None

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'CFPChannelConfig':
        """Create from dictionary. Accepts both v1 (flat) and v2 (config push) formats."""
        return cls(
            name=name,
            address=data.get('address', 0),
            register_type=data.get('register_type', 'holding'),
            data_type=data.get('data_type', 'int16'),
            slave_id=data.get('slave_id', data.get('modbus_slave_id', 1)),
            scale=data.get('scale', data.get('scale_slope', 1.0)),
            offset=data.get('offset', data.get('scale_offset', 0.0)),
            unit=data.get('unit', data.get('units', '')),
            writable=data.get('writable', False),
            channel_type=data.get('channel_type', 'voltage_input'),
            default_value=data.get('default_value', 0.0),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
            alarm_enabled=data.get('alarm_enabled', False),
            alarm_deadband=data.get('alarm_deadband', 0.0),
            alarm_delay_sec=data.get('alarm_delay_sec', 0.0),
            safety_action=data.get('safety_action'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        d = {
            'name': self.name,
            'address': self.address,
            'register_type': self.register_type,
            'data_type': self.data_type,
            'slave_id': self.slave_id,
            'scale': self.scale,
            'offset': self.offset,
            'unit': self.unit,
            'writable': self.writable,
            'channel_type': self.channel_type,
            'default_value': self.default_value,
            'alarm_enabled': self.alarm_enabled,
            'alarm_deadband': self.alarm_deadband,
            'alarm_delay_sec': self.alarm_delay_sec,
        }
        if self.hihi_limit is not None:
            d['hihi_limit'] = self.hihi_limit
        if self.hi_limit is not None:
            d['hi_limit'] = self.hi_limit
        if self.lo_limit is not None:
            d['lo_limit'] = self.lo_limit
        if self.lolo_limit is not None:
            d['lolo_limit'] = self.lolo_limit
        if self.safety_action:
            d['safety_action'] = self.safety_action
        return d

@dataclass
class CFPModuleConfig:
    """Configuration for a cFP I/O module."""
    slot: int
    module_type: str                     # e.g., 'cFP-AI-110', 'cFP-AO-210'
    base_address: int
    channels: List[CFPChannelConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CFPModuleConfig':
        """Create from dictionary."""
        channels = []
        for ch_data in data.get('channels', []):
            ch_name = ch_data.get('name', f"CH_{data.get('slot', 0)}_{len(channels)}")
            channels.append(CFPChannelConfig.from_dict(ch_name, ch_data))
        return cls(
            slot=data.get('slot', 0),
            module_type=data.get('module_type', ''),
            base_address=data.get('base_address', 0),
            channels=channels,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'slot': self.slot,
            'module_type': self.module_type,
            'base_address': self.base_address,
            'channels': [ch.to_dict() for ch in self.channels],
        }

@dataclass
class CFPNodeConfig:
    """Complete CFP Node configuration."""
    node_id: str = 'cfp-001'
    device_name: str = 'cFP1'

    # CFP hardware connection
    cfp_host: str = '192.168.1.30'
    cfp_port: int = 502
    slave_id: int = 1

    # Scan rates
    scan_rate_hz: float = 1.0
    publish_rate_hz: float = 1.0

    # MQTT
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 8883           # TLS port by default
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = 'nisystem'
    tls_enabled: bool = True
    tls_ca_cert: Optional[str] = None

    # Timing
    heartbeat_interval_s: float = 5.0
    timeout: float = 5.0
    retry_count: int = 3
    retry_delay: float = 1.0

    # Modules (from config file)
    modules: List[CFPModuleConfig] = field(default_factory=list)

    # Flat channel dict (built from modules, used by safety manager)
    channels: Dict[str, CFPChannelConfig] = field(default_factory=dict)

    def rebuild_channel_dict(self):
        """Rebuild flat channel dict from modules."""
        self.channels.clear()
        for module in self.modules:
            for ch in module.channels:
                self.channels[ch.name] = ch

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CFPNodeConfig':
        """Create from dictionary (config file or MQTT push)."""
        modules = []
        for mod_data in data.get('modules', []):
            modules.append(CFPModuleConfig.from_dict(mod_data))

        # Build channels from 'channels' dict if present (config push format)
        channels = {}
        for name, ch_data in data.get('channels', {}).items():
            if isinstance(ch_data, dict):
                channels[name] = CFPChannelConfig.from_dict(name, ch_data)

        config = cls(
            node_id=data.get('node_id', 'cfp-001'),
            device_name=data.get('device_name', 'cFP1'),
            cfp_host=data.get('cfp_host', '192.168.1.30'),
            cfp_port=data.get('cfp_port', 502),
            slave_id=data.get('slave_id', 1),
            scan_rate_hz=data.get('scan_rate_hz', data.get('poll_interval', 1.0)),
            publish_rate_hz=data.get('publish_rate_hz', data.get('poll_interval', 1.0)),
            mqtt_broker=data.get('mqtt_broker', 'localhost'),
            mqtt_port=data.get('mqtt_port', 8883),
            mqtt_username=data.get('mqtt_username'),
            mqtt_password=data.get('mqtt_password'),
            mqtt_base_topic=data.get('mqtt_base_topic', 'nisystem'),
            tls_enabled=data.get('tls_enabled', True),
            tls_ca_cert=data.get('tls_ca_cert'),
            heartbeat_interval_s=data.get('heartbeat_interval_s', 5.0),
            timeout=data.get('timeout', 5.0),
            retry_count=data.get('retry_count', 3),
            retry_delay=data.get('retry_delay', 1.0),
            modules=modules,
            channels=channels,
        )

        # If channels were not provided directly, build from modules
        if not config.channels and config.modules:
            config.rebuild_channel_dict()

        return config

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for saving to disk."""
        return {
            'config_version': CURRENT_CFP_CONFIG_VERSION,
            'node_id': self.node_id,
            'device_name': self.device_name,
            'cfp_host': self.cfp_host,
            'cfp_port': self.cfp_port,
            'slave_id': self.slave_id,
            'scan_rate_hz': self.scan_rate_hz,
            'publish_rate_hz': self.publish_rate_hz,
            'mqtt_broker': self.mqtt_broker,
            'mqtt_port': self.mqtt_port,
            'mqtt_username': self.mqtt_username,
            'mqtt_password': self.mqtt_password,
            'mqtt_base_topic': self.mqtt_base_topic,
            'tls_enabled': self.tls_enabled,
            'tls_ca_cert': self.tls_ca_cert,
            'heartbeat_interval_s': self.heartbeat_interval_s,
            'timeout': self.timeout,
            'retry_count': self.retry_count,
            'retry_delay': self.retry_delay,
            'modules': [mod.to_dict() for mod in self.modules],
        }

def migrate_cfp_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate config from older versions to current format.
    v1.0 -> v2.0: Add TLS/auth fields, alarm limits, slave_id per channel.
    """
    version = data.get('config_version', '1.0')

    if version == '1.0':
        # Add v2.0 fields with safe defaults
        data.setdefault('mqtt_port', 8883)
        data.setdefault('tls_enabled', False)  # Don't break existing setups
        data.setdefault('tls_ca_cert', None)
        data.setdefault('mqtt_username', None)
        data.setdefault('mqtt_password', None)
        data.setdefault('slave_id', 1)
        data.setdefault('scan_rate_hz', data.get('poll_interval', 1.0))
        data.setdefault('publish_rate_hz', data.get('poll_interval', 1.0))
        data.setdefault('heartbeat_interval_s', 5.0)

        # Add slave_id to each channel in modules
        for module in data.get('modules', []):
            for ch in module.get('channels', []):
                ch.setdefault('slave_id', 1)
                ch.setdefault('alarm_enabled', False)

        data['config_version'] = '2.0'
        logger.info("Migrated CFP config from v1.0 to v2.0")

    return data

# Standard search paths for config file
_CONFIG_SEARCH_PATHS = [
    os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cfp_config.json'),
    os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'cfp_config.json'),
    './cfp_config.json',
    './config.json',
]

def find_config_file() -> Optional[str]:
    """Find the first existing config file from standard search paths."""
    for path in _CONFIG_SEARCH_PATHS:
        if Path(path).exists():
            return path
    return None

def load_config(path: Optional[str] = None, **overrides) -> CFPNodeConfig:
    """
    Load CFP node configuration with priority chain:
    1. JSON config file (with auto-migration)
    2. Environment variables
    3. Explicit overrides

    Args:
        path: Path to config file (auto-detected if None)
        **overrides: Explicit config overrides

    Returns:
        CFPNodeConfig instance
    """
    data = {}

    # 1. Load from file
    config_path = path or find_config_file()
    if config_path and Path(config_path).exists():
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
            data = migrate_cfp_config(data)
            logger.info(f"Loaded config from {config_path}")
        except Exception as e:
            logger.warning(f"Could not load config from {config_path}: {e}")

    # 2. Apply environment variable overrides
    env_map = {
        'CFP_HOST': 'cfp_host',
        'CFP_PORT': ('cfp_port', int),
        'CFP_SLAVE_ID': ('slave_id', int),
        'CFP_MQTT_BROKER': 'mqtt_broker',
        'CFP_MQTT_PORT': ('mqtt_port', int),
        'CFP_NODE_ID': 'node_id',
        'MQTT_USERNAME': 'mqtt_username',
        'MQTT_PASSWORD': 'mqtt_password',
        'CFP_TLS_CA_CERT': 'tls_ca_cert',
        'CFP_SCAN_RATE_HZ': ('scan_rate_hz', float),
    }

    for env_var, mapping in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            if isinstance(mapping, tuple):
                key, converter = mapping
                try:
                    data[key] = converter(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {env_var}: {value}")
            else:
                data[mapping] = value

    # TLS enabled if CA cert is specified
    if data.get('tls_ca_cert') and 'tls_enabled' not in data:
        data['tls_enabled'] = True

    # 3. Apply explicit overrides
    data.update(overrides)

    return CFPNodeConfig.from_dict(data)

def save_config(config: CFPNodeConfig, path: str):
    """
    Save configuration to disk with secure permissions.

    Args:
        config: Configuration to save
        path: Output file path
    """
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.to_dict()
    tmp_path = config_path.with_suffix('.tmp')

    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename
        tmp_path.replace(config_path)

        # Secure permissions on non-Windows
        if os.name != 'nt':
            os.chmod(config_path, 0o600)

        logger.info(f"Config saved to {config_path}")
    except Exception as e:
        logger.error(f"Failed to save config to {config_path}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise
