"""
Shared test utilities for NISystem tests.

This module contains the MQTT test harness and configuration constants
that can be imported by test files.
"""

import time
import json
import threading
from typing import Callable, Dict, List, Any, Optional
import configparser
from pathlib import Path
import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# General-purpose polling helpers
# ---------------------------------------------------------------------------

def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 3.0,
    interval: float = 0.05,
    description: str = "",
) -> bool:
    """Poll *predicate* until it returns True or *timeout* expires.

    Returns True if the predicate was satisfied, False on timeout.
    Typical usage::

        assert wait_until(lambda: mgr.active_alarms.get('a1'),
                          timeout=3.0), "Alarm did not activate"

    Parameters
    ----------
    predicate : callable
        A zero-argument callable that returns a truthy value on success.
    timeout : float
        Maximum seconds to wait (default 3).
    interval : float
        Seconds between polls (default 0.05 — 50 ms).
    description : str
        Optional label for debugging; included in repr but not raised.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass  # predicate may raise while state is in flux
        time.sleep(interval)
    # One final attempt (avoids off-by-one on tight timeouts)
    try:
        return bool(predicate())
    except Exception:
        return False

def wait_until_value(
    getter: Callable[[], Any],
    expected: Any,
    timeout: float = 3.0,
    interval: float = 0.05,
) -> bool:
    """Poll *getter* until its return value equals *expected*.

    Convenience wrapper around :func:`wait_until` for equality checks.
    """
    return wait_until(lambda: getter() == expected, timeout=timeout, interval=interval)

def _load_system_settings() -> dict:
    """Load MQTT settings from config/system.ini"""
    config_path = Path(__file__).parent.parent / "config" / "system.ini"
    settings = {
        "mqtt_host": "localhost",
        "mqtt_port": 1883,
        "mqtt_base_topic": "nisystem"
    }
    if config_path.exists():
        parser = configparser.RawConfigParser()
        parser.read(config_path)
        if 'system' in parser:
            settings["mqtt_host"] = parser['system'].get('mqtt_broker', settings["mqtt_host"])
            settings["mqtt_port"] = int(parser['system'].get('mqtt_port', settings["mqtt_port"]))
            settings["mqtt_base_topic"] = parser['system'].get('mqtt_base_topic', settings["mqtt_base_topic"])
    return settings

# Load test configuration from system.ini
_system_settings = _load_system_settings()
MQTT_HOST = _system_settings["mqtt_host"]
MQTT_PORT = _system_settings["mqtt_port"]
SYSTEM_PREFIX = _system_settings["mqtt_base_topic"]

class MQTTTestHarness:
    """
    Robust MQTT test client with proper timing and state management.

    Features:
    - Waits for subscription to be active before proceeding
    - Tracks system state (acquiring, recording, etc.)
    - Provides reliable message waiting
    - Handles race conditions properly
    """

    def __init__(self, client_id: str, username: str = None, password: str = None):
        self.client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        if username and password:
            self.client.username_pw_set(username, password)
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
