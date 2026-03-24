"""
Unit tests for Watchdog Engine

Tests channel monitoring for stale data, out-of-range values,
rate exceeded, and stuck values. No hardware or MQTT required.
"""

import pytest
import time
import sys
from pathlib import Path

# Add services to path
services_dir = Path(__file__).parent.parent / "services" / "daq_service"
sys.path.insert(0, str(services_dir))

from watchdog_engine import (
    WatchdogEngine, Watchdog, WatchdogCondition, WatchdogAction,
    WatchdogConditionType, WatchdogActionType, ChannelTracker,
    AutomationRunMode
)

class TestWatchdogCondition:
    """Tests for WatchdogCondition dataclass"""

    def test_create_stale_data_condition(self):
        """Test creating a stale data condition"""
        cond = WatchdogCondition(
            condition_type=WatchdogConditionType.STALE_DATA,
            max_stale_ms=5000
        )
        assert cond.condition_type == WatchdogConditionType.STALE_DATA
        assert cond.max_stale_ms == 5000

    def test_create_out_of_range_condition(self):
        """Test creating an out of range condition"""
        cond = WatchdogCondition(
            condition_type=WatchdogConditionType.OUT_OF_RANGE,
            min_value=0.0,
            max_value=100.0
        )
        assert cond.min_value == 0.0
        assert cond.max_value == 100.0

    def test_from_dict(self):
        """Test creating condition from dictionary"""
        data = {
            'type': 'out_of_range',
            'minValue': 10,
            'maxValue': 90
        }
        cond = WatchdogCondition.from_dict(data)
        assert cond.condition_type == WatchdogConditionType.OUT_OF_RANGE
        assert cond.min_value == 10
        assert cond.max_value == 90

class TestWatchdogAction:
    """Tests for WatchdogAction dataclass"""

    def test_create_notification_action(self):
        """Test creating a notification action"""
        action = WatchdogAction(
            action_type=WatchdogActionType.NOTIFICATION,
            message="Data quality issue detected!"
        )
        assert action.action_type == WatchdogActionType.NOTIFICATION
        assert action.message == "Data quality issue detected!"

    def test_create_set_output_action(self):
        """Test creating a setOutput action"""
        action = WatchdogAction(
            action_type=WatchdogActionType.SET_OUTPUT,
            channel="safety_relay",
            value=0.0
        )
        assert action.channel == "safety_relay"
        assert action.value == 0.0

    def test_from_dict(self):
        """Test creating action from dictionary"""
        data = {
            'type': 'alarm',
            'message': 'Sensor failure!',
            'alarmSeverity': 'critical'
        }
        action = WatchdogAction.from_dict(data)
        assert action.action_type == WatchdogActionType.ALARM
        assert action.alarm_severity == 'critical'

class TestWatchdog:
    """Tests for Watchdog dataclass"""

    def test_create_watchdog(self):
        """Test creating a watchdog"""
        wd = Watchdog(
            id="wd1",
            name="Temperature Monitor",
            description="Monitors temperature sensors for data quality",
            enabled=True,
            channels=["TC1", "TC2", "TC3"],
            condition=WatchdogCondition(
                condition_type=WatchdogConditionType.OUT_OF_RANGE,
                min_value=-50,
                max_value=200
            ),
            actions=[
                WatchdogAction(action_type=WatchdogActionType.NOTIFICATION, message="Temp out of range")
            ]
        )
        assert wd.id == "wd1"
        assert len(wd.channels) == 3
        assert wd.is_triggered == False

    def test_from_dict(self):
        """Test creating watchdog from dictionary"""
        data = {
            'id': 'stale_check',
            'name': 'Stale Data Check',
            'description': 'Monitors for stale sensor data',
            'enabled': True,
            'channels': ['sensor1', 'sensor2'],
            'condition': {
                'type': 'stale_data',
                'maxStaleMs': 3000
            },
            'actions': [
                {'type': 'notification', 'message': 'Data is stale!'}
            ],
            'recoveryActions': [
                {'type': 'notification', 'message': 'Data recovered'}
            ],
            'autoRecover': True,
            'cooldownMs': 5000
        }
        wd = Watchdog.from_dict(data)
        assert wd.id == 'stale_check'
        assert len(wd.channels) == 2
        assert wd.condition.max_stale_ms == 3000
        assert len(wd.recovery_actions) == 1
        assert wd.auto_recover == True

    def test_to_dict(self):
        """Test exporting watchdog to dictionary"""
        wd = Watchdog(
            id="test",
            name="Test",
            description="Test watchdog",
            enabled=True,
            channels=["ch1"],
            condition=WatchdogCondition(condition_type=WatchdogConditionType.STALE_DATA),
            actions=[]
        )
        wd.is_triggered = True
        wd.triggered_channels = ["ch1"]

        data = wd.to_dict()
        assert data['id'] == 'test'
        assert data['isTriggered'] == True
        assert 'ch1' in data['triggeredChannels']

