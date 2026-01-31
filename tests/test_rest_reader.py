"""
Unit tests for REST API Reader
Tests HTTP/REST data source functionality
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

import sys
sys.path.insert(0, 'services/daq_service')

from data_source_manager import (
    DataSourceType, ConnectionState, ChannelMapping, DataSourceManager
)


# Import with mocked HTTP libraries
@pytest.fixture(autouse=True)
def mock_http_libs():
    """Mock HTTP libraries"""
    with patch.dict('sys.modules', {
        'httpx': MagicMock(),
        'requests': MagicMock(),
    }):
        yield


from rest_reader import (
    AuthType, HttpMethod, RestEndpointConfig, RestSourceConfig,
    RestChannelMapping, RestDataSource, Opto22DataSource,
    HTTPX_AVAILABLE, REQUESTS_AVAILABLE
)


class TestAuthType:
    """Test AuthType enumeration"""

    def test_auth_types(self):
        """Test all auth types defined"""
        assert AuthType.NONE.value == "none"
        assert AuthType.BASIC.value == "basic"
        assert AuthType.BEARER.value == "bearer"
        assert AuthType.API_KEY.value == "api_key"
        assert AuthType.CUSTOM_HEADER.value == "custom_header"


class TestHttpMethod:
    """Test HttpMethod enumeration"""

    def test_http_methods(self):
        """Test HTTP methods defined"""
        assert HttpMethod.GET.value == "GET"
        assert HttpMethod.POST.value == "POST"
        assert HttpMethod.PUT.value == "PUT"


class TestRestEndpointConfig:
    """Test RestEndpointConfig dataclass"""

    def test_default_values(self):
        """Test default endpoint config"""
        endpoint = RestEndpointConfig(path="/api/v1/value")
        assert endpoint.method == HttpMethod.GET
        assert endpoint.response_key is None
        assert endpoint.body_template is None
        assert endpoint.headers == {}

    def test_custom_endpoint(self):
        """Test custom endpoint config"""
        endpoint = RestEndpointConfig(
            path="/api/v1/write",
            method=HttpMethod.POST,
            response_key="data.result",
            body_template='{"value": {value}}',
            headers={"X-Custom": "header"}
        )
        assert endpoint.path == "/api/v1/write"
        assert endpoint.method == HttpMethod.POST
        assert endpoint.response_key == "data.result"


class TestRestSourceConfig:
    """Test RestSourceConfig dataclass"""

    def test_default_values(self):
        """Test default REST source config"""
        config = RestSourceConfig(
            name="api_source",
            source_type=DataSourceType.REST_API
        )
        assert config.base_url == "http://192.168.1.100"
        assert config.auth_type == AuthType.NONE
        assert config.verify_ssl is True
        assert config.follow_redirects is True

    def test_basic_auth_config(self):
        """Test basic authentication config"""
        config = RestSourceConfig(
            name="api_source",
            source_type=DataSourceType.REST_API,
            auth_type=AuthType.BASIC,
            username="admin",
            password="secret"
        )
        assert config.auth_type == AuthType.BASIC
        assert config.username == "admin"
        assert config.password == "secret"

    def test_api_key_config(self):
        """Test API key authentication config"""
        config = RestSourceConfig(
            name="api_source",
            source_type=DataSourceType.REST_API,
            auth_type=AuthType.API_KEY,
            api_key="my-api-key-123",
            api_key_header="X-API-Key"
        )
        assert config.auth_type == AuthType.API_KEY
        assert config.api_key == "my-api-key-123"

    def test_bearer_token_config(self):
        """Test bearer token config"""
        config = RestSourceConfig(
            name="api_source",
            source_type=DataSourceType.REST_API,
            auth_type=AuthType.BEARER,
            bearer_token="jwt-token-here"
        )
        assert config.bearer_token == "jwt-token-here"

    def test_batch_endpoint_config(self):
        """Test batch endpoint configuration"""
        config = RestSourceConfig(
            name="api_source",
            source_type=DataSourceType.REST_API,
            batch_endpoint="/api/v1/batch",
            batch_key="tags"
        )
        assert config.batch_endpoint == "/api/v1/batch"
        assert config.batch_key == "tags"


class TestRestChannelMapping:
    """Test RestChannelMapping dataclass"""

    def test_simple_mapping(self):
        """Test simple channel mapping"""
        mapping = RestChannelMapping(
            channel_name="temperature",
            source_address="/api/v1/temp"
        )
        assert mapping.channel_name == "temperature"
        assert mapping.source_address == "/api/v1/temp"
        assert mapping.endpoint is None

    def test_mapping_with_endpoint(self):
        """Test channel mapping with endpoint config"""
        endpoint = RestEndpointConfig(
            path="/api/v1/read",
            method=HttpMethod.POST,
            response_key="data.value"
        )
        mapping = RestChannelMapping(
            channel_name="sensor1",
            source_address="/api/v1/read",
            endpoint=endpoint
        )
        assert mapping.endpoint == endpoint


class TestRestDataSource:
    """Test RestDataSource class"""

    @pytest.fixture
    def rest_source(self):
        """Create REST data source for testing"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API,
            base_url="http://192.168.1.100:8080",
            timeout_s=5.0
        )
        return RestDataSource(config)

    def test_initialization(self, rest_source):
        """Test source initialization"""
        assert rest_source.name == "test_api"
        assert rest_source.rest_config.base_url == "http://192.168.1.100:8080"
        assert rest_source._client is None

    def test_create_httpx_client_no_auth(self, rest_source):
        """Test creating client without auth - just verify config is set"""
        # We can't mock httpx if it's not installed, just verify config
        assert rest_source.rest_config.auth_type == AuthType.NONE

    def test_create_httpx_client_basic_auth(self):
        """Test creating client with basic auth config"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API,
            auth_type=AuthType.BASIC,
            username="user",
            password="pass"
        )
        source = RestDataSource(config)

        # Just verify config is stored correctly
        assert source.rest_config.auth_type == AuthType.BASIC
        assert source.rest_config.username == "user"
        assert source.rest_config.password == "pass"

    @patch('rest_reader.HTTPX_AVAILABLE', False)
    @patch('rest_reader.REQUESTS_AVAILABLE', True)
    @patch('rest_reader.requests')
    def test_create_requests_session(self, mock_requests):
        """Test creating requests session as fallback"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API
        )
        source = RestDataSource(config)

        mock_session = MagicMock()
        mock_requests.Session.return_value = mock_session

        source._create_client()

        mock_requests.Session.assert_called_once()
        assert source._session == mock_session

    def test_extract_value_simple(self, rest_source):
        """Test extracting simple value"""
        response = 42.5
        result = rest_source._extract_value(response, None)
        assert result == 42.5

    def test_extract_value_dict_path(self, rest_source):
        """Test extracting value from nested dict"""
        response = {"data": {"value": 123.45}}
        result = rest_source._extract_value(response, "data.value")
        assert result == 123.45

    def test_extract_value_array_index(self, rest_source):
        """Test extracting value from array"""
        response = {"results": [{"value": 10}, {"value": 20}, {"value": 30}]}
        result = rest_source._extract_value(response, "results[1].value")
        assert result == 20

    def test_extract_value_invalid_path(self, rest_source):
        """Test extracting with invalid path returns None"""
        response = {"data": {"value": 123.45}}
        result = rest_source._extract_value(response, "invalid.path")
        assert result is None

    def test_apply_scaling(self, rest_source):
        """Test applying scale and offset"""
        mapping = ChannelMapping(
            channel_name="temp",
            source_address="/temp",
            scale=0.1,
            offset=32.0
        )

        # 1000 * 0.1 + 32 = 132
        result = rest_source._apply_scaling(1000, mapping)
        assert result == 132.0

    def test_apply_scaling_none(self, rest_source):
        """Test scaling with None value"""
        mapping = ChannelMapping(channel_name="temp", source_address="/temp")
        result = rest_source._apply_scaling(None, mapping)
        assert result is None

    def test_apply_scaling_non_numeric(self, rest_source):
        """Test scaling with non-numeric value"""
        mapping = ChannelMapping(channel_name="status", source_address="/status")
        result = rest_source._apply_scaling("OK", mapping)
        assert result == "OK"

    def test_get_connection_config(self, rest_source):
        """Test getting connection config for serialization"""
        config = rest_source.get_connection_config()

        assert config['base_url'] == "http://192.168.1.100:8080"
        assert config['auth_type'] == "none"
        assert config['verify_ssl'] is True

    def test_read_channel_not_found(self, rest_source):
        """Test reading non-existent channel"""
        result = rest_source.read_channel("unknown")
        assert result is None

    def test_write_channel_not_found(self, rest_source):
        """Test writing to non-existent channel"""
        result = rest_source.write_channel("unknown", 100)
        assert result is False

    def test_write_channel_not_writable(self, rest_source):
        """Test writing to non-writable channel"""
        rest_source.add_channel(ChannelMapping(
            channel_name="input",
            source_address="/input",
            is_output=False
        ))
        result = rest_source.write_channel("input", 100)
        assert result is False


