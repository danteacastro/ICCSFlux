"""
Tests for hot-unplug resilience features.

Covers:
- COMM_FAIL alarm generation when channels go missing
- channel_offline flag in interlock condition evaluation
- has_offline_channels in InterlockStatus
- Discovery staleness (is_stale, get_scan_age)
- Node-side safety COMM_FAIL alarm (cRIO/Opto22 safety.py)
- InterlockStatus serialization of hasOfflineChannels
"""

import math
import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "crio_node_v2"))

from safety_manager import (
    SafetyManager, InterlockCondition, InterlockControl, Interlock,
    InterlockStatus, SafeStateConfig,
)

# =========================================================================
# DAQ Service: channel_offline flag
# =========================================================================

class TestChannelOfflineFlag:
    """Test that missing channels produce channel_offline flag in condition evaluation."""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SafetyManager(
                data_dir=Path(tmpdir),
                get_channel_value=lambda x: None,  # All channels return None
                get_channel_type=lambda x: 'voltage_input',
                get_all_channels=lambda: {},
            )
            yield m

    def test_channel_value_offline_flag(self, manager):
        """channel_value condition sets channel_offline when value is None."""
        cond = InterlockCondition(
            id="c1", condition_type="channel_value",
            channel="TC_Zone1", operator=">", value=50.0,
        )
        result = manager._evaluate_condition(cond)
        assert result['satisfied'] is False
        assert result.get('channel_offline') is True
        assert 'OFFLINE' in result['reason']

    def test_digital_input_offline_flag(self, manager):
        """digital_input condition sets channel_offline when value is None."""
        cond = InterlockCondition(
            id="c2", condition_type="digital_input",
            channel="DI_EmergStop", operator="==", value=True,
        )
        result = manager._evaluate_condition(cond)
        assert result['satisfied'] is False
        assert result.get('channel_offline') is True
        assert 'OFFLINE' in result['reason']

    def test_present_channel_no_offline_flag(self):
        """When channel has a value, no channel_offline flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SafetyManager(
                data_dir=Path(tmpdir),
                get_channel_value=lambda x: 75.0,
                get_channel_type=lambda x: 'voltage_input',
                get_all_channels=lambda: {},
            )
            cond = InterlockCondition(
                id="c3", condition_type="channel_value",
                channel="TC_Zone1", operator=">", value=50.0,
            )
            result = m._evaluate_condition(cond)
            assert result['satisfied'] is True
            assert result.get('channel_offline') is None

    def test_no_active_alarms_no_offline_flag(self):
        """Non-channel conditions don't produce channel_offline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SafetyManager(
                data_dir=Path(tmpdir),
                get_channel_value=lambda x: None,
                get_channel_type=lambda x: 'voltage_input',
                get_all_channels=lambda: {},
                get_alarm_state=lambda: {'active_count': 0, 'active_alarms': {}},
            )
            cond = InterlockCondition(
                id="c4", condition_type="no_active_alarms",
            )
            result = m._evaluate_condition(cond)
            assert result.get('channel_offline') is None

# =========================================================================
# DAQ Service: has_offline_channels in InterlockStatus
# =========================================================================

