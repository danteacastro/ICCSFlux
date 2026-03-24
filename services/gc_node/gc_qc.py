"""
GC Quality Control Module

ISO 17025 quality control for chromatographic analysis:
- System Suitability Testing (SST) per USP <621> / EP 2.2.46
- QC sample tracking (blanks, duplicates, check standards, spikes)
- Method validation parameters (LOD, LOQ, linearity, precision, accuracy)
- Control charts (Shewhart X-bar) for trending QC data
- Retention time drift monitoring

References:
- ISO/IEC 17025:2017 Section 7.7 (Quality Control)
- USP <621> Chromatography - System Suitability
- ICH Q2(R1) Validation of Analytical Procedures
- ASTM E2968 Method Validation for GC

Pure Python + stdlib. No external dependencies. Python 3.4+ compatible.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('GCNode.QC')

# ======================================================================
# System Suitability Testing (SST)
# ======================================================================

@dataclass
class SSTResult:
    """Result of a System Suitability Test evaluation.

    Contains all USP <621> suitability parameters and pass/fail status.
    """
    timestamp: str = ''
    run_number: int = 0
    resolution: Dict[str, float] = field(default_factory=dict)
    tailing_factors: Dict[str, float] = field(default_factory=dict)
    theoretical_plates: Dict[str, float] = field(default_factory=dict)
    capacity_factors: Dict[str, float] = field(default_factory=dict)
    rsd_areas: Dict[str, float] = field(default_factory=dict)
    rsd_retention_times: Dict[str, float] = field(default_factory=dict)
    rt_drift: Dict[str, float] = field(default_factory=dict)
    passed: bool = False
    failures: List[str] = field(default_factory=list)

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            'timestamp': self.timestamp,
            'run_number': self.run_number,
            'resolution': dict(self.resolution),
            'tailing_factors': dict(self.tailing_factors),
            'theoretical_plates': dict(self.theoretical_plates),
            'capacity_factors': dict(self.capacity_factors),
            'rsd_areas': dict(self.rsd_areas),
            'rsd_retention_times': dict(self.rsd_retention_times),
            'rt_drift': dict(self.rt_drift),
            'passed': self.passed,
            'failures': list(self.failures),
        }

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> SSTResult
        return cls(
            timestamp=data.get('timestamp', ''),
            run_number=int(data.get('run_number', 0)),
            resolution=dict(data.get('resolution', {})),
            tailing_factors=dict(data.get('tailing_factors', {})),
            theoretical_plates=dict(data.get('theoretical_plates', {})),
            capacity_factors=dict(data.get('capacity_factors', {})),
            rsd_areas=dict(data.get('rsd_areas', {})),
            rsd_retention_times=dict(data.get('rsd_retention_times', {})),
            rt_drift=dict(data.get('rt_drift', {})),
            passed=bool(data.get('passed', False)),
            failures=list(data.get('failures', [])),
        )

@dataclass
class SSTCriteria:
    """Acceptance criteria for System Suitability Testing.

    Defaults based on USP <621> general requirements.
    """
    min_resolution: float = 1.5
    max_tailing: float = 2.0
    min_plates: int = 2000
    max_rsd_area_pct: float = 2.0
    max_rsd_rt_pct: float = 1.0
    max_rt_drift_s: float = 0.5
    min_replicates: int = 5

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            'min_resolution': self.min_resolution,
            'max_tailing': self.max_tailing,
            'min_plates': self.min_plates,
            'max_rsd_area_pct': self.max_rsd_area_pct,
            'max_rsd_rt_pct': self.max_rsd_rt_pct,
            'max_rt_drift_s': self.max_rt_drift_s,
            'min_replicates': self.min_replicates,
        }

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> SSTCriteria
        return cls(
            min_resolution=float(data.get('min_resolution', 1.5)),
            max_tailing=float(data.get('max_tailing', 2.0)),
            min_plates=int(data.get('min_plates', 2000)),
            max_rsd_area_pct=float(data.get('max_rsd_area_pct', 2.0)),
            max_rsd_rt_pct=float(data.get('max_rsd_rt_pct', 1.0)),
            max_rt_drift_s=float(data.get('max_rt_drift_s', 0.5)),
            min_replicates=int(data.get('min_replicates', 5)),
        )

class SystemSuitabilityTest:
    """System Suitability Testing per USP <621>.

    Collects replicate injection results, then evaluates resolution,
    tailing factor, theoretical plates, capacity factor, and %RSD
    of peak areas and retention times.

    Usage:
        sst = SystemSuitabilityTest(SSTCriteria())
        for run in replicate_runs:
            sst.add_replicate(run)
        result = sst.evaluate()
        if result.passed:
            print("SST passed - proceed with sample analysis")
    """

    # Maximum replicates retained in memory (SST rarely needs >20)
    MAX_REPLICATES = 100

    def __init__(self, criteria=None):
        # type: (Optional[SSTCriteria]) -> None
        self.criteria = criteria or SSTCriteria()
        self._replicate_data = []  # type: List[Dict[str, Any]]
        self._reference_rts = {}   # type: Dict[str, float]

    def set_reference_rts(self, rts):
        # type: (Dict[str, float]) -> None
        """Set reference retention times for drift monitoring.

        Args:
            rts: {component_name: retention_time_seconds} from a
                 reference run or method definition.
        """
        self._reference_rts = dict(rts)

    def add_replicate(self, result):
        # type: (Dict[str, Any]) -> None
        """Add an analysis result from GCAnalysisEngine.finish_run().

        Args:
            result: Dict with 'components' key containing per-component
                    data (area, retention_time, peak_width, asymmetry, etc.)
        """
        self._replicate_data.append(result)
        if len(self._replicate_data) > self.MAX_REPLICATES:
            self._replicate_data = self._replicate_data[-self.MAX_REPLICATES:]

    def evaluate(self):
        # type: () -> SSTResult
        """Evaluate all SST criteria against collected replicates.

        Returns:
            SSTResult with all computed parameters and pass/fail.
        """
        failures = []  # type: List[str]
        n = len(self._replicate_data)

        if n == 0:
            return SSTResult(
                timestamp=datetime.now().isoformat(),
                passed=False,
                failures=['No replicate data provided'],
            )

        # Collect component names across all replicates
        all_components = set()  # type: set
        for rep in self._replicate_data:
            for name in rep.get('components', {}):
                all_components.add(name)

        # --- Per-component calculations ---
        tailing_factors = {}    # type: Dict[str, float]
        theoretical_plates = {} # type: Dict[str, float]
        capacity_factors = {}   # type: Dict[str, float]
        rsd_areas = {}          # type: Dict[str, float]
        rsd_rts = {}            # type: Dict[str, float]
        rt_drift = {}           # type: Dict[str, float]

        for comp_name in sorted(all_components):
            areas = []    # type: List[float]
            rts = []      # type: List[float]
            widths = []   # type: List[float]
            asym_vals = []  # type: List[float]

            for rep in self._replicate_data:
                comp = rep.get('components', {}).get(comp_name)
                if comp is None:
                    continue
                areas.append(float(comp.get('area', 0)))
                rts.append(float(comp.get('retention_time', 0)))
                widths.append(float(comp.get('peak_width', 0)))
                asym_vals.append(float(comp.get('asymmetry', 1.0)))

            if not rts:
                continue

            # Tailing factor (average across replicates)
            # USP tailing: T = W_0.05 / (2f). The asymmetry from the
            # analysis engine is measured at 10%. For SST purposes we
            # use the reported asymmetry as an approximation.
            avg_tailing = self._calc_tailing_from_asymmetry(asym_vals)
            tailing_factors[comp_name] = round(avg_tailing, 3)
            if avg_tailing > self.criteria.max_tailing:
                failures.append(
                    'Tailing factor for %s = %.3f (max %.1f)' %
                    (comp_name, avg_tailing, self.criteria.max_tailing)
                )

            # Theoretical plates (average across replicates)
            plate_values = []  # type: List[float]
            for rt_val, w_val in zip(rts, widths):
                plates = self._calc_plates_half_width(rt_val, w_val)
                if plates > 0:
                    plate_values.append(plates)

            if plate_values:
                avg_plates = sum(plate_values) / len(plate_values)
                theoretical_plates[comp_name] = round(avg_plates, 0)
                if avg_plates < self.criteria.min_plates:
                    failures.append(
                        'Theoretical plates for %s = %.0f (min %d)' %
                        (comp_name, avg_plates, self.criteria.min_plates)
                    )

            # Capacity factor (from last replicate, using first peak as t0 proxy)
            if rts:
                # Use the smallest RT across all components as t0 estimate
                all_rts_flat = []  # type: List[float]
                for rep in self._replicate_data:
                    for c_data in rep.get('components', {}).values():
                        rt_val = float(c_data.get('retention_time', 0))
                        if rt_val > 0:
                            all_rts_flat.append(rt_val)
                t0 = min(all_rts_flat) if all_rts_flat else 0.0
                avg_rt = sum(rts) / len(rts)
                k_prime = self._calc_capacity_factor(avg_rt, t0)
                capacity_factors[comp_name] = round(k_prime, 3)

            # %RSD of areas
            if len(areas) >= self.criteria.min_replicates:
                rsd_a = self._calc_rsd(areas)
                rsd_areas[comp_name] = round(rsd_a, 4)
                if rsd_a > self.criteria.max_rsd_area_pct:
                    failures.append(
                        'Area %%RSD for %s = %.4f%% (max %.1f%%)' %
                        (comp_name, rsd_a, self.criteria.max_rsd_area_pct)
                    )
            elif n < self.criteria.min_replicates:
                failures.append(
                    'Insufficient replicates for %s area RSD: %d of %d required' %
                    (comp_name, len(areas), self.criteria.min_replicates)
                )

            # %RSD of retention times
            if len(rts) >= self.criteria.min_replicates:
                rsd_r = self._calc_rsd(rts)
                rsd_rts[comp_name] = round(rsd_r, 4)
                if rsd_r > self.criteria.max_rsd_rt_pct:
                    failures.append(
                        'RT %%RSD for %s = %.4f%% (max %.1f%%)' %
                        (comp_name, rsd_r, self.criteria.max_rsd_rt_pct)
                    )

            # RT drift from reference
            if comp_name in self._reference_rts and rts:
                ref_rt = self._reference_rts[comp_name]
                latest_rt = rts[-1]
                drift = abs(latest_rt - ref_rt)
                rt_drift[comp_name] = round(drift, 4)
                if drift > self.criteria.max_rt_drift_s:
                    failures.append(
                        'RT drift for %s = %.4f s (max %.1f s)' %
                        (comp_name, drift, self.criteria.max_rt_drift_s)
                    )

        # --- Resolution between adjacent peak pairs ---
        resolution = {}  # type: Dict[str, float]
        if n > 0:
            # Use the latest replicate for resolution calculation
            last_rep = self._replicate_data[-1]
            comps = last_rep.get('components', {})
            # Sort components by retention time
            sorted_comps = sorted(
                comps.items(),
                key=lambda item: float(item[1].get('retention_time', 0)),
            )
            for i in range(len(sorted_comps) - 1):
                name1, data1 = sorted_comps[i]
                name2, data2 = sorted_comps[i + 1]
                r = self._calc_resolution(data1, data2)
                pair_label = '%s/%s' % (name1, name2)
                resolution[pair_label] = round(r, 3)
                if r < self.criteria.min_resolution:
                    failures.append(
                        'Resolution %s = %.3f (min %.1f)' %
                        (pair_label, r, self.criteria.min_resolution)
                    )

        passed = len(failures) == 0

        run_num = 0
        if self._replicate_data:
            run_num = int(self._replicate_data[-1].get('run_number', 0))

        result = SSTResult(
            timestamp=datetime.now().isoformat(),
            run_number=run_num,
            resolution=resolution,
            tailing_factors=tailing_factors,
            theoretical_plates=theoretical_plates,
            capacity_factors=capacity_factors,
            rsd_areas=rsd_areas,
            rsd_retention_times=rsd_rts,
            rt_drift=rt_drift,
            passed=passed,
            failures=failures,
        )

        if passed:
            logger.info('SST PASSED (%d replicates, %d components)',
                        n, len(all_components))
        else:
            logger.warning('SST FAILED: %s', '; '.join(failures))

        return result

    @staticmethod
    def _calc_resolution(peak1, peak2):
        # type: (Dict[str, Any], Dict[str, Any]) -> float
        """Resolution between two adjacent peaks.

        R = 2 * (tR2 - tR1) / (w1 + w2)

        Uses peak_width (width at half-height * 1.699 for Gaussian peaks
        to approximate base width, or direct base width if available).
        """
        rt1 = float(peak1.get('retention_time', 0))
        rt2 = float(peak2.get('retention_time', 0))

        # Approximate base width from half-height width (W = 1.699 * W_half
        # for Gaussian peaks, but here we use the reported width which is
        # already at half-height). USP formula uses base width, so scale.
        w1 = float(peak1.get('peak_width', 0)) * 1.699
        w2 = float(peak2.get('peak_width', 0)) * 1.699

        denom = w1 + w2
        if denom <= 0:
            return 0.0
        return 2.0 * abs(rt2 - rt1) / denom

    @staticmethod
    def _calc_tailing_from_asymmetry(asymmetry_values):
        # type: (List[float]) -> float
        """Approximate USP tailing factor from asymmetry factors.

        USP tailing T = W_0.05 / (2f) where f is the front half-width
        at 5% height. The asymmetry factor (B/A at 10% height) is related
        but not identical. For moderate asymmetry, T ~ (A + B) / (2A)
        which simplifies to T ~ (1 + asymmetry) / 2.
        """
        if not asymmetry_values:
            return 1.0
        avg_asym = sum(asymmetry_values) / len(asymmetry_values)
        return (1.0 + avg_asym) / 2.0

    @staticmethod
    def _calc_plates_half_width(rt, w_half):
        # type: (float, float) -> float
        """Theoretical plates from retention time and half-height width.

        N = 5.545 * (tR / W_half)^2
        """
        if w_half <= 0 or rt <= 0:
            return 0.0
        return 5.545 * (rt / w_half) ** 2

    @staticmethod
    def _calc_capacity_factor(rt, t0):
        # type: (float, float) -> float
        """Capacity factor (retention factor).

        k' = (tR - t0) / t0
        """
        if t0 <= 0:
            return 0.0
        return (rt - t0) / t0

    @staticmethod
    def _calc_rsd(values):
        # type: (List[float]) -> float
        """%RSD = (stdev / mean) * 100."""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        if abs(mean) < 1e-15:
            return 0.0
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = math.sqrt(variance)
        return (stdev / abs(mean)) * 100.0

    def clear(self):
        # type: () -> None
        """Reset replicate data for a new SST sequence."""
        self._replicate_data.clear()

# ======================================================================
# QC Sample Tracking
# ======================================================================

class QCSampleType(Enum):
    """Types of QC samples in an analytical sequence."""
    BLANK = 'blank'
    CHECK_STANDARD = 'check_standard'
    DUPLICATE = 'duplicate'
    SPIKE = 'spike'
    CALIBRATION_VERIFICATION = 'calibration_verification'
    REFERENCE_STANDARD = 'reference_standard'

@dataclass
class QCSample:
    """Record of a QC sample evaluation."""
    sample_id: str = ''
    sample_type: QCSampleType = QCSampleType.BLANK
    timestamp: str = ''
    run_number: int = 0
    expected_values: Dict[str, float] = field(default_factory=dict)
    measured_values: Dict[str, float] = field(default_factory=dict)
    passed: bool = False
    failures: List[str] = field(default_factory=list)
    recovery_pct: Dict[str, float] = field(default_factory=dict)
    rsd_pct: Dict[str, float] = field(default_factory=dict)
    notes: str = ''

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            'sample_id': self.sample_id,
            'sample_type': self.sample_type.value,
            'timestamp': self.timestamp,
            'run_number': self.run_number,
            'expected_values': dict(self.expected_values),
            'measured_values': dict(self.measured_values),
            'passed': self.passed,
            'failures': list(self.failures),
            'recovery_pct': dict(self.recovery_pct),
            'rsd_pct': dict(self.rsd_pct),
            'notes': self.notes,
        }

@dataclass
class QCLimits:
    """Acceptance limits for QC sample evaluations."""
    blank_max_area: float = 0.1
    check_std_tolerance_pct: float = 10.0
    duplicate_max_rsd_pct: float = 5.0
    spike_recovery_min_pct: float = 80.0
    spike_recovery_max_pct: float = 120.0
    cal_verify_tolerance_pct: float = 15.0

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            'blank_max_area': self.blank_max_area,
            'check_std_tolerance_pct': self.check_std_tolerance_pct,
            'duplicate_max_rsd_pct': self.duplicate_max_rsd_pct,
            'spike_recovery_min_pct': self.spike_recovery_min_pct,
            'spike_recovery_max_pct': self.spike_recovery_max_pct,
            'cal_verify_tolerance_pct': self.cal_verify_tolerance_pct,
        }

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> QCLimits
        return cls(
            blank_max_area=float(data.get('blank_max_area', 0.1)),
            check_std_tolerance_pct=float(data.get('check_std_tolerance_pct', 10.0)),
            duplicate_max_rsd_pct=float(data.get('duplicate_max_rsd_pct', 5.0)),
            spike_recovery_min_pct=float(data.get('spike_recovery_min_pct', 80.0)),
            spike_recovery_max_pct=float(data.get('spike_recovery_max_pct', 120.0)),
            cal_verify_tolerance_pct=float(data.get('cal_verify_tolerance_pct', 15.0)),
        )

class QCTracker:
    """Track and evaluate QC samples throughout an analytical sequence.

    Maintains a history of QC evaluations (blanks, check standards,
    duplicates, spikes, calibration verifications) and provides
    Shewhart control chart data for trending.

    Usage:
        tracker = QCTracker(QCLimits())
        blank_qc = tracker.evaluate_blank(blank_result)
        std_qc = tracker.evaluate_check_standard(std_result, expected)
        chart = tracker.get_control_chart_data('Methane', QCSampleType.CHECK_STANDARD)
    """

    def __init__(self, limits=None):
        # type: (Optional[QCLimits]) -> None
        self.limits = limits or QCLimits()
        self._samples = []   # type: List[QCSample]
        self._history_limit = 1000
        self._run_counter = 0

    def evaluate_blank(self, result):
        # type: (Dict[str, Any]) -> QCSample
        """Evaluate a blank (solvent/carrier gas) run.

        Checks that no component area exceeds blank_max_area threshold,
        indicating carryover or contamination.

        Args:
            result: Analysis result from GCAnalysisEngine.finish_run().

        Returns:
            QCSample with pass/fail and measured values.
        """
        self._run_counter += 1
        failures = []  # type: List[str]
        measured = {}  # type: Dict[str, float]

        comps = result.get('components', {})
        for name, data in comps.items():
            area_pct = float(data.get('area_pct', 0))
            measured[name] = area_pct
            if area_pct > self.limits.blank_max_area:
                failures.append(
                    'Blank area for %s = %.4f%% (max %.2f%%)' %
                    (name, area_pct, self.limits.blank_max_area)
                )

        # Also check unknown peaks in the blank
        for unk in result.get('unknown_peaks', []):
            area_pct = float(unk.get('area_pct', 0))
            label = unk.get('label', 'Unknown')
            if area_pct > self.limits.blank_max_area:
                failures.append(
                    'Blank area for %s = %.4f%% (max %.2f%%)' %
                    (label, area_pct, self.limits.blank_max_area)
                )

        sample = QCSample(
            sample_id='BLANK-%04d' % self._run_counter,
            sample_type=QCSampleType.BLANK,
            timestamp=result.get('timestamp', datetime.now().isoformat()),
            run_number=int(result.get('run_number', self._run_counter)),
            expected_values={},
            measured_values=measured,
            passed=len(failures) == 0,
            failures=failures,
            notes='Blank evaluation - checking carryover/contamination',
        )

        self._add_sample(sample)
        return sample

    def evaluate_check_standard(self, result, expected):
        # type: (Dict[str, Any], Dict[str, float]) -> QCSample
        """Evaluate a check standard against known concentrations.

        Args:
            result: Analysis result from GCAnalysisEngine.finish_run().
            expected: {component_name: expected_concentration}

        Returns:
            QCSample with pass/fail, measured values, and deviations.
        """
        self._run_counter += 1
        failures = []  # type: List[str]
        measured = {}  # type: Dict[str, float]
        recovery = {}  # type: Dict[str, float]

        comps = result.get('components', {})
        for name, exp_val in expected.items():
            comp = comps.get(name)
            if comp is None:
                failures.append('Component %s not detected in check standard' % name)
                continue

            meas_val = float(comp.get('concentration', 0))
            measured[name] = meas_val

            if abs(exp_val) > 1e-15:
                pct_diff = abs(meas_val - exp_val) / abs(exp_val) * 100.0
                recovery[name] = round(meas_val / exp_val * 100.0, 2)
            else:
                pct_diff = abs(meas_val) * 100.0
                recovery[name] = 0.0

            if pct_diff > self.limits.check_std_tolerance_pct:
                failures.append(
                    'Check standard %s: measured=%.4f expected=%.4f (%.1f%% deviation, max %.1f%%)' %
                    (name, meas_val, exp_val, pct_diff, self.limits.check_std_tolerance_pct)
                )

        sample = QCSample(
            sample_id='CHKSTD-%04d' % self._run_counter,
            sample_type=QCSampleType.CHECK_STANDARD,
            timestamp=result.get('timestamp', datetime.now().isoformat()),
            run_number=int(result.get('run_number', self._run_counter)),
            expected_values=dict(expected),
            measured_values=measured,
            passed=len(failures) == 0,
            failures=failures,
            recovery_pct=recovery,
            notes='Check standard verification',
        )

        self._add_sample(sample)
        return sample

    def evaluate_duplicate(self, result1, result2):
        # type: (Dict[str, Any], Dict[str, Any]) -> QCSample
        """Evaluate duplicate injections for precision.

        Calculates %RSD between paired measurements for each component.

        Args:
            result1: First injection result.
            result2: Second injection result.

        Returns:
            QCSample with pass/fail and per-component RSDs.
        """
        self._run_counter += 1
        failures = []  # type: List[str]
        measured = {}  # type: Dict[str, float]
        rsd_values = {}  # type: Dict[str, float]

        comps1 = result1.get('components', {})
        comps2 = result2.get('components', {})
        all_names = set(comps1.keys()) | set(comps2.keys())

        for name in sorted(all_names):
            c1 = comps1.get(name)
            c2 = comps2.get(name)
            if c1 is None or c2 is None:
                failures.append('Component %s missing in one duplicate' % name)
                continue

            v1 = float(c1.get('concentration', 0))
            v2 = float(c2.get('concentration', 0))
            mean = (v1 + v2) / 2.0
            measured[name] = mean

            if abs(mean) > 1e-15:
                # RSD of two values: stdev / mean * 100
                diff_sq = ((v1 - mean) ** 2 + (v2 - mean) ** 2) / 1.0  # n-1 = 1
                rsd = math.sqrt(diff_sq) / abs(mean) * 100.0
            else:
                rsd = 0.0

            rsd_values[name] = round(rsd, 4)
            if rsd > self.limits.duplicate_max_rsd_pct:
                failures.append(
                    'Duplicate RSD for %s = %.4f%% (max %.1f%%)' %
                    (name, rsd, self.limits.duplicate_max_rsd_pct)
                )

        sample = QCSample(
            sample_id='DUP-%04d' % self._run_counter,
            sample_type=QCSampleType.DUPLICATE,
            timestamp=result2.get('timestamp', datetime.now().isoformat()),
            run_number=int(result2.get('run_number', self._run_counter)),
            expected_values={},
            measured_values=measured,
            passed=len(failures) == 0,
            failures=failures,
            rsd_pct=rsd_values,
            notes='Duplicate injection precision check',
        )

        self._add_sample(sample)
        return sample

    def evaluate_spike(self, unspiked, spiked, spike_amounts):
        # type: (Dict[str, Any], Dict[str, Any], Dict[str, float]) -> QCSample
        """Evaluate spike recovery (matrix effect / accuracy check).

        Recovery% = (spiked_result - unspiked_result) / spike_amount * 100

        Args:
            unspiked: Analysis result of the unspiked sample.
            spiked: Analysis result of the spiked sample.
            spike_amounts: {component_name: amount_spiked}

        Returns:
            QCSample with pass/fail and per-component recovery percentages.
        """
        self._run_counter += 1
        failures = []  # type: List[str]
        measured = {}  # type: Dict[str, float]
        recovery = {}  # type: Dict[str, float]

        comps_us = unspiked.get('components', {})
        comps_sp = spiked.get('components', {})

        for name, spike_amt in spike_amounts.items():
            c_us = comps_us.get(name)
            c_sp = comps_sp.get(name)

            val_us = float(c_us.get('concentration', 0)) if c_us else 0.0
            val_sp = float(c_sp.get('concentration', 0)) if c_sp else 0.0

            measured[name] = val_sp

            if abs(spike_amt) > 1e-15:
                rec_pct = (val_sp - val_us) / spike_amt * 100.0
            else:
                rec_pct = 0.0

            recovery[name] = round(rec_pct, 2)

            if rec_pct < self.limits.spike_recovery_min_pct:
                failures.append(
                    'Spike recovery for %s = %.1f%% (min %.1f%%)' %
                    (name, rec_pct, self.limits.spike_recovery_min_pct)
                )
            elif rec_pct > self.limits.spike_recovery_max_pct:
                failures.append(
                    'Spike recovery for %s = %.1f%% (max %.1f%%)' %
                    (name, rec_pct, self.limits.spike_recovery_max_pct)
                )

        sample = QCSample(
            sample_id='SPIKE-%04d' % self._run_counter,
            sample_type=QCSampleType.SPIKE,
            timestamp=spiked.get('timestamp', datetime.now().isoformat()),
            run_number=int(spiked.get('run_number', self._run_counter)),
            expected_values=dict(spike_amounts),
            measured_values=measured,
            passed=len(failures) == 0,
            failures=failures,
            recovery_pct=recovery,
            notes='Spike recovery (accuracy / matrix effect)',
        )

        self._add_sample(sample)
        return sample

    def evaluate_cal_verification(self, result, expected):
        # type: (Dict[str, Any], Dict[str, float]) -> QCSample
        """Evaluate a mid-run calibration verification standard.

        Similar to check standard but uses a wider tolerance (cal_verify).

        Args:
            result: Analysis result from GCAnalysisEngine.finish_run().
            expected: {component_name: expected_concentration}

        Returns:
            QCSample with pass/fail.
        """
        self._run_counter += 1
        failures = []  # type: List[str]
        measured = {}  # type: Dict[str, float]
        recovery = {}  # type: Dict[str, float]

        comps = result.get('components', {})
        for name, exp_val in expected.items():
            comp = comps.get(name)
            if comp is None:
                failures.append('Component %s not detected in cal verification' % name)
                continue

            meas_val = float(comp.get('concentration', 0))
            measured[name] = meas_val

            if abs(exp_val) > 1e-15:
                pct_diff = abs(meas_val - exp_val) / abs(exp_val) * 100.0
                recovery[name] = round(meas_val / exp_val * 100.0, 2)
            else:
                pct_diff = abs(meas_val) * 100.0
                recovery[name] = 0.0

            if pct_diff > self.limits.cal_verify_tolerance_pct:
                failures.append(
                    'Cal verification %s: measured=%.4f expected=%.4f (%.1f%% deviation, max %.1f%%)' %
                    (name, meas_val, exp_val, pct_diff, self.limits.cal_verify_tolerance_pct)
                )

        sample = QCSample(
            sample_id='CALVER-%04d' % self._run_counter,
            sample_type=QCSampleType.CALIBRATION_VERIFICATION,
            timestamp=result.get('timestamp', datetime.now().isoformat()),
            run_number=int(result.get('run_number', self._run_counter)),
            expected_values=dict(expected),
            measured_values=measured,
            passed=len(failures) == 0,
            failures=failures,
            recovery_pct=recovery,
            notes='Calibration verification - mid-run accuracy check',
        )

        self._add_sample(sample)
        return sample

    def get_history(self, sample_type=None, limit=100):
        # type: (Optional[QCSampleType], int) -> List[Dict[str, Any]]
        """Retrieve QC sample history.

        Args:
            sample_type: Filter by type (None = all types).
            limit: Maximum number of records to return.

        Returns:
            List of QCSample dicts, most recent first.
        """
        filtered = self._samples
        if sample_type is not None:
            filtered = [s for s in filtered if s.sample_type == sample_type]

        # Most recent first
        filtered = list(reversed(filtered))
        return [s.to_dict() for s in filtered[:limit]]

    def get_control_chart_data(self, component, sample_type, field_name='measured'):
        # type: (str, QCSampleType, str) -> Dict[str, Any]
        """Generate Shewhart X-bar control chart data for a component.

        Extracts historical values for the specified component from
        QC samples of the given type, then computes mean, UCL, and LCL.

        UCL = mean + 3*sigma
        LCL = mean - 3*sigma

        Args:
            component: Component name to chart.
            sample_type: QC sample type to filter.
            field_name: 'measured' for measured_values, 'recovery' for recovery_pct.

        Returns:
            {values, mean, ucl, lcl, timestamps, n, sigma}
        """
        values = []     # type: List[float]
        timestamps = [] # type: List[str]

        for sample in self._samples:
            if sample.sample_type != sample_type:
                continue

            if field_name == 'recovery':
                source = sample.recovery_pct
            else:
                source = sample.measured_values

            if component in source:
                values.append(source[component])
                timestamps.append(sample.timestamp)

        if len(values) < 2:
            mean = values[0] if values else 0.0
            return {
                'values': values,
                'mean': mean,
                'ucl': mean,
                'lcl': mean,
                'timestamps': timestamps,
                'n': len(values),
                'sigma': 0.0,
            }

        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        sigma = math.sqrt(variance)

        return {
            'values': values,
            'mean': round(mean, 6),
            'ucl': round(mean + 3.0 * sigma, 6),
            'lcl': round(mean - 3.0 * sigma, 6),
            'timestamps': timestamps,
            'n': n,
            'sigma': round(sigma, 6),
        }

    def get_summary(self):
        # type: () -> Dict[str, Any]
        """QC program summary: counts and pass rates by sample type."""
        summary = {}  # type: Dict[str, Any]
        for st in QCSampleType:
            samples_of_type = [s for s in self._samples if s.sample_type == st]
            total = len(samples_of_type)
            passed = sum(1 for s in samples_of_type if s.passed)
            summary[st.value] = {
                'total': total,
                'passed': passed,
                'failed': total - passed,
                'pass_rate_pct': round(passed / total * 100.0, 1) if total > 0 else 0.0,
            }

        total_all = len(self._samples)
        passed_all = sum(1 for s in self._samples if s.passed)
        summary['overall'] = {
            'total': total_all,
            'passed': passed_all,
            'failed': total_all - passed_all,
            'pass_rate_pct': round(passed_all / total_all * 100.0, 1) if total_all > 0 else 0.0,
        }

        return summary

    def _add_sample(self, sample):
        # type: (QCSample) -> None
        """Add a QC sample, enforcing history limit."""
        self._samples.append(sample)
        if len(self._samples) > self._history_limit:
            self._samples = self._samples[-self._history_limit:]

        status = 'PASS' if sample.passed else 'FAIL'
        logger.info('QC %s [%s] %s: %s', sample.sample_type.value,
                     status, sample.sample_id,
                     '; '.join(sample.failures) if sample.failures else 'OK')

# ======================================================================
# Method Validation (ICH Q2 / ASTM E2968)
# ======================================================================

@dataclass
class MethodValidation:
    """Method validation record per ICH Q2(R1) and ASTM E2968.

    Stores validation parameters: linearity, LOD, LOQ, precision,
    accuracy, specificity, robustness, and validated range.
    """
    method_name: str = ''
    validated_date: str = ''
    validated_by: str = ''
    linearity: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    lod: Dict[str, float] = field(default_factory=dict)
    loq: Dict[str, float] = field(default_factory=dict)
    precision_repeatability: Dict[str, float] = field(default_factory=dict)
    precision_reproducibility: Dict[str, float] = field(default_factory=dict)
    accuracy: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    specificity_notes: str = ''
    robustness_notes: str = ''
    range_min: Dict[str, float] = field(default_factory=dict)
    range_max: Dict[str, float] = field(default_factory=dict)
    status: str = 'provisional'

    def to_dict(self):
        # type: () -> Dict[str, Any]
        return {
            'method_name': self.method_name,
            'validated_date': self.validated_date,
            'validated_by': self.validated_by,
            'linearity': dict(self.linearity),
            'lod': dict(self.lod),
            'loq': dict(self.loq),
            'precision_repeatability': dict(self.precision_repeatability),
            'precision_reproducibility': dict(self.precision_reproducibility),
            'accuracy': dict(self.accuracy),
            'specificity_notes': self.specificity_notes,
            'robustness_notes': self.robustness_notes,
            'range_min': dict(self.range_min),
            'range_max': dict(self.range_max),
            'status': self.status,
        }

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> MethodValidation
        return cls(
            method_name=data.get('method_name', ''),
            validated_date=data.get('validated_date', ''),
            validated_by=data.get('validated_by', ''),
            linearity=dict(data.get('linearity', {})),
            lod=dict(data.get('lod', {})),
            loq=dict(data.get('loq', {})),
            precision_repeatability=dict(data.get('precision_repeatability', {})),
            precision_reproducibility=dict(data.get('precision_reproducibility', {})),
            accuracy=dict(data.get('accuracy', {})),
            specificity_notes=data.get('specificity_notes', ''),
            robustness_notes=data.get('robustness_notes', ''),
            range_min=dict(data.get('range_min', {})),
            range_max=dict(data.get('range_max', {})),
            status=data.get('status', 'provisional'),
        )

    @staticmethod
    def calc_lod(blank_std, slope):
        # type: (float, float) -> float
        """Limit of Detection per ICH Q2.

        LOD = 3.3 * sigma / S
        where sigma = standard deviation of blank response,
              S = slope of calibration curve.

        Args:
            blank_std: Standard deviation of blank signal.
            slope: Slope of calibration curve (response per unit concentration).

        Returns:
            LOD concentration value.
        """
        if abs(slope) < 1e-15:
            return 0.0
        return 3.3 * blank_std / abs(slope)

    @staticmethod
    def calc_loq(blank_std, slope):
        # type: (float, float) -> float
        """Limit of Quantitation per ICH Q2.

        LOQ = 10 * sigma / S
        where sigma = standard deviation of blank response,
              S = slope of calibration curve.

        Args:
            blank_std: Standard deviation of blank signal.
            slope: Slope of calibration curve (response per unit concentration).

        Returns:
            LOQ concentration value.
        """
        if abs(slope) < 1e-15:
            return 0.0
        return 10.0 * blank_std / abs(slope)

    @staticmethod
    def calc_linearity(concentrations, responses):
        # type: (List[float], List[float]) -> Dict[str, Any]
        """Calculate linearity parameters from calibration data.

        Performs linear regression (response = slope * concentration + intercept)
        and computes R-squared.

        Args:
            concentrations: List of known concentrations.
            responses: List of measured responses (areas).

        Returns:
            Dict with keys: slope, intercept, r_squared, range_min,
            range_max, points.
        """
        n = len(concentrations)
        if n < 2:
            return {
                'slope': 0.0, 'intercept': 0.0, 'r_squared': 0.0,
                'range_min': 0.0, 'range_max': 0.0, 'points': n,
            }

        # Linear regression: response = slope * conc + intercept
        sum_x = sum(concentrations)
        sum_y = sum(responses)
        sum_xx = sum(c * c for c in concentrations)
        sum_xy = sum(c * r for c, r in zip(concentrations, responses))
        mean_x = sum_x / n
        mean_y = sum_y / n

        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-15:
            return {
                'slope': 0.0, 'intercept': mean_y, 'r_squared': 0.0,
                'range_min': min(concentrations), 'range_max': max(concentrations),
                'points': n,
            }

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # R-squared
        ss_res = sum((r - (slope * c + intercept)) ** 2
                      for c, r in zip(concentrations, responses))
        ss_tot = sum((r - mean_y) ** 2 for r in responses)

        r_squared = 1.0 - ss_res / ss_tot if abs(ss_tot) > 1e-15 else 0.0

        return {
            'slope': round(slope, 6),
            'intercept': round(intercept, 6),
            'r_squared': round(r_squared, 6),
            'range_min': round(min(concentrations), 6),
            'range_max': round(max(concentrations), 6),
            'points': n,
        }

    @staticmethod
    def calc_precision(values):
        # type: (List[float]) -> float
        """Calculate %RSD for precision assessment.

        Args:
            values: Replicate measurement values.

        Returns:
            %RSD value.
        """
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        if abs(mean) < 1e-15:
            return 0.0
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = math.sqrt(variance)
        return round((stdev / abs(mean)) * 100.0, 4)

    @staticmethod
    def calc_accuracy(measured_values, true_value):
        # type: (List[float], float) -> Dict[str, float]
        """Calculate accuracy as recovery% and bias%.

        Args:
            measured_values: List of measured concentrations.
            true_value: Known/certified concentration.

        Returns:
            Dict with recovery_pct and bias_pct.
        """
        if not measured_values or abs(true_value) < 1e-15:
            return {'recovery_pct': 0.0, 'bias_pct': 0.0}

        mean_measured = sum(measured_values) / len(measured_values)
        recovery = mean_measured / true_value * 100.0
        bias = (mean_measured - true_value) / true_value * 100.0

        return {
            'recovery_pct': round(recovery, 2),
            'bias_pct': round(bias, 2),
        }
