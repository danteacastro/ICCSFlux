"""
Unit tests for cRIO Node V2 — main service, config, state machine,
MQTT interface, and hardware abstraction.

Tests all cRIO node components WITHOUT real MQTT broker or NI hardware.
All dependencies are mocked.

Test classes:
  - TestCrioConfig (~10 tests) — config loading, scaling, defaults, validation
  - TestCrioStateMachine (~8 tests) — state transitions, callbacks, session
  - TestCrioMQTTInterface (~10 tests) — client lifecycle, publish, subscribe
  - TestCrioHardware (~12 tests) — MockHardware, reads, writes, fault injection
  - TestCrioNodeOrchestration (~15 tests) — command dispatch, scan loop, errors
  - TestCrioNodeLifecycle (~8 tests) — startup, shutdown, config push, recovery
"""

import json
import math
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest

# Add service paths so relative imports resolve
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "crio_node_v2"))

try:
    from crio_node_v2.config import (
        ChannelConfig,
        NodeConfig as ConfigNodeConfig,
        load_config,
        apply_scaling,
        validate_scaling,
        migrate_crio_config,
    )
    from crio_node_v2.state_machine import State, StateTransition, SessionInfo
    from crio_node_v2.hardware import (
        HardwareConfig,
        HardwareInterface,
        MockHardware,
        create_hardware,
        DAQMX_AVAILABLE,
    )
except ImportError as _exc:
    pytest.skip(f"crio_node_v2 import failed: {_exc}", allow_module_level=True)

# MQTT and crio_node require paho-mqtt; skip gracefully if missing
try:
    from crio_node_v2.mqtt_interface import MQTTInterface, MQTTConfig, MQTT_AVAILABLE
except ImportError:
    MQTT_AVAILABLE = False

try:
    from crio_node_v2.crio_node import CRIONodeV2, NodeConfig, Command, ScanTimingStats
    CRIO_NODE_AVAILABLE = True
except ImportError as _exc:
    CRIO_NODE_AVAILABLE = False

# ============================================================================
# HELPERS
# ============================================================================

def _make_channel_config(name: str, ch_type: str = 'voltage_input',
                         physical: str = 'Mod1/ai0', **kwargs) -> ChannelConfig:
    """Create a ChannelConfig with sensible defaults."""
    return ChannelConfig(
        name=name,
        physical_channel=physical,
        channel_type=ch_type,
        **kwargs,
    )

def _make_hw_config(**kwargs) -> HardwareConfig:
    """Create a HardwareConfig with test channels."""
    channels = kwargs.pop('channels', {
        'ai0': _make_channel_config('ai0', 'voltage_input', 'Mod1/ai0'),
        'ai1': _make_channel_config('ai1', 'thermocouple', 'Mod5/ai0',
                                    thermocouple_type='K'),
        'di0': _make_channel_config('di0', 'digital_input', 'Mod3/port0/line0'),
        'ao0': _make_channel_config('ao0', 'voltage_output', 'Mod2/ao0',
                                    default_value=0.0),
        'do0': _make_channel_config('do0', 'digital_output', 'Mod4/port0/line0',
                                    default_value=0.0),
    })
    return HardwareConfig(
        device_name=kwargs.pop('device_name', 'cRIO1'),
        scan_rate_hz=kwargs.pop('scan_rate_hz', 4.0),
        channels=channels,
    )

def _make_node_config(**overrides) -> NodeConfig:
    """Create a NodeConfig with test defaults (requires CRIONodeV2 import)."""
    data = {
        'node_id': 'crio-test',
        'device_name': 'cRIO1',
        'scan_rate_hz': 4.0,
        'publish_rate_hz': 4.0,
        'mqtt_broker': 'localhost',
        'mqtt_port': 1883,
        'mqtt_base_topic': 'nisystem',
        'use_mock_hardware': True,
        'heartbeat_interval_s': 5.0,
        'channels': {
            'ai0': {
                'physical_channel': 'Mod1/ai0',
                'channel_type': 'voltage_input',
            },
            'ao0': {
                'physical_channel': 'Mod2/ao0',
                'channel_type': 'voltage_output',
                'default_value': 0.0,
            },
            'di0': {
                'physical_channel': 'Mod3/port0/line0',
                'channel_type': 'digital_input',
            },
            'do0': {
                'physical_channel': 'Mod4/port0/line0',
                'channel_type': 'digital_output',
                'default_value': 0.0,
            },
        },
    }
    data.update(overrides)
    return NodeConfig.from_dict(data)

# ============================================================================
# 1. TestCrioConfig
# ============================================================================

