"""
Unit tests for Trigger Engine

Tests trigger condition evaluation, action execution, cooldown,
one-shot behavior, and various trigger types. No hardware or MQTT required.
"""

import pytest
import time
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

# Add services to path
services_dir = Path(__file__).parent.parent / "services" / "daq_service"
sys.path.insert(0, str(services_dir))

from trigger_engine import (
    TriggerEngine, AutomationTrigger, TriggerCondition, TriggerAction,
    TriggerType, TriggerActionType, AutomationRunMode
)

class TestTriggerCondition:
    """Tests for TriggerCondition dataclass"""

    def test_create_value_reached_condition(self):
        """Test creating a valueReached condition"""
        cond = TriggerCondition(
            trigger_type=TriggerType.VALUE_REACHED,
            channel="temperature",
            operator=">",
            threshold=100.0,
            hysteresis=2.0
        )
        assert cond.trigger_type == TriggerType.VALUE_REACHED
        assert cond.channel == "temperature"
        assert cond.threshold == 100.0

    def test_from_dict_value_reached(self):
        """Test creating condition from dict"""
        data = {
            'type': 'valueReached',
            'channel': 'pressure',
            'operator': '>=',
            'value': 50.0,
            'hysteresis': 1.0
        }
        cond = TriggerCondition.from_dict(data)
        assert cond.trigger_type == TriggerType.VALUE_REACHED
        assert cond.channel == 'pressure'
        assert cond.threshold == 50.0

    def test_from_dict_time_elapsed(self):
        """Test creating time elapsed condition"""
        data = {
            'type': 'timeElapsed',
            'durationMs': 5000,
            'startEvent': 'acquisitionStart'
        }
        cond = TriggerCondition.from_dict(data)
        assert cond.trigger_type == TriggerType.TIME_ELAPSED
        assert cond.duration_ms == 5000
        assert cond.start_event == 'acquisitionStart'

    def test_from_dict_scheduled(self):
        """Test creating scheduled condition"""
        data = {
            'type': 'scheduled',
            'schedule': {
                'type': 'daily',
                'time': '14:30'
            }
        }
        cond = TriggerCondition.from_dict(data)
        assert cond.trigger_type == TriggerType.SCHEDULED
        assert cond.schedule_type == 'daily'
        assert cond.schedule_time == '14:30'

class TestTriggerAction:
    """Tests for TriggerAction dataclass"""

    def test_create_set_output_action(self):
        """Test creating setOutput action"""
        action = TriggerAction(
            action_type=TriggerActionType.SET_OUTPUT,
            channel="valve1",
            value=1.0
        )
        assert action.action_type == TriggerActionType.SET_OUTPUT
        assert action.channel == "valve1"

    def test_from_dict(self):
        """Test creating action from dict"""
        data = {
            'type': 'startSequence',
            'sequenceId': 'shutdown_seq'
        }
        action = TriggerAction.from_dict(data)
        assert action.action_type == TriggerActionType.START_SEQUENCE
        assert action.sequence_id == 'shutdown_seq'

    def test_run_sequence_alias(self):
        """Test that runSequence is aliased to startSequence"""
        data = {'type': 'runSequence', 'sequenceId': 'test'}
        action = TriggerAction.from_dict(data)
        assert action.action_type == TriggerActionType.START_SEQUENCE

