"""
MQTT Interface for Opto22 Node

Dual-connection MQTT wrapper:
- System connection: NISystem Mosquitto broker (commands, data publishing)
- Upstream connection: groov Manage's built-in MQTT broker (I/O data subscription)

Features:
- Automatic reconnection on both connections
- Topic building helpers
- JSON serialization
- Non-blocking message callbacks
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, List

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

logger = logging.getLogger('Opto22Node')


@dataclass
class MQTTConfig:
    """MQTT connection configuration for NISystem broker."""
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "opto22-001"
    base_topic: str = "nisystem"
    node_id: str = "opto22-001"
    keepalive: int = 60
    reconnect_delay: float = 5.0
    tls_enabled: bool = False
    tls_ca_cert: Optional[str] = None


@dataclass
class GroovMQTTConfig:
    """MQTT connection configuration for groov Manage's MQTT broker."""
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "nisystem-opto22-subscriber"
    keepalive: int = 60
    tls_enabled: bool = False
    tls_ca_cert: Optional[str] = None
    # Topic patterns to subscribe to for I/O data
    io_topic_patterns: List[str] = field(default_factory=lambda: ["groov/io/#"])


def _create_mqtt_client(client_id: str) -> 'mqtt.Client':
    """Create paho MQTT client compatible with both 1.x and 2.x."""
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311
        )
    except (AttributeError, TypeError):
        return mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311
        )


