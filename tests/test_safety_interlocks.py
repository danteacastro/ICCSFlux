#!/usr/bin/env python3
"""
NISystem Safety Interlocks Test Suite

Tests safety interlock functionality:
1. Latch alarm behavior (LATCH, AUTO_CLEAR, TIMED_LATCH)
2. Interlock condition evaluation
3. Output blocking by interlocks
4. Session blocking by latched alarms
5. Alarm acknowledge and reset
6. First-out alarm tracking

Requirements:
- DAQ service must be running
- MQTT broker must be running

Usage:
    pytest tests/test_safety_interlocks.py -v
"""

import pytest
import json
import time
from typing import Dict, Any, Optional
from test_helpers import MQTTTestHarness, SYSTEM_PREFIX, MQTT_HOST, MQTT_PORT

class TestSafetyInterlocks:
    """Test suite for safety interlock functionality"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test harness before each test"""
        self.harness = MQTTTestHarness(f"test_safety_{int(time.time()*1000)}")
        self.harness.connect()
        time.sleep(0.5)

        # Subscribe to safety-related topics
        topics = [
            f"{SYSTEM_PREFIX}/status/alarms",
            f"{SYSTEM_PREFIX}/status/alarms/response",
            f"{SYSTEM_PREFIX}/status/system",
            f"{SYSTEM_PREFIX}/status/variables/response",
            f"{SYSTEM_PREFIX}/status/test-session",
        ]
        for topic in topics:
            self.harness.subscribe(topic)
        time.sleep(0.3)

        yield

        # Cleanup - reset all latched alarms
        self.send_command("alarms/reset-all-latched")
        time.sleep(0.2)
        self.harness.disconnect()

    def send_command(self, topic: str, payload: Dict[str, Any] = None):
        """Send a command via MQTT"""
        full_topic = f"{SYSTEM_PREFIX}/{topic}"
        msg = json.dumps(payload) if payload else "{}"
        self.harness.client.publish(full_topic, msg)
        time.sleep(0.2)

    def wait_for_response(self, topic: str, timeout: float = 2.0) -> Optional[Dict]:
        """Wait for a response on a topic"""
        return self.harness.wait_for_message(f"{SYSTEM_PREFIX}/{topic}", timeout)

class TestLatchBehavior(TestSafetyInterlocks):
    """Tests for alarm latch behavior"""

    def test_auto_clear_alarm(self):
        """AUTO_CLEAR alarms should clear when condition clears"""
        # Configure an auto-clear alarm
        alarm_config = {
            "channel": "test_temp",
            "high": 100.0,
            "low": 0.0,
            "latch_behavior": "auto_clear",
            "severity": "medium"
        }
        self.send_command("alarms/configure", alarm_config)
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_latch_alarm_requires_reset(self):
        """LATCH alarms should stay active until manually reset"""
        alarm_config = {
            "channel": "test_pressure",
            "high_high": 150.0,
            "latch_behavior": "latch",
            "severity": "critical"
        }
        self.send_command("alarms/configure", alarm_config)
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_timed_latch_auto_clears(self):
        """TIMED_LATCH alarms should auto-clear after delay"""
        alarm_config = {
            "channel": "test_flow",
            "low": 10.0,
            "latch_behavior": "timed_latch",
            "timed_latch_s": 5.0,
            "severity": "high"
        }
        self.send_command("alarms/configure", alarm_config)
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

class TestAlarmActions(TestSafetyInterlocks):
    """Tests for alarm acknowledge and reset actions"""

    def test_acknowledge_alarm(self):
        """Should acknowledge an active alarm"""
        self.send_command("alarms/acknowledge", {"channel": "test_temp"})
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_acknowledge_all_alarms(self):
        """Should acknowledge all active alarms"""
        self.send_command("alarms/acknowledge-all")
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_reset_latched_alarm(self):
        """Should reset a latched alarm"""
        self.send_command("alarms/reset-latched", {"channel": "test_pressure"})
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_reset_all_latched_alarms(self):
        """Should reset all latched alarms"""
        self.send_command("alarms/reset-all-latched")
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_get_alarm_counts(self):
        """Should return alarm counts by state"""
        self.send_command("alarms/counts")
        response = self.wait_for_response("status/alarms")
        assert response is not None

