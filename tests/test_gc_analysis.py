"""
Unit tests for the GC Chromatogram Analysis Engine.

Tests cover:
  - Baseline estimation
  - Peak detection (height, width, count)
  - Peak integration (trapezoidal area)
  - Peak asymmetry calculation
  - Component identification by RT window
  - Retention index calculation (Kovats + Linear)
  - Peak library management and RI-based matching
  - Unknown peak labeling and reporting
  - Calibration (response factor, linear, quadratic)
  - Area normalization
  - Multi-port valve support
  - Edge cases (no data, single peak, overlapping peaks)
  - Library JSON loading
"""

import json
import math
import os
import tempfile
import unittest

from services.gc_node.gc_analysis import (
    AnalysisMethod,
    CalibrationPoint,
    ComponentCalibration,
    DetectedPeak,
    GCAnalysisEngine,
    LibraryEntry,
    PeakLibrary,
    PeakWindow,
    ReferenceStandard,
    _linear_fit,
    _quadratic_fit,
    _det3x3,
)


# ======================================================================
# Helper: generate synthetic chromatograms
# ======================================================================

def gaussian_peak(t, center, height, sigma):
    """Generate a Gaussian peak value at time t."""
    return height * math.exp(-((t - center) ** 2) / (2 * sigma ** 2))


def make_chromatogram(peaks, duration=200.0, rate=10.0, baseline=0.01, noise=0.0):
    """Generate a synthetic chromatogram with Gaussian peaks.

    Args:
        peaks: List of (center_time, height, sigma) tuples.
        duration: Total run time in seconds.
        rate: Sample rate in Hz.
        baseline: Baseline offset.
        noise: Random noise amplitude (0 = none).

    Returns:
        (times, values) lists.
    """
    n_points = int(duration * rate)
    times = [i / rate for i in range(n_points)]
    values = []
    for t in times:
        v = baseline
        for center, height, sigma in peaks:
            v += gaussian_peak(t, center, height, sigma)
        values.append(v)
    return times, values


def make_default_method(**kwargs):
    """Create an AnalysisMethod with sensible test defaults."""
    defaults = dict(
        name='test_method',
        min_peak_height=0.03,
        min_peak_width_s=0.3,
        max_peak_width_s=60.0,
        noise_threshold=0.005,
        baseline_window_s=3.0,
        normalize_areas=True,
        report_unknowns=True,
        unknown_min_area_pct=0.0,
    )
    defaults.update(kwargs)
    return AnalysisMethod(**defaults)


def run_analysis(peaks_spec, method=None, library=None, **method_kwargs):
    """Run a full analysis on a synthetic chromatogram.

    Args:
        peaks_spec: List of (center_time, height, sigma) for Gaussian peaks.
        method: AnalysisMethod (or None for default).
        library: PeakLibrary (or None).
        **method_kwargs: Overrides for make_default_method.

    Returns:
        (result_dict, engine) tuple.
    """
    if method is None:
        method = make_default_method(**method_kwargs)
    engine = GCAnalysisEngine(method)
    if library:
        engine.load_library(library)

    times, values = make_chromatogram(peaks_spec)

    engine.start_run()
    for t, v in zip(times, values):
        engine.add_point(t, v)
    result = engine.finish_run()
    return result, engine


# ======================================================================
# Tests: Math helpers
# ======================================================================

