"""
OPC-UA Data Source for NISystem
Connects to OPC-UA servers to read/write tags.
Uses python-opcua (or asyncua) library.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from enum import Enum

from data_source_manager import (
    DataSource, DataSourceConfig, DataSourceType, ChannelMapping,
    ConnectionState, DataSourceManager
)

# Try to import opcua library
try:
    from opcua import Client, ua
    from opcua.common.node import Node
    OPCUA_AVAILABLE = True
    OPCUA_ASYNC = False
except ImportError:
    try:
        # Try asyncua as alternative
        from asyncua.sync import Client
        from asyncua import ua
        from asyncua.common.node import Node
        OPCUA_AVAILABLE = True
        OPCUA_ASYNC = True
    except ImportError:
        OPCUA_AVAILABLE = False
        OPCUA_ASYNC = False

logger = logging.getLogger('OpcUaSource')

class OpcUaSecurityPolicy(Enum):
    """OPC-UA Security policies"""
    NONE = "None"
    BASIC128RSA15 = "Basic128Rsa15"
    BASIC256 = "Basic256"
    BASIC256SHA256 = "Basic256Sha256"

class OpcUaMessageMode(Enum):
    """OPC-UA Message security modes"""
    NONE = "None"
    SIGN = "Sign"
    SIGN_AND_ENCRYPT = "SignAndEncrypt"

@dataclass
class OpcUaConfig(DataSourceConfig):
    """Configuration for OPC-UA data source"""
    # Connection
    endpoint_url: str = "opc.tcp://localhost:4840"

    # Security
    security_policy: str = "None"  # None, Basic128Rsa15, Basic256, Basic256Sha256
    message_mode: str = "None"     # None, Sign, SignAndEncrypt
    certificate_path: Optional[str] = None
    private_key_path: Optional[str] = None

    # Authentication
    username: Optional[str] = None
    password: Optional[str] = None

    # Subscription settings (for efficient updates)
    use_subscription: bool = True
    subscription_interval_ms: int = 100

    # Namespace configuration
    namespace_uri: Optional[str] = None  # Auto-detect if None

    def __post_init__(self):
        self.source_type = DataSourceType.OPC_UA

class OpcUaDataSource(DataSource):
    """
    OPC-UA data source implementation.
    Connects to OPC-UA servers and reads/writes node values.
    """

    def __init__(self, config: OpcUaConfig):
        super().__init__(config)
        self.opcua_config = config
        self.client: Optional[Client] = None
        self.subscription = None
        self.sub_handle = None
        self._node_cache: Dict[str, Node] = {}
        self._namespace_index: Optional[int] = None
        self._subscription_values: Dict[str, Any] = {}
        self._sub_lock = threading.Lock()

        if not OPCUA_AVAILABLE:
            logger.error("OPC-UA library not available. Install with: pip install opcua or pip install asyncua")

    def get_connection_config(self) -> Dict[str, Any]:
        """Return connection configuration for serialization."""
        return {
            'endpoint_url': self.opcua_config.endpoint_url,
            'security_policy': self.opcua_config.security_policy,
            'message_mode': self.opcua_config.message_mode,
            'username': self.opcua_config.username,
            'use_subscription': self.opcua_config.use_subscription,
            'subscription_interval_ms': self.opcua_config.subscription_interval_ms,
            'namespace_uri': self.opcua_config.namespace_uri,
        }

    def connect(self) -> bool:
        """Establish connection to OPC-UA server."""
        if not OPCUA_AVAILABLE:
            self.status.last_error = "OPC-UA library not available"
            return False

        try:
            self.status.state = ConnectionState.CONNECTING

            # Create client
            self.client = Client(self.opcua_config.endpoint_url)
            self.client.set_user(self.opcua_config.username or "")
            self.client.set_password(self.opcua_config.password or "")

            # Set security policy if specified
            if self.opcua_config.security_policy != "None":
                policy_map = {
                    "Basic128Rsa15": ua.SecurityPolicyType.Basic128Rsa15_SignAndEncrypt,
                    "Basic256": ua.SecurityPolicyType.Basic256_SignAndEncrypt,
                    "Basic256Sha256": ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                }
                policy = policy_map.get(self.opcua_config.security_policy)
                if policy and self.opcua_config.certificate_path and self.opcua_config.private_key_path:
                    self.client.set_security(
                        policy,
                        self.opcua_config.certificate_path,
                        self.opcua_config.private_key_path
                    )

            # Connect
            self.client.connect()

            # Get namespace index if URI specified
            if self.opcua_config.namespace_uri:
                try:
                    self._namespace_index = self.client.get_namespace_index(
                        self.opcua_config.namespace_uri
                    )
                except Exception as e:
                    logger.warning(f"Could not get namespace index for {self.opcua_config.namespace_uri}: {e}")

            # Set up subscription if enabled
            if self.opcua_config.use_subscription and self.channels:
                self._setup_subscription()

            self.status.state = ConnectionState.CONNECTED
            self.status.error_count = 0
            logger.info(f"[{self.name}] Connected to OPC-UA server: {self.opcua_config.endpoint_url}")
            return True

        except Exception as e:
            self.status.state = ConnectionState.ERROR
            self.status.last_error = str(e)
            self.status.error_count += 1
            logger.error(f"[{self.name}] OPC-UA connection failed: {e}")
            return False

    def disconnect(self):
        """Close connection to OPC-UA server."""
        try:
            if self.subscription:
                try:
                    self.subscription.delete()
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to delete OPC-UA subscription: {e}")
                self.subscription = None
                self.sub_handle = None

            if self.client:
                self.client.disconnect()
                self.client = None

            self._node_cache.clear()
            self.status.state = ConnectionState.DISCONNECTED
            logger.info(f"[{self.name}] Disconnected from OPC-UA server")

        except Exception as e:
            logger.error(f"[{self.name}] Error disconnecting: {e}")

    def _get_node(self, node_id: str) -> Optional[Node]:
        """Get node by ID, with caching."""
        if node_id in self._node_cache:
            return self._node_cache[node_id]

        if not self.client:
            return None

        try:
            # Parse node ID
            # Supports formats:
            #   ns=2;i=1234         (numeric)
            #   ns=2;s=TagName      (string)
            #   i=1234              (numeric, default ns)
            #   s=TagName           (string, default ns)

            if node_id.startswith("ns="):
                # Full node ID format
                node = self.client.get_node(node_id)
            elif node_id.startswith("i=") or node_id.startswith("s="):
                # Node ID without namespace - use configured or default namespace
                ns = self._namespace_index if self._namespace_index else 2
                node = self.client.get_node(f"ns={ns};{node_id}")
            else:
                # Assume string identifier
                ns = self._namespace_index if self._namespace_index else 2
                node = self.client.get_node(f"ns={ns};s={node_id}")

            self._node_cache[node_id] = node
            return node

        except Exception as e:
            logger.error(f"[{self.name}] Failed to get node {node_id}: {e}")
            return None

    def _setup_subscription(self):
        """Set up OPC-UA subscription for monitored items."""
        if not self.client or not self.channels:
            return

        try:
            # Create subscription handler
            handler = self._SubscriptionHandler(self)

            self.subscription = self.client.create_subscription(
                self.opcua_config.subscription_interval_ms,
                handler
            )

            # Subscribe to all configured channels
            for channel_name, mapping in self.channels.items():
                node = self._get_node(mapping.source_address)
                if node:
                    try:
                        self.subscription.subscribe_data_change(node)
                        logger.debug(f"[{self.name}] Subscribed to {channel_name}")
                    except Exception as e:
                        logger.warning(f"[{self.name}] Failed to subscribe to {channel_name}: {e}")

            logger.info(f"[{self.name}] Subscription created with {len(self.channels)} monitored items")

        except Exception as e:
            logger.error(f"[{self.name}] Failed to setup subscription: {e}")
            self.subscription = None

    class _SubscriptionHandler:
        """Handler for OPC-UA subscription callbacks."""

        def __init__(self, source: 'OpcUaDataSource'):
            self.source = source

        def datachange_notification(self, node, val, data):
            """Called when a monitored item changes."""
            try:
                # Find channel name by node ID
                node_id = node.nodeid.to_string()
                for name, mapping in self.source.channels.items():
                    # Check if this node matches the mapping
                    if self._matches_node(mapping.source_address, node_id):
                        with self.source._sub_lock:
                            self.source._subscription_values[name] = val
                        break
            except Exception as e:
                logger.error(f"Subscription callback error: {e}")

        def _matches_node(self, address: str, node_id: str) -> bool:
            """Check if address matches node_id."""
            # Direct match
            if address == node_id:
                return True
            # Check if address is contained in full node_id
            if address in node_id:
                return True
            # Check string identifier
            if f"s={address}" in node_id:
                return True
            return False

    def read_all(self) -> Dict[str, Any]:
        """Read all configured channels."""
        values = {}

        if not self.client or self.status.state != ConnectionState.CONNECTED:
            return values

        # If using subscription, merge subscription values
        if self.opcua_config.use_subscription:
            with self._sub_lock:
                values.update(self._subscription_values)

        # Read any channels not updated by subscription
        for channel_name, mapping in self.channels.items():
            if channel_name not in values or not self.opcua_config.use_subscription:
                try:
                    node = self._get_node(mapping.source_address)
                    if node:
                        raw_value = node.get_value()
                        # Apply scaling
                        if isinstance(raw_value, (int, float)):
                            scaled = raw_value * mapping.scale + mapping.offset
                            values[channel_name] = scaled
                        else:
                            values[channel_name] = raw_value
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to read {channel_name}: {e}")
                    values[channel_name] = None

        with self._lock:
            self.values.update(values)

        return values

    def read_channel(self, channel_name: str) -> Optional[Any]:
        """Read a single channel value."""
        if channel_name not in self.channels:
            return None

        if not self.client or self.status.state != ConnectionState.CONNECTED:
            return None

        mapping = self.channels[channel_name]
        try:
            node = self._get_node(mapping.source_address)
            if node:
                raw_value = node.get_value()
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

        if not self.client or self.status.state != ConnectionState.CONNECTED:
            logger.warning(f"[{self.name}] Not connected")
            return False

        try:
            node = self._get_node(mapping.source_address)
            if not node:
                return False

            # Reverse scaling for output
            if isinstance(value, (int, float)) and mapping.scale != 0:
                raw_value = (value - mapping.offset) / mapping.scale
            else:
                raw_value = value

            # Get data type from node and write
            dv = node.get_data_value()
            variant_type = dv.Value.VariantType if dv.Value else ua.VariantType.Float

            node.set_value(ua.DataValue(ua.Variant(raw_value, variant_type)))

            self.status.write_count += 1
            logger.debug(f"[{self.name}] Wrote {value} to {channel_name}")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Failed to write {channel_name}: {e}")
            return False

    def browse_nodes(self, parent_node_id: str = "ns=0;i=85") -> List[Dict[str, Any]]:
        """
        Browse child nodes of a parent node.
        Default parent is Objects folder (i=85).
        Returns list of node info dicts.
        """
        if not self.client or self.status.state != ConnectionState.CONNECTED:
            return []

        try:
            parent = self.client.get_node(parent_node_id)
            children = parent.get_children()

            result = []
            for child in children:
                try:
                    node_class = child.get_node_class()
                    node_info = {
                        'node_id': child.nodeid.to_string(),
                        'browse_name': child.get_browse_name().Name,
                        'display_name': child.get_display_name().Text,
                        'node_class': node_class.name if hasattr(node_class, 'name') else str(node_class),
                        'has_children': len(child.get_children()) > 0,
                    }

                    # Get data type for variables
                    if node_class == ua.NodeClass.Variable:
                        try:
                            dv = child.get_data_value()
                            if dv.Value:
                                node_info['data_type'] = dv.Value.VariantType.name
                                node_info['value'] = dv.Value.Value
                        except Exception as e:
                            logger.debug(f"Could not read OPC-UA node value: {e}")

                    result.append(node_info)
                except Exception as e:
                    logger.warning(f"Error browsing child node: {e}")

            return result

        except Exception as e:
            logger.error(f"[{self.name}] Browse failed: {e}")
            return []

    def get_server_info(self) -> Dict[str, Any]:
        """Get information about the connected OPC-UA server."""
        if not self.client or self.status.state != ConnectionState.CONNECTED:
            return {}

        try:
            server_node = self.client.get_node("ns=0;i=2253")  # Server node

            return {
                'product_uri': self.client.get_node("ns=0;i=2261").get_value(),
                'manufacturer_name': self.client.get_node("ns=0;i=2262").get_value(),
                'product_name': self.client.get_node("ns=0;i=2263").get_value(),
                'software_version': self.client.get_node("ns=0;i=2264").get_value(),
                'namespaces': self.client.get_namespace_array(),
            }
        except Exception as e:
            logger.warning(f"[{self.name}] Could not get server info: {e}")
            return {'error': str(e)}

# Register with DataSourceManager
if OPCUA_AVAILABLE:
    DataSourceManager.register_source_type(DataSourceType.OPC_UA, OpcUaDataSource)
    logger.info("OPC-UA data source registered")
else:
    logger.warning("OPC-UA data source not available - install opcua or asyncua package")

# Utility function to create OPC-UA source from config dict
def create_opcua_source_from_config(config_dict: Dict[str, Any]) -> Optional[OpcUaDataSource]:
    """Create an OPC-UA data source from a configuration dictionary."""
    try:
        opcua_config = OpcUaConfig(
            name=config_dict.get('name', 'opcua_device'),
            source_type=DataSourceType.OPC_UA,
            enabled=config_dict.get('enabled', True),
            poll_rate_ms=config_dict.get('poll_rate_ms', 100),
            timeout_s=config_dict.get('timeout_s', 5.0),
            description=config_dict.get('description', ''),
            endpoint_url=config_dict.get('endpoint_url', 'opc.tcp://localhost:4840'),
            security_policy=config_dict.get('security_policy', 'None'),
            message_mode=config_dict.get('message_mode', 'None'),
            certificate_path=config_dict.get('certificate_path'),
            private_key_path=config_dict.get('private_key_path'),
            username=config_dict.get('username'),
            password=config_dict.get('password'),
            use_subscription=config_dict.get('use_subscription', True),
            subscription_interval_ms=config_dict.get('subscription_interval_ms', 100),
            namespace_uri=config_dict.get('namespace_uri'),
        )

        source = OpcUaDataSource(opcua_config)

        # Add channels
        for ch_config in config_dict.get('channels', []):
            mapping = ChannelMapping(
                channel_name=ch_config['name'],
                source_address=ch_config['node_id'],
                data_type=ch_config.get('data_type', 'float32'),
                scale=ch_config.get('scale', 1.0),
                offset=ch_config.get('offset', 0.0),
                unit=ch_config.get('unit', ''),
                is_output=ch_config.get('is_output', False),
            )
            source.add_channel(mapping)

        return source

    except Exception as e:
        logger.error(f"Failed to create OPC-UA source: {e}")
        return None

# Test code
if __name__ == "__main__":
    import sys

    if not OPCUA_AVAILABLE:
        print("OPC-UA library not available")
        print("Install with: pip install opcua")
        print("  or: pip install asyncua")
        sys.exit(1)

    print(f"OPC-UA library available (async={OPCUA_ASYNC})")

    # Test with a local server (if running)
    config = OpcUaConfig(
        name="test_server",
        endpoint_url="opc.tcp://localhost:4840",
        use_subscription=False,
    )

    source = OpcUaDataSource(config)

    print(f"\nTrying to connect to {config.endpoint_url}...")
    if source.connect():
        print("Connected!")

        # Get server info
        info = source.get_server_info()
        print(f"\nServer info: {info}")

        # Browse root
        print("\nBrowsing Objects folder...")
        nodes = source.browse_nodes()
        for node in nodes[:10]:  # First 10
            print(f"  {node['display_name']} ({node['node_id']})")

        source.disconnect()
    else:
        print(f"Connection failed: {source.status.last_error}")
        print("(This is expected if no OPC-UA server is running locally)")
