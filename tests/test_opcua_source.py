"""
Unit tests for OPC-UA Data Source
Tests OPC-UA protocol communication
"""

import pytest
import threading
from unittest.mock import Mock, MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, 'services/daq_service')

from data_source_manager import (
    DataSourceType, ConnectionState, ChannelMapping, DataSourceManager
)

# Mock opcua before importing
@pytest.fixture(autouse=True)
def mock_opcua():
    """Mock OPC-UA library"""
    mock_ua = MagicMock()
    mock_ua.SecurityPolicyType = MagicMock()
    mock_ua.NodeClass = MagicMock()
    mock_ua.NodeClass.Variable = "Variable"
    mock_ua.VariantType = MagicMock()
    mock_ua.VariantType.Float = "Float"
    mock_ua.DataValue = MagicMock()
    mock_ua.Variant = MagicMock()

    with patch.dict('sys.modules', {
        'opcua': MagicMock(),
        'opcua.common': MagicMock(),
        'opcua.common.node': MagicMock(),
    }):
        with patch('opcua_source.ua', mock_ua):
            with patch('opcua_source.OPCUA_AVAILABLE', True):
                yield mock_ua

from opcua_source import (
    OpcUaSecurityPolicy, OpcUaMessageMode, OpcUaConfig, OpcUaDataSource,
    create_opcua_source_from_config, OPCUA_AVAILABLE
)

class TestOpcUaSecurityPolicy:
    """Test OPC-UA security policy enumeration"""

    def test_security_policies(self):
        """Test security policy values"""
        assert OpcUaSecurityPolicy.NONE.value == "None"
        assert OpcUaSecurityPolicy.BASIC128RSA15.value == "Basic128Rsa15"
        assert OpcUaSecurityPolicy.BASIC256.value == "Basic256"
        assert OpcUaSecurityPolicy.BASIC256SHA256.value == "Basic256Sha256"

class TestOpcUaMessageMode:
    """Test OPC-UA message mode enumeration"""

    def test_message_modes(self):
        """Test message mode values"""
        assert OpcUaMessageMode.NONE.value == "None"
        assert OpcUaMessageMode.SIGN.value == "Sign"
        assert OpcUaMessageMode.SIGN_AND_ENCRYPT.value == "SignAndEncrypt"

