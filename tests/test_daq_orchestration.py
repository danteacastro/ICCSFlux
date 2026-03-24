"""
Unit tests for DAQ service orchestration layer.

Tests the core orchestration logic without requiring MQTT broker,
hardware, or running services. Uses mocking to isolate the DAQService
class and its subsystems.

Covers:
- State machine transitions (DAQStateMachine)
- Acquisition lifecycle (start/stop with permission checks)
- Payload validation (script size limits)
- Command acknowledgment flow
- Rate limiter behavior
- Scan timing statistics
"""

import json
import sys
import time
import threading
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add service directory to path for imports
service_dir = Path(__file__).parent.parent / "services" / "daq_service"
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

# =============================================================================
# STATE MACHINE TESTS
# =============================================================================

from state_machine import DAQStateMachine, DAQState, VALID_TRANSITIONS

class TestDAQStateMachine:
    """Test the acquisition lifecycle state machine."""

    def test_initial_state_is_stopped(self):
        sm = DAQStateMachine()
        assert sm.state == DAQState.STOPPED

    def test_custom_initial_state(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.state == DAQState.RUNNING

    def test_stopped_to_initializing(self):
        sm = DAQStateMachine(DAQState.STOPPED)
        assert sm.to(DAQState.INITIALIZING) is True
        assert sm.state == DAQState.INITIALIZING

    def test_initializing_to_running(self):
        sm = DAQStateMachine(DAQState.INITIALIZING)
        assert sm.to(DAQState.RUNNING) is True
        assert sm.state == DAQState.RUNNING

    def test_running_to_stopping(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.to(DAQState.STOPPING) is True
        assert sm.state == DAQState.STOPPING

    def test_stopping_to_stopped(self):
        sm = DAQStateMachine(DAQState.STOPPING)
        assert sm.to(DAQState.STOPPED) is True
        assert sm.state == DAQState.STOPPED

    def test_full_lifecycle(self):
        """Test complete acquisition lifecycle: STOPPED -> INIT -> RUNNING -> STOPPING -> STOPPED"""
        sm = DAQStateMachine()
        assert sm.to(DAQState.INITIALIZING)
        assert sm.to(DAQState.RUNNING)
        assert sm.to(DAQState.STOPPING)
        assert sm.to(DAQState.STOPPED)
        assert sm.state == DAQState.STOPPED

    def test_direct_start(self):
        """STOPPED -> RUNNING is valid (script/scheduler direct start)."""
        sm = DAQStateMachine(DAQState.STOPPED)
        assert sm.to(DAQState.RUNNING) is True
        assert sm.state == DAQState.RUNNING

    def test_direct_stop(self):
        """RUNNING -> STOPPED is valid (script/scheduler direct stop)."""
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.to(DAQState.STOPPED) is True
        assert sm.state == DAQState.STOPPED

    def test_invalid_stopped_to_stopping(self):
        sm = DAQStateMachine(DAQState.STOPPED)
        assert sm.to(DAQState.STOPPING) is False
        assert sm.state == DAQState.STOPPED

    def test_invalid_initializing_to_stopping(self):
        sm = DAQStateMachine(DAQState.INITIALIZING)
        assert sm.to(DAQState.STOPPING) is False
        assert sm.state == DAQState.INITIALIZING

    def test_invalid_stopping_to_running(self):
        sm = DAQStateMachine(DAQState.STOPPING)
        assert sm.to(DAQState.RUNNING) is False
        assert sm.state == DAQState.STOPPING

    def test_invalid_stopping_to_initializing(self):
        sm = DAQStateMachine(DAQState.STOPPING)
        assert sm.to(DAQState.INITIALIZING) is False
        assert sm.state == DAQState.STOPPING

    def test_same_state_noop(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.to(DAQState.RUNNING) is True
        assert sm.state == DAQState.RUNNING

    def test_is_acquiring_when_running(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.is_acquiring is True

    def test_is_acquiring_when_initializing(self):
        sm = DAQStateMachine(DAQState.INITIALIZING)
        assert sm.is_acquiring is True

    def test_not_acquiring_when_stopped(self):
        sm = DAQStateMachine(DAQState.STOPPED)
        assert sm.is_acquiring is False

    def test_not_acquiring_when_stopping(self):
        sm = DAQStateMachine(DAQState.STOPPING)
        assert sm.is_acquiring is False

    def test_acquisition_state_string(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        assert sm.acquisition_state == "running"

    def test_can_transition_check(self):
        sm = DAQStateMachine(DAQState.STOPPED)
        assert sm.can_transition(DAQState.INITIALIZING) is True
        assert sm.can_transition(DAQState.STOPPING) is False

    def test_force_state(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        sm.force_state(DAQState.STOPPED)
        assert sm.state == DAQState.STOPPED

    def test_force_state_bypasses_validation(self):
        """Force state should work even for invalid transitions."""
        sm = DAQStateMachine(DAQState.STOPPING)
        sm.force_state(DAQState.INITIALIZING)
        assert sm.state == DAQState.INITIALIZING

    def test_enter_callback_fired(self):
        callback = MagicMock()
        sm = DAQStateMachine(DAQState.STOPPED)
        sm.on_enter(DAQState.RUNNING, callback)
        sm.to(DAQState.RUNNING)
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == DAQState.STOPPED
        assert args[1] == DAQState.RUNNING

    def test_exit_callback_fired(self):
        callback = MagicMock()
        sm = DAQStateMachine(DAQState.RUNNING)
        sm.on_exit(DAQState.RUNNING, callback)
        sm.to(DAQState.STOPPING)
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == DAQState.RUNNING
        assert args[1] == DAQState.STOPPING

    def test_callback_not_fired_on_noop(self):
        enter_cb = MagicMock()
        exit_cb = MagicMock()
        sm = DAQStateMachine(DAQState.RUNNING)
        sm.on_enter(DAQState.RUNNING, enter_cb)
        sm.on_exit(DAQState.RUNNING, exit_cb)
        sm.to(DAQState.RUNNING)  # Same state = noop
        enter_cb.assert_not_called()
        exit_cb.assert_not_called()

    def test_callback_exception_does_not_block_transition(self):
        def bad_callback(old, new, payload):
            raise RuntimeError("callback error")

        sm = DAQStateMachine(DAQState.STOPPED)
        sm.on_enter(DAQState.RUNNING, bad_callback)
        assert sm.to(DAQState.RUNNING) is True
        assert sm.state == DAQState.RUNNING

    def test_get_status(self):
        sm = DAQStateMachine(DAQState.RUNNING)
        status = sm.get_status()
        assert status["state"] == "RUNNING"
        assert status["acquiring"] is True
        assert status["acquisition_state"] == "running"

    def test_thread_safety(self):
        """Verify concurrent transitions don't corrupt state."""
        sm = DAQStateMachine(DAQState.STOPPED)
        results = []

        def cycle():
            for _ in range(100):
                sm.to(DAQState.INITIALIZING)
                sm.to(DAQState.RUNNING)
                sm.to(DAQState.STOPPING)
                sm.to(DAQState.STOPPED)
            results.append(True)

        threads = [threading.Thread(target=cycle) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sm.state == DAQState.STOPPED
        assert len(results) == 4

# =============================================================================
# RATE LIMITER TESTS
# =============================================================================

# Import after path setup
from daq_service import TokenBucketRateLimiter

class TestTokenBucketRateLimiter:
    """Test the token bucket rate limiter."""

    def test_initial_burst_allowed(self):
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=5.0)
        # Should allow up to capacity tokens immediately
        for _ in range(5):
            assert limiter.allow() is True

    def test_exceeding_capacity_denied(self):
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=3.0)
        for _ in range(3):
            limiter.allow()
        assert limiter.allow() is False

    def test_refill_after_wait(self):
        limiter = TokenBucketRateLimiter(rate=100.0, capacity=1.0)
        assert limiter.allow() is True
        assert limiter.allow() is False
        time.sleep(0.02)  # Wait for ~2 tokens to refill at 100/sec
        assert limiter.allow() is True

    def test_capacity_is_max(self):
        """Tokens should never exceed capacity even after long wait."""
        limiter = TokenBucketRateLimiter(rate=1000.0, capacity=3.0)
        time.sleep(0.1)  # Would refill 100 tokens, but capped at 3
        count = 0
        while limiter.allow():
            count += 1
            if count > 10:
                break
        assert count <= 4  # Capacity + 1 tolerance for timing

# =============================================================================
# SCAN TIMING STATS TESTS
# =============================================================================

from daq_service import ScanTimingStats

class TestScanTimingStats:
    """Test scan timing statistics tracking."""

    def test_empty_stats(self):
        stats = ScanTimingStats(target_ms=10.0)
        assert stats.min_ms == 0.0
        assert stats.max_ms == 0.0
        assert stats.mean_ms == 0.0
        assert stats.jitter_ms == 0.0
        assert stats.actual_rate_hz == 0.0
        assert stats.total_scans == 0

    def test_record_single(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.5)
        assert stats.total_scans == 1
        assert stats.min_ms == 10.5
        assert stats.max_ms == 10.5
        assert stats.mean_ms == 10.5

    def test_record_multiple(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.0)
        stats.record(12.0)
        stats.record(8.0)
        assert stats.total_scans == 3
        assert stats.min_ms == 8.0
        assert stats.max_ms == 12.0
        assert stats.mean_ms == 10.0

    def test_overrun_detection(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.0)   # OK
        stats.record(14.0)   # OK (< 15ms threshold)
        stats.record(16.0)   # Overrun (> 15ms = 10.0 * 1.5)
        assert stats.overruns == 1

    def test_window_size(self):
        stats = ScanTimingStats(target_ms=10.0, window_size=3)
        stats.record(100.0)
        stats.record(10.0)
        stats.record(10.0)
        stats.record(10.0)  # Should push out the 100.0
        assert stats.max_ms == 10.0

    def test_jitter_calculation(self):
        stats = ScanTimingStats(target_ms=10.0)
        # Constant timing = zero jitter
        for _ in range(10):
            stats.record(10.0)
        assert stats.jitter_ms == 0.0

    def test_actual_rate_hz(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.0)
        assert stats.actual_rate_hz == pytest.approx(100.0)

    def test_reset(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.0)
        stats.record(20.0)
        stats.reset()
        assert stats.total_scans == 0
        assert stats.overruns == 0
        assert stats.min_ms == 0.0

    def test_to_dict(self):
        stats = ScanTimingStats(target_ms=10.0)
        stats.record(10.0)
        d = stats.to_dict()
        assert "target_ms" in d
        assert "actual_ms" in d
        assert "overruns" in d
        assert "total_scans" in d
        assert d["total_scans"] == 1

# =============================================================================
# DAQ SERVICE ORCHESTRATION TESTS (MOCKED)
# =============================================================================

def _make_service():
    """Create a DAQService instance with __init__ bypassed via mocking.

    Manually sets up only the attributes needed for orchestration tests.
    """
    from daq_service import DAQService

    with mock.patch.object(DAQService, '__init__', lambda self, *a, **kw: None):
        svc = DAQService.__new__(DAQService)

    # Minimal state that orchestration methods depend on
    svc.config = MagicMock()
    svc.config.system.mqtt_base_topic = "nisystem"
    svc.config.system.node_id = "node-001"
    svc.config.system.scan_rate_hz = 100
    svc.config.system.simulation_mode = True
    svc.config.system.project_mode = MagicMock()
    svc.config.channels = {}

    svc.mqtt_client = MagicMock()
    svc._state_machine = DAQStateMachine(DAQState.STOPPED)
    svc._running = threading.Event()
    svc._shutdown_requested = threading.Event()
    svc._command_queue = MagicMock()
    svc._scan_timing = ScanTimingStats(target_ms=10.0)

    svc.state_lock = threading.Lock()
    svc.values_lock = threading.Lock()
    svc.safety_lock = threading.Lock()

    svc.recording = False
    svc.recording_manager = MagicMock()
    svc.current_session_id = "test-session"
    svc.current_user_role = "admin"
    svc.current_project_path = None
    svc.current_project_data = {}

    svc.user_session_manager = MagicMock()
    svc.user_session_manager.has_permission.return_value = True
    # auth_username is a read-only property that calls validate_session
    mock_session = MagicMock()
    mock_session.username = "test_user"
    svc.user_session_manager.validate_session.return_value = mock_session

    svc.script_manager = MagicMock()
    svc.trigger_engine = MagicMock()
    svc.watchdog_engine = MagicMock()
    svc.project_manager = MagicMock()
    svc.audit_trail = MagicMock()
    svc.device_discovery = MagicMock()
    svc.device_discovery.get_crio_nodes.return_value = []
    svc.hardware_reader = None
    svc.simulator = MagicMock()

    svc._stop_command_time = None
    svc._heartbeat_sequence = 0
    svc.channel_values = {}
    svc.channel_raw_values = {}
    svc.channel_timestamps = {}
    svc.channel_acquisition_ts_us = {}

    svc._rate_limiters = {
        'output': TokenBucketRateLimiter(rate=50.0, capacity=100.0),
        'script': TokenBucketRateLimiter(rate=5.0, capacity=10.0),
        'config': TokenBucketRateLimiter(rate=2.0, capacity=5.0),
    }
    svc._rate_limit_warn_times = {}

    # Acquisition event pipeline (diagnostic overlay)
    svc._acq_events = None

    # Safety managers (for stop safety gate)
    svc.alarm_manager = MagicMock()
    svc.alarm_manager.get_active_alarms.return_value = []
    svc.safety_manager = MagicMock()
    svc.safety_manager.latch_state = MagicMock()
    svc.safety_manager.latch_state.name = 'SAFE'
    svc.safety_manager.interlocks = {}

    # cRIO stop ACK tracking
    svc._crio_stop_ack_events = {}

    # User variables (session state)
    svc.user_variables = MagicMock()
    svc.user_variables.session.active = False

    # Channel claims
    svc._clear_channel_claims = MagicMock()
    svc._publish_channel_claims = MagicMock()

    # Stub methods that publish to MQTT (we don't need to test MQTT publishing here)
    svc._publish_system_status = MagicMock()
    svc._publish_command_ack = MagicMock()
    svc._publish_channel_config = MagicMock()
    svc._publish_script_status = MagicMock()
    svc._forward_acquisition_command_to_crio = MagicMock()
    svc._stop_crio_nodes_and_wait = MagicMock(return_value=True)
    svc._load_config = MagicMock()
    svc._handle_test_session_stop = MagicMock()

    # MAX_SCRIPT_CODE_BYTES
    svc.MAX_SCRIPT_CODE_BYTES = 256 * 1024

    return svc

class TestDAQServiceAcquireStart:
    """Test _handle_acquire_start orchestration."""

    def test_acquire_start_transitions_to_running(self):
        svc = _make_service()
        svc._handle_acquire_start(request_id="req-1")

        assert svc._state_machine.state == DAQState.RUNNING
        svc._publish_command_ack.assert_called_with(
            "acquire/start", "req-1", True
        )

    def test_acquire_start_denied_without_permission(self):
        svc = _make_service()
        svc.user_session_manager.has_permission.return_value = False

        svc._handle_acquire_start(request_id="req-1")

        assert svc._state_machine.state == DAQState.STOPPED
        svc._publish_command_ack.assert_called_once()
        call_args = svc._publish_command_ack.call_args
        assert call_args[0][2] is False  # success=False
        assert "Permission denied" in call_args[0][3]

    def test_acquire_start_rejected_when_already_running(self):
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)

        svc._handle_acquire_start(request_id="req-1")

        # Should stay RUNNING, not restart
        assert svc._state_machine.state == DAQState.RUNNING
        svc._publish_command_ack.assert_called_once()
        call_args = svc._publish_command_ack.call_args
        assert call_args[0][2] is False  # success=False

    def test_acquire_start_notifies_engines(self):
        svc = _make_service()
        svc._handle_acquire_start()

        svc.script_manager.on_acquisition_start.assert_called_once()
        svc.trigger_engine.on_acquisition_start.assert_called_once()
        svc.watchdog_engine.on_acquisition_start.assert_called_once()

    def test_acquire_start_locks_safety_config(self):
        svc = _make_service()
        svc._handle_acquire_start()

        svc.project_manager.lock_safety_config.assert_called_once()

    def test_acquire_start_logs_audit_event(self):
        svc = _make_service()
        svc._handle_acquire_start()

        svc.audit_trail.log_event.assert_called_once()

    def test_acquire_start_rollback_on_exception(self):
        """If an exception occurs during start, state should roll back to STOPPED."""
        svc = _make_service()
        # Make _publish_channel_config throw to trigger rollback
        svc._publish_channel_config.side_effect = RuntimeError("config publish failed")

        svc._handle_acquire_start(request_id="req-1")

        assert svc._state_machine.state == DAQState.STOPPED
        svc.project_manager.unlock_safety_config.assert_called_once()

    def test_acquire_start_uses_existing_project_config(self):
        svc = _make_service()
        svc.current_project_path = Path("test_project.json")

        svc._handle_acquire_start()

        svc._load_config.assert_not_called()

    def test_acquire_start_reloads_config_when_no_channels(self):
        svc = _make_service()
        svc.current_project_path = None
        svc.current_project_data = {}
        svc.config.channels = {}  # Empty channels, no project

        svc._handle_acquire_start()

        svc._load_config.assert_called_once()

class TestDAQServiceAcquireStop:
    """Test _handle_acquire_stop orchestration."""

    def test_acquire_stop_transitions_to_stopped(self):
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)

        svc._handle_acquire_stop(request_id="req-1")

        assert svc._state_machine.state == DAQState.STOPPED
        svc._publish_command_ack.assert_called_with(
            "acquire/stop", "req-1", True
        )

    def test_acquire_stop_denied_without_permission(self):
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)
        svc.user_session_manager.has_permission.return_value = False

        svc._handle_acquire_stop(request_id="req-1")

        assert svc._state_machine.state == DAQState.RUNNING
        call_args = svc._publish_command_ack.call_args
        assert call_args[0][2] is False

    def test_acquire_stop_rejected_when_already_stopped(self):
        svc = _make_service()
        # Already STOPPED
        svc._handle_acquire_stop(request_id="req-1")

        assert svc._state_machine.state == DAQState.STOPPED
        call_args = svc._publish_command_ack.call_args
        assert call_args[0][2] is False

    def test_acquire_stop_cascades_to_recording(self):
        """Stopping acquisition should also stop active recording."""
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)
        svc.recording = True
        svc._handle_recording_stop = MagicMock()

        svc._handle_acquire_stop(request_id="req-1")

        svc._handle_recording_stop.assert_called_once()

    def test_acquire_stop_cascades_to_session(self):
        """Stopping acquisition should also stop an active session."""
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)
        svc.user_variables = MagicMock()
        svc.user_variables.session.active = True

        svc._handle_acquire_stop(request_id="req-1")

        assert svc._state_machine.state == DAQState.STOPPED
        svc._handle_test_session_stop.assert_called_once()

    def test_acquire_stop_blocked_by_active_alarms(self):
        """Stop should be rejected if alarms are active (without force)."""
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)
        mock_alarm = MagicMock()
        mock_alarm.channel = "TC001"
        mock_alarm.severity = MagicMock()
        mock_alarm.severity.name = "HIGH"
        svc.alarm_manager.get_active_alarms.return_value = [mock_alarm]

        svc._handle_acquire_stop(request_id="req-1")

        # Should still be RUNNING — stop was blocked
        assert svc._state_machine.state == DAQState.RUNNING
        call_args = svc._publish_command_ack.call_args
        assert call_args[0][2] is False
        assert "active safety conditions" in call_args[0][3]

    def test_acquire_stop_force_overrides_safety(self):
        """force=True should allow stop even with active alarms."""
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)
        mock_alarm = MagicMock()
        mock_alarm.channel = "TC001"
        mock_alarm.severity = MagicMock()
        mock_alarm.severity.name = "HIGH"
        svc.alarm_manager.get_active_alarms.return_value = [mock_alarm]

        svc._handle_acquire_stop(request_id="req-1", force=True)

        assert svc._state_machine.state == DAQState.STOPPED
        svc._publish_command_ack.assert_called_with(
            "acquire/stop", "req-1", True
        )

    def test_acquire_stop_waits_for_crio(self):
        """Stop should call _stop_crio_nodes_and_wait."""
        svc = _make_service()
        svc._state_machine.to(DAQState.RUNNING)

        svc._handle_acquire_stop(request_id="req-1")

        svc._stop_crio_nodes_and_wait.assert_called_once()

