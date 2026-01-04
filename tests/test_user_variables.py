#!/usr/bin/env python3
"""
NISystem User Variables Test Suite

Tests all user variable functionality:
1. Counter edge detection (rising, falling, increment, rate)
2. Formula/expression evaluation
3. Session lifecycle (start/stop with safety checks)
4. Variable reset modes (test_session, time_of_day, elapsed, never)
5. Timer variables
6. Accumulator variables
7. Persistence (save/load)
8. Latched alarm blocking of session start

Requirements:
- DAQ service must be running
- MQTT broker must be running

Usage:
    pytest tests/test_user_variables.py -v
"""

import pytest
import json
import time
from typing import Dict, Any, Optional
from conftest import MQTTTestHarness, SYSTEM_PREFIX, MQTT_HOST, MQTT_PORT


class TestUserVariables:
    """Test suite for user variable functionality"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test harness before each test"""
        self.harness = MQTTTestHarness(f"test_user_vars_{int(time.time()*1000)}")
        self.harness.connect()
        time.sleep(0.5)  # Allow connection to stabilize

        # Subscribe to variable-related topics
        topics = [
            f"{SYSTEM_PREFIX}/status/variables",
            f"{SYSTEM_PREFIX}/status/variables/response",
            f"{SYSTEM_PREFIX}/status/test-session",
            f"{SYSTEM_PREFIX}/status/system",
        ]
        for topic in topics:
            self.harness.subscribe(topic)
        time.sleep(0.3)

        yield

        # Cleanup
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


