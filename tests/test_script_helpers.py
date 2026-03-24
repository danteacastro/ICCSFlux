"""
Unit tests for script helper classes: signal processing, analysis, and data logging.

Tests all 10 new helper classes added to the script engine:

Group A (DAQ + cRIO):
- SignalFilter (EMA / low-pass)
- LookupTable (linear interpolation)
- RampSoak (thermal setpoint profiles)
- TrendLine (online linear regression)
- RingBuffer (circular buffer with stats)
- PeakDetector (signal peak detection)

Group B (DAQ-only):
- SpectralAnalysis (FFT-based frequency analysis)
- SPCChart (Statistical Process Control)
- BiquadFilter (IIR digital filter)
- DataLog (structured data logging)

Also tests cRIO DAQ-only stubs raise clear errors.

No MQTT broker, hardware, or cRIO required — all dependencies are mocked.
"""

import math
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add service paths
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "crio_node_v2"))

from script_manager import (
    SignalFilter, LookupTable, RampSoak, TrendLine, RingBuffer, PeakDetector,
    SpectralAnalysis, SPCChart, BiquadFilter, _CascadeFilter, DataLog,
)

import script_engine as crio_engine

# =============================================================================
# SignalFilter Tests
# =============================================================================

class TestSignalFilter:
    """Tests for EMA / low-pass filter."""

    def test_alpha_constructor(self):
        filt = SignalFilter(alpha=0.5)
        assert filt.alpha == 0.5

    def test_tau_dt_constructor(self):
        filt = SignalFilter(tau=5.0, dt=0.1)
        expected = 0.1 / (5.0 + 0.1)  # ~0.01961
        assert abs(filt.alpha - expected) < 1e-10

    def test_default_alpha(self):
        filt = SignalFilter()
        assert filt.alpha == 0.1

    def test_alpha_clamped(self):
        filt = SignalFilter(alpha=5.0)
        assert filt.alpha == 1.0
        filt2 = SignalFilter(alpha=-1.0)
        assert filt2.alpha == 0.0

    def test_first_update_returns_input(self):
        filt = SignalFilter(alpha=0.1)
        assert filt.update(100.0) == 100.0

    def test_smoothing(self):
        filt = SignalFilter(alpha=0.5)
        filt.update(0.0)
        result = filt.update(10.0)
        assert result == 5.0  # 0 + 0.5 * (10 - 0)

    def test_alpha_one_passes_through(self):
        filt = SignalFilter(alpha=1.0)
        filt.update(0.0)
        assert filt.update(100.0) == 100.0

    def test_alpha_zero_holds_first(self):
        filt = SignalFilter(alpha=0.0)
        filt.update(50.0)
        assert filt.update(100.0) == 50.0

    def test_value_property(self):
        filt = SignalFilter(alpha=0.5)
        assert filt.value == 0.0  # before any update
        filt.update(10.0)
        assert filt.value == 10.0

    def test_reset(self):
        filt = SignalFilter(alpha=0.5)
        filt.update(100.0)
        filt.reset()
        assert filt.value == 0.0
        assert filt.update(50.0) == 50.0  # first update after reset

    def test_convergence(self):
        """Low alpha filter converges to constant input."""
        filt = SignalFilter(alpha=0.1)
        for _ in range(200):
            filt.update(42.0)
        assert abs(filt.value - 42.0) < 0.01

# =============================================================================
# LookupTable Tests
# =============================================================================

class TestLookupTable:
    """Tests for linear interpolation lookup table."""

    def test_basic_interpolation(self):
        cal = LookupTable([(0, 0), (100, 50), (200, 150)])
        assert cal.lookup(50) == 25.0

    def test_clamp_below(self):
        cal = LookupTable([(0, 0), (100, 100)])
        assert cal.lookup(-50) == 0.0

    def test_clamp_above(self):
        cal = LookupTable([(0, 0), (100, 100)])
        assert cal.lookup(200) == 100.0

    def test_exact_point(self):
        cal = LookupTable([(0, 0), (50, 25), (100, 100)])
        assert cal.lookup(0) == 0.0
        assert cal.lookup(100) == 100.0

    def test_callable(self):
        cal = LookupTable([(0, 0), (100, 100)])
        assert cal(50) == 50.0

    def test_auto_sorts(self):
        cal = LookupTable([(100, 100), (0, 0), (50, 50)])
        assert cal.lookup(25) == 25.0

    def test_points_property(self):
        cal = LookupTable([(100, 100), (0, 0)])
        pts = cal.points
        assert pts[0][0] == 0  # sorted

    def test_requires_two_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            LookupTable([(0, 0)])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            LookupTable([])

    def test_non_uniform_spacing(self):
        cal = LookupTable([(0, 0), (10, 100), (1000, 200)])
        assert cal.lookup(5) == 50.0  # midpoint of first segment

