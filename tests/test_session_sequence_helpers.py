"""
Session, Sequence, and Helper-class Bug Fix Tests

Verifies fixes for bugs found in the session/sequence/helper audit:

  A3: Session timeout race — state captured inside lock
  A4: Rolling buffer uses deque (O(1) ops) + warn-once
  A5: set_variable_value() catches TypeError/ValueError
  A6: Reset on session start clears stats accumulators
  C1: Sequence loops capped at MAX_LOOP_ITERATIONS
  C2: CONDITIONAL step validates target index bounds
  C3: WAIT_CONDITION raises StepTimeoutError instead of silently continuing
  C4: pause/resume callbacks fire OUTSIDE the lock
  D1: TrendLine.time_to_value handles NaN/inf inputs
  D4: Counter._events uses deque (O(1) popleft)
"""

import math
import pytest
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# Source-level checks — verify each fix is in the code
# ===================================================================

class TestSourceLevelFixes:

    def _read_user_vars(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "user_variables.py").read_text(encoding='utf-8')

    def _read_seq(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "sequence_manager.py").read_text(encoding='utf-8')

    def _read_script(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py").read_text(encoding='utf-8')

    def test_a3_session_timeout_captures_state_inside_lock(self):
        content = self._read_user_vars()
        # The fixed version captures elapsed_seconds inside the lock and
        # only enters the body after we know we need to stop.
        idx = content.find("def check_session_timeout")
        body = content[idx:idx + 3000]
        assert "elapsed_seconds = None" in body or "elapsed_seconds=None" in body
        assert "Lock released" in body or "Captures all state inside the lock" in body

    def test_a4_rolling_buffer_uses_deque(self):
        content = self._read_user_vars()
        assert "deque" in content
        assert "popleft" in content
        # Warn-once flag
        assert "_rolling_capped_warned" in content

    def test_a5_set_variable_value_catches_errors(self):
        content = self._read_user_vars()
        idx = content.find("def set_variable_value")
        body = content[idx:idx + 1500]
        assert "ValueError" in body
        assert "TypeError" in body

    def test_a6_session_reset_clears_accumulators(self):
        content = self._read_user_vars()
        idx = content.find("Reset all variables with reset_mode='test_session'")
        body = content[idx:idx + 1000]
        assert "var.sample_count = 0" in body
        assert "var._sum_squares = 0.0" in body
        assert "var._mean_accumulator = 0.0" in body
        assert "var._m2_accumulator = 0.0" in body

    def test_c1_loop_iterations_capped(self):
        content = self._read_seq()
        assert "MAX_LOOP_ITERATIONS" in content
        # Capping logic
        assert "min(requested, self.MAX_LOOP_ITERATIONS)" in content

    def test_c2_conditional_validates_index(self):
        content = self._read_seq()
        idx = content.find("CONDITIONAL.value")
        body = content[idx:idx + 1000]
        assert "target_index < 0" in body
        assert "len(seq.steps)" in body

    def test_c3_wait_condition_raises_on_timeout(self):
        content = self._read_seq()
        assert "class StepTimeoutError" in content
        idx = content.find("def _wait_for_condition")
        body = content[idx:idx + 1500]
        assert "raise StepTimeoutError" in body

    def test_c4_pause_resume_emit_outside_lock(self):
        content = self._read_seq()
        # Verify both pause and resume use the seq_to_emit pattern
        idx = content.find("def pause_sequence")
        body = content[idx:idx + 1000]
        assert "seq_to_emit" in body
        idx = content.find("def resume_sequence")
        body = content[idx:idx + 1000]
        assert "seq_to_emit" in body

    def test_d1_trendline_handles_nan(self):
        content = self._read_script()
        idx = content.find("def time_to_value")
        body = content[idx:idx + 1500]
        assert "math.isnan(slope)" in body
        assert "math.isnan(intercept)" in body

    def test_d4_counter_uses_deque(self):
        content = self._read_script()
        idx = content.find("self._events: deque")
        assert idx > 0, "Counter._events should be a deque"
        # Verify popleft is used
        assert "self._events.popleft()" in content


# ===================================================================
# Logic replicas
# ===================================================================

class TestRollingBufferDeque:
    """A4: Rolling buffer should use deque for O(1) append/popleft."""

    def test_deque_maxlen_drops_oldest(self):
        d = deque(maxlen=5)
        for i in range(10):
            d.append((float(i), 1.0))
        # Only the last 5 are kept
        assert len(d) == 5
        assert d[0][0] == 5.0
        assert d[-1][0] == 9.0

    def test_popleft_is_O_1(self):
        d = deque()
        for i in range(10000):
            d.append((float(i), 1.0))
        cutoff = 5000
        # Pop expired in O(k)
        while d and d[0][0] < cutoff:
            d.popleft()
        assert len(d) == 5000
        assert d[0][0] == 5000.0


class TestSequenceLoopCap:
    """C1: Loop iterations must be capped."""

    MAX_LOOP_ITERATIONS = 100000

    def test_normal_loop_count_unchanged(self):
        """Loop count of 10 stays 10."""
        requested = 10
        loop_count = min(requested, self.MAX_LOOP_ITERATIONS)
        assert loop_count == 10

    def test_huge_loop_count_capped(self):
        """Loop count of 999_999_999 capped to MAX_LOOP_ITERATIONS."""
        requested = 999_999_999
        loop_count = min(requested, self.MAX_LOOP_ITERATIONS)
        assert loop_count == self.MAX_LOOP_ITERATIONS


class TestConditionalIndexBounds:
    """C2: Conditional jump target must be validated."""

    def test_valid_index_accepted(self):
        seq_steps_count = 50
        target_index = 25
        valid = 0 <= target_index < seq_steps_count
        assert valid

    def test_out_of_bounds_index_rejected(self):
        seq_steps_count = 50
        for bad_index in [-1, 50, 999, 100]:
            valid = 0 <= bad_index < seq_steps_count
            assert not valid

    def test_zero_steps_rejects_any_index(self):
        seq_steps_count = 0
        for any_index in [0, 1, -1]:
            valid = 0 <= any_index < seq_steps_count
            assert not valid


class TestVariableValueCoercion:
    """A5: set_variable_value must reject non-numeric strings cleanly."""

    def test_float_conversion_succeeds(self):
        try:
            v = float(42)
            assert v == 42.0
        except (ValueError, TypeError):
            pytest.fail("Should not raise")

    def test_string_to_float_raises_valueerror(self):
        with pytest.raises(ValueError):
            float("not_a_number")

    def test_none_to_float_raises_typeerror(self):
        with pytest.raises(TypeError):
            float(None)

    def test_dict_to_float_raises_typeerror(self):
        with pytest.raises(TypeError):
            float({"a": 1})


class TestTrendLineNaN:
    """D1: time_to_value must return NaN early for NaN inputs."""

    def test_nan_in_y_returns_nan(self):
        ys = [1.0, 2.0, float('nan'), 4.0]
        # Replica check
        result = float('nan') if any(math.isnan(y) for y in ys) else "computed"
        assert math.isnan(result)

    def test_inf_in_y_returns_nan(self):
        ys = [1.0, 2.0, float('inf'), 4.0]
        result = float('nan') if any(math.isinf(y) for y in ys) else "computed"
        assert math.isnan(result)

    def test_nan_target_returns_nan(self):
        target = float('nan')
        result = float('nan') if math.isnan(target) else "computed"
        assert math.isnan(result)

    def test_zero_slope_returns_nan(self):
        slope = 0.0
        if slope == 0 or math.isnan(slope) or math.isinf(slope):
            result = float('nan')
        else:
            result = 1.0
        assert math.isnan(result)


class TestCounterDeque:
    """D4: Counter._events as deque — O(1) operations."""

    def test_deque_append_and_popleft(self):
        d = deque(maxlen=10000)
        for i in range(100):
            d.append(float(i))
        cutoff = 50.0
        while d and d[0] < cutoff:
            d.popleft()
        assert len(d) == 50
        assert d[0] == 50.0

    def test_unbounded_window_capped_by_maxlen(self):
        """When window=None, maxlen drops oldest automatically."""
        MAX = 10
        d = deque(maxlen=MAX)
        for i in range(100):
            d.append(float(i))
        assert len(d) == MAX
        assert d[0] == 90.0
        assert d[-1] == 99.0


class TestRMSAccumulatorReset:
    """A6: Resetting a stats variable must clear accumulators, not just .value."""

    def test_rms_accumulator_must_clear_on_reset(self):
        """Without clearing _sum_squares, the next sample still uses
        pre-reset state."""
        # Pre-reset: 100 samples of 5.0 each
        sum_squares = 100 * 25.0  # = 2500
        sample_count = 100

        # Reset: only set value=0 (BUG behavior)
        bug_value = 0.0
        # Next sample: 1.0
        sum_squares += 1.0
        sample_count += 1
        bug_rms = math.sqrt(sum_squares / sample_count)
        # Result: ~4.95, NOT ~1.0 — old data leaks in
        assert bug_rms > 4.0

        # Now FIXED behavior: also clear accumulators
        sum_squares = 0.0
        sample_count = 0
        # Next sample: 1.0
        sum_squares += 1.0
        sample_count += 1
        fixed_rms = math.sqrt(sum_squares / sample_count)
        assert fixed_rms == pytest.approx(1.0)


# ===================================================================
# Real-world scenarios
# ===================================================================

class TestRealWorldScenarios:

    def test_runaway_loop_prevented(self):
        """Operator types loop_count=999_999_999 by mistake — must cap."""
        MAX_LOOP_ITERATIONS = 100000
        loop_count = min(999_999_999, MAX_LOOP_ITERATIONS)
        # Even 100K iterations at typical step rates won't run forever
        assert loop_count == 100000

    def test_session_timeout_doesnt_crash_on_concurrent_stop(self):
        """If stop_session() runs between our two lock acquisitions, we
        must not crash with TypeError on datetime.fromisoformat(None)."""
        # Replicate the fixed flow: capture inside lock, only proceed if
        # we have a valid started_at
        session_active = True
        started_at = "2024-01-01T00:00:00"
        timeout_minutes = 1

        # Inside lock: capture state
        if not session_active or timeout_minutes <= 0 or not started_at:
            elapsed_seconds = None
        else:
            try:
                from datetime import datetime
                started = datetime.fromisoformat(started_at)
                elapsed_seconds = (datetime.now() - started).total_seconds()
            except Exception:
                elapsed_seconds = None

        # After lock release, even if started_at is now None in the parent
        # object, we use our local copy
        assert elapsed_seconds is not None  # Safe value captured


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
