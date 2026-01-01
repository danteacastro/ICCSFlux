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

import sys
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'services' / 'daq_service'))

from alarm_manager import (
    AlarmManager, AlarmConfig, AlarmSeverity, AlarmState,
    LatchBehavior, ActiveAlarm
)


class TestResults:
    """Track test results"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add(self, name: str, passed: bool, message: str = ""):
        self.tests.append((name, passed, message))
        if passed:
            self.passed += 1
            print(f"  ✓ {name}")
        else:
            self.failed += 1
            print(f"  ✗ {name}: {message}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"Results: {self.passed}/{total} tests passed")
        if self.failed > 0:
            print("Failed tests:")
            for name, passed, message in self.tests:
                if not passed:
                    print(f"  - {name}: {message}")
        return self.failed == 0


def test_basic_alarm_triggering(results: TestResults):
    """Test basic alarm triggering and clearing"""
    print("\n=== Test: Basic Alarm Triggering ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        events = []
        def publish_callback(event_type, data):
            events.append((event_type, data))

        mgr = AlarmManager(Path(tmpdir), publish_callback)

        # Add an alarm config
        config = AlarmConfig(
            id="test-temp-high",
            channel="Temp1",
            name="Temperature High",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            high_high=120.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # Process normal value - no alarm
        mgr.process_value("Temp1", 80.0)
        results.add("No alarm on normal value",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0 alarms, got {len(mgr.active_alarms)}")

        # Process value above high threshold - should trigger
        mgr.process_value("Temp1", 105.0)
        results.add("Alarm triggered on high threshold",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1 alarm, got {len(mgr.active_alarms)}")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("Alarm state is ACTIVE",
                       alarm.state == AlarmState.ACTIVE,
                       f"Expected ACTIVE, got {alarm.state}")
            results.add("Alarm severity is HIGH",
                       alarm.severity == AlarmSeverity.HIGH,
                       f"Expected HIGH, got {alarm.severity}")
            results.add("Threshold type is 'high'",
                       alarm.threshold_type == 'high',
                       f"Expected 'high', got {alarm.threshold_type}")

        # Process value back to normal - should auto-clear
        mgr.process_value("Temp1", 80.0)
        results.add("Alarm auto-cleared on normal value",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0 alarms, got {len(mgr.active_alarms)}")

        # Check that alarm event was published
        results.add("Alarm events published",
                   len(events) >= 2,
                   f"Expected >=2 events, got {len(events)}")


def test_severity_levels(results: TestResults):
    """Test different severity levels trigger correctly"""
    print("\n=== Test: Severity Levels ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Add configs with different severities
        for severity in [AlarmSeverity.CRITICAL, AlarmSeverity.HIGH,
                         AlarmSeverity.MEDIUM, AlarmSeverity.LOW]:
            config = AlarmConfig(
                id=f"alarm-{severity.name}",
                channel=f"Ch_{severity.name}",
                name=f"{severity.name} Alarm",
                severity=severity,
                high=100.0,
                latch_behavior=LatchBehavior.AUTO_CLEAR
            )
            mgr.add_alarm_config(config)

        # Trigger all alarms
        for severity in [AlarmSeverity.CRITICAL, AlarmSeverity.HIGH,
                         AlarmSeverity.MEDIUM, AlarmSeverity.LOW]:
            mgr.process_value(f"Ch_{severity.name}", 110.0)

        results.add("All severity alarms triggered",
                   len(mgr.active_alarms) == 4,
                   f"Expected 4 alarms, got {len(mgr.active_alarms)}")

        # Check counts
        counts = mgr.get_alarm_counts()
        results.add("Critical count correct", counts['critical'] == 1,
                   f"Expected 1, got {counts.get('critical', 0)}")
        results.add("High count correct", counts['high'] == 1,
                   f"Expected 1, got {counts.get('high', 0)}")


def test_latching_behavior(results: TestResults):
    """Test latching vs auto-clear behavior"""
    print("\n=== Test: Latching Behavior ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Add latching alarm
        latch_config = AlarmConfig(
            id="latch-test",
            channel="LatchCh",
            name="Latching Alarm",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        mgr.add_alarm_config(latch_config)

        # Trigger alarm
        mgr.process_value("LatchCh", 110.0)
        results.add("Latch alarm triggered",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1, got {len(mgr.active_alarms)}")

        # Value returns to normal - alarm should NOT clear (latched)
        mgr.process_value("LatchCh", 80.0)
        results.add("Latch alarm persists after value normal",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1 (latched), got {len(mgr.active_alarms)}")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("Alarm state is RETURNED",
                       alarm.state == AlarmState.RETURNED,
                       f"Expected RETURNED, got {alarm.state}")

        # Manual reset should clear it
        mgr.reset_alarm("latch-test", "TestUser")
        results.add("Latch alarm cleared after reset",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0, got {len(mgr.active_alarms)}")


def test_deadband(results: TestResults):
    """Test deadband/hysteresis prevents chatter"""
    print("\n=== Test: Deadband/Hysteresis ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Alarm at 100 with 5 degree deadband
        config = AlarmConfig(
            id="deadband-test",
            channel="DeadbandCh",
            name="Deadband Alarm",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            deadband=5.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # Trigger at 100
        mgr.process_value("DeadbandCh", 105.0)
        results.add("Alarm triggered at threshold",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1, got {len(mgr.active_alarms)}")

        # Value at 97 (within deadband of 100-5=95) - should NOT clear
        mgr.process_value("DeadbandCh", 97.0)
        results.add("Alarm persists within deadband",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1 (within deadband), got {len(mgr.active_alarms)}")

        # Value at 94 (below deadband) - should clear
        mgr.process_value("DeadbandCh", 94.0)
        results.add("Alarm clears below deadband",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0 (below deadband), got {len(mgr.active_alarms)}")


def test_on_delay(results: TestResults):
    """Test on-delay prevents spurious alarms"""
    print("\n=== Test: On-Delay Timer ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Alarm with 1 second on-delay
        config = AlarmConfig(
            id="delay-test",
            channel="DelayCh",
            name="Delayed Alarm",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            on_delay_s=1.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # First value above threshold - starts timer, no alarm yet
        mgr.process_value("DelayCh", 110.0)
        results.add("No alarm before on-delay expires",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0 (delay pending), got {len(mgr.active_alarms)}")

        # Simulate time passing (>1 second)
        time.sleep(0.1)  # Small sleep
        # Process again with timestamp > delay
        mgr.process_value("DelayCh", 110.0, time.time() + 1.5)
        results.add("Alarm triggers after on-delay expires",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1 (delay expired), got {len(mgr.active_alarms)}")


def test_first_out(results: TestResults):
    """Test first-out tracking for root cause analysis"""
    print("\n=== Test: First-Out Tracking ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Add multiple alarm configs
        for i in range(3):
            config = AlarmConfig(
                id=f"firstout-{i}",
                channel=f"FOCh{i}",
                name=f"First-Out Test {i}",
                severity=AlarmSeverity.HIGH,
                high=100.0,
                latch_behavior=LatchBehavior.AUTO_CLEAR
            )
            mgr.add_alarm_config(config)

        # Trigger alarms in sequence
        mgr.process_value("FOCh0", 110.0)  # First
        time.sleep(0.01)
        mgr.process_value("FOCh1", 110.0)  # Second
        time.sleep(0.01)
        mgr.process_value("FOCh2", 110.0)  # Third

        results.add("All three alarms active",
                   len(mgr.active_alarms) == 3,
                   f"Expected 3, got {len(mgr.active_alarms)}")

        # Check first-out
        first_out = mgr.get_first_out_alarm()
        results.add("First-out alarm identified",
                   first_out is not None,
                   "No first-out alarm found")

        if first_out:
            results.add("First-out is first triggered alarm",
                       first_out.alarm_id == "firstout-0",
                       f"Expected firstout-0, got {first_out.alarm_id}")
            results.add("First-out flag is set",
                       first_out.is_first_out == True,
                       f"is_first_out should be True")


def test_acknowledge(results: TestResults):
    """Test alarm acknowledgment"""
    print("\n=== Test: Acknowledge ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        config = AlarmConfig(
            id="ack-test",
            channel="AckCh",
            name="Ack Test",
            severity=AlarmSeverity.HIGH,
            high=100.0,
            latch_behavior=LatchBehavior.LATCH
        )
        mgr.add_alarm_config(config)

        # Trigger alarm
        mgr.process_value("AckCh", 110.0)
        results.add("Alarm active",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1, got {len(mgr.active_alarms)}")

        # Acknowledge
        success = mgr.acknowledge_alarm("ack-test", "TestOperator")
        results.add("Acknowledge succeeded", success, "acknowledge_alarm returned False")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("State is ACKNOWLEDGED",
                       alarm.state == AlarmState.ACKNOWLEDGED,
                       f"Expected ACKNOWLEDGED, got {alarm.state}")
            results.add("Acknowledged by recorded",
                       alarm.acknowledged_by == "TestOperator",
                       f"Expected TestOperator, got {alarm.acknowledged_by}")


def test_shelving(results: TestResults):
    """Test alarm shelving (temporary suppression)"""
    print("\n=== Test: Shelving ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        config = AlarmConfig(
            id="shelve-test",
            channel="ShelveCh",
            name="Shelve Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            shelve_allowed=True,
            max_shelve_time_s=3600
        )
        mgr.add_alarm_config(config)

        # Trigger alarm
        mgr.process_value("ShelveCh", 110.0)

        # Shelve it
        success = mgr.shelve_alarm("shelve-test", "TestUser", "Sensor maintenance", 300)
        results.add("Shelve succeeded", success, "shelve_alarm returned False")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("State is SHELVED",
                       alarm.state == AlarmState.SHELVED,
                       f"Expected SHELVED, got {alarm.state}")
            results.add("Shelve reason recorded",
                       alarm.shelve_reason == "Sensor maintenance",
                       f"Got: {alarm.shelve_reason}")
            results.add("Shelve expiry set",
                       alarm.shelve_expires_at is not None,
                       "No expiry time set")

        # Unshelve
        mgr.unshelve_alarm("shelve-test", "TestUser")
        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("State reverted after unshelve",
                       alarm.state == AlarmState.ACTIVE,
                       f"Expected ACTIVE, got {alarm.state}")


def test_history_logging(results: TestResults):
    """Test audit history logging"""
    print("\n=== Test: History/Audit Logging ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        config = AlarmConfig(
            id="history-test",
            channel="HistoryCh",
            name="History Test",
            severity=AlarmSeverity.MEDIUM,
            high=100.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # Trigger and clear alarm
        mgr.process_value("HistoryCh", 110.0)  # Trigger
        mgr.acknowledge_alarm("history-test", "Operator")  # Acknowledge
        mgr.process_value("HistoryCh", 80.0)  # Clear

        # Check history
        history = mgr.get_history(limit=10)
        results.add("History entries recorded",
                   len(history) >= 2,
                   f"Expected >=2 entries, got {len(history)}")

        # Check event types in history
        event_types = [h.event_type for h in history]
        results.add("Triggered event in history",
                   'triggered' in event_types,
                   f"Events: {event_types}")
        results.add("Acknowledged event in history",
                   'acknowledged' in event_types,
                   f"Events: {event_types}")


def test_rate_of_change(results: TestResults):
    """Test rate-of-change alarms"""
    print("\n=== Test: Rate-of-Change Alarm ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        # Alarm if rate exceeds 10 units/second
        config = AlarmConfig(
            id="rate-test",
            channel="RateCh",
            name="Rate Alarm",
            severity=AlarmSeverity.HIGH,
            rate_limit=10.0,
            rate_window_s=1.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # Normal rate - no alarm
        base_time = time.time()
        mgr.process_value("RateCh", 50.0, base_time)
        mgr.process_value("RateCh", 55.0, base_time + 1.0)  # 5 units/sec
        results.add("No alarm on normal rate",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0, got {len(mgr.active_alarms)}")

        # Fast rate - should alarm
        mgr.process_value("RateCh", 80.0, base_time + 2.0)  # 25 units/sec
        results.add("Alarm on excessive rate",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1, got {len(mgr.active_alarms)}")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("Threshold type is 'rate'",
                       alarm.threshold_type == 'rate',
                       f"Expected 'rate', got {alarm.threshold_type}")


def test_persistence(results: TestResults):
    """Test state persistence across restarts"""
    print("\n=== Test: State Persistence ===")

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

        results.add("Config restored after restart",
                   "persist-test" in mgr2.alarm_configs,
                   "Config not found")

        results.add("Active alarm restored after restart",
                   len(mgr2.active_alarms) == 1,
                   f"Expected 1, got {len(mgr2.active_alarms)}")


def test_low_thresholds(results: TestResults):
    """Test low and low_low thresholds"""
    print("\n=== Test: Low Thresholds ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AlarmManager(Path(tmpdir))

        config = AlarmConfig(
            id="low-test",
            channel="LowCh",
            name="Low Threshold Test",
            severity=AlarmSeverity.MEDIUM,
            low=20.0,
            low_low=10.0,
            latch_behavior=LatchBehavior.AUTO_CLEAR
        )
        mgr.add_alarm_config(config)

        # Normal value
        mgr.process_value("LowCh", 50.0)
        results.add("No alarm on normal value",
                   len(mgr.active_alarms) == 0,
                   f"Expected 0, got {len(mgr.active_alarms)}")

        # Below low threshold
        mgr.process_value("LowCh", 15.0)
        results.add("Alarm on low threshold",
                   len(mgr.active_alarms) == 1,
                   f"Expected 1, got {len(mgr.active_alarms)}")

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("Threshold type is 'low'",
                       alarm.threshold_type == 'low',
                       f"Expected 'low', got {alarm.threshold_type}")

        # Clear and test low_low
        mgr.process_value("LowCh", 50.0)
        mgr.process_value("LowCh", 5.0)  # Below low_low

        if mgr.active_alarms:
            alarm = list(mgr.active_alarms.values())[0]
            results.add("Threshold type is 'low_low' for critical low",
                       alarm.threshold_type == 'low_low',
                       f"Expected 'low_low', got {alarm.threshold_type}")


def main():
    print("=" * 60)
    print("NISystem Enhanced Safety System Tests")
    print("=" * 60)

    results = TestResults()

    # Run all tests
    test_basic_alarm_triggering(results)
    test_severity_levels(results)
    test_latching_behavior(results)
    test_deadband(results)
    test_on_delay(results)
    test_first_out(results)
    test_acknowledge(results)
    test_shelving(results)
    test_history_logging(results)
    test_rate_of_change(results)
    test_persistence(results)
    test_low_thresholds(results)

    # Summary
    success = results.summary()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