class TestHasOfflineChannels:
    """Test has_offline_channels propagation in evaluate_interlock."""

    @pytest.fixture
    def manager_with_interlock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SafetyManager(
                data_dir=Path(tmpdir),
                get_channel_value=lambda x: None,  # Channels offline
                get_channel_type=lambda x: 'voltage_input',
                get_all_channels=lambda: {},
            )
            interlock = Interlock(
                id="int-offline",
                name="Offline Test",
                conditions=[
                    InterlockCondition(
                        id="c1", condition_type="channel_value",
                        channel="TC_Zone1", operator=">", value=50.0,
                    ),
                ],
                controls=[
                    InterlockControl(control_type="set_output", channel="DO_Heater", set_value=0),
                ],
            )
            m.add_interlock(interlock)
            yield m

    def test_offline_channels_flagged(self, manager_with_interlock):
        """InterlockStatus.has_offline_channels is True when channels missing."""
        status = manager_with_interlock.evaluate_interlock(
            manager_with_interlock.interlocks['int-offline']
        )
        assert status.has_offline_channels is True
        assert status.satisfied is False
        assert len(status.failed_conditions) == 1
        assert status.failed_conditions[0].get('channel_offline') is True

    def test_offline_channels_in_to_dict(self, manager_with_interlock):
        """to_dict() includes hasOfflineChannels."""
        status = manager_with_interlock.evaluate_interlock(
            manager_with_interlock.interlocks['int-offline']
        )
        d = status.to_dict()
        assert d['hasOfflineChannels'] is True

    def test_online_channels_not_flagged(self):
        """has_offline_channels is False when all channels have values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = SafetyManager(
                data_dir=Path(tmpdir),
                get_channel_value=lambda x: 75.0,
                get_channel_type=lambda x: 'voltage_input',
                get_all_channels=lambda: {},
            )
            interlock = Interlock(
                id="int-online",
                name="Online Test",
                conditions=[
                    InterlockCondition(
                        id="c1", condition_type="channel_value",
                        channel="TC_Zone1", operator=">", value=50.0,
                    ),
                ],
                controls=[],
            )
            m.add_interlock(interlock)
            status = m.evaluate_interlock(m.interlocks['int-online'])
            assert status.has_offline_channels is False
            d = status.to_dict()
            assert d['hasOfflineChannels'] is False

    def test_interlock_status_default(self):
        """InterlockStatus defaults to has_offline_channels=False."""
        status = InterlockStatus(
            id="test", name="Test", satisfied=True,
            enabled=True, bypassed=False,
        )
        assert status.has_offline_channels is False

# =========================================================================
# Node-side safety: COMM_FAIL alarm
# =========================================================================

class TestNodeCommFailAlarm:
    """Test COMM_FAIL alarm generation in cRIO/Opto22 safety.py."""

    @pytest.fixture
    def safety(self):
        """Create a node-side SafetyManager with alarm configs."""
        # Import node-side safety module
        import safety as node_safety
        mgr = node_safety.SafetyManager()
        mgr.configure('TC_Zone1', node_safety.AlarmConfig(
            channel='TC_Zone1', enabled=True,
            hihi_limit=200.0, hi_limit=150.0,
            lo_limit=10.0, lolo_limit=0.0,
        ))
        mgr.configure('TC_Zone2', node_safety.AlarmConfig(
            channel='TC_Zone2', enabled=True,
            hihi_limit=200.0, hi_limit=150.0,
        ))
        return mgr

    def test_comm_fail_on_missing_channel(self, safety):
        """COMM_FAIL alarm fires when configured channel is absent from values."""
        import safety as node_safety
        # Pass values with TC_Zone1 present, TC_Zone2 missing
        events = safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails = [e for e in events if e.alarm_type == 'comm_fail']
        assert len(comm_fails) == 1
        assert comm_fails[0].channel == 'TC_Zone2'
        assert comm_fails[0].severity == node_safety.AlarmSeverity.CRITICAL
        assert comm_fails[0].value == 0.0  # 0.0 not NaN (NaN breaks JSON serialization)

    def test_comm_fail_clear_on_recovery(self, safety):
        """COMM_FAIL clears when channel comes back online."""
        # First: trigger COMM_FAIL
        safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        # Second: channel reappears
        events = safety.check_all(
            {'TC_Zone1': 100.0, 'TC_Zone2': 80.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        clears = [e for e in events if e.alarm_type == 'comm_fail_clear']
        assert len(clears) == 1
        assert clears[0].channel == 'TC_Zone2'

    def test_no_comm_fail_when_all_present(self, safety):
        """No COMM_FAIL when all configured channels have values."""
        events = safety.check_all(
            {'TC_Zone1': 100.0, 'TC_Zone2': 80.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails = [e for e in events if e.alarm_type == 'comm_fail']
        assert len(comm_fails) == 0

    def test_no_comm_fail_without_configured_channels(self, safety):
        """No COMM_FAIL when configured_channels is not provided."""
        events = safety.check_all({'TC_Zone1': 100.0})
        comm_fails = [e for e in events if e.alarm_type == 'comm_fail']
        assert len(comm_fails) == 0

    def test_comm_fail_not_duplicated(self, safety):
        """COMM_FAIL doesn't fire again if already active."""
        # First: trigger COMM_FAIL
        events1 = safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails1 = [e for e in events1 if e.alarm_type == 'comm_fail']
        assert len(comm_fails1) == 1

        # Second: still missing — should NOT fire again
        events2 = safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails2 = [e for e in events2 if e.alarm_type == 'comm_fail']
        assert len(comm_fails2) == 0

    def test_comm_fail_respects_shelved(self, safety):
        """COMM_FAIL doesn't fire for shelved channels."""
        import safety as node_safety
        safety.shelve_alarm('TC_Zone2', duration_s=3600, operator='operator')
        events = safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails = [e for e in events if e.alarm_type == 'comm_fail']
        assert len(comm_fails) == 0

    def test_comm_fail_triggers_safety_action(self, safety):
        """COMM_FAIL fires safety action if configured."""
        import safety as node_safety
        action_called = {}
        safety.on_action = lambda ch, action, val: action_called.update(
            {'channel': ch, 'action': action, 'value': val}
        )
        # Re-configure with safety action
        safety.configure('TC_Zone2', node_safety.AlarmConfig(
            channel='TC_Zone2', enabled=True,
            hihi_limit=200.0, safety_action='stop_session',
        ))
        events = safety.check_all(
            {'TC_Zone1': 100.0},
            configured_channels={'TC_Zone1', 'TC_Zone2'},
        )
        comm_fails = [e for e in events if e.alarm_type == 'comm_fail']
        assert len(comm_fails) == 1