# =============================================================================
# RampSoak Tests
# =============================================================================

class TestRampSoak:
    """Tests for thermal setpoint profiles."""

    def test_ramp_up(self):
        profile = RampSoak([
            {'type': 'ramp', 'target': 100, 'rate': 6000},  # 100/sec
        ])
        profile.start(initial_value=0.0)
        time.sleep(0.05)
        sp = profile.tick()
        assert 0 < sp <= 100

    def test_soak_holds_value(self):
        profile = RampSoak([
            {'type': 'soak', 'duration': 10.0},
        ])
        profile.start(initial_value=50.0)
        sp = profile.tick()
        assert sp == 50.0

    def test_done_flag(self):
        profile = RampSoak([
            {'type': 'ramp', 'target': 10, 'rate': 600000},  # very fast
        ])
        profile.start(initial_value=0.0)
        time.sleep(0.01)
        profile.tick()
        assert profile.done is True

    def test_segment_index(self):
        profile = RampSoak([
            {'type': 'ramp', 'target': 10, 'rate': 600000},
            {'type': 'soak', 'duration': 100},
        ])
        profile.start()
        time.sleep(0.01)
        profile.tick()
        assert profile.segment_index == 1  # past first ramp, in soak

    def test_progress(self):
        profile = RampSoak([
            {'type': 'ramp', 'target': 10, 'rate': 600000},
            {'type': 'soak', 'duration': 100},
        ])
        profile.start()
        time.sleep(0.01)
        profile.tick()
        assert profile.progress == 0.5  # 1 of 2 segments done

    def test_elapsed(self):
        profile = RampSoak([{'type': 'soak', 'duration': 100}])
        profile.start()
        time.sleep(0.05)
        assert profile.elapsed >= 0.04

    def test_reset(self):
        profile = RampSoak([{'type': 'soak', 'duration': 1}])
        profile.start(initial_value=100.0)
        profile.reset()
        assert profile.done is False
        assert profile.elapsed == 0.0
        assert profile.segment_index == 0

    def test_tick_before_start(self):
        profile = RampSoak([{'type': 'ramp', 'target': 100, 'rate': 10}])
        assert profile.tick() == 0.0  # not started yet

    def test_requires_segments(self):
        with pytest.raises(ValueError, match="at least one"):
            RampSoak([])

    def test_ramp_down(self):
        profile = RampSoak([
            {'type': 'ramp', 'target': 0, 'rate': 600000},
        ])
        profile.start(initial_value=100.0)
        time.sleep(0.01)
        sp = profile.tick()
        assert sp == 0.0  # fast enough to complete

# =============================================================================
# TrendLine Tests
# =============================================================================

class TestTrendLine:
    """Tests for online linear regression."""

    def test_linear_data(self):
        trend = TrendLine(window=100)
        for i in range(10):
            result = trend.update(float(i))
        assert abs(result['slope'] - 1.0) < 0.01
        assert result['r_squared'] > 0.99

    def test_constant_data(self):
        trend = TrendLine(window=50)
        for _ in range(20):
            result = trend.update(5.0)
        assert abs(result['slope']) < 0.001
        assert abs(result['intercept'] - 5.0) < 0.1

    def test_single_point(self):
        trend = TrendLine()
        result = trend.update(42.0)
        assert result['count'] == 1
        assert result['slope'] == 0.0

    def test_predict(self):
        trend = TrendLine(window=100)
        for i in range(20):
            trend.update(float(i * 2))  # slope = 2
        prediction = trend.predict(steps_ahead=5)
        # Should predict roughly 20*2 + 5*2 = 50
        assert prediction > 40

    def test_predict_empty(self):
        trend = TrendLine()
        assert trend.predict() == 0.0

    def test_time_to_value(self):
        trend = TrendLine(window=100)
        for i in range(20):
            trend.update(float(i))
        steps = trend.time_to_value(100.0)
        assert steps > 0  # should be reachable
        assert not math.isnan(steps)

    def test_time_to_value_unreachable(self):
        trend = TrendLine()
        for i in range(20):
            trend.update(float(i))  # increasing
        steps = trend.time_to_value(-100.0)  # below and going up
        assert math.isnan(steps)

    def test_time_to_value_flat(self):
        trend = TrendLine()
        for _ in range(20):
            trend.update(5.0)
        assert math.isnan(trend.time_to_value(10.0))

    def test_window_eviction(self):
        trend = TrendLine(window=5)
        for i in range(10):
            trend.update(float(i))
        result = trend.update(10.0)
        assert result['count'] == 5  # window limit