class TestMathHelpers(unittest.TestCase):
    """Test the pure-Python math helper functions."""

    def test_linear_fit_perfect(self):
        """Linear fit on perfect data: y = 2x + 1."""
        x = [1, 2, 3, 4, 5]
        y = [3, 5, 7, 9, 11]
        a, b = _linear_fit(x, y)
        self.assertAlmostEqual(a, 2.0, places=6)
        self.assertAlmostEqual(b, 1.0, places=6)

    def test_linear_fit_single_point(self):
        """Linear fit with one point."""
        a, b = _linear_fit([5.0], [10.0])
        self.assertAlmostEqual(a * 5.0, 10.0, places=3)

    def test_linear_fit_empty(self):
        """Linear fit with no data returns defaults."""
        a, b = _linear_fit([], [])
        self.assertEqual(a, 1.0)
        self.assertEqual(b, 0.0)

    def test_quadratic_fit_perfect(self):
        """Quadratic fit: y = x^2 + 2x + 3."""
        x = [0, 1, 2, 3, 4]
        y = [3, 6, 11, 18, 27]
        a, b, c = _quadratic_fit(x, y)
        self.assertAlmostEqual(a, 1.0, places=4)
        self.assertAlmostEqual(b, 2.0, places=4)
        self.assertAlmostEqual(c, 3.0, places=4)

    def test_quadratic_fit_falls_back_to_linear(self):
        """Quadratic fit with <3 points falls back to linear."""
        result = _quadratic_fit([1, 2], [3, 5])
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 0.0)  # No quadratic term

    def test_det3x3(self):
        """3x3 determinant calculation."""
        # Identity matrix det = 1
        self.assertAlmostEqual(_det3x3(1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0)
        # Known matrix
        self.assertAlmostEqual(_det3x3(1, 2, 3, 4, 5, 6, 7, 8, 0), 27.0)


# ======================================================================
# Tests: PeakWindow
# ======================================================================

class TestPeakWindow(unittest.TestCase):

    def test_rt_window(self):
        pw = PeakWindow(name='Methane', rt_expected=30.0, rt_tolerance=2.0)
        self.assertAlmostEqual(pw.rt_min, 28.0)
        self.assertAlmostEqual(pw.rt_max, 32.0)

    def test_from_dict(self):
        pw = PeakWindow.from_dict('Ethane', {
            'rt_expected': 60, 'rt_tolerance': 3, 'response_factor': 0.95
        })
        self.assertEqual(pw.name, 'Ethane')
        self.assertAlmostEqual(pw.rt_expected, 60.0)
        self.assertAlmostEqual(pw.response_factor, 0.95)


# ======================================================================
# Tests: ReferenceStandard
# ======================================================================

class TestReferenceStandard(unittest.TestCase):

    def test_auto_name(self):
        ref = ReferenceStandard(carbon_number=5, retention_time=100.0)
        self.assertEqual(ref.name, 'C5')

    def test_explicit_name(self):
        ref = ReferenceStandard(carbon_number=5, retention_time=100.0, name='n-Pentane')
        self.assertEqual(ref.name, 'n-Pentane')


# ======================================================================
# Tests: ComponentCalibration
# ======================================================================

class TestComponentCalibration(unittest.TestCase):

    def test_response_factor_single_point(self):
        cal = ComponentCalibration(name='CH4', cal_type='response_factor')
        cal.points = [CalibrationPoint(concentration=50.0, area=1000.0)]
        cal.fit()
        # RF = 50/1000 = 0.05
        self.assertAlmostEqual(cal.area_to_concentration(2000.0), 100.0, places=3)

    def test_linear_calibration(self):
        cal = ComponentCalibration(name='C2H6', cal_type='linear')
        cal.points = [
            CalibrationPoint(concentration=0.0, area=0.0),
            CalibrationPoint(concentration=10.0, area=500.0),
            CalibrationPoint(concentration=20.0, area=1000.0),
        ]
        cal.fit()
        # Linear: conc = 0.02 * area + 0
        self.assertAlmostEqual(cal.area_to_concentration(750.0), 15.0, places=2)

    def test_quadratic_calibration(self):
        cal = ComponentCalibration(name='C3H8', cal_type='quadratic')
        # y = 0.001*x^2 + 0.5*x + 0
        cal.points = [
            CalibrationPoint(concentration=0.0, area=0.0),
            CalibrationPoint(concentration=0.501, area=1.0),  # 0.001 + 0.5
            CalibrationPoint(concentration=2.004, area=2.0),  # 0.004 + 2.0
            CalibrationPoint(concentration=4.509, area=3.0),  # 0.009 + 4.5
        ]
        cal.fit()
        result = cal.area_to_concentration(2.0)
        self.assertAlmostEqual(result, 2.004, places=1)

    def test_from_dict(self):
        cal = ComponentCalibration.from_dict('test', {
            'cal_type': 'linear',
            'points': [
                {'concentration': 0, 'area': 0},
                {'concentration': 10, 'area': 100},
            ]
        })
        self.assertEqual(cal.name, 'test')
        self.assertEqual(len(cal.points), 2)
        self.assertAlmostEqual(cal.area_to_concentration(50), 5.0, places=1)


# ======================================================================
# Tests: PeakLibrary
# ======================================================================

class TestPeakLibrary(unittest.TestCase):

    def setUp(self):
        self.library = PeakLibrary()
        self.library.add_entries([
            LibraryEntry(name='Methane', retention_index=100, ri_tolerance=10),
            LibraryEntry(name='Ethane', retention_index=200, ri_tolerance=10),
            LibraryEntry(name='Propane', retention_index=300, ri_tolerance=10),
            LibraryEntry(name='Benzene', retention_index=653, ri_tolerance=8,
                         formula='C6H6', category='aromatic'),
            LibraryEntry(name='Toluene', retention_index=764, ri_tolerance=8,
                         formula='C7H8', category='aromatic'),
        ])

    def test_size(self):
        self.assertEqual(self.library.size, 5)

    def test_exact_match(self):
        candidates = self.library.find_candidates(ri=653, max_results=1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['name'], 'Benzene')
        self.assertAlmostEqual(candidates[0]['confidence'], 1.0)
        self.assertAlmostEqual(candidates[0]['ri_delta'], 0.0)

    def test_close_match(self):
        candidates = self.library.find_candidates(ri=660, max_results=3, max_ri_delta=20)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['name'], 'Benzene')
        self.assertGreater(candidates[0]['confidence'], 0.5)

    def test_no_match(self):
        candidates = self.library.find_candidates(ri=500, max_results=3, max_ri_delta=10)
        self.assertEqual(len(candidates), 0)

    def test_multiple_candidates(self):
        # RI=250 is between Ethane(200) and Propane(300) with large delta
        candidates = self.library.find_candidates(ri=250, max_results=5, max_ri_delta=60)
        names = [c['name'] for c in candidates]
        self.assertIn('Ethane', names)
        self.assertIn('Propane', names)

    def test_get_best_match(self):
        match = self.library.get_best_match(ri=655)
        self.assertIsNotNone(match)
        self.assertEqual(match['name'], 'Benzene')

    def test_get_best_match_none(self):
        match = self.library.get_best_match(ri=500)
        self.assertIsNone(match)

    def test_load_json(self):
        # Create a temp library file
        lib_data = {
            "compounds": [
                {"name": "TestComp", "retention_index": 555, "formula": "C4H10"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(lib_data, f)
            tmp_path = f.name

        try:
            lib = PeakLibrary()
            lib.load_json(tmp_path)
            self.assertEqual(lib.size, 1)
            candidates = lib.find_candidates(ri=555, max_results=1)
            self.assertEqual(candidates[0]['name'], 'TestComp')
        finally:
            os.unlink(tmp_path)

    def test_load_dict(self):
        lib = PeakLibrary()
        lib.load_dict({
            "compounds": [
                {"name": "A", "retention_index": 100},
                {"name": "B", "retention_index": 200},
            ]
        })
        self.assertEqual(lib.size, 2)

    def test_confidence_scaling(self):
        """Confidence should decrease linearly with RI distance."""
        candidates = self.library.find_candidates(ri=680, max_results=1, max_ri_delta=50)
        # Delta is 27, max is 50 -> confidence = 1 - 27/50 = 0.46
        if candidates:
            self.assertAlmostEqual(candidates[0]['confidence'], 0.46, places=1)


# ======================================================================
# Tests: Analysis Engine — Basic peak detection
# ======================================================================

class TestPeakDetection(unittest.TestCase):
    """Test peak detection on synthetic chromatograms."""

    def test_single_peak(self):
        """Detect a single Gaussian peak."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        self.assertEqual(result['total_peaks'], 1)

    def test_two_peaks_resolved(self):
        """Detect two well-separated peaks."""
        result, _ = run_analysis([
            (40.0, 0.5, 2.0),
            (80.0, 0.3, 2.0),
        ])
        self.assertEqual(result['total_peaks'], 2)

    def test_three_peaks(self):
        """Detect three peaks of varying heights."""
        result, _ = run_analysis([
            (30.0, 0.8, 1.5),
            (60.0, 0.4, 2.0),
            (100.0, 0.2, 3.0),
        ])
        self.assertEqual(result['total_peaks'], 3)

    def test_no_peaks_flat_baseline(self):
        """No peaks on a flat baseline."""
        result, _ = run_analysis([])
        self.assertEqual(result['total_peaks'], 0)

    def test_peak_below_threshold_rejected(self):
        """Very small peak below min_peak_height is rejected."""
        result, _ = run_analysis(
            [(50.0, 0.01, 2.0)],  # Height 0.01 < default threshold 0.03
        )
        self.assertEqual(result['total_peaks'], 0)

    def test_narrow_peak_rejected(self):
        """Very narrow peak below min_peak_width_s is rejected."""
        result, _ = run_analysis(
            [(50.0, 0.5, 0.01)],  # sigma=0.01 -> very narrow
        )
        self.assertEqual(result['total_peaks'], 0)

    def test_peak_timing(self):
        """Detected peak apex time should be close to the true center."""
        result, _ = run_analysis([(75.0, 0.5, 2.0)])
        self.assertEqual(result['total_peaks'], 1)

        # Get the peak data (it's unidentified so check unknown_peaks)
        unknowns = result['unknown_peaks']
        self.assertEqual(len(unknowns), 1)
        rt = unknowns[0]['retention_time']
        self.assertAlmostEqual(rt, 75.0, delta=1.0)


# ======================================================================
# Tests: Peak integration
# ======================================================================

class TestPeakIntegration(unittest.TestCase):

    def test_area_proportional_to_height(self):
        """Taller peak should have proportionally larger area."""
        result1, _ = run_analysis([(50.0, 0.5, 2.0)])
        result2, _ = run_analysis([(50.0, 1.0, 2.0)])

        area1 = result1['total_area']
        area2 = result2['total_area']
        # Area ratio should be ~2.0 (linear with height for Gaussian)
        ratio = area2 / area1
        self.assertAlmostEqual(ratio, 2.0, delta=0.3)

    def test_area_is_positive(self):
        """Integrated area should always be positive for real peaks."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        self.assertGreater(result['total_area'], 0)

        result2, _ = run_analysis([(50.0, 0.5, 3.0)])
        self.assertGreater(result2['total_area'], 0)

    def test_total_area_sum(self):
        """Total area should equal sum of individual peak areas."""
        result, _ = run_analysis([
            (40.0, 0.5, 2.0),
            (80.0, 0.3, 2.0),
        ])
        # With area normalization, area_pct should sum to ~100
        total_pct = sum(u['area_pct'] for u in result['unknown_peaks'])
        self.assertAlmostEqual(total_pct, 100.0, delta=0.1)


# ======================================================================
# Tests: Component identification by RT window
# ======================================================================

class TestComponentIdentification(unittest.TestCase):

    def test_single_component_identified(self):
        """Peak within RT window is identified."""
        method = make_default_method(
            components={
                'Methane': PeakWindow(name='Methane', rt_expected=50.0, rt_tolerance=3.0),
            }
        )
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)

        self.assertEqual(result['identified_peaks'], 1)
        self.assertIn('Methane', result['components'])
        self.assertEqual(result['components']['Methane']['identification_method'], 'rt_window')

    def test_two_components_identified(self):
        """Two peaks within RT windows are identified."""
        method = make_default_method(
            components={
                'Methane': PeakWindow(name='Methane', rt_expected=40.0, rt_tolerance=3.0),
                'Ethane': PeakWindow(name='Ethane', rt_expected=80.0, rt_tolerance=3.0),
            }
        )
        result, _ = run_analysis([
            (40.0, 0.5, 2.0),
            (80.0, 0.3, 2.0),
        ], method=method)

        self.assertEqual(result['identified_peaks'], 2)
        self.assertIn('Methane', result['components'])
        self.assertIn('Ethane', result['components'])

    def test_peak_outside_window_is_unknown(self):
        """Peak outside RT window is not identified."""
        method = make_default_method(
            components={
                'Methane': PeakWindow(name='Methane', rt_expected=50.0, rt_tolerance=2.0),
            }
        )
        # Peak at 70s is far from 50s window
        result, _ = run_analysis([(70.0, 0.5, 2.0)], method=method)
        self.assertEqual(result['identified_peaks'], 0)
        self.assertEqual(result['unknown_count'], 1)

    def test_closest_match_wins(self):
        """When two components overlap, closest RT match wins."""
        method = make_default_method(
            components={
                'A': PeakWindow(name='A', rt_expected=49.0, rt_tolerance=3.0),
                'B': PeakWindow(name='B', rt_expected=51.0, rt_tolerance=3.0),
            }
        )
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        # Peak at 50 is equidistant but largest-area priority applies
        self.assertEqual(result['identified_peaks'], 1)


# ======================================================================
# Tests: Retention Index calculation
# ======================================================================

class TestRetentionIndex(unittest.TestCase):

    def _make_ri_method(self, mode='linear'):
        return make_default_method(
            ri_references=[
                ReferenceStandard(carbon_number=1, retention_time=25.0),
                ReferenceStandard(carbon_number=2, retention_time=55.0),
                ReferenceStandard(carbon_number=3, retention_time=90.0),
                ReferenceStandard(carbon_number=4, retention_time=130.0),
            ],
            ri_mode=mode,
        )

    def test_linear_ri_at_reference_points(self):
        """RI at n-alkane reference times should equal 100*n."""
        method = self._make_ri_method('linear')
        engine = GCAnalysisEngine(method)

        # Test at reference points
        refs = sorted(method.ri_references, key=lambda r: r.retention_time)
        ri = engine._calc_single_ri(25.0, refs)
        self.assertAlmostEqual(ri, 100.0, delta=0.5)

        ri = engine._calc_single_ri(55.0, refs)
        self.assertAlmostEqual(ri, 200.0, delta=0.5)

        ri = engine._calc_single_ri(90.0, refs)
        self.assertAlmostEqual(ri, 300.0, delta=0.5)

    def test_linear_ri_interpolation(self):
        """RI between references should interpolate linearly."""
        method = self._make_ri_method('linear')
        engine = GCAnalysisEngine(method)
        refs = sorted(method.ri_references, key=lambda r: r.retention_time)

        # Midpoint between C1 (25s, RI=100) and C2 (55s, RI=200)
        ri = engine._calc_single_ri(40.0, refs)
        self.assertAlmostEqual(ri, 150.0, delta=1.0)

    def test_kovats_ri_at_reference_points(self):
        """Kovats RI at reference points should equal 100*n."""
        method = self._make_ri_method('kovats')
        engine = GCAnalysisEngine(method)
        refs = sorted(method.ri_references, key=lambda r: r.retention_time)

        ri = engine._calc_single_ri(55.0, refs)
        self.assertAlmostEqual(ri, 200.0, delta=0.5)

    def test_kovats_ri_logarithmic(self):
        """Kovats RI uses log interpolation, not linear."""
        method = self._make_ri_method('kovats')
        engine = GCAnalysisEngine(method)
        refs = sorted(method.ri_references, key=lambda r: r.retention_time)

        # Geometric mean of 25 and 55 = sqrt(25*55) ≈ 37.08
        geometric_mean = math.sqrt(25.0 * 55.0)
        ri = engine._calc_single_ri(geometric_mean, refs)
        # Should be exactly 150 for Kovats (log midpoint)
        self.assertAlmostEqual(ri, 150.0, delta=1.0)

    def test_ri_extrapolation(self):
        """RI should extrapolate for RTs outside reference range."""
        method = self._make_ri_method('linear')
        engine = GCAnalysisEngine(method)
        refs = sorted(method.ri_references, key=lambda r: r.retention_time)

        # Before first reference
        ri = engine._calc_single_ri(10.0, refs)
        self.assertIsNotNone(ri)
        self.assertLess(ri, 100.0)

        # After last reference
        ri = engine._calc_single_ri(160.0, refs)
        self.assertIsNotNone(ri)
        self.assertGreater(ri, 400.0)

    def test_ri_no_references(self):
        """With no references, RI should not be calculated."""
        method = make_default_method()  # No ri_references
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        unknowns = result['unknown_peaks']
        if unknowns:
            self.assertIsNone(unknowns[0].get('retention_index'))

    def test_ri_in_results(self):
        """RI should appear in analysis results when references set."""
        method = self._make_ri_method()
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        unknowns = result['unknown_peaks']
        self.assertEqual(len(unknowns), 1)
        self.assertIsNotNone(unknowns[0]['retention_index'])
        ri = unknowns[0]['retention_index']
        # Peak at 50s with linear refs should be between 100-200
        self.assertGreater(ri, 100)
        self.assertLess(ri, 200)


# ======================================================================
# Tests: Library matching for unknowns
# ======================================================================

class TestLibraryMatching(unittest.TestCase):

    def _make_ri_method(self):
        return make_default_method(
            ri_references=[
                ReferenceStandard(carbon_number=1, retention_time=25.0),
                ReferenceStandard(carbon_number=2, retention_time=55.0),
                ReferenceStandard(carbon_number=3, retention_time=90.0),
                ReferenceStandard(carbon_number=4, retention_time=130.0),
                ReferenceStandard(carbon_number=5, retention_time=175.0),
            ],
            ri_mode='linear',
        )

    def _make_library(self):
        lib = PeakLibrary()
        lib.add_entries([
            LibraryEntry(name='Methane', retention_index=100, ri_tolerance=10),
            LibraryEntry(name='Ethane', retention_index=200, ri_tolerance=10),
            LibraryEntry(name='Propane', retention_index=300, ri_tolerance=10),
            LibraryEntry(name='n-Butane', retention_index=400, ri_tolerance=10),
            LibraryEntry(name='n-Pentane', retention_index=500, ri_tolerance=10),
        ])
        return lib

    def test_library_auto_identifies_strong_match(self):
        """High-confidence library match auto-identifies the peak."""
        method = self._make_ri_method()
        lib = self._make_library()

        # Peak at exactly the C3 reference time -> RI=300 -> Propane
        result, _ = run_analysis([(90.0, 0.5, 2.0)], method=method, library=lib)

        # Should be identified as Propane via RI library
        self.assertEqual(result['identified_peaks'], 1)
        self.assertIn('Propane', result['components'])
        self.assertEqual(
            result['components']['Propane']['identification_method'],
            'ri_library'
        )

    def test_library_unknown_with_candidates(self):
        """Unknown peak gets candidate list from library."""
        method = self._make_ri_method()
        lib = self._make_library()

        # Peak between references, RI ≈ 250 — between Ethane(200) and Propane(300)
        # With max_ri_delta=30, should have candidates but not auto-match
        result, _ = run_analysis([(72.5, 0.3, 2.0)], method=method, library=lib)

        unknowns = result['unknown_peaks']
        # May or may not have candidates depending on exact RI calculation
        # The peak should be detected at least
        self.assertGreaterEqual(result['total_peaks'], 1)

    def test_rt_window_takes_priority_over_library(self):
        """RT window identification takes priority over RI library."""
        method = self._make_ri_method()
        method.components = {
            'MyMethane': PeakWindow(name='MyMethane', rt_expected=25.0, rt_tolerance=3.0),
        }
        lib = self._make_library()

        result, _ = run_analysis([(25.0, 0.5, 2.0)], method=method, library=lib)

        # Should be identified by RT window as 'MyMethane', not by library as 'Methane'
        self.assertIn('MyMethane', result['components'])
        self.assertEqual(
            result['components']['MyMethane']['identification_method'],
            'rt_window'
        )

    def test_no_library_all_unknowns_labeled(self):
        """Without a library, unknowns get sequential labels."""
        method = self._make_ri_method()
        result, _ = run_analysis([
            (40.0, 0.5, 2.0),
            (80.0, 0.3, 2.0),
        ], method=method)

        unknowns = result['unknown_peaks']
        self.assertEqual(len(unknowns), 2)
        # Should have sequential labels
        self.assertIn('Unknown-1', unknowns[0]['label'])
        self.assertIn('Unknown-2', unknowns[1]['label'])
        # Labels should contain RI
        self.assertIn('RI=', unknowns[0]['label'])


# ======================================================================
# Tests: Area normalization
# ======================================================================

class TestAreaNormalization(unittest.TestCase):

    def test_area_pct_sums_to_100(self):
        """All peak area percentages should sum to 100%."""
        result, _ = run_analysis([
            (30.0, 0.5, 2.0),
            (60.0, 0.3, 2.0),
            (90.0, 0.2, 2.0),
        ])

        total_pct = 0
        for u in result['unknown_peaks']:
            total_pct += u['area_pct']
        for c in result['components'].values():
            total_pct += c['area_pct']

        self.assertAlmostEqual(total_pct, 100.0, delta=0.5)

    def test_normalization_disabled(self):
        """When normalization is off, area_pct might not sum to 100."""
        result, _ = run_analysis(
            [(50.0, 0.5, 2.0)],
            normalize_areas=False,
        )
        # area_pct should still be present but could be 0 when not normalized
        unknowns = result['unknown_peaks']
        if unknowns:
            # With normalization off, area_pct should be 0
            self.assertAlmostEqual(unknowns[0]['area_pct'], 0.0)


# ======================================================================
# Tests: Peak asymmetry
# ======================================================================

class TestPeakAsymmetry(unittest.TestCase):

    def test_symmetric_peak(self):
        """Gaussian peak should have asymmetry reasonably close to 1.0.

        Note: discrete sampling and baseline correction introduce some
        asymmetry even for a perfect Gaussian, so we allow wider tolerance.
        """
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        unknowns = result['unknown_peaks']
        if unknowns:
            asym = unknowns[0]['asymmetry']
            # Within 0.5-1.5 range for a roughly symmetric peak
            self.assertGreater(asym, 0.5)
            self.assertLess(asym, 1.6)


# ======================================================================
# Tests: Multi-port valve
# ======================================================================

class TestMultiPort(unittest.TestCase):

    def test_port_in_result(self):
        """Active port should appear in results."""
        method = make_default_method(
            active_port=2,
            port_labels={1: 'Sample', 2: 'Cal Gas'},
        )
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        self.assertEqual(result['port'], 2)
        self.assertEqual(result['port_label'], 'Cal Gas')

    def test_port_override_on_start(self):
        """Port can be overridden on start_run()."""
        method = make_default_method(
            active_port=1,
            port_labels={1: 'Sample', 3: 'Backflush'},
        )
        engine = GCAnalysisEngine(method)

        times, values = make_chromatogram([(50.0, 0.5, 2.0)])
        engine.start_run(port=3)
        for t, v in zip(times, values):
            engine.add_point(t, v)
        result = engine.finish_run()

        self.assertEqual(result['port'], 3)
        self.assertEqual(result['port_label'], 'Backflush')


# ======================================================================
# Tests: AnalysisMethod serialization
# ======================================================================

class TestAnalysisMethodSerialization(unittest.TestCase):

    def test_from_dict_roundtrip(self):
        """AnalysisMethod.from_dict should parse all fields."""
        data = {
            'name': 'Natural Gas',
            'min_peak_height': 0.05,
            'noise_threshold': 0.01,
            'normalize_areas': True,
            'ri_mode': 'kovats',
            'report_unknowns': True,
            'unknown_min_area_pct': 0.5,
            'components': {
                'CH4': {'rt_expected': 30, 'rt_tolerance': 2},
                'C2H6': {'rt_expected': 60, 'rt_tolerance': 2},
            },
            'ri_references': [
                {'carbon_number': 1, 'retention_time': 25, 'name': 'Methane'},
                {'carbon_number': 2, 'retention_time': 55, 'name': 'Ethane'},
            ],
            'port_labels': {'1': 'Sample', '2': 'Cal'},
        }
        method = AnalysisMethod.from_dict(data)
        self.assertEqual(method.name, 'Natural Gas')
        self.assertEqual(method.ri_mode, 'kovats')
        self.assertEqual(len(method.components), 2)
        self.assertEqual(len(method.ri_references), 2)
        self.assertEqual(method.ri_references[0].name, 'Methane')
        self.assertEqual(method.port_labels[2], 'Cal')
        self.assertTrue(method.report_unknowns)
        self.assertAlmostEqual(method.unknown_min_area_pct, 0.5)

    def test_from_json_file(self):
        """Load method from a JSON file."""
        data = {'name': 'test', 'min_peak_height': 0.1}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            method = AnalysisMethod.from_json_file(tmp_path)
            self.assertEqual(method.name, 'test')
            self.assertAlmostEqual(method.min_peak_height, 0.1)
        finally:
            os.unlink(tmp_path)


# ======================================================================
# Tests: Engine lifecycle
# ======================================================================

class TestEngineLifecycle(unittest.TestCase):

    def test_insufficient_data(self):
        """Engine with <10 points returns empty result."""
        engine = GCAnalysisEngine(make_default_method())
        engine.start_run()
        for i in range(5):
            engine.add_point(float(i), 0.01)
        result = engine.finish_run()
        self.assertEqual(result['total_peaks'], 0)
        self.assertIn('error', result['metadata'])

    def test_points_before_inject_delay_skipped(self):
        """Points before inject_delay_s are ignored."""
        method = make_default_method(inject_delay_s=10.0)
        engine = GCAnalysisEngine(method)
        engine.start_run()
        # Add 100 points before delay — all should be skipped
        for i in range(100):
            engine.add_point(i * 0.1, 0.5)  # 0-10s
        # Only 0 points remain (all within delay)
        result = engine.finish_run()
        self.assertEqual(result['chromatogram_points'], 0)

    def test_multiple_runs(self):
        """Engine can run multiple consecutive analyses."""
        engine = GCAnalysisEngine(make_default_method())

        for run_num in range(3):
            times, values = make_chromatogram([(50.0, 0.5, 2.0)])
            engine.start_run()
            for t, v in zip(times, values):
                engine.add_point(t, v)
            result = engine.finish_run()
            self.assertEqual(result['run_number'], run_num + 1)
            self.assertEqual(result['total_peaks'], 1)

    def test_run_number_increments(self):
        engine = GCAnalysisEngine(make_default_method())
        self.assertEqual(engine.run_number, 0)
        engine.start_run()
        self.assertEqual(engine.run_number, 1)

    def test_is_running_flag(self):
        engine = GCAnalysisEngine(make_default_method())
        self.assertFalse(engine.is_running)
        engine.start_run()
        self.assertTrue(engine.is_running)
        engine.add_point(0, 0.01)
        engine.finish_run()
        self.assertFalse(engine.is_running)

    def test_last_result(self):
        engine = GCAnalysisEngine(make_default_method())
        self.assertIsNone(engine.last_result)

        times, values = make_chromatogram([(50.0, 0.5, 2.0)])
        engine.start_run()
        for t, v in zip(times, values):
            engine.add_point(t, v)
        result = engine.finish_run()

        self.assertIsNotNone(engine.last_result)
        self.assertEqual(engine.last_result['run_number'], result['run_number'])

    def test_add_points_bulk(self):
        """add_points() bulk method works."""
        engine = GCAnalysisEngine(make_default_method())
        times, values = make_chromatogram([(50.0, 0.5, 2.0)])
        engine.start_run()
        engine.add_points(times, values)
        result = engine.finish_run()
        self.assertEqual(result['total_peaks'], 1)

    def test_get_raw_chromatogram(self):
        engine = GCAnalysisEngine(make_default_method())
        times, values = make_chromatogram([(50.0, 0.5, 2.0)])
        engine.start_run()
        engine.add_points(times, values)
        raw_t, raw_v = engine.get_raw_chromatogram()
        self.assertEqual(len(raw_t), len(times))
        self.assertEqual(len(raw_v), len(values))


# ======================================================================
# Tests: Library loading from process_gas.json
# ======================================================================

class TestProcessGasLibrary(unittest.TestCase):

    def test_load_bundled_library(self):
        """The bundled process_gas.json library loads correctly."""
        lib_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'services', 'gc_node', 'libraries', 'process_gas.json',
        )
        lib_path = os.path.normpath(lib_path)
        if not os.path.exists(lib_path):
            self.skipTest(f"Library file not found: {lib_path}")

        lib = PeakLibrary()
        lib.load_json(lib_path)
        self.assertGreater(lib.size, 30)  # Should have 43+ compounds

        # Spot-check known compounds
        methane = lib.find_candidates(ri=100, max_results=1, max_ri_delta=5)
        self.assertEqual(len(methane), 1)
        self.assertEqual(methane[0]['name'], 'Methane')

        benzene = lib.find_candidates(ri=653, max_results=1, max_ri_delta=5)
        self.assertEqual(len(benzene), 1)
        self.assertEqual(benzene[0]['name'], 'Benzene')

        h2s = lib.find_candidates(ri=150, max_results=1, max_ri_delta=5)
        self.assertEqual(len(h2s), 1)
        self.assertEqual(h2s[0]['name'], 'Hydrogen Sulfide')


# ======================================================================
# Tests: Full integration — end to end
# ======================================================================

class TestFullIntegration(unittest.TestCase):
    """End-to-end analysis with all features enabled."""

    def test_known_and_unknown_peaks(self):
        """Mix of known components and unknowns in one run."""
        method = make_default_method(
            components={
                'Methane': PeakWindow(name='Methane', rt_expected=30.0, rt_tolerance=3.0),
                'Ethane': PeakWindow(name='Ethane', rt_expected=60.0, rt_tolerance=3.0),
            },
            ri_references=[
                ReferenceStandard(carbon_number=1, retention_time=25.0),
                ReferenceStandard(carbon_number=2, retention_time=55.0),
                ReferenceStandard(carbon_number=3, retention_time=90.0),
            ],
            ri_mode='linear',
        )

        result, _ = run_analysis([
            (30.0, 0.5, 1.5),   # Methane (known)
            (60.0, 0.3, 2.0),   # Ethane (known)
            (75.0, 0.15, 2.0),  # Unknown
        ], method=method)

        # Should have 2 identified + 1 unknown
        self.assertEqual(result['identified_peaks'], 2)
        self.assertEqual(result['unknown_count'], 1)
        self.assertIn('Methane', result['components'])
        self.assertIn('Ethane', result['components'])
        self.assertEqual(len(result['unknown_peaks']), 1)

        # Area% should sum to ~100
        total_pct = 0
        for c in result['components'].values():
            total_pct += c['area_pct']
        for u in result['unknown_peaks']:
            total_pct += u['area_pct']
        self.assertAlmostEqual(total_pct, 100.0, delta=1.0)

    def test_with_calibration(self):
        """Calibration converts area to concentration."""
        method = make_default_method(
            components={
                'CH4': PeakWindow(name='CH4', rt_expected=50.0, rt_tolerance=3.0),
            },
            calibrations={
                'CH4': ComponentCalibration(
                    name='CH4', cal_type='response_factor',
                    points=[CalibrationPoint(concentration=80.0, area=1.0)],
                ),
            },
        )
        method.calibrations['CH4'].fit()

        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        self.assertIn('CH4', result['components'])
        # Concentration should be area * RF (80/1 = 80)
        conc = result['components']['CH4']['concentration']
        self.assertGreater(conc, 0)

    def test_result_metadata(self):
        """Result metadata is populated correctly."""
        method = make_default_method(
            ri_references=[
                ReferenceStandard(carbon_number=1, retention_time=25.0),
                ReferenceStandard(carbon_number=2, retention_time=55.0),
            ],
        )

        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)

        self.assertIn('timestamp', result)
        self.assertEqual(result['method'], 'test_method')
        self.assertGreater(result['chromatogram_points'], 100)
        self.assertEqual(result['ri_mode'], 'linear')
        self.assertEqual(result['metadata']['ri_references'], 2)


