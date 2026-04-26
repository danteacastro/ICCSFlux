"""
User Variable Statistics Tests

Verifies the running statistics (RMS, stddev) handle bad inputs gracefully:
  - NaN sample must not corrupt the accumulator forever
  - Inf sample must be skipped
  - Welford's algorithm rounding must not produce ValueError on sqrt(-tiny)

These bugs would cause Mike's vibration/AC/RMS measurements to permanently
read NaN after a single bad sensor reading.
"""

import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# 1. Source-level checks
# ===================================================================

class TestSourceLevelFixes:

    def _read(self):
        path = Path(__file__).parent.parent / "services" / "daq_service" / "user_variables.py"
        return path.read_text(encoding='utf-8')

    def test_rms_skips_nan(self):
        content = self._read()
        # Find the RMS block
        idx = content.find("variable_type == 'rms'")
        snippet = content[idx:idx + 600]
        assert "math.isnan(scaled)" in snippet
        assert "return" in snippet  # Skip-NaN exits the method early

    def test_stddev_skips_nan(self):
        content = self._read()
        idx = content.find("variable_type == 'stddev'")
        snippet = content[idx:idx + 800]
        assert "math.isnan(scaled)" in snippet

    def test_stddev_clamps_negative_m2(self):
        """Floating-point rounding can make _m2 slightly negative — must clamp."""
        content = self._read()
        idx = content.find("variable_type == 'stddev'")
        snippet = content[idx:idx + 800]
        assert "max(0.0" in snippet


# ===================================================================
# 2. Logic replicas — verify the algorithm with fakes
# ===================================================================

def update_rms(sum_squares, sample_count, scaled):
    """Replica of the RMS update logic."""
    if math.isnan(scaled) or math.isinf(scaled):
        return sum_squares, sample_count, None  # skip
    sample_count += 1
    sum_squares += scaled * scaled
    value = math.sqrt(sum_squares / sample_count)
    return sum_squares, sample_count, value


def update_stddev(mean_acc, m2_acc, sample_count, scaled):
    """Replica of the Welford stddev update logic."""
    if math.isnan(scaled) or math.isinf(scaled):
        return mean_acc, m2_acc, sample_count, None  # skip
    sample_count += 1
    delta = scaled - mean_acc
    mean_acc += delta / sample_count
    delta2 = scaled - mean_acc
    m2_acc += delta * delta2
    if sample_count > 1:
        m2 = max(0.0, m2_acc)
        value = math.sqrt(m2 / (sample_count - 1))
    else:
        value = 0.0
    return mean_acc, m2_acc, sample_count, value


class TestRMS:

    def test_rms_normal_samples(self):
        ss, n, v = 0.0, 0, None
        for sample in [1.0, 2.0, 3.0]:
            ss, n, v = update_rms(ss, n, sample)
        # RMS of [1,2,3] = sqrt((1+4+9)/3) = sqrt(14/3)
        assert v == pytest.approx(math.sqrt(14.0/3.0))

    def test_rms_skips_nan(self):
        """NaN sample must not corrupt accumulator."""
        ss, n, v = 0.0, 0, None
        ss, n, v = update_rms(ss, n, 5.0)
        # Inject NaN
        ss, n, v_nan = update_rms(ss, n, float('nan'))
        assert v_nan is None  # skipped
        # Continue with normal sample — RMS still valid
        ss, n, v = update_rms(ss, n, 5.0)
        assert v == pytest.approx(5.0)

    def test_rms_skips_inf(self):
        ss, n, v = 0.0, 0, None
        ss, n, v = update_rms(ss, n, 3.0)
        ss, n, v_inf = update_rms(ss, n, float('inf'))
        assert v_inf is None
        ss, n, v = update_rms(ss, n, 3.0)
        assert not math.isnan(v)
        assert not math.isinf(v)

    def test_rms_skips_negative_inf(self):
        ss, n, v = 0.0, 0, None
        ss, n, v_inf = update_rms(ss, n, float('-inf'))
        assert v_inf is None
        assert ss == 0.0
        assert n == 0


class TestStdDev:

    def test_stddev_normal(self):
        m, m2, n, v = 0.0, 0.0, 0, None
        for sample in [1.0, 2.0, 3.0, 4.0, 5.0]:
            m, m2, n, v = update_stddev(m, m2, n, sample)
        # stddev of [1,2,3,4,5] (sample) = sqrt(sum((x-mean)^2)/(n-1)) = sqrt(10/4) ≈ 1.581
        assert v == pytest.approx(1.5811, abs=0.01)

    def test_stddev_skips_nan(self):
        m, m2, n, v = 0.0, 0.0, 0, None
        for sample in [1.0, 2.0, 3.0]:
            m, m2, n, v = update_stddev(m, m2, n, sample)
        good_value = v
        # Inject NaN
        m, m2, n, v_nan = update_stddev(m, m2, n, float('nan'))
        assert v_nan is None
        # Continue with normal sample
        m, m2, n, v = update_stddev(m, m2, n, 4.0)
        assert not math.isnan(v)

    def test_stddev_negative_m2_clamped(self):
        """Force a tiny negative m2 (simulating FP rounding) — must not crash."""
        m, m2, n, v = 5.0, -1e-15, 5, None  # Slightly negative m2
        # Update with another sample
        m, m2, n, v = update_stddev(m, m2, n, 5.0)
        # Must not be NaN (would happen if sqrt(-tiny) wasn't clamped)
        assert not math.isnan(v)
        assert v >= 0

    def test_stddev_constant_signal(self):
        """Constant signal — stddev should be 0 (or very close)."""
        m, m2, n, v = 0.0, 0.0, 0, None
        for _ in range(100):
            m, m2, n, v = update_stddev(m, m2, n, 7.5)
        # Should be exactly 0 or very near 0
        assert v == pytest.approx(0.0, abs=1e-9)


class TestRealWorldVibration:
    """Simulates Mike's vibration monitoring scenario."""

    def test_burst_of_nan_doesnt_break_rms(self):
        """Sensor goes bad for 100 readings, then recovers — RMS should
        still produce valid output."""
        ss, n, v = 0.0, 0, None
        # Good samples
        for _ in range(100):
            ss, n, v = update_rms(ss, n, 0.5)
        before_burst = v

        # 100 NaN readings (sensor disconnected)
        for _ in range(100):
            ss, n, _ = update_rms(ss, n, float('nan'))

        # Sensor reconnects
        for _ in range(100):
            ss, n, v = update_rms(ss, n, 0.5)

        # RMS should still be valid (close to 0.5)
        assert not math.isnan(v)
        assert v == pytest.approx(0.5, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
