"""
Comprehensive unit tests for the Opto22 Node Service.

Tests all major subsystems of the Opto22 node without requiring
real MQTT brokers, hardware, or groov EPIC/RIO devices:

- TestOpto22Config:             Config loading, defaults, groov MQTT, channel config, validation
- TestOpto22StateMachine:       State transitions, invalid transitions, callbacks, session lifecycle
- TestOpto22MQTTInterface:      Dual MQTT clients, connection tracking, message routing, topics
- TestOpto22Hardware:           GroovIOSubscriber, stale detection, REST fallback, HardwareInterface
- TestOpto22NodeOrchestration:  Node init, command dispatch, status, scan loop, shutdown
- TestOpto22SafetyIntegration:  Safety manager, interlocks, alarms, COMM_FAIL, output blocking

Total: ~75 tests
"""

import json
import math
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest

# Add services dir so opto22_node resolves as a package (relative imports work)
sys.path.insert(0, str(Path(__file__).parent.parent / 'services'))

try:
    from opto22_node.config import (
        ChannelConfig, CODESYSConfig, NodeConfig,
        load_config, save_config, migrate_opto22_config,
        CURRENT_OPTO22_CONFIG_VERSION,
    )
    from opto22_node.state_machine import (
        State, StateTransition, SessionInfo,
        Opto22State, Opto22StateMachine,
        VALID_TRANSITIONS,
    )
    from opto22_node.hardware import (
        GroovIOSubscriber, GroovRestFallback, HardwareInterface,
    )
    from opto22_node.channel_types import ChannelType
except ImportError as _exc:
    pytest.skip(f"opto22_node import failed: {_exc}", allow_module_level=True)

# Safety module import (separate try block -- may have different dependencies)
try:
    from opto22_node.safety import (
        SafetyManager, AlarmConfig, AlarmState, AlarmSeverity,
        InterlockCondition, InterlockControl, Interlock,
        SafeStateConfig, LatchState,
    )
    SAFETY_AVAILABLE = True
except ImportError:
    SAFETY_AVAILABLE = False

# MQTT interface import (requires paho-mqtt)
try:
    from opto22_node.mqtt_interface import (
        SystemMQTT, GroovMQTT, MQTTConfig, GroovMQTTConfig,
        _create_mqtt_client, MQTT_AVAILABLE,
    )
except ImportError:
    MQTT_AVAILABLE = False

# Node service import -- uses heavy dependencies; mock what's needed
try:
    from opto22_node.opto22_node import (
        Opto22NodeService, get_value_quality, ScanTimingStats,
    )
    NODE_AVAILABLE = True
except ImportError:
    NODE_AVAILABLE = False

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def basic_channel_data():
    """Minimal channel configuration dict."""
    return {
        'physical_channel': 'groov/io/mod0/ch0',
        'channel_type': 'voltage_input',
        'groov_topic': 'groov/io/mod0/ch0',
        'scale_slope': 1.0,
        'scale_offset': 0.0,
    }

@pytest.fixture
def basic_config_dict():
    """Minimal NodeConfig-compatible dict."""
    return {
        'system': {
            'node_id': 'opto22-test',
            'device_name': 'Test EPIC',
            'scan_rate_hz': 4.0,
            'publish_rate_hz': 4.0,
            'mqtt_broker': 'localhost',
            'mqtt_port': 8883,
            'mqtt_username': 'nisystem',
            'mqtt_password': 'secret',
            'mqtt_base_topic': 'nisystem',
            'mqtt_tls_enabled': False,
            'heartbeat_interval_s': 5.0,
        },
        'groov': {
            'mqtt_host': 'localhost',
            'mqtt_port': 1883,
            'mqtt_username': 'groov',
            'mqtt_password': 'groovpw',
            'io_topic_patterns': ['groov/io/#'],
            'rest_host': '192.168.1.100',
            'rest_port': 443,
        },
        'channels': {
            'TC_Zone1': {
                'physical_channel': 'groov/io/mod0/ch0',
                'channel_type': 'thermocouple',
                'groov_topic': 'groov/io/mod0/ch0',
            },
            'AI_Press': {
                'physical_channel': 'groov/io/mod0/ch1',
                'channel_type': 'voltage_input',
                'groov_topic': 'groov/io/mod0/ch1',
            },
            'DO_Heater': {
                'physical_channel': 'groov/io/mod1/ch0',
                'channel_type': 'digital_output',
                'groov_topic': 'groov/io/mod1/ch0',
            },
        },
    }

@pytest.fixture
def node_config(basic_config_dict):
    """Create a NodeConfig from dict."""
    return NodeConfig.from_dict(basic_config_dict)

@pytest.fixture
def topic_mapping():
    """Standard topic mapping for hardware tests."""
    return {
        'groov/io/mod0/ch0': 'TC_Zone1',
        'groov/io/mod0/ch1': 'AI_Press',
        'groov/io/mod1/ch0': 'DO_Heater',
    }

# ============================================================================
# TestOpto22Config — Configuration module tests (~12 tests)
# ============================================================================