class TestOpcUaConfig:
    """Test OpcUaConfig dataclass"""

    def test_default_values(self):
        """Test default configuration"""
        config = OpcUaConfig(
            name="opcua_server",
            source_type=DataSourceType.OPC_UA
        )
        assert config.endpoint_url == "opc.tcp://localhost:4840"
        assert config.security_policy == "None"
        assert config.message_mode == "None"
        assert config.certificate_path is None
        assert config.use_subscription is True
        assert config.subscription_interval_ms == 100

    def test_custom_values(self):
        """Test custom configuration"""
        config = OpcUaConfig(
            name="secure_server",
            source_type=DataSourceType.OPC_UA,
            endpoint_url="opc.tcp://192.168.1.100:4840",
            security_policy="Basic256Sha256",
            message_mode="SignAndEncrypt",
            certificate_path="/certs/client.pem",
            private_key_path="/certs/client.key",
            username="admin",
            password="secret",
            use_subscription=False
        )
        assert config.endpoint_url == "opc.tcp://192.168.1.100:4840"
        assert config.security_policy == "Basic256Sha256"
        assert config.username == "admin"

    def test_source_type_set_in_post_init(self):
        """Test source type is set correctly"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.REST_API  # Wrong type
        )
        assert config.source_type == DataSourceType.OPC_UA

class TestOpcUaDataSource:
    """Test OpcUaDataSource class"""

    @pytest.fixture
    def opcua_source(self):
        """Create OPC-UA data source"""
        config = OpcUaConfig(
            name="test_server",
            source_type=DataSourceType.OPC_UA,
            endpoint_url="opc.tcp://localhost:4840"
        )
        with patch('opcua_source.OPCUA_AVAILABLE', True):
            source = OpcUaDataSource(config)
        return source

    def test_initialization(self, opcua_source):
        """Test source initialization"""
        assert opcua_source.name == "test_server"
        assert opcua_source.client is None
        assert opcua_source._node_cache == {}
        assert opcua_source._namespace_index is None

    def test_get_connection_config(self, opcua_source):
        """Test getting connection config"""
        config = opcua_source.get_connection_config()

        assert config['endpoint_url'] == "opc.tcp://localhost:4840"
        assert config['security_policy'] == "None"
        assert config['use_subscription'] is True

    @patch('opcua_source.Client')
    def test_connect_success(self, mock_client_class, opcua_source):
        """Test successful connection"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        with patch('opcua_source.OPCUA_AVAILABLE', True):
            result = opcua_source.connect()

        assert result is True
        assert opcua_source.status.state == ConnectionState.CONNECTED
        mock_client.connect.assert_called_once()

    @patch('opcua_source.Client')
    def test_connect_failure(self, mock_client_class, opcua_source):
        """Test connection failure"""
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection refused")
        mock_client_class.return_value = mock_client

        with patch('opcua_source.OPCUA_AVAILABLE', True):
            result = opcua_source.connect()

        assert result is False
        assert opcua_source.status.state == ConnectionState.ERROR
        assert "Connection refused" in opcua_source.status.last_error

    @patch('opcua_source.Client')
    def test_connect_with_credentials(self, mock_client_class):
        """Test connection with username/password"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA,
            username="user",
            password="pass"
        )
        source = OpcUaDataSource(config)

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        with patch('opcua_source.OPCUA_AVAILABLE', True):
            source.connect()

        mock_client.set_user.assert_called_with("user")
        mock_client.set_password.assert_called_with("pass")

    @patch('opcua_source.Client')
    def test_disconnect(self, mock_client_class, opcua_source):
        """Test disconnection"""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        opcua_source.client = mock_client
        opcua_source._node_cache = {"node1": MagicMock()}

        opcua_source.disconnect()

        mock_client.disconnect.assert_called_once()
        assert opcua_source.client is None
        assert opcua_source._node_cache == {}
        assert opcua_source.status.state == ConnectionState.DISCONNECTED

class TestNodeOperations:
    """Test node reading/writing operations"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source with mock client"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA,
            use_subscription=False
        )
        source = OpcUaDataSource(config)
        source.client = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_get_node_full_format(self, connected_source):
        """Test getting node with full ns=X;i=Y format"""
        mock_node = MagicMock()
        connected_source.client.get_node.return_value = mock_node

        node = connected_source._get_node("ns=2;i=1234")

        connected_source.client.get_node.assert_called_with("ns=2;i=1234")
        assert node == mock_node
        assert "ns=2;i=1234" in connected_source._node_cache

    def test_get_node_short_format(self, connected_source):
        """Test getting node with short i=Y format"""
        mock_node = MagicMock()
        connected_source.client.get_node.return_value = mock_node

        node = connected_source._get_node("i=1234")

        # Should add default namespace
        connected_source.client.get_node.assert_called_with("ns=2;i=1234")

    def test_get_node_string_identifier(self, connected_source):
        """Test getting node with string identifier"""
        mock_node = MagicMock()
        connected_source.client.get_node.return_value = mock_node

        node = connected_source._get_node("TagName")

        connected_source.client.get_node.assert_called_with("ns=2;s=TagName")

    def test_get_node_cached(self, connected_source):
        """Test node caching"""
        mock_node = MagicMock()
        connected_source._node_cache["ns=2;i=1234"] = mock_node

        node = connected_source._get_node("ns=2;i=1234")

        # Should not call client.get_node again
        connected_source.client.get_node.assert_not_called()
        assert node == mock_node

    def test_read_channel_success(self, connected_source):
        """Test reading channel successfully"""
        mock_node = MagicMock()
        mock_node.get_value.return_value = 25.5
        connected_source._node_cache["ns=2;s=Temperature"] = mock_node

        connected_source.add_channel(ChannelMapping(
            channel_name="temp",
            source_address="ns=2;s=Temperature",
            scale=1.0,
            offset=0.0
        ))

        result = connected_source.read_channel("temp")

        assert result == 25.5
        mock_node.get_value.assert_called_once()

    def test_read_channel_with_scaling(self, connected_source):
        """Test reading channel with scaling"""
        mock_node = MagicMock()
        mock_node.get_value.return_value = 1000  # Raw value
        connected_source.client.get_node.return_value = mock_node

        connected_source.add_channel(ChannelMapping(
            channel_name="temp",
            source_address="Temperature",
            scale=0.1,
            offset=32.0
        ))

        result = connected_source.read_channel("temp")

        # 1000 * 0.1 + 32 = 132
        assert result == 132.0

    def test_read_channel_not_connected(self, connected_source):
        """Test reading when not connected"""
        connected_source.status.state = ConnectionState.DISCONNECTED
        connected_source.add_channel(ChannelMapping(
            channel_name="temp",
            source_address="Temperature"
        ))

        result = connected_source.read_channel("temp")

        assert result is None

    def test_read_channel_not_found(self, connected_source):
        """Test reading non-existent channel"""
        result = connected_source.read_channel("unknown")
        assert result is None

    def test_write_channel_success(self, connected_source):
        """Test writing channel successfully"""
        mock_node = MagicMock()
        mock_dv = MagicMock()
        mock_dv.Value = MagicMock()
        mock_dv.Value.VariantType = "Float"
        mock_node.get_data_value.return_value = mock_dv
        connected_source.client.get_node.return_value = mock_node

        connected_source.add_channel(ChannelMapping(
            channel_name="output",
            source_address="OutputTag",
            is_output=True
        ))

        with patch('opcua_source.ua') as mock_ua:
            result = connected_source.write_channel("output", 100.0)

        assert result is True
        mock_node.set_value.assert_called_once()

    def test_write_channel_not_writable(self, connected_source):
        """Test writing to non-writable channel"""
        connected_source.add_channel(ChannelMapping(
            channel_name="input",
            source_address="InputTag",
            is_output=False
        ))

        result = connected_source.write_channel("input", 100.0)

        assert result is False

    def test_write_channel_with_scaling(self, connected_source):
        """Test writing channel with reverse scaling"""
        mock_node = MagicMock()
        mock_dv = MagicMock()
        mock_dv.Value = MagicMock()
        mock_dv.Value.VariantType = "Float"
        mock_node.get_data_value.return_value = mock_dv
        connected_source.client.get_node.return_value = mock_node

        connected_source.add_channel(ChannelMapping(
            channel_name="output",
            source_address="OutputTag",
            scale=0.1,
            offset=32.0,
            is_output=True
        ))

        with patch('opcua_source.ua') as mock_ua:
            # Write 132 -> raw = (132 - 32) / 0.1 = 1000
            result = connected_source.write_channel("output", 132.0)

        assert result is True

