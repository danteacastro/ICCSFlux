#!/usr/bin/env python3
"""
Unit tests for CalibrationManager (services/daq_service/calibration_manager.py).

Covers:
- UncertaintyComponent: standard uncertainty, distributions, degrees of freedom
- UncertaintyBudget: RSS combination, expanded uncertainty, Welch-Satterthwaite, serialization
- CalibrationRecord: overdue logic, days_until_due, max_error, result, serialization
- CalibrationManager: CRUD, due-date tracking, uncertainty budgets, verification,
  traceability, status summary, persistence roundtrip

Target: ~35-40 tests, all self-contained (no external deps, temp dirs for I/O).
"""

import sys
import os
import math
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on the path so imports work regardless of working dir
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.daq_service.calibration_manager import (
    UncertaintyComponent,
    UncertaintyBudget,
    CalibrationRecord,
    CalibrationManager,
    INF_DOF,
)

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _future_date(days_ahead: int = 180) -> str:
    """Return an ISO date string N days in the future."""
    return (date.today() + timedelta(days=days_ahead)).isoformat()

def _past_date(days_ago: int = 30) -> str:
    """Return an ISO date string N days in the past."""
    return (date.today() - timedelta(days=days_ago)).isoformat()

def _make_record(record_id: str = 'CAL-001',
                 channel_id: str = 'TC_01',
                 calibration_date: str = '2025-06-15',
                 next_due_date: str = '',
                 result: str = 'pass',
                 as_found: dict = None,
                 as_left: dict = None,
                 reference_values: dict = None,
                 tolerance: float = 0.5,
                 adjustment_made: bool = False,
                 **kwargs) -> CalibrationRecord:
    """Convenience factory for CalibrationRecord with sensible defaults."""
    return CalibrationRecord(
        record_id=record_id,
        channel_id=channel_id,
        instrument_id=kwargs.get('instrument_id', 'SN-12345'),
        calibration_date=calibration_date,
        next_due_date=next_due_date,
        certificate_number=kwargs.get('certificate_number', 'CERT-001'),
        performed_by=kwargs.get('performed_by', 'Tech A'),
        approved_by=kwargs.get('approved_by', 'Eng B'),
        calibration_lab=kwargs.get('calibration_lab', 'Acme Cal Lab'),
        lab_accreditation=kwargs.get('lab_accreditation', 'A2LA #99999'),
        standard_used=kwargs.get('standard_used', 'Fluke 9142'),
        standard_certificate=kwargs.get('standard_certificate', 'STD-CERT-01'),
        as_found=as_found or {},
        as_left=as_left or {},
        reference_values=reference_values or {},
        tolerance=tolerance,
        result=result,
        adjustment_made=adjustment_made,
        notes=kwargs.get('notes', ''),
    )

# ================================================================== #
# TestUncertaintyComponent
# ================================================================== #