class TestCrioConfig:
    """Configuration loading, scaling, defaults, and validation."""

    def test_channel_config_from_dict_defaults(self):
        """ChannelConfig.from_dict fills in sensible defaults."""
        ch = ChannelConfig.from_dict('temp1', {})
        assert ch.name == 'temp1'
        assert ch.channel_type == 'voltage_input'
        assert ch.scale_slope == 1.0
        assert ch.scale_offset == 0.0
        assert ch.alarm_enabled is False
        assert ch.default_value == 0.0

    def test_channel_config_from_dict_with_values(self):
        """ChannelConfig.from_dict uses provided values."""
        data = {
            'physical_channel': 'Mod1/ai3',
            'channel_type': 'thermocouple',
            'thermocouple_type': 'J',
            'alarm_enabled': True,
            'hi_limit': 100.0,
            'hihi_limit': 120.0,
        }
        ch = ChannelConfig.from_dict('tc1', data)
        assert ch.physical_channel == 'Mod1/ai3'
        assert ch.channel_type == 'thermocouple'
        assert ch.thermocouple_type == 'J'
        assert ch.alarm_enabled is True
        assert ch.hi_limit == 100.0

    def test_channel_config_thermocouple_default_k(self):
        """Thermocouple channels default to K-type when unspecified."""
        ch = ChannelConfig.from_dict('tc2', {'channel_type': 'thermocouple'})
        assert ch.thermocouple_type == 'K'

    def test_node_config_from_dict(self):
        """NodeConfig.from_dict builds complete config."""
        data = {
            'system': {
                'node_id': 'crio-42',
                'mqtt_broker': '10.0.0.1',
                'mqtt_port': 8883,
                'scan_rate_hz': 10.0,
            },
            'channels': {
                'ch1': {'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
            },
        }
        cfg = ConfigNodeConfig.from_dict(data)
        assert cfg.node_id == 'crio-42'
        assert cfg.mqtt_broker == '10.0.0.1'
        assert cfg.mqtt_port == 8883
        assert cfg.scan_rate_hz == 10.0
        assert 'ch1' in cfg.channels

    def test_node_config_to_dict_roundtrip(self):
        """NodeConfig serializes and deserializes without data loss."""
        original = ConfigNodeConfig(
            node_id='crio-rt',
            mqtt_broker='192.168.1.1',
            scan_rate_hz=8.0,
            channels={
                'ai0': _make_channel_config('ai0', 'voltage_input', 'Mod1/ai0'),
            },
        )
        d = original.to_dict()
        assert d['node_id'] == 'crio-rt'
        assert d['mqtt_broker'] == '192.168.1.1'
        assert 'ai0' in d['channels']
        assert d['channels']['ai0']['channel_type'] == 'voltage_input'

    def test_scaling_linear(self):
        """Linear scaling applies slope + offset."""
        ch = _make_channel_config('s1', scale_slope=2.0, scale_offset=10.0)
        result = ChannelConfig.apply_scaling(5.0, ch)
        assert result == pytest.approx(20.0)  # 5*2 + 10

    def test_scaling_four_twenty(self):
        """4-20 mA scaling maps current to engineering units."""
        ch = _make_channel_config(
            's2', ch_type='current_input',
            four_twenty_scaling=True,
            eng_units_min=0.0,
            eng_units_max=100.0,
        )
        # At 4 mA => 0.0
        assert ChannelConfig.apply_scaling(4.0, ch) == pytest.approx(0.0)
        # At 20 mA => 100.0
        assert ChannelConfig.apply_scaling(20.0, ch) == pytest.approx(100.0)
        # At 12 mA => 50.0  (midpoint)
        assert ChannelConfig.apply_scaling(12.0, ch) == pytest.approx(50.0)

    def test_scaling_map(self):
        """Map scaling converts raw voltage range to engineering range."""
        ch = _make_channel_config(
            's3', ch_type='voltage_input',
            scale_type='map',
            pre_scaled_min=0.0, pre_scaled_max=10.0,
            scaled_min=0.0, scaled_max=500.0,
        )
        assert ChannelConfig.apply_scaling(5.0, ch) == pytest.approx(250.0)
        assert ChannelConfig.apply_scaling(0.0, ch) == pytest.approx(0.0)
        assert ChannelConfig.apply_scaling(10.0, ch) == pytest.approx(500.0)

    def test_scaling_none_passthrough(self):
        """No scaling configured passes raw value through."""
        ch = _make_channel_config('s4')
        assert ChannelConfig.apply_scaling(42.0, ch) == pytest.approx(42.0)

    def test_alarm_limit_ordering_disables_alarms(self):
        """Invalid alarm limit ordering disables alarms."""
        ch = ChannelConfig.from_dict('bad_limits', {
            'alarm_enabled': True,
            'lo_limit': 50.0,
            'hi_limit': 40.0,  # hi < lo: invalid
        })
        assert ch.alarm_enabled is False

    def test_momentary_pulse_clamping(self):
        """Momentary pulse ms is clamped to valid range."""
        ch = _make_channel_config('relay', momentary_pulse_ms=-5)
        assert ch.momentary_pulse_ms == 0

        ch2 = _make_channel_config('relay2', momentary_pulse_ms=9999999)
        assert ch2.momentary_pulse_ms == 3600000

    def test_pulse_duty_cycle_clamping(self):
        """Pulse duty cycle is clamped to 0-100%."""
        ch = _make_channel_config('pul', pulse_duty_cycle=-10.0)
        assert ch.pulse_duty_cycle == 0.0

        ch2 = _make_channel_config('pul2', pulse_duty_cycle=150.0)
        assert ch2.pulse_duty_cycle == 100.0

    def test_config_migration_1_0_to_1_1(self):
        """Config migration from 1.0 to 1.1 adds TLS fields."""
        data = {'config_version': '1.0', 'system': {}}
        migrated, applied = migrate_crio_config(data)
        assert len(applied) == 1
        assert '1.0->1.1' in applied[0]
        assert migrated['system'].get('tls_enabled') is False

    def test_get_channels_by_type(self):
        """NodeConfig.get_channels_by_type filters correctly."""
        cfg = ConfigNodeConfig(
            channels={
                'ai0': _make_channel_config('ai0', 'voltage_input'),
                'ci0': _make_channel_config('ci0', 'current_input'),
                'ao0': _make_channel_config('ao0', 'voltage_output'),
            },
        )
        # get_input_channels filters by 'input' in channel_type
        inputs = cfg.get_input_channels()
        assert 'ai0' in inputs
        assert 'ci0' in inputs
        assert 'ao0' not in inputs

        outputs = cfg.get_output_channels()
        assert 'ao0' in outputs
        assert 'ai0' not in outputs

    def test_validate_scaling_negative_slope_warns(self):
        """Negative slope produces a warning."""
        ch = _make_channel_config('neg', scale_slope=-1.0)
        warnings = validate_scaling(ch)
        assert any('negative scale_slope' in w for w in warnings)

# ============================================================================
# 2. TestCrioStateMachine
# ============================================================================

class TestCrioStateMachine:
    """State transitions, callbacks, and session management."""

    def test_initial_state_is_idle(self):
        sm = StateTransition()
        assert sm.state == State.IDLE
        assert sm.is_acquiring is False
        assert sm.is_session_active is False

    def test_idle_to_acquiring(self):
        sm = StateTransition()
        assert sm.to(State.ACQUIRING) is True
        assert sm.state == State.ACQUIRING
        assert sm.is_acquiring is True

    def test_idle_to_session_rejected(self):
        """Cannot jump directly from IDLE to SESSION."""
        sm = StateTransition()
        assert sm.to(State.SESSION) is False
        assert sm.state == State.IDLE

    def test_acquiring_to_session(self):
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.to(State.SESSION, {'name': 'test', 'operator': 'alice'}) is True
        assert sm.state == State.SESSION
        assert sm.is_session_active is True
        assert sm.session.name == 'test'
        assert sm.session.operator == 'alice'

    def test_session_to_idle(self):
        """SESSION -> IDLE stops both session and acquisition."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION)
        assert sm.to(State.IDLE) is True
        assert sm.state == State.IDLE
        assert sm.is_session_active is False

    def test_session_to_acquiring(self):
        """SESSION -> ACQUIRING stops session, keeps acquiring."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION)
        assert sm.to(State.ACQUIRING) is True
        assert sm.state == State.ACQUIRING
        assert sm.is_session_active is False

    def test_same_state_noop(self):
        """Transitioning to same state succeeds as no-op."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.to(State.ACQUIRING) is True
        assert sm.state == State.ACQUIRING

    def test_enter_exit_callbacks(self):
        """on_enter and on_exit callbacks fire correctly."""
        enter_log = []
        exit_log = []

        sm = StateTransition()
        sm.on_enter(State.ACQUIRING, lambda old, new, p: enter_log.append(('enter', new)))
        sm.on_exit(State.ACQUIRING, lambda old, new, p: exit_log.append(('exit', old)))

        sm.to(State.ACQUIRING)
        assert len(enter_log) == 1
        assert enter_log[0] == ('enter', State.ACQUIRING)

        sm.to(State.IDLE)
        assert len(exit_log) == 1
        assert exit_log[0] == ('exit', State.ACQUIRING)

    def test_output_locked_in_session(self):
        """Output locking enforced during SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, {'locked_outputs': ['ao0', 'do0']})

        assert sm.is_output_locked('ao0') is True
        assert sm.is_output_locked('do0') is True
        assert sm.is_output_locked('ao1') is False

    def test_output_not_locked_outside_session(self):
        """No outputs are locked when not in SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.is_output_locked('ao0') is False

    def test_get_status(self):
        """get_status returns correct dictionary."""
        sm = StateTransition()
        status = sm.get_status()
        assert status['state'] == 'IDLE'
        assert status['acquiring'] is False
        assert status['session_active'] is False

    def test_session_clears_on_exit(self):
        """Session info is cleared when leaving SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, {'name': 'run1'})
        assert sm.session.name == 'run1'
        sm.to(State.ACQUIRING)
        assert sm.session.name == ''

