"""
Unit tests for services/gc_node/gc_qc.py

Tests cover:
- SSTCriteria: defaults, serialization roundtrip, custom values
- SystemSuitabilityTest: resolution, tailing, plates, capacity factor, RSD,
  passing/failing evaluations, multiple replicates, clear()
- QCLimits: defaults, serialization roundtrip
- QCTracker: blank, check standard, duplicate, spike, cal verification,
  history filtering, control chart data, summary
- MethodValidation: LOD, LOQ, from_dict roundtrip, status, linearity

Target: ~35-40 tests.
"""

import math
import sys
import os
import unittest

# Ensure the project root is on sys.path so gc_qc can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.gc_node.gc_qc import (
    SSTCriteria,
    SSTResult,
    SystemSuitabilityTest,
    QCLimits,
    QCSampleType,
    QCTracker,
    MethodValidation,
)

# ---------------------------------------------------------------------------
# Helper factories for mock analysis results
# ---------------------------------------------------------------------------

def _make_analysis_result(components, unknown_peaks=None, run_number=0,
                          total_area=None, timestamp='2025-01-15T10:30:00'):
    """Build a dict that looks like GCAnalysisEngine.finish_run() output."""
    result = {
        'components': dict(components),
        'unknown_peaks': unknown_peaks or [],
        'total_area': total_area or sum(
            c.get('area', 0) for c in components.values()
        ),
        'run_number': run_number,
        'timestamp': timestamp,
    }
    return result

def _make_component(retention_time, peak_width, area, area_pct=0.0,
                    peak_height=1.0, peak_start=None, peak_end=None,
                    asymmetry=1.0, theoretical_plates=None,
                    usp_tailing=None, resolution=None,
                    capacity_factor=None, concentration=0.0):
    """Build a single component dict."""
    return {
        'retention_time': retention_time,
        'peak_width': peak_width,
        'peak_height': peak_height,
        'area': area,
        'area_pct': area_pct,
        'peak_start': peak_start or retention_time - peak_width,
        'peak_end': peak_end or retention_time + peak_width,
        'asymmetry': asymmetry,
        'theoretical_plates': theoretical_plates,
        'usp_tailing': usp_tailing,
        'resolution': resolution,
        'capacity_factor': capacity_factor,
        'concentration': concentration,
    }

def _default_two_component_result(run_number=1):
    """Standard two-component result (Methane + Ethane) for SST tests."""
    return _make_analysis_result(
        components={
            'Methane': _make_component(
                retention_time=30.0, peak_width=2.0, area=100.0,
                area_pct=50.0, peak_height=1.0, peak_start=28.0,
                peak_end=32.0, asymmetry=1.1, theoretical_plates=12500,
                usp_tailing=1.05, resolution=None, capacity_factor=2.0,
            ),
            'Ethane': _make_component(
                retention_time=60.0, peak_width=2.5, area=80.0,
                area_pct=40.0, peak_height=0.8, peak_start=57.0,
                peak_end=63.0, asymmetry=1.2, theoretical_plates=10000,
                usp_tailing=1.1, resolution=8.0, capacity_factor=5.0,
            ),
        },
        unknown_peaks=[{'retention_time': 90.0, 'area': 20.0, 'area_pct': 10.0}],
        total_area=200.0,
        run_number=run_number,
    )

# ======================================================================
# TestSSTCriteria
# ======================================================================

class TestSSTCriteria(unittest.TestCase):
    """SSTCriteria dataclass: defaults, custom values, serialization."""

    def test_default_values(self):
        """USP <621> default criteria are set correctly."""
        c = SSTCriteria()
        self.assertAlmostEqual(c.min_resolution, 1.5)
        self.assertAlmostEqual(c.max_tailing, 2.0)
        self.assertEqual(c.min_plates, 2000)
        self.assertAlmostEqual(c.max_rsd_area_pct, 2.0)
        self.assertAlmostEqual(c.max_rsd_rt_pct, 1.0)
        self.assertAlmostEqual(c.max_rt_drift_s, 0.5)
        self.assertEqual(c.min_replicates, 5)

    def test_to_dict_from_dict_roundtrip(self):
        """Serialize to dict and back preserves all fields."""
        original = SSTCriteria(
            min_resolution=2.0, max_tailing=1.5, min_plates=5000,
            max_rsd_area_pct=1.0, max_rsd_rt_pct=0.5,
            max_rt_drift_s=0.3, min_replicates=6,
        )
        d = original.to_dict()
        restored = SSTCriteria.from_dict(d)
        self.assertAlmostEqual(restored.min_resolution, 2.0)
        self.assertAlmostEqual(restored.max_tailing, 1.5)
        self.assertEqual(restored.min_plates, 5000)
        self.assertAlmostEqual(restored.max_rsd_area_pct, 1.0)
        self.assertAlmostEqual(restored.max_rsd_rt_pct, 0.5)
        self.assertAlmostEqual(restored.max_rt_drift_s, 0.3)
        self.assertEqual(restored.min_replicates, 6)

    def test_custom_values(self):
        """Custom criteria can be supplied at construction."""
        c = SSTCriteria(min_resolution=3.0, min_plates=10000)
        self.assertAlmostEqual(c.min_resolution, 3.0)
        self.assertEqual(c.min_plates, 10000)
        # Other fields keep defaults
        self.assertAlmostEqual(c.max_tailing, 2.0)