class TestUncertaintyComponent(unittest.TestCase):
    """Tests for UncertaintyComponent dataclass and its standard_uncertainty property."""

    def test_standard_uncertainty_basic(self):
        """standard_uncertainty = value / divisor with default divisor=2."""
        comp = UncertaintyComponent(name='Sensor', value=0.5, divisor=2.0)
        self.assertAlmostEqual(comp.standard_uncertainty, 0.25)

    def test_normal_distribution_divisor_2(self):
        """Normal (Gaussian) distribution with k=2 divisor."""
        comp = UncertaintyComponent(name='Ref accuracy', value=1.0,
                                    distribution='normal', divisor=2.0)
        self.assertAlmostEqual(comp.standard_uncertainty, 0.5)

    def test_rectangular_distribution(self):
        """Rectangular (uniform) distribution: divisor = sqrt(3)."""
        comp = UncertaintyComponent(name='ADC resolution', value=0.1,
                                    distribution='rectangular',
                                    divisor=math.sqrt(3))
        expected = 0.1 / math.sqrt(3)
        self.assertAlmostEqual(comp.standard_uncertainty, expected, places=10)

    def test_triangular_distribution(self):
        """Triangular distribution: divisor = sqrt(6)."""
        comp = UncertaintyComponent(name='Hysteresis', value=0.06,
                                    distribution='triangular',
                                    divisor=math.sqrt(6))
        expected = 0.06 / math.sqrt(6)
        self.assertAlmostEqual(comp.standard_uncertainty, expected, places=10)

    def test_type_a_degrees_of_freedom(self):
        """Type A component stores finite degrees of freedom (n-1)."""
        comp = UncertaintyComponent(name='Repeatability', value=0.02,
                                    type='A', divisor=1.0,
                                    degrees_of_freedom=9)
        self.assertEqual(comp.type, 'A')
        self.assertEqual(comp.degrees_of_freedom, 9)
        self.assertAlmostEqual(comp.standard_uncertainty, 0.02)

    def test_type_b_degrees_of_freedom_default(self):
        """Type B component defaults to INF_DOF degrees of freedom."""
        comp = UncertaintyComponent(name='Spec', value=0.1)
        self.assertEqual(comp.type, 'B')
        self.assertEqual(comp.degrees_of_freedom, INF_DOF)

    def test_zero_divisor_returns_zero(self):
        """Divisor of zero should return 0.0, not raise."""
        comp = UncertaintyComponent(name='Edge', value=1.0, divisor=0.0)
        self.assertEqual(comp.standard_uncertainty, 0.0)

    def test_negative_value_uses_abs(self):
        """Negative value is taken as absolute value."""
        comp = UncertaintyComponent(name='Neg', value=-0.4, divisor=2.0)
        self.assertAlmostEqual(comp.standard_uncertainty, 0.2)

# ================================================================== #
# TestUncertaintyBudget
# ================================================================== #