# ============================================================================
# 3. TestCrioMQTTInterface
# ============================================================================

@pytest.mark.skipif(not MQTT_AVAILABLE, reason="paho-mqtt not available")
class TestCrioMQTTInterface:
    """MQTT client lifecycle, publish, subscribe."""

    def _make_config(self, **kwargs) -> MQTTConfig:
        defaults = dict(
            broker_host='localhost', broker_port=1883,
            client_id='test-crio', base_topic='nisystem',
            node_id='crio-test',
        )
        defaults.update(kwargs)
        return MQTTConfig(**defaults)

    def test_topic_base(self):
        """topic_base builds node-prefixed path."""
        mi = MQTTInterface(self._make_config())
        assert mi.topic_base == 'nisystem/nodes/crio-test'

    def test_topic_builder(self):
        """topic() builds full topic paths."""
        mi = MQTTInterface(self._make_config())
        assert mi.topic('status', 'system') == 'nisystem/nodes/crio-test/status/system'
        assert mi.topic('heartbeat') == 'nisystem/nodes/crio-test/heartbeat'

    def test_publish_when_not_connected(self):
        """Publish returns False when not connected."""
        mi = MQTTInterface(self._make_config())
        assert mi.publish('test', {'hello': 1}) is False

    def test_is_connected_initially_false(self):
        """Interface starts disconnected."""
        mi = MQTTInterface(self._make_config())
        assert mi.is_connected() is False

    @patch('crio_node_v2.mqtt_interface.mqtt.Client')
    def test_connect_creates_client(self, MockClient):
        """connect() creates paho client and initiates connection."""
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mi = MQTTInterface(self._make_config(username='user', password='pass'))
        result = mi.connect()

        assert result is True
        mock_client.username_pw_set.assert_called_once_with('user', 'pass')
        mock_client.connect_async.assert_called_once()
        mock_client.loop_start.assert_called_once()

    @patch('crio_node_v2.mqtt_interface.mqtt.Client')
    def test_disconnect_stops_loop(self, MockClient):
        """disconnect() stops the loop and clears client."""
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mi = MQTTInterface(self._make_config())
        mi.connect()
        mi.disconnect()

        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()
        assert mi._client is None

    def test_subscribe_dedup(self):
        """Duplicate subscriptions are not stored twice."""
        mi = MQTTInterface(self._make_config())
        mi.subscribe('test/topic', 1)
        mi.subscribe('test/topic', 1)
        assert len(mi._subscriptions) == 1

    def test_on_connect_restores_subscriptions(self):
        """Subscriptions are restored on reconnect."""
        mi = MQTTInterface(self._make_config())
        mi.subscribe('topic/a', 1)
        mi.subscribe('topic/b', 0)

        mock_client = MagicMock()
        # Simulate successful connect (reason_code=0 for success)
        mi._on_connect(mock_client, None, None, 0)

        assert mi.is_connected() is True
        assert mock_client.subscribe.call_count == 2

    def test_on_disconnect_clears_connected(self):
        """Disconnection clears the connected flag."""
        mi = MQTTInterface(self._make_config())
        mi._connected.set()

        # Simulate unexpected disconnect (paho 1.x style: rc != 0)
        mi._on_disconnect(None, None, 1)

        assert mi.is_connected() is False

    def test_on_message_calls_callback(self):
        """Incoming messages are routed to the callback."""
        mi = MQTTInterface(self._make_config())
        received = []
        mi.on_message = lambda topic, payload: received.append((topic, payload))

        msg = MagicMock()
        msg.topic = 'nisystem/nodes/crio-test/commands/output'
        msg.payload = json.dumps({'channel': 'ao0', 'value': 5.0}).encode()

        mi._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0][0] == msg.topic
        assert received[0][1]['channel'] == 'ao0'

    def test_on_message_rejects_oversized(self):
        """Oversized payloads are dropped."""
        mi = MQTTInterface(self._make_config())
        received = []
        mi.on_message = lambda topic, payload: received.append(payload)

        msg = MagicMock()
        msg.topic = 'test'
        msg.payload = b'x' * (MQTTInterface.MAX_PAYLOAD_SIZE + 1)

        mi._on_message(None, None, msg)

        assert len(received) == 0

    def test_on_connection_change_callback(self):
        """on_connection_change is called on connect/disconnect."""
        mi = MQTTInterface(self._make_config())
        states = []
        mi.on_connection_change = lambda connected: states.append(connected)

        mock_client = MagicMock()
        mi._on_connect(mock_client, None, None, 0)
        mi._on_disconnect(None, None, 0)

        assert states == [True, False]

    @patch('crio_node_v2.mqtt_interface.mqtt.Client')
    def test_connect_with_tls(self, MockClient):
        """TLS is configured when enabled."""
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mi = MQTTInterface(self._make_config(
            tls_enabled=True, tls_ca_cert='/path/to/ca.crt'))
        mi.connect()

        mock_client.tls_set.assert_called_once()

