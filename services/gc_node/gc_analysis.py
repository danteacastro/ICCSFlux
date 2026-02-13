"""
GC Chromatogram Analysis Engine

Replaces vendor GC software for process gas chromatography:
  - Baseline correction (rolling minimum + linear interpolation)
  - Peak detection (derivative zero-crossing with height/width thresholds)
  - Peak integration (trapezoidal rule)
  - Component identification (retention time windows)
  - Retention index calculation (Kovats isothermal + linear RI)
  - Peak library matching for unknown identification
  - Area normalization (area%)
  - Multi-point calibration (response factors, linear/quadratic)
  - Multi-port valve / stream selection
  - Peak asymmetry factor

Pure Python + stdlib math. No numpy/scipy required (runs on Python 3.4+/XP).

Typical flow:
    engine = GCAnalysisEngine(method)
    engine.load_calibration(cal_data)
    engine.load_library(library)      # optional — for unknown identification

    # Feed raw detector signal (voltage vs time)
    engine.start_run()
    for t, voltage in detector_stream:
        engine.add_point(t, voltage)
    result = engine.finish_run()
    # result = {components: {Methane: {area, area_pct, conc, rt, ri, ...}, ...},
    #           unknown_peaks: [{label, rt, ri, candidates, ...}, ...]}
"""

import bisect
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('GCNode.Analysis')


# ======================================================================
# Configuration dataclasses
# ======================================================================

@dataclass
class PeakWindow:
    """Retention time window for a known component."""
    name: str
    rt_expected: float          # Expected retention time (seconds)
    rt_tolerance: float = 2.0   # +/- window (seconds)
    response_factor: float = 1.0  # RF for area -> concentration
    unit: str = 'mol%'
    min_area: float = 0.0       # Minimum area to report (noise filter)

    @property
    def rt_min(self) -> float:
        return self.rt_expected - self.rt_tolerance

    @property
    def rt_max(self) -> float:
        return self.rt_expected + self.rt_tolerance

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'PeakWindow':
        return cls(
            name=name,
            rt_expected=float(data.get('rt_expected', 0)),
            rt_tolerance=float(data.get('rt_tolerance', 2.0)),
            response_factor=float(data.get('response_factor', 1.0)),
            unit=data.get('unit', 'mol%'),
            min_area=float(data.get('min_area', 0.0)),
        )


@dataclass
class ReferenceStandard:
    """N-alkane (or other homolog) retention time reference for RI calculation.

    Retention Index uses a series of reference compounds with known carbon
    numbers. Typically n-alkanes (C5-C40) injected under the same conditions.
    """
    carbon_number: int      # e.g., 5 for pentane, 10 for decane
    retention_time: float   # Measured RT under current conditions (seconds)
    name: str = ''          # Optional compound name (e.g., "n-Pentane")

    def __post_init__(self):
        if not self.name:
            self.name = f"C{self.carbon_number}"


@dataclass
class LibraryEntry:
    """A compound entry in the peak identification library.

    Compounds are matched by retention index (RI), which is more robust
    than retention time since RI is largely independent of column length,
    film thickness, and (for linear RI) temperature program rate.
    """
    name: str
    retention_index: float          # Expected RI (e.g., 600 for hexane)
    ri_tolerance: float = 10.0      # +/- RI units for matching
    cas_number: str = ''            # CAS registry number
    formula: str = ''               # Molecular formula
    molecular_weight: float = 0.0   # MW (g/mol)
    category: str = ''              # e.g., "alkane", "aromatic", "sulfur"
    response_factor: float = 1.0    # Default RF if no calibration exists
    unit: str = 'mol%'

    @property
    def ri_min(self) -> float:
        return self.retention_index - self.ri_tolerance

    @property
    def ri_max(self) -> float:
        return self.retention_index + self.ri_tolerance

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LibraryEntry':
        return cls(
            name=data.get('name', ''),
            retention_index=float(data.get('retention_index', 0)),
            ri_tolerance=float(data.get('ri_tolerance', 10.0)),
            cas_number=data.get('cas_number', ''),
            formula=data.get('formula', ''),
            molecular_weight=float(data.get('molecular_weight', 0)),
            category=data.get('category', ''),
            response_factor=float(data.get('response_factor', 1.0)),
            unit=data.get('unit', 'mol%'),
        )