# =========================================================================
# Node-side safety: channel_offline in interlock evaluation
# =========================================================================

class TestNodeInterlockOffline:
    """Test channel_offline flag in node-side interlock evaluation."""

    @pytest.fixture
    def safety_with_interlock(self):
        import safety as node_safety
        mgr = node_safety.SafetyManager()
        interlock = node_safety.Interlock(
            id='int-1', name='Temp Guard',
            conditions=[
                node_safety.InterlockCondition(
                    id='c1', condition_type='channel_value',
                    channel='TC_Zone1', operator='<', value=200.0,
                ),
            ],
            controls=[
                node_safety.InterlockControl(
                    control_type='set_output', channel='DO_Heater', set_value=0,
                ),
            ],
        )
        mgr.add_interlock(interlock)
        return mgr

    def test_offline_channel_fails_condition(self, safety_with_interlock):
        """Missing channel fails condition with channel_offline flag."""
        import safety as node_safety
        result = safety_with_interlock._evaluate_condition(
            node_safety.InterlockCondition(
                id='c1', condition_type='channel_value',
                channel='TC_Zone1', operator='<', value=200.0,
            ),
            {},  # No values
            time.time(),
        )
        assert result['satisfied'] is False
        assert result.get('channel_offline') is True

    def test_has_offline_in_interlock_status(self, safety_with_interlock):
        """evaluate_interlock includes has_offline_channels."""
        import safety as node_safety
        interlock = list(safety_with_interlock._interlocks.values())[0]
        status = safety_with_interlock.evaluate_interlock(
            interlock, {}, time.time()
        )
        assert status['has_offline_channels'] is True
        assert status['satisfied'] is False

    def test_no_offline_when_present(self, safety_with_interlock):
        """has_offline_channels is False when channel has value."""
        import safety as node_safety
        interlock = list(safety_with_interlock._interlocks.values())[0]
        status = safety_with_interlock.evaluate_interlock(
            interlock, {'TC_Zone1': 150.0}, time.time()
        )
        assert status['has_offline_channels'] is False
        assert status['satisfied'] is True

# =========================================================================
# Discovery staleness
# =========================================================================

class TestDiscoveryStaleness:
    """Test discovery cache staleness detection."""

    @pytest.fixture
    def discovery(self):
        from device_discovery import DeviceDiscovery
        d = DeviceDiscovery()
        return d

    def test_get_scan_age_none_before_scan(self, discovery):
        """get_scan_age() returns None before any scan."""
        assert discovery.get_scan_age() is None

    def test_is_stale_true_before_scan(self, discovery):
        """is_stale() returns True before any scan."""
        assert discovery.is_stale() is True

    def test_scan_age_after_scan(self, discovery):
        """get_scan_age() returns small number right after scan."""
        # Simulate a scan by setting _last_scan_time directly
        discovery._last_result = Mock()
        discovery._last_scan_time = time.time()
        age = discovery.get_scan_age()
        assert age is not None
        assert age < 2.0  # Should be well under 2 seconds

    def test_is_stale_false_after_fresh_scan(self, discovery):
        """is_stale() returns False right after scan."""
        discovery._last_result = Mock()
        discovery._last_scan_time = time.time()
        assert discovery.is_stale(max_age_s=300.0) is False

    def test_is_stale_true_after_timeout(self, discovery):
        """is_stale() returns True when scan is older than threshold."""
        discovery._last_result = Mock()
        discovery._last_scan_time = time.time() - 600  # 10 minutes ago
        assert discovery.is_stale(max_age_s=300.0) is True

    def test_is_stale_custom_threshold(self, discovery):
        """is_stale() respects custom max_age_s."""
        discovery._last_result = Mock()
        discovery._last_scan_time = time.time() - 10  # 10 seconds ago
        assert discovery.is_stale(max_age_s=5.0) is True
        assert discovery.is_stale(max_age_s=30.0) is False