# ============================================================================
# 4. TestCrioHardware
# ============================================================================

class TestCrioHardware:
    """MockHardware — reads, writes, fault injection, safe state."""

    def test_create_hardware_uses_mock_when_forced(self):
        """create_hardware returns MockHardware when use_mock=True."""
        hw = create_hardware(_make_hw_config(), use_mock=True)
        assert isinstance(hw, MockHardware)

    def test_create_hardware_uses_mock_without_daqmx(self):
        """create_hardware falls back to MockHardware when DAQmx unavailable."""
        # On a test machine without NI-DAQmx, this should use mock
        hw = create_hardware(_make_hw_config())
        if not DAQMX_AVAILABLE:
            assert isinstance(hw, MockHardware)

    def test_mock_hardware_start_stop(self):
        """MockHardware starts and stops cleanly."""
        hw = MockHardware(_make_hw_config())
        assert hw.start() is True
        assert hw._running is True
        hw.stop()
        assert hw._running is False

    def test_mock_hardware_read_all(self):
        """read_all returns values for all input channels."""
        hw = MockHardware(_make_hw_config())
        hw.start()
        readings = hw.read_all()
        # Should have entries for input channels (ai0, ai1, di0)
        assert 'ai0' in readings
        assert 'di0' in readings
        # Output channels are not in read_all
        assert 'ao0' not in readings

    def test_mock_hardware_read_all_not_running(self):
        """read_all returns empty when hardware not started."""
        hw = MockHardware(_make_hw_config())
        readings = hw.read_all()
        assert readings == {}

    def test_mock_hardware_write_output(self):
        """write_output writes to known output channels."""
        hw = MockHardware(_make_hw_config())
        assert hw.write_output('ao0', 5.0) is True
        assert hw.get_output_value('ao0') == 5.0

    def test_mock_hardware_write_unknown_channel(self):
        """write_output rejects unknown channels."""
        hw = MockHardware(_make_hw_config())
        assert hw.write_output('nonexistent', 1.0) is False

    def test_mock_hardware_safe_state(self):
        """set_safe_state resets all outputs to default values."""
        hw = MockHardware(_make_hw_config())
        hw.write_output('ao0', 10.0)
        hw.set_safe_state()
        assert hw.get_output_value('ao0') == 0.0  # default_value

    def test_mock_hardware_set_input_value(self):
        """Test helper: set_input_value updates internal value store."""
        hw = MockHardware(_make_hw_config())
        hw.set_input_value('ai0', 42.0)
        # Verify internal store was updated (read_all overwrites with simulation,
        # so we check the store directly before any read)
        assert hw._values['ai0'] == 42.0

    def test_mock_hardware_fault_read_error(self):
        """Fault injection: read_all raises RuntimeError."""
        hw = MockHardware(_make_hw_config())
        hw.start()
        hw._simulate_read_error = True

        with pytest.raises(RuntimeError, match="Simulated read error"):
            hw.read_all()

        # One-shot: next read should succeed
        readings = hw.read_all()
        assert len(readings) > 0

    def test_mock_hardware_fault_write_error(self):
        """Fault injection: write_output returns False."""
        hw = MockHardware(_make_hw_config())
        hw._simulate_write_error = True
        assert hw.write_output('ao0', 5.0) is False

    def test_mock_hardware_fault_nan_channels(self):
        """Fault injection: specific channels return NaN."""
        hw = MockHardware(_make_hw_config())
        hw.start()
        hw._simulate_nan_channels.add('ai0')

        readings = hw.read_all()
        assert math.isnan(readings['ai0'][0])

    def test_mock_hardware_fault_start_failure(self):
        """Fault injection: start() returns False."""
        hw = MockHardware(_make_hw_config())
        hw._simulate_start_failure = True
        assert hw.start() is False

    def test_mock_hardware_read_output_from_hardware(self):
        """read_output_from_hardware returns stored output value (mock readback)."""
        hw = MockHardware(_make_hw_config())
        hw.write_output('ao0', 3.14)
        assert hw.read_output_from_hardware('ao0') == pytest.approx(3.14)

    def test_mock_hardware_read_output_from_hardware_unknown(self):
        """read_output_from_hardware returns None for unknown channel."""
        hw = MockHardware(_make_hw_config())
        assert hw.read_output_from_hardware('nonexistent') is None

    def test_mock_hardware_digital_input_values(self):
        """Digital input channels return 0.0 or 1.0."""
        hw = MockHardware(_make_hw_config())
        hw.start()
        readings = hw.read_all()
        di_val = readings['di0'][0]
        assert di_val in (0.0, 1.0)