class TestUncertaintyBudget(unittest.TestCase):
    """Tests for UncertaintyBudget: RSS combination, expanded uncertainty,
    Welch-Satterthwaite, and serialization."""

    def test_empty_budget_combined_zero(self):
        """An empty budget has combined standard uncertainty of 0."""
        budget = UncertaintyBudget(channel_id='TC_01', components=[])
        self.assertEqual(budget.combined_standard_uncertainty(), 0.0)

    def test_empty_budget_expanded_zero(self):
        """An empty budget has expanded uncertainty of 0."""
        budget = UncertaintyBudget(channel_id='TC_01', components=[])
        self.assertEqual(budget.expanded_uncertainty(), 0.0)

    def test_single_component_combined(self):
        """Combined uncertainty with one component equals that component's std uncertainty."""
        comp = UncertaintyComponent(name='A', value=0.6, divisor=2.0)
        budget = UncertaintyBudget(channel_id='TC_01', components=[comp])
        self.assertAlmostEqual(budget.combined_standard_uncertainty(), 0.3)

    def test_rss_combination_two_components(self):
        """RSS of two components: sqrt(u1^2 + u2^2)."""
        c1 = UncertaintyComponent(name='A', value=0.6, divisor=2.0)   # u=0.3
        c2 = UncertaintyComponent(name='B', value=0.8, divisor=2.0)   # u=0.4
        budget = UncertaintyBudget(channel_id='TC_01', components=[c1, c2])
        expected = math.sqrt(0.3**2 + 0.4**2)  # 0.5
        self.assertAlmostEqual(budget.combined_standard_uncertainty(), expected)

    def test_expanded_uncertainty_with_coverage_factor(self):
        """Expanded uncertainty = combined * k."""
        c1 = UncertaintyComponent(name='A', value=0.6, divisor=2.0)   # u=0.3
        c2 = UncertaintyComponent(name='B', value=0.8, divisor=2.0)   # u=0.4
        budget = UncertaintyBudget(channel_id='TC_01', components=[c1, c2],
                                   coverage_factor=2.0)
        combined = math.sqrt(0.3**2 + 0.4**2)
        self.assertAlmostEqual(budget.expanded_uncertainty(), combined * 2.0)

    def test_effective_dof_all_type_b(self):
        """All Type B components (INF_DOF) -> effective DOF = INF_DOF."""
        c1 = UncertaintyComponent(name='A', value=0.5, divisor=2.0)
        c2 = UncertaintyComponent(name='B', value=0.3, divisor=2.0)
        budget = UncertaintyBudget(channel_id='TC_01', components=[c1, c2])
        self.assertAlmostEqual(budget.effective_degrees_of_freedom(),
                               float(INF_DOF))

    def test_effective_dof_welch_satterthwaite(self):
        """Mixed Type A/B: Welch-Satterthwaite gives finite effective DOF."""
        # Type A: u=0.05, dof=9
        c_a = UncertaintyComponent(name='Repeat', value=0.05, type='A',
                                   divisor=1.0, degrees_of_freedom=9)
        # Type B: u=0.03, dof=INF_DOF  (divisor=1 so u=value)
        c_b = UncertaintyComponent(name='Spec', value=0.03, type='B',
                                   divisor=1.0, degrees_of_freedom=INF_DOF)

        budget = UncertaintyBudget(channel_id='TC_01', components=[c_a, c_b])
        u_c = budget.combined_standard_uncertainty()
        # Manual Welch-Satterthwaite:
        # v_eff = u_c^4 / (u_a^4/v_a + u_b^4/v_b)
        u_a, u_b = 0.05, 0.03
        v_a, v_b = 9, INF_DOF
        u_c_manual = math.sqrt(u_a**2 + u_b**2)
        numerator = u_c_manual ** 4
        denominator = (u_a**4 / v_a) + (u_b**4 / v_b)
        expected_dof = numerator / denominator
        self.assertAlmostEqual(budget.effective_degrees_of_freedom(),
                               expected_dof, places=2)
        # With a dominant Type A at dof=9, effective DOF should be finite
        self.assertGreater(budget.effective_degrees_of_freedom(), 9)
        self.assertLess(budget.effective_degrees_of_freedom(), float(INF_DOF))

    def test_to_dict_from_dict_roundtrip(self):
        """Serialize to dict and back; computed values match."""
        c1 = UncertaintyComponent(name='A', value=0.5, divisor=2.0, source='Spec')
        c2 = UncertaintyComponent(name='B', value=0.3, divisor=math.sqrt(3),
                                  distribution='rectangular')
        budget = UncertaintyBudget(
            channel_id='TC_01', components=[c1, c2],
            coverage_factor=2.0, unit='degC',
            last_evaluated='2025-07-01T10:00:00',
            evaluated_by='Engineer X',
        )

        d = budget.to_dict()
        restored = UncertaintyBudget.from_dict(d)

        self.assertEqual(restored.channel_id, 'TC_01')
        self.assertEqual(len(restored.components), 2)
        self.assertEqual(restored.coverage_factor, 2.0)
        self.assertEqual(restored.unit, 'degC')
        self.assertAlmostEqual(restored.combined_standard_uncertainty(),
                               budget.combined_standard_uncertainty())
        self.assertAlmostEqual(restored.expanded_uncertainty(),
                               budget.expanded_uncertainty())

    def test_multiple_components_combine_correctly(self):
        """Four components combine via RSS."""
        values = [0.10, 0.20, 0.30, 0.40]
        components = [
            UncertaintyComponent(name=f'C{i}', value=v, divisor=1.0)
            for i, v in enumerate(values)
        ]
        budget = UncertaintyBudget(channel_id='CH', components=components)
        expected = math.sqrt(sum(v**2 for v in values))
        self.assertAlmostEqual(budget.combined_standard_uncertainty(), expected)

# ================================================================== #
# TestCalibrationRecord
# ================================================================== #

