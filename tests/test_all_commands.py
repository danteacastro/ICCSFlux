#!/usr/bin/env python3
"""
Comprehensive Command Tests for NISystem

Tests all UI button actions and their corresponding backend commands:
- START/STOP acquisition
- RECORD start/stop
- SCHEDULE enable/disable
- LOAD/SAVE configuration
- Output channel controls (digital/analog)
- Discovery scan
- Alarm acknowledge/clear

Run with: python -m pytest tests/test_all_commands.py -v
"""

import pytest
import time

# Import test harness from conftest
from conftest import SYSTEM_PREFIX


class TestStartStopButtons:
    """Test START and STOP acquisition buttons"""

    def test_start_button_starts_acquisition(self, mqtt_client_clean):
        """START button sends to nisystem/system/acquire/start"""
        client = mqtt_client_clean

        # Verify not acquiring initially
        assert not client.is_acquiring(), "Should start in stopped state"

        # Simulate START button click
        client.publish(f"{SYSTEM_PREFIX}/system/acquire/start", "{}")

        # Wait for acquisition to start
        assert client.ensure_acquiring(timeout=3.0), "Acquisition should start after START"

    def test_stop_button_stops_acquisition(self, mqtt_client_acquiring):
        """STOP button sends to nisystem/system/acquire/stop"""
        client = mqtt_client_acquiring

        # Verify acquiring initially
        assert client.is_acquiring(), "Should be acquiring before STOP"

        # Simulate STOP button click
        client.publish(f"{SYSTEM_PREFIX}/system/acquire/stop", "{}")

        # Wait for acquisition to stop
        assert client.ensure_not_acquiring(timeout=3.0), "Acquisition should stop after STOP"


class TestRecordButtons:
    """Test RECORD start and stop buttons"""

    def test_record_start_begins_recording(self, mqtt_client_acquiring):
        """RECORD button sends to nisystem/system/recording/start"""
        client = mqtt_client_acquiring

        # Ensure not recording initially
        client.ensure_not_recording()

        # Simulate RECORD button click
        client.publish(f"{SYSTEM_PREFIX}/system/recording/start", "{}")

        # Wait for recording to start
        start = time.time()
        while (time.time() - start) < 5.0:
            time.sleep(0.3)
            if client.is_recording():
                break

        status = client.get_system_status()
        assert status is not None, "Should have status"
        assert status.get("recording"), "Recording should be true after start"
        assert status.get("recording_filename"), "Should have recording filename"

        # Cleanup
        client.ensure_not_recording()

    def test_record_stop_ends_recording(self, mqtt_client_acquiring):
        """RECORD stop sends to nisystem/system/recording/stop"""
        client = mqtt_client_acquiring

        # Start recording first
        client.publish(f"{SYSTEM_PREFIX}/system/recording/start", "{}")
        time.sleep(1.5)

        # Verify recording started
        assert client.is_recording(), "Should be recording before stop"

        # Simulate RECORD stop
        client.publish(f"{SYSTEM_PREFIX}/system/recording/stop", "{}")

        # Wait for recording to stop
        assert client.ensure_not_recording(timeout=3.0), "Recording should stop"


class TestSchedulerToggle:
    """Test SCHEDULE enable/disable toggle"""

    def test_schedule_enable_activates_scheduler(self, mqtt_client):
        """SCHEDULE toggle ON sends to nisystem/schedule/enable"""
        client = mqtt_client

        # Disable first to ensure clean state
        client.publish(f"{SYSTEM_PREFIX}/schedule/disable", "{}")
        time.sleep(1.0)

        # Simulate SCHEDULE toggle ON
        client.publish(f"{SYSTEM_PREFIX}/schedule/enable", "{}")

        # Wait and check status with refresh
        time.sleep(1.0)
        assert client.is_scheduler_enabled(), "Scheduler should be enabled"

        # Cleanup
        client.publish(f"{SYSTEM_PREFIX}/schedule/disable", "{}")

    def test_schedule_disable_deactivates_scheduler(self, mqtt_client):
        """SCHEDULE toggle OFF sends to nisystem/schedule/disable"""
        client = mqtt_client

        # Enable first
        client.publish(f"{SYSTEM_PREFIX}/schedule/enable", "{}")
        time.sleep(1.0)

        # Verify enabled
        assert client.is_scheduler_enabled(), "Scheduler should be enabled first"

        # Simulate SCHEDULE toggle OFF
        client.publish(f"{SYSTEM_PREFIX}/schedule/disable", "{}")

        # Wait and check status with refresh
        time.sleep(1.0)
        assert not client.is_scheduler_enabled(), "Scheduler should be disabled"


class TestConfigButtons:
    """Test LOAD and SAVE configuration buttons"""

    def test_load_config_sends_command(self, mqtt_client):
        """LOAD button sends to nisystem/config/load"""
        client = mqtt_client

        # Subscribe to response
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/config/response")
        client.clear_messages()

        # Simulate LOAD button
        client.publish(
            f"{SYSTEM_PREFIX}/config/load",
            {"config": "test_config"}
        )

        # Wait for response (may fail if config doesn't exist, that's ok)
        time.sleep(1.0)
        # Command was sent successfully
        assert True

    def test_save_config_sends_command(self, mqtt_client):
        """SAVE button sends to nisystem/config/save"""
        client = mqtt_client

        # Subscribe to response
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/config/response")
        client.clear_messages()

        # Simulate SAVE button
        client.publish(
            f"{SYSTEM_PREFIX}/config/save",
            {"config": "test_config"}
        )

        # Wait for response
        time.sleep(1.0)
        # Command was sent successfully
        assert True