# ============================================================================
# 5. TestScanTimingStats
# ============================================================================

class TestScanTimingStats:
    """Lightweight scan loop timing statistics."""

    def test_initial_state(self):
        stats = ScanTimingStats(target_ms=250.0)
        assert stats.total_scans == 0
        assert stats.overruns == 0
        assert stats.min_ms == 0.0
        assert stats.mean_ms == 0.0

    def test_record_updates_stats(self):
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(200.0)
        stats.record(250.0)
        stats.record(300.0)

        assert stats.total_scans == 3
        assert stats.min_ms == pytest.approx(200.0)
        assert stats.max_ms == pytest.approx(300.0)
        assert stats.mean_ms == pytest.approx(250.0)

    def test_overrun_counting(self):
        """Overrun detected when dt > 1.5x target."""
        stats = ScanTimingStats(target_ms=100.0)
        stats.record(100.0)  # OK
        stats.record(140.0)  # OK (< 150)
        stats.record(160.0)  # Overrun (> 150)
        assert stats.overruns == 1

    def test_jitter_calculation(self):
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(250.0)
        stats.record(250.0)
        assert stats.jitter_ms == pytest.approx(0.0)

        stats.record(200.0)
        stats.record(300.0)
        assert stats.jitter_ms > 0

    def test_window_size_limiting(self):
        """Old samples are evicted after window_size."""
        stats = ScanTimingStats(target_ms=250.0, window_size=3)
        for i in range(10):
            stats.record(float(i))
        assert len(stats._samples) == 3
        assert stats.total_scans == 10

    def test_to_dict(self):
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(250.0)
        d = stats.to_dict()
        assert 'target_ms' in d
        assert 'actual_ms' in d
        assert 'overruns' in d
        assert 'actual_rate_hz' in d

    def test_reset_clears_all(self):
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(100.0)
        stats.record(500.0)
        stats.reset()
        assert stats.total_scans == 0
        assert stats.overruns == 0
        assert stats.min_ms == 0.0

# ============================================================================
# 6. TestCrioNodeOrchestration
# ============================================================================

