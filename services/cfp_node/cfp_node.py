#!/usr/bin/env python3
"""
CFP Node V2 — CompactFieldPoint Bridge Service

Bridges NI CompactFieldPoint (cFP-20xx) Modbus I/O to MQTT with:
- Authenticated + TLS MQTT connection (port 8883)
- ISA-18.2 alarms + IEC 61511 interlocks (local safety)
- SHA-256 hash chain audit trail
- Formal state machine (IDLE → ACQUIRING → SESSION)
- pymodbus-based hardware communication (replaces hand-rolled raw sockets)
- Epoch-anchored scan loop with 3-error safe-state fallback

Architecture follows cRIO v2 pattern:
  main loop: process_commands → read_channels → check_safety → publish_values

Usage:
    python -m cfp_node --host 192.168.1.30 --broker 192.168.1.100 --node-id cfp-001
"""

import argparse
import json
import logging
import math
import os
import queue
import signal
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from .state_machine import State, StateTransition
from .mqtt_interface import MQTTInterface, MQTTConfig
from .safety import SafetyManager, AlarmConfig, AlarmEvent, AlarmState
from .audit_trail import AuditTrail
from .config import (
    CFPNodeConfig, CFPChannelConfig, CFPModuleConfig,
    load_config, save_config, find_config_file,
)

try:
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ModbusException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

logger = logging.getLogger('CFPNode')

__version__ = '2.0.0'

# Error threshold before safe-state fallback (matches cRIO v2)
MAX_CONSECUTIVE_ERRORS = 3

# Stale value threshold (seconds) — values older than this are marked 'stale'
STALE_VALUE_THRESHOLD_S = 10.0

# Critical commands that bypass queue eviction
_CRITICAL_COMMANDS = ('stop', 'acquire/stop', 'session/stop', 'safe_state', 'safe-state', 'alarm')

# Config save path
_CONFIG_SAVE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cfp_config.json')

class ScanTimingStats:
    """Lightweight scan loop timing statistics."""

    def __init__(self, target_ms: float, window_size: int = 200):
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

    def to_dict(self) -> dict:
        samples = self._samples
        return {
            'target_ms': round(self.target_ms, 2),
            'actual_ms': round(self.mean_ms, 2),
            'min_ms': round(min(samples), 2) if samples else 0.0,
            'max_ms': round(max(samples), 2) if samples else 0.0,
            'overruns': self.overruns,
            'total_scans': self.total_scans,
        }

@dataclass
class Command:
    """Queued command from MQTT."""
    topic: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