class TestReadAll:
    """Test read_all functionality"""

    @pytest.fixture
    def source_with_channels(self):
        """Create source with multiple channels"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA,
            use_subscription=False
        )
        source = OpcUaDataSource(config)
        source.client = MagicMock()
        source.status.state = ConnectionState.CONNECTED

        source.add_channel(ChannelMapping(
            channel_name="temp1",
            source_address="ns=2;s=Temp1"
        ))
        source.add_channel(ChannelMapping(
            channel_name="temp2",
            source_address="ns=2;s=Temp2"
        ))

        return source

    def test_read_all_values(self, source_with_channels):
        """Test reading all channels"""
        mock_node1 = MagicMock()
        mock_node1.get_value.return_value = 25.0
        mock_node2 = MagicMock()
        mock_node2.get_value.return_value = 30.0

        source_with_channels._node_cache = {
            "ns=2;s=Temp1": mock_node1,
            "ns=2;s=Temp2": mock_node2
        }

        values = source_with_channels.read_all()

        assert values["temp1"] == 25.0
        assert values["temp2"] == 30.0

class TestBrowsing:
    """Test node browsing functionality"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA
        )
        source = OpcUaDataSource(config)
        source.client = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_browse_nodes(self, connected_source):
        """Test browsing child nodes"""
        mock_parent = MagicMock()
        mock_child = MagicMock()
        mock_child.nodeid.to_string.return_value = "ns=2;i=1"
        mock_child.get_browse_name.return_value.Name = "TestNode"
        mock_child.get_display_name.return_value.Text = "Test Node"
        mock_child.get_node_class.return_value.name = "Object"
        mock_child.get_children.return_value = []

        mock_parent.get_children.return_value = [mock_child]
        connected_source.client.get_node.return_value = mock_parent

        nodes = connected_source.browse_nodes("ns=0;i=85")

        assert len(nodes) == 1
        assert nodes[0]['browse_name'] == "TestNode"
        assert nodes[0]['node_id'] == "ns=2;i=1"

    def test_browse_nodes_not_connected(self, connected_source):
        """Test browsing when not connected"""
        connected_source.status.state = ConnectionState.DISCONNECTED

        nodes = connected_source.browse_nodes()

        assert nodes == []