class TestAutomationTrigger:
    """Tests for AutomationTrigger dataclass"""

    def test_create_trigger(self):
        """Test creating a complete trigger"""
        trigger = AutomationTrigger(
            id="trig1",
            name="High Temp Alarm",
            description="Triggers when temperature exceeds limit",
            enabled=True,
            one_shot=False,
            cooldown_ms=5000,
            condition=TriggerCondition(
                trigger_type=TriggerType.VALUE_REACHED,
                channel="temp",
                operator=">",
                threshold=100.0
            ),
            actions=[
                TriggerAction(action_type=TriggerActionType.NOTIFICATION, message="High temp!")
            ]
        )
        assert trigger.id == "trig1"
        assert trigger.enabled == True
        assert len(trigger.actions) == 1

    def test_from_dict(self):
        """Test creating trigger from project data"""
        data = {
            'id': 'temp_high',
            'name': 'Temperature High',
            'description': 'Fire when temp > 100',
            'enabled': True,
            'oneShot': True,
            'cooldownMs': 10000,
            'trigger': {
                'type': 'valueReached',
                'channel': 'TC1',
                'operator': '>',
                'value': 100.0
            },
            'actions': [
                {'type': 'notification', 'message': 'Temperature exceeded!'},
                {'type': 'setOutput', 'channel': 'alarm_light', 'value': 1}
            ]
        }
        trigger = AutomationTrigger.from_dict(data)
        assert trigger.id == 'temp_high'
        assert trigger.one_shot == True
        assert trigger.cooldown_ms == 10000
        assert len(trigger.actions) == 2

    def test_run_mode_default(self):
        """Test that default run mode is acquisition"""
        data = {
            'id': 'test',
            'name': 'Test',
            'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 0},
            'actions': []
        }
        trigger = AutomationTrigger.from_dict(data)
        assert trigger.run_mode == AutomationRunMode.ACQUISITION

    def test_run_mode_session(self):
        """Test session run mode"""
        data = {
            'id': 'test',
            'name': 'Test',
            'runMode': 'session',
            'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 0},
            'actions': []
        }
        trigger = AutomationTrigger.from_dict(data)
        assert trigger.run_mode == AutomationRunMode.SESSION

class TestTriggerEngine:
    """Tests for TriggerEngine class"""

    def test_create_engine(self):
        """Test creating trigger engine"""
        engine = TriggerEngine()
        assert len(engine.triggers) == 0
        assert engine._is_acquiring == False

    def test_load_from_project(self):
        """Test loading triggers from project data"""
        engine = TriggerEngine()
        project_data = {
            'scripts': {
                'triggers': [
                    {
                        'id': 'trig1',
                        'name': 'Trigger 1',
                        'enabled': True,
                        'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 50},
                        'actions': [{'type': 'notification', 'message': 'Fired!'}]
                    },
                    {
                        'id': 'trig2',
                        'name': 'Trigger 2',
                        'enabled': False,
                        'trigger': {'type': 'valueReached', 'channel': 'ch2', 'operator': '<', 'value': 10},
                        'actions': []
                    }
                ]
            }
        }

        count = engine.load_from_project(project_data)
        assert count == 2
        assert 'trig1' in engine.triggers
        assert 'trig2' in engine.triggers

    def test_clear(self):
        """Test clearing triggers"""
        engine = TriggerEngine()
        engine.triggers['test'] = AutomationTrigger(
            id='test', name='Test', description='', enabled=True,
            one_shot=False, cooldown_ms=1000,
            condition=TriggerCondition(trigger_type=TriggerType.VALUE_REACHED),
            actions=[]
        )

        engine.clear()
        assert len(engine.triggers) == 0

class TestAcquisitionControl:
    """Tests for acquisition state management"""

    def test_acquisition_start(self):
        """Test acquisition start callback"""
        engine = TriggerEngine()
        engine.on_acquisition_start()

        assert engine._is_acquiring == True
        assert engine._acquisition_start_time is not None

    def test_acquisition_stop(self):
        """Test acquisition stop callback"""
        engine = TriggerEngine()
        engine.on_acquisition_start()
        engine.on_acquisition_stop()

        assert engine._is_acquiring == False
        assert engine._acquisition_start_time is None

    def test_triggers_inactive_without_acquisition(self):
        """Test that triggers don't fire when not acquiring"""
        engine = TriggerEngine()
        fired = []
        engine.publish_notification = lambda t, n, m: fired.append((t, n, m))

        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 50},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Process without starting acquisition
        engine.process_scan({'ch1': 100.0})

        assert len(fired) == 0

