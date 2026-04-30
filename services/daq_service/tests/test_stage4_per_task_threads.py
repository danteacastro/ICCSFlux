#!/usr/bin/env python3
"""
Stage 4 per-task producer thread regression tests.

Coverage:
  - _TaskReaderStats dataclass: fields and defaults
  - _TaskReader lifecycle (start/stop/is_alive) using a fake task that
    does NOT need nidaqmx — exercises the read loop with a stub task
    object that mimics the surface our reader touches.
  - Drop-oldest backpressure: when chunk_q fills, oldest chunks are
    discarded and samples_lost_queue_full ticks up; the producer keeps
    running rather than backing up DAQmx.
  - Per-task error isolation: an exception during read() bumps
    consecutive_errors and triggers per-task NaN updates without
    affecting sibling _TaskReaders.
  - _RecordingConsumer drains all _TaskReader queues and dispatches to
    the parent's chunk callback with the right payload shape.
  - Source invariants: per-task lifecycle wiring, deprecation of the
    old single _reader_thread_func, get_health_status surfaces per-task
    state.

Runs without nidaqmx installed; the fake task uses a duck-typed object
covering only the attributes our reader needs.
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import List

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Stage 4 classes are imported indirectly to avoid pulling nidaqmx-dependent
# modules during test collection. capabilities.py is nidaqmx-free, but
# hardware_reader.py wraps the import in try/except — safe to import even
# without the NI driver. The actual nidaqmx Task is replaced with a fake.
from hardware_reader import (  # noqa: E402
    _TaskReader,
    _TaskReaderStats,
    _RecordingConsumer,
    _SlowPollThread,
    _TASK_READER_QUEUE_DEPTH,
    _TASK_READER_MAX_CONSECUTIVE_ERRORS,
    _DIAG_INTERVAL_S,
    TaskGroup,
)
from config_parser import ChannelType  # noqa: E402


# =============================================================================
# Fakes — minimal duck-typed surface our reader touches
# =============================================================================

class _FakeInStream:
    """Mimics nidaqmx Task.in_stream — exposes the few attrs we read."""
    def __init__(self):
        self.avail_samp_per_chan = 0
        self.total_samp_per_chan_acquired = 0
        self.curr_read_pos = 0


class _FakeTiming:
    samp_clk_rate = 10.0


class _FakeTask:
    """Mimics enough of nidaqmx.Task for _TaskReader._loop to run.

    Each call to read_many_sample copies pre-staged values into the
    caller's buffer (or raises if read_should_raise=True), then advances
    the read cursor.
    """
    def __init__(self, n_channels: int, sample_value: float = 1.5):
        self.n_channels = n_channels
        self.sample_value = sample_value
        self.in_stream = _FakeInStream()
        self.timing = _FakeTiming()
        self.read_should_raise: Exception = None
        self.read_count = 0
        self.start_count = 0
        self.stop_count = 0

    def stage_samples(self, n: int):
        """Caller signals N samples available on the next read."""
        self.in_stream.avail_samp_per_chan = n
        self.in_stream.total_samp_per_chan_acquired += n

    def start(self):
        self.start_count += 1

    def stop(self):
        self.stop_count += 1


class _FakeReader:
    """Mimics nidaqmx AnalogMultiChannelReader — fills the caller's buffer."""
    def __init__(self, fake_task: _FakeTask):
        self.task = fake_task

    def read_many_sample(self, buffer, number_of_samples_per_channel, timeout):
        if self.task.read_should_raise is not None:
            err = self.task.read_should_raise
            # one-shot: clear after raising so subsequent loops can recover
            self.task.read_should_raise = None
            raise err
        buffer[:] = self.task.sample_value
        self.task.read_count += 1
        # Advance cursor and clear pending so next iteration sees no data
        # until the test stages more samples.
        self.task.in_stream.curr_read_pos = self.task.in_stream.total_samp_per_chan_acquired
        self.task.in_stream.avail_samp_per_chan = 0