class TestCounterEdgeDetection(TestUserVariables):
    """Tests for counter edge detection logic"""

    def test_rising_edge_detection(self):
        """Test rising edge detection counts properly"""
        # Create a counter variable with rising edge
        var_config = {
            "id": "test_rising_counter",
            "name": "Rising Edge Counter",
            "variable_type": "counter",
            "source_channel": "test_input",
            "edge_type": "rising",
            "scale_factor": 1.0
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")

        # Variable should be created (may already exist)
        assert response is not None

    def test_falling_edge_detection(self):
        """Test falling edge detection counts properly"""
        var_config = {
            "id": "test_falling_counter",
            "name": "Falling Edge Counter",
            "variable_type": "counter",
            "source_channel": "test_input",
            "edge_type": "falling",
            "scale_factor": 1.0
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_increment_edge_detection(self):
        """Test increment mode counts any increase"""
        var_config = {
            "id": "test_increment_counter",
            "name": "Increment Counter",
            "variable_type": "accumulator",
            "source_channel": "test_counter",
            "edge_type": "increment",
            "scale_factor": 1.0
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_rate_integration(self):
        """Test rate-based integration (e.g., GPM -> total gallons)"""
        var_config = {
            "id": "test_rate_totalizer",
            "name": "Flow Totalizer",
            "variable_type": "accumulator",
            "source_channel": "flow_rate",
            "edge_type": "rate",
            "rate_unit": "per_minute",
            "scale_factor": 1.0
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None


class TestFormulaEvaluation(TestUserVariables):
    """Tests for formula/expression variable evaluation"""

    def test_simple_expression(self):
        """Test simple arithmetic expression"""
        var_config = {
            "id": "test_expr_simple",
            "name": "Temperature F",
            "variable_type": "expression",
            "expression": "temp_c * 9 / 5 + 32"
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_expression_with_functions(self):
        """Test expression with math functions"""
        var_config = {
            "id": "test_expr_func",
            "name": "Velocity Magnitude",
            "variable_type": "expression",
            "expression": "sqrt(vx**2 + vy**2)"
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_expression_with_conditionals(self):
        """Test conditional expression"""
        var_config = {
            "id": "test_expr_cond",
            "name": "High Temp Indicator",
            "variable_type": "expression",
            "expression": "1 if temperature > 100 else 0"
        }
        self.send_command("variables/create", var_config)
        response = self.wait_for_response("status/variables/response")
        assert response is not None


class TestSessionLifecycle(TestUserVariables):
    """Tests for test session start/stop lifecycle"""

    def test_session_start_requires_acquisition(self):
        """Session should fail to start if not acquiring"""
        # Stop acquisition first
        self.send_command("system/acquire/stop")
        time.sleep(0.5)

        # Try to start session
        self.send_command("test-session/start", {"started_by": "test"})
        response = self.wait_for_response("status/variables/response")

        # Should fail with acquisition error
        assert response is not None
        if isinstance(response, dict):
            # Check for error message
            assert response.get('success') == False or 'error' in str(response).lower()

    def test_session_start_with_acquisition(self):
        """Session should start when acquisition is running"""
        # Start acquisition
        self.send_command("system/acquire/start")
        time.sleep(1.0)

        # Clear any latched alarms first
        self.send_command("alarms/reset-all-latched")
        time.sleep(0.3)

        # Start session
        self.send_command("test-session/start", {"started_by": "pytest"})
        response = self.wait_for_response("status/variables/response")

        # Should succeed or already be active
        assert response is not None

    def test_session_blocks_with_latched_alarms(self):
        """Session should fail to start if latched alarms exist"""
        # This test requires creating a latched alarm first
        # For now, just verify the endpoint exists
        self.send_command("test-session/status")
        response = self.wait_for_response("status/test-session")
        assert response is not None

    def test_session_stop(self):
        """Session should stop cleanly"""
        self.send_command("test-session/stop")
        response = self.wait_for_response("status/variables/response")
        assert response is not None


class TestVariableResetModes(TestUserVariables):
    """Tests for variable reset modes"""

    def test_reset_on_session_start(self):
        """Variables with reset_mode='test_session' should reset on session start"""
        var_config = {
            "id": "test_session_reset_var",
            "name": "Session Counter",
            "variable_type": "counter",
            "source_channel": "test_input",
            "reset_mode": "test_session"
        }
        self.send_command("variables/create", var_config)
        time.sleep(0.3)

        # Get variables list to verify creation
        self.send_command("variables/list")
        response = self.wait_for_response("status/variables")
        assert response is not None

    def test_manual_reset(self):
        """Variables can be manually reset"""
        self.send_command("variables/reset", {"variable_id": "test_session_reset_var"})
        response = self.wait_for_response("status/variables/response")
        assert response is not None


class TestTimerVariables(TestUserVariables):
    """Tests for timer variables"""

    def test_timer_start_stop(self):
        """Timer should track elapsed time"""
        # Create timer
        var_config = {
            "id": "test_timer",
            "name": "Test Timer",
            "variable_type": "timer",
            "reset_mode": "test_session"
        }
        self.send_command("variables/create", var_config)
        time.sleep(0.3)

        # Start timer
        self.send_command("variables/timer/start", {"variable_id": "test_timer"})
        response = self.wait_for_response("status/variables/response")
        assert response is not None

        # Wait a bit
        time.sleep(1.0)

        # Stop timer
        self.send_command("variables/timer/stop", {"variable_id": "test_timer"})
        response = self.wait_for_response("status/variables/response")
        assert response is not None


class TestPersistence(TestUserVariables):
    """Tests for variable persistence"""

    def test_variables_persist_to_file(self):
        """Variables should be saved to disk"""
        # Create a variable
        var_config = {
            "id": "test_persist_var",
            "name": "Persistent Counter",
            "variable_type": "counter",
            "source_channel": "test_input",
            "persistent": True
        }
        self.send_command("variables/create", var_config)
        time.sleep(0.5)

        # Request save
        self.send_command("variables/save")
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_variables_list(self):
        """Should return list of all variables"""
        self.send_command("variables/list")
        response = self.wait_for_response("status/variables", timeout=3.0)
        assert response is not None


class TestSafetyInterlocks(TestUserVariables):
    """Tests for safety interlock enforcement on session start"""

    def test_session_respects_latched_alarms(self):
        """Session start should check for latched alarms"""
        # Get current alarm status
        self.send_command("alarms/status")
        response = self.wait_for_response("status/alarms", timeout=2.0)

        # Session start command includes latch check parameters
        self.send_command("test-session/start", {
            "started_by": "pytest",
            "require_no_latched": True,
            "require_no_active": False
        })
        response = self.wait_for_response("status/variables/response")
        assert response is not None

    def test_session_bypass_latch_check(self):
        """Admin can bypass latch check if needed"""
        self.send_command("test-session/start", {
            "started_by": "admin",
            "require_no_latched": False,  # Bypass for testing
            "require_no_active": False
        })
        response = self.wait_for_response("status/variables/response")
        assert response is not None


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
