"""
Pytest configuration and shared fixtures for NISystem tests

Provides robust test harness with:
- Proper MQTT connection management
- Acquisition state management
- Reliable message waiting with subscription confirmation
- System status checking
"""

import pytest
import time
import json
import threading
from typing import Dict, List, Any, Optional
import paho.mqtt.client as mqtt


# Test configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
SYSTEM_PREFIX = "nisystem"


class MQTTTestHarness:
    """
    Robust MQTT test client with proper timing and state management.

    Features:
    - Waits for subscription to be active before proceeding
    - Tracks system state (acquiring, recording, etc.)
    - Provides reliable message waiting
    - Handles race conditions properly
    """

    def __init__(self, client_id: str):
        self.client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        self.connected = False
        self.messages: Dict[str, List[dict]] = {}
        self.message_lock = threading.Lock()
        self.subscribed_topics: set = set()
        self.subscription_complete = threading.Event()

        # System state cache
        self._system_status: Optional[dict] = None
        self._status_lock = threading.Lock()

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0
        if self.connected:
            # Always subscribe to system status for state tracking
            self.client.subscribe(f"{SYSTEM_PREFIX}/status/system")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        self.subscription_complete.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            payload = msg.payload.decode()

        # Update system status cache
        if msg.topic == f"{SYSTEM_PREFIX}/status/system":
            with self._status_lock:
                self._system_status = payload

        with self.message_lock:
            if msg.topic not in self.messages:
                self.messages[msg.topic] = []
            self.messages[msg.topic].append({
                "payload": payload,
                "timestamp": time.time()
            })

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to MQTT broker and wait for connection"""
        try:
            self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            self.client.loop_start()

            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            return self.connected
        except Exception:
            return False

    def disconnect(self):
        """Cleanly disconnect from broker"""
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe_and_wait(self, topic: str, timeout: float = 2.0) -> bool:
        """
        Subscribe to topic and wait for subscription to be confirmed.
        This ensures we don't miss messages due to race conditions.
        """
        self.subscription_complete.clear()
        self.client.subscribe(topic)
        self.subscribed_topics.add(topic)

        # Wait for subscription confirmation
        return self.subscription_complete.wait(timeout=timeout)

    def subscribe(self, topic: str):
        """Subscribe without waiting (legacy compatibility)"""
        self.client.subscribe(topic)
        self.subscribed_topics.add(topic)
        # Small delay to allow subscription to propagate
        time.sleep(0.1)

    def publish(self, topic: str, payload: Any = "{}"):
        """Publish message to topic"""
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload)

    def wait_for_message(self, topic: str, timeout: float = 5.0, count: int = 1) -> List[dict]:
        """
        Wait for messages on a topic.
        Returns list of message dicts with 'payload' and 'timestamp'.
        """
        start = time.time()
        while (time.time() - start) < timeout:
            with self.message_lock:
                if topic in self.messages and len(self.messages[topic]) >= count:
                    return self.messages[topic][:count]
            time.sleep(0.05)  # Shorter sleep for better responsiveness

        with self.message_lock:
            return self.messages.get(topic, [])

    def wait_for_new_message(self, topic: str, timeout: float = 5.0) -> Optional[dict]:
        """
        Clear existing messages and wait for a new one.
        More reliable than clear_messages + wait_for_message.
        """
        # Mark current count
        with self.message_lock:
            current_count = len(self.messages.get(topic, []))

        # Wait for a new message
        start = time.time()
        while (time.time() - start) < timeout:
            with self.message_lock:
                msgs = self.messages.get(topic, [])
                if len(msgs) > current_count:
                    return msgs[-1]  # Return newest message
            time.sleep(0.05)

        return None

    def clear_messages(self, topic: str = None):
        """Clear stored messages"""
        with self.message_lock:
            if topic:
                self.messages.pop(topic, None)
            else:
                self.messages.clear()

    def get_latest_message(self, topic: str) -> Optional[dict]:
        """Get the most recent message on a topic"""
        with self.message_lock:
            msgs = self.messages.get(topic, [])
            return msgs[-1] if msgs else None

    def get_system_status(self) -> Optional[dict]:
        """Get cached system status"""
        with self._status_lock:
            return self._system_status.copy() if self._system_status else None

    def wait_for_status(self, timeout: float = 3.0) -> Optional[dict]:
        """Wait for system status to be received"""
        start = time.time()
        while (time.time() - start) < timeout:
            status = self.get_system_status()
            if status:
                return status
            time.sleep(0.1)
        return None

    def refresh_status(self, timeout: float = 2.0) -> Optional[dict]:
        """Request fresh status and wait for it"""
        # Clear old status to force refresh
        with self._status_lock:
            old_ts = self._system_status.get("timestamp") if self._system_status else None

        # Wait for new status with different timestamp
        start = time.time()
        while (time.time() - start) < timeout:
            time.sleep(0.15)
            with self._status_lock:
                if self._system_status:
                    new_ts = self._system_status.get("timestamp")
                    if new_ts != old_ts:
                        return self._system_status.copy()
        return self.get_system_status()

    def is_acquiring(self) -> bool:
        """Check if system is currently acquiring data (with fresh status)"""
        status = self.refresh_status(timeout=1.5)
        return status.get("acquiring", False) if status else False

    def is_recording(self) -> bool:
        """Check if system is currently recording (with fresh status)"""
        status = self.refresh_status(timeout=1.5)
        return status.get("recording", False) if status else False

    def is_scheduler_enabled(self) -> bool:
        """Check if scheduler is enabled (with fresh status)"""
        status = self.refresh_status(timeout=1.5)
        return status.get("scheduler_enabled", False) if status else False

    def ensure_acquiring(self, timeout: float = 5.0) -> bool:
        """Ensure acquisition is running, start if not"""
        # Wait for initial status
        self.wait_for_status(timeout=2.0)

        if self.is_acquiring():
            return True

        # Start acquisition
        self.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")

        # Wait for acquisition to start
        start = time.time()
        while (time.time() - start) < timeout:
            time.sleep(0.2)
            if self.is_acquiring():
                return True

        return False

    def ensure_not_acquiring(self, timeout: float = 3.0) -> bool:
        """Ensure acquisition is stopped"""
        if not self.is_acquiring():
            return True

        self.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")

        start = time.time()
        while (time.time() - start) < timeout:
            time.sleep(0.2)
            if not self.is_acquiring():
                return True

        return False

    def ensure_not_recording(self, timeout: float = 3.0) -> bool:
        """Ensure recording is stopped"""
        if not self.is_recording():
            return True

        self.publish(f"{SYSTEM_PREFIX}/system/recording/stop", "{}")

        start = time.time()
        while (time.time() - start) < timeout:
            time.sleep(0.2)
            if not self.is_recording():
                return True

        return False


# Legacy alias for backwards compatibility
MQTTTestFixture = MQTTTestHarness


@pytest.fixture
def mqtt_client():
    """Provide a connected MQTT test client"""
    client = MQTTTestHarness(f"pytest-{time.time()}")
    assert client.connect(), "Failed to connect to MQTT broker"
    # Wait for initial status
    client.wait_for_status(timeout=2.0)
    yield client
    client.disconnect()


@pytest.fixture
def mqtt_client_acquiring(mqtt_client):
    """
    Provide MQTT client with acquisition guaranteed to be running.
    Cleans up by stopping acquisition after test.
    """
    assert mqtt_client.ensure_acquiring(), "Failed to start acquisition"
    # Give the system a moment to stabilize
    time.sleep(0.5)
    yield mqtt_client
    mqtt_client.ensure_not_acquiring()


@pytest.fixture
def mqtt_client_clean(mqtt_client):
    """
    Provide MQTT client with clean state (no acquisition, no recording).
    """
    mqtt_client.ensure_not_recording()
    mqtt_client.ensure_not_acquiring()
    time.sleep(0.3)
    yield mqtt_client


@pytest.fixture(scope="session")
def check_services():
    """Check that required services are running"""
    client = MQTTTestHarness("service-check")
    if not client.connect(timeout=3.0):
        pytest.skip("MQTT broker not available")

    # Check for DAQ service by waiting for status
    client.wait_for_status(timeout=3.0)
    status = client.get_system_status()
    if not status:
        client.disconnect()
        pytest.skip("DAQ service not responding")

    client.disconnect()
