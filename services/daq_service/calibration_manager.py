#!/usr/bin/env python3
"""
Calibration Manager for NISystem

ISO 17025 calibration traceability:
- Calibration record tracking (certificates, dates, performed by)
- Measurement uncertainty budgets (Type A and Type B)
- Calibration due date monitoring with alerts
- Channel-to-calibration linking
- Calibration verification and as-found/as-left recording

References:
- ISO/IEC 17025:2017 (Testing and Calibration Laboratories)
- GUM (Guide to the Expression of Uncertainty in Measurement)
- ILAC-G24 (Guidelines for Determination of Calibration Intervals)
"""

import json
import math
import uuid
import logging
import threading
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger('CalibrationManager')

# Degrees of freedom sentinel for Type B components (effectively infinite)
INF_DOF = 9999


@dataclass
class UncertaintyComponent:
    """
    A single uncertainty contribution in a measurement uncertainty budget.

    Follows GUM (Guide to the Expression of Uncertainty in Measurement)
    methodology for combining Type A (statistical) and Type B (non-statistical)
    uncertainty components.
    """
    name: str                       # e.g., "Sensor accuracy", "ADC resolution"
    value: float                    # Uncertainty value in engineering units
    type: str = 'B'                 # 'A' (statistical) or 'B' (non-statistical)
    distribution: str = 'normal'    # 'normal', 'rectangular', 'triangular', 'u-shaped'
    divisor: float = 2.0            # Coverage divisor (2.0 for normal k=2, sqrt(3) for rectangular)
    degrees_of_freedom: int = INF_DOF  # For Type A: n-1; for Type B: INF_DOF
    source: str = ''                # Where this value comes from (e.g., "Manufacturer spec sheet")

    @property
    def standard_uncertainty(self) -> float:
        """Standard uncertainty u(x) = value / divisor"""
        if self.divisor == 0:
            return 0.0
        return abs(self.value) / self.divisor

    def to_dict(self) -> dict:
        d = asdict(self)
        d['standard_uncertainty'] = self.standard_uncertainty
        return d

    @staticmethod
    def from_dict(d: dict) -> 'UncertaintyComponent':
        # Remove computed property if present (not a constructor arg)
        d = dict(d)
        d.pop('standard_uncertainty', None)
        return UncertaintyComponent(**d)


