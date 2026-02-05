"""
Unit tests for cRIO script engine helper classes and APIs.

Tests all cRIO-side classes that user scripts interact with:
- RateCalculator, Accumulator, EdgeDetector, RollingStats
- SharedVariableStore (thread-safe inter-script communication)
- TagsAPI, OutputsAPI, SessionAPI, VarsAPI (script environment)

No MQTT broker, hardware, or cRIO required — all dependencies are mocked.
"""

import sys
import time
import threading
from pathlib import Path
from typing import Any

import pytest

# Add service paths
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "crio_node_v2"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from script_engine import (
    RateCalculator, Accumulator, EdgeDetector, RollingStats,
    SharedVariableStore, TagsAPI, OutputsAPI, SessionAPI, VarsAPI,
    StatePersistence,
)


# =========================================================================
# 1. RateCalculator
# =========================================================================

class TestRateCalculator:
    """Rate of change calculation."""

    def test_first_update_returns_zero(self):
        rc = RateCalculator()
        assert rc.update(100.0) == 0.0

    def test_rate_positive(self):
        rc = RateCalculator()
        rc.update(0.0)
        time.sleep(0.1)
        rate = rc.update(10.0)
        # 10.0 change in ~0.1s → ~100/s
        assert rate > 0
        assert 50 < rate < 200  # generous bounds for timing jitter

    def test_rate_negative(self):
        rc = RateCalculator()
        rc.update(100.0)
        time.sleep(0.1)
        rate = rc.update(90.0)
        assert rate < 0

    def test_rate_stable_value(self):
        rc = RateCalculator()
        rc.update(50.0)
        time.sleep(0.05)
        rate = rc.update(50.0)
        assert rate == pytest.approx(0.0, abs=0.1)

    def test_consecutive_updates(self):
        rc = RateCalculator()
        rc.update(0.0)
        time.sleep(0.05)
        r1 = rc.update(10.0)
        time.sleep(0.05)
        r2 = rc.update(10.0)  # same value → rate ~0
        assert r1 > 0
        assert abs(r2) < abs(r1)  # rate should drop


# =========================================================================
# 2. Accumulator
# =========================================================================

class TestAccumulator:
    """Cumulative integration over time."""

    def test_initial_value(self):
        acc = Accumulator(initial=100.0)
        assert acc.total == 100.0

    def test_default_initial_zero(self):
        acc = Accumulator()
        assert acc.total == 0.0

    def test_add_integrates_over_time(self):
        acc = Accumulator()
        time.sleep(0.1)
        result = acc.add(100.0)
        # 100.0 * ~0.1s → ~10.0
        assert result > 0
        assert 5.0 < result < 20.0

    def test_add_accumulates(self):
        acc = Accumulator()
        time.sleep(0.1)
        acc.add(100.0)
        time.sleep(0.1)
        result = acc.add(100.0)
        # Two additions of 100 * ~0.1s each → ~20.0 total
        assert result > acc.total * 0  # just check it grew
        assert acc.total > 10.0

    def test_reset_clears_total(self):
        acc = Accumulator()
        time.sleep(0.05)
        acc.add(100.0)
        assert acc.total > 0
        acc.reset()
        assert acc.total == 0.0

    def test_accumulator_with_zero_value(self):
        acc = Accumulator()
        time.sleep(0.05)
        result = acc.add(0.0)
        # 0.0 * dt = 0.0
        assert result == pytest.approx(0.0, abs=0.01)


# =========================================================================
# 3. EdgeDetector
# =========================================================================

class TestEdgeDetector:
    """Boolean edge detection."""

    def test_first_value_returns_none(self):
        ed = EdgeDetector()
        assert ed.update(True) == 'none'

    def test_rising_edge(self):
        ed = EdgeDetector()
        ed.update(False)
        assert ed.update(True) == 'rising'

    def test_falling_edge(self):
        ed = EdgeDetector()
        ed.update(True)
        assert ed.update(False) == 'falling'

    def test_repeated_true(self):
        ed = EdgeDetector()
        ed.update(True)
        assert ed.update(True) == 'none'

    def test_repeated_false(self):
        ed = EdgeDetector()
        ed.update(False)
        assert ed.update(False) == 'none'

    def test_alternating_sequence(self):
        ed = EdgeDetector()
        ed.update(False)  # first value
        results = []
        for val in [True, False, True, False, True]:
            results.append(ed.update(val))
        assert results == ['rising', 'falling', 'rising', 'falling', 'rising']

    def test_long_low_then_rising(self):
        ed = EdgeDetector()
        for _ in range(100):
            ed.update(False)
        assert ed.update(True) == 'rising'

    def test_long_high_then_falling(self):
        ed = EdgeDetector()
        for _ in range(100):
            ed.update(True)
        assert ed.update(False) == 'falling'


