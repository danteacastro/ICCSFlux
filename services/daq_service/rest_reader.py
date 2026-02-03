"""
REST API Reader for NISystem
Reads values from devices with REST APIs (Opto22, custom endpoints, etc.)
Provides the same interface as other data sources for unified access.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum

from data_source_manager import (
    DataSource, DataSourceConfig, DataSourceType, ChannelMapping,
    ConnectionState, DataSourceManager
)

# Try to import httpx (preferred) or fall back to requests
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

if not HTTPX_AVAILABLE and not REQUESTS_AVAILABLE:
    raise ImportError("Either httpx or requests library is required for REST API support")

logger = logging.getLogger('RestReader')


class AuthType(Enum):
    """Authentication types for REST APIs"""
    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"
    API_KEY = "api_key"
    CUSTOM_HEADER = "custom_header"


class HttpMethod(Enum):
    """HTTP methods"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"


@dataclass
class RestEndpointConfig:
    """Configuration for a REST API endpoint"""
    path: str  # e.g., "/api/v1/analog/0" or "/read?tag={tag}"
    method: HttpMethod = HttpMethod.GET
    response_key: Optional[str] = None  # JSON path to value, e.g., "data.value" or "result[0].value"
    body_template: Optional[str] = None  # For POST/PUT, JSON template with {value} placeholder
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class RestSourceConfig(DataSourceConfig):
    """Configuration for a REST API data source"""
    # Connection settings
    base_url: str = "http://192.168.1.100"  # e.g., "http://192.168.1.100:8080"

    # Authentication
    auth_type: AuthType = AuthType.NONE
    username: str = ""
    password: str = ""
    api_key: str = ""
    api_key_header: str = "X-API-Key"
    bearer_token: str = ""
    custom_headers: Dict[str, str] = field(default_factory=dict)

    # Request settings
    verify_ssl: bool = True
    follow_redirects: bool = True

    # Batch reading (if API supports reading multiple values at once)
    batch_endpoint: Optional[str] = None  # e.g., "/api/v1/batch"
    batch_key: str = "tags"  # Key name for tag list in batch request

    def __post_init__(self):
        # Ensure source_type is set correctly
        self.source_type = DataSourceType.REST_API


@dataclass
class RestChannelMapping(ChannelMapping):
    """Extended channel mapping for REST API sources"""
    endpoint: Optional[RestEndpointConfig] = None

    # For simple GET endpoints, just use source_address as the path
    # For complex endpoints, use the endpoint config


