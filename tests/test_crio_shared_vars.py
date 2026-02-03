"""Tests for cRIO shared variable store and VarsAPI."""

import os
import json
import tempfile
import threading
import time
import pytest

from services.crio_node_v2.script_engine import (
    SharedVariableStore,
    StatePersistence,
    VarsAPI,
)


@pytest.fixture
def tmp_dir():
    """Temporary directory for state persistence."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def persistence(tmp_dir):
    return StatePersistence(state_dir=tmp_dir)


@pytest.fixture
def published():
    """Capture published MQTT messages."""
    messages = []
    return messages


@pytest.fixture
def store(persistence, published):
    def publish_fn(data):
        published.append(data)
    return SharedVariableStore(persistence=persistence, publish_fn=publish_fn)


@pytest.fixture
def vars_api(store):
    return VarsAPI(store)


# =============================================================================
# SharedVariableStore Tests
# =============================================================================


class TestSharedVariableStore:

    def test_get_set(self, store):
        assert store.get('x') is None
        assert store.set('x', 42)
        assert store.get('x') == 42

    def test_get_default(self, store):
        assert store.get('missing', 99) == 99

    def test_set_overwrites(self, store):
        store.set('x', 1)
        store.set('x', 2)
        assert store.get('x') == 2

    def test_set_string(self, store):
        store.set('name', 'hello')
        assert store.get('name') == 'hello'

    def test_set_bool(self, store):
        store.set('flag', True)
        assert store.get('flag') is True

    def test_has(self, store):
        assert not store.has('x')
        store.set('x', 1)
        assert store.has('x')

    def test_keys(self, store):
        store.set('a', 1)
        store.set('b', 2)
        assert sorted(store.keys()) == ['a', 'b']

    def test_keys_empty(self, store):
        assert store.keys() == []

    def test_delete(self, store):
        store.set('x', 1)
        assert store.delete('x')
        assert not store.has('x')
        assert store.get('x') is None

    def test_delete_nonexistent(self, store):
        assert not store.delete('nope')

    def test_reset_numeric(self, store):
        store.set('x', 42)
        assert store.reset('x')
        assert store.get('x') == 0

    def test_reset_string(self, store):
        store.set('name', 'hello')
        assert store.reset('name')
        assert store.get('name') == ''

    def test_reset_nonexistent(self, store):
        assert not store.reset('nope')

    def test_get_all(self, store):
        store.set('a', 1)
        store.set('b', 'two')
        result = store.get_all()
        assert result == {'a': 1, 'b': 'two'}
        # Should be a copy
        result['c'] = 3
        assert not store.has('c')

    def test_max_variables(self, store):
        for i in range(SharedVariableStore.MAX_VARIABLES):
            assert store.set(f'var_{i}', i)
        # Next one should fail
        assert not store.set('overflow', 999)
        assert not store.has('overflow')

    def test_max_variables_allows_update(self, store):
        """Updating an existing variable should work even at limit."""
        for i in range(SharedVariableStore.MAX_VARIABLES):
            store.set(f'var_{i}', i)
        # Updating existing should succeed
        assert store.set('var_0', 999)
        assert store.get('var_0') == 999

    def test_publishes_on_set(self, store, published):
        store.set('temp', 72.5)
        assert len(published) == 1
        assert published[0] == {'temp': 72.5}

    def test_publishes_on_reset(self, store, published):
        store.set('x', 42)
        published.clear()
        store.reset('x')
        assert len(published) == 1
        assert published[0] == {'x': 0}

    def test_no_publish_on_delete(self, store, published):
        store.set('x', 1)
        published.clear()
        store.delete('x')
        assert len(published) == 0

    def test_persistence_round_trip(self, tmp_dir):
        """Variables survive store recreation (simulates restart)."""
        persistence = StatePersistence(state_dir=tmp_dir)
        store1 = SharedVariableStore(persistence=persistence)
        store1.set('saved', 123)
        store1.set('text', 'hello')

        # Create new store with same persistence
        store2 = SharedVariableStore(persistence=persistence)
        assert store2.get('saved') == 123
        assert store2.get('text') == 'hello'

    def test_flush_saves_dirty(self, tmp_dir):
        """flush() saves changes made with persist=False."""
        persistence = StatePersistence(state_dir=tmp_dir)
        store1 = SharedVariableStore(persistence=persistence)
        store1.set('fast', 1, persist=False)
        store1.set('fast', 2, persist=False)

        # Not yet persisted — new store won't see it
        store_check = SharedVariableStore(persistence=StatePersistence(state_dir=tmp_dir))
        assert store_check.get('fast') is None

        # Flush and check again
        store1.flush()
        store_after = SharedVariableStore(persistence=StatePersistence(state_dir=tmp_dir))
        assert store_after.get('fast') == 2


class TestSharedVariableStoreThreadSafety:

    def test_concurrent_set_get(self, store):
        """Multiple threads setting and getting should not corrupt data."""
        errors = []
        iterations = 200

        def writer(thread_id):
            try:
                for i in range(iterations):
                    store.set(f't{thread_id}', i, persist=False)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(iterations):
                    store.get_all()
                    store.keys()
            except Exception as e:
                errors.append(e)

        threads = []
        for t in range(10):
            threads.append(threading.Thread(target=writer, args=(t,)))
        threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"

        # Each writer's variable should have its final value
        for t in range(10):
            assert store.get(f't{t}') == iterations - 1


# =============================================================================
# VarsAPI Tests
# =============================================================================


class TestVarsAPI:

    def test_attribute_read(self, vars_api, store):
        store.set('temp', 72.5)
        assert vars_api.temp == 72.5

    def test_attribute_read_missing(self, vars_api):
        assert vars_api.missing_var == 0.0

    def test_index_read(self, vars_api, store):
        store.set('pressure', 14.7)
        assert vars_api['pressure'] == 14.7

    def test_index_read_missing(self, vars_api):
        assert vars_api['nope'] == 0.0

    def test_contains(self, vars_api, store):
        assert 'x' not in vars_api
        store.set('x', 1)
        assert 'x' in vars_api

    def test_get_with_default(self, vars_api, store):
        assert vars_api.get('missing', 99) == 99
        store.set('present', 42)
        assert vars_api.get('present', 99) == 42

    def test_set(self, vars_api):
        assert vars_api.set('val', 123)
        assert vars_api.val == 123

    def test_reset(self, vars_api):
        vars_api.set('counter', 50)
        vars_api.reset('counter')
        assert vars_api.counter == 0

    def test_keys(self, vars_api):
        vars_api.set('a', 1)
        vars_api.set('b', 2)
        assert sorted(vars_api.keys()) == ['a', 'b']

    def test_delete(self, vars_api):
        vars_api.set('tmp', 1)
        assert vars_api.delete('tmp')
        assert 'tmp' not in vars_api

    def test_flush(self, vars_api, store):
        """flush() delegates to store."""
        vars_api.set('x', 1, persist=False)
        vars_api.flush()
        # No error is success; actual persistence tested in store tests

    def test_string_variable(self, vars_api):
        vars_api.set('batch', 'RUN-042')
        assert vars_api.batch == 'RUN-042'
        vars_api.reset('batch')
        assert vars_api.batch == ''

    def test_private_attr_raises(self, vars_api):
        with pytest.raises(AttributeError):
            _ = vars_api._internal