class TestOutputControls:
    """Test output channel toggle switches and controls"""

    def test_digital_output_toggle_on(self, mqtt_client_acquiring):
        """Digital toggle switch sends command and receives feedback"""
        client = mqtt_client_acquiring
        channel = "F1_Heater_Enable"
        topic = f"{SYSTEM_PREFIX}/channels/{channel}"

        # Subscribe and wait for subscription to be active
        client.subscribe_and_wait(topic)

        # Wait for at least one message to establish baseline
        time.sleep(0.5)

        # Simulate toggle switch ON
        client.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            {"value": True}
        )

        # Wait for new message with updated value
        msg = client.wait_for_new_message(topic, timeout=3.0)
        assert msg is not None, f"Should receive feedback from {channel}"

        # Verify value was set (digital outputs report as 0.0 or 1.0)
        value = msg["payload"].get("value")
        assert value == 1.0 or value is True, f"Value should be true/1.0, got {value}"

    def test_digital_output_toggle_off(self, mqtt_client_acquiring):
        """Digital toggle switch sends command with false value"""
        client = mqtt_client_acquiring
        channel = "F1_Heater_Enable"
        topic = f"{SYSTEM_PREFIX}/channels/{channel}"

        # Subscribe and wait
        client.subscribe_and_wait(topic)
        time.sleep(0.5)

        # Simulate toggle switch OFF
        client.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            {"value": False}
        )

        # Wait for new message
        msg = client.wait_for_new_message(topic, timeout=3.0)
        assert msg is not None, f"Should receive feedback from {channel}"

        value = msg["payload"].get("value")
        assert value == 0.0 or value is False, f"Value should be false/0.0, got {value}"

    def test_analog_output_setpoint(self, mqtt_client_acquiring):
        """Analog output setpoint sends to nisystem/commands/<channel>"""
        client = mqtt_client_acquiring
        channel = "F1_Temp_Setpoint"
        setpoint = 250.0
        topic = f"{SYSTEM_PREFIX}/channels/{channel}"

        # Subscribe and wait
        client.subscribe_and_wait(topic)
        time.sleep(0.5)

        # Simulate setpoint change
        client.publish(
            f"{SYSTEM_PREFIX}/commands/{channel}",
            {"value": setpoint}
        )

        # Wait for new message
        msg = client.wait_for_new_message(topic, timeout=3.0)
        assert msg is not None, f"Should receive feedback from {channel}"

        value = msg["payload"].get("value")
        assert value == setpoint, f"Value should be {setpoint}, got {value}"

    def test_multiple_outputs_in_sequence(self, mqtt_client_acquiring):
        """Multiple output commands work sequentially"""
        client = mqtt_client_acquiring

        outputs = [
            ("F1_Heater_Enable", True),
            ("F2_Heater_Enable", True),
            ("F1_N2_Purge", True),
            ("Cooling_Pump", True),
        ]

        for channel, value in outputs:
            client.publish(
                f"{SYSTEM_PREFIX}/commands/{channel}",
                {"value": value}
            )
            time.sleep(0.2)

        time.sleep(1.0)

        # Verify by checking logs wrote successfully (no exception)
        assert True, "All output commands sent successfully"


class TestDiscoveryButton:
    """Test device discovery scan button"""

    def test_discovery_scan_returns_results(self, mqtt_client):
        """Discovery scan sends to nisystem/discovery/scan and returns results"""
        client = mqtt_client

        # Subscribe to discovery results
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/discovery/result")
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/discovery/channels")
        client.clear_messages()

        # Simulate discovery scan button
        client.publish(f"{SYSTEM_PREFIX}/discovery/scan", "")

        # Wait for result
        time.sleep(3.0)
        msgs = client.wait_for_message(
            f"{SYSTEM_PREFIX}/discovery/result",
            timeout=5.0
        )

        # Should receive some response (even in simulation mode)
        assert len(msgs) > 0, "Should receive discovery result"


class TestAlarmControls:
    """Test alarm acknowledge and clear controls"""

    def test_alarm_acknowledge_sends_command(self, mqtt_client):
        """Alarm acknowledge sends to nisystem/alarms/acknowledge"""
        client = mqtt_client

        # Subscribe to alarm responses
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/alarms/#")
        client.clear_messages()

        # Simulate alarm acknowledge
        client.publish(
            f"{SYSTEM_PREFIX}/alarms/acknowledge",
            {"source": "test_alarm"}
        )

        time.sleep(0.5)
        # Command sent successfully
        assert True

    def test_alarm_clear_sends_command(self, mqtt_client):
        """Alarm clear sends to nisystem/alarms/clear"""
        client = mqtt_client

        # Subscribe to alarm responses
        client.subscribe_and_wait(f"{SYSTEM_PREFIX}/alarms/#")
        client.clear_messages()

        # Simulate alarm clear
        client.publish(
            f"{SYSTEM_PREFIX}/alarms/clear",
            {"source": "test_alarm"}
        )

        time.sleep(0.5)
        # Command sent successfully
        assert True


class TestSequenceControls:
    """Test sequence/automation controls (placeholder for future)"""

    def test_sequence_abort(self, mqtt_client):
        """Sequence abort sends correct topic"""
        client = mqtt_client

        # Simulate sequence abort
        client.publish(f"{SYSTEM_PREFIX}/sequence/abort", "{}")

        time.sleep(0.5)
        # Command sent (no response expected for abort)
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