@dataclass
class UncertaintyBudget:
    """
    Complete measurement uncertainty budget for a channel.

    Combines multiple uncertainty components using RSS (root sum of squares)
    and applies a coverage factor for expanded uncertainty. Implements the
    Welch-Satterthwaite formula for effective degrees of freedom.
    """
    channel_id: str
    components: List[UncertaintyComponent] = field(default_factory=list)
    coverage_factor: float = 2.0    # k-factor (2.0 for ~95% confidence)
    unit: str = ''
    last_evaluated: str = ''        # ISO timestamp of last evaluation
    evaluated_by: str = ''          # Person who evaluated the budget

    def combined_standard_uncertainty(self) -> float:
        """
        Combined standard uncertainty u_c using RSS (root sum of squares).

        u_c = sqrt(sum(u_i^2)) for all components i
        """
        sum_sq = 0.0
        for comp in self.components:
            u = comp.standard_uncertainty
            sum_sq += u * u
        return math.sqrt(sum_sq)

    def expanded_uncertainty(self) -> float:
        """
        Expanded uncertainty U = k * u_c

        Where k is the coverage factor (typically 2.0 for ~95% confidence).
        """
        return self.combined_standard_uncertainty() * self.coverage_factor

    def effective_degrees_of_freedom(self) -> float:
        """
        Effective degrees of freedom using the Welch-Satterthwaite formula.

        v_eff = u_c^4 / sum(u_i^4 / v_i)

        Where u_c is combined standard uncertainty, u_i is the standard
        uncertainty of component i, and v_i is its degrees of freedom.

        Returns INF_DOF if all components have infinite degrees of freedom
        or if there are no components.
        """
        u_c = self.combined_standard_uncertainty()
        if u_c == 0 or not self.components:
            return float(INF_DOF)

        u_c_4 = u_c ** 4
        denominator = 0.0

        for comp in self.components:
            u_i = comp.standard_uncertainty
            v_i = comp.degrees_of_freedom
            if v_i <= 0:
                v_i = INF_DOF
            u_i_4 = u_i ** 4
            denominator += u_i_4 / v_i

        if denominator == 0:
            return float(INF_DOF)

        v_eff = u_c_4 / denominator
        return min(v_eff, float(INF_DOF))

    def to_dict(self) -> dict:
        return {
            'channel_id': self.channel_id,
            'components': [c.to_dict() for c in self.components],
            'coverage_factor': self.coverage_factor,
            'unit': self.unit,
            'last_evaluated': self.last_evaluated,
            'evaluated_by': self.evaluated_by,
            'combined_standard_uncertainty': self.combined_standard_uncertainty(),
            'expanded_uncertainty': self.expanded_uncertainty(),
            'effective_degrees_of_freedom': self.effective_degrees_of_freedom(),
        }

    @staticmethod
    def from_dict(d: dict) -> 'UncertaintyBudget':
        d = dict(d)
        # Remove computed fields
        d.pop('combined_standard_uncertainty', None)
        d.pop('expanded_uncertainty', None)
        d.pop('effective_degrees_of_freedom', None)
        components = [UncertaintyComponent.from_dict(c) for c in d.pop('components', [])]
        return UncertaintyBudget(components=components, **d)


