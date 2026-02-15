#!/usr/bin/env python3
"""
Opto22 Node Service for NISystem — Hybrid Architecture

Runs on groov EPIC/RIO hardware with dual MQTT connections:
1. groov Manage MQTT: receives native I/O data at full speed (zero Python scanning)
2. NISystem MQTT: publishes data, receives commands, integrates with dashboard

Modular architecture matching cRIO Node v2 pattern:
- state_machine.py   — Formal state machine with CONNECTING_MQTT state
- mqtt_interface.py   — Dual MQTT connections (System + groov Manage)
- hardware.py         — groov Manage MQTT subscriber + REST API fallback
- script_engine.py    — Sandboxed user scripts with rate limiting
- safety.py           — ISA-18.2 alarms with shelving, off-delay, ROC
- config.py           — Project config loading
- channel_types.py    — Channel type definitions and Opto22 module database
- audit_trail.py      — SHA-256 hash chain audit trail
- pid_engine.py       — PID control loops
- sequence_manager.py — Server-side sequences
- trigger_engine.py   — Condition-based automation triggers
- watchdog_engine.py  — Stale data / out-of-range watchdogs
"""

__version__ = '2.0.0'

import argparse
import hashlib
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger('Opto22Node')

# Module imports
from .state_machine import Opto22StateMachine, Opto22State
from .mqtt_interface import SystemMQTT, GroovMQTT, MQTTConfig, GroovMQTTConfig
from .hardware import HardwareInterface
from .config import NodeConfig, ChannelConfig, load_config, save_config
from .channel_types import ChannelType
from .safety import SafetyManager, AlarmState, AlarmConfig
from .audit_trail import AuditTrail
from .pid_engine import PIDEngine, PIDLoop
from .sequence_manager import SequenceManager, Sequence
from .trigger_engine import TriggerEngine
from .watchdog_engine import WatchdogEngine

# Optional: script engine (large dependency)
try:
    from .script_engine import ScriptEngine
    SCRIPT_ENGINE_AVAILABLE = True
except ImportError:
    SCRIPT_ENGINE_AVAILABLE = False
    logger.warning("Script engine not available")

# Constants
DEFAULT_CONFIG_DIR = Path('/home/dev/nisystem')
DEFAULT_CONFIG_FILE = 'opto22_config.json'
HEARTBEAT_INTERVAL = 2.0
STATUS_PUBLISH_INTERVAL = 30.0

# OPC UA style quality codes
OPEN_THERMOCOUPLE_THRESHOLD = 1e300
MAX_REASONABLE_VALUE = 1e15


def get_value_quality(value: Any) -> str:
    """Get OPC UA style quality status for a value."""
    if value is None:
        return 'bad'
    if not isinstance(value, (int, float)):
        return 'bad'
    if math.isnan(value) or math.isinf(value):
        return 'bad'
    if abs(value) > OPEN_THERMOCOUPLE_THRESHOLD:
        return 'bad'
    if abs(value) > MAX_REASONABLE_VALUE:
        return 'uncertain'
    return 'good'


class ScanTimingStats:
    """Track scan loop timing for observability."""

    def __init__(self, target_ms: float = 250.0, window_size: int = 100):
        self.target_ms = target_ms
        self._window_size = window_size
        self.reset()

    def reset(self):
        self._samples: list = []
        self.overruns = 0
        self.total_scans = 0

    def record(self, dt_ms: float):
        self.total_scans += 1
        self._samples.append(dt_ms)
        if len(self._samples) > self._window_size:
            self._samples.pop(0)
        if dt_ms > self.target_ms * 1.5:
            self.overruns += 1

    @property
    def mean_ms(self) -> float:
        return sum(self._samples) / len(self._samples) if self._samples else 0.0

    @property
    def actual_rate_hz(self) -> float:
        mean = self.mean_ms
        return 1000.0 / mean if mean > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            'target_ms': round(self.target_ms, 2),
            'actual_ms': round(self.mean_ms, 2),
            'min_ms': round(min(self._samples), 2) if self._samples else 0.0,
            'max_ms': round(max(self._samples), 2) if self._samples else 0.0,
            'actual_rate_hz': round(self.actual_rate_hz, 2),
            'overruns': self.overruns,
            'total_scans': self.total_scans,
        }