class TestCalibrationRecord(unittest.TestCase):
    """Tests for CalibrationRecord: overdue detection, error calculation,
    result handling, and serialization."""

    def test_is_overdue_past_due(self):
        """Record with a due date in the past is overdue."""
        rec = _make_record(next_due_date=_past_date(30))
        self.assertTrue(rec.is_overdue())

    def test_is_overdue_future_due(self):
        """Record with a due date in the future is not overdue."""
        rec = _make_record(next_due_date=_future_date(180))
        self.assertFalse(rec.is_overdue())

    def test_is_overdue_no_date(self):
        """Record with no due date is not considered overdue."""
        rec = _make_record(next_due_date='')
        self.assertFalse(rec.is_overdue())

    def test_days_until_due_future(self):
        """days_until_due returns positive for future date."""
        days_ahead = 45
        rec = _make_record(next_due_date=_future_date(days_ahead))
        self.assertEqual(rec.days_until_due(), days_ahead)

    def test_days_until_due_past(self):
        """days_until_due returns negative for past date."""
        days_ago = 10
        rec = _make_record(next_due_date=_past_date(days_ago))
        self.assertEqual(rec.days_until_due(), -days_ago)

    def test_days_until_due_no_date(self):
        """days_until_due returns 0 if no due date set."""
        rec = _make_record(next_due_date='')
        self.assertEqual(rec.days_until_due(), 0)

    def test_max_error_calculation(self):
        """max_error returns largest |as_found - reference|."""
        rec = _make_record(
            as_found={'0': 0.02, '50': 50.15, '100': 99.80},
            reference_values={'0': 0.0, '50': 50.0, '100': 100.0},
        )
        # Errors: 0.02, 0.15, 0.20 -> max = 0.20
        self.assertAlmostEqual(rec.max_error(), 0.20)

    def test_max_error_empty(self):
        """max_error returns 0.0 when no data."""
        rec = _make_record()
        self.assertEqual(rec.max_error(), 0.0)

    def test_max_error_partial_overlap(self):
        """max_error only considers test points present in both dicts."""
        rec = _make_record(
            as_found={'0': 0.05, '50': 50.3, '100': 100.1},
            reference_values={'0': 0.0, '100': 100.0},
            # '50' has no reference, so it's ignored
        )
        # Errors for common points: |0.05-0|=0.05, |100.1-100|=0.1
        self.assertAlmostEqual(rec.max_error(), 0.1)

    def test_result_pass(self):
        """Result string stored correctly for pass."""
        rec = _make_record(result='pass')
        self.assertEqual(rec.result, 'pass')

    def test_result_fail(self):
        """Result string stored correctly for fail."""
        rec = _make_record(result='fail')
        self.assertEqual(rec.result, 'fail')

    def test_adjustment_made_flag(self):
        """adjustment_made flag is correctly stored."""
        rec = _make_record(result='adjusted', adjustment_made=True)
        self.assertTrue(rec.adjustment_made)
        self.assertEqual(rec.result, 'adjusted')

    def test_to_dict_from_dict_roundtrip(self):
        """Serialize and deserialize a CalibrationRecord with all fields."""
        budget = UncertaintyBudget(
            channel_id='TC_01',
            components=[UncertaintyComponent(name='X', value=0.1, divisor=2.0)],
            coverage_factor=2.0,
            unit='degC',
        )
        rec = _make_record(
            next_due_date=_future_date(90),
            as_found={'0': 0.01, '100': 100.05},
            as_left={'0': 0.00, '100': 100.01},
            reference_values={'0': 0.0, '100': 100.0},
            tolerance=0.5,
            adjustment_made=True,
            result='adjusted',
            notes='Adjusted zero offset',
        )
        rec.uncertainty = budget
        rec.created_at = '2025-07-01T12:00:00'

        d = rec.to_dict()
        restored = CalibrationRecord.from_dict(d)

        self.assertEqual(restored.record_id, rec.record_id)
        self.assertEqual(restored.channel_id, rec.channel_id)
        self.assertEqual(restored.instrument_id, rec.instrument_id)
        self.assertEqual(restored.calibration_date, rec.calibration_date)
        self.assertEqual(restored.next_due_date, rec.next_due_date)
        self.assertEqual(restored.result, 'adjusted')
        self.assertTrue(restored.adjustment_made)
        self.assertEqual(restored.as_found, rec.as_found)
        self.assertEqual(restored.as_left, rec.as_left)
        self.assertEqual(restored.reference_values, rec.reference_values)
        self.assertAlmostEqual(restored.tolerance, 0.5)
        self.assertIsNotNone(restored.uncertainty)
        self.assertAlmostEqual(
            restored.uncertainty.expanded_uncertainty(),
            budget.expanded_uncertainty(),
        )

    def test_to_dict_includes_computed_fields(self):
        """to_dict output includes is_overdue, days_until_due, max_error."""
        rec = _make_record(
            next_due_date=_future_date(60),
            as_found={'0': 0.1},
            reference_values={'0': 0.0},
        )
        d = rec.to_dict()
        self.assertIn('is_overdue', d)
        self.assertIn('days_until_due', d)
        self.assertIn('max_error', d)
        self.assertFalse(d['is_overdue'])
        self.assertEqual(d['days_until_due'], 60)
        self.assertAlmostEqual(d['max_error'], 0.1)

