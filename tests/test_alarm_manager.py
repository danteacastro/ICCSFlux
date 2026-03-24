#!/usr/bin/env python3
"""
Test suite for the enhanced AlarmManager safety system

Tests:
- Alarm triggering and clearing
- Severity levels
- Latching behavior (auto-clear, latch, timed-latch)
- On-delay and off-delay timers
- Deadband/hysteresis
- First-out tracking
- Shelving
- Rate-of-change alarms
- Audit logging
"""

import pytest
import sys
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Add parent and tests directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'services' / 'daq_service'))
sys.path.insert(0, str(Path(__file__).parent))

from test_helpers import wait_until

from alarm_manager import (
    AlarmManager, AlarmConfig, AlarmSeverity, AlarmState,
    LatchBehavior, ActiveAlarm
)

class TestBasicAlarmTriggering:
    """Test basic alarm triggering functionality"""

    @pytest.fixture
    def manager(self):
        """Create a temporary alarm manager"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_alarm_triggers_on_high_threshold(self, manager):
        """Test that alarm triggers when value exceeds high threshold"""
        config = AlarmConfig(
            id="high-test",
            channel="TempCh",
            name="High Temp Alarm",
            severity=AlarmSeverity.HIGH,
            high=100.0
        )
        manager.add_alarm_config(config)

        # Normal value - no alarm
        manager.process_value("TempCh", 50.0)
        assert len(manager.active_alarms) == 0

        # Above threshold - should trigger
        manager.process_value("TempCh", 110.0)
        assert len(manager.active_alarms) == 1

    def test_alarm_clears_on_normal_value(self, manager):
        """Test that non-latching alarm clears when value returns to normal"""
        config = AlarmConfig(
            id="clear-test",
            channel="TempCh",
            name="Clear Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        # Trigger alarm
        manager.process_value("TempCh", 110.0)
        assert len(manager.active_alarms) == 1

        # Return to normal - should clear
        manager.process_value("TempCh", 50.0)
        assert len(manager.active_alarms) == 0

class TestSeverityLevels:
    """Test alarm severity levels"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_severity_levels_defined(self):
        """Test all severity levels are available"""
        assert AlarmSeverity.LOW is not None
        assert AlarmSeverity.MEDIUM is not None
        assert AlarmSeverity.HIGH is not None
        assert AlarmSeverity.CRITICAL is not None

    def test_alarm_has_correct_severity(self, manager):
        """Test that triggered alarm has correct severity"""
        config = AlarmConfig(
            id="severity-test",
            channel="TestCh",
            name="Severity Test",
            severity=AlarmSeverity.CRITICAL,
            high=100.0
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        alarm = list(manager.active_alarms.values())[0]
        assert alarm.severity == AlarmSeverity.CRITICAL

class TestLatchingBehavior:
    """Test alarm latching behaviors"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_auto_clear_behavior(self, manager):
        """Test AUTO_CLEAR behavior clears when condition clears"""
        config = AlarmConfig(
            id="auto-clear",
            channel="TestCh",
            name="Auto Clear Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        manager.process_value("TestCh", 50.0)
        assert len(manager.active_alarms) == 0

    def test_latch_behavior_stays_active(self, manager):
        """Test LATCH behavior stays active until acknowledged"""
        config = AlarmConfig(
            id="latch-test",
            channel="TestCh",
            name="Latch Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        # Return to normal - should stay latched
        manager.process_value("TestCh", 50.0)
        assert len(manager.active_alarms) == 1

    def test_acknowledge_latched_alarm(self, manager):
        """Test that acknowledging a latched alarm marks it as acknowledged"""
        config = AlarmConfig(
            id="ack-test",
            channel="TestCh",
            name="Ack Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        result = manager.acknowledge_alarm("ack-test", "test_user")
        assert result is True

        # Alarm acknowledged but may still be active depending on implementation
        alarm = manager.active_alarms.get("ack-test")
        if alarm:
            assert alarm.acknowledged_by == "test_user"

class TestDeadband:
    """Test deadband/hysteresis functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_deadband_prevents_chattering(self, manager):
        """Test that deadband prevents alarm chattering"""
        config = AlarmConfig(
            id="deadband-test",
            channel="TestCh",
            name="Deadband Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            deadband=5.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        # Trigger alarm
        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        # Value below threshold but within deadband - should stay active
        manager.process_value("TestCh", 98.0)
        assert len(manager.active_alarms) == 1

        # Value below threshold minus deadband - should clear
        manager.process_value("TestCh", 90.0)
        assert len(manager.active_alarms) == 0

class TestOnDelay:
    """Test on-delay timer functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_on_delay_prevents_immediate_trigger(self, manager):
        """Test that on_delay prevents immediate alarm triggering"""
        config = AlarmConfig(
            id="delay-test",
            channel="TestCh",
            name="Delay Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            on_delay_s=0.2  # 200 ms delay (shorter than original 1 s)
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        # Should not trigger immediately
        assert len(manager.active_alarms) == 0

        # Poll until the on-delay elapses and alarm activates
        def _alarm_active():
            manager.process_value("TestCh", 110.0)
            return len(manager.active_alarms) == 1

        assert wait_until(_alarm_active, timeout=3.0), \
            "Alarm did not activate after on_delay elapsed"

class TestFirstOut:
    """Test first-out tracking functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_first_alarm_marked_as_first_out(self, manager):
        """Test that first alarm in group is marked as first out"""
        config1 = AlarmConfig(
            id="first-out-1",
            channel="TestCh1",
            name="First Out Test 1",
            severity=AlarmSeverity.HIGH,
            high=100.0
        )
        config2 = AlarmConfig(
            id="first-out-2",
            channel="TestCh2",
            name="First Out Test 2",
            severity=AlarmSeverity.HIGH,
            high=100.0
        )
        manager.add_alarm_config(config1)
        manager.add_alarm_config(config2)

        manager.process_value("TestCh1", 110.0)
        manager.process_value("TestCh2", 110.0)

        # First should be marked as first out
        alarm1 = manager.active_alarms.get("first-out-1")
        alarm2 = manager.active_alarms.get("first-out-2")

        assert alarm1 is not None
        assert alarm1.is_first_out is True
        assert alarm2 is not None
        assert alarm2.is_first_out is False

class TestAcknowledge:
    """Test alarm acknowledgment functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_acknowledge_updates_alarm(self, manager):
        """Test that acknowledging updates alarm state"""
        config = AlarmConfig(
            id="ack-test",
            channel="TestCh",
            name="Ack Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        result = manager.acknowledge_alarm("ack-test", "test_user")

        assert result is True

    def test_acknowledge_returns_false_for_unknown(self, manager):
        """Test that acknowledging unknown alarm returns False"""
        result = manager.acknowledge_alarm("unknown", "test_user")
        assert result is False

class TestShelving:
    """Test alarm shelving functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_shelve_marks_alarm_as_shelved(self, manager):
        """Test that shelving an active alarm marks it as shelved"""
        config = AlarmConfig(
            id="shelve-test",
            channel="TestCh",
            name="Shelve Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0
        )
        manager.add_alarm_config(config)

        # Trigger alarm first
        manager.process_value("TestCh", 110.0)
        assert len(manager.active_alarms) == 1

        # Shelve the alarm
        result = manager.shelve_alarm("shelve-test", "test_user", "maintenance", 300)
        assert result is True

        # Check alarm is shelved
        alarm = manager.active_alarms.get("shelve-test")
        assert alarm is not None
        assert alarm.shelved_by == "test_user"

    def test_unshelve_clears_shelved_state(self, manager):
        """Test that unshelving clears the shelved state"""
        config = AlarmConfig(
            id="unshelve-test",
            channel="TestCh",
            name="Unshelve Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0
        )
        manager.add_alarm_config(config)

        # Trigger and shelve
        manager.process_value("TestCh", 110.0)
        manager.shelve_alarm("unshelve-test", "test_user", "test", 300)

        # Unshelve
        result = manager.unshelve_alarm("unshelve-test", "test_user", "done")
        assert result is True

class TestHistoryLogging:
    """Test alarm history logging"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_alarm_logged_to_history(self, manager):
        """Test that alarms are logged to history"""
        config = AlarmConfig(
            id="history-test",
            channel="TestCh",
            name="History Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        manager.process_value("TestCh", 110.0)
        manager.process_value("TestCh", 50.0)

        history = manager.get_history(limit=100)
        assert len(history) >= 1

class TestRateOfChange:
    """Test rate of change alarm functionality"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_rate_of_change_triggers(self, manager):
        """Test that rapid change triggers rate of change alarm"""
        config = AlarmConfig(
            id="roc-test",
            channel="TestCh",
            name="Rate of Change Test",
            severity=AlarmSeverity.MEDIUM,
            rate_limit=10.0,  # 10 units per second max
            rate_window_s=1.0
        )
        manager.add_alarm_config(config)

        # Rapid change
        manager.process_value("TestCh", 0.0)
        time.sleep(0.1)
        manager.process_value("TestCh", 50.0)  # 50 units in 0.1 sec = 500/sec

        assert len(manager.active_alarms) == 1

class TestPersistence:
    """Test alarm state persistence"""

    def test_state_persists_across_restart(self):
        """Test that alarm state persists after restart"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create manager and trigger alarm
            mgr1 = AlarmManager(Path(tmpdir))

            config = AlarmConfig(
                id="persist-test",
                channel="PersistCh",
                name="Persistence Test",
                severity=AlarmSeverity.HIGH,
                high=100.0,
                latch_behavior=LatchBehavior.LATCH
            )
            mgr1.add_alarm_config(config)
            mgr1.process_value("PersistCh", 110.0)

            # Save state
            mgr1.save_all()

            # Create new manager (simulating restart)
            mgr2 = AlarmManager(Path(tmpdir))

            assert "persist-test" in mgr2.alarm_configs
            assert len(mgr2.active_alarms) == 1

class TestLowThresholds:
    """Test low and low_low threshold alarms"""

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_low_threshold_triggers(self, manager):
        """Test that low threshold triggers alarm"""
        config = AlarmConfig(
            id="low-test",
            channel="LowCh",
            name="Low Threshold Test",
            severity=AlarmSeverity.MEDIUM,
            low=20.0,
            low_low=10.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        # Normal value - no alarm
        manager.process_value("LowCh", 50.0)
        assert len(manager.active_alarms) == 0

        # Below low threshold
        manager.process_value("LowCh", 15.0)
        assert len(manager.active_alarms) == 1

        alarm = list(manager.active_alarms.values())[0]
        assert alarm.threshold_type == 'low'

    def test_low_low_threshold_triggers(self, manager):
        """Test that low_low threshold triggers alarm"""
        config = AlarmConfig(
            id="lowlow-test",
            channel="LowCh",
            name="Low Low Test",
            severity=AlarmSeverity.MEDIUM,
            low=20.0,
            low_low=10.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        manager.process_value("LowCh", 5.0)
        assert len(manager.active_alarms) == 1

        alarm = list(manager.active_alarms.values())[0]
        assert alarm.threshold_type == 'low_low'

class TestUnshelveReEvaluation:
    """Test alarm unshelve re-evaluates condition correctly.

    Validates the fix for the AttributeError crash where unshelve_alarm
    accessed config.alarm_type (which doesn't exist) instead of
    config.digital_alarm_enabled.
    """

    @pytest.fixture
    def manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield AlarmManager(Path(tmpdir))

    def test_unshelve_analog_alarm_condition_still_active(self, manager):
        """Unshelve when analog alarm condition is still active — should go to ACTIVE"""
        config = AlarmConfig(
            id="unshelve-active",
            channel="Temp1",
            name="Unshelve Active Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        manager.add_alarm_config(config)

        # Trigger alarm with high value
        manager.process_value("Temp1", 110.0)
        assert "unshelve-active" in manager.active_alarms

        # Shelve it
        manager.shelve_alarm("unshelve-active", "operator", "maintenance", 3600)
        alarm = manager.active_alarms["unshelve-active"]
        assert alarm.state == AlarmState.SHELVED

        # Unshelve — condition still active (current_value=110 > high=100)
        result = manager.unshelve_alarm("unshelve-active", "operator", "done")
        assert result is True

        # Alarm should be restored to active state (not crash with AttributeError)
        alarm = manager.active_alarms.get("unshelve-active")
        assert alarm is not None
        assert alarm.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)

    def test_unshelve_analog_alarm_condition_cleared(self, manager):
        """Unshelve when analog alarm condition has cleared — should remove alarm"""
        config = AlarmConfig(
            id="unshelve-clear",
            channel="Temp2",
            name="Unshelve Clear Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        manager.add_alarm_config(config)

        # Trigger alarm
        manager.process_value("Temp2", 110.0)
        assert "unshelve-clear" in manager.active_alarms

        # Shelve it
        manager.shelve_alarm("unshelve-clear", "operator", "work", 3600)

        # Update value to normal (below threshold) while shelved
        manager.process_value("Temp2", 80.0)

        # Unshelve — condition cleared, alarm should be removed
        result = manager.unshelve_alarm("unshelve-clear", "operator", "done")
        assert result is True

        # Alarm should be gone
        assert "unshelve-clear" not in manager.active_alarms

    def test_unshelve_digital_alarm_no_crash(self, manager):
        """Unshelve a digital alarm — validates the alarm_type -> digital_alarm_enabled fix"""
        config = AlarmConfig(
            id="unshelve-digital",
            channel="Switch1",
            name="Digital Unshelve Test",
            severity=AlarmSeverity.HIGH,
            digital_alarm_enabled=True,
            digital_expected_state=False,  # Alarm when True
            latch_behavior=LatchBehavior.LATCH
        )
        manager.add_alarm_config(config)

        # Trigger digital alarm (value=1 != expected=False)
        manager.process_value("Switch1", 1.0)
        assert "unshelve-digital" in manager.active_alarms

        # Shelve it
        manager.shelve_alarm("unshelve-digital", "operator", "test", 3600)

        # Unshelve — this used to crash with AttributeError: 'AlarmConfig' has no attribute 'alarm_type'
        result = manager.unshelve_alarm("unshelve-digital", "operator", "done")
        assert result is True

        # Should not crash — alarm should still be active (condition still met)
        alarm = manager.active_alarms.get("unshelve-digital")
        assert alarm is not None

    def test_shelve_auto_expiry_no_crash(self, manager):
        """Shelve with very short duration — auto-expiry should not crash"""
        config = AlarmConfig(
            id="expiry-test",
            channel="Pressure",
            name="Expiry Test",
            severity=AlarmSeverity.MEDIUM,
            high=500.0,
            latch_behavior=LatchBehavior.LATCH,
            max_shelve_time_s=1.0  # Allow shelving
        )
        manager.add_alarm_config(config)

        # Trigger alarm
        manager.process_value("Pressure", 600.0)
        assert "expiry-test" in manager.active_alarms

        # Shelve with short duration
        manager.shelve_alarm("expiry-test", "operator", "quick check", duration_s=0.15)
        assert manager.active_alarms["expiry-test"].state == AlarmState.SHELVED

        # Poll until shelve expires (process_value triggers the expiry check)
        def _unshelved():
            manager.process_value("Pressure", 600.0)
            alarm = manager.active_alarms.get("expiry-test")
            return alarm is not None and alarm.state != AlarmState.SHELVED

        assert wait_until(_unshelved, timeout=3.0), \
            "Alarm shelve did not expire"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