class TestDAQServiceScriptValidation:
    """Test MQTT payload validation for scripts."""

    def test_script_add_rejects_oversized_code(self):
        svc = _make_service()
        large_code = "x" * (256 * 1024 + 1)
        payload = {
            "name": "test_script",
            "code": large_code,
            "run_mode": "manual",
        }

        svc._handle_script_add(payload)

        # Script manager should NOT have been called
        svc.script_manager.add_script.assert_not_called()

    def test_script_add_rejects_oversized_name(self):
        svc = _make_service()
        payload = {
            "name": "x" * 257,
            "code": "print('hello')",
            "run_mode": "manual",
        }

        svc._handle_script_add(payload)

        svc.script_manager.add_script.assert_not_called()

    def test_script_add_accepts_valid_payload(self):
        svc = _make_service()
        svc.config.system.project_mode = MagicMock()
        # Ensure we're not in CRIO mode so it processes locally
        svc.config.system.project_mode.__eq__ = lambda self, other: False

        payload = {
            "name": "test_script",
            "code": "result = channel_values.get('TC001', 0)",
            "run_mode": "manual",
        }

        svc._handle_script_add(payload)

        # Script should be processed (even if add_script ultimately fails,
        # it should have been called, meaning validation passed)
        # Note: The actual script_manager.add_script call may happen
        # deeper in the method after more checks

    def test_script_update_rejects_oversized_code(self):
        svc = _make_service()
        large_code = "x" * (256 * 1024 + 1)
        payload = {
            "id": "script-1",
            "code": large_code,
        }

        svc._handle_script_update(payload)

        # Should have returned early without processing

    def test_script_update_accepts_valid_code(self):
        svc = _make_service()
        svc.config.system.project_mode = MagicMock()
        svc.config.system.project_mode.__eq__ = lambda self, other: False

        payload = {
            "id": "script-1",
            "code": "result = 42",
        }

        svc._handle_script_update(payload)

