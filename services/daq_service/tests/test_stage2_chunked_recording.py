#!/usr/bin/env python3
"""
Stage 2 chunked-recording regression tests.

Coverage:
  - RecordingManager.write_chunk() actual behavior:
      * no-op when not recording / triggered mode / empty / malformed
      * N rows written for N-sample chunk
      * per-sample decimation (continues across chunk boundaries)
      * per-sample time-interval filter (uses reconstructed sample times)
      * selected_channels filter applies to chunk channels and extras
      * extras merged into rows
  - Start/stop hooks fire after lock release; raising hooks don't fail
    start()/stop().
  - Source-level invariants:
      * HardwareReader chunk callback API (set/has, attribute, copy on emit,
        exception caught)
      * daq_service.py bridge (_on_chunk, enable/disable, scan-loop gate)

Run without nidaqmx installed; uses numpy (already a project dependency).
"""

import csv
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from recording_manager import RecordingManager  # noqa: E402


# =============================================================================
# Helpers
# =============================================================================

@pytest.fixture
def temp_recording_dir():
    d = tempfile.mkdtemp(prefix="iccs_test_recording_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def rm(temp_recording_dir):
    """A RecordingManager set up so all samples pass the time/decimation
    filters by default. Individual tests override config attrs as needed."""
    m = RecordingManager(default_path=temp_recording_dir)
    m.config.base_path = temp_recording_dir
    m.config.sample_interval = 0.0       # accept all samples (no time gate)
    m.config.sample_interval_unit = "seconds"
    m.config.decimation = 1
    m.config.mode = "continuous"
    return m


def _read_data_rows(file_path):
    """Read a recording CSV; return rows excluding metadata comment lines."""
    rows = []
    with open(file_path, "r", newline="") as f:
        for raw in f:
            if not raw.strip() or raw.startswith("#"):
                continue
            rows.append(next(csv.reader([raw])))
    return rows


# =============================================================================
# RecordingManager.write_chunk — actual behavior
# =============================================================================

class TestWriteChunkBasic:
    def test_no_op_when_not_recording(self, rm):
        samples = np.array([[1.0, 2.0, 3.0]])
        rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
        assert rm.samples_written == 0
        assert rm.current_file is None

    def test_no_op_in_triggered_mode(self, rm):
        rm.config.mode = "triggered"
        rm.config.trigger_channel = "ch_a"
        rm.config.trigger_condition = ">"
        rm.config.trigger_value = 0.0
        rm.start()
        try:
            samples = np.array([[1.0, 2.0]])
            n_before = rm.samples_written
            rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
            assert rm.samples_written == n_before
        finally:
            rm.stop()

    def test_writes_n_rows_for_n_samples(self, rm):
        rm.start()
        try:
            samples = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
            rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        # 1 header row + 5 data rows
        assert len(rows) == 6, f"expected 6 rows, got {len(rows)}: {rows}"

    def test_rows_contain_chunk_channel_values(self, rm):
        rm.start()
        try:
            samples = np.array([[10.0, 20.0, 30.0]])
            rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        header = rows[0]
        assert "ch_a" in header
        ch_a_idx = header.index("ch_a")
        values = [float(r[ch_a_idx]) for r in rows[1:]]
        assert values == [10.0, 20.0, 30.0]

    def test_extras_merged_into_each_row(self, rm):
        rm.start()
        try:
            samples = np.array([[10.0, 20.0]])
            rm.write_chunk(
                "AI1",
                ["ch_a"],
                samples,
                0.0,
                10.0,
                {},
                extra_row_values={"sys.recording": 1.0, "ch_b": 99.0},
            )
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        header = rows[0]
        assert "ch_a" in header
        assert "ch_b" in header
        assert "sys.recording" in header

    def test_decimation_per_sample(self, rm):
        rm.config.decimation = 4   # keep every 4th sample
        rm.start()
        try:
            samples = np.array([[float(i) for i in range(20)]])
            rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        assert len(rows) == 6, f"want 1 header + 5 data, got {len(rows)}"
        ch_a_idx = rows[0].index("ch_a")
        ch_a_values = [float(r[ch_a_idx]) for r in rows[1:]]
        # decimation_counter increments BEFORE the < check — first written
        # sample is the one where counter reaches `decimation`. Counter starts
        # at 0; with decimation=4 it triggers at indices 3, 7, 11, 15, 19.
        assert ch_a_values == [3.0, 7.0, 11.0, 15.0, 19.0]

    def test_decimation_counter_persists_across_chunks(self, rm):
        """decimation_counter is RecordingManager state, not per-chunk —
        gating must continue seamlessly across chunk boundaries."""
        rm.config.decimation = 3
        rm.start()
        try:
            # Chunk 1: indices 0,1,2 → counter hits 3 at index 2 → row at 2.
            rm.write_chunk("AI1", ["ch_a"], np.array([[0.0, 1.0, 2.0]]), 0.0, 10.0, {})
            # Chunk 2: indices 0,1,2 → counter resets after chunk-1 fire,
            # so 0 brings to 1, 1 to 2, 2 to 3 → row at chunk-2 index 2.
            rm.write_chunk("AI1", ["ch_a"], np.array([[10.0, 20.0, 30.0]]), 1.0, 10.0, {})
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        ch_a_idx = rows[0].index("ch_a")
        values = [float(r[ch_a_idx]) for r in rows[1:]]
        assert values == [2.0, 30.0]

    def test_time_interval_filter(self, rm):
        """sample_interval=1.0s + 30 samples at 10 Hz = ~3 rows kept."""
        rm.config.sample_interval = 1.0
        rm.config.sample_interval_unit = "seconds"
        rm.config.decimation = 1
        rm.start()
        try:
            samples = np.array([[float(i) for i in range(30)]])
            rm.write_chunk("AI1", ["ch_a"], samples, 0.0, 10.0, {})
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        # 1 header + ~3-4 data rows (first sample passes immediately;
        # subsequent gated by 1s interval over a 3s span).
        n_data = len(rows) - 1
        assert 3 <= n_data <= 4, f"got {n_data} data rows: {rows}"

    def test_selected_channels_filter_excludes_others(self, rm):
        rm.config.selected_channels = ["ch_a"]
        rm.start()
        try:
            samples = np.array([[1.0], [99.0]])
            rm.write_chunk(
                "AI1",
                ["ch_a", "ch_b"],
                samples,
                0.0,
                10.0,
                {},
                extra_row_values={"ch_c": 7.0},
            )
        finally:
            rm.stop()
        rows = _read_data_rows(rm.current_file)
        header = rows[0]
        assert "ch_a" in header
        assert "ch_b" not in header   # filtered out (not selected)
        assert "ch_c" not in header   # extras filtered too

    def test_malformed_shape_logged_not_raised(self, rm, caplog):
        rm.start()
        try:
            with caplog.at_level("WARNING"):
                rm.write_chunk("AI1", ["ch_a"], np.array([1.0, 2.0]), 0.0, 10.0, {})
            # 1D array is malformed — but write_chunk must not raise.
            assert any("malformed samples shape" in r.getMessage() for r in caplog.records)
        finally:
            rm.stop()

    def test_shape_mismatch_logged_not_raised(self, rm, caplog):
        rm.start()
        try:
            samples = np.zeros((3, 5))   # 3 rows, but only 1 channel name
            with caplog.at_level("WARNING"):
                rm.write_chunk("AI1", ["only_one"], samples, 0.0, 10.0, {})
            assert any("channel_names length" in r.getMessage() for r in caplog.records)
        finally:
            rm.stop()

    def test_empty_chunk_is_noop(self, rm):
        rm.start()
        try:
            rm.write_chunk("AI1", ["ch_a"], np.zeros((1, 0)), 0.0, 10.0, {})
            assert rm.samples_written == 0
        finally:
            rm.stop()


# =============================================================================
# Start/stop hooks
# =============================================================================

class TestRecordingHooks:
    def test_on_record_start_fires_after_start(self, rm):
        called = []
        rm._on_record_start = lambda: called.append("start")
        assert rm.start() is True
        try:
            assert called == ["start"]
        finally:
            rm.stop()

    def test_on_record_stop_fires_after_stop(self, rm):
        called = []
        rm._on_record_stop = lambda: called.append("stop")
        rm.start()
        rm.stop()
        assert called == ["stop"]

    def test_start_hook_exception_does_not_fail_start(self, rm, caplog):
        def boom():
            raise RuntimeError("boom")
        rm._on_record_start = boom
        with caplog.at_level("WARNING"):
            assert rm.start() is True   # start still succeeded
        try:
            assert any("start hook raised" in r.getMessage() for r in caplog.records)
        finally:
            rm.stop()

    def test_stop_hook_exception_does_not_fail_stop(self, rm, caplog):
        def boom():
            raise RuntimeError("boom")
        rm._on_record_stop = boom
        rm.start()
        with caplog.at_level("WARNING"):
            assert rm.stop() is True   # stop still succeeded
        assert any("stop hook raised" in r.getMessage() for r in caplog.records)


# =============================================================================
# HardwareReader chunk-callback API — source-level invariants
# (Avoiding instantiation: HardwareReader.__init__ requires nidaqmx, which
# we intentionally don't depend on for unit tests.)
# =============================================================================

class TestHardwareReaderChunkAPI:
    @pytest.fixture(scope="class")
    def src(self):
        return (Path(__file__).parent.parent / "hardware_reader.py").read_text(encoding="utf-8")

    def test_set_chunk_callback_method(self, src):
        assert "def set_chunk_callback(self, callback)" in src

    def test_has_chunk_callback_method(self, src):
        assert "def has_chunk_callback(self)" in src

    def test_chunk_callback_attr_initialized(self, src):
        assert "self._chunk_callback" in src
        assert "self._chunk_cb_error_count" in src

    def test_emit_uses_buffer_copy(self, src):
        """Producer must hand the consumer a COPY — never a view of the
        live read buffer (the buffer gets reused next iteration)."""
        assert "buffer.copy()" in src

    def test_emit_callback_exception_caught(self, src):
        """A raising consumer must NOT crash the reader thread."""
        assert "chunk callback raised on" in src

    def test_emit_uses_actual_rate(self, src):
        """t0/rate computation must use task.timing.samp_clk_rate (the
        post-coercion actual rate), not the requested rate. Otherwise
        timestamps drift on slow modules where DAQmx coerced the request."""
        assert "task_group.task.timing.samp_clk_rate" in src

    def test_transforms_applied_in_place_before_emit(self, src):
        """Stage 2 refactor: unit conversion (A->mA) and open-TC sentinel
        must be applied to the raw buffer once, before both the dashboard
        update and the chunk emission. Otherwise the chunk values diverge
        from what the dashboard shows."""
        # Vectorized transform on the buffer (not a per-element scalar in
        # the lock loop, which was the pre-Stage-2 pattern).
        assert "buffer[i, :] *= 1000.0" in src
        # Vectorized open-TC sentinel detection.
        assert "np.abs(buffer[i, :]) > 1e9" in src


# =============================================================================
# daq_service bridge — source-level invariants
# =============================================================================

class TestDaqServiceBridge:
    @pytest.fixture(scope="class")
    def src(self):
        return (Path(__file__).parent.parent / "daq_service.py").read_text(encoding="utf-8")

    def test_chunk_recording_methods_present(self, src):
        assert "def _enable_chunk_recording(self):" in src
        assert "def _disable_chunk_recording(self):" in src
        assert "def _on_chunk(self, " in src

    def test_hooks_wired_in_init_recording_manager(self, src):
        assert "self.recording_manager._on_record_start = self._enable_chunk_recording" in src
        assert "self.recording_manager._on_record_stop = self._disable_chunk_recording" in src

    def test_chunk_active_flag_initialized(self, src):
        assert "self._chunk_recording_active = False" in src

    def test_scan_loop_gates_write_sample(self, src):
        """When chunk recording is active, scan-loop write_sample MUST NOT
        fire — otherwise we double-write rows with stale timestamps."""
        assert "if not getattr(self, '_chunk_recording_active', False):" in src

    def test_on_chunk_calls_write_chunk(self, src):
        assert "rm.write_chunk(" in src

    def test_on_chunk_snapshots_other_hw_under_lock(self, src):
        """Other-task hardware values from latest_values cache must be
        snapshotted under the reader's lock to avoid torn reads."""
        assert "with self.hardware_reader.lock:" in src
        assert "self.hardware_reader.latest_values" in src

    def test_on_chunk_includes_sys_uv_fx_extras(self, src):
        """Stage 2 chunk-mode CSV columns must match scan-mode CSV columns
        (sys.* + uv.* + fx.* present in both)."""
        assert "'sys.acquiring'" in src
        assert "'sys.session_active'" in src
        assert "'sys.recording'" in src
        assert "uv." in src
        assert "fx." in src

    def test_set_chunk_callback_invoked_on_enable(self, src):
        assert "self.hardware_reader.set_chunk_callback(self._on_chunk)" in src

    def test_callback_cleared_on_disable(self, src):
        assert "self.hardware_reader.set_chunk_callback(None)" in src
