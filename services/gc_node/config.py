"""
Configuration for GC Node Service.

Dataclasses for file watching, Modbus, serial, and overall node configuration.

Config versioning:
  - All saved configs include a 'config_version' field.
  - On load, migrate_config() auto-upgrades old configs to the latest version.
  - Migration functions are idempotent (safe to run multiple times).
  - Version history:
      1.0  Initial release (file_watcher, modbus, serial, analysis, channels)
      1.1  Added scheduler section, TLS fields
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('GCNode')

# Ordered list of config schema versions
CONFIG_VERSIONS = ["1.0", "1.1"]
CURRENT_CONFIG_VERSION = CONFIG_VERSIONS[-1]


def migrate_config(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Migrate config data to the latest version.

    Returns (migrated_data, list_of_applied_migrations).
    Safe to call on already-current configs (returns unchanged).
    """
    current = data.get('config_version', '1.0')
    if current not in CONFIG_VERSIONS:
        logger.warning(f"Unknown config version '{current}', treating as 1.0")
        current = '1.0'

    from_idx = CONFIG_VERSIONS.index(current)
    to_idx = len(CONFIG_VERSIONS) - 1
    if from_idx >= to_idx:
        return data, []

    result = dict(data)
    applied = []

    for version in CONFIG_VERSIONS[from_idx + 1:to_idx + 1]:
        func_name = f"_migrate_config_to_{version.replace('.', '_')}"
        migrate_func = globals().get(func_name)
        if migrate_func:
            prev = result.get('config_version', '1.0')
            logger.info(f"GC config migration: {prev} -> {version}")
            result = migrate_func(result)
            result['config_version'] = version
            applied.append(f"{prev}->{version}")

    return result, applied