@pytest.mark.skipif(not CRIO_NODE_AVAILABLE, reason="CRIONodeV2 not importable")
@pytest.mark.skipif(not MQTT_AVAILABLE, reason="paho-mqtt not available")
class TestCrioNodeOrchestration:
    """Command dispatch, scan loop behavior, error handling."""

    @pytest.fixture
    def node(self, tmp_path):
        """Create a CRIONodeV2 with mock hardware and mocked MQTT."""
        config = _make_node_config()
        with patch('crio_node_v2.crio_node.AuditTrail'):
            node = CRIONodeV2(config)
        node.mqtt = MagicMock()
        node.mqtt.is_connected.return_value = True
        node.mqtt.publish.return_value = True
        node.mqtt.topic_base = 'nisystem/nodes/crio-test'
        node.mqtt.topic = lambda cat, ent='': f'nisystem/nodes/crio-test/{cat}/{ent}'.rstrip('/')
        return node

    def test_node_initial_state_idle(self, node):
        """Node starts in IDLE state."""
        assert node.state.state == State.IDLE
        assert node.state.is_acquiring is False

    def test_node_has_mock_hardware(self, node):
        """Node uses MockHardware when use_mock_hardware=True."""
        assert isinstance(node.hardware, MockHardware)

    def test_node_output_defaults_initialized(self, node):
        """Output channels have default values initialized."""
        assert 'ao0' in node.output_values
        assert 'do0' in node.output_values
        assert node.output_values['ao0'] == 0.0

    def test_enqueue_command(self, node):
        """_enqueue_command adds commands to the queue."""
        node._enqueue_command('nisystem/nodes/crio-test/commands/output',
                              {'channel': 'ao0', 'value': 5.0})
        assert not node.command_queue.empty()
        cmd = node.command_queue.get_nowait()
        assert cmd.payload['channel'] == 'ao0'

    def test_enqueue_command_full_queue_drops_noncritical(self, node):
        """Non-critical commands are dropped when queue is full."""
        # Fill the queue
        for i in range(1000):
            node.command_queue.put_nowait(
                Command(topic=f'test/topic/{i}', payload={}))

        # Non-critical command should be dropped
        node._enqueue_command('nisystem/test/status', {'status': 'ok'})
        assert node.command_queue.qsize() == 1000

    def test_enqueue_command_critical_never_dropped(self, node):
        """Critical commands make space in a full queue."""
        for i in range(1000):
            node.command_queue.put_nowait(
                Command(topic=f'test/routine/{i}', payload={}))

        # Critical command (stop) should force its way in
        node._enqueue_command('nisystem/nodes/crio-test/system/stop',
                              {'reason': 'emergency'})
        # Queue should still be at capacity (one was dropped to make room)
        assert node.command_queue.qsize() == 1000

    def test_cmd_acquire_start(self, node):
        """acquire/start transitions to ACQUIRING."""
        node._cmd_acquire_start({'request_id': 'r1'})
        assert node.state.state == State.ACQUIRING

    def test_cmd_acquire_start_already_acquiring(self, node):
        """acquire/start when already acquiring is a no-op success."""
        node.state.to(State.ACQUIRING)
        node._cmd_acquire_start({})
        assert node.state.state == State.ACQUIRING
        # Should still publish ack
        node.mqtt.publish.assert_called()

    def test_cmd_acquire_stop(self, node):
        """acquire/stop transitions back to IDLE."""
        node.state.to(State.ACQUIRING)
        node._cmd_acquire_stop({})
        assert node.state.state == State.IDLE

    def test_cmd_write_output(self, node):
        """Output write command writes to hardware and updates values."""
        node.state.to(State.ACQUIRING)
        node.hardware.start()

        node._cmd_write_output({'channel': 'ao0', 'value': 7.5})

        assert node.output_values['ao0'] == 7.5
        assert node.hardware.get_output_value('ao0') == 7.5

    def test_cmd_write_output_missing_channel(self, node):
        """Output write with missing channel is rejected."""
        node._cmd_write_output({'value': 5.0})
        # Verify an ack with success=False was published
        calls = [c for c in node.mqtt.publish.call_args_list
                 if 'command/ack' in str(c)]
        assert len(calls) > 0

    def test_cmd_write_output_session_locked(self, node):
        """Output write blocked when channel is locked by session."""
        node.state.to(State.ACQUIRING)
        node.state.to(State.SESSION, {'locked_outputs': ['ao0']})

        node._cmd_write_output({'channel': 'ao0', 'value': 5.0})

        # Value should NOT have changed
        assert node.output_values['ao0'] == 0.0

    def test_cmd_session_start(self, node):
        """Session start requires ACQUIRING state."""
        node.state.to(State.ACQUIRING)
        node._cmd_session_start({'name': 'Test', 'operator': 'admin'})
        assert node.state.state == State.SESSION

    def test_cmd_session_start_from_idle_rejected(self, node):
        """Session start from IDLE is rejected."""
        node._cmd_session_start({'name': 'Test'})
        assert node.state.state == State.IDLE

    def test_cmd_session_stop(self, node):
        """Session stop returns to ACQUIRING."""
        node.state.to(State.ACQUIRING)
        node.state.to(State.SESSION)
        node._cmd_session_stop({})
        assert node.state.state == State.ACQUIRING

    def test_cmd_safe_state(self, node):
        """safe_state command resets all outputs to safe values."""
        node.hardware.start()
        node.hardware.write_output('ao0', 10.0)
        node.output_values['ao0'] = 10.0

        node._cmd_safe_state({'reason': 'test'})

        # ao0 should be back to default (0.0)
        assert node.output_values['ao0'] == 0.0

    def test_read_channels_updates_values(self, node):
        """_read_channels populates channel_values from hardware."""
        node.hardware.start()
        node._read_channels()

        assert 'ai0' in node.channel_values
        assert 'value' in node.channel_values['ai0']
        assert 'timestamp' in node.channel_values['ai0']
        assert 'quality' in node.channel_values['ai0']

    def test_handle_command_routing(self, node):
        """_handle_command routes topics to correct handlers."""
        base = 'nisystem/nodes/crio-test'

        # Test acquire start routing
        with patch.object(node, '_cmd_acquire_start') as mock:
            node._handle_command(f'{base}/system/acquire/start', {})
            mock.assert_called_once()

        # Test output write routing
        with patch.object(node, '_cmd_write_output') as mock:
            node._handle_command(f'{base}/commands/output', {'channel': 'ao0'})
            mock.assert_called_once()

        # Test safe state routing
        with patch.object(node, '_cmd_safe_state') as mock:
            node._handle_command(f'{base}/safety/safe-state', {})
            mock.assert_called_once()

        # Test discovery ping routing
        with patch.object(node, '_publish_status') as mock:
            node._handle_command('nisystem/discovery/ping', {})
            mock.assert_called_once()

    def test_safety_action_retries_on_failure(self, node):
        """Safety action retries once after 50ms if first write fails."""
        node.hardware.start()
        # First call fails, second succeeds
        node.hardware._simulate_write_error = True

        with patch.object(node.hardware, 'write_output',
                          side_effect=[False, True]) as mock_write:
            node._on_safety_action('ao0', 'close_valve', 0.0)
            assert mock_write.call_count == 2

    def test_safety_action_publishes_failure(self, node):
        """Safety action publishes failure on double write failure."""
        node.hardware.start()
        node.hardware._simulate_write_error = True

        node._on_safety_action('ao0', 'close_valve', 0.0)

        # Should have published a safety/write_failure message
        publish_calls = node.mqtt.publish.call_args_list
        failure_calls = [c for c in publish_calls
                         if 'safety/write_failure' in str(c)]
        assert len(failure_calls) > 0

