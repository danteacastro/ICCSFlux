"""
MQTT Interface for cRIO Node V2

Clean wrapper around paho-mqtt with:
- Automatic reconnection
- Topic building helpers
- JSON serialization
- Non-blocking message callback
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, List

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

logger = logging.getLogger('cRIONode')

@dataclass
class MQTTConfig:
    """MQTT connection configuration."""
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "crio-001"
    base_topic: str = "nisystem"
    node_id: str = "crio-001"
    keepalive: int = 60
    reconnect_delay: float = 5.0
    tls_enabled: bool = False
    tls_ca_cert: Optional[str] = None  # Path to CA certificate file

class MQTTInterface:
    """
    MQTT interface with automatic reconnection.

    The on_message callback is called from paho's thread.
    IMPORTANT: Callbacks should be non-blocking (just queue the message).

    Usage:
        mqtt = MQTTInterface(config)
        mqtt.on_message = lambda topic, payload: command_queue.put((topic, payload))
        mqtt.connect()
        mqtt.publish("status", {"state": "online"})
    """

    def __init__(self, config: MQTTConfig):
        if not MQTT_AVAILABLE:
            raise RuntimeError("paho-mqtt not available")

        self.config = config
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._shutdown = threading.Event()

        # Callback for incoming messages
        # Signature: (topic: str, payload: Dict) -> None
        self.on_message: Optional[Callable[[str, Dict], None]] = None

        # Callback for connection state changes
        # Signature: (connected: bool) -> None
        self.on_connection_change: Optional[Callable[[bool], None]] = None

        # Topics to subscribe on connect
        self._subscriptions: List[str] = []

    @property
    def topic_base(self) -> str:
        """Get node-prefixed topic base (e.g., 'nisystem/nodes/crio-001')."""
        return f"{self.config.base_topic}/nodes/{self.config.node_id}"

    def topic(self, category: str, entity: str = "") -> str:
        """Build full topic path."""
        base = self.topic_base
        if entity:
            return f"{base}/{category}/{entity}"
        return f"{base}/{category}"

    def connect(self) -> bool:
        """
        Connect to MQTT broker.
        Returns True if connection initiated (not necessarily connected yet).
        Safe to call after disconnect() for retry.
        """
        try:
            # Reset shutdown flag so reconnect logic works correctly
            self._shutdown.clear()

            # paho-mqtt 2.x requires callback_api_version
            try:
                self._client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.config.client_id,
                    protocol=mqtt.MQTTv311
                )
            except (AttributeError, TypeError):
                # Fallback for paho-mqtt 1.x
                self._client = mqtt.Client(
                    client_id=self.config.client_id,
                    protocol=mqtt.MQTTv311
                )

            if self.config.username:
                self._client.username_pw_set(
                    self.config.username,
                    self.config.password
                )

            # Configure TLS if enabled
            if self.config.tls_enabled and self.config.tls_ca_cert:
                import ssl
                self._client.tls_set(
                    ca_certs=self.config.tls_ca_cert,
                    cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )
                logger.info(f"MQTT TLS enabled with CA: {self.config.tls_ca_cert}")

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            # Set last will (offline status)
            self._client.will_set(
                self.topic("status", "system"),
                json.dumps({"status": "offline", "node_id": self.config.node_id}),
                qos=1,
                retain=True
            )

            # Start connection
            self._client.connect_async(
                self.config.broker_host,
                self.config.broker_port,
                keepalive=self.config.keepalive
            )

            # Start network loop in background thread
            self._client.loop_start()

            logger.info(f"MQTT connecting to {self.config.broker_host}:{self.config.broker_port}")
            return True

        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from broker."""
        self._shutdown.set()

        if self._client:
            # Publish offline status before disconnecting
            try:
                self._client.publish(
                    self.topic("status", "system"),
                    json.dumps({"status": "offline", "node_id": self.config.node_id}),
                    qos=1,
                    retain=True
                )
            except Exception as e:
                logger.debug(f"Could not publish offline status during disconnect: {e}")

            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected.clear()

        logger.info("MQTT disconnected")

    def subscribe(self, topic_pattern: str, qos: int = 1):
        """
        Subscribe to topic pattern.
        Subscriptions are restored on reconnect.
        Deduplicates to prevent list growth across reconnect cycles.
        """
        if (topic_pattern, qos) not in self._subscriptions:
            self._subscriptions.append((topic_pattern, qos))

        if self._connected.is_set() and self._client:
            self._client.subscribe(topic_pattern, qos)
            logger.debug(f"Subscribed to {topic_pattern}")

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        """
        Publish message to topic.

        Args:
            topic: Full topic path or relative to topic_base
            payload: Dict/list to serialize as JSON, or string/bytes
            qos: Quality of service (0, 1, or 2)
            retain: Retain message on broker

        Returns:
            True if published successfully
        """
        if not self._connected.is_set() or not self._client:
            return False

        # Build full topic if relative
        if not topic.startswith(self.config.base_topic):
            topic = f"{self.topic_base}/{topic}"

        # Serialize payload
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
            logger.error(f"MQTT publish failed: {e}")
            return False

    def publish_critical(self, topic: str, payload: Any, retain: bool = False) -> bool:
        """Publish critical message with QoS 1 (guaranteed delivery)."""
        return self.publish(topic, payload, qos=1, retain=retain)

    def is_connected(self) -> bool:
        """Check if connected to broker."""
        return self._connected.is_set()

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for connection to be established."""
        return self._connected.wait(timeout)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle connection established (paho-mqtt 2.x API)."""
        # reason_code is ReasonCode object in 2.x, int in 1.x
        is_success = (reason_code == 0) if isinstance(reason_code, int) else not reason_code.is_failure

        if is_success:
            logger.info("MQTT connected")
            self._connected.set()

            # Restore subscriptions
            for topic_pattern, qos in self._subscriptions:
                client.subscribe(topic_pattern, qos)
                logger.debug(f"Resubscribed to {topic_pattern}")

            # Notify callback
            if self.on_connection_change:
                try:
                    self.on_connection_change(True)
                except Exception as e:
                    logger.error(f"Connection callback error: {e}")
        else:
            logger.error(f"MQTT connection failed: rc={reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags_or_rc, reason_code=None, properties=None):
        """Handle disconnection (paho-mqtt 2.x API)."""
        self._connected.clear()

        # In 2.x: disconnect_flags_or_rc is DisconnectFlags, reason_code is ReasonCode
        # In 1.x: disconnect_flags_or_rc is rc (int), reason_code is None
        if reason_code is None:
            # paho-mqtt 1.x style
            rc = disconnect_flags_or_rc
            is_unexpected = (rc != 0)
        else:
            # paho-mqtt 2.x style
            rc = reason_code
            is_unexpected = reason_code.is_failure if hasattr(reason_code, 'is_failure') else (reason_code != 0)

        if is_unexpected and not self._shutdown.is_set():
            logger.warning(
                f"MQTT unexpected disconnect: rc={rc} — "
                f"paho will attempt automatic reconnection"
            )
        elif is_unexpected:
            logger.info(f"MQTT disconnected during shutdown: rc={rc}")
        else:
            logger.info("MQTT disconnected normally")

        # Notify callback
        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception as e:
                logger.error(f"Disconnection callback error: {e}")

    # Maximum accepted MQTT payload size (256 KB)
    MAX_PAYLOAD_SIZE = 262144

    def _on_message(self, client, userdata, msg):
        """
        Handle incoming message.
        IMPORTANT: This runs in paho's thread - must be non-blocking!
        """
        if not self.on_message:
            return

        if len(msg.payload) > self.MAX_PAYLOAD_SIZE:
            logger.warning(
                f"Oversized MQTT payload on {msg.topic}: "
                f"{len(msg.payload)} bytes (limit {self.MAX_PAYLOAD_SIZE}), dropping"
            )
            return

        try:
            # Parse JSON payload
            payload = json.loads(msg.payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Non-JSON payload
            payload = {'raw': msg.payload}

        try:
            self.on_message(msg.topic, payload)
        except Exception as e:
            logger.error(f"Message callback error: {e}")

    def setup_standard_subscriptions(self):
        """Set up standard subscriptions for cRIO node."""
        base = self.topic_base

        # Command topics (from DAQ service)
        self.subscribe(f"{base}/config/#")      # Config updates
        self.subscribe(f"{base}/commands/#")    # Output commands
        self.subscribe(f"{base}/system/#")      # System commands (acquire, etc.)
        self.subscribe(f"{base}/session/#")     # Session commands
        self.subscribe(f"{base}/script/#")      # Script commands
        self.subscribe(f"{base}/safety/#")      # Safety commands
        self.subscribe(f"{base}/alarm/#")       # Alarm ack from DAQ service

        # Global discovery ping
        self.subscribe(f"{self.config.base_topic}/discovery/ping")

        logger.info(f"Standard subscriptions configured for {base}")
