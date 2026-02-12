"""
Azure IoT Hub Uploader Module

Streams live channel data to Azure IoT Hub for real-time telemetry.
Designed to feed into PostgreSQL TimescaleDB or other downstream systems.

Features:
- Configurable channel selection
- Batching for efficiency
- Automatic reconnection
- Rate limiting to avoid throttling
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

# Try to import Azure IoT SDK
try:
    from azure.iot.device import IoTHubDeviceClient, Message
    from azure.iot.device.exceptions import (
        ConnectionFailedError,
        ConnectionDroppedError,
        OperationTimeout,
    )
    AZURE_IOT_AVAILABLE = True
except ImportError:
    AZURE_IOT_AVAILABLE = False
    logger.warning("azure-iot-device not installed. Azure IoT Hub upload disabled.")


class AzureIoTUploader:
    """
    Uploads channel data to Azure IoT Hub.

    Usage:
        uploader = AzureIoTUploader(connection_string)
        uploader.set_channels(['TC_01', 'TC_02', 'Pressure_01'])
        uploader.start()

        # In scan loop:
        uploader.push_data(channel_values)

        # Cleanup:
        uploader.stop()
    """

    def __init__(
        self,
        connection_string: str,
        batch_size: int = 10,
        batch_interval_ms: int = 1000,
        max_queue_size: int = 10000,
        upload_interval_s: float = 1.0,
    ):
        """
        Initialize Azure IoT Hub uploader.

        Args:
            connection_string: Azure IoT Hub device connection string
            batch_size: Number of samples to batch before sending
            batch_interval_ms: Max time between sends (even if batch not full)
            max_queue_size: Max queued samples before dropping oldest
            upload_interval_s: Minimum seconds between queued samples (decimation).
                               0 = no decimation (queue every scan).
                               1.0 = ~1 Hz upload rate (default).
        """
        if not AZURE_IOT_AVAILABLE:
            raise RuntimeError(
                "azure-iot-device package not installed. "
                "Install with: pip install azure-iot-device"
            )

        self._connection_string = connection_string
        self._batch_size = batch_size
        self._batch_interval_ms = batch_interval_ms
        self._max_queue_size = max_queue_size
        self._upload_interval_s = max(0.0, upload_interval_s)

        self._client: Optional[IoTHubDeviceClient] = None
        self._channels: List[str] = []
        self._enabled = False
        self._running = False

        # Thread-safe queue for data
        self._queue: deque = deque(maxlen=max_queue_size)
        self._queue_lock = threading.Lock()

        # Decimation tracking
        self._last_push_time: float = 0.0
        # Safety event cooldown: prevents alarm chatter from flooding Azure
        self._last_force_time: float = 0.0
        self._force_cooldown_s: float = 30.0  # Min seconds between forced pushes

        # Upload thread
        self._upload_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Statistics
        self._stats = {
            'messages_sent': 0,
            'messages_failed': 0,
            'samples_sent': 0,
            'samples_dropped': 0,
            'samples_decimated': 0,
            'last_send_time': None,
            'last_error': None,
            'connected': False,
        }
        self._stats_lock = threading.Lock()

        # Callbacks
        self._on_status_change: Optional[Callable[[Dict], None]] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def connected(self) -> bool:
        with self._stats_lock:
            return self._stats['connected']

    @property
    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return dict(self._stats)

    def set_channels(self, channels: List[str]) -> None:
        """Set which channels to upload."""
        self._channels = list(channels)
        logger.info(f"Azure IoT uploader channels: {self._channels}")

    def set_status_callback(self, callback: Callable[[Dict], None]) -> None:
        """Set callback for status changes."""
        self._on_status_change = callback

    def start(self) -> bool:
        """Start the uploader. Returns True if successful."""
        if self._running:
            logger.warning("Azure IoT uploader already running")
            return True

        if not self._connection_string:
            logger.error("No Azure IoT Hub connection string configured")
            return False

        try:
            # Create client
            self._client = IoTHubDeviceClient.create_from_connection_string(
                self._connection_string,
                connection_retry=True,
                connection_retry_interval=10,
                keep_alive=60,
            )

            # Connect
            self._client.connect()

            with self._stats_lock:
                self._stats['connected'] = True
                self._stats['last_error'] = None

            self._enabled = True
            self._running = True
            self._stop_event.clear()

            # Start upload thread
            self._upload_thread = threading.Thread(
                target=self._upload_loop,
                name="AzureIoTUploader",
                daemon=True
            )
            self._upload_thread.start()

            logger.info("Azure IoT Hub uploader started")
            self._notify_status()
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Azure IoT Hub: {e}")
            with self._stats_lock:
                self._stats['connected'] = False
                self._stats['last_error'] = str(e)
            self._notify_status()
            return False

    def stop(self) -> None:
        """Stop the uploader."""
        if not self._running:
            return

        logger.info("Stopping Azure IoT Hub uploader...")
        self._running = False
        self._stop_event.set()

        # Wait for upload thread
        if self._upload_thread and self._upload_thread.is_alive():
            self._upload_thread.join(timeout=5.0)

        # Disconnect client
        if self._client:
            try:
                self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting Azure IoT client: {e}")
            self._client = None

        with self._stats_lock:
            self._stats['connected'] = False

        self._enabled = False
        logger.info("Azure IoT Hub uploader stopped")
        self._notify_status()

    def push_data(self, channel_values: Dict[str, float], timestamp: Optional[datetime] = None,
                  force: bool = False) -> None:
        """
        Push channel data to the upload queue.

        Called from scan loop - must be fast and non-blocking.

        Args:
            channel_values: Dict of channel_name -> value
            timestamp: Optional timestamp (defaults to now)
            force: Bypass decimation (use for alarm/interlock events)
        """
        if not self._enabled or not self._channels:
            return

        # Cooldown on forced pushes to prevent alarm chatter flooding Azure
        if force:
            now_f = time.time()
            if (now_f - self._last_force_time) < self._force_cooldown_s:
                force = False  # Downgrade to normal decimation path
            else:
                self._last_force_time = now_f

        # Decimation: skip samples that arrive faster than upload_interval_s
        # Bypassed when force=True (safety-critical events)
        if not force and self._upload_interval_s > 0:
            now = time.time()
            if (now - self._last_push_time) < self._upload_interval_s:
                with self._stats_lock:
                    self._stats['samples_decimated'] += 1
                return
            self._last_push_time = now

        # Filter to selected channels only
        filtered = {}
        for ch in self._channels:
            if ch in channel_values:
                value = channel_values[ch]
                # Only include numeric values
                if isinstance(value, (int, float)) and not (isinstance(value, float) and (value != value)):  # NaN check
                    filtered[ch] = value

        if not filtered:
            return

        # Create data point
        ts = timestamp or datetime.now(timezone.utc)
        data_point = {
            'timestamp': ts.isoformat(),
            'values': filtered,
        }
        if force:
            data_point['safety_event'] = True

        # Add to queue (thread-safe via deque maxlen)
        with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:
                # Queue full - oldest will be dropped automatically
                with self._stats_lock:
                    self._stats['samples_dropped'] += 1
            self._queue.append(data_point)

    def _upload_loop(self) -> None:
        """Background thread that batches and sends data."""
        batch: List[Dict] = []
        last_send = time.time()

        while not self._stop_event.is_set():
            try:
                # Collect data from queue
                with self._queue_lock:
                    while self._queue and len(batch) < self._batch_size:
                        batch.append(self._queue.popleft())

                # Check if we should send
                elapsed_ms = (time.time() - last_send) * 1000
                should_send = (
                    len(batch) >= self._batch_size or
                    (batch and elapsed_ms >= self._batch_interval_ms)
                )

                if should_send and batch:
                    self._send_batch(batch)
                    batch = []
                    last_send = time.time()

                # Small sleep to prevent busy-waiting
                self._stop_event.wait(0.05)  # 50ms

            except Exception as e:
                logger.error(f"Error in Azure upload loop: {e}")
                with self._stats_lock:
                    self._stats['last_error'] = str(e)
                time.sleep(1)  # Back off on error

        # Send remaining data on shutdown
        if batch:
            try:
                self._send_batch(batch)
            except Exception as e:
                logger.warning(f"Failed to send final batch: {e}")

    def _send_batch(self, batch: List[Dict]) -> bool:
        """Send a batch of data points to IoT Hub."""
        if not self._client or not batch:
            return False

        try:
            # Create message payload
            payload = {
                'device_id': self._get_device_id(),
                'batch_size': len(batch),
                'data': batch
            }

            message = Message(
                json.dumps(payload),
                content_encoding='utf-8',
                content_type='application/json'
            )

            # Add message properties for routing
            has_safety = any(p.get('safety_event') for p in batch)
            message.custom_properties['messageType'] = 'safety_event' if has_safety else 'telemetry'
            message.custom_properties['batchSize'] = str(len(batch))

            # Send (blocking, but with timeout)
            self._client.send_message(message)

            # Update stats
            with self._stats_lock:
                self._stats['messages_sent'] += 1
                self._stats['samples_sent'] += len(batch)
                self._stats['last_send_time'] = datetime.now(timezone.utc).isoformat()
                self._stats['connected'] = True

            logger.debug(f"Sent {len(batch)} samples to Azure IoT Hub")
            return True

        except (ConnectionFailedError, ConnectionDroppedError) as e:
            logger.warning(f"Azure IoT Hub connection lost: {e}")
            with self._stats_lock:
                self._stats['messages_failed'] += 1
                self._stats['connected'] = False
                self._stats['last_error'] = str(e)
            self._notify_status()

            # Try to reconnect
            self._try_reconnect()
            return False

        except OperationTimeout as e:
            logger.warning(f"Azure IoT Hub send timeout: {e}")
            with self._stats_lock:
                self._stats['messages_failed'] += 1
                self._stats['last_error'] = str(e)
            return False

        except Exception as e:
            logger.error(f"Azure IoT Hub send error: {e}")
            with self._stats_lock:
                self._stats['messages_failed'] += 1
                self._stats['last_error'] = str(e)
            return False

    def _try_reconnect(self) -> bool:
        """Attempt to reconnect to IoT Hub."""
        if not self._client:
            return False

        try:
            logger.info("Attempting to reconnect to Azure IoT Hub...")
            self._client.connect()

            with self._stats_lock:
                self._stats['connected'] = True
                self._stats['last_error'] = None

            logger.info("Reconnected to Azure IoT Hub")
            self._notify_status()
            return True

        except Exception as e:
            logger.warning(f"Reconnection failed: {e}")
            return False

    def _get_device_id(self) -> str:
        """Extract device ID from connection string."""
        try:
            parts = dict(p.split('=', 1) for p in self._connection_string.split(';') if '=' in p)
            return parts.get('DeviceId', 'unknown')
        except Exception:
            return 'unknown'

    def _notify_status(self) -> None:
        """Notify status callback if set."""
        if self._on_status_change:
            try:
                self._on_status_change(self.stats)
            except Exception as e:
                logger.warning(f"Status callback error: {e}")

    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return {
            'enabled': self._enabled,
            'channels': self._channels,
            'batch_size': self._batch_size,
            'batch_interval_ms': self._batch_interval_ms,
            'max_queue_size': self._max_queue_size,
            'upload_interval_s': self._upload_interval_s,
            # Don't include connection string for security
            'has_connection_string': bool(self._connection_string),
        }

    def update_config(
        self,
        channels: Optional[List[str]] = None,
        batch_size: Optional[int] = None,
        batch_interval_ms: Optional[int] = None,
        upload_interval_s: Optional[float] = None,
    ) -> None:
        """Update configuration (doesn't require restart)."""
        if channels is not None:
            self._channels = list(channels)
        if batch_size is not None:
            self._batch_size = max(1, batch_size)
        if batch_interval_ms is not None:
            self._batch_interval_ms = max(100, batch_interval_ms)
        if upload_interval_s is not None:
            self._upload_interval_s = max(0.0, upload_interval_s)

        rate = f"{1/self._upload_interval_s:.1f}Hz" if self._upload_interval_s > 0 else "unlimited"
        logger.info(f"Azure IoT config updated: channels={len(self._channels)}, "
                   f"batch_size={self._batch_size}, interval={self._batch_interval_ms}ms, "
                   f"upload_rate={rate}")


def is_available() -> bool:
    """Check if Azure IoT SDK is available."""
    return AZURE_IOT_AVAILABLE
