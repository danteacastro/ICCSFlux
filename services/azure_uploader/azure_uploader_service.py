#!/usr/bin/env python3
"""
Azure IoT Hub Uploader Service

Command-driven service that streams channel data to Azure IoT Hub.
Runs in its own Python environment to avoid paho-mqtt version conflicts.

Design:
- Starts with ICCSFlux and sits idle, connected only to MQTT
- Listens for start/stop commands from DAQ service
- When recording starts, begins streaming to Azure IoT Hub
- When recording stops, stops streaming

Control Topics:
    nisystem/azure/command  - receives start/stop commands with config

Data Topics:
    nisystem/nodes/+/channels/values - channel data to forward
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import deque

# paho-mqtt 1.x API
import paho.mqtt.client as mqtt

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
    Command-driven Azure IoT Hub uploader service.

    Starts idle, waiting for commands via MQTT. When DAQ service starts
    recording with Azure enabled, it sends a 'start' command with config.
    """

    def __init__(self, mqtt_host: str = 'localhost', mqtt_port: int = 1883):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # MQTT topics
        self.command_topic = 'nisystem/azure/command'
        self.data_topic = 'nisystem/nodes/+/channels/values'
        self.status_topic = 'nisystem/azure/status'

        # MQTT client (always connected)
        self.mqtt_client: Optional[mqtt.Client] = None

        # Azure client (only connected when streaming)
        self.azure_client: Optional[IoTHubDeviceClient] = None

        # Current configuration (set by start command)
        self.connection_string: str = ''
        self.channels: List[str] = []
        self.batch_size: int = 10
        self.batch_interval_ms: int = 1000
        self.max_queue_size: int = 10000

        # State
        self._service_running = False  # Service process running
        self._streaming = False         # Actively streaming to Azure
        self._stop_event = threading.Event()

        # Data queue (only used when streaming)
        self._queue: deque = deque(maxlen=self.max_queue_size)
        self._queue_lock = threading.Lock()
        self._upload_thread: Optional[threading.Thread] = None

        # Stats
        self._stats = {
            'state': 'idle',
            'mqtt_connected': False,
            'azure_connected': False,
            'messages_received': 0,
            'messages_sent': 0,
            'messages_failed': 0,
            'samples_sent': 0,
            'last_error': None,
        }
        self._stats_lock = threading.Lock()

    def start_service(self) -> bool:
        """Start the service (connects to MQTT, waits for commands)."""
        if self._service_running:
            return True

        logger.info(f"Starting Azure Uploader Service...")
        logger.info(f"  MQTT broker: {self.mqtt_host}:{self.mqtt_port}")
        logger.info(f"  Command topic: {self.command_topic}")

        try:
            # Connect to MQTT broker
            self.mqtt_client = mqtt.Client(client_id=f"azure_uploader_{os.getpid()}")
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message

            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()

            self._service_running = True
            self._update_state('idle')

            logger.info("Azure Uploader Service started (waiting for commands)")
            return True

        except Exception as e:
            logger.error(f"Failed to start service: {e}")
            return False

    def stop_service(self) -> None:
        """Stop the service completely."""
        if not self._service_running:
            return

        logger.info("Stopping Azure Uploader Service...")

        # Stop streaming if active
        if self._streaming:
            self._stop_streaming()

        # Disconnect MQTT
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting MQTT: {e}")
            self.mqtt_client = None

        self._service_running = False
        self._update_state('stopped')
        logger.info("Azure Uploader Service stopped")

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback."""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            # Subscribe to command topic
            client.subscribe(self.command_topic)
            logger.info(f"Subscribed to {self.command_topic}")

            # Subscribe to data topic (will only process when streaming)
            client.subscribe(self.data_topic)

            with self._stats_lock:
                self._stats['mqtt_connected'] = True

            # Publish status
            self._publish_status()
        else:
            logger.error(f"MQTT connection failed with code {rc}")
            with self._stats_lock:
                self._stats['mqtt_connected'] = False

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback."""
        logger.warning(f"Disconnected from MQTT broker (rc={rc})")
        with self._stats_lock:
            self._stats['mqtt_connected'] = False

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            if msg.topic == self.command_topic:
                self._handle_command(msg.payload)
            elif self._streaming and '/channels/values' in msg.topic:
                self._handle_data(msg.payload)
        except Exception as e:
            logger.warning(f"Error processing message on {msg.topic}: {e}")

    def _handle_command(self, payload: bytes) -> None:
        """Handle control commands from DAQ service."""
        try:
            cmd = json.loads(payload.decode('utf-8'))
            action = cmd.get('action', '')

            if action == 'start':
                logger.info("Received START command")
                config = cmd.get('config', {})
                self._start_streaming(config)

            elif action == 'stop':
                logger.info("Received STOP command")
                self._stop_streaming()

            elif action == 'status':
                self._publish_status()

            else:
                logger.warning(f"Unknown command action: {action}")

        except json.JSONDecodeError:
            logger.warning("Invalid JSON in command")
        except Exception as e:
            logger.error(f"Error handling command: {e}")

    def _start_streaming(self, config: Dict[str, Any]) -> None:
        """Start streaming to Azure IoT Hub."""
        if self._streaming:
            logger.warning("Already streaming, ignoring start command")
            return

        # Extract config
        self.connection_string = config.get('connection_string', '')
        self.channels = config.get('channels', [])
        self.batch_size = config.get('batch_size', 10)
        self.batch_interval_ms = config.get('batch_interval_ms', 1000)

        if not self.connection_string:
            logger.error("No Azure connection string in config")
            self._update_state('error', 'No connection string')
            return

        if not self.connection_string.startswith('HostName='):
            logger.error("Invalid Azure connection string format")
            self._update_state('error', 'Invalid connection string')
            return

        try:
            # Connect to Azure IoT Hub
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

            logger.info(f"Connected to Azure IoT Hub (device: {self._get_device_id()})")
            if self.channels:
                logger.info(f"Streaming channels: {', '.join(self.channels)}")
            else:
                logger.info("Streaming all channels")

            # Clear queue and start upload thread
            with self._queue_lock:
                self._queue.clear()

            self._streaming = True
            self._stop_event.clear()

            self._upload_thread = threading.Thread(
                target=self._upload_loop,
                name="AzureUploadLoop",
                daemon=True
            )
            self._upload_thread.start()

            self._update_state('streaming')
            logger.info("Azure streaming started")

        except Exception as e:
            logger.error(f"Failed to connect to Azure: {e}")
            self._update_state('error', str(e))
            if self.azure_client:
                try:
                    self.azure_client.disconnect()
                except:
                    pass
                self.azure_client = None

    def _stop_streaming(self) -> None:
        """Stop streaming to Azure IoT Hub."""
        if not self._streaming:
            return

        logger.info("Stopping Azure streaming...")
        self._streaming = False
        self._stop_event.set()

        # Wait for upload thread
        if self._upload_thread and self._upload_thread.is_alive():
            self._upload_thread.join(timeout=5.0)

        # Disconnect Azure
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

    def _handle_data(self, payload: bytes) -> None:
        """Handle channel data message."""
        if not self._streaming:
            return

        try:
            data = json.loads(payload.decode('utf-8'))

            with self._stats_lock:
                self._stats['messages_received'] += 1

            # Extract values
            values = data.get('values', data)
            if not isinstance(values, dict):
                return

            # Filter channels if configured
            if self.channels:
                filtered = {k: v for k, v in values.items() if k in self.channels}
            else:
                filtered = values

            if not filtered:
                return

            # Filter to numeric values only
            numeric_values = {}
            for k, v in filtered.items():
                if isinstance(v, (int, float)) and not (isinstance(v, float) and v != v):
                    numeric_values[k] = v

            if not numeric_values:
                return

            # Queue data point
            data_point = {
                'timestamp': data.get('timestamp', datetime.now(timezone.utc).isoformat()),
                'node_id': data.get('node_id', 'unknown'),
                'values': numeric_values
            }

            with self._queue_lock:
                self._queue.append(data_point)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.debug(f"Error processing data: {e}")

    def _upload_loop(self) -> None:
        """Background thread that batches and sends data to Azure."""
        batch: List[Dict] = []
        last_send = time.time()

        while not self._stop_event.is_set():
            try:
                # Collect data from queue
                with self._queue_lock:
                    while self._queue and len(batch) < self.batch_size:
                        batch.append(self._queue.popleft())

                # Check if we should send
                elapsed_ms = (time.time() - last_send) * 1000
                should_send = (
                    len(batch) >= self.batch_size or
                    (batch and elapsed_ms >= self.batch_interval_ms)
                )

                if should_send and batch:
                    self._send_batch(batch)
                    batch = []
                    last_send = time.time()

                self._stop_event.wait(0.05)

            except Exception as e:
                logger.error(f"Error in upload loop: {e}")
                with self._stats_lock:
                    self._stats['last_error'] = str(e)
                time.sleep(1)

        # Send remaining on stop
        if batch:
            try:
                self._send_batch(batch)
            except:
                pass

    def _send_batch(self, batch: List[Dict]) -> bool:
        """Send a batch of data points to Azure IoT Hub."""
        if not self.azure_client or not batch:
            return False

        try:
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
            message.custom_properties['messageType'] = 'telemetry'
            message.custom_properties['batchSize'] = str(len(batch))

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
        except:
            return False

    def _get_device_id(self) -> str:
        """Extract device ID from connection string."""
        try:
            parts = dict(p.split('=', 1) for p in self.connection_string.split(';') if '=' in p)
            return parts.get('DeviceId', 'unknown')
        except:
            return 'unknown'

    def _update_state(self, state: str, error: str = None) -> None:
        """Update state and publish status."""
        with self._stats_lock:
            self._stats['state'] = state
            if error:
                self._stats['last_error'] = error
        self._publish_status()

    def _publish_status(self) -> None:
        """Publish current status to MQTT."""
        if not self.mqtt_client:
            return
        try:
            with self._stats_lock:
                status = dict(self._stats)
            status['timestamp'] = datetime.now(timezone.utc).isoformat()
            self.mqtt_client.publish(
                self.status_topic,
                json.dumps(status),
                retain=True
            )
        except Exception as e:
            logger.debug(f"Failed to publish status: {e}")

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

        # Main loop
        while self._service_running:
            time.sleep(30)
            # Periodic status update
            self._publish_status()

            if self._streaming:
                with self._stats_lock:
                    stats = dict(self._stats)
                logger.info(f"Streaming: sent={stats['messages_sent']}, samples={stats['samples_sent']}")


def main():
    parser = argparse.ArgumentParser(description='Azure IoT Hub Uploader Service')
    parser.add_argument('--host', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    service = AzureUploaderService(mqtt_host=args.host, mqtt_port=args.port)
    service.run_forever()


if __name__ == '__main__':
    main()
