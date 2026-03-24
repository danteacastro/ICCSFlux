#!/usr/bin/env python3
"""
Azure IoT Hub Uploader Service

Polls the historian SQLite database for channel data and safety events,
then forwards to Azure IoT Hub over HTTPS.

Runs in its own Python environment to avoid paho-mqtt version conflicts.

Design:
- Starts with ICCSFlux, reads config from historian.db azure_config table
- DAQ service writes config (connection string, channels, upload interval)
  to historian.db when the user changes settings in the DataTab
- Polls historian.db for new datapoints and safety events
- Sends batches to Azure IoT Hub over HTTPS
- No MQTT dependency — data flows through SQLite only

This architecture is Purdue-Model compliant: the uploader can run on a
DMZ host (Level 3.5) reading historian.db from a read-only network share,
keeping the Level 2 DAQ workstation air-gapped from the internet.
"""

import argparse
import json
import logging
import os
import signal
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import deque

# Azure IoT SDK
from azure.iot.device import IoTHubDeviceClient, Message
from azure.iot.device.exceptions import (
    ConnectionFailedError,
    ConnectionDroppedError,
    OperationTimeout,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('AzureUploader')

class AzureUploaderService:
    """
    SQLite-driven Azure IoT Hub uploader service.

    Reads config + data from historian.db, sends to Azure IoT Hub.
    All user configuration comes from the DataTab UI via the DAQ service.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

        # Azure client (connected when streaming)
        self.azure_client: Optional[IoTHubDeviceClient] = None

        # Config (read from historian.db azure_config table)
        self.connection_string: str = ''
        self._node_id: str = 'node-001'
        self.channels: List[str] = []
        self.batch_size: int = 10
        self.upload_interval_ms: int = 1000
        self.max_queue_size: int = 10000

        # State
        self._service_running = False
        self._streaming = False
        self._stop_event = threading.Event()
        self._force_flush = threading.Event()

        # SQLite cursors
        self._last_data_ts: int = 0
        self._last_event_id: int = 0
        self._last_config_hash: str = ''

        # Safety event cooldown
        self._safety_cooldowns: Dict[str, float] = {}
        self._safety_cooldown_s: float = 30.0

        # Data queue
        self._queue: deque = deque(maxlen=self.max_queue_size)
        self._queue_lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._upload_thread: Optional[threading.Thread] = None

        # Stats
        self._stats = {
            'state': 'idle',
            'azure_connected': False,
            'messages_received': 0,
            'messages_sent': 0,
            'messages_failed': 0,
            'samples_sent': 0,
            'last_error': None,
        }
        self._stats_lock = threading.Lock()

    def start_service(self) -> bool:
        """Start the service — reads config from historian.db, begins polling."""
        if self._service_running:
            return True

        if not os.path.exists(self._db_path):
            logger.error(f"Database not found: {self._db_path}")
            return False

        logger.info(f"Starting Azure Uploader Service")
        logger.info(f"  Database: {self._db_path}")

        # Read initial config from historian
        config = self._read_config()
        if not config:
            logger.info("No Azure config in historian yet — waiting for DataTab configuration")
        else:
            self._apply_config(config)

        # Seed data cursor to current position (don't replay old data)
        self._seed_cursors()

        self._service_running = True
        self._stop_event.clear()

        # Start the poll loop (handles config watching + data polling + upload)
        self._poll_thread = threading.Thread(
            target=self._main_poll_loop,
            name="AzurePollLoop",
            daemon=True
        )
        self._poll_thread.start()

        self._update_state('idle')
        logger.info("Azure Uploader Service started (polling historian.db)")
        return True

    def stop_service(self) -> None:
        """Stop the service completely."""
        if not self._service_running:
            return

        logger.info("Stopping Azure Uploader Service...")
        self._service_running = False
        self._streaming = False
        self._stop_event.set()

        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
        if self._upload_thread and self._upload_thread.is_alive():
            self._upload_thread.join(timeout=5.0)

        if self.azure_client:
            try:
                self.azure_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting Azure: {e}")
            self.azure_client = None

        with self._stats_lock:
            self._stats['azure_connected'] = False

        self._update_state('stopped')
        logger.info("Azure Uploader Service stopped")

    # ── Config management ────────────────────────────────────────────

    def _read_config(self) -> Optional[Dict[str, Any]]:
        """Read Azure config from historian.db azure_config table."""
        try:
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                cursor = conn.execute(
                    "SELECT value FROM azure_config WHERE key = 'config'")
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None
            finally:
                conn.close()
        except Exception as e:
            logger.debug(f"Could not read Azure config: {e}")
            return None

    def _apply_config(self, config: Dict[str, Any]) -> None:
        """Apply config from historian to local state."""
        self.connection_string = config.get('connection_string', '')
        self.channels = config.get('channels', [])
        self.batch_size = config.get('batch_size', 10)
        self.upload_interval_ms = config.get('upload_interval_ms', 1000)
        self._node_id = config.get('node_id', 'node-001')

        logger.info(f"  Upload interval: {self.upload_interval_ms} ms")
        if self.channels:
            logger.info(f"  Channels: {', '.join(self.channels)}")
        else:
            logger.info(f"  Channels: all")

    def _config_hash(self, config: Dict[str, Any]) -> str:
        """Quick hash to detect config changes."""
        return json.dumps(config, sort_keys=True)

    def _seed_cursors(self) -> None:
        """Seed data/event cursors to current DB position."""
        try:
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                cursor = conn.execute("SELECT MAX(ts) FROM datapoints")
                row = cursor.fetchone()
                self._last_data_ts = row[0] or 0

                cursor = conn.execute("SELECT MAX(id) FROM events")
                row = cursor.fetchone()
                self._last_event_id = row[0] or 0
            finally:
                conn.close()
            logger.info(f"  Data cursor: ts={self._last_data_ts}, event_id={self._last_event_id}")
        except Exception as e:
            logger.warning(f"Could not seed cursors: {e}")

    # ── Main poll loop ───────────────────────────────────────────────

    def _main_poll_loop(self) -> None:
        """
        Single loop that:
        1. Checks config for changes (start/stop streaming)
        2. Polls data + events when streaming
        3. Sends batches to Azure
        """
        config_check_interval = 2.0  # Check config every 2s
        last_config_check = 0.0

        while not self._stop_event.is_set():
            now = time.monotonic()

            # 1. Check config periodically
            if now - last_config_check >= config_check_interval:
                last_config_check = now
                self._check_config()

            # 2. Poll data + send when streaming
            if self._streaming:
                self._poll_and_send()

            # Sleep for poll interval (or config check interval if not streaming)
            sleep_s = (self.upload_interval_ms / 1000.0) if self._streaming else config_check_interval
            self._stop_event.wait(min(sleep_s, config_check_interval))

    def _check_config(self) -> None:
        """Check historian for config changes, start/stop streaming accordingly."""
        config = self._read_config()
        if not config:
            if self._streaming:
                logger.info("Azure config removed — stopping streaming")
                self._stop_streaming()
            return

        config_hash = self._config_hash(config)
        config_changed = config_hash != self._last_config_hash
        should_stream = config.get('streaming', False)
        has_connection = config.get('connection_string', '').startswith('HostName=')

        if config_changed:
            self._apply_config(config)
            self._last_config_hash = config_hash

        if should_stream and has_connection and not self._streaming:
            self._start_streaming()
        elif not should_stream and self._streaming:
            self._stop_streaming()

    def _start_streaming(self) -> None:
        """Connect to Azure and begin streaming."""
        if self._streaming:
            return

        if not self.connection_string or not self.connection_string.startswith('HostName='):
            logger.error("Cannot start streaming: no valid connection string")
            self._update_state('error', 'No connection string')
            return

        try:
            logger.info("Connecting to Azure IoT Hub...")
            self.azure_client = IoTHubDeviceClient.create_from_connection_string(
                self.connection_string,
                connection_retry=True,
                connection_retry_interval=10,
                keep_alive=60,
            )
            self.azure_client.connect()

            with self._stats_lock:
                self._stats['azure_connected'] = True

            logger.info(f"Connected to Azure IoT Hub (device: {self._get_device_id()}, "
                        f"identifier: {self._get_device_identifier()})")

            with self._queue_lock:
                self._queue.clear()

            self._streaming = True
            self._safety_cooldowns.clear()
            self._update_state('streaming')
            logger.info("Azure streaming started")

        except Exception as e:
            logger.error(f"Failed to connect to Azure: {e}")
            self._update_state('error', str(e))
            if self.azure_client:
                try:
                    self.azure_client.disconnect()
                except Exception:
                    pass
                self.azure_client = None

    def _stop_streaming(self) -> None:
        """Disconnect from Azure and stop streaming."""
        if not self._streaming:
            return

        logger.info("Stopping Azure streaming...")
        self._streaming = False

        # Send remaining queued data
        self._flush_queue()

        if self.azure_client:
            try:
                self.azure_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting Azure: {e}")
            self.azure_client = None

        with self._stats_lock:
            self._stats['azure_connected'] = False

        self._update_state('idle')
        logger.info("Azure streaming stopped")

    # ── Data polling + sending ───────────────────────────────────────

    def _poll_and_send(self) -> None:
        """Poll historian.db for new data and events, send to Azure."""
        try:
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")

            try:
                # Poll channel data
                if self.channels:
                    placeholders = ','.join('?' * len(self.channels))
                    cursor = conn.execute(
                        f"SELECT id, name FROM channels WHERE name IN ({placeholders})",
                        self.channels
                    )
                    ch_map = {row[0]: row[1] for row in cursor.fetchall()}
                    if ch_map:
                        ch_placeholders = ','.join('?' * len(ch_map))
                        cursor = conn.execute(
                            f"SELECT ts, ch, val FROM datapoints "
                            f"WHERE ts > ? AND ch IN ({ch_placeholders}) "
                            f"ORDER BY ts LIMIT 5000",
                            (self._last_data_ts, *ch_map.keys())
                        )
                    else:
                        cursor = conn.execute("SELECT 1 WHERE 0")
                else:
                    cursor = conn.execute("SELECT id, name FROM channels")
                    ch_map = {row[0]: row[1] for row in cursor.fetchall()}
                    cursor = conn.execute(
                        "SELECT ts, ch, val FROM datapoints "
                        "WHERE ts > ? ORDER BY ts LIMIT 5000",
                        (self._last_data_ts,)
                    )

                # Group rows by timestamp
                current_ts = None
                current_values: Dict[str, Any] = {}
                for ts, ch, val in cursor.fetchall():
                    if ts != current_ts:
                        if current_values:
                            self._queue_data_point(current_ts, current_values)
                        current_ts = ts
                        current_values = {}
                    name = ch_map.get(ch)
                    if name and val is not None:
                        current_values[name] = val
                if current_values:
                    self._queue_data_point(current_ts, current_values)
                if current_ts:
                    self._last_data_ts = current_ts

                # Poll safety events
                cursor = conn.execute(
                    "SELECT id, ts, event_type, topic, data FROM events "
                    "WHERE id > ? ORDER BY id LIMIT 500",
                    (self._last_event_id,)
                )
                for row_id, ts, event_type, topic, data_str in cursor.fetchall():
                    # Cooldown check
                    cooldown_key = topic
                    now_t = time.time()
                    if (now_t - self._safety_cooldowns.get(cooldown_key, 0.0)) < self._safety_cooldown_s:
                        self._last_event_id = row_id
                        continue
                    self._safety_cooldowns[cooldown_key] = now_t

                    try:
                        event_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        event_data = {'raw': data_str}

                    event_point = {
                        'timestamp': datetime.fromtimestamp(
                            ts / 1000, tz=timezone.utc).isoformat(),
                        'safety_event': True,
                        'event_topic': topic,
                        'event_data': event_data
                    }
                    with self._queue_lock:
                        self._queue.append(event_point)
                    self._force_flush.set()
                    self._last_event_id = row_id

                with self._stats_lock:
                    self._stats['messages_received'] += 1

            finally:
                conn.close()

        except Exception as e:
            logger.warning(f"SQLite poll error: {e}")
            with self._stats_lock:
                self._stats['last_error'] = str(e)

        # Send queued data
        self._flush_queue()

    def _queue_data_point(self, ts_ms: int, values: Dict[str, Any]) -> None:
        """Queue a single timestamp's data for Azure upload."""
        data_point = {
            'timestamp': datetime.fromtimestamp(
                ts_ms / 1000, tz=timezone.utc).isoformat(),
            'node_id': self._node_id,
            'values': values
        }
        with self._queue_lock:
            self._queue.append(data_point)

    def _flush_queue(self) -> None:
        """Send all queued data to Azure in batches."""
        while True:
            batch: List[Dict] = []
            with self._queue_lock:
                while self._queue and len(batch) < self.batch_size:
                    batch.append(self._queue.popleft())

            if not batch:
                break

            self._send_batch(batch)

    def _send_batch(self, batch: List[Dict]) -> bool:
        """Send a batch of data points to Azure IoT Hub."""
        if not self.azure_client or not batch:
            return False

        try:
            payload = {
                'batch_size': len(batch),
                'data': batch
            }

            message = Message(
                json.dumps(payload),
                content_encoding='utf-8',
                content_type='application/json'
            )
            has_safety = any(p.get('safety_event') for p in batch)
            message.custom_properties['messageType'] = 'safety_event' if has_safety else 'telemetry'
            message.custom_properties['batchSize'] = str(len(batch))
            message.custom_properties['deviceIdentifier'] = self._get_device_identifier()
            message.custom_properties['nodeId'] = self._node_id

            self.azure_client.send_message(message)

            with self._stats_lock:
                self._stats['messages_sent'] += 1
                self._stats['samples_sent'] += len(batch)

            logger.debug(f"Sent {len(batch)} samples to Azure")
            return True

        except (ConnectionFailedError, ConnectionDroppedError) as e:
            logger.warning(f"Azure connection lost: {e}")
            with self._stats_lock:
                self._stats['messages_failed'] += 1
                self._stats['azure_connected'] = False
                self._stats['last_error'] = str(e)
            self._try_reconnect()
            return False

        except Exception as e:
            logger.error(f"Azure send error: {e}")
            with self._stats_lock:
                self._stats['messages_failed'] += 1
                self._stats['last_error'] = str(e)
            return False

    def _try_reconnect(self) -> bool:
        """Attempt to reconnect to Azure IoT Hub."""
        if not self.azure_client:
            return False
        try:
            self.azure_client.connect()
            with self._stats_lock:
                self._stats['azure_connected'] = True
            logger.info("Reconnected to Azure IoT Hub")
            return True
        except Exception as e:
            logger.warning(f"Azure reconnection failed: {e}")
            with self._stats_lock:
                self._stats['last_error'] = f"Reconnect failed: {e}"
            return False

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_device_id(self) -> str:
        """Extract device ID from connection string."""
        try:
            parts = dict(p.split('=', 1) for p in self.connection_string.split(';') if '=' in p)
            return parts.get('DeviceId', 'unknown')
        except (ValueError, AttributeError):
            return 'unknown'

    def _get_device_identifier(self) -> str:
        """Build structured device identifier: {HOSTNAME}_ICCSFlux_{node_id}"""
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = 'unknown-host'
        return f"{hostname}_ICCSFlux_{self._node_id}"

    def _update_state(self, state: str, error: str = None) -> None:
        """Update internal state."""
        with self._stats_lock:
            self._stats['state'] = state
            if error:
                self._stats['last_error'] = error

    def run_forever(self) -> None:
        """Run the service until interrupted."""
        if not self.start_service():
            sys.exit(1)

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            self.stop_service()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("Azure Uploader running (Ctrl+C to stop)")

        while self._service_running:
            time.sleep(30)
            if self._streaming:
                with self._stats_lock:
                    stats = dict(self._stats)
                logger.info(f"Streaming: sent={stats['messages_sent']}, "
                            f"samples={stats['samples_sent']}")

def main():
    parser = argparse.ArgumentParser(description='Azure IoT Hub Uploader Service')
    parser.add_argument('--db-path', required=True,
                        help='Path to historian.db (local or network share)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    service = AzureUploaderService(db_path=args.db_path)
    service.run_forever()

if __name__ == '__main__':
    main()
