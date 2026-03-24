"""
EtherNet/IP Data Source for NISystem
Connects to Allen Bradley ControlLogix/CompactLogix PLCs using pycomm3.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

from data_source_manager import (
    DataSource, DataSourceConfig, DataSourceType, ChannelMapping,
    ConnectionState, DataSourceManager
)

# Try to import pycomm3 library
try:
    from pycomm3 import LogixDriver, Tag
    from pycomm3.exceptions import CommError, RequestError
    PYCOMM3_AVAILABLE = True
except ImportError:
    PYCOMM3_AVAILABLE = False

logger = logging.getLogger('EtherNetIPSource')

class PlcType(Enum):
    """Supported PLC types"""
    CONTROLLOGIX = "controllogix"
    COMPACTLOGIX = "compactlogix"
    MICRO800 = "micro800"

@dataclass
class EtherNetIPConfig(DataSourceConfig):
    """Configuration for EtherNet/IP data source"""
    # Connection
    ip_address: str = "192.168.1.1"
    slot: int = 0  # Slot number for ControlLogix

    # PLC Type
    plc_type: str = "controllogix"  # controllogix, compactlogix, micro800

    # Connection options
    init_tags: bool = True      # Read tag list on connect
    init_program_tags: bool = False  # Also read program-scoped tags

    # Batch read optimization
    use_batch_read: bool = True  # Read multiple tags in one request

    def __post_init__(self):
        self.source_type = DataSourceType.ETHERNET_IP

class EtherNetIPDataSource(DataSource):
    """
    EtherNet/IP data source implementation for Allen Bradley PLCs.
    Uses pycomm3 for communication.
    """

    def __init__(self, config: EtherNetIPConfig):
        super().__init__(config)
        self.eip_config = config
        self.plc: Optional[LogixDriver] = None
        self._tag_list: List[Dict[str, Any]] = []
        self._program_tags: Dict[str, List[Dict[str, Any]]] = {}

        if not PYCOMM3_AVAILABLE:
            logger.error("pycomm3 library not available. Install with: pip install pycomm3")

    def get_connection_config(self) -> Dict[str, Any]:
        """Return connection configuration for serialization."""
        return {
            'ip_address': self.eip_config.ip_address,
            'slot': self.eip_config.slot,
            'plc_type': self.eip_config.plc_type,
            'init_tags': self.eip_config.init_tags,
            'init_program_tags': self.eip_config.init_program_tags,
            'use_batch_read': self.eip_config.use_batch_read,
        }

    def connect(self) -> bool:
        """Establish connection to the PLC."""
        if not PYCOMM3_AVAILABLE:
            self.status.last_error = "pycomm3 library not available"
            return False

        try:
            self.status.state = ConnectionState.CONNECTING

            # Build path for ControlLogix (slot-based)
            if self.eip_config.plc_type.lower() in ('controllogix', 'compactlogix'):
                path = f"{self.eip_config.ip_address}/{self.eip_config.slot}"
            else:
                path = self.eip_config.ip_address

            # Create LogixDriver
            self.plc = LogixDriver(
                path,
                init_tags=self.eip_config.init_tags,
                init_program_tags=self.eip_config.init_program_tags
            )

            # Open connection
            self.plc.open()

            # Cache tag list if available
            if self.eip_config.init_tags and hasattr(self.plc, 'tags'):
                self._tag_list = self._parse_tag_list(self.plc.tags)
                logger.info(f"[{self.name}] Found {len(self._tag_list)} controller tags")

            self.status.state = ConnectionState.CONNECTED
            self.status.error_count = 0
            logger.info(f"[{self.name}] Connected to PLC at {self.eip_config.ip_address}")
            return True

        except Exception as e:
            self.status.state = ConnectionState.ERROR
            self.status.last_error = str(e)
            self.status.error_count += 1
            logger.error(f"[{self.name}] Connection failed: {e}")
            return False

    def disconnect(self):
        """Close connection to the PLC."""
        try:
            if self.plc:
                self.plc.close()
                self.plc = None

            self.status.state = ConnectionState.DISCONNECTED
            logger.info(f"[{self.name}] Disconnected from PLC")

        except Exception as e:
            logger.error(f"[{self.name}] Error disconnecting: {e}")

    def _parse_tag_list(self, tags_dict: Dict) -> List[Dict[str, Any]]:
        """Parse pycomm3 tag dictionary into list of tag info."""
        result = []
        for name, info in tags_dict.items():
            tag_info = {
                'name': name,
                'data_type': info.get('data_type_name', 'UNKNOWN'),
                'dim': info.get('dim', 0),  # Array dimensions
                'value': info.get('value'),
                'tag_type': info.get('tag_type', 'atomic'),
            }
            result.append(tag_info)
        return result

    def read_all(self) -> Dict[str, Any]:
        """Read all configured channels."""
        values = {}

        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return values

        try:
            if self.eip_config.use_batch_read and len(self.channels) > 1:
                # Batch read - more efficient for multiple tags
                tag_names = [mapping.source_address for mapping in self.channels.values()]
                results = self.plc.read(*tag_names)

                # Handle single vs multiple results
                if not isinstance(results, list):
                    results = [results]

                # Map results back to channel names
                channel_list = list(self.channels.keys())
                for i, result in enumerate(results):
                    if i < len(channel_list):
                        channel_name = channel_list[i]
                        mapping = self.channels[channel_name]

                        if result.error is None:
                            raw_value = result.value
                            if isinstance(raw_value, (int, float)):
                                values[channel_name] = raw_value * mapping.scale + mapping.offset
                            else:
                                values[channel_name] = raw_value
                        else:
                            logger.warning(f"[{self.name}] Read error for {channel_name}: {result.error}")
                            values[channel_name] = None

            else:
                # Individual reads
                for channel_name, mapping in self.channels.items():
                    try:
                        result = self.plc.read(mapping.source_address)
                        if result.error is None:
                            raw_value = result.value
                            if isinstance(raw_value, (int, float)):
                                values[channel_name] = raw_value * mapping.scale + mapping.offset
                            else:
                                values[channel_name] = raw_value
                        else:
                            values[channel_name] = None
                    except Exception as e:
                        logger.warning(f"[{self.name}] Failed to read {channel_name}: {e}")
                        values[channel_name] = None

            with self._lock:
                self.values.update(values)

        except CommError as e:
            logger.error(f"[{self.name}] Communication error: {e}")
            self.status.error_count += 1
            self.status.last_error = str(e)
        except Exception as e:
            logger.error(f"[{self.name}] Read error: {e}")
            self.status.error_count += 1

        return values

    def read_channel(self, channel_name: str) -> Optional[Any]:
        """Read a single channel value."""
        if channel_name not in self.channels:
            return None

        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return None

        mapping = self.channels[channel_name]
        try:
            result = self.plc.read(mapping.source_address)
            if result.error is None:
                raw_value = result.value
                if isinstance(raw_value, (int, float)):
                    return raw_value * mapping.scale + mapping.offset
                return raw_value
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to read {channel_name}: {e}")

        return None

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write a value to a channel."""
        if channel_name not in self.channels:
            logger.warning(f"[{self.name}] Channel {channel_name} not found")
            return False

        mapping = self.channels[channel_name]
        if not mapping.is_output:
            logger.warning(f"[{self.name}] Channel {channel_name} is not writable")
            return False

        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            logger.warning(f"[{self.name}] Not connected")
            return False

        try:
            # Reverse scaling for output
            if isinstance(value, (int, float)) and mapping.scale != 0:
                raw_value = (value - mapping.offset) / mapping.scale
            else:
                raw_value = value

            result = self.plc.write(mapping.source_address, raw_value)

            if result.error is None:
                self.status.write_count += 1
                logger.debug(f"[{self.name}] Wrote {value} to {channel_name}")
                return True
            else:
                logger.error(f"[{self.name}] Write error for {channel_name}: {result.error}")
                return False

        except Exception as e:
            logger.error(f"[{self.name}] Failed to write {channel_name}: {e}")
            return False

    def get_tag_list(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get list of available tags from the PLC.
        Returns cached list unless refresh=True.
        """
        if refresh or not self._tag_list:
            if self.plc and self.status.state == ConnectionState.CONNECTED:
                try:
                    # Force tag list reload
                    tags = self.plc.get_tag_list()
                    self._tag_list = self._parse_tag_list(tags)
                except Exception as e:
                    logger.error(f"[{self.name}] Failed to get tag list: {e}")

        return self._tag_list

    def get_program_tags(self, program_name: str) -> List[Dict[str, Any]]:
        """Get tags for a specific program."""
        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return []

        try:
            tags = self.plc.get_tag_list(program=program_name)
            return self._parse_tag_list(tags)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get program tags: {e}")
            return []

    def get_programs(self) -> List[str]:
        """Get list of program names in the PLC."""
        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return []

        try:
            return list(self.plc.get_plc_info().programs.keys())
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get programs: {e}")
            return []

    def get_plc_info(self) -> Dict[str, Any]:
        """Get information about the connected PLC."""
        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return {}

        try:
            info = self.plc.get_plc_info()
            return {
                'vendor': info.vendor,
                'product_type': info.product_type,
                'product_code': info.product_code,
                'revision': f"{info.revision['major']}.{info.revision['minor']}",
                'serial_number': hex(info.serial_number),
                'device_type': info.device_type,
                'product_name': info.product_name,
            }
        except Exception as e:
            logger.warning(f"[{self.name}] Could not get PLC info: {e}")
            return {'error': str(e)}

    def read_tag_direct(self, tag_name: str) -> Tuple[Any, Optional[str]]:
        """
        Read a tag directly by name (not through channel mapping).
        Returns (value, error_string).
        """
        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return None, "Not connected"

        try:
            result = self.plc.read(tag_name)
            if result.error is None:
                return result.value, None
            else:
                return None, result.error
        except Exception as e:
            return None, str(e)

    def write_tag_direct(self, tag_name: str, value: Any) -> Tuple[bool, Optional[str]]:
        """
        Write to a tag directly by name (not through channel mapping).
        Returns (success, error_string).
        """
        if not self.plc or self.status.state != ConnectionState.CONNECTED:
            return False, "Not connected"

        try:
            result = self.plc.write(tag_name, value)
            if result.error is None:
                return True, None
            else:
                return False, result.error
        except Exception as e:
            return False, str(e)

# Register with DataSourceManager
if PYCOMM3_AVAILABLE:
    DataSourceManager.register_source_type(DataSourceType.ETHERNET_IP, EtherNetIPDataSource)
    logger.info("EtherNet/IP data source registered")
else:
    logger.warning("EtherNet/IP data source not available - install pycomm3 package")

# Utility function to create EtherNet/IP source from config dict
def create_ethernet_ip_source_from_config(config_dict: Dict[str, Any]) -> Optional[EtherNetIPDataSource]:
    """Create an EtherNet/IP data source from a configuration dictionary."""
    try:
        eip_config = EtherNetIPConfig(
            name=config_dict.get('name', 'plc_device'),
            source_type=DataSourceType.ETHERNET_IP,
            enabled=config_dict.get('enabled', True),
            poll_rate_ms=config_dict.get('poll_rate_ms', 100),
            timeout_s=config_dict.get('timeout_s', 5.0),
            description=config_dict.get('description', ''),
            ip_address=config_dict.get('ip_address', '192.168.1.1'),
            slot=config_dict.get('slot', 0),
            plc_type=config_dict.get('plc_type', 'controllogix'),
            init_tags=config_dict.get('init_tags', True),
            init_program_tags=config_dict.get('init_program_tags', False),
            use_batch_read=config_dict.get('use_batch_read', True),
        )

        source = EtherNetIPDataSource(eip_config)

        # Add channels
        for ch_config in config_dict.get('channels', []):
            mapping = ChannelMapping(
                channel_name=ch_config['name'],
                source_address=ch_config['tag_name'],
                data_type=ch_config.get('data_type', 'float32'),
                scale=ch_config.get('scale', 1.0),
                offset=ch_config.get('offset', 0.0),
                unit=ch_config.get('unit', ''),
                is_output=ch_config.get('is_output', False),
            )
            source.add_channel(mapping)

        return source

    except Exception as e:
        logger.error(f"Failed to create EtherNet/IP source: {e}")
        return None

# Test code
if __name__ == "__main__":
    import sys

    if not PYCOMM3_AVAILABLE:
        print("pycomm3 library not available")
        print("Install with: pip install pycomm3")
        sys.exit(1)

    print("pycomm3 library available")

    # Test configuration (won't connect without real PLC)
    config = EtherNetIPConfig(
        name="test_plc",
        ip_address="192.168.1.1",
        slot=0,
        init_tags=False,  # Don't try to read tags
    )

    source = EtherNetIPDataSource(config)

    print(f"\nWould connect to PLC at {config.ip_address} slot {config.slot}")
    print("(Not actually connecting - no PLC available for test)")

    # Show available configuration options
    print("\nConfiguration options:")
    print(f"  ip_address: PLC IP address")
    print(f"  slot: Backplane slot number (ControlLogix)")
    print(f"  plc_type: controllogix, compactlogix, micro800")
    print(f"  init_tags: Read tag list on connect")
    print(f"  use_batch_read: Batch multiple reads")