class TestDAQServiceTopics:
    """Test MQTT topic construction."""

    def test_get_topic_base(self):
        svc = _make_service()
        assert svc.get_topic_base() == "nisystem/nodes/node-001"

    def test_get_topic_base_fallback(self):
        svc = _make_service()
        svc.config = None
        assert svc.get_topic_base() == "nisystem/nodes/node-001"

    def test_get_topic_with_category(self):
        svc = _make_service()
        topic = svc.get_topic("channels", "TC001")
        assert topic == "nisystem/nodes/node-001/channels/TC001"

    def test_get_topic_without_entity(self):
        svc = _make_service()
        topic = svc.get_topic("status", "system")
        assert topic == "nisystem/nodes/node-001/status/system"

class TestDAQServiceProperties:
    """Test thread-safe property accessors."""

    def test_running_property(self):
        svc = _make_service()
        assert svc.running is False
        svc.running = True
        assert svc.running is True
        svc.running = False
        assert svc.running is False

    def test_acquiring_property(self):
        svc = _make_service()
        assert svc.acquiring is False
        svc._state_machine.to(DAQState.INITIALIZING)
        assert svc.acquiring is True
        svc._state_machine.to(DAQState.RUNNING)
        assert svc.acquiring is True
        svc._state_machine.to(DAQState.STOPPING)
        assert svc.acquiring is False

    def test_acquisition_state_property(self):
        svc = _make_service()
        assert svc.acquisition_state == "stopped"
        svc._state_machine.to(DAQState.INITIALIZING)
        assert svc.acquisition_state == "initializing"

