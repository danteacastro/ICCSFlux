"""
Hardware Abstraction for Opto22 Node

Receives I/O data from groov Manage's MQTT broker and maintains
a latest_values dictionary matching the cRIO hardware interface.

groov Manage publishes I/O data to topics like:
  groov/io/<module>/<channel>

This module maps those topics to NISystem channel names via config.

Fallback: If groov Manage MQTT is unavailable, uses groov Manage REST API.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger('Opto22Node')

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class GroovIOSubscriber:
    """
    Receives I/O data from groov Manage MQTT and maintains latest values.

    The GroovMQTT client calls on_io_message() for each incoming I/O message.
    This class parses the topic, maps to NISystem channel names, and stores values.
    """

    def __init__(self, topic_mapping: Optional[Dict[str, str]] = None):
        """
        Args:
            topic_mapping: Optional dict mapping groov topics to NISystem channel names.
                          e.g., {"groov/io/mod0/ch0": "TC_Zone1", "groov/io/mod0/ch1": "TC_Zone2"}
                          If None, auto-derives channel names from topic.
        """
        self._topic_mapping = topic_mapping or {}
        self._reverse_mapping: Dict[str, str] = {}  # channel name -> groov topic
        self._values: Dict[str, float] = {}
        self._qualities: Dict[str, str] = {}  # channel -> 'good', 'bad', 'uncertain'
        self._last_update: Dict[str, float] = {}
        self._lock = threading.Lock()

        # Build reverse mapping
        for groov_topic, channel_name in self._topic_mapping.items():
            self._reverse_mapping[channel_name] = groov_topic

    def on_io_message(self, topic: str, payload: Any):
        """
        Called by GroovMQTT when I/O data arrives.

        Args:
            topic: groov MQTT topic (e.g., "groov/io/mod0/ch0")
            payload: Value (float, int, bool, or dict with 'value' key)
        """
        channel_name = self._resolve_channel_name(topic)
        value = self._extract_value(payload)

        if value is not None:
            with self._lock:
                self._values[channel_name] = value
                self._qualities[channel_name] = 'good'
                self._last_update[channel_name] = time.time()

    def _resolve_channel_name(self, topic: str) -> str:
        """Map groov topic to NISystem channel name."""
        if topic in self._topic_mapping:
            return self._topic_mapping[topic]
        # Auto-derive: "groov/io/mod0/ch0" -> "mod0_ch0"
        parts = topic.split('/')
        if len(parts) >= 3:
            return '_'.join(parts[2:])
        return topic.replace('/', '_')

    def _extract_value(self, payload: Any) -> Optional[float]:
        """Extract numeric value from MQTT payload."""
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, bool):
            return 1.0 if payload else 0.0
        if isinstance(payload, dict):
            # groov Manage may publish {"value": 23.5, "quality": "good"}
            v = payload.get('value')
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        if isinstance(payload, str):
            try:
                return float(payload)
            except ValueError:
                pass
        return None

    def get_values(self) -> Dict[str, float]:
        """Get snapshot of all current channel values."""
        with self._lock:
            return dict(self._values)

    def get_value(self, channel: str) -> Optional[float]:
        """Get value for a single channel."""
        with self._lock:
            return self._values.get(channel)

    def get_qualities(self) -> Dict[str, str]:
        """Get snapshot of all channel qualities."""
        with self._lock:
            return dict(self._qualities)

    def get_stale_channels(self, timeout_s: float = 10.0) -> List[str]:
        """Get channels that haven't been updated within timeout."""
        now = time.time()
        stale = []
        with self._lock:
            for channel, last in self._last_update.items():
                if now - last > timeout_s:
                    stale.append(channel)
        return stale

    def update_topic_mapping(self, mapping: Dict[str, str]):
        """Update the topic-to-channel name mapping."""
        self._topic_mapping = mapping
        self._reverse_mapping = {v: k for k, v in mapping.items()}

    @property
    def channel_count(self) -> int:
        with self._lock:
            return len(self._values)


class GroovRestFallback:
    """
    Fallback I/O reader using groov Manage REST API.

    Used when groov Manage MQTT broker is unavailable.
    Uses groov Manage API (NOT PAC Control API).

    API endpoint: https://<host>/manage/api/v1/io/local/modules/
    """

    def __init__(self, host: str, port: int = 443, api_key: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 verify_ssl: bool = False):
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests library not available for REST fallback")

        self._base_url = f"https://{host}:{port}/manage/api/v1"
        self._session = requests.Session()
        self._session.verify = verify_ssl

        if api_key:
            self._session.headers['apiKey'] = api_key
        elif username and password:
            self._session.auth = (username, password)

    def read_all_modules(self) -> Dict[str, Any]:
        """Read all I/O modules and their channel values."""
        try:
            resp = self._session.get(f"{self._base_url}/io/local/modules/", timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"groov REST read_all_modules failed: {e}")
            return {}

    def read_channel(self, module_index: int, channel_index: int) -> Optional[float]:
        """Read a single channel value."""
        try:
            resp = self._session.get(
                f"{self._base_url}/io/local/modules/{module_index}/channels/{channel_index}",
                timeout=5.0
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get('value', 0))
        except Exception as e:
            logger.error(f"groov REST read_channel({module_index}/{channel_index}) failed: {e}")
            return None

    def write_channel(self, module_index: int, channel_index: int, value: float) -> bool:
        """Write a value to an output channel."""
        try:
            resp = self._session.put(
                f"{self._base_url}/io/local/modules/{module_index}/channels/{channel_index}",
                json={'value': value},
                timeout=5.0
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"groov REST write_channel({module_index}/{channel_index}={value}) failed: {e}")
            return False

    def poll_values(self, channel_map: Dict[str, tuple]) -> Dict[str, float]:
        """
        Poll all configured channels via REST.

        Args:
            channel_map: {channel_name: (module_index, channel_index)}

        Returns:
            {channel_name: value}
        """
        values = {}
        for name, (mod_idx, ch_idx) in channel_map.items():
            val = self.read_channel(mod_idx, ch_idx)
            if val is not None:
                values[name] = val
        return values


class HardwareInterface:
    """
    Unified hardware interface for Opto22 node.

    Primary: GroovIOSubscriber (MQTT-based, real-time)
    Fallback: GroovRestFallback (polling-based)

    Provides the same get_values() / write_output() interface as cRIO hardware.
    """

    def __init__(self, io_subscriber: GroovIOSubscriber,
                 rest_fallback: Optional[GroovRestFallback] = None,
                 output_write_fn: Optional[Callable[[str, float], bool]] = None):
        self.io = io_subscriber
        self._rest = rest_fallback
        self._output_write_fn = output_write_fn
        self._output_values: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_values(self) -> Dict[str, float]:
        """Get all current channel values from MQTT subscriber."""
        return self.io.get_values()

    def get_value(self, channel: str) -> Optional[float]:
        return self.io.get_value(channel)

    def write_output(self, channel: str, value: float) -> bool:
        """Write output value via the configured write function."""
        if self._output_write_fn:
            success = self._output_write_fn(channel, value)
            if success:
                with self._lock:
                    self._output_values[channel] = value
            return success
        logger.warning(f"No output write function configured for {channel}")
        return False

    def get_output_values(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._output_values)
