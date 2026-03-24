"""
Tests for historian.py — SQLite historian engine.

Covers:
- Initialization and schema creation
- Channel ID caching (auto-register on first encounter)
- write_batch: numeric filtering, NaN/Inf skip, 1Hz rate gating, rounding
- query: time range, channel filtering, decimation, uPlot-aligned output
- get_available_tags: channel listing with time range and point count
- export_csv: CSV string generation
- prune: retention-based deletion, orphan channel cleanup
- get_stats: database statistics
- close: WAL checkpoint and connection cleanup
- Thread safety: concurrent read/write
"""

import math
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

# Add daq_service to path
service_dir = Path(__file__).parent.parent / "services" / "daq_service"
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

from historian import Historian

class TestHistorianInit:
    """Tests for Historian initialization and schema."""

    def test_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "subdir" / "test.db")
        h = Historian(db_path)
        assert os.path.exists(db_path)
        h.close()

    def test_creates_parent_directories(self, tmp_path):
        db_path = str(tmp_path / "deep" / "nested" / "test.db")
        h = Historian(db_path)
        assert os.path.isdir(str(tmp_path / "deep" / "nested"))
        h.close()

    def test_schema_tables_exist(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        h = Historian(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        assert 'channels' in tables
        assert 'datapoints' in tables
        conn.close()
        h.close()

    def test_default_retention_days(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        assert h._retention_days == 30
        h.close()

    def test_custom_retention_days(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"), retention_days=7)
        assert h._retention_days == 7
        h.close()

    def test_wal_mode_enabled(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        h = Historian(db_path)
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == 'wal'
        conn.close()
        h.close()

    def test_empty_channel_cache_on_new_db(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        assert len(h._channel_ids) == 0
        h.close()

class TestWriteBatch:
    """Tests for write_batch: data insertion, filtering, rate gating."""

    @pytest.fixture
    def historian(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        yield h
        h.close()

    def test_writes_numeric_values(self, historian):
        historian._last_write_ts = 0  # bypass rate gate
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'temp': 23.5, 'pressure': 14.7})
        assert historian._points_written == 2

    def test_skips_non_numeric_values(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {
            'temp': 23.5,
            'status': 'OK',
            'label': None,
            'flag': True,  # bool is subclass of int — should be written
        })
        # temp + flag = 2 numeric values written
        assert historian._points_written == 2

    def test_skips_nan_and_inf(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {
            'good': 42.0,
            'nan_val': float('nan'),
            'inf_val': float('inf'),
            'neg_inf': float('-inf'),
        })
        assert historian._points_written == 1  # only 'good'

    def test_rounds_floats_to_6_decimals(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'precise': 3.141592653589793})

        # Query the raw value from DB
        cursor = historian._conn.execute(
            "SELECT val FROM datapoints"
        )
        val = cursor.fetchone()[0]
        assert val == 3.141593  # rounded to 6 decimals

    def test_integers_not_rounded(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'count': 42})

        cursor = historian._conn.execute("SELECT val FROM datapoints")
        val = cursor.fetchone()[0]
        assert val == 42

    def test_rate_gating_skips_fast_writes(self, historian):
        ts = int(time.time() * 1000)
        # First write should succeed (last_write_ts starts at 0)
        historian._last_write_ts = 0
        historian.write_batch(ts, {'temp': 23.5})
        assert historian._points_written == 1

        # Second write within 1s should be skipped
        historian.write_batch(ts + 100, {'temp': 24.0})
        assert historian._points_written == 1  # still 1

    def test_rate_gating_allows_after_1_second(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'temp': 23.5})
        assert historian._points_written == 1

        # Manually advance the write timestamp
        historian._last_write_ts = time.monotonic() - 1.1
        historian.write_batch(ts + 1000, {'temp': 24.0})
        assert historian._points_written == 2

    def test_auto_creates_channel_on_first_write(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'new_channel': 99.0})
        assert 'new_channel' in historian._channel_ids

    def test_channel_units_stored(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {'temp': 23.5}, units={'temp': 'degC'})

        cursor = historian._conn.execute(
            "SELECT unit FROM channels WHERE name = ?", ('temp',)
        )
        unit = cursor.fetchone()[0]
        assert unit == 'degC'

    def test_empty_values_dict(self, historian):
        historian._last_write_ts = 0
        ts = int(time.time() * 1000)
        historian.write_batch(ts, {})
        assert historian._points_written == 0

class TestQuery:
    """Tests for query: time range filtering, decimation, output format."""

    @pytest.fixture
    def historian_with_data(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        # Insert 10 points across 10 seconds
        base_ts = 1700000000000  # fixed base timestamp (ms)
        for i in range(10):
            h._last_write_ts = 0  # bypass rate gate
            h.write_batch(base_ts + i * 1000, {
                'temp': 20.0 + i,
                'pressure': 14.0 + i * 0.1,
            })
        yield h, base_ts
        h.close()

    def test_query_returns_all_data_in_range(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp', 'pressure'], base_ts, base_ts + 9000)
        assert result['success'] is True
        assert len(result['timestamps']) == 10
        assert len(result['series']['temp']) == 10
        assert len(result['series']['pressure']) == 10

    def test_query_timestamps_in_seconds(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts, base_ts + 9000)
        # Timestamps should be in seconds (divided by 1000)
        assert result['timestamps'][0] == base_ts / 1000.0

    def test_query_partial_time_range(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts + 3000, base_ts + 6000)
        assert result['success'] is True
        assert len(result['timestamps']) == 4  # points at 3s, 4s, 5s, 6s

    def test_query_nonexistent_channel(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['nonexistent'], base_ts, base_ts + 9000)
        assert result['success'] is True
        assert len(result['timestamps']) == 0
        assert result['total_points'] == 0

    def test_query_single_channel(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts, base_ts + 9000)
        assert 'temp' in result['channels']
        assert 'pressure' not in result['channels']

    def test_query_decimation(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts, base_ts + 9000, max_points=5)
        assert result['success'] is True
        assert result['decimated'] is True
        assert len(result['timestamps']) == 5
        assert result['total_points'] == 10

    def test_query_no_decimation_when_under_limit(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts, base_ts + 9000, max_points=100)
        assert result['decimated'] is False
        assert len(result['timestamps']) == 10

    def test_query_empty_range(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp'], base_ts + 100000, base_ts + 200000)
        assert result['success'] is True
        assert len(result['timestamps']) == 0

    def test_query_values_aligned(self, historian_with_data):
        h, base_ts = historian_with_data
        result = h.query(['temp', 'pressure'], base_ts, base_ts + 2000)
        # First point
        assert result['series']['temp'][0] == 20.0
        assert result['series']['pressure'][0] == 14.0
        # Third point
        assert result['series']['temp'][2] == 22.0
        assert abs(result['series']['pressure'][2] - 14.2) < 0.001

class TestGetAvailableTags:
    """Tests for get_available_tags."""

    def test_returns_all_channels(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        ts = int(time.time() * 1000)
        h.write_batch(ts, {'ch_a': 1.0, 'ch_b': 2.0, 'ch_c': 3.0})

        tags = h.get_available_tags()
        names = [t['name'] for t in tags]
        assert 'ch_a' in names
        assert 'ch_b' in names
        assert 'ch_c' in names
        h.close()

    def test_tag_includes_point_count(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        for i in range(3):
            h._last_write_ts = 0
            h.write_batch(1700000000000 + i * 1000, {'sensor': float(i)})

        tags = h.get_available_tags()
        sensor_tag = next(t for t in tags if t['name'] == 'sensor')
        assert sensor_tag['point_count'] == 3
        h.close()

    def test_tag_includes_time_range(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'sensor': 1.0})
        h._last_write_ts = 0
        h.write_batch(1700000005000, {'sensor': 2.0})

        tags = h.get_available_tags()
        sensor_tag = next(t for t in tags if t['name'] == 'sensor')
        assert sensor_tag['first_ts'] == 1700000000.0
        assert sensor_tag['last_ts'] == 1700000005.0
        h.close()

    def test_tag_includes_unit(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'temp': 23.5}, units={'temp': 'degC'})

        tags = h.get_available_tags()
        temp_tag = next(t for t in tags if t['name'] == 'temp')
        assert temp_tag['unit'] == 'degC'
        h.close()

    def test_empty_db_returns_empty_list(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        tags = h.get_available_tags()
        assert tags == []
        h.close()

class TestExportCSV:
    """Tests for export_csv."""

    def test_csv_has_header_and_data(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'temp': 23.5, 'pressure': 14.7})
        h._last_write_ts = 0
        h.write_batch(1700000001000, {'temp': 24.0, 'pressure': 14.8})

        csv_str = h.export_csv(['temp', 'pressure'], 1700000000000, 1700000001000)
        lines = csv_str.strip().split('\n')
        assert len(lines) == 3  # header + 2 data rows
        assert 'timestamp' in lines[0].lower()
        assert 'temp' in lines[0]
        assert 'pressure' in lines[0]
        h.close()

    def test_csv_empty_when_no_data(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        csv_str = h.export_csv(['temp'], 0, 1)
        assert csv_str == ''
        h.close()

    def test_csv_no_decimation(self, tmp_path):
        """export_csv should return full resolution (no decimation)."""
        h = Historian(str(tmp_path / "test.db"))
        for i in range(100):
            h._last_write_ts = 0
            h.write_batch(1700000000000 + i * 1000, {'temp': float(i)})

        csv_str = h.export_csv(['temp'], 1700000000000, 1700000099000)
        lines = csv_str.strip().split('\n')
        assert len(lines) == 101  # header + 100 data rows
        h.close()

class TestPrune:
    """Tests for prune: retention-based data deletion."""

    def test_prune_deletes_old_data(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"), retention_days=1)
        # Insert data from 2 days ago
        old_ts = int((time.time() - 2 * 86400) * 1000)
        h._last_write_ts = 0
        h.write_batch(old_ts, {'temp': 23.5})

        # Insert recent data
        recent_ts = int(time.time() * 1000)
        h._last_write_ts = 0
        h.write_batch(recent_ts, {'temp': 24.0})

        deleted = h.prune()
        assert deleted == 1  # old point deleted

        # Recent data should still exist
        result = h.query(['temp'], recent_ts - 1000, recent_ts + 1000)
        assert len(result['timestamps']) == 1
        h.close()

    def test_prune_returns_zero_when_nothing_to_delete(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"), retention_days=30)
        h._last_write_ts = 0
        h.write_batch(int(time.time() * 1000), {'temp': 23.5})

        deleted = h.prune()
        assert deleted == 0
        h.close()

    def test_prune_removes_orphan_channels(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"), retention_days=1)
        # Insert old data for a channel
        old_ts = int((time.time() - 2 * 86400) * 1000)
        h._last_write_ts = 0
        h.write_batch(old_ts, {'old_channel': 1.0})
        assert 'old_channel' in h._channel_ids

        h.prune()
        # Channel should be removed from cache after pruning orphans
        assert 'old_channel' not in h._channel_ids
        h.close()

class TestGetStats:
    """Tests for get_stats."""

    def test_stats_on_empty_db(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        stats = h.get_stats()
        assert stats['total_points'] == 0
        assert stats['channel_count'] == 0
        assert stats['oldest_ts'] is None
        assert stats['newest_ts'] is None
        assert stats['retention_days'] == 30
        assert stats['points_written'] == 0
        assert stats['write_errors'] == 0
        h.close()

    def test_stats_with_data(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'a': 1.0, 'b': 2.0})
        h._last_write_ts = 0
        h.write_batch(1700000001000, {'a': 3.0, 'b': 4.0})

        stats = h.get_stats()
        assert stats['total_points'] == 4
        assert stats['channel_count'] == 2
        assert stats['oldest_ts'] == 1700000000.0
        assert stats['newest_ts'] == 1700000001.0
        assert stats['points_written'] == 4
        h.close()

    def test_stats_db_size_nonzero(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'a': 1.0})

        stats = h.get_stats()
        assert stats['db_size_bytes'] > 0
        h.close()

class TestClose:
    """Tests for close."""

    def test_close_sets_conn_to_none(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        assert h._conn is not None
        h.close()
        assert h._conn is None

    def test_double_close_does_not_raise(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h.close()
        h.close()  # Should not raise

class TestChannelCache:
    """Tests for channel ID caching behavior."""

    def test_channel_ids_cached_after_write(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'sensor_1': 1.0, 'sensor_2': 2.0})

        assert 'sensor_1' in h._channel_ids
        assert 'sensor_2' in h._channel_ids
        assert isinstance(h._channel_ids['sensor_1'], int)
        h.close()

    def test_channel_cache_survives_reopen(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        h1 = Historian(db_path)
        h1._last_write_ts = 0
        h1.write_batch(1700000000000, {'persistent_ch': 42.0})
        h1.close()

        # Reopen — cache should be loaded from DB
        h2 = Historian(db_path)
        assert 'persistent_ch' in h2._channel_ids
        h2.close()

    def test_channel_ids_are_unique(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        h._last_write_ts = 0
        h.write_batch(1700000000000, {'a': 1.0, 'b': 2.0, 'c': 3.0})

        ids = list(h._channel_ids.values())
        assert len(ids) == len(set(ids))  # all unique
        h.close()

class TestConcurrency:
    """Tests for thread safety."""

    def test_concurrent_writes(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        errors = []

        def writer(thread_id):
            try:
                for i in range(20):
                    h._last_write_ts = 0  # bypass rate gate for testing
                    ts = 1700000000000 + thread_id * 100000 + i * 1000
                    h.write_batch(ts, {f'ch_{thread_id}': float(i)})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All 4 channels should have been created
        assert len(h._channel_ids) == 4
        h.close()

    def test_concurrent_read_write(self, tmp_path):
        h = Historian(str(tmp_path / "test.db"))
        errors = []

        # Pre-populate some data
        for i in range(10):
            h._last_write_ts = 0
            h.write_batch(1700000000000 + i * 1000, {'sensor': float(i)})

        def writer():
            try:
                for i in range(10, 30):
                    h._last_write_ts = 0
                    h.write_batch(1700000000000 + i * 1000, {'sensor': float(i)})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    h.query(['sensor'], 1700000000000, 1700000030000)
                    h.get_available_tags()
                    h.get_stats()
            except Exception as e:
                errors.append(e)

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert len(errors) == 0
        h.close()