class TestChannelTracker:
    """Tests for ChannelTracker"""

    def test_create_tracker(self):
        """Test creating a channel tracker"""
        tracker = ChannelTracker()
        assert tracker.last_value is None
        assert tracker.last_update_time is None
        assert tracker.stuck_since is None
        assert len(tracker.rate_history) == 0

class TestWatchdogEngine:
    """Tests for WatchdogEngine class"""

    def test_create_engine(self):
        """Test creating watchdog engine"""
        engine = WatchdogEngine()
        assert len(engine.watchdogs) == 0
        assert engine._is_acquiring == False

    def test_load_from_project(self):
        """Test loading watchdogs from project data"""
        engine = WatchdogEngine()
        project_data = {
            'scripts': {
                'watchdogs': [
                    {
                        'id': 'wd1',
                        'name': 'Watchdog 1',
                        'enabled': True,
                        'channels': ['ch1', 'ch2'],
                        'condition': {'type': 'stale_data', 'maxStaleMs': 5000},
                        'actions': [{'type': 'notification', 'message': 'Stale!'}]
                    },
                    {
                        'id': 'wd2',
                        'name': 'Watchdog 2',
                        'enabled': False,
                        'channels': ['ch3'],
                        'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                        'actions': []
                    }
                ]
            }
        }

        count = engine.load_from_project(project_data)
        assert count == 2
        assert 'wd1' in engine.watchdogs
        assert 'wd2' in engine.watchdogs
        # Channel trackers should be created
        assert 'ch1' in engine.channel_trackers
        assert 'ch2' in engine.channel_trackers
        assert 'ch3' in engine.channel_trackers

    def test_clear(self):
        """Test clearing watchdogs"""
        engine = WatchdogEngine()
        engine.watchdogs['test'] = Watchdog(
            id='test', name='Test', description='', enabled=True,
            channels=['ch1'],
            condition=WatchdogCondition(condition_type=WatchdogConditionType.STALE_DATA),
            actions=[]
        )
        engine.channel_trackers['ch1'] = ChannelTracker()

        engine.clear()
        assert len(engine.watchdogs) == 0
        assert len(engine.channel_trackers) == 0

class TestAcquisitionControl:
    """Tests for acquisition state management"""

    def test_acquisition_start(self):
        """Test acquisition start callback"""
        engine = WatchdogEngine()
        engine.on_acquisition_start()
        assert engine._is_acquiring == True

    def test_acquisition_stop(self):
        """Test acquisition stop callback"""
        engine = WatchdogEngine()
        engine.on_acquisition_start()
        engine.on_acquisition_stop()
        assert engine._is_acquiring == False

    def test_session_control(self):
        """Test session start/stop"""
        engine = WatchdogEngine()
        engine.on_session_start()
        assert engine._is_session_active == True
        engine.on_session_stop()
        assert engine._is_session_active == False