class PeakLibrary:
    """Compound library for RI-based peak identification.

    Used to tentatively identify unknown peaks by matching their
    calculated retention index against library entries.

    Usage:
        library = PeakLibrary()
        library.add_entry(LibraryEntry(name='Benzene', retention_index=653))
        library.add_entry(LibraryEntry(name='Toluene', retention_index=764))
        library.load_json('compounds.json')

        candidates = library.find_candidates(ri=658, max_results=3)
        # [{'name': 'Benzene', 'ri': 653, 'ri_delta': 5.0, 'confidence': 0.95}, ...]
    """

    def __init__(self):
        self._entries: List[LibraryEntry] = []
        # Sorted RI values for fast bisect lookup
        self._sorted_ri: List[float] = []
        self._sorted_entries: List[LibraryEntry] = []

    def add_entry(self, entry: LibraryEntry):
        """Add a compound to the library."""
        self._entries.append(entry)
        self._rebuild_index()

    def add_entries(self, entries: List[LibraryEntry]):
        """Add multiple compounds."""
        self._entries.extend(entries)
        self._rebuild_index()

    def load_json(self, path: str):
        """Load library entries from a JSON file.

        Expected format: {"compounds": [{"name": ..., "retention_index": ...}, ...]}
        """
        with open(path, 'r') as f:
            data = json.load(f)
        for entry_data in data.get('compounds', []):
            self._entries.append(LibraryEntry.from_dict(entry_data))
        self._rebuild_index()

    def load_dict(self, data: Dict[str, Any]):
        """Load library entries from a dict (e.g., from MQTT config push)."""
        for entry_data in data.get('compounds', []):
            self._entries.append(LibraryEntry.from_dict(entry_data))
        self._rebuild_index()

    def find_candidates(
        self, ri: float, max_results: int = 5, max_ri_delta: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Find library entries matching a retention index.

        Args:
            ri: Calculated retention index of the unknown peak.
            max_results: Maximum number of candidates to return.
            max_ri_delta: Maximum RI difference to consider a match.

        Returns:
            List of candidate dicts sorted by confidence (best first):
            [{'name', 'ri', 'ri_delta', 'confidence', 'formula', 'category'}, ...]
        """
        if not self._sorted_entries:
            return []

        candidates = []
        for entry in self._sorted_entries:
            delta = abs(ri - entry.retention_index)
            if delta <= max_ri_delta:
                # Confidence: 1.0 at exact match, 0.0 at max_ri_delta
                confidence = max(0.0, 1.0 - delta / max_ri_delta)
                candidates.append({
                    'name': entry.name,
                    'ri': entry.retention_index,
                    'ri_delta': round(delta, 1),
                    'confidence': round(confidence, 3),
                    'formula': entry.formula,
                    'category': entry.category,
                    'cas_number': entry.cas_number,
                    'molecular_weight': entry.molecular_weight,
                    'response_factor': entry.response_factor,
                    'unit': entry.unit,
                })

        # Sort by confidence (highest first)
        candidates.sort(key=lambda c: c['confidence'], reverse=True)
        return candidates[:max_results]

    def get_best_match(self, ri: float) -> Optional[Dict[str, Any]]:
        """Get the single best library match for a retention index.

        Returns the best candidate if confidence >= 0.5, else None.
        """
        candidates = self.find_candidates(ri, max_results=1)
        if candidates and candidates[0]['confidence'] >= 0.5:
            return candidates[0]
        return None

    @property
    def size(self) -> int:
        return len(self._entries)

    def _rebuild_index(self):
        """Rebuild the sorted index for fast bisect lookup."""
        self._sorted_entries = sorted(
            self._entries, key=lambda e: e.retention_index,
        )
        self._sorted_ri = [e.retention_index for e in self._sorted_entries]


@dataclass
class CalibrationPoint:
    """Single calibration point: known concentration -> measured area."""
    concentration: float
    area: float


@dataclass
class ComponentCalibration:
    """Multi-point calibration for one component."""
    name: str
    points: List[CalibrationPoint] = field(default_factory=list)
    cal_type: str = 'linear'  # 'response_factor', 'linear', 'quadratic'

    # Cached fit coefficients (computed on load)
    _coeffs: Optional[List[float]] = field(default=None, repr=False)

    def fit(self):
        """Compute calibration curve coefficients from cal points."""
        if not self.points:
            self._coeffs = None
            return

        if self.cal_type == 'response_factor' or len(self.points) == 1:
            # Single-point: RF = concentration / area
            p = self.points[0]
            if p.area > 0:
                self._coeffs = [p.concentration / p.area]
            else:
                self._coeffs = [1.0]

        elif self.cal_type == 'linear' or len(self.points) == 2:
            # Linear least squares: conc = a * area + b
            self._coeffs = _linear_fit(
                [p.area for p in self.points],
                [p.concentration for p in self.points],
            )

        elif self.cal_type == 'quadratic' and len(self.points) >= 3:
            # Quadratic: conc = a * area^2 + b * area + c
            self._coeffs = _quadratic_fit(
                [p.area for p in self.points],
                [p.concentration for p in self.points],
            )
        else:
            # Fallback to linear
            self._coeffs = _linear_fit(
                [p.area for p in self.points],
                [p.concentration for p in self.points],
            )

    def area_to_concentration(self, area: float) -> float:
        """Convert peak area to concentration using calibration curve."""
        if self._coeffs is None:
            self.fit()

        if self._coeffs is None:
            return area  # No calibration — return raw area

        if self.cal_type == 'response_factor' or len(self._coeffs) == 1:
            return area * self._coeffs[0]

        elif len(self._coeffs) == 2:
            # Linear: conc = a * area + b
            a, b = self._coeffs
            return a * area + b

        elif len(self._coeffs) == 3:
            # Quadratic: conc = a * area^2 + b * area + c
            a, b, c = self._coeffs
            return a * area * area + b * area + c

        return area

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ComponentCalibration':
        points = []
        for pt in data.get('points', []):
            points.append(CalibrationPoint(
                concentration=float(pt.get('concentration', 0)),
                area=float(pt.get('area', 0)),
            ))
        cal = cls(
            name=name,
            points=points,
            cal_type=data.get('cal_type', 'linear'),
        )
        cal.fit()
        return cal


@dataclass
class AnalysisMethod:
    """Complete GC analysis method configuration."""
    name: str = 'default'
    description: str = ''

    # Detector settings
    sample_rate_hz: float = 10.0    # Expected detector sample rate
    baseline_window_s: float = 5.0  # Rolling window for baseline estimation
    noise_threshold: float = 0.01   # Minimum signal above baseline to detect peaks

    # Peak detection
    min_peak_height: float = 0.05   # Minimum height above baseline
    min_peak_width_s: float = 0.5   # Minimum peak width (seconds)
    max_peak_width_s: float = 60.0  # Maximum peak width (rejects artifacts)
    peak_slope_threshold: float = 0.001  # Minimum slope to start a peak

    # Component identification
    components: Dict[str, PeakWindow] = field(default_factory=dict)

    # Calibration
    calibrations: Dict[str, ComponentCalibration] = field(default_factory=dict)

    # Normalization
    normalize_areas: bool = True    # Report area% (sum to 100)

    # Valve/port settings
    active_port: int = 1            # Current valve port (for multi-stream)
    port_labels: Dict[int, str] = field(default_factory=dict)  # {1: "Sample", 2: "Cal Gas"}

    # Run timing
    run_duration_s: float = 300.0   # Expected run duration (5 min default)
    inject_delay_s: float = 0.0     # Delay after inject before analysis starts

    # Retention Index settings
    ri_references: List[ReferenceStandard] = field(default_factory=list)
    ri_mode: str = 'linear'         # 'kovats' (isothermal) or 'linear' (temp programmed)
    report_unknowns: bool = True    # Include unidentified peaks in results
    unknown_min_area_pct: float = 0.1  # Min area% to report an unknown peak

    # System suitability settings
    dead_time_s: float = 0.0        # Column dead time t0 (for capacity factor k')

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisMethod':
        components = {}
        for name, comp_data in data.get('components', {}).items():
            components[name] = PeakWindow.from_dict(name, comp_data)

        calibrations = {}
        for name, cal_data in data.get('calibrations', {}).items():
            calibrations[name] = ComponentCalibration.from_dict(name, cal_data)

        port_labels = {}
        for port_str, label in data.get('port_labels', {}).items():
            port_labels[int(port_str)] = label

        ri_references = []
        for ref_data in data.get('ri_references', []):
            ri_references.append(ReferenceStandard(
                carbon_number=int(ref_data.get('carbon_number', 0)),
                retention_time=float(ref_data.get('retention_time', 0)),
                name=ref_data.get('name', ''),
            ))

        return cls(
            name=data.get('name', 'default'),
            description=data.get('description', ''),
            sample_rate_hz=float(data.get('sample_rate_hz', 10.0)),
            baseline_window_s=float(data.get('baseline_window_s', 5.0)),
            noise_threshold=float(data.get('noise_threshold', 0.01)),
            min_peak_height=float(data.get('min_peak_height', 0.05)),
            min_peak_width_s=float(data.get('min_peak_width_s', 0.5)),
            max_peak_width_s=float(data.get('max_peak_width_s', 60.0)),
            peak_slope_threshold=float(data.get('peak_slope_threshold', 0.001)),
            components=components,
            calibrations=calibrations,
            normalize_areas=data.get('normalize_areas', True),
            active_port=int(data.get('active_port', 1)),
            port_labels=port_labels,
            run_duration_s=float(data.get('run_duration_s', 300.0)),
            inject_delay_s=float(data.get('inject_delay_s', 0.0)),
            ri_references=ri_references,
            ri_mode=data.get('ri_mode', 'linear'),
            report_unknowns=data.get('report_unknowns', True),
            unknown_min_area_pct=float(data.get('unknown_min_area_pct', 0.1)),
            dead_time_s=float(data.get('dead_time_s', 0.0)),
        )

    @classmethod
    def from_json_file(cls, path: str) -> 'AnalysisMethod':
        with open(path, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)


# ======================================================================
# Peak detection result
# ======================================================================

@dataclass
class DetectedPeak:
    """A single detected chromatographic peak."""
    start_time: float       # Peak start (seconds)
    apex_time: float        # Peak apex / retention time (seconds)
    end_time: float         # Peak end (seconds)
    apex_height: float      # Height above baseline at apex
    area: float             # Integrated area (trapezoidal)
    baseline_start: float   # Baseline value at start
    baseline_end: float     # Baseline value at end
    width_half: float = 0.0  # Width at half height (seconds)
    asymmetry: float = 1.0  # Peak asymmetry factor (1.0 = symmetric)

    # Identification (filled after matching)
    component_name: str = ''
    identified: bool = False
    identification_method: str = ''  # 'rt_window', 'ri_library', ''

    # Retention index (filled after RI calculation)
    retention_index: float = 0.0

    # Library matching for unknowns
    library_candidates: List[Dict[str, Any]] = field(default_factory=list)

    # Auto-label for unknown peaks
    unknown_label: str = ''

    # System suitability (filled after SST calculation)
    theoretical_plates: float = 0.0   # N (column efficiency)
    usp_tailing: float = 0.0         # USP tailing factor at 5% height
    resolution: float = 0.0          # Resolution vs previous peak
    capacity_factor: float = 0.0     # k' = (tR - t0) / t0

    # Quantification (filled after calibration)
    concentration: float = 0.0
    area_pct: float = 0.0
    unit: str = ''


# ======================================================================
# Main Analysis Engine
# ======================================================================

class GCAnalysisEngine:
    """Process GC chromatogram analysis engine.

    Replaces vendor software for standard process GC applications:
    known components, retention time identification, area normalization.

    Usage:
        method = AnalysisMethod.from_dict({...})
        engine = GCAnalysisEngine(method)

        engine.start_run()
        for t, v in signal:
            engine.add_point(t, v)
        result = engine.finish_run()
    """

    def __init__(self, method: AnalysisMethod):
        self.method = method

        # Raw chromatogram data for current run
        self._times: List[float] = []
        self._values: List[float] = []

        # State
        self._run_active = False
        self._run_start_time = 0.0
        self._run_number = 0

        # Results history
        self._last_result: Optional[Dict[str, Any]] = None

        # Peak library for unknown identification
        self._library: Optional[PeakLibrary] = None

    def load_library(self, library: PeakLibrary):
        """Attach a peak library for RI-based unknown identification."""
        self._library = library
        logger.info(f"Loaded peak library with {library.size} compounds")

    def load_library_json(self, path: str):
        """Load a peak library from a JSON file."""
        self._library = PeakLibrary()
        self._library.load_json(path)
        logger.info(f"Loaded peak library from {path} ({self._library.size} compounds)")

    def load_library_dict(self, data: Dict[str, Any]):
        """Load a peak library from a dict (e.g., from MQTT config push)."""
        self._library = PeakLibrary()
        self._library.load_dict(data)
        logger.info(f"Loaded peak library ({self._library.size} compounds)")

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, port: Optional[int] = None):
        """Begin a new analysis run. Optionally set valve port."""
        self._times.clear()
        self._values.clear()
        self._run_active = True
        self._run_start_time = time.time()
        self._run_number += 1

        if port is not None:
            self.method.active_port = port

        logger.info(
            f"Analysis run #{self._run_number} started "
            f"(port={self.method.active_port}, "
            f"method={self.method.name})"
        )

    def add_point(self, t: float, value: float):
        """Add a raw detector data point.

        Args:
            t: Time in seconds from run start.
            value: Detector signal (voltage, mV, etc.).
        """
        if not self._run_active:
            return

        # Skip points during inject delay
        if t < self.method.inject_delay_s:
            return

        self._times.append(t)
        self._values.append(value)

    def add_points(self, times: List[float], values: List[float]):
        """Add multiple data points at once."""
        for t, v in zip(times, values):
            self.add_point(t, v)

    def finish_run(self) -> Dict[str, Any]:
        """Complete the run and return analysis results.

        Returns:
            Dict with keys:
              - timestamp: ISO timestamp of run
              - run_number: Sequential run counter
              - port: Active valve port
              - port_label: Port label string
              - components: {name: {area, area_pct, concentration, rt, ...}}
              - unidentified_peaks: [{area, rt, ...}]
              - total_area: Sum of all peak areas
              - chromatogram_points: Number of data points
              - method: Method name
              - metadata: Additional info
        """
        self._run_active = False

        if len(self._times) < 10:
            logger.warning(f"Run #{self._run_number}: insufficient data ({len(self._times)} points)")
            return self._empty_result()

        # 1. Baseline correction
        baseline = self._estimate_baseline()

        # 2. Peak detection
        peaks = self._detect_peaks(baseline)

        # 3. Peak integration + asymmetry
        for peak in peaks:
            peak.area = self._integrate_peak(peak, baseline)
            peak.asymmetry = self._calc_asymmetry(peak, baseline)

        # 3b. System suitability metrics (USP <621>)
        self._calc_system_suitability(peaks, baseline)

        # 4. Component identification (known RT windows)
        self._identify_peaks(peaks)

        # 5. Retention index calculation (for all peaks)
        self._calc_retention_indices(peaks)

        # 6. Library matching for unknowns
        self._match_unknowns_by_library(peaks)

        # 7. Label remaining unknowns
        self._label_unknowns(peaks)

        # 8. Calibration / quantification
        self._quantify_peaks(peaks)

        # 9. Area normalization
        if self.method.normalize_areas:
            self._normalize_areas(peaks)

        # 10. Build result
        result = self._build_result(peaks)
        self._last_result = result

        identified = sum(1 for p in peaks if p.identified)
        unknown_count = sum(1 for p in peaks if not p.identified)
        logger.info(
            f"Run #{self._run_number} complete: "
            f"{len(peaks)} peaks, {identified} identified, "
            f"{unknown_count} unknown, {len(self._times)} points"
        )

        return result

    # ------------------------------------------------------------------
    # 1. Baseline estimation
    # ------------------------------------------------------------------

    def _estimate_baseline(self) -> List[float]:
        """Estimate baseline using rolling minimum + linear interpolation.

        Uses a sliding window to find local minima, then interpolates
        between them to create a smooth baseline estimate.
        """
        n = len(self._values)
        if n == 0:
            return []

        # Window size in samples
        dt = (self._times[-1] - self._times[0]) / max(n - 1, 1)
        window = max(1, int(self.method.baseline_window_s / max(dt, 0.001)))

        # Find local minima in each window
        anchor_times = []
        anchor_values = []

        for i in range(0, n, window):
            end = min(i + window, n)
            segment = self._values[i:end]
            min_val = min(segment)
            min_idx = i + segment.index(min_val)
            anchor_times.append(self._times[min_idx])
            anchor_values.append(min_val)

        # Ensure we have anchors at start and end
        if anchor_times[0] > self._times[0]:
            anchor_times.insert(0, self._times[0])
            anchor_values.insert(0, self._values[0])
        if anchor_times[-1] < self._times[-1]:
            anchor_times.append(self._times[-1])
            anchor_values.append(self._values[-1])

        # Interpolate baseline at each data point
        baseline = []
        for t in self._times:
            # Find surrounding anchors
            idx = bisect.bisect_right(anchor_times, t) - 1
            idx = max(0, min(idx, len(anchor_times) - 2))

            t0 = anchor_times[idx]
            t1 = anchor_times[idx + 1]
            v0 = anchor_values[idx]
            v1 = anchor_values[idx + 1]

            # Linear interpolation
            if t1 > t0:
                frac = (t - t0) / (t1 - t0)
                baseline.append(v0 + frac * (v1 - v0))
            else:
                baseline.append(v0)

        return baseline

    # ------------------------------------------------------------------
    # 2. Peak detection
    # ------------------------------------------------------------------

    def _detect_peaks(self, baseline: List[float]) -> List[DetectedPeak]:
        """Detect peaks using slope analysis and height thresholds.

        Algorithm:
          1. Compute baseline-corrected signal
          2. Find regions where signal exceeds noise threshold
          3. Within each region, find the apex (maximum)
          4. Determine start/end by slope reversal or return to baseline
          5. Filter by height and width constraints
        """
        n = len(self._values)
        if n < 3:
            return []

        # Baseline-corrected signal
        corrected = [self._values[i] - baseline[i] for i in range(n)]

        peaks = []
        i = 0

        while i < n - 1:
            # Find peak start: signal rises above noise threshold
            if corrected[i] < self.method.noise_threshold:
                i += 1
                continue

            # We're above threshold — find the peak region
            start_idx = i

            # Walk back to find true start (where slope first goes positive)
            while start_idx > 0 and corrected[start_idx - 1] > 0:
                start_idx -= 1

            # Find apex (maximum in this region)
            apex_idx = i
            apex_val = corrected[i]

            j = i + 1
            while j < n and corrected[j] > self.method.noise_threshold * 0.5:
                if corrected[j] > apex_val:
                    apex_idx = j
                    apex_val = corrected[j]
                j += 1

            end_idx = min(j, n - 1)

            # Validate peak
            peak_width_s = self._times[end_idx] - self._times[start_idx]
            peak_height = apex_val

            if (peak_height >= self.method.min_peak_height and
                    peak_width_s >= self.method.min_peak_width_s and
                    peak_width_s <= self.method.max_peak_width_s):

                # Calculate width at half height
                half_height = apex_val / 2.0
                whh = self._width_at_height(start_idx, end_idx, corrected, half_height)

                peaks.append(DetectedPeak(
                    start_time=self._times[start_idx],
                    apex_time=self._times[apex_idx],
                    end_time=self._times[end_idx],
                    apex_height=peak_height,
                    area=0.0,  # Computed in integration step
                    baseline_start=baseline[start_idx],
                    baseline_end=baseline[end_idx],
                    width_half=whh,
                ))

            # Move past this peak
            i = end_idx + 1

        return peaks

    def _width_at_height(self, start: int, end: int,
                         corrected: List[float], height: float) -> float:
        """Calculate peak width at a given height above baseline."""
        # Find left crossing
        left_t = self._times[start]
        for i in range(start, end):
            if corrected[i] >= height:
                if i > start and corrected[i - 1] < height:
                    # Interpolate
                    frac = (height - corrected[i - 1]) / max(corrected[i] - corrected[i - 1], 1e-10)
                    left_t = self._times[i - 1] + frac * (self._times[i] - self._times[i - 1])
                else:
                    left_t = self._times[i]
                break

        # Find right crossing
        right_t = self._times[end]
        for i in range(end, start, -1):
            if corrected[i] >= height:
                if i < end and corrected[i + 1] < height:
                    frac = (height - corrected[i + 1]) / max(corrected[i] - corrected[i + 1], 1e-10)
                    right_t = self._times[i + 1] - frac * (self._times[i + 1] - self._times[i])
                else:
                    right_t = self._times[i]
                break

        return max(0.0, right_t - left_t)

    # ------------------------------------------------------------------
    # 3. Peak integration
    # ------------------------------------------------------------------

    def _integrate_peak(self, peak: DetectedPeak, baseline: List[float]) -> float:
        """Integrate peak area using trapezoidal rule with baseline subtraction.

        The baseline under the peak is linearly interpolated between
        the peak start and end baseline values (valley-to-valley).
        """
        # Find index range for this peak
        start_idx = bisect.bisect_left(self._times, peak.start_time)
        end_idx = bisect.bisect_right(self._times, peak.end_time)

        if end_idx <= start_idx + 1:
            return 0.0

        # Linear baseline under the peak (start to end)
        bl_start = peak.baseline_start
        bl_end = peak.baseline_end
        peak_duration = peak.end_time - peak.start_time

        area = 0.0
        for i in range(start_idx, end_idx - 1):
            t0 = self._times[i]
            t1 = self._times[i + 1]
            dt = t1 - t0

            # Baseline at each point (linear interpolation under peak)
            if peak_duration > 0:
                frac0 = (t0 - peak.start_time) / peak_duration
                frac1 = (t1 - peak.start_time) / peak_duration
            else:
                frac0 = frac1 = 0.0

            bl0 = bl_start + frac0 * (bl_end - bl_start)
            bl1 = bl_start + frac1 * (bl_end - bl_start)

            # Corrected values
            v0 = max(0.0, self._values[i] - bl0)
            v1 = max(0.0, self._values[i + 1] - bl1)

            # Trapezoidal rule
            area += 0.5 * (v0 + v1) * dt

        return area

    # ------------------------------------------------------------------
    # 4. Component identification
    # ------------------------------------------------------------------

    def _identify_peaks(self, peaks: List[DetectedPeak]):
        """Match detected peaks to known components by retention time."""
        # Sort components by retention time for deterministic matching
        components = sorted(
            self.method.components.values(),
            key=lambda c: c.rt_expected,
        )

        # Track which components have been matched (one peak per component)
        matched_components = set()

        # Sort peaks by area (largest first) so the biggest peak gets
        # priority when two peaks fall in the same RT window
        sorted_peaks = sorted(peaks, key=lambda p: p.area, reverse=True)

        for peak in sorted_peaks:
            best_match = None
            best_distance = float('inf')

            for comp in components:
                if comp.name in matched_components:
                    continue

                # Check if peak apex falls within the RT window
                if comp.rt_min <= peak.apex_time <= comp.rt_max:
                    distance = abs(peak.apex_time - comp.rt_expected)
                    if distance < best_distance:
                        best_distance = distance
                        best_match = comp

            if best_match is not None:
                # Check minimum area threshold
                if peak.area >= best_match.min_area:
                    peak.component_name = best_match.name
                    peak.identified = True
                    peak.identification_method = 'rt_window'
                    peak.unit = best_match.unit
                    matched_components.add(best_match.name)

    # ------------------------------------------------------------------
    # 4b. Peak asymmetry
    # ------------------------------------------------------------------

    def _calc_asymmetry(self, peak: DetectedPeak, baseline: List[float]) -> float:
        """Calculate peak asymmetry factor at 10% of peak height.

        Asymmetry = B / A, where A is the distance from the leading edge
        to the apex, and B is from the apex to the trailing edge,
        both measured at 10% height.

        Returns:
            Asymmetry factor. 1.0 = symmetric, >1.0 = tailing, <1.0 = fronting.
        """
        target_height = peak.apex_height * 0.1  # 10% of peak height

        start_idx = bisect.bisect_left(self._times, peak.start_time)
        end_idx = bisect.bisect_right(self._times, peak.end_time)
        apex_idx = bisect.bisect_left(self._times, peak.apex_time)

        if end_idx <= start_idx + 2 or apex_idx <= start_idx or apex_idx >= end_idx:
            return 1.0

        # Baseline-corrected values in peak region
        corrected = []
        for i in range(start_idx, end_idx):
            bl = baseline[i] if i < len(baseline) else 0.0
            corrected.append(max(0.0, self._values[i] - bl))

        apex_local = apex_idx - start_idx
        if apex_local <= 0 or apex_local >= len(corrected) - 1:
            return 1.0

        # Find left crossing at 10% height (leading edge -> apex)
        left_t = self._times[start_idx]
        for i in range(apex_local, 0, -1):
            if corrected[i] >= target_height > corrected[i - 1]:
                # Interpolate
                dv = corrected[i] - corrected[i - 1]
                if dv > 1e-10:
                    frac = (target_height - corrected[i - 1]) / dv
                    gi = start_idx + i - 1
                    left_t = self._times[gi] + frac * (self._times[gi + 1] - self._times[gi])
                else:
                    left_t = self._times[start_idx + i]
                break

        # Find right crossing at 10% height (apex -> trailing edge)
        right_t = self._times[min(end_idx - 1, len(self._times) - 1)]
        for i in range(apex_local, len(corrected) - 1):
            if corrected[i] >= target_height > corrected[i + 1]:
                dv = corrected[i] - corrected[i + 1]
                if dv > 1e-10:
                    frac = (target_height - corrected[i + 1]) / dv
                    gi = start_idx + i
                    right_t = self._times[gi + 1] - frac * (self._times[gi + 1] - self._times[gi])
                else:
                    right_t = self._times[start_idx + i]
                break

        a_dist = peak.apex_time - left_t   # Leading edge to apex
        b_dist = right_t - peak.apex_time   # Apex to trailing edge

        if a_dist <= 0:
            return 1.0

        return b_dist / a_dist

    # ------------------------------------------------------------------
    # 4c. System suitability testing (USP <621> / EP 2.2.46)
    # ------------------------------------------------------------------

    def _calc_system_suitability(self, peaks: List[DetectedPeak],
                                  baseline: List[float]):
        """Calculate system suitability metrics for all detected peaks.

        Metrics per USP <621>:
          - Theoretical plates (N): column efficiency
          - USP tailing factor (T): peak symmetry at 5% height
          - Resolution (R): separation between adjacent peaks
          - Capacity factor (k'): retention relative to dead time
        """
        # Sort peaks by retention time for resolution calculation
        sorted_peaks = sorted(peaks, key=lambda p: p.apex_time)

        for i, peak in enumerate(sorted_peaks):
            # Theoretical plates: N = 5.545 * (tR / W_half)^2
            if peak.width_half > 0:
                peak.theoretical_plates = 5.545 * (
                    peak.apex_time / peak.width_half
                ) ** 2

            # USP tailing factor at 5% height: T = W_0.05 / (2 * f)
            peak.usp_tailing = self._calc_usp_tailing(peak, baseline)

            # Resolution vs previous peak: R = 2(tR2 - tR1) / (W1 + W2)
            if i > 0:
                prev = sorted_peaks[i - 1]
                w1 = prev.end_time - prev.start_time  # Base width
                w2 = peak.end_time - peak.start_time
                if (w1 + w2) > 0:
                    peak.resolution = (
                        2.0 * (peak.apex_time - prev.apex_time) / (w1 + w2)
                    )

            # Capacity factor: k' = (tR - t0) / t0
            t0 = self.method.dead_time_s
            if t0 > 0:
                peak.capacity_factor = (peak.apex_time - t0) / t0

    def _calc_usp_tailing(self, peak: DetectedPeak,
                           baseline: List[float]) -> float:
        """Calculate USP tailing factor at 5% of peak height.

        T = W_0.05 / (2 * f)
        Where:
          W_0.05 = peak width at 5% height
          f = distance from leading edge to apex at 5% height

        Returns 1.0 for a symmetric peak.
        """
        target_height = peak.apex_height * 0.05  # 5% of peak height

        start_idx = bisect.bisect_left(self._times, peak.start_time)
        end_idx = bisect.bisect_right(self._times, peak.end_time)
        apex_idx = bisect.bisect_left(self._times, peak.apex_time)

        if end_idx <= start_idx + 2 or apex_idx <= start_idx or apex_idx >= end_idx:
            return 1.0

        # Baseline-corrected values in peak region
        corrected = []
        for i in range(start_idx, end_idx):
            bl = baseline[i] if i < len(baseline) else 0.0
            corrected.append(max(0.0, self._values[i] - bl))

        apex_local = apex_idx - start_idx
        if apex_local <= 0 or apex_local >= len(corrected) - 1:
            return 1.0

        # Find left crossing at 5% height
        left_t = self._times[start_idx]
        for i in range(apex_local, 0, -1):
            if corrected[i] >= target_height > corrected[i - 1]:
                dv = corrected[i] - corrected[i - 1]
                if dv > 1e-10:
                    frac = (target_height - corrected[i - 1]) / dv
                    gi = start_idx + i - 1
                    left_t = self._times[gi] + frac * (self._times[gi + 1] - self._times[gi])
                else:
                    left_t = self._times[start_idx + i]
                break

        # Find right crossing at 5% height
        right_t = self._times[min(end_idx - 1, len(self._times) - 1)]
        for i in range(apex_local, len(corrected) - 1):
            if corrected[i] >= target_height > corrected[i + 1]:
                dv = corrected[i] - corrected[i + 1]
                if dv > 1e-10:
                    frac = (target_height - corrected[i + 1]) / dv
                    gi = start_idx + i
                    right_t = self._times[gi + 1] - frac * (self._times[gi + 1] - self._times[gi])
                else:
                    right_t = self._times[start_idx + i]
                break

        w_005 = right_t - left_t   # Full width at 5%
        f_dist = peak.apex_time - left_t  # Leading edge to apex at 5%

        if f_dist <= 0 or w_005 <= 0:
            return 1.0

        return w_005 / (2.0 * f_dist)

    # ------------------------------------------------------------------
    # 5. Retention Index calculation
    # ------------------------------------------------------------------

    def _calc_retention_indices(self, peaks: List[DetectedPeak]):
        """Calculate retention index for all detected peaks.

        Uses n-alkane reference standards from the method configuration.
        Supports Kovats (isothermal) and Linear (temperature programmed) modes.

        Kovats RI (isothermal):
            RI = 100 * [n + (log(tR_x) - log(tR_n)) / (log(tR_n+1) - log(tR_n))]

        Linear RI (temperature programmed):
            RI = 100 * [n + (tR_x - tR_n) / (tR_n+1 - tR_n)]

        Where:
            tR_x = retention time of unknown
            tR_n, tR_n+1 = retention times of bracketing n-alkanes
            n = carbon number of the earlier eluting alkane
        """
        refs = self.method.ri_references
        if len(refs) < 2:
            return  # Need at least 2 reference points

        # Sort references by retention time
        refs_sorted = sorted(refs, key=lambda r: r.retention_time)

        for peak in peaks:
            ri = self._calc_single_ri(peak.apex_time, refs_sorted)
            if ri is not None:
                peak.retention_index = ri

    def _calc_single_ri(
        self, rt: float, refs: List[ReferenceStandard],
    ) -> Optional[float]:
        """Calculate retention index for a single retention time.

        Args:
            rt: Retention time in seconds.
            refs: Sorted list of reference standards.

        Returns:
            Retention index value, or None if RT is outside reference range.
        """
        # Find bracketing references
        if rt < refs[0].retention_time or rt > refs[-1].retention_time:
            # Extrapolation: use nearest two references
            if rt < refs[0].retention_time and len(refs) >= 2:
                lower, upper = refs[0], refs[1]
            elif rt > refs[-1].retention_time and len(refs) >= 2:
                lower, upper = refs[-2], refs[-1]
            else:
                return None
        else:
            # Interpolation: find bracketing pair
            lower = refs[0]
            upper = refs[1]
            for i in range(len(refs) - 1):
                if refs[i].retention_time <= rt <= refs[i + 1].retention_time:
                    lower = refs[i]
                    upper = refs[i + 1]
                    break

        rt_lower = lower.retention_time
        rt_upper = upper.retention_time
        n_lower = lower.carbon_number

        if rt_upper <= rt_lower:
            return None

        if self.method.ri_mode == 'kovats':
            # Kovats index (isothermal): uses log retention times
            # Guard against non-positive values
            if rt <= 0 or rt_lower <= 0 or rt_upper <= 0:
                return None
            log_rt = math.log(rt)
            log_lower = math.log(rt_lower)
            log_upper = math.log(rt_upper)
            if abs(log_upper - log_lower) < 1e-10:
                return None
            ri = 100.0 * (n_lower + (log_rt - log_lower) / (log_upper - log_lower))
        else:
            # Linear RI (temperature programmed): uses raw retention times
            ri = 100.0 * (n_lower + (rt - rt_lower) / (rt_upper - rt_lower))

        return round(ri, 1)

    # ------------------------------------------------------------------
    # 6. Library matching for unknowns
    # ------------------------------------------------------------------

    def _match_unknowns_by_library(self, peaks: List[DetectedPeak]):
        """Match unidentified peaks against the peak library using RI.

        For peaks already identified by RT window matching, this step
        is skipped. For unidentified peaks with a calculated RI, we
        search the library for candidate compounds.

        If a single high-confidence match is found (confidence >= 0.7),
        the peak is tentatively identified.
        """
        if self._library is None or self._library.size == 0:
            return

        for peak in peaks:
            if peak.identified:
                continue  # Already matched by RT window
            if peak.retention_index <= 0:
                continue  # No RI calculated

            # Find candidates from library
            candidates = self._library.find_candidates(
                ri=peak.retention_index,
                max_results=5,
                max_ri_delta=30.0,
            )

            peak.library_candidates = candidates

            # Auto-identify if single strong match
            if len(candidates) == 1 and candidates[0]['confidence'] >= 0.7:
                match = candidates[0]
                peak.component_name = match['name']
                peak.identified = True
                peak.identification_method = 'ri_library'
                peak.unit = match.get('unit', 'mol%')
                logger.debug(
                    f"RI library match: RT={peak.apex_time:.1f}s "
                    f"RI={peak.retention_index:.0f} -> {match['name']} "
                    f"(confidence={match['confidence']:.2f})"
                )
            elif len(candidates) >= 2:
                # Multiple candidates — check if top one is clearly best
                if (candidates[0]['confidence'] >= 0.8 and
                        candidates[0]['confidence'] - candidates[1]['confidence'] >= 0.3):
                    match = candidates[0]
                    peak.component_name = match['name']
                    peak.identified = True
                    peak.identification_method = 'ri_library'
                    peak.unit = match.get('unit', 'mol%')

    # ------------------------------------------------------------------
    # 6b. Label remaining unknowns
    # ------------------------------------------------------------------

    def _label_unknowns(self, peaks: List[DetectedPeak]):
        """Assign auto-labels to peaks that remain unidentified.

        Labels are like 'Unknown-1', 'Unknown-2', etc., ordered by
        retention time. Includes RI in label if available.
        """
        unknown_num = 0
        for peak in sorted(peaks, key=lambda p: p.apex_time):
            if peak.identified:
                continue
            unknown_num += 1
            if peak.retention_index > 0:
                peak.unknown_label = f"Unknown-{unknown_num} (RI={peak.retention_index:.0f})"
            else:
                peak.unknown_label = f"Unknown-{unknown_num} (RT={peak.apex_time:.1f}s)"

    # ------------------------------------------------------------------
    # 7. Quantification
    # ------------------------------------------------------------------

    def _quantify_peaks(self, peaks: List[DetectedPeak]):
        """Apply calibration to convert peak areas to concentrations."""
        for peak in peaks:
            if not peak.identified:
                continue

            name = peak.component_name

            # Check for multi-point calibration
            if name in self.method.calibrations:
                cal = self.method.calibrations[name]
                peak.concentration = cal.area_to_concentration(peak.area)

            # Fall back to simple response factor from component config
            elif name in self.method.components:
                rf = self.method.components[name].response_factor
                peak.concentration = peak.area * rf

            # Library-matched peaks: use library response factor
            elif peak.identification_method == 'ri_library' and peak.library_candidates:
                rf = peak.library_candidates[0].get('response_factor', 1.0)
                peak.concentration = peak.area * rf

            else:
                peak.concentration = peak.area

    # ------------------------------------------------------------------
    # 6. Area normalization
    # ------------------------------------------------------------------

    def _normalize_areas(self, peaks: List[DetectedPeak]):
        """Compute area% for each peak (all peaks sum to 100%)."""
        total_area = sum(p.area for p in peaks)

        if total_area <= 0:
            return

        for peak in peaks:
            peak.area_pct = (peak.area / total_area) * 100.0

    # ------------------------------------------------------------------
    # 7. Build result
    # ------------------------------------------------------------------

    def _build_result(self, peaks: List[DetectedPeak]) -> Dict[str, Any]:
        """Build the final analysis result dictionary."""
        from datetime import datetime

        total_area = sum(p.area for p in peaks)

        # Identified components (by RT window or RI library)
        components = {}
        for peak in peaks:
            if peak.identified:
                comp_data = {
                    'value': peak.concentration,
                    'area': peak.area,
                    'area_pct': round(peak.area_pct, 4),
                    'concentration': round(peak.concentration, 6),
                    'retention_time': round(peak.apex_time, 3),
                    'retention_index': round(peak.retention_index, 1) if peak.retention_index > 0 else None,
                    'peak_height': round(peak.apex_height, 6),
                    'peak_width': round(peak.width_half, 3),
                    'peak_start': round(peak.start_time, 3),
                    'peak_end': round(peak.end_time, 3),
                    'asymmetry': round(peak.asymmetry, 2),
                    'identification_method': peak.identification_method,
                    'unit': peak.unit,
                    'theoretical_plates': round(peak.theoretical_plates, 0) if peak.theoretical_plates > 0 else None,
                    'usp_tailing': round(peak.usp_tailing, 3) if peak.usp_tailing > 0 else None,
                    'resolution': round(peak.resolution, 2) if peak.resolution > 0 else None,
                    'capacity_factor': round(peak.capacity_factor, 2) if peak.capacity_factor > 0 else None,
                }
                # Include library candidates if identified by RI
                if peak.identification_method == 'ri_library' and peak.library_candidates:
                    comp_data['library_confidence'] = peak.library_candidates[0].get('confidence', 0)
                components[peak.component_name] = comp_data

        # Unknown peaks (unidentified, with full characterization)
        unknown_peaks = []
        for peak in sorted(peaks, key=lambda p: p.apex_time):
            if peak.identified:
                continue
            # Filter small unknowns unless report_unknowns is off
            if not self.method.report_unknowns:
                continue
            if peak.area_pct < self.method.unknown_min_area_pct and total_area > 0:
                continue

            unknown_data = {
                'label': peak.unknown_label,
                'area': peak.area,
                'area_pct': round(peak.area_pct, 4),
                'retention_time': round(peak.apex_time, 3),
                'retention_index': round(peak.retention_index, 1) if peak.retention_index > 0 else None,
                'peak_height': round(peak.apex_height, 6),
                'peak_width': round(peak.width_half, 3),
                'peak_start': round(peak.start_time, 3),
                'peak_end': round(peak.end_time, 3),
                'asymmetry': round(peak.asymmetry, 2),
            }
            # Include library candidates if any
            if peak.library_candidates:
                unknown_data['candidates'] = peak.library_candidates[:3]
            unknown_peaks.append(unknown_data)

        port_label = self.method.port_labels.get(
            self.method.active_port,
            f"Port {self.method.active_port}",
        )

        return {
            'timestamp': datetime.now().isoformat(),
            'run_number': self._run_number,
            'port': self.method.active_port,
            'port_label': port_label,
            'components': components,
            'unknown_peaks': unknown_peaks,
            'total_area': total_area,
            'total_peaks': len(peaks),
            'identified_peaks': sum(1 for p in peaks if p.identified),
            'unknown_count': sum(1 for p in peaks if not p.identified),
            'chromatogram_points': len(self._times),
            'method': self.method.name,
            'ri_mode': self.method.ri_mode if self.method.ri_references else None,
            'library_size': self._library.size if self._library else 0,
            'system_suitability': self._build_sst_summary(peaks),
            'metadata': {
                'run_duration_s': self._times[-1] - self._times[0] if self._times else 0,
                'sample_rate_actual': len(self._times) / max(self._times[-1] - self._times[0], 0.001) if len(self._times) > 1 else 0,
                'normalize_areas': self.method.normalize_areas,
                'ri_references': len(self.method.ri_references),
            },
        }

    def _build_sst_summary(self, peaks: List[DetectedPeak]) -> Dict[str, Any]:
        """Build system suitability summary from peak metrics."""
        plates = [p.theoretical_plates for p in peaks if p.theoretical_plates > 0]
        tailings = [p.usp_tailing for p in peaks if p.usp_tailing > 0]
        resolutions = [p.resolution for p in peaks if p.resolution > 0]

        return {
            'min_theoretical_plates': round(min(plates), 0) if plates else None,
            'max_theoretical_plates': round(max(plates), 0) if plates else None,
            'avg_theoretical_plates': round(sum(plates) / len(plates), 0) if plates else None,
            'min_resolution': round(min(resolutions), 2) if resolutions else None,
            'max_usp_tailing': round(max(tailings), 3) if tailings else None,
            'avg_usp_tailing': round(sum(tailings) / len(tailings), 3) if tailings else None,
            'peaks_evaluated': len(peaks),
        }

    def _empty_result(self) -> Dict[str, Any]:
        """Return an empty result when there's insufficient data."""
        from datetime import datetime
        return {
            'timestamp': datetime.now().isoformat(),
            'run_number': self._run_number,
            'port': self.method.active_port,
            'port_label': self.method.port_labels.get(self.method.active_port, ''),
            'components': {},
            'unknown_peaks': [],
            'total_area': 0.0,
            'total_peaks': 0,
            'identified_peaks': 0,
            'unknown_count': 0,
            'chromatogram_points': len(self._times),
            'method': self.method.name,
            'ri_mode': None,
            'library_size': 0,
            'system_suitability': {},
            'metadata': {'error': 'insufficient data'},
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def last_result(self) -> Optional[Dict[str, Any]]:
        return self._last_result

    @property
    def run_number(self) -> int:
        return self._run_number

    @property
    def is_running(self) -> bool:
        return self._run_active

    def get_raw_chromatogram(self) -> Tuple[List[float], List[float]]:
        """Return (times, values) of the current/last run."""
        return list(self._times), list(self._values)


# ======================================================================
# Pure-Python math helpers (no numpy/scipy dependency)
# ======================================================================

def _linear_fit(x: List[float], y: List[float]) -> List[float]:
    """Least-squares linear fit: y = a*x + b.

    Returns [a, b].
    """
    n = len(x)
    if n == 0:
        return [1.0, 0.0]
    if n == 1:
        return [y[0] / max(x[0], 1e-10), 0.0]

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(xi * xi for xi in x)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-15:
        return [1.0, 0.0]

    a = (n * sum_xy - sum_x * sum_y) / denom
    b = (sum_y - a * sum_x) / n

    return [a, b]


def _quadratic_fit(x: List[float], y: List[float]) -> List[float]:
    """Least-squares quadratic fit: y = a*x^2 + b*x + c.

    Returns [a, b, c]. Uses normal equations (no matrix library).
    """
    n = len(x)
    if n < 3:
        coeffs = _linear_fit(x, y)
        return [0.0] + coeffs

    # Build sums for normal equations
    s0 = float(n)
    s1 = sum(x)
    s2 = sum(xi ** 2 for xi in x)
    s3 = sum(xi ** 3 for xi in x)
    s4 = sum(xi ** 4 for xi in x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sx2y = sum(xi ** 2 * yi for xi, yi in zip(x, y))

    # Solve 3x3 system using Cramer's rule
    # [s4 s3 s2] [a]   [sx2y]
    # [s3 s2 s1] [b] = [sxy]
    # [s2 s1 s0] [c]   [sy]

    det = _det3x3(s4, s3, s2, s3, s2, s1, s2, s1, s0)
    if abs(det) < 1e-15:
        coeffs = _linear_fit(x, y)
        return [0.0] + coeffs

    a = _det3x3(sx2y, s3, s2, sxy, s2, s1, sy, s1, s0) / det
    b = _det3x3(s4, sx2y, s2, s3, sxy, s1, s2, sy, s0) / det
    c = _det3x3(s4, s3, sx2y, s3, s2, sxy, s2, s1, sy) / det

    return [a, b, c]


def _det3x3(a11, a12, a13, a21, a22, a23, a31, a32, a33) -> float:
    """Determinant of a 3x3 matrix."""
    return (a11 * (a22 * a33 - a23 * a32)
            - a12 * (a21 * a33 - a23 * a31)
            + a13 * (a21 * a32 - a22 * a31))