# ================================================================== #
# TestCalibrationManager
# ================================================================== #

class TestCalibrationManager(unittest.TestCase):
    """Tests for the CalibrationManager class: CRUD, due-date tracking,
    uncertainty, verification, traceability, status, and persistence."""

    def setUp(self):
        """Create a temporary directory for each test."""
        self.test_dir = tempfile.mkdtemp(prefix='caltest_')
        self.mgr = CalibrationManager(data_dir=Path(self.test_dir))

    def tearDown(self):
        """Remove the temporary directory after each test."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -- Record CRUD --

    def test_add_and_get_record(self):
        """add_record stores a record retrievable by get_record."""
        rec = _make_record(record_id='CAL-100', channel_id='TC_01')
        returned_id = self.mgr.add_record(rec)
        self.assertEqual(returned_id, 'CAL-100')

        fetched = self.mgr.get_record('CAL-100')
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.channel_id, 'TC_01')

    def test_add_record_auto_generates_id(self):
        """add_record generates a record_id if none is provided."""
        rec = _make_record(record_id='', channel_id='TC_02')
        returned_id = self.mgr.add_record(rec)
        self.assertTrue(returned_id.startswith('CAL-'))
        self.assertIsNotNone(self.mgr.get_record(returned_id))

    def test_get_record_not_found(self):
        """get_record returns None for unknown record_id."""
        self.assertIsNone(self.mgr.get_record('NONEXISTENT'))

    def test_get_channel_calibration_returns_latest(self):
        """get_channel_calibration returns the most recent record for a channel."""
        old = _make_record(record_id='CAL-OLD', channel_id='TC_01',
                           calibration_date='2024-01-01',
                           next_due_date='2025-01-01')
        new = _make_record(record_id='CAL-NEW', channel_id='TC_01',
                           calibration_date='2025-06-01',
                           next_due_date='2026-06-01')

        self.mgr.add_record(old)
        self.mgr.add_record(new)

        latest = self.mgr.get_channel_calibration('TC_01')
        self.assertIsNotNone(latest)
        self.assertEqual(latest.record_id, 'CAL-NEW')

    def test_get_channel_calibration_older_does_not_replace(self):
        """Adding an older record does not replace a newer one in the channel map."""
        new = _make_record(record_id='CAL-NEW', channel_id='TC_01',
                           calibration_date='2025-06-01')
        old = _make_record(record_id='CAL-OLD', channel_id='TC_01',
                           calibration_date='2024-01-01')

        self.mgr.add_record(new)
        self.mgr.add_record(old)

        latest = self.mgr.get_channel_calibration('TC_01')
        self.assertEqual(latest.record_id, 'CAL-NEW')

    # -- Due-date tracking --

    def test_get_overdue_channels(self):
        """get_overdue_channels lists channels whose latest cal is past due."""
        rec = _make_record(record_id='CAL-OD', channel_id='TC_OVERDUE',
                           next_due_date=_past_date(15))
        self.mgr.add_record(rec)

        overdue = self.mgr.get_overdue_channels()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]['channel_id'], 'TC_OVERDUE')
        self.assertEqual(overdue[0]['days_overdue'], 15)

    def test_get_overdue_channels_empty_when_all_valid(self):
        """No overdue channels when all calibrations have future due dates."""
        rec = _make_record(record_id='CAL-OK', channel_id='TC_OK',
                           next_due_date=_future_date(200))
        self.mgr.add_record(rec)

        self.assertEqual(len(self.mgr.get_overdue_channels()), 0)

    def test_get_upcoming_due(self):
        """get_upcoming_due lists channels due within N days (not overdue)."""
        # Due in 15 days -- should appear
        rec_soon = _make_record(record_id='CAL-SOON', channel_id='TC_SOON',
                                next_due_date=_future_date(15))
        # Due in 60 days -- outside 30-day window
        rec_later = _make_record(record_id='CAL-LATER', channel_id='TC_LATER',
                                 next_due_date=_future_date(60))
        self.mgr.add_record(rec_soon)
        self.mgr.add_record(rec_later)

        upcoming = self.mgr.get_upcoming_due(days=30)
        channel_ids = [u['channel_id'] for u in upcoming]
        self.assertIn('TC_SOON', channel_ids)
        self.assertNotIn('TC_LATER', channel_ids)

    def test_get_upcoming_due_excludes_overdue(self):
        """get_upcoming_due does not include already-overdue channels."""
        rec = _make_record(record_id='CAL-PAST', channel_id='TC_PAST',
                           next_due_date=_past_date(5))
        self.mgr.add_record(rec)

        upcoming = self.mgr.get_upcoming_due(days=30)
        self.assertEqual(len(upcoming), 0)

    # -- Uncertainty budgets --

    def test_set_and_get_uncertainty_budget(self):
        """set_uncertainty_budget stores a budget retrievable by get_uncertainty."""
        budget = UncertaintyBudget(
            channel_id='TC_01',
            components=[UncertaintyComponent(name='A', value=0.5, divisor=2.0)],
            coverage_factor=2.0,
            unit='degC',
        )
        self.mgr.set_uncertainty_budget('TC_01', budget)

        retrieved = self.mgr.get_uncertainty('TC_01')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.channel_id, 'TC_01')
        self.assertAlmostEqual(retrieved.expanded_uncertainty(),
                               budget.expanded_uncertainty())

    def test_get_expanded_uncertainty(self):
        """get_expanded_uncertainty returns the U value for a channel."""
        comp = UncertaintyComponent(name='A', value=1.0, divisor=2.0)  # u=0.5
        budget = UncertaintyBudget(channel_id='TC_01', components=[comp],
                                   coverage_factor=2.0)
        self.mgr.set_uncertainty_budget('TC_01', budget)

        U = self.mgr.get_expanded_uncertainty('TC_01')
        self.assertAlmostEqual(U, 1.0)  # 0.5 * 2.0

    def test_get_expanded_uncertainty_unknown_channel(self):
        """get_expanded_uncertainty returns None for unknown channel."""
        self.assertIsNone(self.mgr.get_expanded_uncertainty('UNKNOWN'))

    # -- Verification --

    def test_verify_calibration_valid(self):
        """verify_calibration returns 'valid' for in-date calibration."""
        rec = _make_record(record_id='CAL-V', channel_id='TC_V',
                           next_due_date=_future_date(90), result='pass')
        self.mgr.add_record(rec)

        result = self.mgr.verify_calibration('TC_V')
        self.assertEqual(result['status'], 'valid')
        self.assertEqual(result['channel_id'], 'TC_V')
        self.assertEqual(result['result'], 'pass')

    def test_verify_calibration_overdue(self):
        """verify_calibration returns 'overdue' for past-due calibration."""
        rec = _make_record(record_id='CAL-OD2', channel_id='TC_OD',
                           next_due_date=_past_date(10))
        self.mgr.add_record(rec)

        result = self.mgr.verify_calibration('TC_OD')
        self.assertEqual(result['status'], 'overdue')

    def test_verify_calibration_expiring_soon(self):
        """verify_calibration returns 'expiring_soon' when due within 30 days."""
        rec = _make_record(record_id='CAL-ES', channel_id='TC_ES',
                           next_due_date=_future_date(20))
        self.mgr.add_record(rec)

        result = self.mgr.verify_calibration('TC_ES')
        self.assertEqual(result['status'], 'expiring_soon')

    def test_verify_calibration_no_record(self):
        """verify_calibration returns 'no_calibration' for unknown channel."""
        result = self.mgr.verify_calibration('UNKNOWN_CH')
        self.assertEqual(result['status'], 'no_calibration')
        self.assertIsNone(result['record'])

    # -- Traceability --

    def test_get_traceability_chain(self):
        """get_traceability_chain returns 5-level chain for calibrated channel."""
        rec = _make_record(
            record_id='CAL-TR', channel_id='TC_TR',
            calibration_lab='Acme Cal Lab',
            lab_accreditation='A2LA #12345',
            standard_used='Fluke 9142',
            standard_certificate='STD-CERT-99',
        )
        self.mgr.add_record(rec)

        chain = self.mgr.get_traceability_chain('TC_TR')
        self.assertEqual(len(chain), 5)
        levels = [link['level'] for link in chain]
        self.assertEqual(levels, [
            'channel',
            'calibration_certificate',
            'reference_standard',
            'national_standard',
            'si_unit',
        ])
        self.assertEqual(chain[0]['instrument_id'], 'SN-12345')
        self.assertEqual(chain[1]['calibration_lab'], 'Acme Cal Lab')
        self.assertEqual(chain[2]['standard_used'], 'Fluke 9142')

    def test_get_traceability_chain_no_record(self):
        """get_traceability_chain returns single 'no_calibration' entry for unknown channel."""
        chain = self.mgr.get_traceability_chain('GHOST')
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]['status'], 'no_calibration')

    # -- Status summary --

    def test_get_status_summary(self):
        """get_status_summary returns correct counts and program_health."""
        # One overdue, one valid, one with 'fail' result
        self.mgr.add_record(_make_record(
            record_id='CAL-A', channel_id='CH_A',
            next_due_date=_past_date(5), result='pass'))
        self.mgr.add_record(_make_record(
            record_id='CAL-B', channel_id='CH_B',
            next_due_date=_future_date(200), result='fail'))
        self.mgr.add_record(_make_record(
            record_id='CAL-C', channel_id='CH_C',
            next_due_date=_future_date(180), result='adjusted'))

        summary = self.mgr.get_status_summary()
        self.assertEqual(summary['total_records'], 3)
        self.assertEqual(summary['total_channels_calibrated'], 3)
        self.assertEqual(summary['overdue_count'], 1)
        self.assertEqual(summary['result_summary']['pass'], 1)
        self.assertEqual(summary['result_summary']['fail'], 1)
        self.assertEqual(summary['result_summary']['adjusted'], 1)
        self.assertEqual(summary['program_health'], 'critical')  # has overdue

    def test_status_summary_good_health(self):
        """program_health is 'good' when no overdue and no upcoming."""
        self.mgr.add_record(_make_record(
            record_id='CAL-OK', channel_id='CH_OK',
            next_due_date=_future_date(365), result='pass'))

        summary = self.mgr.get_status_summary()
        self.assertEqual(summary['program_health'], 'good')

    def test_status_summary_warning_health(self):
        """program_health is 'warning' when upcoming due but no overdue."""
        self.mgr.add_record(_make_record(
            record_id='CAL-W', channel_id='CH_W',
            next_due_date=_future_date(10), result='pass'))

        summary = self.mgr.get_status_summary()
        self.assertEqual(summary['program_health'], 'warning')

    # -- Persistence roundtrip --

    def test_save_and_load_persistence(self):
        """Records, channel map, and uncertainty budgets survive save+load cycle."""
        # Add a record
        rec = _make_record(
            record_id='CAL-P1', channel_id='TC_P1',
            calibration_date='2025-06-15',
            next_due_date=_future_date(90),
            as_found={'0': 0.01, '100': 100.05},
            reference_values={'0': 0.0, '100': 100.0},
            result='pass',
        )
        self.mgr.add_record(rec)

        # Add an uncertainty budget
        budget = UncertaintyBudget(
            channel_id='TC_P1',
            components=[
                UncertaintyComponent(name='Sensor', value=0.5, divisor=2.0),
                UncertaintyComponent(name='ADC', value=0.1,
                                     divisor=math.sqrt(3),
                                     distribution='rectangular'),
            ],
            coverage_factor=2.0,
            unit='degC',
            evaluated_by='Engineer Z',
        )
        self.mgr.set_uncertainty_budget('TC_P1', budget)

        # Create a new manager from the same directory -- triggers _load
        mgr2 = CalibrationManager(data_dir=Path(self.test_dir))

        # Verify record
        loaded_rec = mgr2.get_record('CAL-P1')
        self.assertIsNotNone(loaded_rec)
        self.assertEqual(loaded_rec.channel_id, 'TC_P1')
        self.assertEqual(loaded_rec.result, 'pass')
        self.assertAlmostEqual(loaded_rec.max_error(), rec.max_error())

        # Verify channel map
        latest = mgr2.get_channel_calibration('TC_P1')
        self.assertIsNotNone(latest)
        self.assertEqual(latest.record_id, 'CAL-P1')

        # Verify uncertainty budget
        loaded_budget = mgr2.get_uncertainty('TC_P1')
        self.assertIsNotNone(loaded_budget)
        self.assertEqual(len(loaded_budget.components), 2)
        self.assertAlmostEqual(loaded_budget.expanded_uncertainty(),
                               budget.expanded_uncertainty())

    def test_load_from_empty_directory(self):
        """CalibrationManager initializes cleanly from an empty directory."""
        empty_dir = tempfile.mkdtemp(prefix='calempty_')
        try:
            mgr = CalibrationManager(data_dir=Path(empty_dir))
            self.assertEqual(len(mgr.get_all_records()), 0)
            self.assertEqual(len(mgr.get_overdue_channels()), 0)
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_persistence_file_exists_after_add(self):
        """The JSON file is created on disk after adding a record."""
        rec = _make_record(record_id='CAL-FILE', channel_id='TC_FILE')
        self.mgr.add_record(rec)

        filepath = Path(self.test_dir) / CalibrationManager.RECORDS_FILENAME
        self.assertTrue(filepath.exists())

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['version'], '1.0')
        self.assertEqual(len(data['records']), 1)

    # -- Audit trail integration --

    def test_audit_trail_called_on_add(self):
        """If audit_trail is provided, log_event is called when adding a record."""
        mock_audit = MagicMock()
        mgr = CalibrationManager(data_dir=Path(self.test_dir),
                                 audit_trail=mock_audit)

        rec = _make_record(record_id='CAL-AUD', channel_id='TC_AUD',
                           performed_by='Tester')
        mgr.add_record(rec)

        mock_audit.log_event.assert_called()
        call_kwargs = mock_audit.log_event.call_args
        self.assertIn('calibration.record.added',
                      str(call_kwargs))

if __name__ == '__main__':
    unittest.main()