class TestStaleDataDetection:
    """Tests for stale data detection"""

    @pytest.fixture
    def engine(self):
        """Create engine with stale data watchdog"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_stale_data_triggers(self, engine):
        """Test that stale data triggers watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'stale_wd',
                    'name': 'Stale Monitor',
                    'enabled': True,
                    'channels': ['sensor1'],
                    'condition': {'type': 'stale_data', 'maxStaleMs': 100},  # 100ms
                    'actions': [{'type': 'notification', 'message': 'Stale data!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Use time.monotonic() to match the engine's internal clock
        now = time.monotonic()
        old_timestamp = now - 0.5  # 500ms ago

        # Process with old timestamp
        engine.process_scan({'sensor1': 50.0}, {'sensor1': old_timestamp})

        assert len(engine.notifications) == 1
        assert engine.watchdogs['stale_wd'].is_triggered == True

    def test_fresh_data_no_trigger(self, engine):
        """Test that fresh data doesn't trigger"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'stale_wd',
                    'name': 'Stale Monitor',
                    'enabled': True,
                    'channels': ['sensor1'],
                    'condition': {'type': 'stale_data', 'maxStaleMs': 5000},
                    'actions': [{'type': 'notification', 'message': 'Stale data!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Use time.monotonic() to match the engine's internal clock
        now = time.monotonic()
        fresh_timestamp = now - 0.1  # 100ms ago, within 5000ms limit

        engine.process_scan({'sensor1': 50.0}, {'sensor1': fresh_timestamp})

        assert len(engine.notifications) == 0
        assert engine.watchdogs['stale_wd'].is_triggered == False

class TestOutOfRangeDetection:
    """Tests for out-of-range detection"""

    @pytest.fixture
    def engine(self):
        """Create engine with out-of-range watchdog"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_below_minimum_triggers(self, engine):
        """Test value below minimum triggers watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['level'],
                    'condition': {'type': 'out_of_range', 'minValue': 10, 'maxValue': 90},
                    'actions': [{'type': 'notification', 'message': 'Out of range!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Value below minimum
        engine.process_scan({'level': 5.0})

        assert len(engine.notifications) == 1
        assert engine.watchdogs['range_wd'].is_triggered == True

    def test_above_maximum_triggers(self, engine):
        """Test value above maximum triggers watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['temp'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Too high!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Value above maximum
        engine.process_scan({'temp': 150.0})

        assert len(engine.notifications) == 1

    def test_within_range_no_trigger(self, engine):
        """Test value within range doesn't trigger"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['pressure'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Out of range!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Value within range
        engine.process_scan({'pressure': 50.0})

        assert len(engine.notifications) == 0

    def test_nan_value_not_triggered(self, engine):
        """Test that NaN values don't trigger out-of-range"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['sensor'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Out of range!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # NaN value - should not trigger out_of_range (separate concern)
        engine.process_scan({'sensor': float('nan')})

        assert len(engine.notifications) == 0

class TestRateExceededDetection:
    """Tests for rate-exceeded detection"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_rate_exceeded_triggers(self, engine):
        """Test rapid rate of change triggers watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'rate_wd',
                    'name': 'Rate Monitor',
                    'enabled': True,
                    'channels': ['temp'],
                    'condition': {'type': 'rate_exceeded', 'maxRatePerMin': 10},  # 10 units/min
                    'actions': [{'type': 'notification', 'message': 'Rate exceeded!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # First reading
        engine.process_scan({'temp': 50.0})

        # Wait a tiny bit then large jump (simulating very fast rate)
        time.sleep(0.1)
        engine.process_scan({'temp': 100.0})  # 50 units in 0.1 sec = 30000/min >> 10/min

        assert len(engine.notifications) == 1

    def test_slow_rate_no_trigger(self, engine):
        """Test slow rate of change doesn't trigger"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'rate_wd',
                    'name': 'Rate Monitor',
                    'enabled': True,
                    'channels': ['level'],
                    'condition': {'type': 'rate_exceeded', 'maxRatePerMin': 1000},  # High limit
                    'actions': [{'type': 'notification', 'message': 'Rate exceeded!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Small changes over time
        engine.process_scan({'level': 50.0})
        time.sleep(0.1)
        engine.process_scan({'level': 51.0})

        assert len(engine.notifications) == 0

class TestStuckValueDetection:
    """Tests for stuck value detection"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_stuck_value_triggers(self, engine):
        """Test stuck value triggers after duration"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'stuck_wd',
                    'name': 'Stuck Monitor',
                    'enabled': True,
                    'channels': ['flow'],
                    'condition': {'type': 'stuck_value', 'stuckDurationMs': 100},  # 100ms
                    'actions': [{'type': 'notification', 'message': 'Stuck value!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Same value repeatedly
        for _ in range(5):
            engine.process_scan({'flow': 42.0})
            time.sleep(0.05)

        assert len(engine.notifications) == 1

    def test_changing_value_no_trigger(self, engine):
        """Test changing values don't trigger stuck"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'stuck_wd',
                    'name': 'Stuck Monitor',
                    'enabled': True,
                    'channels': ['rpm'],
                    'condition': {'type': 'stuck_value', 'stuckDurationMs': 500},
                    'actions': [{'type': 'notification', 'message': 'Stuck value!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Changing values
        engine.process_scan({'rpm': 100.0})
        time.sleep(0.1)
        engine.process_scan({'rpm': 105.0})
        time.sleep(0.1)
        engine.process_scan({'rpm': 98.0})

        assert len(engine.notifications) == 0

class TestAutoRecovery:
    """Tests for auto-recovery functionality"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_auto_recovery_on_good_value(self, engine):
        """Test auto-recovery when condition clears"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['temp'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Out of range!'}],
                    'recoveryActions': [{'type': 'notification', 'message': 'Recovered!'}],
                    'autoRecover': True,
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Trigger with out-of-range value
        engine.process_scan({'temp': 150.0})
        assert engine.watchdogs['range_wd'].is_triggered == True

        # Recover with in-range value
        engine.process_scan({'temp': 50.0})
        assert engine.watchdogs['range_wd'].is_triggered == False

        # Should have trigger notification and recovery notification
        assert len(engine.notifications) == 2

    def test_no_auto_recovery_when_disabled(self, engine):
        """Test no auto-recovery when disabled"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'range_wd',
                    'name': 'Range Monitor',
                    'enabled': True,
                    'channels': ['level'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Out of range!'}],
                    'recoveryActions': [{'type': 'notification', 'message': 'Recovered!'}],
                    'autoRecover': False,  # Disabled
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Trigger
        engine.process_scan({'level': 150.0})
        assert engine.watchdogs['range_wd'].is_triggered == True

        # Good value - should NOT recover automatically
        engine.process_scan({'level': 50.0})
        assert engine.watchdogs['range_wd'].is_triggered == True  # Still triggered

        # Only 1 notification (trigger, no recovery)
        assert len(engine.notifications) == 1

class TestManualClear:
    """Tests for manual watchdog clearing"""

    @pytest.fixture
    def engine(self):
        """Create engine with triggered watchdog"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()

        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'test_wd',
                    'name': 'Test',
                    'enabled': True,
                    'channels': ['ch1'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'autoRecover': False,
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Trigger it
        engine.process_scan({'ch1': 150.0})
        return engine

    def test_manual_clear(self, engine):
        """Test manually clearing a triggered watchdog"""
        assert engine.watchdogs['test_wd'].is_triggered == True

        result = engine.manual_clear('test_wd')
        assert result == True
        assert engine.watchdogs['test_wd'].is_triggered == False
        assert engine.watchdogs['test_wd'].triggered_channels == []

    def test_manual_clear_nonexistent(self, engine):
        """Test clearing nonexistent watchdog"""
        result = engine.manual_clear('nonexistent')
        assert result == False

    def test_manual_clear_not_triggered(self, engine):
        """Test clearing watchdog that isn't triggered"""
        # Clear it first
        engine.manual_clear('test_wd')

        # Try to clear again
        result = engine.manual_clear('test_wd')
        assert result == False

class TestCooldown:
    """Tests for watchdog cooldown"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_cooldown_prevents_rapid_trigger(self, engine):
        """Test cooldown prevents rapid re-triggering"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Watchdog',
                    'enabled': True,
                    'channels': ['ch1'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'recoveryActions': [{'type': 'notification', 'message': 'Recovered!'}],
                    'autoRecover': True,
                    'cooldownMs': 1000  # 1 second cooldown
                }]
            }
        }
        engine.load_from_project(project_data)

        # First trigger
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 1  # 1 trigger

        # Recover - this fires recovery action
        engine.process_scan({'ch1': 50.0})
        assert len(engine.notifications) == 2  # 1 trigger + 1 recovery

        # Immediately try to trigger again (within cooldown) - should be blocked
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 2  # Still 2, no second trigger due to cooldown

class TestWatchdogActions:
    """Tests for watchdog action execution"""

    @pytest.fixture
    def engine(self):
        """Create engine with action mocks"""
        engine = WatchdogEngine()
        engine.outputs_set = []
        engine.set_output = lambda ch, val: engine.outputs_set.append((ch, val))
        engine.sequences_started = []
        engine.run_sequence = lambda seq_id: engine.sequences_started.append(seq_id)
        engine.sequences_stopped = []
        engine.stop_sequence = lambda seq_id: engine.sequences_stopped.append(seq_id)
        engine.recordings_stopped = []
        engine.stop_recording = lambda: engine.recordings_stopped.append(True)
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.alarms_raised = []
        engine.raise_alarm = lambda id, sev, msg: engine.alarms_raised.append((id, sev, msg))
        engine.on_acquisition_start()
        return engine

    def test_set_output_action(self, engine):
        """Test setOutput action execution"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Watchdog',
                    'enabled': True,
                    'channels': ['sensor'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'setOutput', 'channel': 'safety_relay', 'value': 0}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'sensor': 150.0})

        assert ('safety_relay', 0) in engine.outputs_set

    def test_run_sequence_action(self, engine):
        """Test runSequence action execution"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Watchdog',
                    'enabled': True,
                    'channels': ['level'],
                    'condition': {'type': 'out_of_range', 'minValue': 10, 'maxValue': 90},
                    'actions': [{'type': 'runSequence', 'sequenceId': 'emergency_shutdown'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'level': 5.0})

        assert 'emergency_shutdown' in engine.sequences_started

    def test_alarm_action(self, engine):
        """Test alarm action execution"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Data Quality',
                    'enabled': True,
                    'channels': ['temp'],
                    'condition': {'type': 'stuck_value', 'stuckDurationMs': 50},
                    'actions': [{'type': 'alarm', 'message': 'Sensor stuck!', 'alarmSeverity': 'critical'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Send same value repeatedly to trigger stuck
        for _ in range(5):
            engine.process_scan({'temp': 42.0})
            time.sleep(0.02)

        assert len(engine.alarms_raised) == 1
        assert engine.alarms_raised[0][1] == 'critical'

    def test_multiple_actions(self, engine):
        """Test multiple actions on single watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Critical Monitor',
                    'enabled': True,
                    'channels': ['pressure'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [
                        {'type': 'notification', 'message': 'Pressure alarm!'},
                        {'type': 'setOutput', 'channel': 'relief_valve', 'value': 1},
                        {'type': 'alarm', 'message': 'High pressure!', 'alarmSeverity': 'critical'}
                    ],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'pressure': 150.0})

        assert len(engine.notifications) == 1
        assert ('relief_valve', 1) in engine.outputs_set
        assert len(engine.alarms_raised) == 1

class TestRunModes:
    """Tests for run mode behavior"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        return engine

    def test_acquisition_mode(self, engine):
        """Test acquisition mode watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Watchdog',
                    'enabled': True,
                    'runMode': 'acquisition',
                    'channels': ['ch1'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Not acquiring - shouldn't trigger
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 0

        # Start acquisition - should trigger
        engine.on_acquisition_start()
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 1

    def test_session_mode_requires_session(self, engine):
        """Test session mode watchdog requires active session"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Watchdog',
                    'enabled': True,
                    'runMode': 'session',
                    'channels': ['ch1'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Acquiring but no session
        engine.on_acquisition_start()
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 0

        # Start session
        engine.on_session_start()
        engine.process_scan({'ch1': 150.0})
        assert len(engine.notifications) == 1

class TestMultipleChannels:
    """Tests for watchdogs monitoring multiple channels"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = WatchdogEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_any_channel_triggers(self, engine):
        """Test that any channel violating condition triggers watchdog"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Multi-channel Monitor',
                    'enabled': True,
                    'channels': ['tc1', 'tc2', 'tc3'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # Only tc2 is out of range
        engine.process_scan({'tc1': 50.0, 'tc2': 150.0, 'tc3': 50.0})

        assert engine.watchdogs['wd'].is_triggered == True
        assert 'tc2' in engine.watchdogs['wd'].triggered_channels
        assert 'tc1' not in engine.watchdogs['wd'].triggered_channels

    def test_triggered_channels_tracked(self, engine):
        """Test that all triggered channels are tracked"""
        project_data = {
            'scripts': {
                'watchdogs': [{
                    'id': 'wd',
                    'name': 'Multi-channel Monitor',
                    'enabled': True,
                    'channels': ['s1', 's2', 's3'],
                    'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                    'actions': [{'type': 'notification', 'message': 'Triggered!'}],
                    'cooldownMs': 0
                }]
            }
        }
        engine.load_from_project(project_data)

        # s1 and s3 out of range
        engine.process_scan({'s1': 150.0, 's2': 50.0, 's3': -10.0})

        triggered = engine.watchdogs['wd'].triggered_channels
        assert 's1' in triggered
        assert 's3' in triggered
        assert 's2' not in triggered

class TestStatus:
    """Tests for status reporting"""

    def test_get_status(self):
        """Test getting engine status"""
        engine = WatchdogEngine()
        project_data = {
            'scripts': {
                'watchdogs': [
                    {
                        'id': 'wd1', 'name': 'W1', 'enabled': True,
                        'channels': ['ch1'],
                        'condition': {'type': 'stale_data', 'maxStaleMs': 5000},
                        'actions': []
                    },
                    {
                        'id': 'wd2', 'name': 'W2', 'enabled': False,
                        'channels': ['ch2'],
                        'condition': {'type': 'out_of_range', 'minValue': 0, 'maxValue': 100},
                        'actions': []
                    }
                ]
            }
        }
        engine.load_from_project(project_data)

        status = engine.get_status()
        assert status['count'] == 2
        assert status['enabled'] == 1
        assert status['triggered'] == 0
        assert 'wd1' in status['watchdogs']

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
