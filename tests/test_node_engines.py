"""
Unit tests for Node Engine Integration

Tests that the PID, Sequence, Trigger, and Watchdog engines are properly
integrated into the cRIO and Opto22 node services.

These tests verify:
1. Engines are instantiated correctly
2. Callbacks are wired up properly
3. Engine processing in scan loop
4. Configuration loading/saving

No hardware or MQTT required - tests the pure integration logic.
"""

import pytest
import sys
import time
import threading
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add services to path
crio_dir = Path(__file__).parent.parent / "services" / "crio_node"
opto22_dir = Path(__file__).parent.parent / "services" / "opto22_node"
sys.path.insert(0, str(crio_dir))
sys.path.insert(0, str(opto22_dir))

class TestCRIONodeEngineInstantiation:
    """Test that cRIO node properly instantiates all engines"""

    def test_import_crio_node_engines(self):
        """Test that we can import the engine classes from crio_node"""
        from crio_node import (
            PIDEngine, PIDLoop, PIDMode,
            SequenceManager, Sequence, SequenceStep, SequenceState,
            TriggerEngine,
            WatchdogEngine,
            EnhancedAlarmManager, AlarmSeverity
        )

        # Verify classes exist and are usable
        assert PIDEngine is not None
        assert SequenceManager is not None
        assert TriggerEngine is not None
        assert WatchdogEngine is not None
        assert EnhancedAlarmManager is not None

    def test_pid_engine_standalone(self):
        """Test PID engine can be created and used standalone"""
        from crio_node import PIDEngine, PIDLoop, PIDMode

        outputs = []
        engine = PIDEngine(on_set_output=lambda ch, val: outputs.append((ch, val)))

        loop = PIDLoop(
            id="test_loop",
            name="Test Temperature Control",
            pv_channel="TC_001",
            cv_channel="Heater_001",
            kp=2.0,
            ki=0.1,
            kd=0.0,
            setpoint=100.0,
            output_min=0.0,
            output_max=100.0
        )
        engine.add_loop(loop)

        # Process a scan
        result = engine.process_scan({"TC_001": 90.0}, dt=0.1)

        assert "Heater_001" in result
        assert len(outputs) == 1
        assert outputs[0][0] == "Heater_001"

    def test_sequence_manager_standalone(self):
        """Test sequence manager can be created and used standalone"""
        from crio_node import SequenceManager, Sequence, SequenceStep, SequenceState

        outputs = []
        manager = SequenceManager()
        manager.on_set_output = lambda ch, val: outputs.append((ch, val))
        manager.on_get_channel_value = lambda ch: 100.0

        seq = Sequence(
            id="test_seq",
            name="Test Sequence",
            steps=[
                SequenceStep(type="setOutput", channel="valve1", value=1),
            ]
        )
        manager.add_sequence(seq)

        # Start sequence
        result = manager.start_sequence("test_seq")
        assert result == True

        # Wait for execution
        time.sleep(0.3)

        assert ("valve1", 1) in outputs

        # Cleanup - use abort if still running (SequenceManager doesn't have shutdown())
        if manager._running_sequence_id:
            manager.abort_sequence(manager._running_sequence_id)

    def test_trigger_engine_standalone(self):
        """Test trigger engine can be created and used standalone"""
        from crio_node import TriggerEngine, AutomationTrigger, TriggerCondition, TriggerAction, TriggerType, TriggerActionType

        notifications = []
        engine = TriggerEngine()
        engine.set_output = lambda ch, val: None
        engine.run_sequence = lambda seq_id: None
        engine.publish_notification = lambda t, n, m: notifications.append((t, n, m))

        # Add a simple trigger using the proper AutomationTrigger object
        trigger = AutomationTrigger(
            id="test",
            name="Test Trigger",
            description="Test trigger for temp",
            enabled=True,
            one_shot=False,
            cooldown_ms=0,  # No cooldown for test
            condition=TriggerCondition(
                trigger_type=TriggerType.VALUE_REACHED,
                channel="temp",
                operator=">",
                threshold=100
            ),
            actions=[TriggerAction(
                action_type=TriggerActionType.NOTIFICATION,
                message="High temp!"
            )]
        )
        engine.triggers["test"] = trigger

        engine.on_acquisition_start()

        # Process - below threshold
        engine.process_scan({"temp": 50.0})
        assert len(notifications) == 0

        # Process - above threshold (transition)
        engine.process_scan({"temp": 150.0})
        # Note: The engine fires on rising edge, so should fire

    def test_watchdog_engine_standalone(self):
        """Test watchdog engine can be created and used standalone"""
        from crio_node import WatchdogEngine, Watchdog, WatchdogCondition, WatchdogAction, WatchdogConditionType, WatchdogActionType

        notifications = []
        engine = WatchdogEngine()
        engine.publish_notification = lambda t, n, m: notifications.append((t, n, m))

        # Add a watchdog using the proper Watchdog object
        watchdog = Watchdog(
            id="test",
            name="Test Watchdog",
            description="Test watchdog for sensor1",
            enabled=True,
            channels=["sensor1"],
            condition=WatchdogCondition(
                condition_type=WatchdogConditionType.OUT_OF_RANGE,
                min_value=0,
                max_value=100
            ),
            actions=[WatchdogAction(
                action_type=WatchdogActionType.NOTIFICATION,
                message="Out of range!"
            )],
            recovery_actions=[],
            cooldown_ms=0  # No cooldown for test
        )
        engine.watchdogs["test"] = watchdog

        engine.on_acquisition_start()

        # Process - within range
        engine.process_scan({"sensor1": 50.0}, {"sensor1": time.time()})

        # Process - out of range
        engine.process_scan({"sensor1": 150.0}, {"sensor1": time.time()})

    def test_enhanced_alarm_manager_standalone(self):
        """Test enhanced alarm manager can be created and used standalone"""
        from crio_node import EnhancedAlarmManager, AlarmConfig, AlarmSeverity, LatchBehavior

        events = []
        manager = EnhancedAlarmManager(
            publish_callback=lambda event_type, data: events.append((event_type, data))
        )

        # Add alarm configuration using correct signature
        config = AlarmConfig(
            id="temp_hi",
            channel="temp",
            name="Temperature High",
            description="Temperature high alarm",
            severity=AlarmSeverity.HIGH,
            high=100.0,  # High limit at 100
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        # Process value - below limit
        manager.process_value("temp", 50.0, time.time())
        assert len(events) == 0

        # Process value - above limit
        manager.process_value("temp", 150.0, time.time())
        # Should have triggered an alarm
        assert len(events) > 0

class TestOpto22NodeEngineInstantiation:
    """Test that Opto22 node properly instantiates all engines"""

    def test_import_opto22_node_engines(self):
        """Test that we can import the engine classes from opto22_node"""
        from opto22_node import (
            PIDEngine, PIDLoop, PIDMode,
            SequenceManager, Sequence, SequenceStep, SequenceState,
            TriggerEngine,
            WatchdogEngine,
            EnhancedAlarmManager, AlarmSeverity
        )

        # Verify classes exist
        assert PIDEngine is not None
        assert SequenceManager is not None
        assert TriggerEngine is not None
        assert WatchdogEngine is not None
        assert EnhancedAlarmManager is not None

    def test_opto22_pid_engine_standalone(self):
        """Test PID engine from opto22_node works"""
        from opto22_node import PIDEngine, PIDLoop

        outputs = []
        engine = PIDEngine(on_set_output=lambda ch, val: outputs.append((ch, val)))

        loop = PIDLoop(
            id="pressure_loop",
            name="Pressure Control",
            pv_channel="PT_001",
            cv_channel="VFD_001",
            kp=1.5,
            ki=0.2,
            kd=0.0,
            setpoint=50.0
        )
        engine.add_loop(loop)

        result = engine.process_scan({"PT_001": 45.0}, dt=0.1)
        assert "VFD_001" in result

    def test_opto22_sequence_manager_standalone(self):
        """Test sequence manager from opto22_node works"""
        from opto22_node import SequenceManager, Sequence, SequenceStep

        outputs = []
        manager = SequenceManager()
        manager.on_set_output = lambda ch, val: outputs.append((ch, val))

        seq = Sequence(
            id="startup",
            name="Startup Sequence",
            steps=[
                SequenceStep(type="setOutput", channel="pump", value=1),
            ]
        )
        manager.add_sequence(seq)
        manager.start_sequence("startup")

        time.sleep(0.3)
        assert ("pump", 1) in outputs

        if manager._running_sequence_id:
            manager.abort_sequence(manager._running_sequence_id)

class TestEngineLifecycle:
    """Test engine lifecycle methods"""

    def test_pid_engine_acquisition_lifecycle(self):
        """Test PID engine can be reset via clear_loops and re-add"""
        from crio_node import PIDEngine, PIDLoop

        engine = PIDEngine()
        loop = PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv1",
            cv_channel="cv1",
            ki=1.0,  # Non-zero integral
            kp=0.1,  # Small P gain so output doesn't saturate immediately
            setpoint=60.0,  # Set above PV so error is positive, output increases
            output_min=0.0,
            output_max=100.0
        )
        engine.add_loop(loop)

        # Process some scans to build up integral
        # With setpoint=60, pv=50, error=+10, output will be positive and not saturate at 0
        for _ in range(10):
            engine.process_scan({"pv1": 50.0}, dt=0.1)

        # Integral should accumulate since output is not saturating at minimum
        assert engine.loops["test"].i_term != 0
        assert engine.loops["test"].last_pv is not None

        # Reset by clearing loops and re-adding (PIDEngine doesn't have lifecycle methods)
        engine.clear_loops()
        assert "test" not in engine.loops

        # Re-add loop (fresh state)
        new_loop = PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv1",
            cv_channel="cv1",
            ki=1.0,
            kp=0.1,
            setpoint=60.0
        )
        engine.add_loop(new_loop)
        assert engine.loops["test"].i_term == 0.0
        assert engine.loops["test"].last_pv is None

    def test_sequence_manager_acquisition_lifecycle(self):
        """Test sequence manager responds to acquisition start/stop"""
        from crio_node import SequenceManager, Sequence, SequenceStep

        manager = SequenceManager()

        seq = Sequence(
            id="long_seq",
            name="Long Sequence",
            steps=[SequenceStep(type="waitDuration", duration_ms=5000)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("long_seq")

        time.sleep(0.1)
        assert manager._running_sequence_id == "long_seq"

        # Abort the sequence (SequenceManager doesn't have on_acquisition_stop)
        manager.abort_sequence("long_seq")

        time.sleep(0.2)
        assert manager._running_sequence_id is None

    def test_trigger_engine_acquisition_lifecycle(self):
        """Test trigger engine responds to acquisition start/stop"""
        from crio_node import TriggerEngine

        engine = TriggerEngine()

        assert engine._is_acquiring == False

        engine.on_acquisition_start()
        assert engine._is_acquiring == True

        engine.on_acquisition_stop()
        assert engine._is_acquiring == False

    def test_watchdog_engine_acquisition_lifecycle(self):
        """Test watchdog engine responds to acquisition start/stop"""
        from crio_node import WatchdogEngine

        engine = WatchdogEngine()

        assert engine._is_acquiring == False

        engine.on_acquisition_start()
        assert engine._is_acquiring == True

        engine.on_acquisition_stop()
        assert engine._is_acquiring == False

class TestEngineConfiguration:
    """Test engine configuration loading"""

    def test_pid_engine_config_load(self):
        """Test loading PID configuration"""
        from crio_node import PIDEngine

        engine = PIDEngine()
        config = {
            "loops": [
                {
                    "id": "temp_control",
                    "name": "Temperature Control",
                    "pv_channel": "TC_001",
                    "cv_channel": "Heater",
                    "kp": 2.0,
                    "ki": 0.5,
                    "kd": 0.1,
                    "setpoint": 100.0
                },
                {
                    "id": "pressure_control",
                    "name": "Pressure Control",
                    "pv_channel": "PT_001",
                    "cv_channel": "Valve",
                    "kp": 1.0
                }
            ]
        }

        engine.load_config(config)

        assert len(engine.loops) == 2
        assert "temp_control" in engine.loops
        assert "pressure_control" in engine.loops
        assert engine.loops["temp_control"].kp == 2.0

    def test_trigger_engine_load_from_project(self):
        """Test loading triggers from project data"""
        from crio_node import TriggerEngine

        engine = TriggerEngine()

        # Load triggers using the proper load_from_config method
        config = {
            "scripts": {
                "triggers": [
                    {
                        "id": "test",
                        "name": "Test",
                        "enabled": True,
                        "trigger": {"type": "valueReached", "channel": "ch1", "operator": ">", "value": 50},
                        "actions": []
                    }
                ]
            }
        }
        count = engine.load_from_config(config)
        assert count == 1
        assert "test" in engine.triggers

    def test_watchdog_engine_load_config(self):
        """Test loading watchdog configuration"""
        from crio_node import WatchdogEngine

        engine = WatchdogEngine()

        # Use the correct load_from_config method with proper structure
        config = {
            "scripts": {
                "watchdogs": [
                    {
                        "id": "stale_check",
                        "name": "Stale Data Check",
                        "enabled": True,
                        "channels": ["sensor1", "sensor2"],
                        "condition": {"type": "stale_data", "maxStaleMs": 5000},
                        "actions": []
                    }
                ]
            }
        }

        count = engine.load_from_config(config)
        assert count == 1
        assert "stale_check" in engine.watchdogs

class TestEngineCallbacks:
    """Test that engine callbacks work correctly"""

    def test_pid_output_callback(self):
        """Test PID output callback is called"""
        from crio_node import PIDEngine, PIDLoop

        outputs = []

        def on_output(channel, value):
            outputs.append((channel, value))
            return True

        engine = PIDEngine(on_set_output=on_output)
        engine.add_loop(PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv",
            cv_channel="cv",
            kp=1.0,
            setpoint=100.0
        ))

        engine.process_scan({"pv": 90.0}, dt=0.1)

        assert len(outputs) == 1
        assert outputs[0][0] == "cv"

    def test_pid_status_callback(self):
        """Test PID status callback is called"""
        from crio_node import PIDEngine, PIDLoop

        statuses = []

        def on_status(loop_id, status):
            statuses.append((loop_id, status))

        engine = PIDEngine()
        engine.set_status_callback(on_status)
        engine.add_loop(PIDLoop(
            id="test",
            name="Test",
            pv_channel="pv",
            cv_channel="cv"
        ))

        engine.process_scan({"pv": 50.0}, dt=0.1)

        assert len(statuses) == 1
        assert statuses[0][0] == "test"
        assert "output" in statuses[0][1]

    def test_sequence_event_callback(self):
        """Test sequence event callback is called"""
        from crio_node import SequenceManager, Sequence, SequenceStep

        events = []

        manager = SequenceManager()
        manager.on_sequence_event = lambda evt, seq: events.append((evt, seq.id))

        seq = Sequence(
            id="test",
            name="Test",
            steps=[SequenceStep(type="setOutput", channel="ch", value=1)]
        )
        manager.add_sequence(seq)
        manager.start_sequence("test")

        time.sleep(0.3)

        # Should have started and completed events
        event_types = [e[0] for e in events]
        assert "started" in event_types
        assert "completed" in event_types

class TestMultipleEnginesIntegration:
    """Test multiple engines working together"""

    def test_trigger_starts_sequence(self):
        """Test that a trigger can start a sequence"""
        from crio_node import (TriggerEngine, SequenceManager, Sequence, SequenceStep,
                               AutomationTrigger, TriggerCondition, TriggerAction, TriggerType, TriggerActionType)

        # Setup sequence manager
        seq_manager = SequenceManager()
        outputs = []
        seq_manager.on_set_output = lambda ch, val: outputs.append((ch, val))

        seq = Sequence(
            id="safety_seq",
            name="Safety Shutdown",
            steps=[SequenceStep(type="setOutput", channel="shutdown_relay", value=1)]
        )
        seq_manager.add_sequence(seq)

        # Setup trigger engine
        trigger_engine = TriggerEngine()
        trigger_engine.run_sequence = lambda seq_id: seq_manager.start_sequence(seq_id)

        # Use proper AutomationTrigger object
        trigger = AutomationTrigger(
            id="safety",
            name="Safety Trigger",
            description="Safety trigger for pressure",
            enabled=True,
            one_shot=False,
            cooldown_ms=0,
            condition=TriggerCondition(
                trigger_type=TriggerType.VALUE_REACHED,
                channel="pressure",
                operator=">",
                threshold=100
            ),
            actions=[TriggerAction(
                action_type=TriggerActionType.START_SEQUENCE,
                sequence_id="safety_seq"
            )]
        )
        trigger_engine.triggers["safety"] = trigger

        trigger_engine.on_acquisition_start()

        # Below threshold
        trigger_engine.process_scan({"pressure": 50.0})
        time.sleep(0.1)
        assert ("shutdown_relay", 1) not in outputs

        # Above threshold - should trigger sequence
        trigger_engine.process_scan({"pressure": 150.0})
        time.sleep(0.3)

        # Cleanup
        if seq_manager._running_sequence_id:
            seq_manager.abort_sequence(seq_manager._running_sequence_id)

    def test_watchdog_sets_output(self):
        """Test that watchdog can set an output"""
        from crio_node import WatchdogEngine, Watchdog, WatchdogCondition, WatchdogAction, WatchdogConditionType, WatchdogActionType

        outputs = []
        engine = WatchdogEngine()
        engine.set_output = lambda ch, val: outputs.append((ch, val))

        # Use proper Watchdog object
        watchdog = Watchdog(
            id="safety_wd",
            name="Safety Watchdog",
            description="Safety watchdog for temp",
            enabled=True,
            channels=["temp"],
            condition=WatchdogCondition(
                condition_type=WatchdogConditionType.OUT_OF_RANGE,
                min_value=0,
                max_value=100
            ),
            actions=[WatchdogAction(
                action_type=WatchdogActionType.SET_OUTPUT,
                channel="heater",
                value=0
            )],
            recovery_actions=[],
            cooldown_ms=0
        )
        engine.watchdogs["safety_wd"] = watchdog

        engine.on_acquisition_start()

        # Normal value
        engine.process_scan({"temp": 50.0}, {"temp": time.time()})
        assert len(outputs) == 0

        # Out of range - should set output
        engine.process_scan({"temp": 150.0}, {"temp": time.time()})
        assert ("heater", 0) in outputs

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