# ======================================================================
# TestSystemSuitabilityTest
# ======================================================================

class TestSystemSuitabilityTest(unittest.TestCase):
    """SystemSuitabilityTest: SST calculations and evaluate()."""

    # --- Static calculation methods ---

    def test_resolution_calculation(self):
        """R = 2*(tR2 - tR1) / (w1_base + w2_base) using 1.699 scaling."""
        peak1 = {'retention_time': 30.0, 'peak_width': 2.0}
        peak2 = {'retention_time': 60.0, 'peak_width': 2.5}
        # w1_base = 2.0 * 1.699 = 3.398
        # w2_base = 2.5 * 1.699 = 4.2475
        # R = 2 * (60 - 30) / (3.398 + 4.2475) = 60 / 7.6455 = 7.847...
        r = SystemSuitabilityTest._calc_resolution(peak1, peak2)
        expected = 2.0 * 30.0 / (2.0 * 1.699 + 2.5 * 1.699)
        self.assertAlmostEqual(r, expected, places=3)

    def test_resolution_zero_width(self):
        """Resolution returns 0 when peak widths are zero."""
        peak1 = {'retention_time': 10.0, 'peak_width': 0.0}
        peak2 = {'retention_time': 20.0, 'peak_width': 0.0}
        r = SystemSuitabilityTest._calc_resolution(peak1, peak2)
        self.assertAlmostEqual(r, 0.0)

    def test_tailing_factor_from_asymmetry(self):
        """T = (1 + asymmetry) / 2. Symmetric peak (asym=1.0) gives T=1.0."""
        # Single symmetric value
        t = SystemSuitabilityTest._calc_tailing_from_asymmetry([1.0])
        self.assertAlmostEqual(t, 1.0)

        # Moderately asymmetric
        t = SystemSuitabilityTest._calc_tailing_from_asymmetry([1.4])
        self.assertAlmostEqual(t, (1.0 + 1.4) / 2.0)

        # Average of multiple values
        t = SystemSuitabilityTest._calc_tailing_from_asymmetry([1.2, 1.4])
        avg_asym = (1.2 + 1.4) / 2.0
        self.assertAlmostEqual(t, (1.0 + avg_asym) / 2.0)

    def test_tailing_empty_list(self):
        """Empty asymmetry list returns 1.0 (ideal)."""
        t = SystemSuitabilityTest._calc_tailing_from_asymmetry([])
        self.assertAlmostEqual(t, 1.0)

    def test_theoretical_plates_calculation(self):
        """N = 5.545 * (tR / W_half)^2."""
        rt = 60.0
        w_half = 2.0
        n = SystemSuitabilityTest._calc_plates_half_width(rt, w_half)
        expected = 5.545 * (60.0 / 2.0) ** 2  # 5.545 * 900 = 4990.5
        self.assertAlmostEqual(n, expected, places=1)

    def test_theoretical_plates_zero_width(self):
        """Zero or negative width returns 0 plates."""
        self.assertAlmostEqual(
            SystemSuitabilityTest._calc_plates_half_width(60.0, 0.0), 0.0
        )
        self.assertAlmostEqual(
            SystemSuitabilityTest._calc_plates_half_width(60.0, -1.0), 0.0
        )

    def test_capacity_factor_calculation(self):
        """k' = (tR - t0) / t0."""
        k = SystemSuitabilityTest._calc_capacity_factor(60.0, 10.0)
        self.assertAlmostEqual(k, 5.0)

    def test_capacity_factor_zero_t0(self):
        """Zero dead time returns 0 capacity factor."""
        k = SystemSuitabilityTest._calc_capacity_factor(60.0, 0.0)
        self.assertAlmostEqual(k, 0.0)

    def test_rsd_calculation(self):
        """%RSD = (stdev / |mean|) * 100. Uses n-1 denominator."""
        vals = [100.0, 102.0, 98.0, 101.0, 99.0]
        rsd = SystemSuitabilityTest._calc_rsd(vals)
        n = len(vals)
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        stdev = math.sqrt(variance)
        expected = (stdev / abs(mean)) * 100.0
        self.assertAlmostEqual(rsd, expected, places=4)

    def test_rsd_single_value(self):
        """Single value gives 0 RSD (cannot compute stdev)."""
        self.assertAlmostEqual(SystemSuitabilityTest._calc_rsd([42.0]), 0.0)

    def test_evaluate_passing_criteria(self):
        """5 identical good replicates should pass all SST criteria."""
        criteria = SSTCriteria(
            min_resolution=1.0,
            max_tailing=2.0,
            min_plates=1000,
            max_rsd_area_pct=5.0,
            max_rsd_rt_pct=5.0,
            max_rt_drift_s=1.0,
            min_replicates=5,
        )
        sst = SystemSuitabilityTest(criteria)

        for i in range(5):
            sst.add_replicate(_default_two_component_result(run_number=i + 1))

        result = sst.evaluate()
        self.assertTrue(result.passed, 'SST should pass. Failures: %s' % result.failures)
        self.assertEqual(len(result.failures), 0)
        # Resolution should be computed for Methane/Ethane pair
        self.assertIn('Methane/Ethane', result.resolution)
        self.assertGreater(result.resolution['Methane/Ethane'], 1.0)
        # Plates computed for both components
        self.assertIn('Methane', result.theoretical_plates)
        self.assertIn('Ethane', result.theoretical_plates)

    def test_evaluate_failing_resolution(self):
        """Peaks too close together should fail resolution criterion."""
        criteria = SSTCriteria(min_resolution=50.0)  # impossibly high
        sst = SystemSuitabilityTest(criteria)
        sst.add_replicate(_default_two_component_result())

        result = sst.evaluate()
        self.assertFalse(result.passed)
        resolution_failures = [f for f in result.failures if 'Resolution' in f]
        self.assertGreater(len(resolution_failures), 0)

    def test_evaluate_failing_tailing(self):
        """Asymmetric peaks should fail tailing criterion if set tight."""
        criteria = SSTCriteria(
            max_tailing=0.9,  # very tight -- (1 + 1.1)/2 = 1.05 > 0.9
            min_replicates=1,
        )
        sst = SystemSuitabilityTest(criteria)
        sst.add_replicate(_default_two_component_result())

        result = sst.evaluate()
        self.assertFalse(result.passed)
        tailing_failures = [f for f in result.failures if 'Tailing' in f]
        self.assertGreater(len(tailing_failures), 0)

    def test_evaluate_failing_plates(self):
        """Low plate count should fail when min_plates is very high."""
        criteria = SSTCriteria(
            min_plates=999999,  # impossibly high
            min_replicates=1,
        )
        sst = SystemSuitabilityTest(criteria)
        sst.add_replicate(_default_two_component_result())

        result = sst.evaluate()
        self.assertFalse(result.passed)
        plate_failures = [f for f in result.failures if 'plates' in f]
        self.assertGreater(len(plate_failures), 0)

    def test_evaluate_no_replicates(self):
        """No data at all returns failure."""
        sst = SystemSuitabilityTest()
        result = sst.evaluate()
        self.assertFalse(result.passed)
        self.assertIn('No replicate data provided', result.failures)

    def test_multiple_replicates_rsd(self):
        """With varying areas the RSD is computed and can cause failure."""
        criteria = SSTCriteria(
            max_rsd_area_pct=0.001,  # extremely tight
            min_replicates=3,
            min_resolution=0.0,
            max_tailing=999.0,
            min_plates=0,
        )
        sst = SystemSuitabilityTest(criteria)

        # Replicate 1: area = 100
        sst.add_replicate(_make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, area_pct=50.0, asymmetry=1.0),
            },
            run_number=1,
        ))
        # Replicate 2: area = 110 (10% higher)
        sst.add_replicate(_make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 110.0, area_pct=55.0, asymmetry=1.0),
            },
            run_number=2,
        ))
        # Replicate 3: area = 90 (10% lower)
        sst.add_replicate(_make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 90.0, area_pct=45.0, asymmetry=1.0),
            },
            run_number=3,
        ))

        result = sst.evaluate()
        self.assertFalse(result.passed)
        area_rsd_failures = [f for f in result.failures if 'Area %RSD' in f]
        self.assertGreater(len(area_rsd_failures), 0)

    def test_clear_resets_data(self):
        """clear() discards all replicate data."""
        sst = SystemSuitabilityTest()
        sst.add_replicate(_default_two_component_result())
        self.assertEqual(len(sst._replicate_data), 1)

        sst.clear()
        self.assertEqual(len(sst._replicate_data), 0)

        # Evaluate after clear gives no-data failure
        result = sst.evaluate()
        self.assertFalse(result.passed)
        self.assertIn('No replicate data provided', result.failures)

    def test_rt_drift_monitoring(self):
        """RT drift is detected when retention times shift from reference."""
        criteria = SSTCriteria(
            max_rt_drift_s=0.1,  # very tight
            min_replicates=1,
            min_resolution=0.0,
            max_tailing=999.0,
            min_plates=0,
        )
        sst = SystemSuitabilityTest(criteria)
        sst.set_reference_rts({'Methane': 30.0, 'Ethane': 60.0})

        # Shift Ethane RT by 1.0 s
        result_shifted = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, asymmetry=1.0),
                'Ethane': _make_component(61.0, 2.5, 80.0, asymmetry=1.0),
            },
            run_number=1,
        )
        sst.add_replicate(result_shifted)
        result = sst.evaluate()
        self.assertFalse(result.passed)
        drift_failures = [f for f in result.failures if 'RT drift' in f]
        self.assertGreater(len(drift_failures), 0)
        self.assertAlmostEqual(result.rt_drift['Ethane'], 1.0, places=3)