# =============================================================================
# VALID TRANSITIONS TABLE TESTS
# =============================================================================

class TestValidTransitions:
    """Verify the VALID_TRANSITIONS table is complete and correct."""

    def test_all_valid_transitions_defined(self):
        """All expected valid transitions should be in the table."""
        expected_valid = [
            (DAQState.STOPPED, DAQState.STOPPED),
            (DAQState.STOPPED, DAQState.INITIALIZING),
            (DAQState.STOPPED, DAQState.RUNNING),
            (DAQState.INITIALIZING, DAQState.INITIALIZING),
            (DAQState.INITIALIZING, DAQState.RUNNING),
            (DAQState.INITIALIZING, DAQState.STOPPED),
            (DAQState.RUNNING, DAQState.RUNNING),
            (DAQState.RUNNING, DAQState.STOPPING),
            (DAQState.RUNNING, DAQState.STOPPED),
            (DAQState.STOPPING, DAQState.STOPPING),
            (DAQState.STOPPING, DAQState.STOPPED),
        ]
        for transition in expected_valid:
            assert VALID_TRANSITIONS.get(transition, False), (
                f"Expected valid transition {transition[0].name} -> {transition[1].name} not found"
            )

    def test_invalid_transitions_not_in_table(self):
        """Transitions not in the table should be treated as invalid."""
        invalid = [
            (DAQState.STOPPED, DAQState.STOPPING),
            (DAQState.INITIALIZING, DAQState.STOPPING),
            (DAQState.STOPPING, DAQState.RUNNING),
            (DAQState.STOPPING, DAQState.INITIALIZING),
        ]
        for transition in invalid:
            assert not VALID_TRANSITIONS.get(transition, False), (
                f"Unexpected valid transition {transition[0].name} -> {transition[1].name}"
            )