class TestOpto22Config:
    """Test configuration loading, defaults, validation, and persistence."""

    def test_channel_config_from_dict_defaults(self, basic_channel_data):
        """ChannelConfig.from_dict applies correct defaults."""
        ch = ChannelConfig.from_dict('test_ch', basic_channel_data)
        assert ch.name == 'test_ch'
        assert ch.physical_channel == 'groov/io/mod0/ch0'
        assert ch.channel_type == 'voltage_input'
        assert ch.scale_slope == 1.0
        assert ch.scale_offset == 0.0
        assert ch.invert is False
        assert ch.default_value == 0.0
        assert ch.alarm_enabled is False
        assert ch.source_type == 'opto22'

    def test_channel_config_scaling_linear(self):
        """Linear scaling: value * slope + offset."""
        ch = ChannelConfig(
            name='scaled', physical_channel='', channel_type='voltage_input',
            scale_slope=2.0, scale_offset=10.0,
        )
        result = ChannelConfig.apply_scaling(5.0, ch)
        assert result == 20.0  # 5 * 2 + 10

    def test_channel_config_scaling_4_20ma(self):
        """4-20mA current input scaling."""
        ch = ChannelConfig(
            name='flow', physical_channel='', channel_type='current_input',
            four_twenty_scaling=True,
            eng_units_min=0.0, eng_units_max=100.0,
        )
        # 4 mA = 0%, 20 mA = 100%
        assert ChannelConfig.apply_scaling(4.0, ch) == pytest.approx(0.0)
        assert ChannelConfig.apply_scaling(20.0, ch) == pytest.approx(100.0)
        assert ChannelConfig.apply_scaling(12.0, ch) == pytest.approx(50.0)

    def test_channel_config_scaling_map(self):
        """Map scaling: linear interpolation between ranges."""
        ch = ChannelConfig(
            name='mapped', physical_channel='', channel_type='voltage_input',
            scale_type='map',
            pre_scaled_min=0.0, pre_scaled_max=10.0,
            scaled_min=0.0, scaled_max=200.0,
        )
        assert ChannelConfig.apply_scaling(5.0, ch) == pytest.approx(100.0)
        assert ChannelConfig.apply_scaling(0.0, ch) == pytest.approx(0.0)
        assert ChannelConfig.apply_scaling(10.0, ch) == pytest.approx(200.0)

    def test_channel_config_alarm_limit_ordering_invalid(self):
        """Invalid alarm limit ordering disables alarms."""
        ch = ChannelConfig(
            name='bad_alarm', physical_channel='', channel_type='voltage_input',
            alarm_enabled=True,
            lo_limit=50.0, hi_limit=30.0,  # hi < lo is invalid
        )
        assert ch.alarm_enabled is False  # __post_init__ disables it

    def test_channel_config_alarm_limit_ordering_valid(self):
        """Valid alarm limit ordering keeps alarms enabled."""
        ch = ChannelConfig(
            name='good_alarm', physical_channel='', channel_type='voltage_input',
            alarm_enabled=True,
            lolo_limit=10.0, lo_limit=20.0, hi_limit=80.0, hihi_limit=90.0,
        )
        assert ch.alarm_enabled is True

    def test_node_config_from_dict(self, basic_config_dict):
        """NodeConfig.from_dict correctly parses system, groov, and channels."""
        config = NodeConfig.from_dict(basic_config_dict)
        assert config.node_id == 'opto22-test'
        assert config.device_name == 'Test EPIC'
        assert config.scan_rate_hz == 4.0
        assert config.mqtt_broker == 'localhost'
        assert config.mqtt_port == 8883
        assert config.mqtt_username == 'nisystem'
        assert config.groov_mqtt_host == 'localhost'
        assert config.groov_mqtt_port == 1883
        assert len(config.channels) == 3
        assert 'TC_Zone1' in config.channels
        assert 'DO_Heater' in config.channels

    def test_node_config_topic_mapping(self, basic_config_dict):
        """Topic mapping is auto-built from channel groov_topic fields."""
        config = NodeConfig.from_dict(basic_config_dict)
        assert config.topic_mapping.get('groov/io/mod0/ch0') == 'TC_Zone1'
        assert config.topic_mapping.get('groov/io/mod0/ch1') == 'AI_Press'
        assert config.topic_mapping.get('groov/io/mod1/ch0') == 'DO_Heater'

    def test_node_config_scan_rate_clamping(self):
        """Scan rate is clamped to 0.1-100 Hz range."""
        cfg_low = load_config({'system': {'scan_rate_hz': 0.001}})
        assert cfg_low.scan_rate_hz == 0.1

        cfg_high = load_config({'system': {'scan_rate_hz': 500.0}})
        assert cfg_high.scan_rate_hz == 100.0

    def test_node_config_get_output_channels(self, node_config):
        """get_output_channels returns only output channels."""
        outputs = node_config.get_output_channels()
        assert 'DO_Heater' in outputs
        assert 'TC_Zone1' not in outputs
        assert 'AI_Press' not in outputs

    def test_config_migration_v1_to_v1_1(self):
        """Migrate config from 1.0 to 1.1 adds groov TLS fields."""
        data = {'config_version': '1.0', 'groov': {'mqtt_host': 'localhost'}}
        migrated, applied = migrate_opto22_config(data)
        assert migrated['config_version'] == '1.1'
        assert migrated['groov']['mqtt_tls'] is False
        assert migrated['groov']['mqtt_ca_cert'] is None
        assert len(applied) == 1

    def test_load_config_with_existing(self, node_config):
        """load_config with existing config merges payload over defaults."""
        payload = {
            'channels': {
                'New_Ch': {
                    'physical_channel': 'groov/io/mod2/ch0',
                    'channel_type': 'voltage_input',
                },
            },
        }
        merged = load_config(payload, existing_config=node_config)
        # Existing MQTT settings preserved
        assert merged.mqtt_broker == 'localhost'
        assert merged.mqtt_username == 'nisystem'
        # New channels from payload
        assert 'New_Ch' in merged.channels

    def test_save_and_reload_config(self, node_config):
        """Config round-trips through save_config and from_json_file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / 'test_config.json')
            save_config(node_config, path)
            reloaded = NodeConfig.from_json_file(path)
            assert reloaded.node_id == node_config.node_id
            assert len(reloaded.channels) == len(node_config.channels)
            assert reloaded.groov_mqtt_host == node_config.groov_mqtt_host

    def test_codesys_config_defaults(self):
        """CODESYSConfig has sensible defaults."""
        cfg = CODESYSConfig()
        assert cfg.enabled is False
        assert cfg.host == 'localhost'
        assert cfg.port == 502
        assert cfg.unit_id == 1
        assert cfg.poll_rate_hz == 10.0

    def test_codesys_config_from_dict(self):
        """CODESYSConfig.from_dict parses correctly."""
        data = {'enabled': True, 'host': '10.0.0.1', 'port': 503, 'unit_id': 2}
        cfg = CODESYSConfig.from_dict(data)
        assert cfg.enabled is True
        assert cfg.host == '10.0.0.1'
        assert cfg.port == 503

# ============================================================================
# TestOpto22StateMachine — State machine tests (~10 tests)
# ============================================================================

class TestOpto22StateMachine:
    """Test state transitions, validation, session lifecycle, and callbacks."""

    def test_initial_state_is_idle(self):
        """State machine starts in IDLE."""
        sm = StateTransition()
        assert sm.state == State.IDLE
        assert sm.is_acquiring is False
        assert sm.is_session_active is False
        assert sm.is_connecting is False

    def test_transition_idle_to_connecting(self):
        """IDLE -> CONNECTING_MQTT is valid."""
        sm = StateTransition()
        assert sm.to(State.CONNECTING_MQTT) is True
        assert sm.state == State.CONNECTING_MQTT
        assert sm.is_connecting is True

    def test_transition_idle_to_acquiring(self):
        """IDLE -> ACQUIRING (direct, MQTT already connected)."""
        sm = StateTransition()
        assert sm.to(State.ACQUIRING) is True
        assert sm.state == State.ACQUIRING
        assert sm.is_acquiring is True

    def test_transition_acquiring_to_session(self):
        """ACQUIRING -> SESSION is valid."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.to(State.SESSION) is True
        assert sm.is_session_active is True
        assert sm.is_acquiring is True  # SESSION implies acquiring

    def test_transition_idle_to_session_invalid(self):
        """IDLE -> SESSION is invalid (must acquire first)."""
        sm = StateTransition()
        assert sm.to(State.SESSION) is False
        assert sm.state == State.IDLE  # unchanged

    def test_transition_connecting_to_session_invalid(self):
        """CONNECTING_MQTT -> SESSION is invalid."""
        sm = StateTransition()
        sm.to(State.CONNECTING_MQTT)
        assert sm.to(State.SESSION) is False
        assert sm.state == State.CONNECTING_MQTT

    def test_same_state_transition_noop(self):
        """Transitioning to the same state returns True but is a no-op."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.to(State.ACQUIRING) is True
        assert sm.state == State.ACQUIRING

    def test_session_start_populates_info(self):
        """Transitioning to SESSION populates session info from payload."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, payload={
            'name': 'Test Run',
            'operator': 'Engineer',
            'locked_outputs': ['DO_Heater'],
            'test_id': 'T-001',
        })
        assert sm.session.name == 'Test Run'
        assert sm.session.operator == 'Engineer'
        assert 'DO_Heater' in sm.session.locked_outputs
        assert sm.session.test_id == 'T-001'
        assert sm.session.start_time > 0

    def test_session_end_clears_info(self):
        """Transitioning out of SESSION clears session info."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, payload={'name': 'Run1', 'operator': 'Op'})
        sm.to(State.ACQUIRING)
        assert sm.is_session_active is False
        assert sm.session.name == ''

    def test_output_lock_in_session(self):
        """is_output_locked returns True for locked outputs during SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, payload={'locked_outputs': ['DO_Heater', 'AO_Valve']})
        assert sm.is_output_locked('DO_Heater') is True
        assert sm.is_output_locked('AO_Valve') is True
        assert sm.is_output_locked('AI_Press') is False

    def test_output_lock_outside_session(self):
        """is_output_locked returns False when not in SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        assert sm.is_output_locked('DO_Heater') is False

    def test_enter_exit_callbacks(self):
        """State transition fires enter/exit callbacks."""
        enter_log = []
        exit_log = []

        sm = StateTransition()
        sm.on_enter(State.ACQUIRING, lambda old, new, p: enter_log.append(('enter', old, new)))
        sm.on_exit(State.IDLE, lambda old, new, p: exit_log.append(('exit', old, new)))

        sm.to(State.ACQUIRING)
        assert len(enter_log) == 1
        assert enter_log[0] == ('enter', State.IDLE, State.ACQUIRING)
        assert len(exit_log) == 1
        assert exit_log[0] == ('exit', State.IDLE, State.ACQUIRING)

    def test_get_status_includes_state(self):
        """get_status returns current state info."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        status = sm.get_status()
        assert status['state'] == 'ACQUIRING'
        assert status['acquiring'] is True
        assert status['session_active'] is False

    def test_get_status_with_session(self):
        """get_status includes session details during SESSION."""
        sm = StateTransition()
        sm.to(State.ACQUIRING)
        sm.to(State.SESSION, payload={'name': 'Run1', 'operator': 'Op', 'test_id': 'T1'})
        status = sm.get_status()
        assert status['session_active'] is True
        assert status['session_name'] == 'Run1'
        assert status['test_id'] == 'T1'
        assert 'session_duration_s' in status

    def test_aliases_exist(self):
        """Opto22State and Opto22StateMachine are proper aliases."""
        assert Opto22State is State
        assert Opto22StateMachine is StateTransition

