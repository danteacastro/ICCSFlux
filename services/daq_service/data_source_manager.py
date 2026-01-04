"""
Data Source Manager for NISystem
Unified abstraction layer for multiple data backends (Modbus, REST API, OPC-UA, etc.)
Provides common interface for reading/writing values from external devices.
"""

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Type

logger = logging.getLogger('DataSourceManager')


class DataSourceType(Enum):
    """Supported data source types"""
    MODBUS_TCP = "modbus_tcp"
    MODBUS_RTU = "modbus_rtu"
    REST_API = "rest_api"
    OPC_UA = "opc_ua"
    ETHERNET_IP = "ethernet_ip"  # Allen Bradley
    S7 = "s7"  # Siemens


class ConnectionState(Enum):
    """Connection state for data sources"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class DataSourceConfig:
    """Base configuration for all data sources"""
    name: str
    source_type: DataSourceType
    enabled: bool = True
    poll_rate_ms: int = 100  # How often to poll values
    timeout_s: float = 5.0
    retries: int = 3

    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class ChannelMapping:
    """Maps a data source value to a channel name"""
    channel_name: str  # The name used in the dashboard (e.g., "Pump_Speed")
    source_address: str  # Source-specific address (e.g., "40001" for Modbus, "/api/v1/analog/0" for REST)
    data_type: str = "float32"  # int16, uint16, int32, float32, bool, string
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    is_output: bool = False  # Can this channel be written to?

    # Optional transform
    transform: Optional[str] = None  # Python expression, e.g., "value * 0.1 + 32"


@dataclass
class DataSourceStatus:
    """Runtime status of a data source"""
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: Optional[str] = None
    error_count: int = 0
    last_successful_read: float = 0
    read_count: int = 0
    write_count: int = 0
    latency_ms: float = 0


class DataSource(ABC):
    """
    Abstract base class for all data sources.
    Implement this to add support for new protocols.
    """

    def __init__(self, config: DataSourceConfig):
        self.config = config
        self.status = DataSourceStatus()
        self.channels: Dict[str, ChannelMapping] = {}
        self.values: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def source_type(self) -> DataSourceType:
        return self.config.source_type

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the data source. Returns True on success."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close connection to the data source."""
        pass

    @abstractmethod
    def read_all(self) -> Dict[str, Any]:
        """Read all configured channels. Returns dict of channel_name -> value."""
        pass

    @abstractmethod
    def read_channel(self, channel_name: str) -> Optional[Any]:
        """Read a single channel value."""
        pass

    @abstractmethod
    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write a value to a channel. Returns True on success."""
        pass

    def add_channel(self, mapping: ChannelMapping):
        """Add a channel mapping to this data source."""
        with self._lock:
            self.channels[mapping.channel_name] = mapping
            self.values[mapping.channel_name] = None
            logger.info(f"[{self.name}] Added channel: {mapping.channel_name} -> {mapping.source_address}")

    def remove_channel(self, channel_name: str):
        """Remove a channel mapping."""
        with self._lock:
            if channel_name in self.channels:
                del self.channels[channel_name]
            if channel_name in self.values:
                del self.values[channel_name]

    def get_channel_names(self) -> List[str]:
        """Get list of configured channel names."""
        return list(self.channels.keys())

    def add_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Add a callback to be called when values are updated.
        Callback signature: callback(source_name, {channel_name: value, ...})
        """
        self._callbacks.append(callback)

    def _notify_callbacks(self, values: Dict[str, Any]):
        """Notify all callbacks with updated values."""
        for callback in self._callbacks:
            try:
                callback(self.name, values)
            except Exception as e:
                logger.error(f"[{self.name}] Callback error: {e}")

    def start_polling(self):
        """Start background polling thread."""
        if self._running:
            return

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info(f"[{self.name}] Started polling at {self.config.poll_rate_ms}ms")

    def stop_polling(self):
        """Stop background polling thread."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None
        logger.info(f"[{self.name}] Stopped polling")

    def _poll_loop(self):
        """Background polling loop."""
        while self._running:
            if self.status.state == ConnectionState.CONNECTED:
                try:
                    start = time.time()
                    values = self.read_all()
                    self.status.latency_ms = (time.time() - start) * 1000
                    self.status.read_count += 1
                    self.status.last_successful_read = time.time()

                    with self._lock:
                        self.values.update(values)

                    self._notify_callbacks(values)

                except Exception as e:
                    self.status.error_count += 1
                    self.status.last_error = str(e)
                    logger.warning(f"[{self.name}] Poll error: {e}")

                    # Auto-reconnect after errors
                    if self.status.error_count >= self.config.retries:
                        self.status.state = ConnectionState.ERROR
                        self._try_reconnect()

            elif self.status.state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR):
                self._try_reconnect()

            time.sleep(self.config.poll_rate_ms / 1000.0)

    def _try_reconnect(self):
        """Attempt to reconnect."""
        self.status.state = ConnectionState.CONNECTING
        try:
            if self.connect():
                self.status.state = ConnectionState.CONNECTED
                self.status.error_count = 0
                logger.info(f"[{self.name}] Reconnected successfully")
            else:
                self.status.state = ConnectionState.ERROR
        except Exception as e:
            self.status.state = ConnectionState.ERROR
            self.status.last_error = str(e)

    def get_status(self) -> Dict[str, Any]:
        """Get current status as dictionary."""
        return {
            'name': self.name,
            'type': self.source_type.value,
            'enabled': self.config.enabled,
            'state': self.status.state.value,
            'connected': self.status.state == ConnectionState.CONNECTED,
            'last_error': self.status.last_error,
            'error_count': self.status.error_count,
            'read_count': self.status.read_count,
            'write_count': self.status.write_count,
            'latency_ms': round(self.status.latency_ms, 2),
            'channel_count': len(self.channels),
        }

    def get_values(self) -> Dict[str, Any]:
        """Get current cached values."""
        with self._lock:
            return self.values.copy()


class DataSourceManager:
    """
    Manages multiple data sources and provides unified access to all channels.
    """

    # Registry of data source implementations
    _source_types: Dict[DataSourceType, Type[DataSource]] = {}

    def __init__(self):
        self.sources: Dict[str, DataSource] = {}
        self._lock = threading.Lock()
        self._value_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._all_values: Dict[str, Any] = {}
        logger.info("DataSourceManager initialized")

    @classmethod
    def register_source_type(cls, source_type: DataSourceType, source_class: Type[DataSource]):
        """Register a data source implementation for a type."""
        cls._source_types[source_type] = source_class
        logger.info(f"Registered data source type: {source_type.value} -> {source_class.__name__}")

    @classmethod
    def get_available_types(cls) -> List[str]:
        """Get list of available data source types."""
        return [t.value for t in cls._source_types.keys()]

    def add_source(self, config: DataSourceConfig, channels: List[ChannelMapping] = None) -> Optional[DataSource]:
        """Add a new data source with optional channel mappings."""
        if config.name in self.sources:
            logger.warning(f"Data source '{config.name}' already exists")
            return None

        source_class = self._source_types.get(config.source_type)
        if not source_class:
            logger.error(f"Unknown data source type: {config.source_type}")
            return None

        try:
            source = source_class(config)

            # Add channels
            if channels:
                for mapping in channels:
                    source.add_channel(mapping)

            # Add callback to aggregate values
            source.add_callback(self._on_source_values)

            with self._lock:
                self.sources[config.name] = source

            logger.info(f"Added data source: {config.name} ({config.source_type.value})")
            return source

        except Exception as e:
            logger.error(f"Failed to create data source '{config.name}': {e}")
            return None

    def remove_source(self, name: str):
        """Remove a data source."""
        with self._lock:
            if name in self.sources:
                source = self.sources[name]
                source.stop_polling()
                source.disconnect()
                del self.sources[name]

                # Remove values for this source's channels
                for channel in source.get_channel_names():
                    if channel in self._all_values:
                        del self._all_values[channel]

                logger.info(f"Removed data source: {name}")

    def get_source(self, name: str) -> Optional[DataSource]:
        """Get a data source by name."""
        return self.sources.get(name)

    def start_all(self):
        """Start polling all enabled data sources."""
        for source in self.sources.values():
            if source.config.enabled:
                if source.connect():
                    source.status.state = ConnectionState.CONNECTED
                source.start_polling()
        logger.info(f"Started {len(self.sources)} data sources")

    def stop_all(self):
        """Stop all data sources."""
        for source in self.sources.values():
            source.stop_polling()
            source.disconnect()
        logger.info("Stopped all data sources")

    def _on_source_values(self, source_name: str, values: Dict[str, Any]):
        """Called when a source has new values."""
        with self._lock:
            self._all_values.update(values)

        # Notify callbacks
        for callback in self._value_callbacks:
            try:
                callback(values)
            except Exception as e:
                logger.error(f"Value callback error: {e}")

    def add_value_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Add callback for value updates from any source."""
        self._value_callbacks.append(callback)

    def get_all_values(self) -> Dict[str, Any]:
        """Get all cached values from all sources."""
        with self._lock:
            return self._all_values.copy()

    def read_channel(self, channel_name: str) -> Optional[Any]:
        """Read a channel value (from cache or direct read)."""
        # First check cache
        if channel_name in self._all_values:
            return self._all_values[channel_name]

        # Find which source has this channel
        for source in self.sources.values():
            if channel_name in source.channels:
                return source.read_channel(channel_name)

        return None

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write to a channel."""
        for source in self.sources.values():
            if channel_name in source.channels:
                mapping = source.channels[channel_name]
                if mapping.is_output:
                    return source.write_channel(channel_name, value)
                else:
                    logger.warning(f"Channel '{channel_name}' is not writable")
                    return False

        logger.warning(f"Channel '{channel_name}' not found in any data source")
        return False

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all data sources."""
        return {name: source.get_status() for name, source in self.sources.items()}

    def get_all_channels(self) -> Dict[str, Dict[str, Any]]:
        """Get info about all channels across all sources."""
        channels = {}
        for source in self.sources.values():
            for name, mapping in source.channels.items():
                channels[name] = {
                    'source': source.name,
                    'address': mapping.source_address,
                    'data_type': mapping.data_type,
                    'unit': mapping.unit,
                    'is_output': mapping.is_output,
                    'value': self._all_values.get(name),
                }
        return channels

    def to_config(self) -> Dict[str, Any]:
        """Export all data sources to config dict for saving."""
        config = {'data_sources': []}
        for source in self.sources.values():
            source_config = {
                'name': source.config.name,
                'type': source.config.source_type.value,
                'enabled': source.config.enabled,
                'poll_rate_ms': source.config.poll_rate_ms,
                'timeout_s': source.config.timeout_s,
                'retries': source.config.retries,
                'description': source.config.description,
                'channels': []
            }

            # Add source-specific config
            if hasattr(source, 'get_connection_config'):
                source_config['connection'] = source.get_connection_config()

            # Add channels
            for name, mapping in source.channels.items():
                source_config['channels'].append({
                    'name': name,
                    'address': mapping.source_address,
                    'data_type': mapping.data_type,
                    'scale': mapping.scale,
                    'offset': mapping.offset,
                    'unit': mapping.unit,
                    'is_output': mapping.is_output,
                })

            config['data_sources'].append(source_config)

        return config


# Convenience function to get singleton instance
_manager_instance: Optional[DataSourceManager] = None

def get_data_source_manager() -> DataSourceManager:
    """Get the singleton DataSourceManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DataSourceManager()
    return _manager_instance