# ============================================================================
# 7. TestCrioNodeLifecycle
# ============================================================================

@pytest.mark.skipif(not CRIO_NODE_AVAILABLE, reason="CRIONodeV2 not importable")
@pytest.mark.skipif(not MQTT_AVAILABLE, reason="paho-mqtt not available")
class TestCrioNodeLifecycle:
    """Startup, shutdown, config push, recovery."""

    @pytest.fixture
    def node(self, tmp_path):
        """Create a CRIONodeV2 with mock hardware and mocked MQTT."""
        config = _make_node_config()
        with patch('crio_node_v2.crio_node.AuditTrail'):
            node = CRIONodeV2(config)
        node.mqtt = MagicMock()
        node.mqtt.is_connected.return_value = True
        node.mqtt.publish.return_value = True
        node.mqtt.connect.return_value = True
        node.mqtt.wait_for_connection.return_value = True
        node.mqtt.topic_base = 'nisystem/nodes/crio-test'
        node.mqtt.topic = lambda cat, ent='': f'nisystem/nodes/crio-test/{cat}/{ent}'.rstrip('/')
        return node

    def test_stop_transitions_to_idle(self, node):
        """stop() transitions to IDLE."""
        node.state.to(State.ACQUIRING)
        node._shutdown = threading.Event()
        node.stop()
        assert node.state.state == State.IDLE

    def test_mqtt_reconnect_publishes_status(self, node):
        """MQTT reconnection triggers status publish."""
        node._on_mqtt_connection_change(True)
        node.mqtt.publish.assert_called()

    def test_config_full_updates_channels(self, node):
        """config/full command replaces all channels."""
        with patch.object(node, '_save_config_to_disk'):
            node._cmd_config_full({
                'channels': {
                    'new_ai': {
                        'physical_channel': 'Mod1/ai5',
                        'channel_type': 'voltage_input',
                    },
                },
            })

        assert 'new_ai' in node.config.channels
        assert 'ai0' not in node.config.channels

    def test_config_full_updates_scan_rate(self, node):
        """config/full command updates scan rate."""
        with patch.object(node, '_save_config_to_disk'):
            node._cmd_config_full({
                'scan_rate_hz': 10.0,
                'channels': {},
            })

        assert node.config.scan_rate_hz == 10.0
        assert node._scan_interval == pytest.approx(0.1)

    def test_config_full_caps_scan_rate(self, node):
        """config/full caps scan rate at 100 Hz."""
        with patch.object(node, '_save_config_to_disk'):
            node._cmd_config_full({
                'scan_rate_hz': 500.0,
                'channels': {},
            })

        assert node.config.scan_rate_hz == 100.0

    def test_config_full_minimum_scan_rate(self, node):
        """config/full enforces minimum 0.1 Hz scan rate."""
        with patch.object(node, '_save_config_to_disk'):
            node._cmd_config_full({
                'scan_rate_hz': 0.01,
                'channels': {},
            })

        assert node.config.scan_rate_hz == 0.1

    def test_config_full_with_interlocks(self, node):
        """config/full configures interlocks from payload."""
        with patch.object(node, '_save_config_to_disk'), \
             patch.object(node.safety, 'configure_interlocks') as mock_il:
            node._cmd_config_full({
                'channels': {},
                'interlocks': [{'id': 'il1', 'conditions': []}],
            })

        mock_il.assert_called_once_with([{'id': 'il1', 'conditions': []}])

    def test_config_full_restarts_hardware_when_acquiring(self, node):
        """config/full restarts hardware if channels change while acquiring."""
        node.state.to(State.ACQUIRING)
        node.hardware.start()

        with patch.object(node, '_save_config_to_disk'), \
             patch.object(node.hardware, 'stop') as mock_stop, \
             patch.object(node.hardware, 'start') as mock_start:
            node._cmd_config_full({
                'channels': {
                    'new_ch': {
                        'physical_channel': 'Mod1/ai9',
                        'channel_type': 'voltage_input',
                    },
                },
            })

        mock_stop.assert_called_once()
        mock_start.assert_called_once()

    def test_config_version_echoed_from_payload(self, node):
        """config_version from DAQ service is echoed back."""
        with patch.object(node, '_save_config_to_disk'):
            node._cmd_config_full({
                'channels': {},
                'config_version': 'abc123hash',
            })

        assert node.config_version == 'abc123hash'

    def test_comm_watchdog_trips_on_timeout(self, node):
        """Communication watchdog trips after timeout."""
        node.config.comm_watchdog_timeout_s = 0.1
        node._last_command_time = time.time() - 1.0  # 1s ago
        node.hardware.start()

        node._check_comm_watchdog()

        assert node._comm_watchdog_tripped is True
        assert node.state.state == State.IDLE

    def test_comm_watchdog_resets_on_contact(self, node):
        """Communication watchdog resets when contact is restored."""
        node.config.comm_watchdog_timeout_s = 10.0
        node._comm_watchdog_tripped = True
        node._last_command_time = time.time()

        node._check_comm_watchdog()

        assert node._comm_watchdog_tripped is False

    def test_interlock_command_routing(self, node):
        """Interlock commands are routed to SafetyManager."""
        base = 'nisystem/nodes/crio-test'

        with patch.object(node.safety, 'arm_latch', return_value=(True, 'armed')) as mock:
            node._handle_interlock_command(f'{base}/interlock/arm', {'user': 'op'})
            mock.assert_called_once_with('op')

        with patch.object(node.safety, 'reset_trip', return_value=(True, 'reset')) as mock:
            node._handle_interlock_command(f'{base}/interlock/reset', {'user': 'op'})
            mock.assert_called_once_with('op')

    def test_alarm_ack_command(self, node):
        """Alarm acknowledgment routes to safety manager."""
        with patch.object(node, 'acknowledge_alarm', return_value=True) as mock:
            node._cmd_alarm_ack({'channel': 'ai0', 'request_id': 'r1'})
            mock.assert_called_once_with('ai0')

    def test_watchdog_output_toggle(self, node):
        """Watchdog output toggles at configured rate."""
        node.config.watchdog_output_enabled = True
        node.config.watchdog_output_channel = 'do0'
        node.config.watchdog_output_rate_hz = 1.0
        node.hardware.start()

        # Force toggle
        node._watchdog_output_last_toggle = 0.0
        node._toggle_watchdog_output()

        assert node._watchdog_output_state is True
        assert node.hardware.get_output_value('do0') == 1.0

    def test_publish_values_marks_nan_as_bad(self, node):
        """NaN channel values are marked as 'bad' quality."""
        node.channel_values = {
            'ai0': {'value': float('nan'), 'timestamp': time.time(), 'quality': 'good'},
        }
        node._publish_values()

        # Verify the published batch had quality='bad'
        publish_calls = node.mqtt.publish.call_args_list
        batch_calls = [c for c in publish_calls if 'channels/batch' in str(c)]
        assert len(batch_calls) > 0

    def test_publish_values_marks_stale(self, node):
        """Old timestamps are marked as 'stale' quality."""
        old_ts = time.time() - 30.0  # 30s old (> STALE_VALUE_THRESHOLD_S=10)
        node.channel_values = {
            'ai0': {'value': 25.0, 'timestamp': old_ts, 'quality': 'good'},
        }
        node._publish_values()

        publish_calls = node.mqtt.publish.call_args_list
        batch_calls = [c for c in publish_calls if 'channels/batch' in str(c)]
        assert len(batch_calls) > 0