class TestServerInfo:
    """Test server info retrieval"""

    def test_get_server_info(self):
        """Test getting server information"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA
        )
        source = OpcUaDataSource(config)
        source.client = MagicMock()
        source.status.state = ConnectionState.CONNECTED

        # Mock server info nodes
        def mock_get_node(node_id):
            mock_node = MagicMock()
            values = {
                "ns=0;i=2261": "test:uri",
                "ns=0;i=2262": "Test Manufacturer",
                "ns=0;i=2263": "Test Product",
                "ns=0;i=2264": "1.0.0",
            }
            mock_node.get_value.return_value = values.get(node_id, "unknown")
            return mock_node

        source.client.get_node.side_effect = mock_get_node
        source.client.get_namespace_array.return_value = ["ns0", "ns1"]

        info = source.get_server_info()

        assert info['product_uri'] == "test:uri"
        assert info['manufacturer_name'] == "Test Manufacturer"

    def test_get_server_info_not_connected(self):
        """Test server info when not connected"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA
        )
        source = OpcUaDataSource(config)
        source.status.state = ConnectionState.DISCONNECTED

        info = source.get_server_info()

        assert info == {}

class TestCreateFromConfig:
    """Test creating source from config dict"""

    def test_create_basic_source(self):
        """Test creating source from basic config"""
        config_dict = {
            'name': 'test_server',
            'endpoint_url': 'opc.tcp://192.168.1.100:4840',
            'channels': [
                {
                    'name': 'temperature',
                    'node_id': 'ns=2;s=Temp',
                    'scale': 0.1,
                    'unit': 'C'
                }
            ]
        }

        with patch('opcua_source.OPCUA_AVAILABLE', True):
            source = create_opcua_source_from_config(config_dict)

        assert source is not None
        assert source.name == 'test_server'
        assert 'temperature' in source.channels
        assert source.channels['temperature'].scale == 0.1

    def test_create_with_security(self):
        """Test creating source with security settings"""
        config_dict = {
            'name': 'secure_server',
            'endpoint_url': 'opc.tcp://192.168.1.100:4840',
            'security_policy': 'Basic256Sha256',
            'message_mode': 'SignAndEncrypt',
            'username': 'admin',
            'password': 'secret',
            'channels': []
        }

        with patch('opcua_source.OPCUA_AVAILABLE', True):
            source = create_opcua_source_from_config(config_dict)

        assert source.opcua_config.security_policy == 'Basic256Sha256'
        assert source.opcua_config.username == 'admin'

    def test_create_with_invalid_config(self):
        """Test creating with invalid config"""
        # This should handle the error gracefully
        with patch('opcua_source.OPCUA_AVAILABLE', True):
            source = create_opcua_source_from_config(None)

        assert source is None

class TestSubscription:
    """Test OPC-UA subscription functionality"""

    @pytest.fixture
    def subscription_source(self):
        """Create source with subscription enabled"""
        config = OpcUaConfig(
            name="test",
            source_type=DataSourceType.OPC_UA,
            use_subscription=True,
            subscription_interval_ms=100
        )
        source = OpcUaDataSource(config)
        source.client = MagicMock()
        source.status.state = ConnectionState.CONNECTED
        return source

    def test_subscription_values_used_in_read_all(self, subscription_source):
        """Test that subscription values are used in read_all"""
        # Pre-populate subscription values
        subscription_source._subscription_values = {
            "temp": 25.0,
            "pressure": 100.5
        }

        values = subscription_source.read_all()

        assert values["temp"] == 25.0
        assert values["pressure"] == 100.5

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