# ======================================================================
# TestSSTResult
# ======================================================================

class TestSSTResult(unittest.TestCase):
    """SSTResult dataclass serialization."""

    def test_to_dict_from_dict_roundtrip(self):
        original = SSTResult(
            timestamp='2025-01-15T12:00:00',
            run_number=5,
            resolution={'A/B': 3.5},
            tailing_factors={'A': 1.1, 'B': 1.2},
            theoretical_plates={'A': 10000.0},
            capacity_factors={'A': 2.5},
            rsd_areas={'A': 0.5},
            rsd_retention_times={'A': 0.1},
            rt_drift={'A': 0.05},
            passed=True,
            failures=[],
        )
        d = original.to_dict()
        restored = SSTResult.from_dict(d)
        self.assertEqual(restored.timestamp, original.timestamp)
        self.assertEqual(restored.run_number, original.run_number)
        self.assertEqual(restored.resolution, original.resolution)
        self.assertEqual(restored.tailing_factors, original.tailing_factors)
        self.assertTrue(restored.passed)
        self.assertEqual(restored.failures, [])

# ======================================================================
# TestQCLimits
# ======================================================================

class TestQCLimits(unittest.TestCase):
    """QCLimits dataclass: defaults and serialization."""

    def test_default_values(self):
        lim = QCLimits()
        self.assertAlmostEqual(lim.blank_max_area, 0.1)
        self.assertAlmostEqual(lim.check_std_tolerance_pct, 10.0)
        self.assertAlmostEqual(lim.duplicate_max_rsd_pct, 5.0)
        self.assertAlmostEqual(lim.spike_recovery_min_pct, 80.0)
        self.assertAlmostEqual(lim.spike_recovery_max_pct, 120.0)
        self.assertAlmostEqual(lim.cal_verify_tolerance_pct, 15.0)

    def test_to_dict_from_dict_roundtrip(self):
        original = QCLimits(
            blank_max_area=0.05,
            check_std_tolerance_pct=5.0,
            duplicate_max_rsd_pct=3.0,
            spike_recovery_min_pct=85.0,
            spike_recovery_max_pct=115.0,
            cal_verify_tolerance_pct=10.0,
        )
        d = original.to_dict()
        restored = QCLimits.from_dict(d)
        self.assertAlmostEqual(restored.blank_max_area, 0.05)
        self.assertAlmostEqual(restored.check_std_tolerance_pct, 5.0)
        self.assertAlmostEqual(restored.duplicate_max_rsd_pct, 3.0)
        self.assertAlmostEqual(restored.spike_recovery_min_pct, 85.0)
        self.assertAlmostEqual(restored.spike_recovery_max_pct, 115.0)
        self.assertAlmostEqual(restored.cal_verify_tolerance_pct, 10.0)