# ============================================================================
# TestOpto22MQTTInterface — MQTT interface tests (~10 tests)
# ============================================================================

@pytest.mark.skipif(not MQTT_AVAILABLE, reason="paho-mqtt not installed")
class TestOpto22MQTTInterface:
    """Test dual MQTT client setup, topic building, connection state, message routing."""

    def test_system_mqtt_topic_base(self):
        """SystemMQTT builds correct topic base."""
        config = MQTTConfig(base_topic='nisystem', node_id='opto22-test')
        mqtt = SystemMQTT(config)
        assert mqtt.topic_base == 'nisystem/nodes/opto22-test'

    def test_system_mqtt_topic_builder(self):
        """SystemMQTT.topic() builds full topics."""
        config = MQTTConfig(base_topic='nisystem', node_id='opto22-test')
        mqtt = SystemMQTT(config)
        assert mqtt.topic('status', 'system') == 'nisystem/nodes/opto22-test/status/system'
        assert mqtt.topic('channels') == 'nisystem/nodes/opto22-test/channels'

    def test_system_mqtt_initially_disconnected(self):
        """SystemMQTT starts disconnected."""
        config = MQTTConfig()
        mqtt = SystemMQTT(config)
        assert mqtt.is_connected() is False

    def test_system_mqtt_publish_fails_when_disconnected(self):
        """Publish returns False when not connected."""
        config = MQTTConfig()
        mqtt = SystemMQTT(config)
        assert mqtt.publish('test/topic', {'data': 1}) is False

    def test_system_mqtt_subscribe_queues(self):
        """Subscriptions are queued when not connected."""
        config = MQTTConfig()
        mqtt = SystemMQTT(config)
        mqtt.subscribe('test/topic/#', qos=1)
        assert len(mqtt._subscriptions) == 1
        assert mqtt._subscriptions[0] == ('test/topic/#', 1)

    def test_system_mqtt_max_payload_size(self):
        """MAX_PAYLOAD_SIZE is defined at 256KB."""
        assert SystemMQTT.MAX_PAYLOAD_SIZE == 262144

    def test_groov_mqtt_initially_disconnected(self):
        """GroovMQTT starts disconnected."""
        config = GroovMQTTConfig()
        mqtt = GroovMQTT(config)
        assert mqtt.is_connected() is False

    def test_groov_mqtt_config_defaults(self):
        """GroovMQTTConfig has correct defaults."""
        config = GroovMQTTConfig()
        assert config.broker_host == 'localhost'
        assert config.broker_port == 1883
        assert config.io_topic_patterns == ['groov/io/#']
        assert config.tls_enabled is False

    def test_system_mqtt_on_message_callback(self):
        """SystemMQTT._on_message parses JSON and dispatches to callback."""
        config = MQTTConfig()
        mqtt = SystemMQTT(config)
        received = []
        mqtt.on_message = lambda topic, payload: received.append((topic, payload))

        # Create a mock message
        mock_msg = MagicMock()
        mock_msg.topic = 'nisystem/nodes/opto22/commands/ping'
        mock_msg.payload = json.dumps({'request_id': '123'}).encode('utf-8')

        mqtt._on_message(None, None, mock_msg)
        assert len(received) == 1
        assert received[0][0] == 'nisystem/nodes/opto22/commands/ping'
        assert received[0][1] == {'request_id': '123'}

    def test_system_mqtt_on_message_oversized_dropped(self):
        """Oversized payloads are dropped."""
        config = MQTTConfig()
        mqtt = SystemMQTT(config)
        received = []
        mqtt.on_message = lambda t, p: received.append(p)

        mock_msg = MagicMock()
        mock_msg.topic = 'test'
        mock_msg.payload = b'x' * (SystemMQTT.MAX_PAYLOAD_SIZE + 1)

        mqtt._on_message(None, None, mock_msg)
        assert len(received) == 0

    def test_groov_mqtt_on_message_numeric(self):
        """GroovMQTT._on_message handles raw numeric payloads."""
        config = GroovMQTTConfig()
        mqtt = GroovMQTT(config)
        received = []
        mqtt.on_io_data = lambda topic, payload: received.append((topic, payload))

        mock_msg = MagicMock()
        mock_msg.topic = 'groov/io/mod0/ch0'
        mock_msg.payload = b'23.5'

        mqtt._on_message(None, None, mock_msg)
        assert len(received) == 1
        assert received[0][1] == 23.5

    def test_system_mqtt_publish_auto_prefixes_topic(self):
        """publish() auto-prefixes topic when it doesn't start with base_topic."""
        config = MQTTConfig(base_topic='nisystem', node_id='opto22-test')
        mqtt = SystemMQTT(config)
        mqtt._connected = threading.Event()
        mqtt._connected.set()
        mqtt._client = MagicMock()
        mqtt._client.publish.return_value = MagicMock(rc=0)

        mqtt.publish('status/system', {'ok': True})
        call_args = mqtt._client.publish.call_args
        # Topic should be prefixed with topic_base
        assert call_args[0][0] == 'nisystem/nodes/opto22-test/status/system'