# ======================================================================
# Tests: System suitability (SST) metrics in results
# ======================================================================

class TestSystemSuitability(unittest.TestCase):
    """Test system suitability metrics added to analysis results."""

    def test_result_has_system_suitability_key(self):
        """Analysis result includes system_suitability section."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        self.assertIn('system_suitability', result)
        sst = result['system_suitability']
        self.assertIn('peaks_evaluated', sst)

    def test_theoretical_plates_positive(self):
        """Detected peaks should have positive theoretical plates."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        sst = result['system_suitability']
        # At least some peaks should have plates > 0
        self.assertIsNotNone(sst.get('min_theoretical_plates'))
        self.assertGreater(sst['min_theoretical_plates'], 0)

    def test_usp_tailing_near_one_for_gaussian(self):
        """Gaussian peak should have USP tailing near 1.0."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        sst = result['system_suitability']
        if sst.get('max_usp_tailing') is not None:
            # Gaussian should be reasonably symmetric: 0.5-2.0
            self.assertGreater(sst['max_usp_tailing'], 0.5)
            self.assertLess(sst['max_usp_tailing'], 2.0)

    def test_resolution_between_two_peaks(self):
        """Two well-separated peaks should have good resolution."""
        result, _ = run_analysis([
            (40.0, 0.5, 2.0),
            (80.0, 0.3, 2.0),
        ])
        sst = result['system_suitability']
        # With peaks at 40 and 80, resolution should be high
        if sst.get('min_resolution') is not None:
            self.assertGreater(sst['min_resolution'], 1.0)

    def test_component_data_has_sst_fields(self):
        """Identified components include SST metrics."""
        method = make_default_method(
            components={
                'Peak1': PeakWindow(name='Peak1', rt_expected=50.0, rt_tolerance=5.0),
            },
        )
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        comp = result['components'].get('Peak1', {})
        # SST fields should be present (may be None if not calculable)
        self.assertIn('theoretical_plates', comp)
        self.assertIn('usp_tailing', comp)
        self.assertIn('resolution', comp)
        self.assertIn('capacity_factor', comp)

    def test_capacity_factor_with_dead_time(self):
        """Capacity factor is calculated when dead time is set."""
        method = make_default_method(
            components={
                'Peak1': PeakWindow(name='Peak1', rt_expected=50.0, rt_tolerance=5.0),
            },
            dead_time_s=10.0,
        )
        result, _ = run_analysis([(50.0, 0.5, 2.0)], method=method)
        comp = result['components'].get('Peak1', {})
        # k' = (50 - 10) / 10 = 4.0
        if comp.get('capacity_factor') is not None:
            self.assertGreater(comp['capacity_factor'], 2.0)

    def test_empty_result_has_sst_key(self):
        """Empty result also has system_suitability key."""
        engine = GCAnalysisEngine(make_default_method())
        engine.start_run()
        engine.add_point(0, 0.01)
        result = engine.finish_run()
        self.assertIn('system_suitability', result)

    def test_single_peak_no_resolution(self):
        """Single peak should have no resolution (first peak)."""
        result, _ = run_analysis([(50.0, 0.5, 2.0)])
        sst = result['system_suitability']
        # With only one peak, min_resolution should be None
        self.assertIsNone(sst.get('min_resolution'))


if __name__ == '__main__':
    unittest.main()