# =========================================================================
# 4. RollingStats
# =========================================================================

class TestRollingStats:
    """Windowed rolling statistics."""

    def test_empty_stats(self):
        rs = RollingStats()
        assert rs.mean == 0.0
        assert rs.min == 0.0
        assert rs.max == 0.0
        assert rs.std == 0.0
        assert rs.count == 0

    def test_single_value(self):
        rs = RollingStats()
        rs.update(42.0)
        assert rs.mean == pytest.approx(42.0)
        assert rs.min == pytest.approx(42.0)
        assert rs.max == pytest.approx(42.0)
        assert rs.std == 0.0  # stdev needs >=2 samples
        assert rs.count == 1

    def test_multiple_values(self):
        rs = RollingStats()
        for v in [10.0, 20.0, 30.0]:
            rs.update(v)
        assert rs.mean == pytest.approx(20.0)
        assert rs.min == pytest.approx(10.0)
        assert rs.max == pytest.approx(30.0)
        assert rs.count == 3

    def test_window_overflow(self):
        """Values beyond window size are discarded."""
        rs = RollingStats(window=5)
        for v in [1, 2, 3, 4, 5, 100, 200]:
            rs.update(v)
        # Window should contain [3, 4, 5, 100, 200]
        assert rs.count == 5
        assert rs.min == pytest.approx(3.0)
        assert rs.max == pytest.approx(200.0)

    def test_std_computation(self):
        rs = RollingStats()
        for v in [10, 10, 10, 10, 10]:
            rs.update(v)
        assert rs.std == pytest.approx(0.0)

        rs2 = RollingStats()
        for v in [2, 4, 4, 4, 5, 5, 7, 9]:
            rs2.update(v)
        assert rs2.std > 0

    def test_large_window(self):
        rs = RollingStats(window=10000)
        for i in range(10000):
            rs.update(float(i))
        assert rs.count == 10000
        assert rs.mean == pytest.approx(4999.5)


# =========================================================================
# 5. SharedVariableStore
# =========================================================================