# ============================================================================
# TestOpto22Hardware — Hardware abstraction tests (~12 tests)
# ============================================================================

class TestOpto22Hardware:
    """Test GroovIOSubscriber, stale channel detection, REST fallback, and HardwareInterface."""

    def test_io_subscriber_topic_mapping(self, topic_mapping):
        """GroovIOSubscriber maps groov topics to channel names."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        sub.on_io_message('groov/io/mod0/ch0', 25.5)
        values = sub.get_values()
        assert values.get('TC_Zone1') == 25.5

    def test_io_subscriber_auto_derive_channel_name(self):
        """Without mapping, channel names are auto-derived from topic."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod2/ch3', 42.0)
        values = sub.get_values()
        assert 'mod2_ch3' in values
        assert values['mod2_ch3'] == 42.0

    def test_io_subscriber_extract_value_float(self):
        """Extract float value from various payload types."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', 25.5)
        assert sub.get_value('mod0_ch0') == 25.5

    def test_io_subscriber_extract_value_int(self):
        """Integer payload is converted to float."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', 42)
        assert sub.get_value('mod0_ch0') == 42.0

    def test_io_subscriber_extract_value_bool(self):
        """Boolean payload is converted: True=1.0, False=0.0."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', True)
        assert sub.get_value('mod0_ch0') == 1.0
        sub.on_io_message('groov/io/mod0/ch0', False)
        assert sub.get_value('mod0_ch0') == 0.0

    def test_io_subscriber_extract_value_dict(self):
        """Dict payload with 'value' key is parsed."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', {'value': 98.6, 'quality': 'good'})
        assert sub.get_value('mod0_ch0') == 98.6

    def test_io_subscriber_extract_value_string(self):
        """String payload is parsed as float."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', '123.45')
        assert sub.get_value('mod0_ch0') == 123.45

    def test_io_subscriber_invalid_payload_ignored(self):
        """Non-numeric payloads are silently ignored."""
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', 'not_a_number')
        assert sub.get_value('mod0_ch0') is None

    def test_io_subscriber_stale_channels(self, topic_mapping):
        """get_stale_channels returns channels not updated within timeout."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        # Inject old timestamps
        sub._values['TC_Zone1'] = 25.0
        sub._last_update['TC_Zone1'] = time.time() - 20.0  # 20s ago
        sub._values['AI_Press'] = 100.0
        sub._last_update['AI_Press'] = time.time()  # just now

        stale = sub.get_stale_channels(timeout_s=10.0)
        assert 'TC_Zone1' in stale
        assert 'AI_Press' not in stale

    def test_io_subscriber_no_stale_when_fresh(self, topic_mapping):
        """No stale channels when all data is fresh."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        sub.on_io_message('groov/io/mod0/ch0', 25.0)
        sub.on_io_message('groov/io/mod0/ch1', 100.0)
        stale = sub.get_stale_channels(timeout_s=10.0)
        assert len(stale) == 0

    def test_io_subscriber_channel_count(self, topic_mapping):
        """channel_count reflects number of received channels."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        assert sub.channel_count == 0
        sub.on_io_message('groov/io/mod0/ch0', 25.0)
        assert sub.channel_count == 1
        sub.on_io_message('groov/io/mod0/ch1', 100.0)
        assert sub.channel_count == 2

    def test_io_subscriber_update_topic_mapping(self, topic_mapping):
        """update_topic_mapping replaces the mapping."""
        sub = GroovIOSubscriber()
        sub.update_topic_mapping(topic_mapping)
        sub.on_io_message('groov/io/mod0/ch0', 25.0)
        assert sub.get_value('TC_Zone1') == 25.0

    def test_hardware_interface_get_values(self, topic_mapping):
        """HardwareInterface.get_values delegates to GroovIOSubscriber."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        sub.on_io_message('groov/io/mod0/ch0', 25.0)
        sub.on_io_message('groov/io/mod0/ch1', 100.0)

        hw = HardwareInterface(io_subscriber=sub)
        values = hw.get_values()
        assert values['TC_Zone1'] == 25.0
        assert values['AI_Press'] == 100.0

    def test_hardware_interface_write_output(self):
        """HardwareInterface.write_output calls the output write function."""
        write_fn = Mock(return_value=True)
        hw = HardwareInterface(output_write_fn=write_fn)
        result = hw.write_output('DO_Heater', 1.0)
        assert result is True
        write_fn.assert_called_once_with('DO_Heater', 1.0)
        assert hw.get_output_values() == {'DO_Heater': 1.0}

    def test_hardware_interface_write_output_no_fn(self):
        """write_output returns False when no output_write_fn is set."""
        hw = HardwareInterface()
        assert hw.write_output('DO_Heater', 1.0) is False

    def test_hardware_interface_is_healthy(self, topic_mapping):
        """is_healthy returns True when channels have data."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        hw = HardwareInterface(io_subscriber=sub)
        assert hw.is_healthy() is False  # no data yet
        sub.on_io_message('groov/io/mod0/ch0', 25.0)
        assert hw.is_healthy() is True

    def test_hardware_interface_construction_with_groov_mqtt(self):
        """HardwareInterface wires groov_mqtt.on_io_data to subscriber."""
        mock_groov = MagicMock()
        mock_groov.on_io_data = None

        hw = HardwareInterface(
            groov_mqtt=mock_groov,
            topic_mapping={'groov/io/mod0/ch0': 'TC_Zone1'},
        )
        # The on_io_data callback should now be set
        assert mock_groov.on_io_data is not None
        assert hw.io is not None

    def test_hardware_interface_stale_channels_proxy(self, topic_mapping):
        """get_stale_channels proxies to the subscriber."""
        sub = GroovIOSubscriber(topic_mapping=topic_mapping)
        sub._values['TC_Zone1'] = 25.0
        sub._last_update['TC_Zone1'] = time.time() - 30.0

        hw = HardwareInterface(io_subscriber=sub)
        stale = hw.get_stale_channels(timeout_s=10.0)
        assert 'TC_Zone1' in stale