@dataclass
class CalibrationRecord:
    """
    Complete calibration record for a channel/instrument.

    Tracks ISO 17025 required fields:
    - Calibration identity and traceability
    - As-found / as-left readings
    - Reference standards used
    - Uncertainty of measurement
    - Pass/fail/adjusted result
    """
    record_id: str                          # Unique record ID
    channel_id: str                         # Which channel this calibration applies to
    instrument_id: str = ''                 # Physical instrument serial number or tag
    calibration_date: str = ''              # ISO date of calibration (YYYY-MM-DD)
    next_due_date: str = ''                 # ISO date for next calibration (YYYY-MM-DD)
    certificate_number: str = ''            # Certificate number
    certificate_path: str = ''              # Path to scanned certificate PDF
    performed_by: str = ''                  # Who performed the calibration
    approved_by: str = ''                   # Who approved/reviewed the calibration
    calibration_lab: str = ''               # Name of calibration laboratory
    lab_accreditation: str = ''             # e.g., "A2LA Cert #12345"
    standard_used: str = ''                 # Reference standard description (traceable to NIST/SI)
    standard_certificate: str = ''          # Reference standard's certificate number
    as_found: Dict[str, float] = field(default_factory=dict)    # {test_point: reading}
    as_left: Dict[str, float] = field(default_factory=dict)     # {test_point: reading}
    reference_values: Dict[str, float] = field(default_factory=dict)  # {test_point: true value}
    tolerance: float = 0.0                  # Acceptance tolerance
    tolerance_unit: str = ''                # Unit for tolerance
    result: str = ''                        # 'pass', 'fail', 'adjusted'
    adjustment_made: bool = False           # Whether adjustment was performed
    notes: str = ''                         # Free-text notes
    uncertainty: Optional[UncertaintyBudget] = None  # Measurement uncertainty at cal
    created_at: str = ''                    # ISO timestamp of record creation

    def is_overdue(self) -> bool:
        """Check if calibration is past its due date."""
        if not self.next_due_date:
            return False
        try:
            due = date.fromisoformat(self.next_due_date)
            return date.today() > due
        except (ValueError, TypeError):
            return False

    def days_until_due(self) -> int:
        """
        Number of days until calibration is due.

        Returns negative value if overdue, 0 if due today,
        positive if not yet due.  Returns 0 if no due date set.
        """
        if not self.next_due_date:
            return 0
        try:
            due = date.fromisoformat(self.next_due_date)
            delta = due - date.today()
            return delta.days
        except (ValueError, TypeError):
            return 0

    def max_error(self) -> float:
        """
        Largest absolute error found during as-found verification.

        Computes max(|as_found[pt] - reference_values[pt]|) for all
        common test points.  Returns 0.0 if no data.
        """
        max_err = 0.0
        for pt, found_val in self.as_found.items():
            ref_val = self.reference_values.get(pt)
            if ref_val is not None:
                err = abs(found_val - ref_val)
                if err > max_err:
                    max_err = err
        return max_err

    def to_dict(self) -> dict:
        d = {
            'record_id': self.record_id,
            'channel_id': self.channel_id,
            'instrument_id': self.instrument_id,
            'calibration_date': self.calibration_date,
            'next_due_date': self.next_due_date,
            'certificate_number': self.certificate_number,
            'certificate_path': self.certificate_path,
            'performed_by': self.performed_by,
            'approved_by': self.approved_by,
            'calibration_lab': self.calibration_lab,
            'lab_accreditation': self.lab_accreditation,
            'standard_used': self.standard_used,
            'standard_certificate': self.standard_certificate,
            'as_found': self.as_found,
            'as_left': self.as_left,
            'reference_values': self.reference_values,
            'tolerance': self.tolerance,
            'tolerance_unit': self.tolerance_unit,
            'result': self.result,
            'adjustment_made': self.adjustment_made,
            'notes': self.notes,
            'uncertainty': self.uncertainty.to_dict() if self.uncertainty else None,
            'created_at': self.created_at,
            'is_overdue': self.is_overdue(),
            'days_until_due': self.days_until_due(),
            'max_error': self.max_error(),
        }
        return d

    @staticmethod
    def from_dict(d: dict) -> 'CalibrationRecord':
        d = dict(d)
        # Remove computed fields
        d.pop('is_overdue', None)
        d.pop('days_until_due', None)
        d.pop('max_error', None)
        # Parse nested uncertainty budget
        unc = d.pop('uncertainty', None)
        if unc is not None and isinstance(unc, dict):
            d['uncertainty'] = UncertaintyBudget.from_dict(unc)
        else:
            d['uncertainty'] = None
        return CalibrationRecord(**d)