class Opto22NodeService:
    """
    Opto22 Node Service — hybrid architecture with groov Manage MQTT + Python intelligence.

    Reduced from 4,671-line monolith to modular service importing:
    state machine, dual MQTT, hardware I/O, script engine, safety/alarms,
    PID, sequences, triggers, watchdogs, audit trail.
    """

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / DEFAULT_CONFIG_FILE
        self.config: Optional[NodeConfig] = None
        self._start_time = time.time()

        # State machine
        self.state_machine = Opto22StateMachine()

        # MQTT connections (initialized in run())
        self.system_mqtt: Optional[SystemMQTT] = None
        self.groov_mqtt: Optional[GroovMQTT] = None

        # Hardware interface (groov MQTT subscriber + REST fallback)
        self.hardware: Optional[HardwareInterface] = None

        # Thread control
        self._running = threading.Event()
        self._acquiring = threading.Event()

        # Channel values (unified: hardware + output + script-published)
        self.channel_values: Dict[str, float] = {}
        self.channel_timestamps: Dict[str, float] = {}
        self.values_lock = threading.Lock()

        # Output state
        self.output_values: Dict[str, float] = {}

        # Watchdog
        self._watchdog_last_pet: float = 0.0
        self._watchdog_triggered: bool = False

        # Threads
        self.scan_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.watchdog_monitor_thread: Optional[threading.Thread] = None
        self._heartbeat_sequence = 0

        # Session state
        self._session_active = False
        self._session_name = ''
        self._session_operator = ''
        self._session_start_time: Optional[float] = None
        self._session_locked_outputs: List[str] = []
        self._session_timeout_minutes = 0

        # Audit trail
        self.audit = AuditTrail(
            audit_dir=str(config_dir / 'audit'),
            node_id='opto22'
        )

        # Safety manager (ISA-18.2 with shelving, off-delay, ROC, interlocks)
        safety_dir = str(config_dir / 'safety')
        self.safety = SafetyManager(data_dir=safety_dir)
        self.safety.on_alarm = self._on_alarm_event
        self.safety.on_action = self._on_safety_action
        self.safety.on_stop_session = lambda: self._stop_session('safety_action')
        self.safety.on_interlock_action = self._on_safety_action
        self.safety.on_publish = self._on_safety_publish

        # PID engine
        self.pid_engine = PIDEngine(on_set_output=self._set_output_internal)
        self.pid_engine.set_status_callback(self._publish_pid_status)

        # Sequence manager
        self.sequence_manager = SequenceManager()
        self.sequence_manager.on_set_output = self._set_output_internal
        self.sequence_manager.on_get_channel_value = self._get_channel_value
        self.sequence_manager.on_sequence_event = self._on_sequence_event

        # Trigger engine
        self.trigger_engine = TriggerEngine()
        self.trigger_engine.set_output = self._set_output_internal
        self.trigger_engine.run_sequence = lambda sid: self.sequence_manager.start_sequence(sid)

        # Watchdog engine
        self.channel_watchdog = WatchdogEngine()
        self.channel_watchdog.publish_notification = self._publish_notification

        # Script engine
        self.script_engine: Optional[ScriptEngine] = None

        # Interactive console namespace
        self._console_namespace: Optional[Dict[str, Any]] = None

        # Scan timing stats
        scan_rate = self.config.scan_rate_hz if self.config else 4.0
        self._scan_timing = ScanTimingStats(target_ms=1000.0 / scan_rate)

        # Status tracking
        self.last_pc_contact = time.time()
        self.pc_connected = False
        self._last_status_time = 0.0
        self._last_publish_time = 0.0
        self.config_version = ''
        self.config_timestamp = ''
        self._hardware_info: Optional[Dict[str, Any]] = None

        # Load config
        self._load_local_config()

    # =========================================================================
    # ENGINE CALLBACKS
    # =========================================================================

    def _set_output_internal(self, channel_name: str, value: float) -> bool:
        """Internal callback for engines to set output values."""
        if not self.config or not self.hardware:
            return False
        ch = self.config.channels.get(channel_name)
        if not ch:
            return False
        if ch.channel_type not in ('analog_output', 'digital_output',
                                   'voltage_output', 'current_output'):
            return False
        success = self.hardware.write_output(channel_name, value)
        if success:
            self.output_values[channel_name] = value
        return success

    def _get_channel_value(self, channel_name: str) -> Optional[float]:
        """Internal callback for engines to read channel values."""
        with self.values_lock:
            return self.channel_values.get(channel_name)

    def _on_alarm_event(self, channel: str, event_type: str, details: Dict):
        """Callback from safety manager when alarm state changes."""
        self.audit.log_event(event_type, channel, details)
        self._publish(self._topic('alarms/event'), {
            'channel': channel,
            'event': event_type,
            'node_id': self.config.node_id if self.config else 'opto22',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **details
        })

    def _on_safety_action(self, action_name: str, channel: str, details: Dict):
        """Callback from safety manager when safety action executes."""
        self.audit.log_event('safety_action', channel, {
            'action': action_name, **details
        })
        self._publish(self._topic('safety/triggered'), {
            'action': action_name,
            'channel': channel,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **details
        })

    def _on_safety_publish(self, topic: str, payload: Dict):
        """Callback for safety manager to publish MQTT messages (interlock events, flood alerts)."""
        self._publish(self._topic(topic), payload)

    def _publish_pid_status(self, loop_id: str, status: Dict):
        """Callback to publish PID loop status."""
        self._publish(self._topic(f'pid/{loop_id}/status'), status)

    def _on_sequence_event(self, event_type: str, sequence):
        """Callback for sequence manager events."""
        self._publish(self._topic(f'sequence/{sequence.id}/{event_type}'), {
            'sequence_id': sequence.id,
            'event': event_type,
            'state': sequence.state.value if sequence.state else 'unknown',
            'current_step': sequence.current_step_index,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, qos=1)

    def _publish_notification(self, notification_type: str, source: str, message: str):
        """Publish a notification via MQTT."""
        self._publish(self._topic('notifications'), {
            'type': notification_type,
            'message': message,
            'source': source,
            'severity': 'info',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # =========================================================================
    # MQTT TOPICS
    # =========================================================================

    def _topic_base(self) -> str:
        """Get node-prefixed topic base."""
        base = self.config.mqtt_base_topic if self.config else 'nisystem'
        node_id = self.config.node_id if self.config else 'opto22-001'
        return f"{base}/nodes/{node_id}"

    def _topic(self, suffix: str) -> str:
        """Build full MQTT topic."""
        return f"{self._topic_base()}/{suffix}"

    # =========================================================================
    # MQTT SETUP
    # =========================================================================

    def _setup_mqtt(self):
        """Setup dual MQTT connections."""
        if not self.config:
            return

        # System MQTT (NISystem Mosquitto broker)
        sys_config = MQTTConfig(
            broker_host=self.config.mqtt_broker,
            broker_port=self.config.mqtt_port,
            username=self.config.mqtt_username,
            password=self.config.mqtt_password,
            client_id=f"opto22-{self.config.node_id}",
            base_topic=self.config.mqtt_base_topic or 'nisystem',
            node_id=self.config.node_id,
        )
        self.system_mqtt = SystemMQTT(sys_config)
        self.system_mqtt.on_connect = self._on_system_mqtt_connect
        self.system_mqtt.on_message = self._on_mqtt_message
        # Will message is set automatically inside SystemMQTT.connect()
        self.system_mqtt.connect()

        # groov Manage MQTT (for I/O data) — only if configured
        if self.config.groov_mqtt_host:
            groov_config = GroovMQTTConfig(
                broker_host=self.config.groov_mqtt_host,
                broker_port=self.config.groov_mqtt_port,
                username=self.config.groov_mqtt_username,
                password=self.config.groov_mqtt_password,
                tls_enabled=getattr(self.config, 'groov_mqtt_tls', False),
                io_topic_patterns=getattr(self.config, 'groov_io_topic_patterns', None) or ['groov/io/#'],
            )
            self.groov_mqtt = GroovMQTT(groov_config)
            self.groov_mqtt.connect()

        # Hardware interface (wraps groov MQTT + REST fallback)
        # HardwareInterface wires groov MQTT → GroovIOSubscriber internally
        self.hardware = HardwareInterface(
            groov_mqtt=self.groov_mqtt,
            rest_host=getattr(self.config, 'groov_rest_host', None),
            rest_port=getattr(self.config, 'groov_rest_port', 443),
            api_key=getattr(self.config, 'groov_rest_api_key', None),
            topic_mapping=getattr(self.config, 'topic_mapping', None),
            output_write_fn=self._write_groov_output,
        )

    def _on_system_mqtt_connect(self):
        """System MQTT connected — subscribe to topics."""
        base = self._topic_base()
        mqtt_base = self.config.mqtt_base_topic if self.config else 'nisystem'
        topics = [
            (f"{base}/config/#", 1),
            (f"{base}/commands/#", 1),
            (f"{base}/script/#", 1),
            (f"{base}/system/#", 1),
            (f"{base}/safety/#", 1),
            (f"{base}/session/#", 1),
            (f"{base}/console/#", 1),
            (f"{mqtt_base}/discovery/ping", 1),
        ]
        for topic, qos in topics:
            self.system_mqtt.subscribe(topic, qos)

        self.pc_connected = True
        self.last_pc_contact = time.time()
        self._publish_status()
        logger.info("System MQTT connected and subscribed")

    def _write_groov_output(self, channel: str, value: float) -> bool:
        """Write output value to groov hardware via REST API."""
        if self.hardware and self.hardware._rest:
            # Use REST API for output writes (more reliable than MQTT for control)
            topic = self.hardware.io._reverse_mapping.get(channel) if self.hardware.io else None
            if topic:
                # Parse module/channel from topic: "groov/io/mod0/ch0" → (0, 0)
                parts = topic.split('/')
                try:
                    mod_idx = int(parts[2].replace('mod', ''))
                    ch_idx = int(parts[3].replace('ch', ''))
                    return self.hardware._rest.write_channel(mod_idx, ch_idx, value)
                except (IndexError, ValueError) as e:
                    logger.warning(f"Cannot parse groov topic '{topic}' for write: {e}")
        # Fallback: publish via groov MQTT
        if self.groov_mqtt and self.groov_mqtt.is_connected():
            topic = self.hardware.io._reverse_mapping.get(channel) if self.hardware and self.hardware.io else None
            if topic:
                try:
                    self.groov_mqtt._client.publish(f"{topic}/set", str(value))
                    return True
                except Exception as e:
                    logger.warning(f"groov MQTT write failed for {channel}: {e}")
        logger.warning(f"No write path available for output {channel}")
        return False

    # =========================================================================
    # MQTT MESSAGE DISPATCH
    # =========================================================================

    def _on_mqtt_message(self, topic: str, payload: Dict[str, Any]):
        """Route incoming MQTT messages to handlers."""
        try:
            self.last_pc_contact = time.time()
            self.pc_connected = True

            base = self._topic_base()
            mqtt_base = self.config.mqtt_base_topic if self.config else 'nisystem'

            if topic == f"{mqtt_base}/discovery/ping":
                self._publish_status()
                return

            if topic.startswith(f"{base}/config/"):
                self._handle_config(topic, payload)
            elif topic.startswith(f"{base}/commands/"):
                self._handle_command(topic, payload)
            elif topic.startswith(f"{base}/script/"):
                self._handle_script(topic, payload)
            elif topic.startswith(f"{base}/system/"):
                self._handle_system(topic, payload)
            elif topic.startswith(f"{base}/safety/"):
                self._handle_safety(topic, payload)
            elif topic.startswith(f"{base}/session/"):
                self._handle_session(topic, payload)
            elif topic.startswith(f"{base}/console/"):
                self._handle_console(topic, payload)

        except Exception as e:
            logger.error(f"Error handling MQTT message on {topic}: {e}")

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    def _handle_config(self, topic: str, payload: Dict):
        """Handle configuration updates from NISystem."""
        if topic.endswith('/full'):
            logger.info("Received full configuration update")
            try:
                old_scan_rate = self.config.scan_rate_hz if self.config else 4.0
                old_publish_rate = self.config.publish_rate_hz if self.config else 4.0

                self.config = load_config(payload, self.config)

                # Update scan timing stats if rate changed
                if self.config.scan_rate_hz != old_scan_rate:
                    logger.info(f"Scan rate updated: {old_scan_rate} Hz -> {self.config.scan_rate_hz} Hz")
                    self._scan_timing.target_ms = 1000.0 / self.config.scan_rate_hz
                if self.config.publish_rate_hz != old_publish_rate:
                    logger.info(f"Publish rate updated: {old_publish_rate} Hz -> {self.config.publish_rate_hz} Hz")

                # Load safety config (alarms, interlocks, safe state)
                self.safety.load_config({
                    'alarms': payload.get('alarms', []),
                    'safety_actions': payload.get('safety_actions', {}),
                    'interlocks': payload.get('interlocks', []),
                    'safe_state_config': payload.get('safe_state_config', {}),
                })

                # Load engine configs
                self.pid_engine.load_config(payload)
                self.sequence_manager.load_config(payload)
                self.trigger_engine.load_config(payload)
                self.channel_watchdog.load_config(payload)

                # Calculate config version
                config_json = json.dumps(
                    {k: v for k, v in sorted(payload.items()) if k != 'scripts'},
                    sort_keys=True
                )
                self.config_version = hashlib.sha256(config_json.encode()).hexdigest()
                self.config_timestamp = datetime.now(timezone.utc).isoformat()

                # Save locally for PC disconnect survival
                self._save_local_config()

                self._publish(self._topic('config/response'), {
                    'status': 'ok',
                    'channels': len(self.config.channels),
                    'config_hash': self.config_version,
                    'config_timestamp': self.config_timestamp,
                })

                # Auto-start acquisition
                if self.config.channels and not self._acquiring.is_set():
                    logger.info("Config received — auto-starting acquisition")
                    self._start_acquisition()

            except Exception as e:
                logger.error(f"Config update failed: {e}")
                self._publish(self._topic('config/response'), {
                    'status': 'error', 'error': str(e)
                })

    def _handle_command(self, topic: str, payload: Dict):
        """Handle commands (ping, info, output writes)."""
        request_id = payload.get('request_id', '')
        base = self._topic_base()
        resp_topic = f"{base}/command/response"

        if topic.endswith('/commands/ping'):
            self._publish(resp_topic, {
                'success': True, 'command': 'ping',
                'request_id': request_id,
                'node_id': self.config.node_id if self.config else 'opto22',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif topic.endswith('/commands/info'):
            hw = self._detect_hardware_info()
            self._publish(resp_topic, {
                'success': True, 'request_id': request_id,
                'info': {
                    'node_id': self.config.node_id if self.config else 'opto22',
                    'type': 'Opto22',
                    'version': __version__,
                    'product_type': hw.get('product_type', 'groov EPIC/RIO'),
                    'channels': len(self.config.channels) if self.config else 0,
                    'acquiring': self._acquiring.is_set(),
                    'uptime_hours': round((time.time() - self._start_time) / 3600, 1),
                    'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                }
            })
        elif topic.endswith('/commands/output'):
            ch = payload.get('channel', '')
            value = payload.get('value')
            if ch and self.config and ch in self.config.channels:
                # Session lock check
                if self._session_active and ch in self._session_locked_outputs:
                    self._publish(self._topic('session/blocked'), {
                        'channel': ch, 'reason': 'session_locked'
                    })
                    return
                # Safety hold check (alarm or interlock)
                if self.safety.is_output_blocked(ch):
                    reason = self.safety.get_output_block_reason(ch)
                    self._publish(self._topic('command/blocked'), {
                        'channel': ch, 'reason': reason
                    })
                    return
                self._set_output_internal(ch, float(value) if value is not None else 0.0)

    def _handle_script(self, topic: str, payload: Dict):
        """Handle script commands."""
        if not self.script_engine:
            return
        if topic.endswith('/add'):
            self.script_engine.add_script(payload)
        elif topic.endswith('/start'):
            self.script_engine.start_script(payload.get('id', ''))
        elif topic.endswith('/stop'):
            self.script_engine.stop_script(payload.get('id', ''))
        elif topic.endswith('/remove'):
            sid = payload.get('id', '')
            self.script_engine.stop_script(sid)
            self.script_engine.remove_script(sid)
        elif topic.endswith('/reload'):
            self.script_engine.reload_script(
                payload.get('id', ''), payload.get('code'))

    def _handle_system(self, topic: str, payload: Dict):
        """Handle system commands (acquire start/stop, reset, safe-state)."""
        if topic.endswith('/acquire/start'):
            self._start_acquisition()
        elif topic.endswith('/acquire/stop'):
            self._stop_acquisition()
        elif topic.endswith('/reset'):
            self._reset()
        elif topic.endswith('/safe-state'):
            self._set_safe_state(payload.get('reason', 'command'))

    def _handle_safety(self, topic: str, payload: Dict):
        """Handle safety commands (alarm ack, shelve, interlock, latch)."""
        if topic.endswith('/alarm/ack'):
            channel = payload.get('channel', '')
            user = payload.get('user', 'remote')
            self.safety.acknowledge_alarm(channel)
            self.audit.log_event('alarm_ack', channel, {'user': user})
        elif topic.endswith('/alarm/shelve'):
            channel = payload.get('channel', '')
            duration = payload.get('duration_s', 3600)
            user = payload.get('user', 'remote')
            self.safety.shelve_alarm(channel, duration, user)
            self.audit.log_event('alarm_shelve', channel, {
                'user': user, 'duration_s': duration
            })
        elif topic.endswith('/alarm/unshelve'):
            self.safety.unshelve_alarm(payload.get('channel', ''))
        elif topic.endswith('/alarm/out_of_service'):
            channel = payload.get('channel', '')
            user = payload.get('user', 'remote')
            self.safety.set_out_of_service(channel, user)
        elif topic.endswith('/alarm/return_to_service'):
            self.safety.return_to_service(payload.get('channel', ''))
        elif topic.endswith('/trigger'):
            action = payload.get('action', '')
            if action:
                self._set_safe_state(f"manual:{payload.get('reason', 'command')}")

        # Interlock commands
        elif '/interlock/configure' in topic:
            interlocks = payload.get('interlocks', [])
            self.safety.configure_interlocks(interlocks)
            self.audit.log_event('interlock_configure', '', {'count': len(interlocks)})
            self._publish(self._topic('interlock/configure/ack'), {
                'success': True, 'count': len(interlocks),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif '/interlock/arm' in topic:
            user = payload.get('user', 'remote')
            success, msg = self.safety.arm_latch(user)
            self.audit.log_event('interlock_arm', '', {'success': success, 'user': user, 'message': msg})
            self._publish(self._topic('interlock/arm/ack'), {
                'success': success, 'message': msg,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif '/interlock/disarm' in topic:
            user = payload.get('user', 'remote')
            self.safety.disarm_latch(user)
            self.audit.log_event('interlock_disarm', '', {'user': user})
            self._publish(self._topic('interlock/disarm/ack'), {
                'success': True,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif '/interlock/bypass' in topic:
            interlock_id = payload.get('interlock_id', '')
            bypass = payload.get('bypass', True)
            user = payload.get('user', 'remote')
            reason = payload.get('reason', '')
            duration = payload.get('max_duration_s')
            success, msg = self.safety.bypass_interlock(
                interlock_id, bypass, user, reason, duration)
            self.audit.log_event('interlock_bypass', '', {
                'interlock_id': interlock_id, 'bypass': bypass,
                'user': user, 'reason': reason, 'success': success
            })
            self._publish(self._topic('interlock/bypass/ack'), {
                'success': success, 'message': msg,
                'interlock_id': interlock_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif '/interlock/acknowledge' in topic:
            interlock_id = payload.get('interlock_id', '')
            user = payload.get('user', 'remote')
            success = self.safety.acknowledge_trip(interlock_id, user)
            self.audit.log_event('interlock_acknowledge', '', {
                'interlock_id': interlock_id, 'user': user, 'success': success
            })
        elif '/interlock/reset' in topic:
            user = payload.get('user', 'remote')
            success, msg = self.safety.reset_trip(user)
            self.audit.log_event('interlock_reset', '', {
                'success': success, 'user': user, 'message': msg
            })
            self._publish(self._topic('interlock/reset/ack'), {
                'success': success, 'message': msg,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        elif '/interlock/status' in topic:
            status = self.safety.get_interlock_status()
            self._publish(self._topic('interlock/status'), status)
        elif '/interlock/safe_state_config' in topic or '/interlock/safe-state-config' in topic:
            self.safety.configure_safe_state(payload)
            self.audit.log_event('safe_state_config', '', payload)
            self._publish(self._topic('interlock/safe_state_config/ack'), {
                'success': True,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

    def _handle_session(self, topic: str, payload: Dict):
        """Handle session commands."""
        if topic.endswith('/start'):
            self._start_session(payload)
        elif topic.endswith('/stop'):
            self._stop_session(payload.get('reason', 'command'))
        elif topic.endswith('/ping'):
            self.last_pc_contact = time.time()

    def _handle_console(self, topic: str, payload: Dict):
        """Handle interactive console commands."""
        if topic.endswith('/execute'):
            self._console_execute(payload)
        elif topic.endswith('/reset'):
            self._console_namespace = None
            self._publish(self._topic('console/result'), {
                'success': True,
                'output': 'Namespace reset.\n',
                'result': '', 'error': ''
            })

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def _start_session(self, payload: Dict):
        """Start a test session."""
        if self._session_active:
            return
        self._session_active = True
        self._session_start_time = time.time()
        self._session_name = payload.get('name', '')
        self._session_operator = payload.get('operator', '')
        self._session_locked_outputs = payload.get('locked_outputs', [])
        self._session_timeout_minutes = payload.get('timeout_minutes', 0)
        self.audit.log_event('session_start', '', {
            'name': self._session_name, 'operator': self._session_operator
        })
        logger.info(f"SESSION STARTED: {self._session_name} by {self._session_operator}")
        self._publish_session_status()

    def _stop_session(self, reason: str = 'command'):
        """Stop the current session."""
        if not self._session_active:
            return
        duration = time.time() - (self._session_start_time or time.time())
        self._session_active = False
        self._session_locked_outputs = []
        self._session_start_time = None
        self.audit.log_event('session_stop', '', {
            'reason': reason, 'duration_s': round(duration, 1)
        })
        logger.info(f"SESSION STOPPED after {duration:.1f}s (reason: {reason})")
        self._publish_session_status()

    def _publish_session_status(self):
        self._publish(self._topic('session/status'), {
            'active': self._session_active,
            'name': self._session_name,
            'operator': self._session_operator,
            'start_time': self._session_start_time,
            'duration_s': time.time() - self._session_start_time if self._session_start_time else 0,
            'locked_outputs': self._session_locked_outputs,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _check_session_timeout(self):
        if not self._session_active or self._session_timeout_minutes <= 0:
            return
        if self._session_start_time:
            if time.time() - self._session_start_time > self._session_timeout_minutes * 60:
                logger.warning("Session timeout")
                self._stop_session('timeout')

    # =========================================================================
    # INTERACTIVE CONSOLE
    # =========================================================================

    def _get_console_ns(self) -> dict:
        """Get or create the persistent console namespace."""
        if self._console_namespace is None:
            import math as _math
            svc = self

            class TagsAPI:
                def __getattr__(self, n): return svc.channel_values.get(n, 0.0)
                def __getitem__(self, n): return svc.channel_values.get(n, 0.0)
                def keys(self): return list(svc.channel_values.keys())
                def get(self, n, d=0.0): return svc.channel_values.get(n, d)
                def __repr__(self): return f'<TagsAPI: {len(self.keys())} channels>'

            class OutputsAPI:
                def set(self, ch, val): svc._set_output_internal(ch, float(val))
                def __repr__(self): return '<OutputsAPI: outputs.set(channel, value)>'

            self._console_namespace = {
                'tags': TagsAPI(), 'outputs': OutputsAPI(),
                'time': time, 'math': _math,
                'datetime': datetime, 'json': json,
                'abs': abs, 'min': min, 'max': max, 'sum': sum,
                'round': round, 'pow': pow, 'len': len,
                'sin': _math.sin, 'cos': _math.cos, 'tan': _math.tan,
                'sqrt': _math.sqrt, 'log': _math.log, 'pi': _math.pi,
                'print': print, 'range': range, 'list': list,
                'dict': dict, 'tuple': tuple, 'set': set,
                'str': str, 'int': int, 'float': float, 'bool': bool,
                'sorted': sorted, 'enumerate': enumerate, 'zip': zip,
                'True': True, 'False': False, 'None': None,
            }
            try:
                import numpy as np
                self._console_namespace['np'] = np
            except ImportError:
                pass

        return self._console_namespace

    def _console_execute(self, payload: Dict):
        """Execute a single Python command from the interactive console."""
        code = payload.get('code', '').strip()
        if not code:
            return
        result = {'success': False, 'output': '', 'result': '', 'error': ''}

        try:
            import io
            import contextlib
            stdout = io.StringIO()
            ns = self._get_console_ns()
            with contextlib.redirect_stdout(stdout):
                try:
                    compiled = compile(code, '<console>', 'eval')
                    res = eval(compiled, ns)
                    result['result'] = repr(res) if res is not None else ''
                except SyntaxError:
                    exec(compile(code, '<console>', 'exec'), ns)
            result['output'] = stdout.getvalue()
            result['success'] = True
        except Exception as e:
            result['error'] = f"{type(e).__name__}: {e}"

        self._publish(self._topic('console/result'), result)

    # =========================================================================
    # SAFETY & WATCHDOG
    # =========================================================================

    def _set_safe_state(self, reason: str = 'command'):
        """Set all outputs to their configured safe values.

        Uses SafeStateConfig for per-channel granularity. Channels not in
        SafeStateConfig fall back to their ChannelConfig.default_value, then 0.0.
        """
        logger.warning(f"Setting outputs to SAFE STATE — reason: {reason}")
        if not self.config or not self.hardware:
            return
        for ch_name, ch_cfg in self.config.channels.items():
            if ch_cfg.channel_type in ('digital_output', 'analog_output',
                                       'voltage_output', 'current_output'):
                safe_value = self.safety.get_channel_safe_value(
                    ch_name, getattr(ch_cfg, 'default_value', 0.0))
                try:
                    self.hardware.write_output(ch_name, safe_value)
                    self.output_values[ch_name] = safe_value
                    logger.info(f"  {ch_name} -> {safe_value} (safe)")
                except Exception as e:
                    logger.error(f"  Failed to set {ch_name} safe: {e}")

        # Check if safe state config says to stop session
        safe_cfg = self.safety.get_safe_state_config()
        if safe_cfg.stop_session and self._session_active:
            self._stop_session('safe_state')

        self.audit.log_event('safe_state', '', {'reason': reason})
        self._publish(self._topic('status/safe-state'), {
            'success': True, 'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def _pet_watchdog(self):
        self._watchdog_last_pet = time.time()
        self._watchdog_triggered = False

    def _check_watchdog_timeout(self) -> bool:
        if not self.config or self.config.watchdog_timeout <= 0:
            return False
        if self._watchdog_last_pet == 0:
            return False
        elapsed = time.time() - self._watchdog_last_pet
        if elapsed > self.config.watchdog_timeout and not self._watchdog_triggered:
            logger.critical(f"WATCHDOG TIMEOUT: {elapsed:.1f}s — TRIGGERING SAFE STATE")
            self._watchdog_triggered = True
            self._set_safe_state("watchdog_timeout")
            return True
        return False

    def _watchdog_monitor_loop(self):
        """Independent watchdog monitor thread."""
        interval = max(0.25, (self.config.watchdog_timeout / 4) if self.config else 0.5)
        while self._running.is_set():
            try:
                if self._acquiring.is_set():
                    self._check_watchdog_timeout()
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")
            time.sleep(interval)

    # =========================================================================
    # DATA ACQUISITION
    # =========================================================================

    def _start_acquisition(self):
        """Start data acquisition."""
        if self._acquiring.is_set():
            return
        logger.info("Starting acquisition...")
        self._acquiring.set()
        self.safety._acquiring = True
        self.state_machine.transition(Opto22State.ACQUIRING)

        self.scan_thread = threading.Thread(
            target=self._scan_loop, name="ScanLoop", daemon=True
        )
        self.scan_thread.start()

        # Notify engines
        self.pid_engine.on_acquisition_start()
        self.sequence_manager.on_acquisition_start()
        self.trigger_engine.on_acquisition_start()
        self.channel_watchdog.on_acquisition_start()

        self._publish_status()
        logger.info("Acquisition started")

    def _stop_acquisition(self):
        """Stop data acquisition."""
        if not self._acquiring.is_set():
            return

        # Notify engines
        self.pid_engine.on_acquisition_stop()
        self.sequence_manager.on_acquisition_stop()
        self.trigger_engine.on_acquisition_stop()
        self.channel_watchdog.on_acquisition_stop()

        logger.info("Stopping acquisition...")
        self._acquiring.clear()
        self.safety._acquiring = False
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=2.0)

        self.state_machine.transition(Opto22State.IDLE)
        self._publish_status()
        logger.info("Acquisition stopped")

    def _scan_loop(self):
        """Main data acquisition loop.

        Uses epoch-anchored timing to prevent cumulative drift.
        Each scan targets an absolute time rather than sleeping relative
        to the end of the previous scan.
        """
        next_scan_time = time.time()
        _scan_count = 0

        while self._acquiring.is_set():
            # Calculate intervals dynamically to pick up runtime rate changes
            scan_interval = 1.0 / (self.config.scan_rate_hz if self.config else 10.0)
            publish_interval = 1.0 / (self.config.publish_rate_hz if self.config else 4.0)
            next_scan_time += scan_interval
            loop_start = time.time()

            try:
                self._pet_watchdog()
                now = time.time()

                _scan_count += 1

                # Read hardware values (from groov MQTT subscriber or REST fallback)
                if self.hardware:
                    hw_values = self.hardware.get_values()
                    # Use actual data arrival timestamps, not scan time
                    io_timestamps = self.hardware.get_last_update_times()
                    with self.values_lock:
                        for name, val in hw_values.items():
                            self.channel_values[name] = val
                            self.channel_timestamps[name] = io_timestamps.get(name, now)

                    # Periodic stale channel check (every 10 scans)
                    if _scan_count % 10 == 0:
                        stale = self.hardware.get_stale_channels(timeout_s=10.0)
                        if stale:
                            logger.warning(f"Stale I/O channels ({len(stale)}): {stale[:5]}")
                            self._publish(self._topic('status/stale_channels'), {
                                'channels': stale,
                                'count': len(stale),
                                'timestamp': time.time(),
                            })

                # Include output values
                with self.values_lock:
                    for name, val in self.output_values.items():
                        self.channel_values[name] = val
                        self.channel_timestamps[name] = now

                # Publish at rate limit (epoch-anchored)
                if now - self._last_publish_time >= publish_interval:
                    self._publish_channel_values()
                    self._last_publish_time += publish_interval
                    if now - self._last_publish_time > publish_interval:
                        self._last_publish_time = now

                # Snapshot for engines
                with self.values_lock:
                    values_snap = dict(self.channel_values)
                    ts_snap = dict(self.channel_timestamps)

                # Safety checks (ISA-18.2 alarms + interlocks)
                configured = set(self.config.channels.keys()) if self.config else set()
                self.safety.check_all(values_snap, configured_channels=configured)

                # PID control
                dt = time.time() - loop_start
                try:
                    self.pid_engine.process_scan(values_snap, dt)
                except Exception as e:
                    logger.error(f"PID engine error: {e}")

                # Triggers
                try:
                    self.trigger_engine.process_scan(values_snap)
                except Exception as e:
                    logger.error(f"Trigger engine error: {e}")

                # Watchdog
                try:
                    self.channel_watchdog.process_scan(values_snap, ts_snap)
                except Exception as e:
                    logger.error(f"Watchdog engine error: {e}")

            except Exception as e:
                logger.error(f"Scan loop error: {e}")

            # Track scan loop timing
            loop_dt_ms = (time.time() - loop_start) * 1000
            self._scan_timing.record(loop_dt_ms)

            # Sleep until next epoch-anchored target (prevents cumulative drift)
            sleep_time = max(0, next_scan_time - time.time())
            # If we fell behind by more than one interval, reset to prevent burst catch-up
            if time.time() - next_scan_time > scan_interval:
                next_scan_time = time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Scan loop stopped")

    # =========================================================================
    # PUBLISHING
    # =========================================================================

    def _publish(self, topic: str, payload: Dict, qos: int = 0, retain: bool = False):
        """Publish message to system MQTT."""
        if self.system_mqtt and self.system_mqtt.is_connected():
            try:
                self.system_mqtt.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            except Exception as e:
                logger.warning(f"Publish failed: {e}")

    def _publish_status(self):
        """Publish system status."""
        hw = self._detect_hardware_info()
        self._publish(self._topic('status/system'), {
            'status': 'online' if self._running.is_set() else 'offline',
            'acquiring': self._acquiring.is_set(),
            'node_type': 'opto22',
            'node_id': self.config.node_id if self.config else 'opto22-001',
            'version': __version__,
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'uptime_s': round(time.time() - self._start_time, 1),
            'pc_connected': self.pc_connected,
            'channels': len(self.config.channels) if self.config else 0,
            'product_type': hw.get('product_type', 'groov EPIC/RIO'),
            'config_version': self.config_version,
            'scan_rate_hz': self.config.scan_rate_hz if self.config else 0,
            'publish_rate_hz': self.config.publish_rate_hz if self.config else 0,
            'scan_timing': self._scan_timing.to_dict(),
            'hardware_health': {
                'groov_mqtt_connected': self.groov_mqtt.is_connected() if self.groov_mqtt else False,
                'stale_channels': self.hardware.get_stale_channels(10.0) if self.hardware else [],
                'channel_count': self.hardware.io.channel_count if self.hardware else 0,
            },
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }, retain=True)

    def _publish_channel_values(self):
        """Publish batched channel values."""
        with self.values_lock:
            batch = {}
            for name, value in self.channel_values.items():
                ts = self.channel_timestamps.get(name, 0)
                batch[name] = {
                    'value': value,
                    'timestamp': ts,
                    'acquisition_ts_us': int(ts * 1_000_000),
                    'quality': get_value_quality(value)
                }
        if batch:
            self._publish(self._topic('channels/batch'), batch)

    def _publish_heartbeat(self):
        self._heartbeat_sequence += 1
        self._publish(self._topic('heartbeat'), {
            'seq': self._heartbeat_sequence,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'acquiring': self._acquiring.is_set(),
            'pc_connected': self.pc_connected,
            'node_type': 'opto22',
            'node_id': self.config.node_id if self.config else 'opto22-001',
        })

        # Publish interlock status if interlocks are configured
        if self.safety._interlocks:
            self._publish(self._topic('interlock/status'),
                          self.safety.get_interlock_status())

    # =========================================================================
    # CONFIG PERSISTENCE
    # =========================================================================

    def _load_local_config(self):
        """Load configuration from local file (survives PC disconnect)."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                self.config = NodeConfig.from_dict(data)
                logger.info(f"Loaded local config: {len(self.config.channels)} channels")
            except Exception as e:
                logger.error(f"Failed to load local config: {e}")
                self.config = NodeConfig()
        else:
            logger.info("No local config found — waiting for config from NISystem")
            self.config = NodeConfig()

    def _save_local_config(self):
        """Save configuration locally for PC disconnect survival."""
        if not self.config:
            return
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            save_config(self.config, self.config_file)
            logger.info(f"Saved config locally: {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save local config: {e}")

    # =========================================================================
    # HARDWARE DETECTION
    # =========================================================================

    def _detect_hardware_info(self) -> Dict[str, Any]:
        """Detect groov EPIC/RIO hardware info for status reporting."""
        if self._hardware_info is not None:
            return self._hardware_info

        info = {
            'product_type': 'groov EPIC/RIO',
            'serial_number': '',
            'firmware_version': '',
        }

        # Try REST API for hardware info
        if self.hardware:
            try:
                sys_info = self.hardware.get_system_info()
                if sys_info:
                    info.update(sys_info)
            except Exception:
                pass

        self._hardware_info = info
        return info

    # =========================================================================
    # RESET
    # =========================================================================

    def _reset(self):
        """Reset service to initial state."""
        logger.info("Resetting Opto22 node...")
        self._stop_acquisition()
        with self.values_lock:
            self.channel_values.clear()
            self.channel_timestamps.clear()
        self._publish_status()
        logger.info("Reset complete")

    # =========================================================================
    # MAIN SERVICE LIFECYCLE
    # =========================================================================

    def run(self):
        """Main service entry point."""
        logger.info("=" * 60)
        logger.info(f"Opto22 Node Service v{__version__} Starting")
        logger.info("=" * 60)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running.set()
        self.state_machine.transition(Opto22State.IDLE)

        # Setup dual MQTT connections
        self._setup_mqtt()

        # Initialize script engine
        if SCRIPT_ENGINE_AVAILABLE:
            self.script_engine = ScriptEngine(node=self)
            logger.info("Script engine initialized")

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="Heartbeat", daemon=True
        )
        self.heartbeat_thread.start()

        # Start watchdog monitor
        self.watchdog_monitor_thread = threading.Thread(
            target=self._watchdog_monitor_loop, name="WatchdogMonitor", daemon=True
        )
        self.watchdog_monitor_thread.start()

        # Auto-start acquisition if channels configured
        if self.config and self.config.channels:
            self._start_acquisition()

        self._publish_status()
        self.audit.log_event('session_start', '', {'version': __version__})

        logger.info("Opto22 Node Service running")
        logger.info(f"  Node ID: {self.config.node_id if self.config else 'opto22-001'}")
        logger.info(f"  Channels: {len(self.config.channels) if self.config else 0}")

        # Main loop
        try:
            while self._running.is_set():
                time.sleep(1.0)

                # Reconnect system MQTT if needed
                if self.system_mqtt and not self.system_mqtt.is_connected():
                    logger.info("System MQTT disconnected — reconnecting...")
                    self.system_mqtt.reconnect()

                # Check groov MQTT health (I/O data source)
                if self.groov_mqtt and not self.groov_mqtt.is_connected():
                    if not getattr(self, '_groov_disconnect_logged', False):
                        logger.warning("groov MQTT disconnected — I/O data will be stale")
                        self._groov_disconnect_logged = True
                        self._publish(self._topic('status/groov_mqtt'), {
                            'connected': False, 'timestamp': time.time(),
                        })
                elif self.groov_mqtt:
                    self._groov_disconnect_logged = False

                # PC contact timeout
                if time.time() - self.last_pc_contact > 30 and self.pc_connected:
                    logger.warning("Lost contact with PC — continuing standalone")
                    self.pc_connected = False

                self._check_session_timeout()

                # Periodic status publish
                if time.time() - self._last_status_time > STATUS_PUBLISH_INTERVAL:
                    self._publish_status()
                    self._last_status_time = time.time()
        except KeyboardInterrupt:
            pass

        self.shutdown()

    def _heartbeat_loop(self):
        while self._running.is_set():
            self._publish_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}")
        self._running.clear()

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down Opto22 Node Service...")
        self._running.clear()
        self.safety.save_all()
        self._stop_acquisition()

        if self.script_engine:
            self.script_engine.stop_all()

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=3.0)
        if self.watchdog_monitor_thread and self.watchdog_monitor_thread.is_alive():
            self.watchdog_monitor_thread.join(timeout=3.0)

        self._publish(self._topic('status/system'), {
            'status': 'offline', 'node_type': 'opto22'
        }, retain=True)

        self.audit.log_event('session_stop', '', {'reason': 'shutdown'})

        if self.system_mqtt:
            self.system_mqtt.disconnect()
        if self.groov_mqtt:
            self.groov_mqtt.disconnect()

        logger.info("Opto22 Node Service stopped")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Opto22 Node Service for NISystem')
    parser.add_argument('-c', '--config-dir', type=str, default=str(DEFAULT_CONFIG_DIR),
                        help=f'Configuration directory (default: {DEFAULT_CONFIG_DIR})')
    parser.add_argument('--broker', type=str, help='MQTT broker address')
    parser.add_argument('--port', type=int, help='MQTT broker port')
    parser.add_argument('--node-id', type=str, help='Node ID')
    parser.add_argument('--api-key', type=str, help='groov API key')
    parser.add_argument('--groov-mqtt', type=str, help='groov Manage MQTT host')

    args = parser.parse_args()

    service = Opto22NodeService(config_dir=Path(args.config_dir))

    # CLI overrides
    broker = args.broker or os.environ.get('MQTT_BROKER')
    if broker and service.config:
        service.config.mqtt_broker = broker

    port = args.port or os.environ.get('MQTT_PORT')
    if port and service.config:
        service.config.mqtt_port = int(port) if isinstance(port, str) else port

    node_id = args.node_id or os.environ.get('NODE_ID')
    if node_id and service.config:
        service.config.node_id = node_id

    api_key = args.api_key or os.environ.get('API_KEY')
    if api_key and service.config:
        service.config.groov_rest_api_key = api_key

    groov_mqtt = args.groov_mqtt or os.environ.get('GROOV_MQTT_HOST')
    if groov_mqtt and service.config:
        service.config.groov_mqtt_host = groov_mqtt

    service.run()


if __name__ == '__main__':
    main()