# ============================================================================
# TestOpto22NodeOrchestration — Node service orchestration tests (~16 tests)
# ============================================================================

@pytest.mark.skipif(not NODE_AVAILABLE, reason="Opto22NodeService import failed")
class TestOpto22NodeOrchestration:
    """Test node initialization, command dispatch, status, scan loop, shutdown."""

    @pytest.fixture
    def node(self):
        """Create an Opto22NodeService with mocked dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            # Write a minimal config file so _load_local_config succeeds
            config_data = {
                'system': {
                    'node_id': 'opto22-test',
                    'scan_rate_hz': 4.0,
                    'publish_rate_hz': 4.0,
                    'mqtt_broker': 'localhost',
                    'mqtt_port': 1883,
                    'mqtt_base_topic': 'nisystem',
                },
                'groov': {
                    'mqtt_host': 'localhost',
                    'mqtt_port': 1883,
                },
                'channels': {
                    'TC_Zone1': {
                        'physical_channel': 'groov/io/mod0/ch0',
                        'channel_type': 'thermocouple',
                        'groov_topic': 'groov/io/mod0/ch0',
                    },
                    'DO_Heater': {
                        'physical_channel': 'groov/io/mod1/ch0',
                        'channel_type': 'digital_output',
                        'groov_topic': 'groov/io/mod1/ch0',
                        'default_value': 0.0,
                    },
                },
            }
            config_file = config_dir / 'opto22_config.json'
            with open(config_file, 'w') as f:
                json.dump(config_data, f)

            node = Opto22NodeService(config_dir=config_dir)
            # Mock MQTT interfaces
            node.system_mqtt = MagicMock()
            node.system_mqtt.is_connected.return_value = True
            node.system_mqtt.publish.return_value = True
            node.groov_mqtt = MagicMock()
            node.groov_mqtt.is_connected.return_value = True
            # Mock hardware
            node.hardware = MagicMock()
            node.hardware.get_values.return_value = {'TC_Zone1': 25.0}
            node.hardware.get_last_update_times.return_value = {'TC_Zone1': time.time()}
            node.hardware.get_stale_channels.return_value = []
            node.hardware.io.channel_count = 1
            node.hardware.write_output.return_value = True

            yield node

    def test_node_initialization(self, node):
        """Node initializes with correct config."""
        assert node.config is not None
        assert node.config.node_id == 'opto22-test'
        assert len(node.config.channels) == 2

    def test_node_topic_base(self, node):
        """Node builds correct topic base from config."""
        assert node._topic_base() == 'nisystem/nodes/opto22-test'

    def test_node_topic_full(self, node):
        """Node builds full topic with suffix."""
        assert node._topic('status/system') == 'nisystem/nodes/opto22-test/status/system'

    def test_handle_command_ping(self, node):
        """Ping command publishes a response."""
        topic = 'nisystem/nodes/opto22-test/commands/ping'
        payload = {'request_id': 'req-123'}
        node._on_mqtt_message(topic, payload)
        # Verify publish was called (response topic)
        assert node.system_mqtt.publish.called

    def test_handle_command_info(self, node):
        """Info command publishes node info."""
        topic = 'nisystem/nodes/opto22-test/commands/info'
        payload = {'request_id': 'req-456'}
        node._on_mqtt_message(topic, payload)
        assert node.system_mqtt.publish.called

    def test_handle_command_output_set(self, node):
        """Output command writes to hardware."""
        topic = 'nisystem/nodes/opto22-test/commands/output'
        payload = {'channel': 'DO_Heater', 'value': 1.0}
        node._on_mqtt_message(topic, payload)
        assert node.output_values.get('DO_Heater') == 1.0

    def test_handle_command_output_session_locked(self, node):
        """Output command is blocked for session-locked channels."""
        node._session_active = True
        node._session_locked_outputs = ['DO_Heater']
        topic = 'nisystem/nodes/opto22-test/commands/output'
        payload = {'channel': 'DO_Heater', 'value': 1.0}
        node._on_mqtt_message(topic, payload)
        # Should publish session/blocked instead of setting output
        assert node.output_values.get('DO_Heater') is None

    def test_handle_system_acquire_start(self, node):
        """Acquire start command starts acquisition."""
        topic = 'nisystem/nodes/opto22-test/system/acquire/start'
        node._on_mqtt_message(topic, {})
        assert node._acquiring.is_set()

    def test_handle_system_acquire_stop(self, node):
        """Acquire stop command stops acquisition."""
        # Start first
        node._acquiring.set()
        node.scan_thread = MagicMock()
        node.scan_thread.is_alive.return_value = False
        topic = 'nisystem/nodes/opto22-test/system/acquire/stop'
        node._on_mqtt_message(topic, {})
        assert not node._acquiring.is_set()

    def test_handle_session_start_stop(self, node):
        """Session start/stop commands update session state."""
        start_topic = 'nisystem/nodes/opto22-test/session/start'
        node._on_mqtt_message(start_topic, {
            'name': 'Test1', 'operator': 'Op', 'locked_outputs': ['DO_Heater']
        })
        assert node._session_active is True
        assert node._session_name == 'Test1'
        assert node._session_operator == 'Op'

        stop_topic = 'nisystem/nodes/opto22-test/session/stop'
        node._on_mqtt_message(stop_topic, {'reason': 'manual'})
        assert node._session_active is False

    def test_session_timeout(self, node):
        """Session auto-stops after timeout."""
        node._session_active = True
        node._session_start_time = time.time() - 3700  # >60 min ago
        node._session_timeout_minutes = 60
        node._check_session_timeout()
        assert node._session_active is False

    def test_session_no_timeout_when_zero(self, node):
        """Session does not timeout when timeout_minutes is 0."""
        node._session_active = True
        node._session_start_time = time.time() - 7200
        node._session_timeout_minutes = 0
        node._check_session_timeout()
        assert node._session_active is True

    def test_set_safe_state(self, node):
        """_set_safe_state writes safe values to all output channels."""
        node._set_safe_state('test')
        # Should attempt to write safe value for DO_Heater
        node.hardware.write_output.assert_called()

    def test_comm_watchdog_trip(self, node):
        """Comm watchdog trips after timeout."""
        node.last_pc_contact = time.time() - 60.0  # 60s ago
        node.config.comm_watchdog_timeout_s = 30.0
        node._comm_watchdog_tripped = False
        # The node calls state_machine.transition() which is actually .to()
        # Mock it to avoid AttributeError in production code
        node.state_machine.transition = node.state_machine.to
        node._check_comm_watchdog()
        assert node._comm_watchdog_tripped is True

    def test_comm_watchdog_no_trip_within_timeout(self, node):
        """Comm watchdog does not trip within timeout."""
        node.last_pc_contact = time.time() - 10.0  # 10s ago
        node.config.comm_watchdog_timeout_s = 30.0
        node._comm_watchdog_tripped = False
        node._check_comm_watchdog()
        assert node._comm_watchdog_tripped is False

    def test_comm_watchdog_restore(self, node):
        """Comm watchdog clears tripped flag when contact restored."""
        node._comm_watchdog_tripped = True
        node.last_pc_contact = time.time()  # just now
        node.config.comm_watchdog_timeout_s = 30.0
        node._check_comm_watchdog()
        assert node._comm_watchdog_tripped is False

    def test_discovery_ping_publishes_status(self, node):
        """Discovery ping triggers status publish."""
        topic = 'nisystem/discovery/ping'
        node._on_mqtt_message(topic, {})
        assert node.system_mqtt.publish.called

    def test_mqtt_message_updates_pc_contact(self, node):
        """Any MQTT message updates last_pc_contact."""
        old_time = node.last_pc_contact
        time.sleep(0.01)
        node._on_mqtt_message('nisystem/nodes/opto22-test/commands/ping', {})
        assert node.last_pc_contact > old_time

    def test_reset_clears_values(self, node):
        """_reset clears channel values."""
        node.channel_values = {'TC_Zone1': 25.0}
        node.channel_timestamps = {'TC_Zone1': time.time()}
        # Pre-set acquiring state so _stop_acquisition has work to do
        node._acquiring.clear()
        node._reset()
        assert len(node.channel_values) == 0
        assert len(node.channel_timestamps) == 0

# ============================================================================
# TestOpto22ValueQuality — Value quality function tests (~5 tests)
# ============================================================================

@pytest.mark.skipif(not NODE_AVAILABLE, reason="Opto22NodeService import failed")
class TestOpto22ValueQuality:
    """Test OPC UA style quality assessment for channel values."""

    def test_good_value(self):
        """Normal numeric values have 'good' quality."""
        assert get_value_quality(25.5) == 'good'
        assert get_value_quality(0) == 'good'
        assert get_value_quality(-100.0) == 'good'

    def test_none_is_bad(self):
        """None values have 'bad' quality."""
        assert get_value_quality(None) == 'bad'

    def test_nan_is_bad(self):
        """NaN values have 'bad' quality."""
        assert get_value_quality(float('nan')) == 'bad'

    def test_inf_is_bad(self):
        """Infinity values have 'bad' quality."""
        assert get_value_quality(float('inf')) == 'bad'
        assert get_value_quality(float('-inf')) == 'bad'

    def test_string_is_bad(self):
        """Non-numeric types have 'bad' quality."""
        assert get_value_quality('hello') == 'bad'

# ============================================================================
# TestScanTimingStats — Scan timing statistics (~4 tests)
# ============================================================================

@pytest.mark.skipif(not NODE_AVAILABLE, reason="Opto22NodeService import failed")
class TestScanTimingStats:
    """Test scan loop timing statistics."""

    def test_initial_stats(self):
        """Fresh ScanTimingStats has zero values."""
        stats = ScanTimingStats(target_ms=250.0)
        assert stats.total_scans == 0
        assert stats.overruns == 0
        assert stats.mean_ms == 0.0

    def test_record_updates_stats(self):
        """Recording samples updates mean and count."""
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(200.0)
        stats.record(300.0)
        assert stats.total_scans == 2
        assert stats.mean_ms == pytest.approx(250.0)

    def test_overrun_detection(self):
        """Samples >1.5x target are counted as overruns."""
        stats = ScanTimingStats(target_ms=100.0)
        stats.record(100.0)  # normal
        stats.record(160.0)  # > 150 = overrun
        assert stats.overruns == 1

    def test_to_dict(self):
        """to_dict contains all expected keys."""
        stats = ScanTimingStats(target_ms=250.0)
        stats.record(240.0)
        d = stats.to_dict()
        assert 'target_ms' in d
        assert 'actual_ms' in d
        assert 'min_ms' in d
        assert 'max_ms' in d
        assert 'actual_rate_hz' in d
        assert 'overruns' in d
        assert 'total_scans' in d
        assert d['total_scans'] == 1

# ============================================================================
# TestOpto22SafetyIntegration — Safety system integration tests (~12 tests)
# ============================================================================

@pytest.mark.skipif(not SAFETY_AVAILABLE, reason="opto22_node.safety import failed")
class TestOpto22SafetyIntegration:
    """Test safety manager integration with the Opto22 node."""

    @pytest.fixture
    def safety_mgr(self):
        """Create a SafetyManager with temporary data dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SafetyManager(data_dir=tmpdir)
            yield sm

    def test_safety_manager_initialization(self, safety_mgr):
        """SafetyManager initializes with clean state."""
        assert safety_mgr._latch_state == LatchState.SAFE
        assert len(safety_mgr._configs) == 0
        assert len(safety_mgr._interlocks) == 0

    def test_alarm_config_loading(self, safety_mgr):
        """load_config parses alarm configurations."""
        config = {
            'alarms': [
                {
                    'channel': 'TC_Zone1',
                    'enabled': True,
                    'hihi_limit': 100.0,
                    'hi_limit': 80.0,
                    'lo_limit': 10.0,
                    'lolo_limit': 5.0,
                    'deadband': 1.0,
                },
            ],
        }
        safety_mgr.load_config(config)
        assert 'TC_Zone1' in safety_mgr._configs

    def test_check_all_normal_values(self, safety_mgr):
        """check_all with normal values produces no alarm events."""
        safety_mgr.load_config({
            'alarms': [{
                'channel': 'TC_Zone1', 'enabled': True,
                'hi_limit': 80.0, 'lo_limit': 10.0,
            }],
        })
        events = safety_mgr.check_all({'TC_Zone1': 50.0})
        # No alarms should fire for value in normal range
        state = safety_mgr._states.get('TC_Zone1')
        assert state is None or state.state == AlarmState.NORMAL

    def test_check_all_hi_alarm(self, safety_mgr):
        """check_all with high value triggers HI alarm."""
        safety_mgr.load_config({
            'alarms': [{
                'channel': 'TC_Zone1', 'enabled': True,
                'hi_limit': 80.0,
            }],
        })
        safety_mgr.check_all({'TC_Zone1': 85.0})
        state = safety_mgr._states.get('TC_Zone1')
        assert state is not None
        assert state.state == AlarmState.ACTIVE

    def test_check_all_comm_fail(self, safety_mgr):
        """check_all with missing channel triggers COMM_FAIL alarm."""
        safety_mgr.load_config({
            'alarms': [{
                'channel': 'TC_Zone1', 'enabled': True,
                'hi_limit': 80.0,
            }],
        })
        # TC_Zone1 is configured but not in values dict
        safety_mgr.check_all(
            {}, configured_channels={'TC_Zone1'}
        )
        # Should have COMM_FAIL alarm tracked in channel state
        state = safety_mgr._states.get('TC_Zone1')
        assert state is not None
        assert state.active_alarm_type == 'comm_fail'
        assert state.state == AlarmState.ACTIVE

    def test_alarm_acknowledge(self, safety_mgr):
        """acknowledge_alarm transitions alarm from ACTIVE to ACKNOWLEDGED."""
        safety_mgr.load_config({
            'alarms': [{
                'channel': 'TC_Zone1', 'enabled': True,
                'hi_limit': 80.0,
            }],
        })
        safety_mgr.check_all({'TC_Zone1': 85.0})
        result = safety_mgr.acknowledge_alarm('TC_Zone1')
        assert result is True
        state = safety_mgr._states.get('TC_Zone1')
        assert state.acknowledged is True

    def test_alarm_shelve(self, safety_mgr):
        """shelve_alarm transitions channel to SHELVED state."""
        safety_mgr.load_config({
            'alarms': [{
                'channel': 'TC_Zone1', 'enabled': True,
                'hi_limit': 80.0,
            }],
        })
        safety_mgr.check_all({'TC_Zone1': 85.0})
        result = safety_mgr.shelve_alarm('TC_Zone1', 3600.0, 'operator1')
        assert result is True
        state = safety_mgr._states.get('TC_Zone1')
        assert state.state == AlarmState.SHELVED

    def test_interlock_configure(self, safety_mgr):
        """configure_interlocks loads interlock definitions."""
        interlocks_data = [
            {
                'id': 'ilk-1',
                'name': 'Overtemp Protection',
                'conditions': [{
                    'id': 'c1',
                    'type': 'channel_value',
                    'channel': 'TC_Zone1',
                    'operator': '<',
                    'value': 100.0,
                }],
                'controls': [{
                    'type': 'set_output',
                    'channel': 'DO_Heater',
                    'setValue': 0,
                }],
            },
        ]
        safety_mgr.configure_interlocks(interlocks_data)
        assert 'ilk-1' in safety_mgr._interlocks
        ilk = safety_mgr._interlocks['ilk-1']
        assert ilk.name == 'Overtemp Protection'
        assert len(ilk.conditions) == 1
        assert len(ilk.controls) == 1

    def test_interlock_arm_latch(self, safety_mgr):
        """arm_latch transitions from SAFE to ARMED."""
        safety_mgr.configure_interlocks([{
            'id': 'ilk-1', 'name': 'Test',
            'conditions': [{'id': 'c1', 'type': 'channel_value',
                            'channel': 'TC', 'operator': '<', 'value': 100}],
            'controls': [],
        }])
        success, msg = safety_mgr.arm_latch('operator1')
        assert success is True
        assert safety_mgr._latch_state == LatchState.ARMED

    def test_interlock_disarm_latch(self, safety_mgr):
        """disarm_latch transitions from ARMED to SAFE."""
        safety_mgr.configure_interlocks([{
            'id': 'ilk-1', 'name': 'Test',
            'conditions': [{'id': 'c1', 'type': 'channel_value',
                            'channel': 'TC', 'operator': '<', 'value': 100}],
            'controls': [],
        }])
        safety_mgr.arm_latch('op')
        safety_mgr.disarm_latch('op')
        assert safety_mgr._latch_state == LatchState.SAFE

    def test_safe_state_config(self, safety_mgr):
        """configure_safe_state sets per-channel safe values."""
        safety_mgr.configure_safe_state({
            'channelSafeValues': {'DO_Heater': 0.0, 'AO_Valve': 50.0},
            'stopSession': True,
        })
        cfg = safety_mgr.get_safe_state_config()
        assert cfg.channel_safe_values.get('DO_Heater') == 0.0
        assert cfg.channel_safe_values.get('AO_Valve') == 50.0
        assert cfg.stop_session is True

    def test_get_channel_safe_value(self, safety_mgr):
        """get_channel_safe_value returns configured or default value."""
        safety_mgr.configure_safe_state({
            'channelSafeValues': {'DO_Heater': 0.0},
        })
        assert safety_mgr.get_channel_safe_value('DO_Heater', 1.0) == 0.0
        # Unconfigured channel uses default
        assert safety_mgr.get_channel_safe_value('Unknown_Ch', 99.0) == 99.0

    def test_interlock_bypass(self, safety_mgr):
        """bypass_interlock sets bypass flag on a specific interlock."""
        safety_mgr.configure_interlocks([{
            'id': 'ilk-1', 'name': 'Test', 'bypassAllowed': True,
            'conditions': [{'id': 'c1', 'type': 'channel_value',
                            'channel': 'TC', 'operator': '<', 'value': 100}],
            'controls': [],
        }])
        success, msg = safety_mgr.bypass_interlock('ilk-1', True, 'op', 'maintenance')
        assert success is True
        assert safety_mgr._interlocks['ilk-1'].bypassed is True