class SystemMQTT:
    """
    MQTT interface to NISystem's Mosquitto broker.
    Handles command reception and data publishing.
    """

    def __init__(self, config: MQTTConfig):
        if not MQTT_AVAILABLE:
            raise RuntimeError("paho-mqtt not available")

        self.config = config
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._shutdown = threading.Event()
        self.on_message: Optional[Callable[[str, Dict], None]] = None
        self.on_connection_change: Optional[Callable[[bool], None]] = None
        self._subscriptions: List = []

    @property
    def topic_base(self) -> str:
        return f"{self.config.base_topic}/nodes/{self.config.node_id}"

    def topic(self, category: str, entity: str = "") -> str:
        base = self.topic_base
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    def connect(self) -> bool:
        try:
            self._client = _create_mqtt_client(self.config.client_id)

            if self.config.username:
                self._client.username_pw_set(self.config.username, self.config.password)

            if self.config.tls_enabled and self.config.tls_ca_cert:
                import ssl
                self._client.tls_set(
                    ca_certs=self.config.tls_ca_cert,
                    cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            self._client.will_set(
                self.topic("status", "system"),
                json.dumps({"status": "offline", "node_id": self.config.node_id}),
                qos=1, retain=True
            )

            self._client.connect_async(
                self.config.broker_host, self.config.broker_port,
                keepalive=self.config.keepalive
            )
            self._client.loop_start()
            logger.info(f"System MQTT connecting to {self.config.broker_host}:{self.config.broker_port}")
            return True
        except Exception as e:
            logger.error(f"System MQTT connection failed: {e}")
            return False

    def disconnect(self):
        self._shutdown.set()
        if self._client:
            try:
                self._client.publish(
                    self.topic("status", "system"),
                    json.dumps({"status": "offline", "node_id": self.config.node_id}),
                    qos=1, retain=True
                )
            except Exception:
                pass
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected.clear()

    def subscribe(self, topic_pattern: str, qos: int = 1):
        self._subscriptions.append((topic_pattern, qos))
        if self._connected.is_set() and self._client:
            self._client.subscribe(topic_pattern, qos)

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        if not self._connected.is_set() or not self._client:
            return False
        if not topic.startswith(self.config.base_topic):
            topic = f"{self.topic_base}/{topic}"
        if isinstance(payload, (dict, list)):
            message = json.dumps(payload)
        elif isinstance(payload, bytes):
            message = payload
        else:
            message = str(payload)
        try:
            result = self._client.publish(topic, message, qos=qos, retain=retain)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"System MQTT publish failed: {e}")
            return False

    def publish_critical(self, topic: str, payload: Any, retain: bool = False) -> bool:
        return self.publish(topic, payload, qos=1, retain=retain)

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        return self._connected.wait(timeout)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        is_success = (reason_code == 0) if isinstance(reason_code, int) else not reason_code.is_failure
        if is_success:
            logger.info("System MQTT connected")
            self._connected.set()
            for topic_pattern, qos in self._subscriptions:
                client.subscribe(topic_pattern, qos)
            if self.on_connection_change:
                try:
                    self.on_connection_change(True)
                except Exception as e:
                    logger.error(f"Connection callback error: {e}")
        else:
            logger.error(f"System MQTT connection failed: rc={reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags_or_rc, reason_code=None, properties=None):
        self._connected.clear()
        if reason_code is None:
            is_unexpected = (disconnect_flags_or_rc != 0)
        else:
            is_unexpected = reason_code.is_failure if hasattr(reason_code, 'is_failure') else (reason_code != 0)
        if is_unexpected and not self._shutdown.is_set():
            logger.warning("System MQTT unexpected disconnect — paho will auto-reconnect")
        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception:
                pass

    MAX_PAYLOAD_SIZE = 262144

    def _on_message(self, client, userdata, msg):
        if not self.on_message:
            return
        if len(msg.payload) > self.MAX_PAYLOAD_SIZE:
            logger.warning(f"Oversized payload on {msg.topic}: {len(msg.payload)} bytes, dropping")
            return
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {'raw': msg.payload}
        try:
            self.on_message(msg.topic, payload)
        except Exception as e:
            logger.error(f"System message callback error: {e}")

    def setup_standard_subscriptions(self):
        """Set up standard subscriptions for Opto22 node."""
        base = self.topic_base
        self.subscribe(f"{base}/config/#")
        self.subscribe(f"{base}/commands/#")
        self.subscribe(f"{base}/system/#")
        self.subscribe(f"{base}/session/#")
        self.subscribe(f"{base}/script/#")
        self.subscribe(f"{base}/safety/#")
        self.subscribe(f"{base}/alarm/#")
        self.subscribe(f"{self.config.base_topic}/discovery/ping")
        logger.info(f"Standard subscriptions configured for {base}")


class GroovMQTT:
    """
    MQTT interface to groov Manage's built-in MQTT broker.
    Subscribes to I/O topics for real-time hardware data.
    """

    def __init__(self, config: GroovMQTTConfig):
        if not MQTT_AVAILABLE:
            raise RuntimeError("paho-mqtt not available")

        self.config = config
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._shutdown = threading.Event()
        self.on_io_data: Optional[Callable[[str, Any], None]] = None
        self.on_connection_change: Optional[Callable[[bool], None]] = None

    def connect(self) -> bool:
        try:
            self._client = _create_mqtt_client(self.config.client_id)

            if self.config.username:
                self._client.username_pw_set(self.config.username, self.config.password)

            if self.config.tls_enabled and self.config.tls_ca_cert:
                import ssl
                self._client.tls_set(
                    ca_certs=self.config.tls_ca_cert,
                    cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            self._client.connect_async(
                self.config.broker_host, self.config.broker_port,
                keepalive=self.config.keepalive
            )
            self._client.loop_start()
            logger.info(f"groov MQTT connecting to {self.config.broker_host}:{self.config.broker_port}")
            return True
        except Exception as e:
            logger.error(f"groov MQTT connection failed: {e}")
            return False

    def disconnect(self):
        self._shutdown.set()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected.clear()

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        return self._connected.wait(timeout)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        is_success = (reason_code == 0) if isinstance(reason_code, int) else not reason_code.is_failure
        if is_success:
            logger.info("groov MQTT connected")
            self._connected.set()
            for pattern in self.config.io_topic_patterns:
                client.subscribe(pattern, qos=0)
                logger.info(f"groov MQTT subscribed to {pattern}")
            if self.on_connection_change:
                try:
                    self.on_connection_change(True)
                except Exception as e:
                    logger.error(f"groov connection callback error: {e}")
        else:
            logger.error(f"groov MQTT connection failed: rc={reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags_or_rc, reason_code=None, properties=None):
        self._connected.clear()
        if not self._shutdown.is_set():
            logger.warning("groov MQTT disconnected — paho will auto-reconnect")
        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception:
                pass

    def _on_message(self, client, userdata, msg):
        if not self.on_io_data:
            return
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                payload = float(msg.payload.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                payload = msg.payload
        try:
            self.on_io_data(msg.topic, payload)
        except Exception as e:
            logger.error(f"groov I/O data callback error: {e}")