class TestValueReachedTrigger:
    """Tests for valueReached trigger type"""

    @pytest.fixture
    def engine(self):
        """Create engine with notifications tracking"""
        engine = TriggerEngine()
        engine.fired_triggers = []
        engine.publish_notification = lambda t, n, m: engine.fired_triggers.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_greater_than_trigger(self, engine):
        """Test > operator"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'temp', 'operator': '>', 'value': 100},
                    'actions': [{'type': 'notification', 'message': 'High temp!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Below threshold - no fire
        engine.process_scan({'temp': 50.0})
        assert len(engine.fired_triggers) == 0

        # Above threshold - should fire
        engine.process_scan({'temp': 101.0})
        assert len(engine.fired_triggers) == 1

    def test_less_than_trigger(self, engine):
        """Test < operator"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'level', 'operator': '<', 'value': 10},
                    'actions': [{'type': 'notification', 'message': 'Low level!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Above threshold first
        engine.process_scan({'level': 50.0})

        # Below threshold - should fire
        engine.process_scan({'level': 5.0})
        assert len(engine.fired_triggers) == 1

    def test_rising_edge_detection(self, engine):
        """Test that trigger only fires on rising edge"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'temp', 'operator': '>', 'value': 100},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Below threshold
        engine.process_scan({'temp': 50.0})
        # Transition above - fires
        engine.process_scan({'temp': 150.0})
        assert len(engine.fired_triggers) == 1

        # Stay above - should NOT fire again
        engine.process_scan({'temp': 160.0})
        assert len(engine.fired_triggers) == 1  # Still 1

        # Go below
        engine.process_scan({'temp': 50.0})
        # Transition above again - fires
        engine.process_scan({'temp': 150.0})
        assert len(engine.fired_triggers) == 2

    def test_disabled_trigger_skipped(self, engine):
        """Test that disabled triggers are skipped"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': False,
                    'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 0},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'ch1': 100.0})
        assert len(engine.fired_triggers) == 0

    def test_missing_channel_skipped(self, engine):
        """Test that triggers with missing channels are skipped"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'trigger': {'type': 'valueReached', 'channel': 'nonexistent', 'operator': '>', 'value': 0},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'other_channel': 100.0})
        assert len(engine.fired_triggers) == 0

class TestOneShotTrigger:
    """Tests for one-shot trigger behavior"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.fired_triggers = []
        engine.publish_notification = lambda t, n, m: engine.fired_triggers.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_one_shot_fires_once(self, engine):
        """Test that one-shot triggers only fire once"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'oneShot': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 50},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # First trigger
        engine.process_scan({'ch1': 100.0})
        assert len(engine.fired_triggers) == 1

        # Reset condition
        engine.process_scan({'ch1': 0.0})
        # Try to trigger again
        engine.process_scan({'ch1': 100.0})
        assert len(engine.fired_triggers) == 1  # Still 1

class TestCooldown:
    """Tests for trigger cooldown"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.fired_triggers = []
        engine.publish_notification = lambda t, n, m: engine.fired_triggers.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_cooldown_prevents_rapid_fire(self, engine):
        """Test that cooldown prevents rapid firing"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'oneShot': False,
                    'cooldownMs': 1000,  # 1 second cooldown
                    'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 50},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # First trigger
        engine.process_scan({'ch1': 100.0})
        assert len(engine.fired_triggers) == 1

        # Reset and immediately try again (within cooldown)
        engine.process_scan({'ch1': 0.0})
        engine.process_scan({'ch1': 100.0})
        assert len(engine.fired_triggers) == 1  # Still 1 due to cooldown

class TestTimeElapsedTrigger:
    """Tests for timeElapsed trigger type"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.fired_triggers = []
        engine.publish_notification = lambda t, n, m: engine.fired_triggers.append((t, n, m))
        return engine

    def test_time_elapsed_from_acquisition_start(self, engine):
        """Test time elapsed from acquisition start"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {
                        'type': 'timeElapsed',
                        'durationMs': 100,  # 100ms
                        'startEvent': 'acquisitionStart'
                    },
                    'actions': [{'type': 'notification', 'message': 'Time elapsed!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.on_acquisition_start()

        # Immediately - not enough time
        engine.process_scan({})
        assert len(engine.fired_triggers) == 0

        # Wait for duration
        time.sleep(0.15)
        engine.process_scan({})
        assert len(engine.fired_triggers) == 1

class TestTriggerActions:
    """Tests for trigger action execution"""

    @pytest.fixture
    def engine(self):
        """Create engine with action mocks"""
        engine = TriggerEngine()
        engine.outputs_set = []
        engine.set_output = lambda ch, val: engine.outputs_set.append((ch, val))
        engine.sequences_started = []
        engine.run_sequence = lambda seq_id: engine.sequences_started.append(seq_id)
        engine.sequences_stopped = []
        engine.stop_sequence = lambda seq_id: engine.sequences_stopped.append(seq_id)
        engine.recordings_started = []
        engine.start_recording = lambda: engine.recordings_started.append(True)
        engine.recordings_stopped = []
        engine.stop_recording = lambda: engine.recordings_stopped.append(True)
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        engine.on_acquisition_start()
        return engine

    def test_set_output_action(self, engine):
        """Test setOutput action"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'temp', 'operator': '>', 'value': 100},
                    'actions': [{'type': 'setOutput', 'channel': 'alarm_light', 'value': 1}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'temp': 150.0})

        assert ('alarm_light', 1) in engine.outputs_set

    def test_start_sequence_action(self, engine):
        """Test startSequence action"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'temp', 'operator': '>', 'value': 100},
                    'actions': [{'type': 'startSequence', 'sequenceId': 'shutdown_seq'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.process_scan({'temp': 150.0})

        assert 'shutdown_seq' in engine.sequences_started

    def test_multiple_actions(self, engine):
        """Test multiple actions on single trigger"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'level', 'operator': '<', 'value': 10},
                    'actions': [
                        {'type': 'notification', 'message': 'Low level!'},
                        {'type': 'setOutput', 'channel': 'pump', 'value': 1},
                        {'type': 'startSequence', 'sequenceId': 'refill_seq'}
                    ]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Initialize then trigger
        engine.process_scan({'level': 50.0})
        engine.process_scan({'level': 5.0})

        assert len(engine.notifications) == 1
        assert ('pump', 1) in engine.outputs_set
        assert 'refill_seq' in engine.sequences_started

class TestStateChangeTrigger:
    """Tests for stateChange trigger type"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        return engine

    def test_state_change_trigger(self, engine):
        """Test state change trigger fires on transition"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {
                        'type': 'stateChange',
                        'stateType': 'acquisition',
                        'fromState': 'stopped',
                        'toState': 'running'
                    },
                    'actions': [{'type': 'notification', 'message': 'Acquisition started!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.on_state_change('acquisition', 'stopped', 'running')

        assert len(engine.notifications) == 1

class TestSequenceEventTrigger:
    """Tests for sequenceEvent trigger type"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        return engine

    def test_sequence_completed_trigger(self, engine):
        """Test trigger fires on sequence completion"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'cooldownMs': 0,
                    'trigger': {
                        'type': 'sequenceEvent',
                        'sequenceId': 'startup_seq',
                        'event': 'completed'
                    },
                    'actions': [{'type': 'notification', 'message': 'Startup complete!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        engine.on_sequence_event('startup_seq', 'completed')

        assert len(engine.notifications) == 1

class TestRunModes:
    """Tests for run mode behavior"""

    @pytest.fixture
    def engine(self):
        """Create engine"""
        engine = TriggerEngine()
        engine.notifications = []
        engine.publish_notification = lambda t, n, m: engine.notifications.append((t, n, m))
        return engine

    def test_session_mode_requires_session(self, engine):
        """Test that session mode triggers only fire during session"""
        project_data = {
            'scripts': {
                'triggers': [{
                    'id': 'test',
                    'name': 'Test',
                    'enabled': True,
                    'runMode': 'session',
                    'cooldownMs': 0,
                    'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 50},
                    'actions': [{'type': 'notification', 'message': 'Fired!'}]
                }]
            }
        }
        engine.load_from_project(project_data)

        # Start acquisition but not session
        engine.on_acquisition_start()
        engine.process_scan({'ch1': 100.0})
        assert len(engine.notifications) == 0

        # Start session
        engine.on_session_start()
        engine.process_scan({'ch1': 0.0})  # Reset
        engine.process_scan({'ch1': 100.0})
        assert len(engine.notifications) == 1

class TestStatus:
    """Tests for status reporting"""

    def test_get_status(self):
        """Test getting engine status"""
        engine = TriggerEngine()
        project_data = {
            'scripts': {
                'triggers': [
                    {
                        'id': 'trig1', 'name': 'T1', 'enabled': True,
                        'trigger': {'type': 'valueReached', 'channel': 'ch1', 'operator': '>', 'value': 0},
                        'actions': []
                    },
                    {
                        'id': 'trig2', 'name': 'T2', 'enabled': False,
                        'trigger': {'type': 'valueReached', 'channel': 'ch2', 'operator': '<', 'value': 0},
                        'actions': []
                    }
                ]
            }
        }
        engine.load_from_project(project_data)

        status = engine.get_status()
        assert status['count'] == 2
        assert status['enabled'] == 1
        assert 'trig1' in status['triggers']

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