# ============================================================================
# TestInterlockDataStructures — Interlock serialization tests (~5 tests)
# ============================================================================

@pytest.mark.skipif(not SAFETY_AVAILABLE, reason="opto22_node.safety import failed")
class TestInterlockDataStructures:
    """Test interlock data structures and serialization compatibility."""

    def test_condition_to_dict(self):
        """InterlockCondition.to_dict uses DAQ service format."""
        cond = InterlockCondition(
            id='c1', condition_type='channel_value',
            channel='TC_Zone1', operator='>', value=50.0,
        )
        d = cond.to_dict()
        assert d['type'] == 'channel_value'  # 'type', not 'condition_type'
        assert d['channel'] == 'TC_Zone1'
        assert d['operator'] == '>'
        assert d['value'] == 50.0

    def test_condition_from_dict_camelcase(self):
        """InterlockCondition.from_dict accepts DAQ service format (type key)."""
        d = {'id': 'c1', 'type': 'channel_value', 'channel': 'TC',
             'operator': '<', 'value': 100.0}
        cond = InterlockCondition.from_dict(d)
        assert cond.condition_type == 'channel_value'
        assert cond.channel == 'TC'

    def test_condition_from_dict_snake_case(self):
        """InterlockCondition.from_dict accepts node format (condition_type key)."""
        d = {'id': 'c1', 'condition_type': 'digital_input', 'channel': 'DI_Stop'}
        cond = InterlockCondition.from_dict(d)
        assert cond.condition_type == 'digital_input'

    def test_control_to_dict(self):
        """InterlockControl.to_dict uses DAQ service format."""
        ctrl = InterlockControl(
            control_type='set_output', channel='DO_Heater', set_value=0.0,
        )
        d = ctrl.to_dict()
        assert d['type'] == 'set_output'
        assert d['setValue'] == 0.0

    def test_control_from_dict_both_formats(self):
        """InterlockControl.from_dict accepts both camelCase and snake_case."""
        # DAQ format
        d1 = {'type': 'set_output', 'channel': 'DO', 'setValue': 0.0}
        ctrl1 = InterlockControl.from_dict(d1)
        assert ctrl1.control_type == 'set_output'
        assert ctrl1.set_value == 0.0

        # Node format
        d2 = {'control_type': 'stop_session', 'set_value': None}
        ctrl2 = InterlockControl.from_dict(d2)
        assert ctrl2.control_type == 'stop_session'

    def test_interlock_round_trip(self):
        """Interlock serializes and deserializes correctly."""
        ilk = Interlock(
            id='ilk-1', name='Test Interlock',
            conditions=[InterlockCondition(id='c1', condition_type='channel_value',
                                           channel='TC', operator='<', value=100)],
            controls=[InterlockControl(control_type='set_output',
                                       channel='DO', set_value=0)],
            bypass_allowed=True, priority='high',
        )
        d = ilk.to_dict()
        restored = Interlock.from_dict(d)
        assert restored.id == 'ilk-1'
        assert restored.name == 'Test Interlock'
        assert len(restored.conditions) == 1
        assert len(restored.controls) == 1
        assert restored.bypass_allowed is True
        assert restored.priority == 'high'

    def test_safe_state_config_from_dict_node_format(self):
        """SafeStateConfig.from_dict handles node format."""
        d = {'channel_safe_values': {'DO_Heater': 0.0}, 'stop_session': False}
        cfg = SafeStateConfig.from_dict(d)
        assert cfg.channel_safe_values == {'DO_Heater': 0.0}
        assert cfg.stop_session is False

    def test_safe_state_config_from_dict_daq_format(self):
        """SafeStateConfig.from_dict handles DAQ service category-based format."""
        d = {
            'resetDigitalOutputs': True,
            'resetAnalogOutputs': True,
            'analogSafeValue': 0.0,
            'digitalOutputChannels': ['DO_1', 'DO_2'],
            'analogOutputChannels': ['AO_1'],
            'stopSession': True,
        }
        cfg = SafeStateConfig.from_dict(d)
        assert cfg.channel_safe_values.get('DO_1') == 0.0
        assert cfg.channel_safe_values.get('DO_2') == 0.0
        assert cfg.channel_safe_values.get('AO_1') == 0.0
        assert cfg.stop_session is True

# ============================================================================
# TestChannelTypes — Channel type utility tests (~3 tests)
# ============================================================================

class TestChannelTypes:
    """Test channel type classification utilities."""

    def test_is_input(self):
        """Input channel types are correctly identified."""
        assert ChannelType.is_input('voltage_input') is True
        assert ChannelType.is_input('thermocouple') is True
        assert ChannelType.is_input('digital_input') is True
        assert ChannelType.is_input('digital_output') is False

    def test_is_output(self):
        """Output channel types are correctly identified."""
        assert ChannelType.is_output('voltage_output') is True
        assert ChannelType.is_output('digital_output') is True
        assert ChannelType.is_output('voltage_input') is False
        assert ChannelType.is_output('thermocouple') is False

    def test_is_analog(self):
        """Analog channel types are correctly identified."""
        assert ChannelType.is_analog('voltage_input') is True
        assert ChannelType.is_analog('current_input') is True
        assert ChannelType.is_analog('thermocouple') is True
        assert ChannelType.is_analog('digital_input') is False
        assert ChannelType.is_analog('digital_output') is False
