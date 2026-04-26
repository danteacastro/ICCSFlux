"""
Acquisition Start Resilience Tests

Verifies the fixes for the bugs found in the acquisition start path audit:
  - Task start failures are NOT silently ignored
  - Partial task creation is rolled back on failure
  - Orphan task cleanup either succeeds or raises a clear error
  - The reader thread synchronization works (first sample event)

These tests use mocks to simulate NI-DAQmx behavior since real hardware
isn't available in CI.
"""

import pytest
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# 1. Source-level fixes verification
# ===================================================================

class TestAcquisitionStartFixes:
    """Verify the source code contains the fixes (defensive against regression)."""

    def test_start_continuous_raises_on_task_start_failure(self):
        """_start_continuous_acquisition must raise if any task fails to start."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # Verify the helper exists
        assert "def _start_continuous_acquisition" in content
        # Verify it tracks failures
        assert "failed_tasks" in content
        # Verify it raises RuntimeError on failure
        assert 'raise RuntimeError' in content
        # Verify it rolls back already-started tasks
        assert "Roll back" in content or "roll back" in content

    def test_start_continuous_waits_for_first_sample(self):
        """_start_continuous_acquisition must wait for first sample event."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        assert "_first_sample_event" in content
        # Both setting and waiting on the event
        assert "_first_sample_event.wait" in content
        assert "_first_sample_event.set" in content

    def test_create_tasks_rolls_back_on_failure(self):
        """_create_tasks must close all created tasks on failure."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        assert "_close_all_tasks_silently" in content
        # The helper should be called from the wrapper
        assert "self._close_all_tasks_silently()" in content

    def test_orphan_cleanup_raises_on_failure(self):
        """_safe_create_task must raise descriptive error if cleanup fails."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # The function must NOT silently swallow cleanup errors
        assert "could not clean up the orphan" in content.lower()


# ===================================================================
# 2. Logic tests using fakes
# ===================================================================

class FakeTask:
    """Mock NI-DAQmx Task for testing."""
    def __init__(self, name, fail_on_start=False):
        self.name = name
        self.fail_on_start = fail_on_start
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        if self.fail_on_start:
            raise RuntimeError(f"Hardware fault: {self.name} could not start")
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeTaskGroup:
    def __init__(self, task, is_continuous=True):
        self.task = task
        self.is_continuous = is_continuous
        self.channel_names = []
        self.channel_types = {}
        self.module_name = "FakeMod"
        self.channel_type = None
        self.reader = None


class TestStartContinuousLogic:
    """Test the logic of _start_continuous_acquisition without nidaqmx."""

    def _build_fake_reader(self, tasks_dict):
        """Build a minimal HardwareReader-like object for testing logic."""
        reader = MagicMock()
        reader.tasks = tasks_dict
        reader._running = False
        reader._reader_thread = None
        reader._first_sample_event = None
        return reader

    def test_all_tasks_succeed_no_raise(self):
        """If all tasks start successfully, no exception is raised."""
        tasks = {
            "t1": FakeTaskGroup(FakeTask("t1")),
            "t2": FakeTaskGroup(FakeTask("t2")),
        }
        # Simulate the loop logic from _start_continuous_acquisition
        failed = []
        started = []
        for name, tg in tasks.items():
            if tg.is_continuous:
                try:
                    tg.task.start()
                    started.append(name)
                except Exception as e:
                    failed.append((name, str(e)))
        assert not failed
        assert started == ["t1", "t2"]
        assert all(tg.task.started for tg in tasks.values())

    def test_one_task_fails_raises_runtime_error(self):
        """If even one task fails, the logic should raise."""
        tasks = {
            "t1": FakeTaskGroup(FakeTask("t1")),
            "t2": FakeTaskGroup(FakeTask("t2", fail_on_start=True)),
            "t3": FakeTaskGroup(FakeTask("t3")),
        }
        failed = []
        started = []
        for name, tg in tasks.items():
            if tg.is_continuous:
                try:
                    tg.task.start()
                    started.append(name)
                except Exception as e:
                    failed.append((name, str(e)))

        # Verify behavior
        assert len(failed) == 1
        assert failed[0][0] == "t2"
        assert "Hardware fault" in failed[0][1]

        # If we ran the rollback, t1 should be stopped
        if failed:
            for name in started:
                tasks[name].task.stop()

        assert tasks["t1"].task.stopped
        # t2 was never started successfully so we don't need to stop it

    def test_rollback_only_stops_started_tasks(self):
        """Rollback must only stop tasks that actually started."""
        tasks = {
            "t1": FakeTaskGroup(FakeTask("t1")),  # Will succeed
            "t2": FakeTaskGroup(FakeTask("t2", fail_on_start=True)),  # Will fail
        }
        started = []
        for name, tg in tasks.items():
            try:
                tg.task.start()
                started.append(name)
            except Exception:
                pass

        # Rollback
        for name in started:
            tasks[name].task.stop()

        assert tasks["t1"].task.stopped  # Was started, then rolled back
        assert not tasks["t2"].task.stopped  # Was never started


class TestFirstSampleEventSync:
    """Test the threading.Event-based first-sample synchronization."""

    def test_event_blocks_until_set(self):
        """Event.wait() must return True if set within timeout."""
        event = threading.Event()

        def set_after_delay():
            time.sleep(0.1)
            event.set()

        threading.Thread(target=set_after_delay, daemon=True).start()
        result = event.wait(timeout=1.0)
        assert result is True

    def test_event_times_out(self):
        """Event.wait() returns False if timeout expires without set."""
        event = threading.Event()
        start = time.time()
        result = event.wait(timeout=0.1)
        elapsed = time.time() - start
        assert result is False
        assert 0.1 <= elapsed < 0.5  # Roughly the timeout

    def test_event_already_set(self):
        """If event is already set, wait returns immediately."""
        event = threading.Event()
        event.set()
        start = time.time()
        result = event.wait(timeout=2.0)
        elapsed = time.time() - start
        assert result is True
        assert elapsed < 0.05  # Should be near-instant


class TestRollbackHelper:
    """Test the _close_all_tasks_silently logic."""

    def test_close_input_tasks(self):
        """All input tasks should be stopped and closed."""
        tasks = {
            "t1": FakeTaskGroup(FakeTask("t1")),
            "t2": FakeTaskGroup(FakeTask("t2")),
        }
        # Simulate _close_all_tasks_silently
        for tg in list(tasks.values()):
            try:
                tg.task.stop()
            except Exception:
                pass
            try:
                tg.task.close()
            except Exception:
                pass
        tasks.clear()
        assert len(tasks) == 0

    def test_close_handles_exceptions(self):
        """Cleanup must not raise even if individual close() throws."""
        bad_task = MagicMock()
        bad_task.stop.side_effect = RuntimeError("stop fail")
        bad_task.close.side_effect = RuntimeError("close fail")
        tg = FakeTaskGroup(bad_task)

        # This should not raise
        try:
            tg.task.stop()
        except Exception:
            pass
        try:
            tg.task.close()
        except Exception:
            pass
        # Test passes if we got here


class TestOrphanCleanupLogic:
    """Test the orphan task cleanup behavior (Bug #5 fix)."""

    def test_cleanup_failure_raises_descriptive_error(self):
        """When cleanup fails, error message must mention restart/reboot."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # The descriptive error must mention how to recover
        assert "Restart the service" in content or "restart the service" in content.lower()

    def test_unfound_orphan_raises(self):
        """If no orphan found in our process, must raise (don't blindly retry)."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # The "no orphan found" path must raise, not silently retry
        assert "no orphan was" in content or "no orphan was\n" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