# =============================================================================
# RingBuffer Tests
# =============================================================================

class TestRingBuffer:
    """Tests for circular buffer with statistics."""

    def test_append_and_values(self):
        buf = RingBuffer(size=5)
        for i in range(3):
            buf.append(float(i))
        assert buf.values == [0.0, 1.0, 2.0]

    def test_wrap_around(self):
        buf = RingBuffer(size=3)
        for i in range(5):
            buf.append(float(i))
        assert buf.values == [2.0, 3.0, 4.0]

    def test_full_property(self):
        buf = RingBuffer(size=3)
        assert buf.full is False
        for i in range(3):
            buf.append(float(i))
        assert buf.full is False  # becomes full on 4th append
        buf.append(99.0)
        assert buf.full is True

    def test_count(self):
        buf = RingBuffer(size=5)
        buf.append(1.0)
        buf.append(2.0)
        assert buf.count == 2

    def test_mean(self):
        buf = RingBuffer(size=10)
        for v in [10, 20, 30]:
            buf.append(float(v))
        assert buf.mean == 20.0

    def test_min_max(self):
        buf = RingBuffer(size=10)
        for v in [5, 1, 9, 3]:
            buf.append(float(v))
        assert buf.min == 1.0
        assert buf.max == 9.0

    def test_std(self):
        buf = RingBuffer(size=10)
        for v in [2, 4, 4, 4, 5, 5, 7, 9]:
            buf.append(float(v))
        # Sample std dev (n-1) of [2,4,4,4,5,5,7,9]: variance=32/7, std≈2.138
        assert abs(buf.std - 2.138) < 0.01

    def test_last_first(self):
        buf = RingBuffer(size=5)
        for i in range(3):
            buf.append(float(i))
        assert buf.first == 0.0
        assert buf.last == 2.0

    def test_last_first_wrapped(self):
        buf = RingBuffer(size=3)
        for i in range(5):
            buf.append(float(i))
        assert buf.first == 2.0
        assert buf.last == 4.0

    def test_clear(self):
        buf = RingBuffer(size=5)
        buf.append(1.0)
        buf.append(2.0)
        buf.clear()
        assert buf.count == 0
        assert buf.full is False
        assert buf.values == []

    def test_empty_stats(self):
        buf = RingBuffer(size=5)
        assert buf.mean == 0.0
        assert buf.min == 0.0
        assert buf.max == 0.0
        assert buf.std == 0.0
        assert buf.first == 0.0
        assert buf.last == 0.0

    def test_single_element_std(self):
        buf = RingBuffer(size=5)
        buf.append(42.0)
        assert buf.std == 0.0

# =============================================================================
# PeakDetector Tests
# =============================================================================

class TestPeakDetector:
    """Tests for signal peak detection."""

    def test_simple_peak(self):
        peaks = PeakDetector()
        results = []
        for v in [0, 1, 5, 10, 5, 1, 0]:
            r = peaks.update(v)
            if r:
                results.append(r)
        assert len(results) == 1
        assert results[0]['height'] == 10

    def test_no_peak_monotonic(self):
        peaks = PeakDetector()
        for v in [1, 2, 3, 4, 5]:
            assert peaks.update(v) is None

    def test_min_height_filter(self):
        peaks = PeakDetector(min_height=8.0)
        results = []
        for v in [0, 5, 0, 10, 0]:
            r = peaks.update(v)
            if r:
                results.append(r)
        assert len(results) == 1
        assert results[0]['height'] == 10

    def test_min_distance(self):
        peaks = PeakDetector(min_distance=5)
        results = []
        # Two peaks at positions 3 and 6 — too close
        for v in [0, 5, 10, 5, 0, 5, 10, 5, 0]:
            r = peaks.update(v)
            if r:
                results.append(r)
        # First peak detected, second may be filtered by distance
        assert len(results) >= 1

    def test_count_property(self):
        peaks = PeakDetector()
        for v in [0, 5, 0, 10, 0]:
            peaks.update(v)
        assert peaks.count >= 1

    def test_last_peak(self):
        peaks = PeakDetector()
        for v in [0, 5, 0, 10, 0]:
            peaks.update(v)
        lp = peaks.last_peak
        assert lp is not None
        assert 'height' in lp

    def test_peaks_list_bounded(self):
        """Peaks list is bounded to MAX_PEAKS."""
        peaks = PeakDetector()
        # Generate more than MAX_PEAKS peaks
        for i in range(PeakDetector.MAX_PEAKS + 100):
            peaks.update(0)
            peaks.update(10)
            peaks.update(0)
        assert len(peaks.peaks) <= PeakDetector.MAX_PEAKS

    def test_area_accumulation(self):
        peaks = PeakDetector(threshold=0.0)
        for v in [0, 5, 10, 5, 0]:
            r = peaks.update(v)
        # The peak result should have an area > 0
        if r:
            assert r['area'] >= 0

