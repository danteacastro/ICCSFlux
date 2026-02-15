"""
SQLite Historian — silent background data recorder for the DAQ service.

Records ALL channel values at 1 Hz into a local SQLite database with configurable
retention (default 30 days). Provides query and export APIs for the frontend
Data Viewer. Uses WAL mode for concurrent read/write safety.

The historian runs unconditionally — it does not depend on recording being active.
Users never configure or interact with the database directly; the frontend
Data Viewer composable queries it via MQTT commands.
"""

import io
import csv
import math
import os
import sqlite3
import threading
import time
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Historian:
    """Silent SQLite historian for continuous 1 Hz data recording."""

    def __init__(self, db_path: str, retention_days: int = 30):
        self._db_path = db_path
        self._retention_days = max(1, retention_days)  # Minimum 1 day retention
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._channel_ids: Dict[str, int] = {}  # name -> id cache
        self._last_write_ts: float = 0.0  # epoch seconds, for 1 Hz rate gating
        self._points_written: int = 0
        self._write_errors: int = 0

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._connect()
        self._load_channel_cache()
        logger.info(f"Historian initialized: {db_path} "
                     f"({len(self._channel_ids)} channels, {self._retention_days}d retention)")

    def _connect(self):
        """Open SQLite connection and initialize schema."""
        conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=10.0,
        )
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8000")  # 8 MB cache
            conn.execute("PRAGMA temp_store=MEMORY")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id   INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    unit TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datapoints (
                    ts  INTEGER NOT NULL,
                    ch  INTEGER NOT NULL,
                    val REAL,
                    PRIMARY KEY (ts, ch)
                ) WITHOUT ROWID
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_datapoints_ts ON datapoints(ts)
            """)
            conn.commit()
            self._conn = conn
        except Exception:
            conn.close()
            raise

    def _load_channel_cache(self):
        """Load channel name -> id mapping from DB into memory."""
        with self._lock:
            cursor = self._conn.execute("SELECT id, name FROM channels")
            self._channel_ids = {name: cid for cid, name in cursor.fetchall()}

    def _get_or_create_channel_id(self, name: str, unit: str = '') -> int:
        """Get channel ID from cache, creating a new DB entry on first encounter."""
        cid = self._channel_ids.get(name)
        if cid is not None:
            return cid

        # New channel — insert and cache
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO channels (name, unit) VALUES (?, ?)",
                (name, unit)
            )
            cursor = self._conn.execute(
                "SELECT id FROM channels WHERE name = ?", (name,)
            )
            row = cursor.fetchone()
            if row:
                self._channel_ids[name] = row[0]
                return row[0]
        except Exception as e:
            logger.warning(f"Historian: channel insert error for '{name}': {e}")

        return -1

    def write_batch(self, timestamp_ms: int, values: Dict[str, Any],
                    units: Optional[Dict[str, str]] = None) -> None:
        """
        Write a batch of channel values at the given timestamp.

        Rate-gated to 1 Hz — calls within 1 second of the last write are skipped.
        Filters to numeric values only (int/float), skips NaN/Inf.

        Args:
            timestamp_ms: Unix timestamp in milliseconds.
            values: {channel_name: value, ...}
            units: Optional {channel_name: unit_string, ...} for first-seen channels.
        """
        now = time.monotonic()
        if now - self._last_write_ts < 1.0:
            return  # Rate-gated: skip writes within 1 Hz window

        self._last_write_ts = now
        units = units or {}

        with self._lock:
            try:
                rows = []
                for name, val in values.items():
                    # Filter to numeric only, skip NaN/Inf
                    if not isinstance(val, (int, float)):
                        continue
                    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                        continue

                    cid = self._get_or_create_channel_id(name, units.get(name, ''))
                    if cid < 0:
                        continue

                    rounded = round(val, 6) if isinstance(val, float) else val
                    rows.append((timestamp_ms, cid, rounded))

                if rows:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO datapoints (ts, ch, val) VALUES (?, ?, ?)",
                        rows
                    )
                    self._conn.commit()
                    self._points_written += len(rows)

            except Exception as e:
                self._write_errors += 1
                if self._write_errors <= 5 or self._write_errors % 100 == 0:
                    logger.error(f"Historian write error ({self._write_errors}): {e}")
                try:
                    self._conn.rollback()
                except Exception:
                    pass

    def query(self, channels: List[str], start_ms: int, end_ms: int,
              max_points: int = 2000) -> Dict[str, Any]:
        """
        Query historical data for the given channels and time range.

        Returns data aligned for uPlot: {timestamps: [...], series: {ch: [...]}, channels: [...]}
        Auto-decimates if total points exceed max_points.

        Args:
            channels: List of channel names to query.
            start_ms: Start timestamp (Unix ms, inclusive).
            end_ms: End timestamp (Unix ms, inclusive).
            max_points: Maximum data points per channel (decimation applied if exceeded).

        Returns:
            Dict with 'success', 'timestamps', 'series', 'channels', 'total_points', 'decimated'.
        """
        with self._lock:
            try:
                # Resolve channel names to IDs
                ch_ids = []
                ch_names = []
                for name in channels:
                    cid = self._channel_ids.get(name)
                    if cid is not None:
                        ch_ids.append(cid)
                        ch_names.append(name)

                if not ch_ids:
                    return {
                        'success': True,
                        'timestamps': [],
                        'series': {},
                        'channels': [],
                        'total_points': 0,
                        'decimated': False,
                    }

                # Get distinct timestamps in range
                placeholders = ','.join('?' * len(ch_ids))
                cursor = self._conn.execute(
                    f"SELECT DISTINCT ts FROM datapoints "
                    f"WHERE ch IN ({placeholders}) AND ts >= ? AND ts <= ? "
                    f"ORDER BY ts",
                    (*ch_ids, start_ms, end_ms)
                )
                all_timestamps = [row[0] for row in cursor.fetchall()]
                total_points = len(all_timestamps)

                # Decimate if needed (evenly-spaced sampling)
                decimated = False
                if total_points > max_points and max_points > 0:
                    step = total_points / max_points
                    indices = [int(i * step) for i in range(max_points)]
                    # Always include last point
                    if indices[-1] != total_points - 1:
                        indices[-1] = total_points - 1
                    all_timestamps = [all_timestamps[i] for i in indices]
                    decimated = True

                if not all_timestamps:
                    return {
                        'success': True,
                        'timestamps': [],
                        'series': {name: [] for name in ch_names},
                        'channels': ch_names,
                        'total_points': total_points,
                        'decimated': decimated,
                    }

                # Fetch values for selected timestamps and channels
                ts_set = set(all_timestamps)
                ts_placeholders = ','.join('?' * len(all_timestamps))
                cursor = self._conn.execute(
                    f"SELECT ts, ch, val FROM datapoints "
                    f"WHERE ch IN ({placeholders}) AND ts IN ({ts_placeholders}) "
                    f"ORDER BY ts",
                    (*ch_ids, *all_timestamps)
                )

                # Build lookup: (ts, ch_id) -> value
                value_map: Dict[tuple, float] = {}
                for ts, ch, val in cursor.fetchall():
                    value_map[(ts, ch)] = val

                # Build aligned series
                series: Dict[str, List[Optional[float]]] = {name: [] for name in ch_names}
                for ts in all_timestamps:
                    for name, cid in zip(ch_names, ch_ids):
                        series[name].append(value_map.get((ts, cid)))

                # Convert timestamps to seconds for uPlot (it uses epoch seconds)
                timestamps_sec = [ts / 1000.0 for ts in all_timestamps]

                return {
                    'success': True,
                    'timestamps': timestamps_sec,
                    'series': series,
                    'channels': ch_names,
                    'total_points': total_points,
                    'decimated': decimated,
                }

            except Exception as e:
                logger.error(f"Historian query error: {e}")
                return {
                    'success': False,
                    'error': str(e),
                    'timestamps': [],
                    'series': {},
                    'channels': [],
                    'total_points': 0,
                    'decimated': False,
                }

    def get_available_tags(self) -> List[Dict[str, Any]]:
        """
        List all channels with their time range and point count.

        Returns:
            List of {name, unit, first_ts, last_ts, point_count}
        """
        with self._lock:
            try:
                cursor = self._conn.execute("""
                    SELECT c.name, c.unit,
                           MIN(d.ts) as first_ts,
                           MAX(d.ts) as last_ts,
                           COUNT(d.ts) as point_count
                    FROM channels c
                    LEFT JOIN datapoints d ON d.ch = c.id
                    GROUP BY c.id
                    ORDER BY c.name
                """)
                tags = []
                for name, unit, first_ts, last_ts, count in cursor.fetchall():
                    tags.append({
                        'name': name,
                        'unit': unit or '',
                        'first_ts': (first_ts / 1000.0) if first_ts else None,
                        'last_ts': (last_ts / 1000.0) if last_ts else None,
                        'point_count': count or 0,
                    })
                return tags
            except Exception as e:
                logger.error(f"Historian get_available_tags error: {e}")
                return []

    def export_csv(self, channels: List[str], start_ms: int, end_ms: int) -> str:
        """
        Export historical data as CSV string.

        Args:
            channels: Channel names to include.
            start_ms: Start timestamp (Unix ms).
            end_ms: End timestamp (Unix ms).

        Returns:
            CSV string with header row + data rows (no decimation, full resolution).
        """
        # Query without decimation limit
        result = self.query(channels, start_ms, end_ms, max_points=0)
        if not result.get('success') or not result.get('timestamps'):
            return ''

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['timestamp'] + result['channels'])

        # Data rows
        timestamps = result['timestamps']
        series = result['series']
        ch_names = result['channels']

        for i, ts in enumerate(timestamps):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            row = [dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]]
            for name in ch_names:
                val = series[name][i]
                row.append('' if val is None else str(val))
            writer.writerow(row)

        return output.getvalue()

    def prune(self) -> int:
        """
        Delete data older than retention_days.

        Returns:
            Number of rows deleted.
        """
        cutoff_ms = int((time.time() - self._retention_days * 86400) * 1000)

        with self._lock:
            try:
                cursor = self._conn.execute(
                    "DELETE FROM datapoints WHERE ts < ?", (cutoff_ms,)
                )
                deleted = cursor.rowcount
                self._conn.commit()

                if deleted > 0:
                    logger.info(f"Historian pruned {deleted:,} points older than {self._retention_days} days")

                # Also remove orphan channels (no datapoints left)
                self._conn.execute("""
                    DELETE FROM channels WHERE id NOT IN (
                        SELECT DISTINCT ch FROM datapoints
                    )
                """)
                self._conn.commit()

                # Reload cache after pruning orphans
                self._load_channel_cache_unlocked()

                return deleted
            except Exception as e:
                logger.error(f"Historian prune error: {e}")
                return 0

    def _load_channel_cache_unlocked(self):
        """Reload channel cache (must be called while holding self._lock)."""
        cursor = self._conn.execute("SELECT id, name FROM channels")
        self._channel_ids = {name: cid for cid, name in cursor.fetchall()}

    def get_stats(self) -> Dict[str, Any]:
        """
        Get historian database statistics.

        Returns:
            Dict with db_size_bytes, total_points, channel_count,
            oldest_ts, newest_ts, retention_days, points_written, write_errors.
        """
        with self._lock:
            try:
                db_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
                # Include WAL file size
                wal_path = self._db_path + '-wal'
                if os.path.exists(wal_path):
                    db_size += os.path.getsize(wal_path)

                cursor = self._conn.execute("SELECT COUNT(*) FROM datapoints")
                total_points = cursor.fetchone()[0]

                cursor = self._conn.execute("SELECT COUNT(*) FROM channels")
                channel_count = cursor.fetchone()[0]

                cursor = self._conn.execute("SELECT MIN(ts), MAX(ts) FROM datapoints")
                row = cursor.fetchone()
                oldest_ts = (row[0] / 1000.0) if row[0] else None
                newest_ts = (row[1] / 1000.0) if row[1] else None

                return {
                    'db_size_bytes': db_size,
                    'total_points': total_points,
                    'channel_count': channel_count,
                    'oldest_ts': oldest_ts,
                    'newest_ts': newest_ts,
                    'retention_days': self._retention_days,
                    'points_written': self._points_written,
                    'write_errors': self._write_errors,
                }
            except Exception as e:
                logger.error(f"Historian stats error: {e}")
                return {
                    'db_size_bytes': 0,
                    'total_points': 0,
                    'channel_count': 0,
                    'oldest_ts': None,
                    'newest_ts': None,
                    'retention_days': self._retention_days,
                    'points_written': self._points_written,
                    'write_errors': self._write_errors,
                }

    def close(self):
        """Checkpoint WAL and close database connection."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._conn.close()
                    logger.info(f"Historian closed ({self._points_written:,} points written, "
                                f"{self._write_errors} errors)")
                except Exception as e:
                    logger.warning(f"Historian close error: {e}")
                self._conn = None