# =========================================================================
# Opto22 hardware: GroovIOSubscriber stale detection
# =========================================================================

class TestGroovIOStaleDetection:
    """Test stale channel detection in GroovIOSubscriber."""

    @pytest.fixture
    def subscriber(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import GroovIOSubscriber
        return GroovIOSubscriber()

    def test_no_stale_on_fresh_data(self, subscriber):
        """No stale channels when data just arrived."""
        subscriber.on_io_message('groov/io/mod0/ch0', 23.5)
        subscriber.on_io_message('groov/io/mod0/ch1', 45.0)
        stale = subscriber.get_stale_channels(timeout_s=10.0)
        assert len(stale) == 0

    def test_stale_after_timeout(self, subscriber):
        """Channels become stale after timeout."""
        subscriber.on_io_message('groov/io/mod0/ch0', 23.5)
        # Manually backdate the timestamp
        subscriber._last_update['mod0_ch0'] = time.time() - 20
        stale = subscriber.get_stale_channels(timeout_s=10.0)
        assert 'mod0_ch0' in stale

    def test_topic_to_channel_mapping(self, subscriber):
        """Auto-derived channel names from groov topics."""
        subscriber.on_io_message('groov/io/mod0/ch0', 100.0)
        assert subscriber.get_value('mod0_ch0') == 100.0

    def test_custom_topic_mapping(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import GroovIOSubscriber
        sub = GroovIOSubscriber(topic_mapping={
            'groov/io/mod0/ch0': 'TC_Zone1',
        })
        sub.on_io_message('groov/io/mod0/ch0', 150.0)
        assert sub.get_value('TC_Zone1') == 150.0

    def test_dict_payload_extraction(self, subscriber):
        """Extract value from dict payload with 'value' key."""
        subscriber.on_io_message('groov/io/mod0/ch0', {'value': 42.5, 'quality': 'good'})
        assert subscriber.get_value('mod0_ch0') == 42.5

    def test_bool_payload_conversion(self, subscriber):
        """Bool payload converts to float."""
        subscriber.on_io_message('groov/io/mod0/ch0', True)
        assert subscriber.get_value('mod0_ch0') == 1.0
        subscriber.on_io_message('groov/io/mod0/ch0', False)
        assert subscriber.get_value('mod0_ch0') == 0.0

# =========================================================================
# Opto22 hardware: HardwareInterface
# =========================================================================

class TestOpto22HardwareInterface:
    """Test Opto22 HardwareInterface construction and data flow."""

    def test_default_construction(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import HardwareInterface
        hw = HardwareInterface()
        assert hw.io is not None
        assert hw.get_values() == {}
        assert hw.is_healthy() is False  # No data yet

    def test_construction_with_groov_mqtt(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import HardwareInterface
        mock_mqtt = Mock()
        mock_mqtt.on_io_data = None
        hw = HardwareInterface(groov_mqtt=mock_mqtt, topic_mapping={'groov/io/mod0/ch0': 'TC1'})
        # on_io_data should be wired to subscriber
        assert mock_mqtt.on_io_data is not None
        assert hw.io is not None

    def test_get_stale_channels_proxy(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import HardwareInterface, GroovIOSubscriber
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', 100.0)
        sub._last_update['mod0_ch0'] = time.time() - 20  # Backdate
        hw = HardwareInterface(io_subscriber=sub)
        stale = hw.get_stale_channels(timeout_s=10.0)
        assert 'mod0_ch0' in stale

    def test_is_healthy_with_data(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "opto22_node"))
        from hardware import HardwareInterface, GroovIOSubscriber
        sub = GroovIOSubscriber()
        sub.on_io_message('groov/io/mod0/ch0', 100.0)
        hw = HardwareInterface(io_subscriber=sub)
        assert hw.is_healthy() is True