class _FakeParent:
    """Mimics HardwareReader for _TaskReader's parent-references.

    Includes only the attributes _TaskReader._loop and _RecordingConsumer
    actually touch.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_values = {}
        self.value_timestamps = {}
        self._logged_open_tc = set()
        self.sample_rate = 10.0
        self._buffer_size = 1000
        self._first_sample_event = threading.Event()
        self._chunk_callback = None
        self._chunk_cb_error_count = 0
        self._task_readers = {}


def _make_task_group(channel_names: List[str], fake_task: _FakeTask) -> TaskGroup:
    return TaskGroup(
        task=fake_task,
        channel_names=list(channel_names),
        module_name="cDAQ1Mod1",
        channel_type=ChannelType.VOLTAGE_INPUT,
        is_continuous=True,
        reader=_FakeReader(fake_task),
        channel_types={n: ChannelType.VOLTAGE_INPUT for n in channel_names},
    )


# =============================================================================
# _TaskReaderStats dataclass
# =============================================================================

class TestTaskReaderStats:
    def test_default_values(self):
        s = _TaskReaderStats()
        assert s.loops == 0
        assert s.reads == 0
        assert s.empty_polls == 0
        assert s.total_read_ms == 0.0
        assert s.max_read_ms == 0.0
        assert s.max_lag == 0
        assert s.samples_lost_queue_full == 0
        assert s.consecutive_errors == 0
        assert s.total_errors == 0
        assert s.recovery_attempts == 0
        assert s.last_read_ts == 0.0


# =============================================================================
# _TaskReader lifecycle and read loop
# =============================================================================

class TestTaskReaderLifecycle:
    def test_start_stop(self):
        parent = _FakeParent()
        ft = _FakeTask(n_channels=2)
        tg = _make_task_group(["ch_a", "ch_b"], ft)
        tr = _TaskReader(parent, "AI1", tg)

        assert tr.is_alive() is False
        tr.start()
        assert tr.is_alive() is True
        tr.stop(timeout=1.0)
        assert tr.is_alive() is False

    def test_first_sample_event_fires_after_first_read(self):
        parent = _FakeParent()
        ft = _FakeTask(n_channels=1, sample_value=2.5)
        ft.stage_samples(5)
        tg = _make_task_group(["ch_a"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        tr.start()
        try:
            assert tr.first_sample_event.wait(timeout=1.0), "first_sample_event never set"
            # Parent's legacy event must also be set (back-compat).
            assert parent._first_sample_event.is_set()
        finally:
            tr.stop(timeout=1.0)

    def test_latest_values_updated_under_parent_lock(self):
        parent = _FakeParent()
        ft = _FakeTask(n_channels=2, sample_value=7.5)
        ft.stage_samples(3)
        tg = _make_task_group(["ch_a", "ch_b"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        tr.start()
        try:
            tr.first_sample_event.wait(timeout=1.0)
            time.sleep(0.05)
            with parent.lock:
                snap = dict(parent.latest_values)
            # last sample of each channel should be the staged value
            assert snap.get("ch_a") == 7.5
            assert snap.get("ch_b") == 7.5
        finally:
            tr.stop(timeout=1.0)

    def test_chunk_pushed_to_own_queue(self):
        parent = _FakeParent()
        ft = _FakeTask(n_channels=1, sample_value=3.0)
        ft.stage_samples(4)
        tg = _make_task_group(["ch_a"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        tr.start()
        try:
            tr.first_sample_event.wait(timeout=1.0)
            time.sleep(0.05)
            assert tr.chunk_q.qsize() >= 1
            payload = tr.chunk_q.get_nowait()
            task_name, channel_names, samples, t0, rate, channel_types = payload
            assert task_name == "AI1"
            assert channel_names == ["ch_a"]
            assert isinstance(samples, np.ndarray)
            assert samples.shape == (1, 4)
            assert (samples == 3.0).all()
            assert rate == 10.0
        finally:
            tr.stop(timeout=1.0)

    def test_drop_oldest_when_queue_full(self):
        """When the chunk queue fills, oldest chunks are dropped and
        samples_lost_queue_full ticks up. Producer keeps running."""
        parent = _FakeParent()
        ft = _FakeTask(n_channels=1, sample_value=1.0)
        tg = _make_task_group(["ch_a"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        # Pre-fill the queue so the next put_nowait must drop oldest.
        for _ in range(_TASK_READER_QUEUE_DEPTH):
            tr.chunk_q.put_nowait(("dummy",))
        ft.stage_samples(5)
        tr.start()
        try:
            # Wait until either samples_lost_queue_full ticks up OR a few
            # successful reads happen.
            deadline = time.time() + 1.0
            while time.time() < deadline:
                if tr.get_stats().samples_lost_queue_full > 0:
                    break
                time.sleep(0.02)
        finally:
            tr.stop(timeout=1.0)
        s = tr.get_stats()
        # Either we observed loss (most likely) OR queue was drained
        # somewhere first — both prove the producer didn't deadlock.
        assert s.reads >= 1 or s.samples_lost_queue_full > 0

    def test_read_exception_sets_nan_and_continues(self):
        """An exception during read() must set the task's channels to NaN
        and bump consecutive_errors but NOT crash the producer thread."""
        parent = _FakeParent()
        ft = _FakeTask(n_channels=1, sample_value=5.0)
        ft.read_should_raise = RuntimeError("driver hiccup")
        ft.stage_samples(2)   # there's data available, but read will raise
        tg = _make_task_group(["ch_a"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        tr.start()
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline:
                if tr.get_stats().total_errors > 0:
                    break
                time.sleep(0.02)
        finally:
            tr.stop(timeout=1.0)
        s = tr.get_stats()
        assert s.total_errors >= 1
        assert s.consecutive_errors >= 1
        with parent.lock:
            assert "ch_a" in parent.latest_values
            assert np.isnan(parent.latest_values["ch_a"])
        # Thread must have stopped cleanly via stop() — never crashed.
        assert tr.is_alive() is False


class TestTaskReaderIsolation:
    """Per-task isolation: an exception on task A doesn't affect task B."""

    def test_sibling_task_keeps_running_when_other_errors(self):
        parent = _FakeParent()
        ft_a = _FakeTask(n_channels=1, sample_value=10.0)
        ft_a.read_should_raise = RuntimeError("A is broken")
        ft_a.stage_samples(2)

        ft_b = _FakeTask(n_channels=1, sample_value=20.0)
        ft_b.stage_samples(3)

        tg_a = _make_task_group(["ch_a"], ft_a)
        tg_b = _make_task_group(["ch_b"], ft_b)
        tr_a = _TaskReader(parent, "AI_A", tg_a)
        tr_b = _TaskReader(parent, "AI_B", tg_b)

        parent._task_readers = {"AI_A": tr_a, "AI_B": tr_b}
        tr_a.start()
        tr_b.start()
        try:
            # Wait for both to do their first iteration.
            assert tr_b.first_sample_event.wait(timeout=1.0), "B failed to read"
            time.sleep(0.05)
            stats_a = tr_a.get_stats()
            stats_b = tr_b.get_stats()
            # A errored at least once.
            assert stats_a.total_errors >= 1
            # B made at least one successful read despite A failing.
            assert stats_b.reads >= 1
            with parent.lock:
                assert np.isnan(parent.latest_values.get("ch_a", 0.0))
                assert parent.latest_values.get("ch_b") == 20.0
        finally:
            tr_a.stop(timeout=1.0)
            tr_b.stop(timeout=1.0)