class CFPNodeV2:
    """
    CompactFieldPoint Node Service (V2).

    Design principles (matching cRIO v2):
    - Single main loop handles everything
    - Command queue — MQTT callbacks never block
    - State machine for acquisition/session
    - Safety manager for alarms + interlocks
    - Audit trail for compliance
    """

    def __init__(self, config: CFPNodeConfig):
        self.config = config
        self._start_time = time.time()

        # State machine
        self.state = StateTransition(State.IDLE)
        self.state.on_enter(State.ACQUIRING, self._on_enter_acquiring)
        self.state.on_exit(State.ACQUIRING, self._on_exit_acquiring)
        self.state.on_enter(State.SESSION, self._on_enter_session)
        self.state.on_exit(State.SESSION, self._on_exit_session)
        self.state.on_enter(State.IDLE, self._on_enter_idle)

        # Command queue — thread-safe, bounded
        self.command_queue: queue.Queue = queue.Queue(maxsize=1000)

        # Channel values
        self.channel_values: Dict[str, Dict[str, Any]] = {}
        self.output_values: Dict[str, float] = {}
        self.values_lock = threading.Lock()

        # Initialize output values from config defaults
        for name, ch in config.channels.items():
            if ch.writable:
                self.output_values[name] = ch.default_value

        # Modbus client (pymodbus)
        self.modbus: Optional[ModbusTcpClient] = None
        self._modbus_connected = False

        # MQTT interface (authenticated + TLS)
        mqtt_config = MQTTConfig(
            broker_host=config.mqtt_broker,
            broker_port=config.mqtt_port,
            username=config.mqtt_username,
            password=config.mqtt_password,
            client_id=config.node_id,
            base_topic=config.mqtt_base_topic,
            node_id=config.node_id,
            tls_enabled=config.tls_enabled,
            tls_ca_cert=config.tls_ca_cert,
        )
        self.mqtt = MQTTInterface(mqtt_config)
        self.mqtt.on_message = self._enqueue_command
        self.mqtt.on_connection_change = self._on_mqtt_connection_change

        # Control flags
        self._shutdown = threading.Event()
        self._main_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Timing
        self._last_publish_time = 0.0
        self._publish_interval = 1.0 / max(config.publish_rate_hz, 0.1)
        self._scan_interval = 1.0 / max(config.scan_rate_hz, 0.1)
        self._scan_timing = ScanTimingStats(target_ms=self._scan_interval * 1000)

        # Error tracking
        self._consecutive_errors = 0

        # Config version (for DAQ sync)
        self.config_version = ''
        self.config_timestamp: Optional[str] = None

        # Audit trail
        audit_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'audit')
        self.audit = AuditTrail(audit_dir=audit_dir, node_id=config.node_id)

        # Safety manager
        safety_data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'safety')
        self.safety = SafetyManager(data_dir=safety_data_dir)
        self.safety.on_alarm = self._on_alarm_event
        self.safety.on_action = self._on_safety_action
        self.safety.on_stop_session = lambda: self._cmd_acquire_stop({'reason': 'safety_action'})
        self.safety.on_interlock_action = self._on_safety_action
        self.safety.on_publish = self._on_safety_publish
        self._configure_safety_from_channels()

        logger.info(
            f"CFP Node V2 initialized: {config.node_id}, "
            f"host={config.cfp_host}:{config.cfp_port}, "
            f"scan={config.scan_rate_hz}Hz, publish={config.publish_rate_hz}Hz"
        )

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> bool:
        """Start the CFP node service."""
        logger.info(f"Starting CFP Node V2: {self.config.node_id}")

        if not PYMODBUS_AVAILABLE:
            logger.error("pymodbus is required but not installed")
            return False

        # Connect Modbus
        if not self._connect_modbus():
            logger.warning("Initial Modbus connection failed — will retry in main loop")

        # Connect MQTT
        if not self.mqtt.connect():
            logger.error("Failed to initiate MQTT connection")
            return False

        if not self.mqtt.wait_for_connection(timeout=10.0):
            logger.error("MQTT connection timeout")
            return False

        self.mqtt.setup_standard_subscriptions()

        # Publish online status
        self._publish_status()

        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name='cfp-heartbeat')
        self._heartbeat_thread.start()

        # Start main loop thread
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name='cfp-main')
        self._main_thread.start()

        logger.info(f"CFP Node V2 started: {self.config.node_id}")
        return True

    def stop(self):
        """Stop the CFP node service."""
        logger.info("Stopping CFP Node V2...")
        self._shutdown.set()

        # Save safety state
        self.safety.save_all()

        # Transition to IDLE (triggers safe state)
        if self.state.is_acquiring:
            self.state.to(State.IDLE)

        # Wait for threads
        if self._main_thread:
            self._main_thread.join(timeout=2.0)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)

        # Disconnect Modbus
        if self.modbus:
            self.modbus.close()
            self.modbus = None
            self._modbus_connected = False

        # Disconnect MQTT
        self.mqtt.disconnect()

        logger.info("CFP Node V2 stopped")

    def run(self):
        """Start and block until shutdown signal."""
        if not self.start():
            return False
        while not self._shutdown.wait(1.0):
            pass
        self.stop()
        return True

    # =========================================================================
    # MODBUS CONNECTION
    # =========================================================================

    def _connect_modbus(self) -> bool:
        """Connect to cFP via pymodbus."""
        try:
            self.modbus = ModbusTcpClient(
                host=self.config.cfp_host,
                port=self.config.cfp_port,
                timeout=self.config.timeout,
            )
            if self.modbus.connect():
                self._modbus_connected = True
                logger.info(f"Modbus connected to {self.config.cfp_host}:{self.config.cfp_port}")
                return True
            else:
                self._modbus_connected = False
                logger.warning(f"Modbus connection failed to {self.config.cfp_host}:{self.config.cfp_port}")
                return False
        except Exception as e:
            self._modbus_connected = False
            logger.error(f"Modbus connection error: {e}")
            return False

    def _ensure_modbus_connected(self) -> bool:
        """Ensure Modbus connection is alive, reconnect if needed."""
        if self.modbus and self._modbus_connected:
            return True
        logger.warning("Modbus disconnected, reconnecting...")
        return self._connect_modbus()

    # =========================================================================
    # MAIN LOOP (epoch-anchored)
    # =========================================================================

    def _main_loop(self):
        """Main scan loop — epoch-anchored timing."""
        next_scan_time = time.time()

        while not self._shutdown.is_set():
            next_scan_time += self._scan_interval
            loop_start = time.time()

            try:
                # 1. Process pending commands
                self._process_commands()

                # 2. Read channels (if acquiring)
                if self.state.is_acquiring:
                    self._read_channels()

                # 3. Check safety (if acquiring)
                if self.state.is_acquiring:
                    self._check_safety()

                # 4. Publish values (rate-limited)
                now = time.time()
                if now - self._last_publish_time >= self._publish_interval:
                    self._publish_values()
                    self._last_publish_time = now

                # Record timing
                dt_ms = (time.time() - loop_start) * 1000
                self._scan_timing.record(dt_ms)

                # Reset error counter on success
                self._consecutive_errors = 0

            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Main loop error ({self._consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")

                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("Max consecutive errors — applying safe state and going IDLE")
                    self._apply_safe_state_all()
                    self.state.to(State.IDLE)
                    self.mqtt.publish_critical("status/degraded", {
                        'reason': 'consecutive_errors',
                        'count': self._consecutive_errors,
                        'timestamp': datetime.now().isoformat(),
                    })
                    # Exponential backoff
                    backoff = min(5 * (2 ** (self._consecutive_errors - MAX_CONSECUTIVE_ERRORS)), 60)
                    self._shutdown.wait(backoff)
                    # Try recovery
                    if not self._shutdown.is_set():
                        self._connect_modbus()
                        self._consecutive_errors = 0

            # Sleep until next scan
            sleep_time = next_scan_time - time.time()
            if sleep_time > 0:
                self._shutdown.wait(sleep_time)
            elif sleep_time < -self._scan_interval:
                # Fell behind by more than one interval — reset anchor
                next_scan_time = time.time()

    # =========================================================================
    # COMMAND PROCESSING
    # =========================================================================

    def _enqueue_command(self, topic: str, payload: Dict[str, Any]):
        """Enqueue command from MQTT (called from paho thread — must be non-blocking)."""
        cmd = Command(topic=topic, payload=payload)

        try:
            self.command_queue.put_nowait(cmd)
        except queue.Full:
            # Check if this is a critical command
            topic_suffix = topic.split('/')[-1] if '/' in topic else topic
            is_critical = any(c in topic for c in _CRITICAL_COMMANDS)

            if is_critical:
                # Evict one non-critical command to make room
                try:
                    evicted = self.command_queue.get_nowait()
                    self.command_queue.put_nowait(cmd)
                    logger.warning(f"Queue full — evicted non-critical command for critical: {topic_suffix}")
                except queue.Empty:
                    logger.error(f"Queue full — cannot enqueue critical command: {topic_suffix}")
            else:
                logger.warning(f"Command queue full — dropping: {topic_suffix}")

    def _process_commands(self):
        """Drain and process all pending commands."""
        processed = 0
        while not self.command_queue.empty() and processed < 50:
            try:
                cmd = self.command_queue.get_nowait()
                self._handle_command(cmd.topic, cmd.payload)
                processed += 1
            except queue.Empty:
                break

    def _handle_command(self, topic: str, payload: Dict[str, Any]):
        """Route command to appropriate handler."""
        base = self.mqtt.topic_base

        # Strip base to get relative topic
        if topic.startswith(base + '/'):
            relative = topic[len(base) + 1:]
        elif topic == f"{self.mqtt.config.base_topic}/discovery/ping":
            self._publish_status()
            return
        else:
            logger.debug(f"Unrecognized topic: {topic}")
            return

        # Route by topic
        if relative == 'system/acquire/start':
            self._cmd_acquire_start(payload)
        elif relative == 'system/acquire/stop':
            self._cmd_acquire_stop(payload)
        elif relative == 'session/start':
            self._cmd_session_start(payload)
        elif relative == 'session/stop':
            self._cmd_session_stop(payload)
        elif relative == 'commands/output':
            self._cmd_write_output(payload)
        elif relative == 'config/full':
            self._cmd_config_full(payload)
        elif relative == 'config/get':
            self._cmd_config_get(payload)
        elif relative.startswith('alarm/'):
            self._handle_alarm_command(relative, payload)
        elif relative.startswith('interlock/'):
            self._handle_interlock_command(relative, payload)
        elif relative in ('safety/safe_state', 'safety/safe-state'):
            self._cmd_safe_state(payload)
        elif relative == 'commands/ping':
            self.mqtt.publish("command/ack", {
                'command': 'ping', 'success': True,
                'request_id': payload.get('request_id', ''),
            })
        elif relative == 'commands/info':
            self.mqtt.publish("command/ack", {
                'command': 'info', 'success': True,
                'info': {
                    'node_id': self.config.node_id,
                    'node_type': 'cfp',
                    'version': __version__,
                    'host': self.config.cfp_host,
                    'modules': len(self.config.modules),
                    'channels': len(self.config.channels),
                },
                'request_id': payload.get('request_id', ''),
            })
        else:
            logger.debug(f"Unhandled command: {relative}")

    # =========================================================================
    # ACQUIRE / SESSION
    # =========================================================================

    def _cmd_acquire_start(self, payload: Dict[str, Any]):
        """Start acquisition."""
        if self.state.is_acquiring:
            self.mqtt.publish("command/ack", {
                'command': 'acquire_start', 'success': True, 'message': 'Already acquiring'})
            return

        if not self._ensure_modbus_connected():
            self.mqtt.publish("command/ack", {
                'command': 'acquire_start', 'success': False, 'error': 'Modbus not connected'})
            return

        success = self.state.to(State.ACQUIRING, payload)
        self.mqtt.publish("command/ack", {
            'command': 'acquire_start', 'success': success,
            'request_id': payload.get('request_id', ''),
        })

    def _cmd_acquire_stop(self, payload: Dict[str, Any]):
        """Stop acquisition."""
        success = self.state.to(State.IDLE, payload)
        self.mqtt.publish("command/ack", {
            'command': 'acquire_stop', 'success': success,
            'reason': payload.get('reason', 'user'),
            'request_id': payload.get('request_id', ''),
        })

    def _cmd_session_start(self, payload: Dict[str, Any]):
        """Start a test session."""
        if not self.state.is_acquiring:
            self.mqtt.publish("command/ack", {
                'command': 'session_start', 'success': False,
                'error': 'Must be acquiring before starting session'})
            return

        success = self.state.to(State.SESSION, payload)
        if success:
            self.audit.log_event('session_start', details={
                'name': payload.get('name', ''),
                'operator': payload.get('operator', ''),
            })
        self.mqtt.publish("command/ack", {
            'command': 'session_start', 'success': success,
            'request_id': payload.get('request_id', ''),
        })

    def _cmd_session_stop(self, payload: Dict[str, Any]):
        """Stop current session."""
        if not self.state.is_session_active:
            self.mqtt.publish("command/ack", {
                'command': 'session_stop', 'success': True, 'message': 'No active session'})
            return

        success = self.state.to(State.ACQUIRING, payload)
        if success:
            self.audit.log_event('session_stop', details={
                'reason': payload.get('reason', 'user'),
            })
        self.mqtt.publish("command/ack", {
            'command': 'session_stop', 'success': success,
            'request_id': payload.get('request_id', ''),
        })

    # =========================================================================
    # OUTPUT WRITES (with safety hold checking)
    # =========================================================================

    def _cmd_write_output(self, payload: Dict[str, Any]):
        """Write to an output channel (with safety checks)."""
        channel = payload.get('channel', '')
        value = payload.get('value')
        request_id = payload.get('request_id', '')

        if channel not in self.config.channels:
            self.mqtt.publish("command/ack", {
                'command': 'output', 'success': False,
                'error': f"Channel '{channel}' not found", 'request_id': request_id})
            return

        ch_config = self.config.channels[channel]
        if not ch_config.writable:
            self.mqtt.publish("command/ack", {
                'command': 'output', 'success': False,
                'error': f"Channel '{channel}' is not writable", 'request_id': request_id})
            return

        # Check safety holds
        if self.safety.is_output_blocked(channel):
            self.mqtt.publish("command/ack", {
                'command': 'output', 'success': False,
                'error': f"Output '{channel}' is blocked by safety hold", 'request_id': request_id})
            return

        # Check session lock
        if self.state.is_output_locked(channel):
            self.mqtt.publish("command/ack", {
                'command': 'output', 'success': False,
                'error': f"Output '{channel}' is locked by session", 'request_id': request_id})
            return

        success = self._write_modbus_output(channel, float(value), ch_config)

        self.mqtt.publish("command/ack", {
            'command': 'output', 'success': success,
            'channel': channel, 'value': value, 'request_id': request_id,
        })

    def _write_modbus_output(self, channel: str, value: float,
                             ch_config: CFPChannelConfig, is_safety: bool = False) -> bool:
        """Write a value to a Modbus output. Retries once for safety writes."""
        if not self._ensure_modbus_connected():
            return False

        try:
            if ch_config.register_type == 'coil':
                result = self.modbus.write_coil(
                    ch_config.address, bool(value), slave=ch_config.slave_id)
            elif ch_config.register_type == 'holding':
                # Reverse scaling: raw = (eng - offset) / scale
                if ch_config.scale != 0:
                    raw_value = (value - ch_config.offset) / ch_config.scale
                else:
                    raw_value = value

                # Encode based on data type
                registers = self._encode_value(raw_value, ch_config.data_type)
                if len(registers) == 1:
                    result = self.modbus.write_register(
                        ch_config.address, registers[0], slave=ch_config.slave_id)
                else:
                    result = self.modbus.write_registers(
                        ch_config.address, registers, slave=ch_config.slave_id)
            else:
                logger.warning(f"Cannot write to {ch_config.register_type} register type")
                return False

            if result.isError():
                if is_safety:
                    # Single retry for safety writes (50ms delay)
                    time.sleep(0.05)
                    logger.warning(f"Safety write retry for {channel}")
                    return self._write_modbus_output(channel, value, ch_config, is_safety=False)
                logger.error(f"Modbus write error for {channel}: {result}")
                return False

            # Update cached output value
            self.output_values[channel] = value
            return True

        except Exception as e:
            if is_safety:
                time.sleep(0.05)
                logger.warning(f"Safety write retry for {channel} after exception: {e}")
                return self._write_modbus_output(channel, value, ch_config, is_safety=False)
            logger.error(f"Write error for {channel}: {e}")
            return False

    def _encode_value(self, raw_value: float, data_type: str) -> List[int]:
        """Encode a value to Modbus register(s)."""
        if data_type == 'float32':
            packed = struct.pack('>f', raw_value)
            return [struct.unpack('>H', packed[0:2])[0], struct.unpack('>H', packed[2:4])[0]]
        elif data_type in ('int32', 'uint32'):
            int_val = int(raw_value)
            if data_type == 'int32':
                int_val = max(-2147483648, min(2147483647, int_val))
                packed = struct.pack('>i', int_val)
            else:
                int_val = max(0, min(4294967295, int_val))
                packed = struct.pack('>I', int_val)
            return [struct.unpack('>H', packed[0:2])[0], struct.unpack('>H', packed[2:4])[0]]
        elif data_type == 'int16':
            int_val = max(-32768, min(32767, int(raw_value)))
            return [int_val & 0xFFFF]
        else:  # uint16 default
            int_val = max(0, min(65535, int(raw_value)))
            return [int_val]

    # =========================================================================
    # CHANNEL READING
    # =========================================================================

    def _read_channels(self):
        """Read all configured channels from cFP via Modbus."""
        if not self._ensure_modbus_connected():
            return

        now = time.time()
        timestamp = datetime.now().isoformat()
        acquisition_ts_us = int(now * 1_000_000)

        new_values = {}
        for name, ch in self.config.channels.items():
            try:
                value = self._read_single_channel(ch)
                quality = 'good' if value is not None else 'bad'

                new_values[name] = {
                    'value': value,
                    'timestamp': timestamp,
                    'acquisition_ts_us': acquisition_ts_us,
                    'units': ch.unit,
                    'quality': quality,
                    'status': 'normal' if quality == 'good' else 'disconnected',
                }
            except Exception as e:
                logger.debug(f"Error reading {name}: {e}")
                new_values[name] = {
                    'value': None,
                    'timestamp': timestamp,
                    'acquisition_ts_us': acquisition_ts_us,
                    'units': ch.unit,
                    'quality': 'bad',
                    'status': 'error',
                }

        with self.values_lock:
            self.channel_values.update(new_values)

    def _read_single_channel(self, ch: CFPChannelConfig) -> Optional[float]:
        """Read a single channel from Modbus."""
        reg_count = 1
        if ch.data_type in ('float32', 'int32', 'uint32'):
            reg_count = 2

        if ch.register_type == 'holding':
            result = self.modbus.read_holding_registers(
                ch.address, reg_count, slave=ch.slave_id)
        elif ch.register_type == 'input':
            result = self.modbus.read_input_registers(
                ch.address, reg_count, slave=ch.slave_id)
        elif ch.register_type == 'coil':
            result = self.modbus.read_coils(ch.address, 1, slave=ch.slave_id)
            if result and not result.isError():
                return float(result.bits[0])
            return None
        elif ch.register_type == 'discrete':
            result = self.modbus.read_discrete_inputs(ch.address, 1, slave=ch.slave_id)
            if result and not result.isError():
                return float(result.bits[0])
            return None
        else:
            return None

        if result is None or result.isError():
            return None

        # Decode registers
        raw_value = self._decode_registers(result.registers, ch.data_type)
        if raw_value is None:
            return None

        # Apply scaling
        return raw_value * ch.scale + ch.offset

    def _decode_registers(self, registers: List[int], data_type: str) -> Optional[float]:
        """Decode Modbus register(s) to a float value."""
        if not registers:
            return None

        if data_type == 'float32' and len(registers) >= 2:
            packed = struct.pack('>HH', registers[0], registers[1])
            value = struct.unpack('>f', packed)[0]
            return value if math.isfinite(value) else None
        elif data_type == 'int32' and len(registers) >= 2:
            packed = struct.pack('>HH', registers[0], registers[1])
            return float(struct.unpack('>i', packed)[0])
        elif data_type == 'uint32' and len(registers) >= 2:
            packed = struct.pack('>HH', registers[0], registers[1])
            return float(struct.unpack('>I', packed)[0])
        elif data_type == 'int16':
            raw = registers[0]
            return float(raw - 65536 if raw > 32767 else raw)
        elif data_type == 'bool':
            return float(registers[0] != 0)
        else:  # uint16 default
            return float(registers[0])

    # =========================================================================
    # SAFETY
    # =========================================================================

    def _configure_safety_from_channels(self):
        """Build alarm configs from channel alarm limits."""
        for name, ch in self.config.channels.items():
            if not ch.alarm_enabled:
                continue
            alarm_cfg = AlarmConfig(
                channel=name,
                hihi=ch.hihi_limit,
                hi=ch.hi_limit,
                lo=ch.lo_limit,
                lolo=ch.lolo_limit,
                deadband=ch.alarm_deadband,
                on_delay=ch.alarm_delay_sec,
            )
            # Set safety action if configured
            if ch.safety_action:
                alarm_cfg.safety_actions = ch.safety_action
            self.safety.configure_alarm(alarm_cfg)

    def _check_safety(self):
        """Run safety checks on current channel values."""
        # Build flat value dict for safety manager
        values = {}
        configured = set(self.config.channels.keys())
        with self.values_lock:
            for name, data in self.channel_values.items():
                val = data.get('value')
                if val is not None:
                    values[name] = val

        self.safety.check_all(values, configured_channels=configured)

    def _on_alarm_event(self, event: AlarmEvent):
        """Handle alarm event from safety manager."""
        logger.warning(f"Alarm: {event.channel} — {event.alarm_type} ({event.severity.name})")
        self.audit.log_event('alarm_trip', channel=event.channel, details={
            'type': event.alarm_type,
            'severity': event.severity.name,
            'value': event.value,
            'limit': event.limit,
        })
        # Build alarm payload
        alarm_payload = {
            'channel': event.channel,
            'alarm_type': event.alarm_type,
            'type': event.alarm_type,
            'severity': event.severity.name,
            'value': event.value,
            'limit': event.limit,
            'state': event.state.name,
            'timestamp': datetime.now().isoformat(),
        }
        # Flat event (backward compat — DAQ service listens for history)
        self.mqtt.publish_critical("alarms/event", alarm_payload)

        # Per-alarm retained topic (dashboard consumes directly)
        alarm_id = f"{event.channel}_{event.alarm_type}"
        is_cleared = event.state.name in ('RETURNED', 'NORMAL')
        alarm_payload['active'] = not is_cleared
        if not is_cleared:
            alarm_payload['alarm_id'] = alarm_id
        self.mqtt.publish_critical(f"alarms/active/{alarm_id}", alarm_payload, retain=True)

        # Publish retained alarm status
        self.mqtt.publish_critical("alarms/status", self.safety.get_alarm_summary(), retain=True)

    def _on_safety_action(self, channel: str, action: Any, value: float):
        """Execute a safety action (write output to safe value)."""
        ch_config = self.config.channels.get(channel)
        if not ch_config:
            logger.error(f"Safety action: channel '{channel}' not found")
            return

        success = self._write_modbus_output(channel, value, ch_config, is_safety=True)
        if not success:
            self.mqtt.publish_critical("safety/write_failure", {
                'channel': channel, 'target_value': value,
                'timestamp': datetime.now().isoformat(),
            })
            logger.critical(f"Safety write FAILED for {channel} → {value}")
        else:
            self.audit.log_event('safety_action', channel=channel, details={
                'value': value, 'action': str(action)})
            self.mqtt.publish("safety/action", {
                'channel': channel, 'value': value, 'action': str(action),
                'timestamp': datetime.now().isoformat(),
            })

    def _on_safety_publish(self, topic: str, payload: Dict[str, Any]):
        """Pass-through for safety manager MQTT publishes."""
        self.mqtt.publish(topic, payload)

    def _cmd_safe_state(self, payload: Dict[str, Any]):
        """Apply safe state to all outputs."""
        self._apply_safe_state_all()
        self.audit.log_event('safe_state', details={'source': 'command'})
        self.mqtt.publish("command/ack", {
            'command': 'safe_state', 'success': True,
            'request_id': payload.get('request_id', ''),
        })

    def _apply_safe_state_all(self):
        """Write all writable channels to their default (safe) values."""
        for name, ch in self.config.channels.items():
            if ch.writable:
                self._write_modbus_output(name, ch.default_value, ch, is_safety=True)

    # =========================================================================
    # ALARM / INTERLOCK COMMANDS
    # =========================================================================

    def _handle_alarm_command(self, relative: str, payload: Dict[str, Any]):
        """Handle alarm management commands."""
        channel = payload.get('channel', '')
        request_id = payload.get('request_id', '')

        if relative == 'alarm/ack':
            self.safety.acknowledge_alarm(channel)
            self.audit.log_event('alarm_ack', channel=channel,
                                 operator=payload.get('operator', 'SYSTEM'))
        elif relative == 'alarm/shelve':
            duration = payload.get('duration_minutes', 60)
            self.safety.shelve_alarm(channel, duration_minutes=duration)
            self.audit.log_event('alarm_shelve', channel=channel)
        elif relative == 'alarm/unshelve':
            self.safety.unshelve_alarm(channel)
            self.audit.log_event('alarm_unshelve', channel=channel)
        elif relative == 'alarm/out-of-service':
            self.safety.set_out_of_service(channel)
            self.audit.log_event('alarm_out_of_service', channel=channel)
        elif relative == 'alarm/return-to-service':
            self.safety.return_to_service(channel)
            self.audit.log_event('alarm_return_to_service', channel=channel)

        self.mqtt.publish("alarms/status", self.safety.get_alarm_summary(), retain=True)
        self.mqtt.publish("command/ack", {
            'command': relative, 'success': True, 'request_id': request_id})

    def _handle_interlock_command(self, relative: str, payload: Dict[str, Any]):
        """Handle interlock management commands."""
        request_id = payload.get('request_id', '')
        cmd = relative.split('/')[-1]  # e.g., 'arm_latch' from 'interlock/arm_latch'

        if cmd == 'arm_latch':
            self.safety.arm_latch()
            self.audit.log_event('interlock_arm')
        elif cmd == 'disarm_latch':
            self.safety.disarm_latch()
            self.audit.log_event('interlock_disarm')
        elif cmd == 'bypass_interlock':
            interlock_id = payload.get('interlock_id', '')
            duration = payload.get('duration_minutes', 60)
            self.safety.bypass_interlock(interlock_id, duration_minutes=duration)
            self.audit.log_event('interlock_bypass', details={'interlock_id': interlock_id})
        elif cmd == 'unbypass_interlock':
            interlock_id = payload.get('interlock_id', '')
            self.safety.unbypass_interlock(interlock_id)
            self.audit.log_event('interlock_unbypass', details={'interlock_id': interlock_id})
        elif cmd == 'acknowledge_trip':
            interlock_id = payload.get('interlock_id', '')
            self.safety.acknowledge_trip(interlock_id)
            self.audit.log_event('interlock_acknowledge', details={'interlock_id': interlock_id})
        elif cmd == 'reset_trip':
            interlock_id = payload.get('interlock_id', '')
            self.safety.reset_trip(interlock_id)
            self.audit.log_event('interlock_reset', details={'interlock_id': interlock_id})
        elif cmd == 'status':
            status = self.safety.get_interlock_status()
            self.mqtt.publish("interlock/status", status, retain=True)

        self.mqtt.publish("command/ack", {
            'command': relative, 'success': True, 'request_id': request_id})

    # =========================================================================
    # CONFIG PUSH FROM DAQ SERVICE
    # =========================================================================

    def _cmd_config_full(self, payload: Dict[str, Any]):
        """Handle full config push from DAQ service (atomic swap)."""
        logger.info("Received config push from DAQ service")

        try:
            # Update scan/publish rates
            new_scan_rate = payload.get('scan_rate_hz', self.config.scan_rate_hz)
            new_publish_rate = payload.get('publish_rate_hz', self.config.publish_rate_hz)
            new_scan_rate = max(0.1, min(100.0, new_scan_rate))
            new_publish_rate = max(0.1, min(100.0, new_publish_rate))

            rate_changed = (new_scan_rate != self.config.scan_rate_hz or
                            new_publish_rate != self.config.publish_rate_hz)
            if rate_changed:
                self.config.scan_rate_hz = new_scan_rate
                self.config.publish_rate_hz = new_publish_rate
                self._scan_interval = 1.0 / new_scan_rate
                self._publish_interval = 1.0 / new_publish_rate
                self._scan_timing = ScanTimingStats(target_ms=self._scan_interval * 1000)

            # Parse channels (atomic swap)
            new_channels = {}
            channels_data = payload.get('channels', {})
            for name, ch_data in channels_data.items():
                if isinstance(ch_data, dict):
                    new_channels[name] = CFPChannelConfig.from_dict(name, ch_data)

            channels_changed = set(new_channels.keys()) != set(self.config.channels.keys())
            self.config.channels = new_channels

            # Initialize output values for new writable channels
            for name, ch in new_channels.items():
                if ch.writable and name not in self.output_values:
                    self.output_values[name] = ch.default_value

            # Rebuild safety from new channels
            self.safety.clear_all()
            self._configure_safety_from_channels()

            # Apply interlocks from push
            interlocks = payload.get('interlocks', [])
            if interlocks:
                self.safety.configure_interlocks(interlocks)
                logger.info(f"Configured {len(interlocks)} interlocks from DAQ push")

            # Apply safe state config
            safe_state_config = payload.get('safe_state_config')
            if safe_state_config:
                self.safety.configure_safe_state(safe_state_config)

            # Store config version
            self.config_version = payload.get('config_version', '')
            self.config_timestamp = payload.get('timestamp')

            # Save to disk
            self._save_config_to_disk()

            logger.info(f"Config push applied: {len(new_channels)} channels, "
                        f"version={self.config_version}")

            self.mqtt.publish_critical("config/response", {
                'success': True, 'message': 'Config applied',
                'config_version': self.config_version,
                'channels': len(new_channels),
            })

            self.audit.log_event('config_update', details={
                'version': self.config_version,
                'channels': len(new_channels),
                'interlocks': len(interlocks),
            })

        except Exception as e:
            logger.error(f"Config push failed: {e}")
            self.mqtt.publish_critical("config/response", {
                'success': False, 'error': str(e)})

    def _cmd_config_get(self, payload: Dict[str, Any]):
        """Return current configuration."""
        self.mqtt.publish("config/response", {
            'success': True,
            'request_type': 'get',
            'config': self.config.to_dict(),
            'config_version': self.config_version,
            'request_id': payload.get('request_id', ''),
        })

    def _save_config_to_disk(self):
        """Save current config to disk."""
        try:
            save_config(self.config, _CONFIG_SAVE_PATH)
        except Exception as e:
            logger.warning(f"Failed to save config to disk: {e}")

    # =========================================================================
    # STATE TRANSITION CALLBACKS
    # =========================================================================

    def _on_enter_acquiring(self, old_state, new_state, payload):
        """Called when entering ACQUIRING state."""
        self._scan_timing.reset()
        self._consecutive_errors = 0
        logger.info("Acquisition started")

    def _on_exit_acquiring(self, old_state, new_state, payload):
        """Called when exiting ACQUIRING state."""
        logger.info("Acquisition stopped")

    def _on_enter_session(self, old_state, new_state, payload):
        """Called when entering SESSION state."""
        logger.info("Session started")

    def _on_exit_session(self, old_state, new_state, payload):
        """Called when exiting SESSION state."""
        logger.info("Session ended")

    def _on_enter_idle(self, old_state, new_state, payload):
        """Called when entering IDLE state — apply safe state."""
        if old_state != State.IDLE:
            self._apply_safe_state_all()
            logger.info("Entered IDLE — safe state applied")

    def _on_mqtt_connection_change(self, connected: bool):
        """Handle MQTT connection state change."""
        if connected:
            logger.info("MQTT connection restored")
        else:
            logger.warning("MQTT connection lost")

    # =========================================================================
    # PUBLISHING
    # =========================================================================

    def _publish_values(self):
        """Publish channel values in lean batch format."""
        now = time.time()
        ts_us = int(now * 1_000_000)
        timestamp = datetime.now().isoformat()

        v = {}
        bad = []

        with self.values_lock:
            if not self.channel_values:
                return
            for name, data in self.channel_values.items():
                val = data.get('value')
                if val is None or data.get('quality') == 'bad':
                    v[name] = None
                    bad.append(name)
                else:
                    v[name] = val

        batch = {'t': timestamp, 'ts_us': ts_us, 'v': v}
        if bad:
            batch['bad'] = bad

        self.mqtt.publish("channels/batch", batch)

    def _publish_status(self):
        """Publish node status (retained)."""
        status = {
            'online': True,
            'node_id': self.config.node_id,
            'node_type': 'cfp',
            'version': __version__,
            'host': self.config.cfp_host,
            'modbus_connected': self._modbus_connected,
            'modules': len(self.config.modules),
            'channels': len(self.config.channels),
            'config_version': self.config_version,
            'uptime_s': round(time.time() - self._start_time, 1),
            'timestamp': datetime.now().isoformat(),
        }
        status.update(self.state.get_status())
        self.mqtt.publish_critical("status/system", status, retain=True)

    def _heartbeat_loop(self):
        """Heartbeat publisher (separate thread)."""
        while not self._shutdown.wait(self.config.heartbeat_interval_s):
            self.mqtt.publish("heartbeat", {
                'node_id': self.config.node_id,
                'node_type': 'cfp',
                'status': self.state.state.name,
                'acquiring': self.state.is_acquiring,
                'modbus_connected': self._modbus_connected,
                'uptime_s': round(time.time() - self._start_time, 1),
                'scan_timing': self._scan_timing.to_dict(),
                'timestamp': datetime.now().isoformat(),
            })

            # Also publish interlock status if any configured
            interlock_status = self.safety.get_interlock_status()
            if interlock_status:
                self.mqtt.publish("interlock/status", interlock_status, retain=True)

            # Publish discovery response format
            self.mqtt.publish(
                f"{self.mqtt.config.base_topic}/discovery/response",
                {
                    'node_id': self.config.node_id,
                    'node_type': 'cfp',
                    'online': True,
                    'host': self.config.cfp_host,
                    'modules': len(self.config.modules),
                    'channels': len(self.config.channels),
                    'version': __version__,
                })

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='NISystem CFP Node V2 — CompactFieldPoint Bridge Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 192.168.1.30 --broker 192.168.1.100
  %(prog)s -c /path/to/cfp_config.json
  %(prog)s --node-id cfp-plant1 --host 10.0.0.50 --tls-ca-cert /etc/nisystem/ca.crt
        """
    )

    parser.add_argument('-c', '--config', help='Path to configuration file')
    parser.add_argument('--host', help='cFP IP address')
    parser.add_argument('--port', type=int, help='cFP Modbus port (default: 502)')
    parser.add_argument('--broker', help='MQTT broker address')
    parser.add_argument('--mqtt-port', type=int, help='MQTT port (default: 8883)')
    parser.add_argument('--mqtt-username', help='MQTT username')
    parser.add_argument('--mqtt-password', help='MQTT password')
    parser.add_argument('--tls-ca-cert', help='Path to TLS CA certificate')
    parser.add_argument('--node-id', help='Node ID for this cFP')
    parser.add_argument('--poll-interval', type=float, help='Scan rate in Hz')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Build overrides from CLI args
    overrides = {}
    if args.host:
        overrides['cfp_host'] = args.host
    if args.port:
        overrides['cfp_port'] = args.port
    if args.broker:
        overrides['mqtt_broker'] = args.broker
    if args.mqtt_port:
        overrides['mqtt_port'] = args.mqtt_port
    if args.mqtt_username:
        overrides['mqtt_username'] = args.mqtt_username
    if args.mqtt_password:
        overrides['mqtt_password'] = args.mqtt_password
    if args.tls_ca_cert:
        overrides['tls_ca_cert'] = args.tls_ca_cert
        overrides['tls_enabled'] = True
    if args.node_id:
        overrides['node_id'] = args.node_id
    if args.poll_interval:
        overrides['scan_rate_hz'] = args.poll_interval

    # Load config
    config = load_config(path=args.config, **overrides)

    # Create node
    node = CFPNodeV2(config)

    # Signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum} — shutting down")
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run
    logger.info(f"CFP Node V2 {__version__} starting: {config.node_id}")
    if not node.run():
        logger.error("Failed to start CFP node")
        sys.exit(1)

if __name__ == '__main__':
    main()