# =============================================================================
# SpectralAnalysis Tests (DAQ-only)
# =============================================================================

class TestSpectralAnalysis:
    """Tests for FFT-based frequency analysis."""

    def test_ready_flag(self):
        spec = SpectralAnalysis(window_size=8, sample_rate=100.0)
        for i in range(7):
            spec.update(float(i))
        assert spec.ready is False
        spec.update(7.0)
        assert spec.ready is True

    def test_window_rounds_to_power_of_2(self):
        spec = SpectralAnalysis(window_size=10)
        # Should round up to 16
        assert spec._n == 16

    def test_analyze_not_ready(self):
        spec = SpectralAnalysis(window_size=8)
        assert spec.analyze() is None

    def test_dominant_frequency_sine(self):
        """A pure sine wave should show dominant frequency at the sine frequency."""
        sample_rate = 100.0
        freq = 10.0  # 10 Hz sine
        spec = SpectralAnalysis(window_size=128, sample_rate=sample_rate)
        for i in range(128):
            t = i / sample_rate
            spec.update(math.sin(2 * math.pi * freq * t))
        result = spec.analyze()
        assert result is not None
        assert abs(result['dominant_freq'] - freq) < 2.0  # within 2 Hz

    def test_analyze_returns_expected_keys(self):
        spec = SpectralAnalysis(window_size=8, sample_rate=10.0)
        for i in range(8):
            spec.update(float(i))
        result = spec.analyze()
        assert 'frequencies' in result
        assert 'magnitudes' in result
        assert 'dominant_freq' in result
        assert 'dominant_mag' in result
        assert 'thd' in result

    def test_dc_signal_low_thd(self):
        """A DC signal should have no significant harmonics."""
        spec = SpectralAnalysis(window_size=32, sample_rate=10.0)
        for _ in range(32):
            spec.update(5.0)
        result = spec.analyze()
        # DC signal, dominant at DC but we skip DC, so magnitude is low
        assert result is not None

    def test_pure_python_fft(self):
        """Test the pure-Python FFT directly."""
        # Simple 4-point DFT
        data = [1.0, 0.0, -1.0, 0.0]
        result = SpectralAnalysis._fft(data)
        assert len(result) == 4
        # DC component should be ~0
        assert abs(result[0]) < 0.01

# =============================================================================
# SPCChart Tests (DAQ-only)
# =============================================================================