# ======================================================================
# TestQCTracker
# ======================================================================

class TestQCTracker(unittest.TestCase):
    """QCTracker: blank, check std, duplicate, spike, cal ver, history."""

    def setUp(self):
        self.tracker = QCTracker(QCLimits())

    # --- Blank ---

    def test_evaluate_blank_clean_passes(self):
        """A blank with negligible area_pct should pass."""
        blank = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 0.01, area_pct=0.005),
            },
            unknown_peaks=[],
            run_number=1,
        )
        sample = self.tracker.evaluate_blank(blank)
        self.assertTrue(sample.passed)
        self.assertEqual(len(sample.failures), 0)
        self.assertEqual(sample.sample_type, QCSampleType.BLANK)

    def test_evaluate_blank_contaminated_fails(self):
        """A blank with significant area_pct should fail."""
        blank = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 50.0, area_pct=5.0),
            },
            unknown_peaks=[{'retention_time': 45.0, 'area_pct': 2.0}],
            run_number=1,
        )
        sample = self.tracker.evaluate_blank(blank)
        self.assertFalse(sample.passed)
        # Both the named component and the unknown peak exceed threshold
        self.assertGreaterEqual(len(sample.failures), 2)

    # --- Check Standard ---

    def test_evaluate_check_standard_within_tolerance(self):
        """Measured value within tolerance passes."""
        result = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=10.2),
            },
            run_number=1,
        )
        expected = {'Methane': 10.0}  # 2% deviation, well within 10%
        sample = self.tracker.evaluate_check_standard(result, expected)
        self.assertTrue(sample.passed)
        self.assertAlmostEqual(sample.recovery_pct['Methane'], 102.0)

    def test_evaluate_check_standard_out_of_tolerance(self):
        """Measured value far from expected fails."""
        result = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=15.0),
            },
            run_number=1,
        )
        expected = {'Methane': 10.0}  # 50% deviation, way over 10%
        sample = self.tracker.evaluate_check_standard(result, expected)
        self.assertFalse(sample.passed)
        self.assertGreater(len(sample.failures), 0)

    def test_evaluate_check_standard_missing_component(self):
        """Component not detected in result causes failure."""
        result = _make_analysis_result(
            components={},  # nothing detected
            run_number=1,
        )
        expected = {'Methane': 10.0}
        sample = self.tracker.evaluate_check_standard(result, expected)
        self.assertFalse(sample.passed)
        self.assertTrue(any('not detected' in f for f in sample.failures))

    # --- Duplicate ---

    def test_evaluate_duplicate_good_agreement(self):
        """Near-identical duplicates pass RSD check."""
        r1 = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=10.0),
            },
            run_number=1,
        )
        r2 = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 102.0, concentration=10.1),
            },
            run_number=2,
        )
        sample = self.tracker.evaluate_duplicate(r1, r2)
        self.assertTrue(sample.passed)
        # RSD of [10.0, 10.1] should be very small
        self.assertLess(sample.rsd_pct['Methane'], 5.0)

    def test_evaluate_duplicate_poor_agreement(self):
        """Widely different duplicates fail RSD check."""
        r1 = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=10.0),
            },
            run_number=1,
        )
        r2 = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 200.0, concentration=20.0),
            },
            run_number=2,
        )
        sample = self.tracker.evaluate_duplicate(r1, r2)
        self.assertFalse(sample.passed)
        self.assertGreater(sample.rsd_pct['Methane'], 5.0)

    def test_evaluate_duplicate_missing_component(self):
        """Component present in only one duplicate causes failure."""
        r1 = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=10.0),
            },
            run_number=1,
        )
        r2 = _make_analysis_result(
            components={},  # Methane not detected
            run_number=2,
        )
        sample = self.tracker.evaluate_duplicate(r1, r2)
        self.assertFalse(sample.passed)
        self.assertTrue(any('missing' in f for f in sample.failures))

    # --- Spike ---

    def test_evaluate_spike_good_recovery(self):
        """Recovery between 80-120% passes."""
        unspiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 50.0, concentration=5.0),
            },
            run_number=1,
        )
        spiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 150.0, concentration=15.0),
            },
            run_number=2,
        )
        spike_amounts = {'Methane': 10.0}
        # Recovery = (15 - 5) / 10 * 100 = 100%
        sample = self.tracker.evaluate_spike(unspiked, spiked, spike_amounts)
        self.assertTrue(sample.passed)
        self.assertAlmostEqual(sample.recovery_pct['Methane'], 100.0)

    def test_evaluate_spike_poor_recovery_low(self):
        """Recovery below 80% fails."""
        unspiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 50.0, concentration=5.0),
            },
            run_number=1,
        )
        spiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=11.0),
            },
            run_number=2,
        )
        spike_amounts = {'Methane': 10.0}
        # Recovery = (11 - 5) / 10 * 100 = 60%
        sample = self.tracker.evaluate_spike(unspiked, spiked, spike_amounts)
        self.assertFalse(sample.passed)
        self.assertAlmostEqual(sample.recovery_pct['Methane'], 60.0)

    def test_evaluate_spike_poor_recovery_high(self):
        """Recovery above 120% fails."""
        unspiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 50.0, concentration=5.0),
            },
            run_number=1,
        )
        spiked = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 300.0, concentration=19.0),
            },
            run_number=2,
        )
        spike_amounts = {'Methane': 10.0}
        # Recovery = (19 - 5) / 10 * 100 = 140%
        sample = self.tracker.evaluate_spike(unspiked, spiked, spike_amounts)
        self.assertFalse(sample.passed)
        self.assertAlmostEqual(sample.recovery_pct['Methane'], 140.0)

    # --- Calibration Verification ---

    def test_evaluate_cal_verification_passes(self):
        """Measured within 15% tolerance passes."""
        result = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=9.0),
            },
            run_number=1,
        )
        expected = {'Methane': 10.0}  # 10% deviation, within 15%
        sample = self.tracker.evaluate_cal_verification(result, expected)
        self.assertTrue(sample.passed)
        self.assertAlmostEqual(sample.recovery_pct['Methane'], 90.0)

    def test_evaluate_cal_verification_fails(self):
        """Measured way outside 15% tolerance fails."""
        result = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=5.0),
            },
            run_number=1,
        )
        expected = {'Methane': 10.0}  # 50% deviation
        sample = self.tracker.evaluate_cal_verification(result, expected)
        self.assertFalse(sample.passed)

    # --- History & Control Charts ---

    def test_get_history_filtering(self):
        """get_history filters by sample type and returns most-recent-first."""
        # Add one blank and one check standard
        blank = _make_analysis_result(
            components={'X': _make_component(10.0, 1.0, 0.01, area_pct=0.001)},
            run_number=1,
        )
        self.tracker.evaluate_blank(blank)

        chk = _make_analysis_result(
            components={'X': _make_component(10.0, 1.0, 100.0, concentration=10.0)},
            run_number=2,
        )
        self.tracker.evaluate_check_standard(chk, {'X': 10.0})

        all_history = self.tracker.get_history()
        self.assertEqual(len(all_history), 2)

        blank_history = self.tracker.get_history(sample_type=QCSampleType.BLANK)
        self.assertEqual(len(blank_history), 1)
        self.assertEqual(blank_history[0]['sample_type'], 'blank')

        chk_history = self.tracker.get_history(sample_type=QCSampleType.CHECK_STANDARD)
        self.assertEqual(len(chk_history), 1)
        self.assertEqual(chk_history[0]['sample_type'], 'check_standard')

    def test_get_history_most_recent_first(self):
        """History entries are returned most-recent-first."""
        for i in range(3):
            blank = _make_analysis_result(
                components={
                    'X': _make_component(10.0, 1.0, 0.01, area_pct=0.001),
                },
                run_number=i + 1,
                timestamp='2025-01-15T10:%02d:00' % i,
            )
            self.tracker.evaluate_blank(blank)

        history = self.tracker.get_history()
        self.assertEqual(len(history), 3)
        # Most recent (run_number=3) should be first
        self.assertEqual(history[0]['run_number'], 3)
        self.assertEqual(history[2]['run_number'], 1)

    def test_get_control_chart_data(self):
        """Control chart computes mean, UCL, LCL from check standard history."""
        # Add 5 check standards with varying concentrations
        concentrations = [10.0, 10.2, 9.8, 10.1, 9.9]
        for i, conc in enumerate(concentrations):
            result = _make_analysis_result(
                components={
                    'Methane': _make_component(30.0, 2.0, 100.0, concentration=conc),
                },
                run_number=i + 1,
            )
            self.tracker.evaluate_check_standard(result, {'Methane': 10.0})

        chart = self.tracker.get_control_chart_data(
            'Methane', QCSampleType.CHECK_STANDARD, field_name='measured'
        )
        self.assertEqual(chart['n'], 5)
        self.assertEqual(len(chart['values']), 5)
        self.assertAlmostEqual(chart['mean'], sum(concentrations) / 5.0, places=4)
        self.assertGreater(chart['ucl'], chart['mean'])
        self.assertLess(chart['lcl'], chart['mean'])
        # UCL = mean + 3*sigma, LCL = mean - 3*sigma
        self.assertAlmostEqual(
            chart['ucl'] - chart['mean'],
            chart['mean'] - chart['lcl'],
            places=4,
        )

    def test_get_control_chart_single_value(self):
        """Control chart with single data point returns degenerate limits."""
        result = _make_analysis_result(
            components={
                'Methane': _make_component(30.0, 2.0, 100.0, concentration=10.0),
            },
            run_number=1,
        )
        self.tracker.evaluate_check_standard(result, {'Methane': 10.0})

        chart = self.tracker.get_control_chart_data(
            'Methane', QCSampleType.CHECK_STANDARD
        )
        self.assertEqual(chart['n'], 1)
        self.assertAlmostEqual(chart['sigma'], 0.0)
        self.assertAlmostEqual(chart['ucl'], chart['mean'])
        self.assertAlmostEqual(chart['lcl'], chart['mean'])

    def test_get_summary(self):
        """Summary counts pass/fail by type and overall."""
        # 2 blanks (both pass)
        for _ in range(2):
            blank = _make_analysis_result(
                components={'X': _make_component(10.0, 1.0, 0.01, area_pct=0.001)},
                run_number=1,
            )
            self.tracker.evaluate_blank(blank)

        # 1 check standard (fail)
        chk = _make_analysis_result(
            components={'X': _make_component(10.0, 1.0, 100.0, concentration=50.0)},
            run_number=2,
        )
        self.tracker.evaluate_check_standard(chk, {'X': 10.0})

        summary = self.tracker.get_summary()

        self.assertEqual(summary['blank']['total'], 2)
        self.assertEqual(summary['blank']['passed'], 2)
        self.assertEqual(summary['blank']['failed'], 0)
        self.assertAlmostEqual(summary['blank']['pass_rate_pct'], 100.0)

        self.assertEqual(summary['check_standard']['total'], 1)
        self.assertEqual(summary['check_standard']['passed'], 0)
        self.assertEqual(summary['check_standard']['failed'], 1)

        self.assertEqual(summary['overall']['total'], 3)
        self.assertEqual(summary['overall']['passed'], 2)
        self.assertEqual(summary['overall']['failed'], 1)

