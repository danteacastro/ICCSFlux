#!/usr/bin/env python3
"""
Watchdog Process for NISystem DAQ Service

Monitors the DAQ service health and triggers fail-safe actions if the service
becomes unresponsive. This provides an external safety layer independent of
the main DAQ service.

Features:
- Monitors MQTT heartbeat from DAQ service
- Triggers fail-safe outputs if heartbeat is lost
- Publishes watchdog status for dashboard monitoring
- Can run as a systemd service

Usage:
    python watchdog.py [-c CONFIG] [--timeout SECONDS]
"""

import json
import time
import signal
import sys
import logging
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Watchdog')


@dataclass
class WatchdogConfig:
    """Watchdog configuration"""
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_base_topic: str = "nisystem"
    heartbeat_timeout_sec: float = 10.0  # Time before considering service dead
    check_interval_sec: float = 2.0      # How often to check
    failsafe_outputs: Dict[str, Any] = field(default_factory=dict)  # Outputs to set on failure
    restart_service: bool = False        # Whether to attempt service restart
    service_name: str = "daq_service"    # Systemd service name


class DAQWatchdog:
    """
    External watchdog that monitors DAQ service health.

    If the DAQ service stops publishing heartbeats, the watchdog will:
    1. Log a critical error
    2. Publish fail-safe commands to critical outputs
    3. Publish alarm to MQTT
    4. Optionally attempt to restart the service
    """

    def __init__(self, config: WatchdogConfig):
        self.config = config
        self.mqtt_client: Optional[mqtt.Client] = None
        self.running = False

        # Tracking state
        self.last_heartbeat: Optional[float] = None
        self.daq_online = False
        self.failsafe_triggered = False
        self.failsafe_trigger_time: Optional[datetime] = None

        # Fail-safe outputs should only come from config - no hardcoded defaults
        # If no failsafe outputs are configured, the watchdog will only log/alarm
        # but not attempt to set any outputs (since we don't know what outputs exist)
        if not self.config.failsafe_outputs:
            logger.info("No fail-safe outputs configured - watchdog will only log/alarm on failure")

    def start(self):
        """Start the watchdog"""
        logger.info("Starting DAQ Watchdog...")
        self.running = True
        self._setup_mqtt()
        self._run_loop()

    def stop(self):
        """Stop the watchdog"""
        logger.info("Stopping DAQ Watchdog...")
        self.running = False

        if self.mqtt_client:
            base = self.config.mqtt_base_topic
            self.mqtt_client.publish(
                f"{base}/watchdog/status",
                json.dumps({
                    "status": "offline",
                    "timestamp": datetime.now().isoformat()
                }),
                retain=True,
                qos=1
            )
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

    def _setup_mqtt(self):
        """Setup MQTT connection"""
        import uuid
        client_id = f"daq_watchdog_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

        # Set will message - if watchdog dies unexpectedly, broker publishes this
        base = self.config.mqtt_base_topic
        self.mqtt_client.will_set(
            f"{base}/watchdog/status",
            json.dumps({
                "status": "offline",
                "reason": "unexpected_disconnect",
                "timestamp": datetime.now().isoformat()
            }),
            retain=True,
            qos=1
        )

        try:
            self.mqtt_client.connect(
                self.config.mqtt_broker,
                self.config.mqtt_port,
                keepalive=30
            )
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        if reason_code == 0:
            logger.info("Watchdog connected to MQTT broker")

            base = self.config.mqtt_base_topic

            # Subscribe to heartbeat topic with wildcard to catch all nodes
            # DAQ service publishes to: {base}/nodes/{node_id}/heartbeat
            client.subscribe(f"{base}/nodes/+/heartbeat", qos=1)
            # Also subscribe to status for offline notifications
            client.subscribe(f"{base}/nodes/+/status/system", qos=1)

            # Publish watchdog online status
            client.publish(
                f"{base}/watchdog/status",
                json.dumps({
                    "status": "online",
                    "monitoring": True,
                    "timeout_sec": self.config.heartbeat_timeout_sec,
                    "timestamp": datetime.now().isoformat()
                }),
                retain=True,
                qos=1
            )
        else:
            logger.error(f"Watchdog MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """MQTT disconnection callback"""
        logger.warning(f"Watchdog disconnected from MQTT broker: {reason_code}")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            payload = json.loads(msg.payload.decode())

            # Topics are: {base}/nodes/{node_id}/heartbeat or {base}/nodes/{node_id}/status/system
            if msg.topic.endswith("/heartbeat"):
                # Direct heartbeat from DAQ service
                self._handle_heartbeat(payload)
            elif msg.topic.endswith("/status/system"):
                # Status updates (for offline detection)
                self._handle_status(payload)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _handle_heartbeat(self, payload: dict):
        """Handle heartbeat from DAQ service"""
        # Heartbeat payload contains: sequence, timestamp, acquiring, recording, thread_health, uptime_seconds, etc.
        # If we receive any heartbeat message, the service is alive
        sequence = payload.get("sequence", 0)

        self.last_heartbeat = time.time()

        if not self.daq_online:
            logger.info(f"DAQ service is online (heartbeat seq={sequence})")
            self.daq_online = True

        # If we previously triggered failsafe and service is back, log it
        if self.failsafe_triggered:
            logger.warning("DAQ service recovered after failsafe trigger")
            self._publish_watchdog_event("daq_recovered", "DAQ service is back online")

    def _handle_status(self, payload: dict):
        """Handle status updates from DAQ service"""
        status = payload.get("status", "unknown")

        if status == "offline":
            logger.warning("DAQ service reported offline")
            self.daq_online = False

    def _run_loop(self):
        """Main watchdog loop"""
        logger.info(f"Watchdog monitoring started (timeout: {self.config.heartbeat_timeout_sec}s)")

        while self.running:
            try:
                self._check_health()
                time.sleep(self.config.check_interval_sec)
            except Exception as e:
                logger.error(f"Error in watchdog loop: {e}")
                time.sleep(1)

    def _check_health(self):
        """Check DAQ service health"""
        now = time.time()

        # Publish periodic status
        self._publish_status()

        # If we've never received a heartbeat, wait a bit longer on startup
        if self.last_heartbeat is None:
            return

        time_since_heartbeat = now - self.last_heartbeat

        if time_since_heartbeat > self.config.heartbeat_timeout_sec:
            if not self.failsafe_triggered:
                self._trigger_failsafe(time_since_heartbeat)
        else:
            # Reset failsafe state if service is healthy
            if self.failsafe_triggered and self.daq_online:
                self.failsafe_triggered = False
                self.failsafe_trigger_time = None

    def _trigger_failsafe(self, time_since_heartbeat: float):
        """Trigger fail-safe actions"""
        self.failsafe_triggered = True
        self.failsafe_trigger_time = datetime.now()
        self.daq_online = False

        logger.critical(
            f"WATCHDOG FAILSAFE TRIGGERED! No heartbeat for {time_since_heartbeat:.1f}s "
            f"(timeout: {self.config.heartbeat_timeout_sec}s)"
        )

        # Publish alarm
        self._publish_alarm(
            "watchdog_failsafe",
            f"DAQ service unresponsive for {time_since_heartbeat:.1f}s - FAILSAFE ACTIVATED"
        )

        # Set fail-safe outputs
        self._set_failsafe_outputs()

        # Publish event
        self._publish_watchdog_event(
            "failsafe_triggered",
            f"No heartbeat for {time_since_heartbeat:.1f}s"
        )

        # Optionally restart service
        if self.config.restart_service:
            self._attempt_restart()

    def _set_failsafe_outputs(self):
        """Set fail-safe output values"""
        if not self.config.failsafe_outputs:
            logger.info("No fail-safe outputs configured - skipping output setting")
            return

        base = self.config.mqtt_base_topic

        logger.warning(f"Setting {len(self.config.failsafe_outputs)} fail-safe outputs")

        for channel_name, value in self.config.failsafe_outputs.items():
            try:
                self.mqtt_client.publish(
                    f"{base}/commands/{channel_name}",
                    json.dumps({
                        "value": value,
                        "source": "watchdog_failsafe"
                    }),
                    qos=1  # At least once delivery
                )
                logger.warning(f"FAILSAFE: Set {channel_name} = {value}")
            except Exception as e:
                logger.error(f"Failed to set failsafe output {channel_name}: {e}")

    def _attempt_restart(self):
        """Attempt to restart the DAQ service"""
        logger.warning(f"Attempting to restart service: {self.config.service_name}")

        try:
            result = subprocess.run(
                ["systemctl", "restart", self.config.service_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("Service restart command sent successfully")
                self._publish_watchdog_event("service_restart", "Restart command sent")
            else:
                logger.error(f"Service restart failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Failed to restart service: {e}")

    def _publish_alarm(self, source: str, message: str):
        """Publish an alarm"""
        base = self.config.mqtt_base_topic

        self.mqtt_client.publish(
            f"{base}/alarms/{source}",
            json.dumps({
                "source": source,
                "message": message,
                "severity": "critical",
                "timestamp": datetime.now().isoformat(),
                "acknowledged": False
            }),
            retain=True,
            qos=1
        )

    def _publish_watchdog_event(self, event: str, message: str):
        """Publish a watchdog event"""
        base = self.config.mqtt_base_topic

        self.mqtt_client.publish(
            f"{base}/watchdog/event",
            json.dumps({
                "event": event,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }),
            qos=1
        )

    def _publish_status(self):
        """Publish watchdog status"""
        base = self.config.mqtt_base_topic

        status = {
            "status": "online",
            "monitoring": True,
            "daq_online": self.daq_online,
            "failsafe_triggered": self.failsafe_triggered,
            "failsafe_trigger_time": self.failsafe_trigger_time.isoformat() if self.failsafe_trigger_time else None,
            "last_heartbeat": datetime.fromtimestamp(self.last_heartbeat).isoformat() if self.last_heartbeat else None,
            "timeout_sec": self.config.heartbeat_timeout_sec,
            "timestamp": datetime.now().isoformat()
        }

        self.mqtt_client.publish(
            f"{base}/watchdog/status",
            json.dumps(status),
            retain=True,
            qos=1
        )


def load_config_from_ini(config_path: str) -> WatchdogConfig:
    """Load watchdog config from the main system.ini"""
    import configparser

    config = WatchdogConfig()

    if Path(config_path).exists():
        parser = configparser.ConfigParser()
        parser.read(config_path)

        if 'system' in parser:
            sys_sec = parser['system']
            config.mqtt_broker = sys_sec.get('mqtt_broker', config.mqtt_broker)
            config.mqtt_port = int(sys_sec.get('mqtt_port', config.mqtt_port))
            config.mqtt_base_topic = sys_sec.get('mqtt_base_topic', config.mqtt_base_topic)

        # Look for watchdog-specific section
        if 'watchdog' in parser:
            wd_sec = parser['watchdog']
            config.heartbeat_timeout_sec = float(wd_sec.get('heartbeat_timeout_sec', config.heartbeat_timeout_sec))
            config.check_interval_sec = float(wd_sec.get('check_interval_sec', config.check_interval_sec))
            config.restart_service = wd_sec.get('restart_service', 'false').lower() in ('true', 'yes', '1')
            config.service_name = wd_sec.get('service_name', config.service_name)

        # Parse fail-safe outputs from safety actions
        failsafe_outputs = {}
        for section in parser.sections():
            if section.startswith('safety_action:') and 'emergency' in section.lower():
                actions_str = parser[section].get('actions', '')
                for action in actions_str.split(','):
                    action = action.strip()
                    if ':' in action:
                        channel, value = action.split(':', 1)
                        channel = channel.strip()
                        value = value.strip().lower()
                        if value in ('true', 'false'):
                            failsafe_outputs[channel] = value == 'true'
                        else:
                            try:
                                failsafe_outputs[channel] = float(value)
                            except ValueError:
                                failsafe_outputs[channel] = value

        if failsafe_outputs:
            config.failsafe_outputs = failsafe_outputs

    return config


def main():
    parser = argparse.ArgumentParser(description='NISystem DAQ Watchdog')
    parser.add_argument(
        '-c', '--config',
        default=str(Path(__file__).parent.parent.parent / "config" / "system.ini"),
        help='Path to configuration file'
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=None,
        help='Heartbeat timeout in seconds (overrides config)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config
    config = load_config_from_ini(args.config)

    if args.timeout:
        config.heartbeat_timeout_sec = args.timeout

    # Create and run watchdog
    watchdog = DAQWatchdog(config)

    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        watchdog.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    watchdog.start()


if __name__ == "__main__":
    main()