def _migrate_config_to_1_1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.0 to 1.1.

    Changes:
    - Add 'scheduler' section if missing
    - Add TLS fields to system section if missing
    """
    if 'scheduler' not in data:
        data['scheduler'] = {}

    system = data.get('system', data)
    if 'mqtt_tls_enabled' not in system:
        system['mqtt_tls_enabled'] = False
    if 'mqtt_tls_ca_cert' not in system:
        system['mqtt_tls_ca_cert'] = None

    return data


@dataclass
class FileWatcherConfig:
    """Configuration for CSV/TXT file watching source."""
    enabled: bool = False
    watch_directory: str = ""
    file_pattern: str = "*.csv"
    poll_interval_s: float = 5.0
    parse_template: str = "generic_csv"
    delimiter: str = ","
    header_rows: int = 1
    encoding: str = "utf-8"
    column_mapping: Dict[str, str] = field(default_factory=dict)
    archive_processed: bool = False
    processed_dir: str = ""
    timestamp_column: str = ""
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FileWatcherConfig':
        return cls(
            enabled=data.get('enabled', False),
            watch_directory=data.get('watch_directory', ''),
            file_pattern=data.get('file_pattern', '*.csv'),
            poll_interval_s=float(data.get('poll_interval_s', 5.0)),
            parse_template=data.get('parse_template', 'generic_csv'),
            delimiter=data.get('delimiter', ','),
            header_rows=int(data.get('header_rows', 1)),
            encoding=data.get('encoding', 'utf-8'),
            column_mapping=data.get('column_mapping', {}),
            archive_processed=data.get('archive_processed', False),
            processed_dir=data.get('processed_dir', ''),
            timestamp_column=data.get('timestamp_column', ''),
            timestamp_format=data.get('timestamp_format', '%Y-%m-%d %H:%M:%S'),
        )


@dataclass
class ModbusSourceConfig:
    """Configuration for Modbus data source."""
    enabled: bool = False
    connection_type: str = "tcp"
    ip_address: str = ""
    port: int = 502
    serial_port: str = ""
    baudrate: int = 9600
    parity: str = "E"
    stopbits: int = 1
    bytesize: int = 8
    slave_id: int = 1
    timeout: float = 2.0
    poll_interval_s: float = 5.0
    registers: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModbusSourceConfig':
        return cls(
            enabled=data.get('enabled', False),
            connection_type=data.get('connection_type', 'tcp'),
            ip_address=data.get('ip_address', ''),
            port=int(data.get('port', 502)),
            serial_port=data.get('serial_port', ''),
            baudrate=int(data.get('baudrate', 9600)),
            parity=data.get('parity', 'E'),
            stopbits=int(data.get('stopbits', 1)),
            bytesize=int(data.get('bytesize', 8)),
            slave_id=int(data.get('slave_id', 1)),
            timeout=float(data.get('timeout', 2.0)),
            poll_interval_s=float(data.get('poll_interval_s', 5.0)),
            registers=data.get('registers', []),
        )


@dataclass
class SerialSourceConfig:
    """Configuration for raw serial data source."""
    enabled: bool = False
    port: str = "COM1"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 2.0
    frame_end: str = "\r\n"
    protocol: str = "line"
    parse_template: str = "generic_csv"
    delimiter: str = ","
    column_mapping: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SerialSourceConfig':
        return cls(
            enabled=data.get('enabled', False),
            port=data.get('port', 'COM1'),
            baudrate=int(data.get('baudrate', 9600)),
            parity=data.get('parity', 'N'),
            stopbits=int(data.get('stopbits', 1)),
            bytesize=int(data.get('bytesize', 8)),
            timeout=float(data.get('timeout', 2.0)),
            frame_end=data.get('frame_end', '\r\n'),
            protocol=data.get('protocol', 'line'),
            parse_template=data.get('parse_template', 'generic_csv'),
            delimiter=data.get('delimiter', ','),
            column_mapping=data.get('column_mapping', {}),
        )


@dataclass
class AnalysisSourceConfig:
    """Configuration for built-in GC analysis engine (raw detector signal)."""
    enabled: bool = False
    mode: str = 'streaming'          # 'streaming' (raw voltage via serial) or 'parsed' (result frames)
    sample_rate_hz: float = 10.0     # Expected detector sample rate
    method_file: str = ''            # Path to AnalysisMethod JSON
    library_file: str = ''           # Path to PeakLibrary JSON (optional)
    run_duration_s: float = 300.0    # Max run duration before auto-finish
    inject_trigger: str = 'mqtt'     # 'mqtt', 'serial_marker', 'threshold', 'timer'
    inject_marker: str = 'INJECT'    # Serial string that triggers run start
    inject_threshold_v: float = 0.1  # Voltage threshold for auto-inject detection
    inject_debounce_s: float = 2.0   # Debounce time after inject trigger
    auto_run_interval_s: float = 0.0 # Timer-based auto-run (0 = disabled)
    publish_raw_chromatogram: bool = True  # Publish raw (time,voltage) after run
    progress_interval_s: float = 10.0     # How often to publish run progress

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisSourceConfig':
        return cls(
            enabled=data.get('enabled', False),
            mode=data.get('mode', 'streaming'),
            sample_rate_hz=float(data.get('sample_rate_hz', 10.0)),
            method_file=data.get('method_file', ''),
            library_file=data.get('library_file', ''),
            run_duration_s=float(data.get('run_duration_s', 300.0)),
            inject_trigger=data.get('inject_trigger', 'mqtt'),
            inject_marker=data.get('inject_marker', 'INJECT'),
            inject_threshold_v=float(data.get('inject_threshold_v', 0.1)),
            inject_debounce_s=float(data.get('inject_debounce_s', 2.0)),
            auto_run_interval_s=float(data.get('auto_run_interval_s', 0.0)),
            publish_raw_chromatogram=data.get('publish_raw_chromatogram', True),
            progress_interval_s=float(data.get('progress_interval_s', 10.0)),
        )


@dataclass
class GCChannelConfig:
    """Configuration for a GC-derived channel."""
    name: str = ""
    source_field: str = ""
    unit: str = ""
    scale: float = 1.0
    offset: float = 0.0
    alarm_enabled: bool = False
    hihi_limit: Optional[float] = None
    hi_limit: Optional[float] = None
    lo_limit: Optional[float] = None
    lolo_limit: Optional[float] = None

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'GCChannelConfig':
        return cls(
            name=name,
            source_field=data.get('source_field', name),
            unit=data.get('unit', ''),
            scale=float(data.get('scale', 1.0)),
            offset=float(data.get('offset', 0.0)),
            alarm_enabled=data.get('alarm_enabled', False),
            hihi_limit=data.get('hihi_limit'),
            hi_limit=data.get('hi_limit'),
            lo_limit=data.get('lo_limit'),
            lolo_limit=data.get('lolo_limit'),
        )


@dataclass
class SchedulerConfig:
    """Configuration for the run scheduler."""
    enabled: bool = False
    auto_blank_interval: int = 10
    auto_cal_interval: int = 0
    auto_blank_method: str = ""
    auto_cal_method: str = ""
    max_queue_size: int = 200

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SchedulerConfig':
        return cls(
            enabled=data.get('enabled', False),
            auto_blank_interval=int(data.get('auto_blank_interval', 10)),
            auto_cal_interval=int(data.get('auto_cal_interval', 0)),
            auto_blank_method=data.get('auto_blank_method', ''),
            auto_cal_method=data.get('auto_cal_method', ''),
            max_queue_size=int(data.get('max_queue_size', 200)),
        )


@dataclass
class NodeConfig:
    """Complete GC node configuration."""
    node_id: str = "gc-001"
    node_name: str = "GC Analyzer 1"
    gc_type: str = ""
    mqtt_broker: str = "10.10.10.1"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "nisystem"
    mqtt_tls_enabled: bool = False
    mqtt_tls_ca_cert: Optional[str] = None
    heartbeat_interval_s: float = 5.0
    publish_rate_hz: float = 0.2
    file_watcher: FileWatcherConfig = field(default_factory=FileWatcherConfig)
    modbus_source: ModbusSourceConfig = field(default_factory=ModbusSourceConfig)
    serial_source: SerialSourceConfig = field(default_factory=SerialSourceConfig)
    analysis_source: AnalysisSourceConfig = field(default_factory=AnalysisSourceConfig)
    scheduler: 'SchedulerConfig' = field(default_factory=lambda: SchedulerConfig())
    channels: Dict[str, GCChannelConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeConfig':
        system = data.get('system', data)
        channels = {}
        for ch_name, ch_data in data.get('channels', {}).items():
            channels[ch_name] = GCChannelConfig.from_dict(ch_name, ch_data)

        return cls(
            node_id=system.get('node_id', data.get('node_id', 'gc-001')),
            node_name=system.get('node_name', data.get('node_name', 'GC Analyzer 1')),
            gc_type=system.get('gc_type', data.get('gc_type', '')),
            mqtt_broker=system.get('mqtt_broker', data.get('mqtt_broker', '10.10.10.1')),
            mqtt_port=int(system.get('mqtt_port', data.get('mqtt_port', 1883))),
            mqtt_username=system.get('mqtt_username', data.get('mqtt_username')),
            mqtt_password=system.get('mqtt_password', data.get('mqtt_password')),
            mqtt_base_topic=system.get('mqtt_base_topic', data.get('mqtt_base_topic', 'nisystem')),
            mqtt_tls_enabled=bool(system.get('mqtt_tls_enabled', data.get('mqtt_tls_enabled', False))),
            mqtt_tls_ca_cert=system.get('mqtt_tls_ca_cert', data.get('mqtt_tls_ca_cert')),
            heartbeat_interval_s=float(system.get('heartbeat_interval_s', data.get('heartbeat_interval_s', 5.0))),
            publish_rate_hz=max(0.01, min(4.0, float(system.get('publish_rate_hz', data.get('publish_rate_hz', 0.2))))),
            file_watcher=FileWatcherConfig.from_dict(data.get('file_watcher', {})),
            modbus_source=ModbusSourceConfig.from_dict(data.get('modbus_source', {})),
            serial_source=SerialSourceConfig.from_dict(data.get('serial_source', {})),
            analysis_source=AnalysisSourceConfig.from_dict(data.get('analysis_source', {})),
            scheduler=SchedulerConfig.from_dict(data.get('scheduler', {})),
            channels=channels,
        )

    @classmethod
    def from_json_file(cls, path: str) -> 'NodeConfig':
        with open(path, 'r') as f:
            data = json.load(f)
        # Auto-migrate older config versions
        data, migrations = migrate_config(data)
        if migrations:
            logger.info(f"Config migrated: {' -> '.join(migrations)}")
        return cls.from_dict(data)


def load_config(payload: Dict[str, Any], existing_config: Optional[NodeConfig] = None) -> NodeConfig:
    """Load configuration from MQTT payload, merging with existing config as defaults."""
    # Auto-migrate older config versions
    payload, migrations = migrate_config(payload)
    if migrations:
        logger.info(f"Config payload migrated: {' -> '.join(migrations)}")

    if existing_config:
        system = payload.get('system', {})
        merged = {
            'system': {
                'node_id': system.get('node_id', existing_config.node_id),
                'node_name': system.get('node_name', existing_config.node_name),
                'gc_type': system.get('gc_type', existing_config.gc_type),
                'mqtt_broker': system.get('mqtt_broker', existing_config.mqtt_broker),
                'mqtt_port': system.get('mqtt_port', existing_config.mqtt_port),
                'mqtt_username': system.get('mqtt_username', existing_config.mqtt_username),
                'mqtt_password': system.get('mqtt_password', existing_config.mqtt_password),
                'mqtt_base_topic': system.get('mqtt_base_topic', existing_config.mqtt_base_topic),
                'mqtt_tls_enabled': system.get('mqtt_tls_enabled', existing_config.mqtt_tls_enabled),
                'mqtt_tls_ca_cert': system.get('mqtt_tls_ca_cert', existing_config.mqtt_tls_ca_cert),
                'heartbeat_interval_s': system.get('heartbeat_interval_s', existing_config.heartbeat_interval_s),
                'publish_rate_hz': system.get('publish_rate_hz', existing_config.publish_rate_hz),
            },
            'file_watcher': payload.get('file_watcher', {}),
            'modbus_source': payload.get('modbus_source', {}),
            'serial_source': payload.get('serial_source', {}),
            'analysis_source': payload.get('analysis_source', {}),
            'scheduler': payload.get('scheduler', {}),
            'channels': payload.get('channels', {}),
        }
        return NodeConfig.from_dict(merged)
    return NodeConfig.from_dict(payload)


def save_config(config: NodeConfig, path: str) -> None:
    """Save configuration to JSON file."""
    data = {
        'config_version': CURRENT_CONFIG_VERSION,
        'system': {
            'node_id': config.node_id,
            'node_name': config.node_name,
            'gc_type': config.gc_type,
            'mqtt_broker': config.mqtt_broker,
            'mqtt_port': config.mqtt_port,
            'mqtt_username': config.mqtt_username,
            'mqtt_password': config.mqtt_password,
            'mqtt_base_topic': config.mqtt_base_topic,
            'mqtt_tls_enabled': config.mqtt_tls_enabled,
            'mqtt_tls_ca_cert': config.mqtt_tls_ca_cert,
            'heartbeat_interval_s': config.heartbeat_interval_s,
            'publish_rate_hz': config.publish_rate_hz,
        },
        'file_watcher': {
            'enabled': config.file_watcher.enabled,
            'watch_directory': config.file_watcher.watch_directory,
            'file_pattern': config.file_watcher.file_pattern,
            'poll_interval_s': config.file_watcher.poll_interval_s,
            'parse_template': config.file_watcher.parse_template,
            'delimiter': config.file_watcher.delimiter,
            'header_rows': config.file_watcher.header_rows,
            'encoding': config.file_watcher.encoding,
            'column_mapping': config.file_watcher.column_mapping,
            'archive_processed': config.file_watcher.archive_processed,
            'processed_dir': config.file_watcher.processed_dir,
        },
        'modbus_source': {
            'enabled': config.modbus_source.enabled,
            'connection_type': config.modbus_source.connection_type,
            'ip_address': config.modbus_source.ip_address,
            'port': config.modbus_source.port,
            'serial_port': config.modbus_source.serial_port,
            'baudrate': config.modbus_source.baudrate,
            'parity': config.modbus_source.parity,
            'slave_id': config.modbus_source.slave_id,
            'timeout': config.modbus_source.timeout,
            'poll_interval_s': config.modbus_source.poll_interval_s,
            'registers': config.modbus_source.registers,
        },
        'serial_source': {
            'enabled': config.serial_source.enabled,
            'port': config.serial_source.port,
            'baudrate': config.serial_source.baudrate,
            'parity': config.serial_source.parity,
            'timeout': config.serial_source.timeout,
            'frame_end': config.serial_source.frame_end,
            'protocol': config.serial_source.protocol,
            'parse_template': config.serial_source.parse_template,
            'delimiter': config.serial_source.delimiter,
            'column_mapping': config.serial_source.column_mapping,
        },
        'analysis_source': {
            'enabled': config.analysis_source.enabled,
            'mode': config.analysis_source.mode,
            'sample_rate_hz': config.analysis_source.sample_rate_hz,
            'method_file': config.analysis_source.method_file,
            'library_file': config.analysis_source.library_file,
            'run_duration_s': config.analysis_source.run_duration_s,
            'inject_trigger': config.analysis_source.inject_trigger,
            'inject_marker': config.analysis_source.inject_marker,
            'inject_threshold_v': config.analysis_source.inject_threshold_v,
            'inject_debounce_s': config.analysis_source.inject_debounce_s,
            'auto_run_interval_s': config.analysis_source.auto_run_interval_s,
            'publish_raw_chromatogram': config.analysis_source.publish_raw_chromatogram,
            'progress_interval_s': config.analysis_source.progress_interval_s,
        },
        'scheduler': {
            'enabled': config.scheduler.enabled,
            'auto_blank_interval': config.scheduler.auto_blank_interval,
            'auto_cal_interval': config.scheduler.auto_cal_interval,
            'auto_blank_method': config.scheduler.auto_blank_method,
            'auto_cal_method': config.scheduler.auto_cal_method,
            'max_queue_size': config.scheduler.max_queue_size,
        },
        'channels': {
            name: {
                'source_field': ch.source_field,
                'unit': ch.unit,
                'scale': ch.scale,
                'offset': ch.offset,
                'alarm_enabled': ch.alarm_enabled,
                'hihi_limit': ch.hihi_limit,
                'hi_limit': ch.hi_limit,
                'lo_limit': ch.lo_limit,
                'lolo_limit': ch.lolo_limit,
            }
            for name, ch in config.channels.items()
        },
    }

    # Filter None values from channels
    for ch_name in data['channels']:
        data['channels'][ch_name] = {k: v for k, v in data['channels'][ch_name].items() if v is not None}

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(path_obj, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"Config saved to {path}")