# ======================================================================
# TestMethodValidation
# ======================================================================

class TestMethodValidation(unittest.TestCase):
    """MethodValidation: LOD, LOQ, linearity, from_dict, status."""

    def test_calc_lod(self):
        """LOD = 3.3 * sigma / S."""
        # blank_std = 0.5, slope = 100
        lod = MethodValidation.calc_lod(0.5, 100.0)
        self.assertAlmostEqual(lod, 3.3 * 0.5 / 100.0, places=6)

    def test_calc_lod_zero_slope(self):
        """Zero slope returns 0 (avoids division by zero)."""
        lod = MethodValidation.calc_lod(0.5, 0.0)
        self.assertAlmostEqual(lod, 0.0)

    def test_calc_loq(self):
        """LOQ = 10 * sigma / S."""
        loq = MethodValidation.calc_loq(0.5, 100.0)
        self.assertAlmostEqual(loq, 10.0 * 0.5 / 100.0, places=6)

    def test_calc_loq_zero_slope(self):
        """Zero slope returns 0."""
        loq = MethodValidation.calc_loq(0.5, 0.0)
        self.assertAlmostEqual(loq, 0.0)

    def test_loq_always_greater_than_lod(self):
        """LOQ > LOD for any positive slope and sigma."""
        sigma = 0.3
        slope = 50.0
        lod = MethodValidation.calc_lod(sigma, slope)
        loq = MethodValidation.calc_loq(sigma, slope)
        self.assertGreater(loq, lod)

    def test_from_dict_roundtrip(self):
        """Serialize and deserialize preserves all fields."""
        original = MethodValidation(
            method_name='ASTM D1945',
            validated_date='2025-01-15',
            validated_by='QC Lab',
            linearity={
                'Methane': {'slope': 100.5, 'intercept': 0.2, 'r_squared': 0.9998},
            },
            lod={'Methane': 0.0165},
            loq={'Methane': 0.05},
            precision_repeatability={'Methane': 0.45},
            precision_reproducibility={'Methane': 1.2},
            accuracy={'Methane': {'recovery_pct': 99.5, 'bias_pct': -0.5}},
            specificity_notes='No interferences observed',
            robustness_notes='Column temp +/- 5 deg C OK',
            range_min={'Methane': 0.05},
            range_max={'Methane': 100.0},
            status='validated',
        )
        d = original.to_dict()
        restored = MethodValidation.from_dict(d)

        self.assertEqual(restored.method_name, 'ASTM D1945')
        self.assertEqual(restored.validated_date, '2025-01-15')
        self.assertEqual(restored.validated_by, 'QC Lab')
        self.assertEqual(restored.linearity['Methane']['slope'], 100.5)
        self.assertAlmostEqual(restored.lod['Methane'], 0.0165)
        self.assertAlmostEqual(restored.loq['Methane'], 0.05)
        self.assertEqual(restored.status, 'validated')
        self.assertEqual(restored.specificity_notes, 'No interferences observed')
        self.assertEqual(restored.robustness_notes, 'Column temp +/- 5 deg C OK')

    def test_status_defaults_to_provisional(self):
        """New MethodValidation has status='provisional'."""
        mv = MethodValidation()
        self.assertEqual(mv.status, 'provisional')

    def test_calc_linearity(self):
        """Linear regression on perfectly linear data gives R^2 = 1.0."""
        # y = 2x + 1
        concentrations = [1.0, 2.0, 3.0, 4.0, 5.0]
        responses = [3.0, 5.0, 7.0, 9.0, 11.0]
        lin = MethodValidation.calc_linearity(concentrations, responses)
        self.assertAlmostEqual(lin['slope'], 2.0, places=4)
        self.assertAlmostEqual(lin['intercept'], 1.0, places=4)
        self.assertAlmostEqual(lin['r_squared'], 1.0, places=4)
        self.assertEqual(lin['points'], 5)
        self.assertAlmostEqual(lin['range_min'], 1.0, places=4)
        self.assertAlmostEqual(lin['range_max'], 5.0, places=4)

    def test_calc_linearity_insufficient_points(self):
        """Single point returns zero slope and R^2."""
        lin = MethodValidation.calc_linearity([1.0], [5.0])
        self.assertAlmostEqual(lin['slope'], 0.0)
        self.assertAlmostEqual(lin['r_squared'], 0.0)
        self.assertEqual(lin['points'], 1)

    def test_calc_precision(self):
        """%RSD matches manual calculation."""
        values = [10.0, 10.2, 9.8, 10.1, 9.9]
        rsd = MethodValidation.calc_precision(values)
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = math.sqrt(variance)
        expected_rsd = (stdev / abs(mean)) * 100.0
        self.assertAlmostEqual(rsd, round(expected_rsd, 4), places=4)

    def test_calc_accuracy(self):
        """Recovery and bias computed correctly."""
        measured = [10.0, 10.2, 9.8]
        true_val = 10.0
        acc = MethodValidation.calc_accuracy(measured, true_val)
        mean_m = sum(measured) / len(measured)
        expected_rec = mean_m / true_val * 100.0
        expected_bias = (mean_m - true_val) / true_val * 100.0
        self.assertAlmostEqual(acc['recovery_pct'], round(expected_rec, 2))
        self.assertAlmostEqual(acc['bias_pct'], round(expected_bias, 2))

    def test_calc_accuracy_zero_true_value(self):
        """Zero true value returns 0 for recovery and bias."""
        acc = MethodValidation.calc_accuracy([1.0, 2.0], 0.0)
        self.assertAlmostEqual(acc['recovery_pct'], 0.0)
        self.assertAlmostEqual(acc['bias_pct'], 0.0)

if __name__ == '__main__':
    unittest.main()