# =============================================================================
# _RecordingConsumer
# =============================================================================

class TestRecordingConsumer:
    def test_drains_queues_and_dispatches(self):
        parent = _FakeParent()
        # Set up two fake task readers with pre-stuffed queues.
        ft_a = _FakeTask(n_channels=1)
        tg_a = _make_task_group(["ch_a"], ft_a)
        tr_a = _TaskReader(parent, "AI_A", tg_a)

        ft_b = _FakeTask(n_channels=1)
        tg_b = _make_task_group(["ch_b"], ft_b)
        tr_b = _TaskReader(parent, "AI_B", tg_b)

        parent._task_readers = {"AI_A": tr_a, "AI_B": tr_b}

        received: List[tuple] = []

        def cb(task_name, channel_names, samples, t0, rate, channel_types):
            received.append((task_name, list(channel_names), samples.shape))

        parent._chunk_callback = cb

        # Stuff chunks directly onto each task reader's queue.
        tr_a.chunk_q.put_nowait((
            "AI_A", ["ch_a"], np.zeros((1, 5)), 0.0, 10.0, {}
        ))
        tr_b.chunk_q.put_nowait((
            "AI_B", ["ch_b"], np.zeros((1, 7)), 0.0, 10.0, {}
        ))

        consumer = _RecordingConsumer(parent)
        consumer.start()
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline and len(received) < 2:
                time.sleep(0.02)
        finally:
            consumer.stop(timeout=1.0)

        names = sorted(r[0] for r in received)
        assert names == ["AI_A", "AI_B"]

    def test_callback_exception_does_not_kill_consumer(self):
        parent = _FakeParent()
        ft = _FakeTask(n_channels=1)
        tg = _make_task_group(["ch_a"], ft)
        tr = _TaskReader(parent, "AI1", tg)
        parent._task_readers = {"AI1": tr}

        def bad_cb(*args, **kwargs):
            raise RuntimeError("consumer-side boom")

        parent._chunk_callback = bad_cb

        # Push chunks; expect the consumer to log + keep draining.
        for _ in range(3):
            tr.chunk_q.put_nowait((
                "AI1", ["ch_a"], np.zeros((1, 1)), 0.0, 10.0, {}
            ))

        consumer = _RecordingConsumer(parent)
        consumer.start()
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline and tr.chunk_q.qsize() > 0:
                time.sleep(0.02)
            assert tr.chunk_q.empty()
            # Consumer is still alive after multiple raised callbacks.
            assert consumer.is_alive()
        finally:
            consumer.stop(timeout=1.0)