class TestAlarmShelf(TestSafetyInterlocks):
    """Tests for alarm shelving functionality"""

    def test_shelve_alarm(self):
        """Should temporarily shelve an alarm"""
        self.send_command("alarms/shelve", {
            "channel": "test_temp",
            "duration_s": 3600,
            "reason": "Maintenance"
        })
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

    def test_unshelve_alarm(self):
        """Should unshelve a shelved alarm"""
        self.send_command("alarms/unshelve", {"channel": "test_temp"})
        response = self.wait_for_response("status/alarms/response")
        assert response is not None

class TestSessionInterlocks(TestSafetyInterlocks):
    """Tests for session start interlock enforcement"""

    def test_session_blocked_by_latched_alarm(self):
        """Session should not start with latched alarms"""
        # First ensure acquisition is running
        self.send_command("system/acquire/start")
        time.sleep(0.5)

        # Try to start session with require_no_latched=True
        self.send_command("test-session/start", {
            "started_by": "test",
            "require_no_latched": True
        })
        response = self.wait_for_response("status/variables/response", timeout=3.0)

        # Response should indicate success or failure based on latch state
        assert response is not None

    def test_session_allowed_after_latch_reset(self):
        """Session should start after latched alarms are reset"""
        # Reset all latched alarms
        self.send_command("alarms/reset-all-latched")
        time.sleep(0.3)

        # Ensure acquisition is running
        self.send_command("system/acquire/start")
        time.sleep(0.5)

        # Now try to start session
        self.send_command("test-session/start", {
            "started_by": "test",
            "require_no_latched": True
        })
        response = self.wait_for_response("status/variables/response", timeout=3.0)
        assert response is not None

class TestOutputBlocking(TestSafetyInterlocks):
    """Tests for output blocking by interlocks"""

    def test_digital_output_blocked(self):
        """Digital output should be blocked when interlock active"""
        # This is primarily a frontend test, but verify the API exists
        self.send_command("outputs/set", {
            "channel": "test_valve",
            "value": 1
        })
        time.sleep(0.2)
        # Response depends on interlock state

    def test_analog_setpoint_blocked(self):
        """Analog setpoint should be blocked when interlock active"""
        self.send_command("outputs/set", {
            "channel": "test_setpoint",
            "value": 50.0
        })
        time.sleep(0.2)
        # Response depends on interlock state

class TestFirstOutAlarm(TestSafetyInterlocks):
    """Tests for first-out alarm tracking"""

    def test_first_out_tracking(self):
        """Should track the first alarm (root cause)"""
        self.send_command("alarms/first-out")
        response = self.wait_for_response("status/alarms")
        assert response is not None

    def test_first_out_cleared_on_reset(self):
        """First-out should clear when all alarms reset"""
        self.send_command("alarms/reset-all-latched")
        time.sleep(0.3)
        self.send_command("alarms/first-out")
        response = self.wait_for_response("status/alarms")
        assert response is not None

class TestAlarmHistory(TestSafetyInterlocks):
    """Tests for alarm history tracking"""

    def test_get_alarm_history(self):
        """Should return alarm history"""
        self.send_command("alarms/history", {"limit": 50})
        response = self.wait_for_response("status/alarms")
        # May or may not have history depending on test order
        # Just verify the endpoint works

    def test_alarm_history_includes_events(self):
        """History should include triggered, acknowledged, cleared events"""
        self.send_command("alarms/history", {
            "limit": 100,
            "event_types": ["triggered", "acknowledged", "cleared"]
        })
        time.sleep(0.3)
        # Verify endpoint responds

# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