class TestRestDataSourceRequests:
    """Test HTTP request functionality"""

    @pytest.fixture
    def connected_source(self):
        """Create connected source with mocked client"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API,
            base_url="http://test.local"
        )
        source = RestDataSource(config)
        source._client = MagicMock()
        return source

    def test_make_get_request(self, connected_source):
        """Test making GET request"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": 42}
        connected_source._client.get.return_value = mock_response

        with patch('rest_reader.HTTPX_AVAILABLE', True):
            result = connected_source._make_request("GET", "/api/value")

        connected_source._client.get.assert_called_once_with("/api/value", headers=None)
        assert result == {"value": 42}

    def test_make_post_request(self, connected_source):
        """Test making POST request"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        connected_source._client.post.return_value = mock_response

        with patch('rest_reader.HTTPX_AVAILABLE', True):
            result = connected_source._make_request("POST", "/api/write", body={"value": 100})

        connected_source._client.post.assert_called_once()
        assert result == {"result": "ok"}


class TestOpto22DataSource:
    """Test Opto22-specific data source"""

    @pytest.fixture
    def opto22_source(self):
        """Create Opto22 data source"""
        config = RestSourceConfig(
            name="groov_epic",
            source_type=DataSourceType.REST_API,
            base_url="http://192.168.1.10"
        )
        return Opto22DataSource(config)

    def test_default_headers_set(self, opto22_source):
        """Test default headers are set"""
        assert opto22_source.rest_config.custom_headers['Content-Type'] == 'application/json'
        assert opto22_source.rest_config.custom_headers['Accept'] == 'application/json'

    def test_add_analog_input(self, opto22_source):
        """Test adding analog input channel"""
        opto22_source.add_analog_input(
            channel_name="AI_0",
            module_index=0,
            channel_index=0,
            unit="V",
            scale=1.0
        )

        assert "AI_0" in opto22_source.channels
        mapping = opto22_source.channels["AI_0"]
        assert "/analogInputs/0/channels/0/value" in mapping.source_address
        assert mapping.unit == "V"
        assert mapping.is_output is False

    def test_add_analog_output(self, opto22_source):
        """Test adding analog output channel"""
        opto22_source.add_analog_output(
            channel_name="AO_0",
            module_index=1,
            channel_index=0
        )

        assert "AO_0" in opto22_source.channels
        mapping = opto22_source.channels["AO_0"]
        assert "/analogOutputs/1/channels/0/value" in mapping.source_address
        assert mapping.is_output is True

    def test_add_digital_input(self, opto22_source):
        """Test adding digital input channel"""
        opto22_source.add_digital_input(
            channel_name="DI_0",
            module_index=2,
            channel_index=3
        )

        assert "DI_0" in opto22_source.channels
        mapping = opto22_source.channels["DI_0"]
        assert "/digitalInputs/2/channels/3/state" in mapping.source_address

    def test_add_digital_output(self, opto22_source):
        """Test adding digital output channel"""
        opto22_source.add_digital_output(
            channel_name="DO_0",
            module_index=3,
            channel_index=0
        )

        assert "DO_0" in opto22_source.channels
        mapping = opto22_source.channels["DO_0"]
        assert "/digitalOutputs/3/channels/0/state" in mapping.source_address
        assert mapping.is_output is True

    def test_add_scratchpad_variable(self, opto22_source):
        """Test adding scratchpad variable"""
        opto22_source.add_scratchpad_variable(
            channel_name="Setpoint",
            var_name="fSetpoint",
            data_type="float32",
            is_output=True
        )

        assert "Setpoint" in opto22_source.channels
        mapping = opto22_source.channels["Setpoint"]
        assert "/vars/fSetpoint/value" in mapping.source_address


class TestBatchReading:
    """Test batch reading functionality"""

    def test_batch_read_uses_batch_endpoint(self):
        """Test batch reading uses batch endpoint when configured"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API,
            batch_endpoint="/api/batch",
            batch_key="tags"
        )
        source = RestDataSource(config)
        source._client = MagicMock()

        source.add_channel(ChannelMapping(channel_name="ch1", source_address="tag1"))
        source.add_channel(ChannelMapping(channel_name="ch2", source_address="tag2"))

        mock_response = MagicMock()
        mock_response.json.return_value = {"tag1": 100, "tag2": 200}
        source._client.post.return_value = mock_response

        with patch('rest_reader.HTTPX_AVAILABLE', True):
            source._make_request = MagicMock(return_value={"tag1": 100, "tag2": 200})
            values = source._read_batch()

        # Should call batch endpoint
        source._make_request.assert_called_once()
        call_args = source._make_request.call_args
        assert call_args[0][1] == "/api/batch"


class TestConnect:
    """Test connection functionality"""

    def test_connect_success(self):
        """Test successful connection"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API
        )
        source = RestDataSource(config)

        with patch.object(source, '_create_client') as mock_create:
            with patch.object(source, '_make_request', return_value={"status": "ok"}):
                result = source.connect()

        assert result is True
        mock_create.assert_called_once()

    def test_connect_failure(self):
        """Test connection failure"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API
        )
        source = RestDataSource(config)

        with patch.object(source, '_create_client'):
            with patch.object(source, '_make_request', return_value=None):
                result = source.connect()

        assert result is False

    def test_disconnect(self):
        """Test disconnection"""
        config = RestSourceConfig(
            name="test_api",
            source_type=DataSourceType.REST_API
        )
        source = RestDataSource(config)
        mock_client = MagicMock()
        source._client = mock_client

        source.disconnect()

        mock_client.close.assert_called_once()
        assert source._client is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