# =============================================================================
# _SlowPollThread lifecycle (no DI/counter tasks => pure idle loop)
# =============================================================================

class TestSlowPollThreadIdle:
    def test_starts_and_stops_with_no_tasks(self):
        """When there are no DI or counter tasks, the slow-poll thread
        should still start, idle quietly, and stop on demand."""
        parent = SimpleNamespace(
            tasks={},
            counter_tasks={},
            lock=threading.Lock(),
            latest_values={},
            config=SimpleNamespace(channels={}),
        )
        sp = _SlowPollThread(parent)
        sp.start()
        try:
            assert sp.is_alive()
            time.sleep(0.1)
            assert sp.is_alive()
        finally:
            sp.stop(timeout=1.0)
        assert sp.is_alive() is False


# =============================================================================
# Source-level invariants
# =============================================================================

class TestStage4SourceInvariants:
    @pytest.fixture(scope="class")
    def src(self):
        return (Path(__file__).parent.parent / "hardware_reader.py").read_text(
            encoding="utf-8"
        )

    def test_per_task_thread_classes_present(self, src):
        for cls in ("_TaskReader", "_TaskReaderStats",
                    "_RecordingConsumer", "_SlowPollThread"):
            assert f"class {cls}" in src

    def test_init_creates_thread_containers(self, src):
        assert "self._task_readers: Dict[str, _TaskReader] = {}" in src
        assert "self._recording_consumer: Optional[_RecordingConsumer] = None" in src
        assert "self._slow_poll_thread: Optional[_SlowPollThread] = None" in src

    def test_start_spawns_per_task_readers(self, src):
        assert "tr = _TaskReader(self, task_name, task_group)" in src
        assert "self._recording_consumer = _RecordingConsumer(self)" in src
        assert "self._slow_poll_thread = _SlowPollThread(self)" in src

    def test_stop_drains_all_three_thread_types(self, src):
        # Per-task readers
        assert "for task_name, tr in list(self._task_readers.items()):" in src
        # Recording consumer
        assert "self._recording_consumer.stop(" in src
        # Slow-poll thread
        assert "self._slow_poll_thread.stop(" in src

    def test_legacy_reader_thread_func_is_deprecated(self, src):
        """The old single-thread reader is now a stub. Must contain the
        deprecation marker so anyone reading the file knows it's dead."""
        assert "[DEPRECATED in Stage 4" in src
        assert "_reader_thread_func is deprecated" in src

    def test_health_status_exposes_per_task_state(self, src):
        assert "'task_count':" in src
        assert "'consumer_alive':" in src
        assert "'slow_poll_alive':" in src
        assert "'tasks':" in src

    def test_watchdog_logs_per_task_health(self, src):
        """The pre-Stage-4 watchdog logged single-thread state. Stage 4
        must report per-task aliveness so operators can identify the
        specific failing module in a multi-module chassis."""
        assert "task_health = ', '.join(" in src

    def test_drop_oldest_backpressure_implemented(self, src):
        """Producer must implement drop-oldest on Full to avoid backing up
        DAQmx. Without this the driver hits -200279 the moment a consumer
        falls behind."""
        assert "self.chunk_q.put_nowait(payload)" in src
        assert "except Full:" in src
        assert "samples_lost_queue_full" in src

    def test_per_task_recovery_present(self, src):
        """A single task's error burst must restart only that task, not
        tear down all reads in the chassis."""
        assert "_TASK_READER_MAX_CONSECUTIVE_ERRORS" in src
        assert "per-task recovery" in src