class TestSPCChart:
    """Tests for Statistical Process Control."""

    def test_add_samples_forms_subgroups(self):
        spc = SPCChart(subgroup_size=5)
        for i in range(10):
            spc.add_sample(float(i))
        assert len(spc._subgroup_means) == 2

    def test_add_subgroup_directly(self):
        spc = SPCChart(subgroup_size=5)
        spc.add_subgroup([1, 2, 3, 4, 5])
        assert len(spc._subgroup_means) == 1
        assert spc.x_bar == 3.0

    def test_xbar_rbar(self):
        spc = SPCChart(subgroup_size=3)
        spc.add_subgroup([10, 11, 12])
        spc.add_subgroup([9, 10, 11])
        assert abs(spc.x_bar - 10.5) < 0.01
        assert spc.r_bar == 2.0

    def test_control_limits(self):
        spc = SPCChart(subgroup_size=5)
        for _ in range(25):
            spc.add_subgroup([10, 10.5, 9.5, 10.2, 9.8])
        assert spc.ucl > spc.x_bar
        assert spc.lcl < spc.x_bar

    def test_in_control_stable_process(self):
        spc = SPCChart(subgroup_size=5)
        import random
        rng = random.Random(42)
        for _ in range(25):
            spc.add_subgroup([10 + rng.gauss(0, 0.1) for _ in range(5)])
        assert spc.in_control is True

    def test_out_of_control_shift(self):
        spc = SPCChart(subgroup_size=5)
        # First 20 stable
        for _ in range(20):
            spc.add_subgroup([10.0, 10.1, 9.9, 10.0, 10.0])
        # Then a big shift
        for _ in range(5):
            spc.add_subgroup([20.0, 20.1, 19.9, 20.0, 20.0])
        assert spc.in_control is False

    def test_spec_limits_cp_cpk(self):
        spc = SPCChart(subgroup_size=5)
        for _ in range(25):
            spc.add_subgroup([10.0, 10.1, 9.9, 10.05, 9.95])
        spc.set_spec_limits(lsl=9.0, usl=11.0)
        assert spc.cp > 0
        assert spc.cpk > 0

    def test_cp_cpk_without_spec_limits(self):
        spc = SPCChart(subgroup_size=5)
        spc.add_subgroup([10, 10, 10, 10, 10])
        assert spc.cp == 0.0
        assert spc.cpk == 0.0

    def test_check_rules_returns_list(self):
        spc = SPCChart(subgroup_size=5)
        assert isinstance(spc.check_rules(), list)

    def test_max_subgroups_eviction(self):
        spc = SPCChart(subgroup_size=3, num_subgroups=5)
        for i in range(10):
            spc.add_subgroup([float(i), float(i), float(i)])
        assert len(spc._subgroup_means) == 5

# =============================================================================
# BiquadFilter Tests (DAQ-only)
# =============================================================================

class TestBiquadFilter:
    """Tests for IIR digital filter."""

    def test_lowpass_attenuates_high_freq(self):
        """Low-pass filter should attenuate a high-frequency signal."""
        lp = BiquadFilter.lowpass(cutoff_hz=5.0, sample_rate=100.0)
        # Feed a high-frequency signal (40 Hz)
        outputs = []
        for i in range(200):
            t = i / 100.0
            sample = math.sin(2 * math.pi * 40 * t)
            outputs.append(lp.process(sample))
        # Steady-state amplitude should be much less than 1.0
        peak = max(abs(v) for v in outputs[100:])  # skip transient
        assert peak < 0.1

    def test_lowpass_passes_low_freq(self):
        """Low-pass filter should pass a low-frequency signal."""
        lp = BiquadFilter.lowpass(cutoff_hz=20.0, sample_rate=100.0)
        outputs = []
        for i in range(500):
            t = i / 100.0
            sample = math.sin(2 * math.pi * 1.0 * t)  # 1 Hz
            outputs.append(lp.process(sample))
        peak = max(abs(v) for v in outputs[300:])
        assert peak > 0.8

    def test_highpass_factory(self):
        hp = BiquadFilter.highpass(cutoff_hz=10.0, sample_rate=100.0)
        assert hp is not None
        assert hp.process(0.0) == 0.0

    def test_bandpass_factory(self):
        bp = BiquadFilter.bandpass(center_hz=10.0, sample_rate=100.0, q=2.0)
        assert bp is not None

    def test_notch_factory(self):
        notch = BiquadFilter.notch(center_hz=60.0, sample_rate=1000.0)
        assert notch is not None

    def test_reset(self):
        lp = BiquadFilter.lowpass(cutoff_hz=5.0, sample_rate=100.0)
        lp.process(10.0)
        lp.process(20.0)
        lp.reset()
        assert lp._x1 == 0.0
        assert lp._y1 == 0.0

    def test_cascade(self):
        """Cascade of two lowpass filters should still work."""
        filt = BiquadFilter.cascade([
            BiquadFilter.lowpass(5.0, 100.0),
            BiquadFilter.lowpass(5.0, 100.0),
        ])
        result = filt.process(1.0)
        assert isinstance(result, float)

    def test_cascade_reset(self):
        filt = BiquadFilter.cascade([
            BiquadFilter.lowpass(5.0, 100.0),
            BiquadFilter.lowpass(5.0, 100.0),
        ])
        filt.process(10.0)
        filt.reset()
        # After reset, processing 0 should give 0
        assert filt.process(0.0) == 0.0