class CalibrationManager:
    """
    Manages calibration records, uncertainty budgets, and due-date tracking
    for all instrumented channels.

    Thread-safe. Persists state to JSON. Optionally integrates with the
    NISystem audit trail for 21 CFR Part 11 compliance.

    Usage:
        mgr = CalibrationManager(data_dir=Path('data/calibration'))
        rec = CalibrationRecord(
            record_id='CAL-001',
            channel_id='TC_01',
            instrument_id='SN-12345',
            calibration_date='2025-01-15',
            next_due_date='2026-01-15',
            ...
        )
        mgr.add_record(rec)
        overdue = mgr.get_overdue_channels()
    """

    RECORDS_FILENAME = 'calibration_records.json'

    def __init__(self, data_dir: Path, audit_trail=None):
        """
        Args:
            data_dir: Directory for persisting calibration records JSON.
            audit_trail: Optional AuditTrail instance for logging calibration
                         events.  If None, events are only logged via the
                         standard Python logger.
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audit_trail = audit_trail

        self._lock = threading.RLock()

        # record_id -> CalibrationRecord
        self._records: Dict[str, CalibrationRecord] = {}

        # channel_id -> latest record_id (most recent calibration)
        self._channel_map: Dict[str, str] = {}

        # channel_id -> UncertaintyBudget
        self._uncertainty_budgets: Dict[str, UncertaintyBudget] = {}

        self._load()
        logger.info(
            "CalibrationManager initialized: %d records, %d channels mapped, %d uncertainty budgets",
            len(self._records), len(self._channel_map), len(self._uncertainty_budgets)
        )

    # ------------------------------------------------------------------ #
    # Record management
    # ------------------------------------------------------------------ #

    def add_record(self, record: CalibrationRecord) -> str:
        """
        Add a calibration record to the store.

        Updates the channel map so this becomes the latest calibration for
        the record's channel_id.  Persists to disk and logs to the audit
        trail if available.

        Returns:
            The record_id of the stored record.
        """
        with self._lock:
            if not record.record_id:
                record.record_id = f"CAL-{uuid.uuid4().hex[:12].upper()}"

            if not record.created_at:
                record.created_at = datetime.now().isoformat(timespec='seconds')

            self._records[record.record_id] = record

            # Update channel map -- this record is now the latest for its channel
            if record.channel_id:
                existing_id = self._channel_map.get(record.channel_id)
                # Only replace if this calibration is newer (or if no prior exists)
                if existing_id:
                    existing = self._records.get(existing_id)
                    if existing and existing.calibration_date and record.calibration_date:
                        if record.calibration_date >= existing.calibration_date:
                            self._channel_map[record.channel_id] = record.record_id
                    else:
                        self._channel_map[record.channel_id] = record.record_id
                else:
                    self._channel_map[record.channel_id] = record.record_id

            self._save()

            # Audit trail logging
            self._audit_log(
                'calibration.record.added',
                f"Calibration record {record.record_id} added for channel {record.channel_id}",
                user=record.performed_by or 'SYSTEM',
                details={
                    'record_id': record.record_id,
                    'channel_id': record.channel_id,
                    'instrument_id': record.instrument_id,
                    'certificate_number': record.certificate_number,
                    'result': record.result,
                    'calibration_date': record.calibration_date,
                    'next_due_date': record.next_due_date,
                }
            )

            logger.info(
                "Added calibration record %s for channel %s (result=%s, due=%s)",
                record.record_id, record.channel_id, record.result, record.next_due_date
            )

            return record.record_id

    def get_record(self, record_id: str) -> Optional[CalibrationRecord]:
        """Retrieve a calibration record by its ID."""
        with self._lock:
            return self._records.get(record_id)

    def get_channel_calibration(self, channel_id: str) -> Optional[CalibrationRecord]:
        """Get the latest calibration record for a given channel."""
        with self._lock:
            record_id = self._channel_map.get(channel_id)
            if record_id:
                return self._records.get(record_id)
            return None

    def get_all_records(self) -> List[CalibrationRecord]:
        """Return all calibration records, sorted by calibration date descending."""
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda r: r.calibration_date or '', reverse=True)
        return records

    def get_channel_history(self, channel_id: str) -> List[CalibrationRecord]:
        """Return all calibration records for a channel, newest first."""
        with self._lock:
            records = [r for r in self._records.values() if r.channel_id == channel_id]
        records.sort(key=lambda r: r.calibration_date or '', reverse=True)
        return records

    # ------------------------------------------------------------------ #
    # Due date tracking
    # ------------------------------------------------------------------ #

    def get_overdue_channels(self) -> List[Dict[str, Any]]:
        """
        Return all channels whose latest calibration is overdue.

        Returns a list of dicts with channel_id, record_id, next_due_date,
        days_overdue, and instrument_id.
        """
        results = []
        with self._lock:
            for channel_id, record_id in self._channel_map.items():
                record = self._records.get(record_id)
                if record and record.is_overdue():
                    results.append({
                        'channel_id': channel_id,
                        'record_id': record_id,
                        'instrument_id': record.instrument_id,
                        'next_due_date': record.next_due_date,
                        'days_overdue': abs(record.days_until_due()),
                        'calibration_lab': record.calibration_lab,
                        'certificate_number': record.certificate_number,
                    })
        results.sort(key=lambda x: x.get('days_overdue', 0), reverse=True)
        return results

    def get_upcoming_due(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Return channels with calibrations due within the next N days.

        Does not include already-overdue channels (use get_overdue_channels
        for those).
        """
        results = []
        with self._lock:
            for channel_id, record_id in self._channel_map.items():
                record = self._records.get(record_id)
                if not record or not record.next_due_date:
                    continue
                remaining = record.days_until_due()
                if 0 <= remaining <= days:
                    results.append({
                        'channel_id': channel_id,
                        'record_id': record_id,
                        'instrument_id': record.instrument_id,
                        'next_due_date': record.next_due_date,
                        'days_until_due': remaining,
                        'calibration_lab': record.calibration_lab,
                        'certificate_number': record.certificate_number,
                    })
        results.sort(key=lambda x: x.get('days_until_due', 0))
        return results

    # ------------------------------------------------------------------ #
    # Uncertainty budgets
    # ------------------------------------------------------------------ #

    def set_uncertainty_budget(self, channel_id: str, budget: UncertaintyBudget) -> None:
        """
        Set or replace the uncertainty budget for a channel.

        The budget is persisted independently of calibration records so it
        can be evaluated and updated without creating a new calibration.
        """
        with self._lock:
            if not budget.last_evaluated:
                budget.last_evaluated = datetime.now().isoformat(timespec='seconds')
            self._uncertainty_budgets[channel_id] = budget
            self._save()

            self._audit_log(
                'calibration.uncertainty.updated',
                f"Uncertainty budget updated for channel {channel_id}: "
                f"U = {budget.expanded_uncertainty():.6g} {budget.unit} (k={budget.coverage_factor})",
                user=budget.evaluated_by or 'SYSTEM',
                details={
                    'channel_id': channel_id,
                    'expanded_uncertainty': budget.expanded_uncertainty(),
                    'coverage_factor': budget.coverage_factor,
                    'num_components': len(budget.components),
                    'unit': budget.unit,
                }
            )

            logger.info(
                "Set uncertainty budget for %s: U = %.6g %s (k=%.1f, %d components)",
                channel_id, budget.expanded_uncertainty(), budget.unit,
                budget.coverage_factor, len(budget.components)
            )

    def get_uncertainty(self, channel_id: str) -> Optional[UncertaintyBudget]:
        """Get the uncertainty budget for a channel."""
        with self._lock:
            return self._uncertainty_budgets.get(channel_id)

    def get_expanded_uncertainty(self, channel_id: str) -> Optional[float]:
        """
        Quick lookup: return the expanded uncertainty U for a channel.

        Returns None if no budget is defined.
        """
        with self._lock:
            budget = self._uncertainty_budgets.get(channel_id)
            if budget:
                return budget.expanded_uncertainty()
            return None

    # ------------------------------------------------------------------ #
    # Verification and traceability
    # ------------------------------------------------------------------ #

    def verify_calibration(self, channel_id: str) -> Dict[str, Any]:
        """
        Check the current calibration status of a channel.

        Returns a dict summarising the calibration state:
        - status: 'valid', 'overdue', 'expiring_soon', 'no_calibration'
        - record details if available
        - uncertainty if available
        """
        with self._lock:
            record = self.get_channel_calibration(channel_id)
            budget = self._uncertainty_budgets.get(channel_id)

        if not record:
            return {
                'channel_id': channel_id,
                'status': 'no_calibration',
                'message': 'No calibration record found for this channel',
                'record': None,
                'uncertainty': None,
            }

        days_left = record.days_until_due()
        if record.is_overdue():
            status = 'overdue'
            message = f"Calibration overdue by {abs(days_left)} days (due {record.next_due_date})"
        elif days_left <= 30:
            status = 'expiring_soon'
            message = f"Calibration due in {days_left} days ({record.next_due_date})"
        else:
            status = 'valid'
            message = f"Calibration valid, due in {days_left} days ({record.next_due_date})"

        result = {
            'channel_id': channel_id,
            'status': status,
            'message': message,
            'record_id': record.record_id,
            'instrument_id': record.instrument_id,
            'calibration_date': record.calibration_date,
            'next_due_date': record.next_due_date,
            'days_until_due': days_left,
            'certificate_number': record.certificate_number,
            'result': record.result,
            'max_error': record.max_error(),
            'uncertainty': budget.to_dict() if budget else None,
        }
        return result

    def get_traceability_chain(self, channel_id: str) -> List[Dict[str, Any]]:
        """
        Build the full metrological traceability chain from channel to SI.

        Returns a list of links in the chain:
        [channel -> instrument -> cal lab standard -> national standard -> SI]

        Each link contains the identity, certificate, and uncertainty at that
        level.
        """
        chain = []
        with self._lock:
            record = self.get_channel_calibration(channel_id)
            budget = self._uncertainty_budgets.get(channel_id)

        if not record:
            return [{
                'level': 'channel',
                'id': channel_id,
                'status': 'no_calibration',
                'note': 'No calibration record found',
            }]

        # Level 1: Channel / field instrument
        chain.append({
            'level': 'channel',
            'id': channel_id,
            'instrument_id': record.instrument_id,
            'calibration_date': record.calibration_date,
            'next_due_date': record.next_due_date,
            'result': record.result,
            'max_error': record.max_error(),
            'expanded_uncertainty': budget.expanded_uncertainty() if budget else None,
            'uncertainty_unit': budget.unit if budget else None,
        })

        # Level 2: Calibration certificate
        chain.append({
            'level': 'calibration_certificate',
            'certificate_number': record.certificate_number,
            'certificate_path': record.certificate_path,
            'calibration_lab': record.calibration_lab,
            'performed_by': record.performed_by,
            'approved_by': record.approved_by,
        })

        # Level 3: Reference standard used
        chain.append({
            'level': 'reference_standard',
            'standard_used': record.standard_used,
            'standard_certificate': record.standard_certificate,
            'lab_accreditation': record.lab_accreditation,
        })

        # Level 4: National / international traceability
        chain.append({
            'level': 'national_standard',
            'note': ('Traceability established through accredited laboratory '
                     f'({record.lab_accreditation})' if record.lab_accreditation
                     else 'Accreditation information not recorded'),
        })

        # Level 5: SI unit
        chain.append({
            'level': 'si_unit',
            'note': 'International System of Units (SI)',
        })

        return chain

    # ------------------------------------------------------------------ #
    # Status and summary
    # ------------------------------------------------------------------ #

    def get_status_summary(self) -> Dict[str, Any]:
        """
        Overall calibration program health summary.

        Returns counts of total, valid, overdue, expiring-soon, and
        uncalibrated channels, plus lists of problem channels.
        """
        with self._lock:
            total_records = len(self._records)
            total_channels = len(self._channel_map)
            overdue = self.get_overdue_channels()
            upcoming = self.get_upcoming_due(days=30)

            # Count results
            pass_count = sum(1 for r in self._records.values() if r.result == 'pass')
            fail_count = sum(1 for r in self._records.values() if r.result == 'fail')
            adjusted_count = sum(1 for r in self._records.values() if r.result == 'adjusted')

            # Channels with uncertainty budgets
            channels_with_uncertainty = len(self._uncertainty_budgets)

        return {
            'total_records': total_records,
            'total_channels_calibrated': total_channels,
            'channels_with_uncertainty_budgets': channels_with_uncertainty,
            'overdue_count': len(overdue),
            'upcoming_due_count': len(upcoming),
            'overdue_channels': overdue,
            'upcoming_due_channels': upcoming,
            'result_summary': {
                'pass': pass_count,
                'fail': fail_count,
                'adjusted': adjusted_count,
            },
            'program_health': (
                'critical' if len(overdue) > 0
                else 'warning' if len(upcoming) > 0
                else 'good'
            ),
            'last_updated': datetime.now().isoformat(timespec='seconds'),
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        MQTT-publishable summary of calibration state.

        Lightweight -- does not include full record details.  Use
        get_status_summary() for the full report.
        """
        with self._lock:
            overdue = self.get_overdue_channels()
            upcoming = self.get_upcoming_due(days=30)

            return {
                'total_records': len(self._records),
                'total_channels': len(self._channel_map),
                'overdue_count': len(overdue),
                'upcoming_due_30d': len(upcoming),
                'program_health': (
                    'critical' if len(overdue) > 0
                    else 'warning' if len(upcoming) > 0
                    else 'good'
                ),
                'overdue_channel_ids': [o['channel_id'] for o in overdue],
                'upcoming_channel_ids': [u['channel_id'] for u in upcoming],
            }

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        """Load calibration records and budgets from disk."""
        filepath = self.data_dir / self.RECORDS_FILENAME
        if not filepath.exists():
            logger.info("No existing calibration records file at %s", filepath)
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Load records
            for rec_dict in data.get('records', []):
                try:
                    rec = CalibrationRecord.from_dict(rec_dict)
                    self._records[rec.record_id] = rec
                except Exception as e:
                    logger.warning("Failed to load calibration record: %s", e)

            # Load channel map
            self._channel_map = data.get('channel_map', {})

            # Load uncertainty budgets
            for ch_id, budget_dict in data.get('uncertainty_budgets', {}).items():
                try:
                    self._uncertainty_budgets[ch_id] = UncertaintyBudget.from_dict(budget_dict)
                except Exception as e:
                    logger.warning("Failed to load uncertainty budget for %s: %s", ch_id, e)

            logger.info(
                "Loaded %d calibration records, %d channel mappings, %d uncertainty budgets from %s",
                len(self._records), len(self._channel_map),
                len(self._uncertainty_budgets), filepath
            )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse calibration records file %s: %s", filepath, e)
        except Exception as e:
            logger.error("Failed to load calibration records from %s: %s", filepath, e)

    def _save(self) -> None:
        """Persist calibration records and budgets to disk."""
        filepath = self.data_dir / self.RECORDS_FILENAME
        tmp_path = filepath.with_suffix('.tmp')

        data = {
            'version': '1.0',
            'saved_at': datetime.now().isoformat(timespec='seconds'),
            'records': [r.to_dict() for r in self._records.values()],
            'channel_map': self._channel_map,
            'uncertainty_budgets': {
                ch_id: budget.to_dict()
                for ch_id, budget in self._uncertainty_budgets.items()
            },
        }

        try:
            # Write to temp file first, then rename for atomicity
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                # fsync for crash safety
                import os as _os
                _os.fsync(f.fileno())

            # Atomic rename (on Windows, need to remove target first)
            if filepath.exists():
                filepath.unlink()
            tmp_path.rename(filepath)

        except Exception as e:
            logger.error("Failed to save calibration records to %s: %s", filepath, e)
            # Clean up temp file if it exists
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # Audit trail integration
    # ------------------------------------------------------------------ #

    def _audit_log(self, event_type: str, description: str,
                   user: str = 'SYSTEM', details: Optional[Dict] = None) -> None:
        """
        Log a calibration event to the audit trail (if available) and
        the standard Python logger.
        """
        logger.info("[AUDIT] %s: %s (user=%s)", event_type, description, user)

        if self.audit_trail is not None:
            try:
                # Use the audit trail's log_event method.
                # We pass event_type as a string; the AuditTrail handles both
                # AuditEventType enums and plain strings.
                self.audit_trail.log_event(
                    event_type=event_type,
                    user=user,
                    description=description,
                    details=details or {},
                )
            except Exception as e:
                logger.warning("Failed to write calibration event to audit trail: %s", e)