class RestDataSource(DataSource):
    """
    Data source that reads from REST APIs.
    Supports Opto22, custom APIs, and any device with HTTP endpoints.
    """

    def __init__(self, config: RestSourceConfig):
        super().__init__(config)
        self.rest_config = config
        self._client = None
        self._session = None

    def _create_client(self):
        """Create HTTP client with authentication configured."""
        headers = dict(self.rest_config.custom_headers)

        # Set up authentication headers
        auth = None
        if self.rest_config.auth_type == AuthType.BASIC:
            if HTTPX_AVAILABLE:
                auth = httpx.BasicAuth(self.rest_config.username, self.rest_config.password)
            else:
                auth = (self.rest_config.username, self.rest_config.password)

        elif self.rest_config.auth_type == AuthType.BEARER:
            headers['Authorization'] = f'Bearer {self.rest_config.bearer_token}'

        elif self.rest_config.auth_type == AuthType.API_KEY:
            headers[self.rest_config.api_key_header] = self.rest_config.api_key

        elif self.rest_config.auth_type == AuthType.CUSTOM_HEADER:
            # Custom headers already added above
            pass

        if HTTPX_AVAILABLE:
            self._client = httpx.Client(
                base_url=self.rest_config.base_url,
                headers=headers,
                auth=auth,
                timeout=self.rest_config.timeout_s,
                verify=self.rest_config.verify_ssl,
                follow_redirects=self.rest_config.follow_redirects
            )
        else:
            self._session = requests.Session()
            self._session.headers.update(headers)
            if auth:
                self._session.auth = auth
            self._session.verify = self.rest_config.verify_ssl

    def connect(self) -> bool:
        """Test connection to the REST API."""
        try:
            self._create_client()

            # Try a simple request to verify connectivity
            # Use the first channel's endpoint or just the base URL
            test_path = "/"
            if self.channels:
                first_channel = list(self.channels.values())[0]
                test_path = first_channel.source_address

            response = self._make_request("GET", test_path)
            if response is not None:
                logger.info(f"[{self.name}] Connected to {self.rest_config.base_url}")
                return True
            else:
                logger.warning(f"[{self.name}] Connection test failed")
                return False

        except Exception as e:
            self.status.last_error = str(e)
            logger.error(f"[{self.name}] Connection failed: {e}")
            return False

    def disconnect(self):
        """Close the HTTP client."""
        try:
            if self._client:
                self._client.close()
                self._client = None
            if self._session:
                self._session.close()
                self._session = None
            logger.info(f"[{self.name}] Disconnected")
        except Exception as e:
            logger.error(f"[{self.name}] Error disconnecting: {e}")

    def _make_request(self, method: str, path: str, body: Any = None,
                      headers: Dict[str, str] = None) -> Optional[Any]:
        """Make an HTTP request and return the parsed JSON response."""
        try:
            url = path if path.startswith('http') else path

            if HTTPX_AVAILABLE and self._client:
                if method == "GET":
                    response = self._client.get(url, headers=headers)
                elif method == "POST":
                    response = self._client.post(url, json=body, headers=headers)
                elif method == "PUT":
                    response = self._client.put(url, json=body, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # Try to parse JSON, fall back to text
                try:
                    return response.json()
                except (json.JSONDecodeError, ValueError):
                    return response.text

            elif self._session:
                full_url = f"{self.rest_config.base_url}{url}" if not url.startswith('http') else url

                if method == "GET":
                    response = self._session.get(full_url, headers=headers,
                                                  timeout=self.rest_config.timeout_s)
                elif method == "POST":
                    response = self._session.post(full_url, json=body, headers=headers,
                                                   timeout=self.rest_config.timeout_s)
                elif method == "PUT":
                    response = self._session.put(full_url, json=body, headers=headers,
                                                  timeout=self.rest_config.timeout_s)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                try:
                    return response.json()
                except (json.JSONDecodeError, ValueError):
                    return response.text
            else:
                raise RuntimeError("No HTTP client available")

        except Exception as e:
            logger.warning(f"[{self.name}] Request failed: {method} {path}: {e}")
            raise

    def _extract_value(self, response: Any, json_path: Optional[str]) -> Any:
        """Extract a value from a JSON response using a dot-notation path."""
        if json_path is None:
            return response

        if isinstance(response, (int, float, str, bool)):
            return response

        # Parse path like "data.value" or "results[0].temperature"
        parts = json_path.replace('[', '.').replace(']', '').split('.')
        value = response

        for part in parts:
            if not part:
                continue
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list):
                try:
                    value = value[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None

            if value is None:
                return None

        return value

    def _apply_scaling(self, value: Any, mapping: ChannelMapping) -> Any:
        """Apply scale and offset to a value."""
        if value is None:
            return None

        try:
            num_value = float(value)
            return num_value * mapping.scale + mapping.offset
        except (ValueError, TypeError):
            return value  # Return non-numeric values as-is

    def read_all(self) -> Dict[str, Any]:
        """Read all configured channels."""
        values = {}

        # Check if batch reading is supported
        if self.rest_config.batch_endpoint and len(self.channels) > 1:
            values = self._read_batch()
        else:
            # Read each channel individually
            for channel_name, mapping in self.channels.items():
                try:
                    value = self._read_single_channel(mapping)
                    values[channel_name] = value
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to read {channel_name}: {e}")
                    values[channel_name] = None

        return values

    def _read_batch(self) -> Dict[str, Any]:
        """Read multiple channels in a single batch request."""
        try:
            # Build batch request
            tags = [m.source_address for m in self.channels.values()]
            body = {self.rest_config.batch_key: tags}

            response = self._make_request("POST", self.rest_config.batch_endpoint, body=body)

            # Parse response - assume it returns a dict with tag names as keys
            values = {}
            for channel_name, mapping in self.channels.items():
                raw_value = self._extract_value(response, mapping.source_address)
                values[channel_name] = self._apply_scaling(raw_value, mapping)

            return values

        except Exception as e:
            logger.warning(f"[{self.name}] Batch read failed: {e}")
            # Fall back to individual reads
            return {name: self._read_single_channel(m) for name, m in self.channels.items()}

    def _read_single_channel(self, mapping: ChannelMapping) -> Optional[Any]:
        """Read a single channel value."""
        # Get endpoint config if available
        endpoint = None
        if isinstance(mapping, RestChannelMapping) and mapping.endpoint:
            endpoint = mapping.endpoint

        # Determine path and method
        path = mapping.source_address
        method = "GET"
        response_key = None
        headers = {}

        if endpoint:
            path = endpoint.path
            method = endpoint.method.value
            response_key = endpoint.response_key
            headers = endpoint.headers

        # Make request
        response = self._make_request(method, path, headers=headers)

        # Extract value from response
        raw_value = self._extract_value(response, response_key)

        # Apply scaling
        return self._apply_scaling(raw_value, mapping)

    def read_channel(self, channel_name: str) -> Optional[Any]:
        """Read a single channel value."""
        if channel_name not in self.channels:
            return None

        mapping = self.channels[channel_name]
        try:
            return self._read_single_channel(mapping)
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to read {channel_name}: {e}")
            return None

    def write_channel(self, channel_name: str, value: Any) -> bool:
        """Write a value to a channel."""
        if channel_name not in self.channels:
            logger.warning(f"[{self.name}] Channel not found: {channel_name}")
            return False

        mapping = self.channels[channel_name]
        if not mapping.is_output:
            logger.warning(f"[{self.name}] Channel {channel_name} is not writable")
            return False

        try:
            # Reverse scaling: raw = (value - offset) / scale
            if mapping.scale != 0:
                raw_value = (float(value) - mapping.offset) / mapping.scale
            else:
                raw_value = value

            # Get endpoint config
            endpoint = None
            if isinstance(mapping, RestChannelMapping) and mapping.endpoint:
                endpoint = mapping.endpoint

            # Determine path, method, and body
            path = mapping.source_address
            method = "PUT"  # Default for writes
            body = {"value": raw_value}
            headers = {}

            if endpoint:
                path = endpoint.path
                method = endpoint.method.value
                headers = endpoint.headers

                # Use body template if provided
                if endpoint.body_template:
                    body = json.loads(endpoint.body_template.replace("{value}", str(raw_value)))

            # Make request
            self._make_request(method, path, body=body, headers=headers)

            self.status.write_count += 1
            logger.debug(f"[{self.name}] Wrote {channel_name} = {value}")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Failed to write {channel_name}: {e}")
            return False

    def get_connection_config(self) -> Dict[str, Any]:
        """Get connection-specific config for serialization."""
        return {
            'base_url': self.rest_config.base_url,
            'auth_type': self.rest_config.auth_type.value,
            'username': self.rest_config.username,
            'api_key_header': self.rest_config.api_key_header,
            'verify_ssl': self.rest_config.verify_ssl,
            'follow_redirects': self.rest_config.follow_redirects,
            'batch_endpoint': self.rest_config.batch_endpoint,
            'batch_key': self.rest_config.batch_key,
        }


# Register REST API data source type
DataSourceManager.register_source_type(DataSourceType.REST_API, RestDataSource)


# ============================================================================
# Opto22 Specific Implementation
# ============================================================================

class Opto22DataSource(RestDataSource):
    """
    Pre-configured REST data source for Opto22 groov EPIC/RIO devices.
    Uses Opto22's REST API conventions.
    """

    # Opto22 API endpoints
    ANALOG_INPUT = "/api/v1/device/strategy/ios/analogInputs"
    ANALOG_OUTPUT = "/api/v1/device/strategy/ios/analogOutputs"
    DIGITAL_INPUT = "/api/v1/device/strategy/ios/digitalInputs"
    DIGITAL_OUTPUT = "/api/v1/device/strategy/ios/digitalOutputs"
    SCRATCH_PAD = "/api/v1/device/strategy/vars"

    def __init__(self, config: RestSourceConfig):
        super().__init__(config)
        # Set default headers for Opto22
        if 'Content-Type' not in self.rest_config.custom_headers:
            self.rest_config.custom_headers['Content-Type'] = 'application/json'
        if 'Accept' not in self.rest_config.custom_headers:
            self.rest_config.custom_headers['Accept'] = 'application/json'

    def add_analog_input(self, channel_name: str, module_index: int, channel_index: int,
                         unit: str = "", scale: float = 1.0, offset: float = 0.0):
        """Add an analog input channel."""
        path = f"{self.ANALOG_INPUT}/{module_index}/channels/{channel_index}/value"
        mapping = RestChannelMapping(
            channel_name=channel_name,
            source_address=path,
            data_type="float32",
            scale=scale,
            offset=offset,
            unit=unit,
            is_output=False
        )
        self.add_channel(mapping)

    def add_analog_output(self, channel_name: str, module_index: int, channel_index: int,
                          unit: str = "", scale: float = 1.0, offset: float = 0.0):
        """Add an analog output channel."""
        path = f"{self.ANALOG_OUTPUT}/{module_index}/channels/{channel_index}/value"
        mapping = RestChannelMapping(
            channel_name=channel_name,
            source_address=path,
            data_type="float32",
            scale=scale,
            offset=offset,
            unit=unit,
            is_output=True
        )
        self.add_channel(mapping)

    def add_digital_input(self, channel_name: str, module_index: int, channel_index: int):
        """Add a digital input channel."""
        path = f"{self.DIGITAL_INPUT}/{module_index}/channels/{channel_index}/state"
        mapping = RestChannelMapping(
            channel_name=channel_name,
            source_address=path,
            data_type="bool",
            is_output=False
        )
        self.add_channel(mapping)

    def add_digital_output(self, channel_name: str, module_index: int, channel_index: int):
        """Add a digital output channel."""
        path = f"{self.DIGITAL_OUTPUT}/{module_index}/channels/{channel_index}/state"
        mapping = RestChannelMapping(
            channel_name=channel_name,
            source_address=path,
            data_type="bool",
            is_output=True
        )
        self.add_channel(mapping)

    def add_scratchpad_variable(self, channel_name: str, var_name: str,
                                 data_type: str = "float32", is_output: bool = False):
        """Add a PAC Control scratchpad variable."""
        path = f"{self.SCRATCH_PAD}/{var_name}/value"
        mapping = RestChannelMapping(
            channel_name=channel_name,
            source_address=path,
            data_type=data_type,
            is_output=is_output
        )
        self.add_channel(mapping)


# ============================================================================
# Test / Example Usage
# ============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)

    if not HTTPX_AVAILABLE and not REQUESTS_AVAILABLE:
        print("No HTTP library available!")
        print("Install with: pip install httpx  OR  pip install requests")
        sys.exit(1)

    print(f"Using {'httpx' if HTTPX_AVAILABLE else 'requests'} for HTTP requests")

    # Example: Create a REST data source for a test API
    config = RestSourceConfig(
        name="TestAPI",
        source_type=DataSourceType.REST_API,
        base_url="https://httpbin.org",
        poll_rate_ms=1000,
        timeout_s=5.0
    )

    source = RestDataSource(config)

    # Add a test channel (httpbin.org returns request info)
    source.add_channel(ChannelMapping(
        channel_name="test_ip",
        source_address="/ip",
        data_type="string"
    ))

    # Test connection
    if source.connect():
        print("Connected successfully!")
        source.status.state = ConnectionState.CONNECTED

        # Read values
        values = source.read_all()
        print(f"Values: {values}")

        source.disconnect()
    else:
        print("Connection failed!")