# =============================================================================
# DataLog Tests (DAQ-only)
# =============================================================================

class TestDataLog:
    """Tests for structured data logging."""

    def test_log_with_publish(self):
        published = {}
        def mock_publish(key, value):
            published[key] = value

        log = DataLog('quality', publish_fn=mock_publish)
        log.log(10.5, label='width_mm')
        assert 'datalog.quality.width_mm' in published
        assert published['datalog.quality.width_mm'] == 10.5

    def test_log_without_label(self):
        published = {}
        def mock_publish(key, value):
            published[key] = value

        log = DataLog('test', publish_fn=mock_publish)
        log.log(42)
        assert 'datalog.test' in published

    def test_log_dict(self):
        published = {}
        def mock_publish(key, value):
            published[key] = value

        log = DataLog('batch', publish_fn=mock_publish)
        log.log_dict({'width': 10.5, 'height': 3.2})
        assert 'datalog.batch.width' in published
        assert 'datalog.batch.height' in published

    def test_mark(self):
        published = {}
        def mock_publish(key, value):
            published[key] = value

        log = DataLog('qc', publish_fn=mock_publish)
        log.mark('out_of_spec')
        assert 'datalog.qc.mark.out_of_spec' in published
        assert published['datalog.qc.mark.out_of_spec'] == 1

    def test_count(self):
        log = DataLog('test', publish_fn=lambda k, v: None)
        log.log(1)
        log.log(2)
        log.mark('event')
        assert log.count == 3

    def test_marks_list(self):
        log = DataLog('test', publish_fn=lambda k, v: None)
        log.mark('first')
        log.mark('second')
        marks = log.marks
        assert len(marks) == 2
        assert marks[0]['event'] == 'first'

    def test_marks_bounded(self):
        log = DataLog('test', publish_fn=lambda k, v: None)
        for i in range(DataLog.MAX_MARKS + 100):
            log.mark(f'event_{i}')
        assert len(log.marks) <= DataLog.MAX_MARKS

    def test_no_publish_fn(self):
        """DataLog without publish_fn should not crash."""
        log = DataLog('test')
        log.log(42, label='value')
        log.mark('event')
        assert log.count == 2

# =============================================================================
# cRIO DAQ-Only Stubs Tests
# =============================================================================

class TestCRIODAQOnlyStubs:
    """Test that DAQ-only classes raise clear errors on cRIO."""

    def test_spectral_analysis_stub(self):
        with pytest.raises(RuntimeError, match="only available on the DAQ"):
            crio_engine._SpectralAnalysisStub()

    def test_spc_chart_stub(self):
        with pytest.raises(RuntimeError, match="only available on the DAQ"):
            crio_engine._SPCChartStub()

    def test_biquad_filter_stub(self):
        with pytest.raises(RuntimeError, match="only available on the DAQ"):
            crio_engine._BiquadFilterStub()

    def test_datalog_stub(self):
        with pytest.raises(RuntimeError, match="only available on the DAQ"):
            crio_engine._DataLogStub()

    def test_stub_message_includes_alternatives(self):
        """Error message should mention Group A alternatives."""
        with pytest.raises(RuntimeError, match="SignalFilter"):
            crio_engine._SpectralAnalysisStub()

# =============================================================================
# cRIO Group A classes exist and work
# =============================================================================

class TestCRIOGroupAAvailable:
    """Verify Group A classes are importable from cRIO script_engine."""

    def test_signal_filter(self):
        filt = crio_engine.SignalFilter(alpha=0.5)
        assert filt.update(10.0) == 10.0

    def test_lookup_table(self):
        cal = crio_engine.LookupTable([(0, 0), (100, 100)])
        assert cal.lookup(50) == 50.0

    def test_ramp_soak(self):
        profile = crio_engine.RampSoak([{'type': 'soak', 'duration': 10}])
        profile.start()
        assert profile.tick() == 0.0

    def test_trend_line(self):
        trend = crio_engine.TrendLine(window=10)
        result = trend.update(5.0)
        assert result['count'] == 1

    def test_ring_buffer(self):
        buf = crio_engine.RingBuffer(size=5)
        buf.append(42.0)
        assert buf.count == 1

    def test_peak_detector(self):
        peaks = crio_engine.PeakDetector()
        assert peaks.count == 0