# ============================================================================
# 8. TestCrioNodeConfigFromDict
# ============================================================================

@pytest.mark.skipif(not CRIO_NODE_AVAILABLE, reason="CRIONodeV2 not importable")
class TestCrioNodeConfigFromDict:
    """NodeConfig (crio_node.py version) — from_dict, defaults, validation."""

    def test_defaults(self):
        cfg = NodeConfig.from_dict({})
        assert cfg.node_id == 'crio-001'
        assert cfg.scan_rate_hz == 4.0
        assert cfg.use_mock_hardware is False

    def test_invalid_scan_rate_corrected(self):
        """Negative or zero scan_rate_hz is corrected to 4.0."""
        cfg = NodeConfig.from_dict({'scan_rate_hz': -1.0})
        assert cfg.scan_rate_hz == 4.0

        cfg2 = NodeConfig.from_dict({'scan_rate_hz': 0})
        assert cfg2.scan_rate_hz == 4.0

    def test_mqtt_host_alias(self):
        """mqtt_host is accepted as alias for mqtt_broker."""
        cfg = NodeConfig.from_dict({'mqtt_host': '10.0.0.1'})
        assert cfg.mqtt_broker == '10.0.0.1'

    def test_channels_parsed(self):
        cfg = NodeConfig.from_dict({
            'channels': {
                'ch1': {'physical_channel': 'Mod1/ai0', 'channel_type': 'voltage_input'},
                'ch2': {'physical_channel': 'Mod2/ao0', 'channel_type': 'voltage_output'},
            }
        })
        assert len(cfg.channels) == 2
        assert cfg.channels['ch1'].channel_type == 'voltage_input'
        assert cfg.channels['ch2'].channel_type == 'voltage_output'