class TestSharedVariableStore:
    """Thread-safe inter-script variable store."""

    def _make_store(self, tmp_path, publish_fn=None):
        """Create a store with real StatePersistence for disk tests."""
        sp = StatePersistence(state_dir=str(tmp_path))
        return SharedVariableStore(persistence=sp, publish_fn=publish_fn)

    def test_set_and_get(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('temp', 25.5)
        assert store.get('temp') == 25.5

    def test_get_missing_returns_default(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.get('nonexistent') is None
        assert store.get('nonexistent', 42) == 42

    def test_has(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.has('x') is False
        store.set('x', 1)
        assert store.has('x') is True

    def test_delete(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('x', 1)
        assert store.delete('x') is True
        assert store.has('x') is False
        assert store.delete('x') is False  # already deleted

    def test_keys(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('a', 1)
        store.set('b', 2)
        store.set('c', 3)
        assert sorted(store.keys()) == ['a', 'b', 'c']

    def test_get_all(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('x', 10)
        store.set('y', 20)
        all_vars = store.get_all()
        assert all_vars == {'x': 10, 'y': 20}

    def test_reset_numeric(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('counter', 999)
        assert store.reset('counter') is True
        assert store.get('counter') == 0

    def test_reset_string(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('label', 'hello')
        assert store.reset('label') is True
        assert store.get('label') == ''

    def test_reset_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.reset('nonexistent') is False

    def test_max_variables_limit(self, tmp_path):
        store = self._make_store(tmp_path)
        # Fill to limit (persist=False for speed)
        for i in range(SharedVariableStore.MAX_VARIABLES):
            assert store.set(f'var_{i}', i, persist=False) is True

        # Next new variable should fail
        assert store.set('one_too_many', 0, persist=False) is False

        # Updating existing should still work
        assert store.set('var_0', 999, persist=False) is True

    def test_overwrite_existing(self, tmp_path):
        store = self._make_store(tmp_path)
        store.set('x', 1)
        store.set('x', 2)
        assert store.get('x') == 2

    def test_publish_callback(self, tmp_path):
        published = []
        store = self._make_store(tmp_path, publish_fn=lambda d: published.append(d))
        store.set('temp', 25.0)
        assert len(published) == 1
        assert published[0] == {'temp': 25.0}

    def test_publish_failure_no_crash(self, tmp_path):
        def bad_publish(d):
            raise RuntimeError("publish failed")
        store = self._make_store(tmp_path, publish_fn=bad_publish)
        # Should not raise
        store.set('temp', 25.0)
        assert store.get('temp') == 25.0

    def test_persistence_survives_reload(self, tmp_path):
        sp = StatePersistence(state_dir=str(tmp_path))
        store1 = SharedVariableStore(persistence=sp)
        store1.set('persistent_var', 42)

        # New store with same persistence should load the data
        store2 = SharedVariableStore(persistence=sp)
        assert store2.get('persistent_var') == 42

    def test_flush_saves_dirty_data(self, tmp_path):
        sp = StatePersistence(state_dir=str(tmp_path))
        store1 = SharedVariableStore(persistence=sp)
        store1.set('ephemeral', 100, persist=False)
        assert store1._dirty is True
        store1.flush()
        assert store1._dirty is False

        # New store should see the flushed data
        store2 = SharedVariableStore(persistence=sp)
        assert store2.get('ephemeral') == 100

    def test_concurrent_access(self, tmp_path):
        """Multiple threads writing different keys don't corrupt the store."""
        store = self._make_store(tmp_path)
        errors = []

        def worker(prefix, count):
            try:
                for i in range(count):
                    store.set(f'{prefix}_{i}', i, persist=False)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f't{t}', 20))
            for t in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Should have 200 variables (10 threads * 20 each)
        assert len(store.keys()) == 200


# =========================================================================
# 6. TagsAPI
# =========================================================================

class TestTagsAPI:
    """Read-only tag value access for scripts."""

    def test_get_dict_value(self):
        """Tags stored as {name: {'value': x}} format."""
        tags = TagsAPI(lambda: {'TC001': {'value': 25.5}})
        assert tags.get('TC001') == 25.5

    def test_get_scalar_value(self):
        """Tags stored as {name: x} scalar format."""
        tags = TagsAPI(lambda: {'TC001': 30.0})
        assert tags.get('TC001') == 30.0

    def test_get_missing_returns_zero(self):
        tags = TagsAPI(lambda: {})
        assert tags.get('NONEXISTENT') == 0.0

    def test_attribute_access(self):
        tags = TagsAPI(lambda: {'TC001': {'value': 42.0}})
        assert tags.TC001 == 42.0

    def test_attribute_access_missing(self):
        tags = TagsAPI(lambda: {})
        assert tags.NONEXISTENT == 0.0

    def test_private_attr_raises(self):
        tags = TagsAPI(lambda: {})
        with pytest.raises(AttributeError):
            _ = tags._internal

    def test_bracket_access_with_dashes(self):
        """ISA-5.1 tag names with dashes work via get()."""
        tags = TagsAPI(lambda: {'PT-001': {'value': 100.5}})
        assert tags.get('PT-001') == 100.5

    def test_dynamic_values(self):
        """Values update on each read (no caching)."""
        values = {'TC001': {'value': 10.0}}
        tags = TagsAPI(lambda: values)
        assert tags.get('TC001') == 10.0

        values['TC001']['value'] = 20.0
        assert tags.get('TC001') == 20.0

    def test_none_value_returns_zero(self):
        tags = TagsAPI(lambda: {'TC001': None})
        assert tags.get('TC001') == 0.0

    def test_integer_value(self):
        tags = TagsAPI(lambda: {'DI001': 1})
        assert tags.get('DI001') == 1.0


# =========================================================================
# 7. OutputsAPI
# =========================================================================

class TestOutputsAPI:
    """Output write and lock checking."""

    def test_set_output(self):
        writes = []
        outputs = OutputsAPI(
            write_fn=lambda name, value: (writes.append((name, value)), True)[1],
            is_locked_fn=lambda name: False,
        )
        result = outputs.set('AO001', 5.0)
        assert result is True
        assert writes == [('AO001', 5.0)]

    def test_set_output_failure(self):
        outputs = OutputsAPI(
            write_fn=lambda name, value: False,
            is_locked_fn=lambda name: False,
        )
        assert outputs.set('AO001', 5.0) is False

    def test_is_locked_true(self):
        outputs = OutputsAPI(
            write_fn=lambda n, v: True,
            is_locked_fn=lambda name: name == 'LOCKED_OUT',
        )
        assert outputs.is_locked('LOCKED_OUT') is True
        assert outputs.is_locked('FREE_OUT') is False

    def test_multiple_outputs(self):
        writes = []
        outputs = OutputsAPI(
            write_fn=lambda n, v: (writes.append((n, v)), True)[1],
            is_locked_fn=lambda n: False,
        )
        outputs.set('AO001', 1.0)
        outputs.set('AO002', 2.0)
        outputs.set('DO001', True)
        assert len(writes) == 3
        assert writes[2] == ('DO001', True)


# =========================================================================
# 8. SessionAPI
# =========================================================================

class TestSessionAPI:
    """Read-only session state access."""

    def _make_session(self, **overrides):
        state = {
            'session_active': False,
            'session_name': '',
            'operator': '',
            'start_time': 0,
            'locked_outputs': [],
        }
        state.update(overrides)
        return SessionAPI(lambda: state)

    def test_inactive_session(self):
        session = self._make_session()
        assert session.active is False
        assert session.name == ''
        assert session.operator == ''
        assert session.duration == 0.0

    def test_active_session(self):
        session = self._make_session(
            session_active=True,
            session_name='Pressure Test #42',
            operator='alice',
            start_time=time.time() - 60,
        )
        assert session.active is True
        assert session.name == 'Pressure Test #42'
        assert session.operator == 'alice'
        assert session.duration >= 59.0  # ~60 seconds

    def test_locked_outputs(self):
        session = self._make_session(
            locked_outputs=['AO001', 'DO002'],
        )
        assert session.is_output_locked('AO001') is True
        assert session.is_output_locked('DO002') is True
        assert session.is_output_locked('AO003') is False

    def test_no_locked_outputs(self):
        session = self._make_session()
        assert session.is_output_locked('AO001') is False

    def test_duration_increases(self):
        start = time.time()
        session = self._make_session(start_time=start)
        d1 = session.duration
        time.sleep(0.05)
        d2 = session.duration
        assert d2 > d1


# =========================================================================
# 9. VarsAPI
# =========================================================================

class TestVarsAPI:
    """Shared variable access for scripts — all access patterns."""

    def _make_vars(self, tmp_path):
        sp = StatePersistence(state_dir=str(tmp_path))
        store = SharedVariableStore(persistence=sp)
        return VarsAPI(store), store

    def test_set_and_get(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('temp', 25.0)
        assert v.get('temp') == 25.0

    def test_get_default(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        assert v.get('nonexistent') == 0.0
        assert v.get('nonexistent', 42) == 42

    def test_attribute_access(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('pressure', 100.5)
        assert v.pressure == 100.5

    def test_attribute_missing_returns_zero(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        assert v.nonexistent == 0.0

    def test_index_access(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('level', 75.0)
        assert v['level'] == 75.0

    def test_index_missing_returns_zero(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        assert v['nonexistent'] == 0.0

    def test_contains(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        assert ('temp' in v) is False
        v.set('temp', 25.0)
        assert ('temp' in v) is True

    def test_keys(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('a', 1)
        v.set('b', 2)
        assert sorted(v.keys()) == ['a', 'b']

    def test_reset(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('counter', 999)
        v.reset('counter')
        assert v.get('counter') == 0

    def test_delete(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('temp', 25.0)
        assert v.delete('temp') is True
        assert ('temp' in v) is False

    def test_flush(self, tmp_path):
        v, store = self._make_vars(tmp_path)
        v.set('data', 42, persist=False)
        assert store._dirty is True
        v.flush()
        assert store._dirty is False

    def test_private_attr_raises(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        with pytest.raises(AttributeError):
            _ = v._nonexistent_private

    def test_cross_script_visibility(self, tmp_path):
        """Two VarsAPI instances sharing a store see each other's writes."""
        sp = StatePersistence(state_dir=str(tmp_path))
        store = SharedVariableStore(persistence=sp)
        v1 = VarsAPI(store)
        v2 = VarsAPI(store)

        v1.set('shared', 42)
        assert v2.get('shared') == 42

    def test_string_variable(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('label', 'Test Session #1')
        assert v.get('label') == 'Test Session #1'
        assert v.label == 'Test Session #1'

    def test_bool_variable(self, tmp_path):
        v, _ = self._make_vars(tmp_path)
        v.set('running', True)
        assert v.running is True
        v.set('running', False)
        assert v['running'] is False
