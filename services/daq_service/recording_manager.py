#!/usr/bin/env python3
"""
Recording Manager for NISystem
Handles data recording with configurable options, triggered recording, and script values
"""

import csv
import json
import os
import shutil
import stat
import hashlib
import sys
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import logging

# Platform-specific file locking
if sys.platform == 'win32':
    try:
        import msvcrt
        _HAS_FILE_LOCK = True
    except ImportError:
        _HAS_FILE_LOCK = False
else:
    try:
        import fcntl
        _HAS_FILE_LOCK = True
    except ImportError:
        _HAS_FILE_LOCK = False


def _lock_file(fh):
    """Acquire an exclusive OS-level lock on an open file handle."""
    if not _HAS_FILE_LOCK:
        return
    try:
        if sys.platform == 'win32':
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError) as e:
        logging.getLogger('RecordingManager').warning(f"Could not acquire file lock: {e}")


def _unlock_file(fh):
    """Release OS-level lock on an open file handle."""
    if not _HAS_FILE_LOCK:
        return
    try:
        if sys.platform == 'win32':
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except (OSError, IOError):
        pass

logger = logging.getLogger('RecordingManager')

# Maximum pre-trigger buffer size to prevent memory exhaustion
# Even if user requests more, we cap at this limit
MAX_PRE_TRIGGER_SAMPLES = 10000

# Minimum free disk space required to start recording (100 MB)
MIN_FREE_DISK_BYTES = 100 * 1024 * 1024


def _get_default_data_path() -> str:
    """Get platform-appropriate default data path relative to project root"""
    # Default to 'data' folder relative to daq_service location
    service_dir = Path(__file__).parent
    project_root = service_dir.parent.parent
    return str(project_root / "data")


@dataclass
class RecordingConfig:
    """Configuration for data recording"""
    # File settings - uses project-relative path by default
    base_path: str = field(default_factory=_get_default_data_path)
    file_prefix: str = "recording"
    file_format: str = "csv"  # 'csv' or 'tdms'

    # Logging rate
    sample_interval: float = 1.0  # Interval between samples
    sample_interval_unit: str = "seconds"  # 'seconds' or 'milliseconds'
    decimation: int = 1  # Log every Nth sample

    # File Rotation Strategy
    rotation_mode: str = "single"  # 'single', 'time', 'size', 'samples', 'session'
    max_file_size_mb: float = 100.0
    max_file_duration_s: float = 3600.0  # seconds
    max_file_samples: int = 10000  # for sample-count rotation

    # Naming Convention
    naming_pattern: str = "timestamp"  # 'timestamp', 'sequential', 'custom'
    include_date: bool = True
    include_time: bool = True
    include_channels_in_name: bool = False
    sequential_start: int = 1  # Starting number for sequential naming
    sequential_padding: int = 3  # Zero-padding (e.g., 001, 002)
    custom_suffix: str = ""

    # Directory Organization
    directory_structure: str = "flat"  # 'flat', 'daily', 'monthly', 'experiment'
    experiment_name: str = ""  # For experiment-based organization

    # Buffer/Write Strategy
    write_mode: str = "buffered"  # 'immediate', 'buffered'
    buffer_size: int = 100  # samples to buffer before flush
    flush_interval_s: float = 5.0  # Max time before flush (seconds)

    # File Reuse
    reuse_file: bool = False  # If True, stop/start appends to the same file instead of creating new

    # ALCOA+ Data Integrity Settings
    append_only: bool = False  # If True, files become read-only once recording stops
    verify_on_close: bool = True  # Compute and store checksum when file closes
    include_audit_metadata: bool = True  # Include operator, timestamps, session info

    # What to do when limit reached (for rotation modes)
    on_limit_reached: str = "new_file"  # 'new_file', 'stop', 'circular'
    circular_max_files: int = 10  # For circular mode: keep last N files

    # Recording mode
    mode: str = "manual"  # 'manual', 'triggered', 'scheduled'

    # Triggered mode settings
    trigger_channel: str = ""
    trigger_condition: str = "above"  # 'above', 'below', 'change'
    trigger_value: float = 0.0
    trigger_hysteresis: float = 0.0
    pre_trigger_samples: int = 0
    post_trigger_samples: int = 0

    # Scheduled mode settings
    schedule_start: str = "08:00"
    schedule_end: str = "17:00"
    schedule_days: List[str] = field(default_factory=lambda: ['mon', 'tue', 'wed', 'thu', 'fri'])

    # Channel selection
    selected_channels: List[str] = field(default_factory=list)  # Empty = all channels
    include_scripts: bool = True  # Include calculated params and transforms

    # PostgreSQL database storage (optional, alongside file recording)
    db_enabled: bool = False
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "iccsflux"
    db_user: str = "iccsflux"
    db_password: str = ""
    db_table: str = "recording_data"
    db_batch_size: int = 50  # Rows to batch before INSERT
    db_timescale: bool = False  # Convert table to TimescaleDB hypertable

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'RecordingConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def effective_sample_rate_hz(self) -> float:
        """Get effective sample rate in Hz"""
        interval_s = self.sample_interval
        if self.sample_interval_unit == "milliseconds":
            interval_s = self.sample_interval / 1000.0
        return (1.0 / interval_s) / self.decimation if interval_s > 0 else 0


class PostgreSQLWriter:
    """
    Optional PostgreSQL data writer for recording manager.
    Stores time-series data in a JSONB-based schema for flexibility.
    psycopg2-binary is a pip-only dependency (no PostgreSQL install needed).
    """

    def __init__(self, config: 'RecordingConfig'):
        self._config = config
        self._conn = None
        self._batch: List[tuple] = []
        self._session_id: Optional[str] = None
        self._rows_written = 0
        self._available = False

        try:
            import psycopg2
            self._psycopg2 = psycopg2
            self._available = True
        except ImportError:
            logger.warning("psycopg2-binary not installed - PostgreSQL storage unavailable")

    @property
    def available(self) -> bool:
        return self._available

    def connect(self, session_id: str) -> bool:
        """Connect to PostgreSQL and ensure table exists."""
        if not self._available:
            return False

        self._session_id = session_id
        self._rows_written = 0

        try:
            self._conn = self._psycopg2.connect(
                host=self._config.db_host,
                port=self._config.db_port,
                dbname=self._config.db_name,
                user=self._config.db_user,
                password=self._config.db_password,
                connect_timeout=5,
            )
            self._conn.autocommit = False
            self._ensure_table()
            logger.info(f"PostgreSQL connected: {self._config.db_host}:{self._config.db_port}/{self._config.db_name}")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            self._conn = None
            return False

    def _ensure_table(self):
        """Create recording table if it doesn't exist.
        Schema is TimescaleDB-compatible: no BIGSERIAL PK (hypertable requires
        the time column in any unique constraint). Uses ts as the natural ordering.
        """
        table = self._safe_table_name()
        with self._conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    ts TIMESTAMPTZ NOT NULL,
                    session_id TEXT,
                    channel_values JSONB NOT NULL
                );
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_ts ON {table} (ts DESC);
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_session ON {table} (session_id, ts DESC);
            """)

            # Convert to TimescaleDB hypertable if requested and extension is available
            if self._config.db_timescale:
                try:
                    # Check if TimescaleDB extension exists
                    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
                    if cur.fetchone():
                        # Check if already a hypertable
                        cur.execute(
                            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s",
                            (table,)
                        )
                        if not cur.fetchone():
                            cur.execute(f"SELECT create_hypertable('{table}', 'ts', migrate_data => true)")
                            logger.info(f"TimescaleDB hypertable created for '{table}'")
                        else:
                            logger.info(f"Table '{table}' is already a TimescaleDB hypertable")
                    else:
                        logger.warning("TimescaleDB extension not installed - using plain PostgreSQL table")
                except Exception as e:
                    logger.warning(f"TimescaleDB hypertable setup skipped: {e}")

        self._conn.commit()
        logger.info(f"PostgreSQL table '{table}' ready")

    def _safe_table_name(self) -> str:
        """Sanitize table name to prevent SQL injection."""
        import re
        name = re.sub(r'[^a-zA-Z0-9_]', '', self._config.db_table)
        return name or 'recording_data'

    def write_row(self, values: Dict[str, Any]):
        """Buffer a row for batch insert."""
        if not self._conn:
            return

        try:
            import json as _json
            timestamp = datetime.now().isoformat()
            # Filter to numeric values for storage
            numeric_values = {}
            for k, v in values.items():
                if isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v or abs(v) == float('inf'))):
                    numeric_values[k] = round(v, 6) if isinstance(v, float) else v

            self._batch.append((timestamp, self._session_id, _json.dumps(numeric_values)))

            if len(self._batch) >= self._config.db_batch_size:
                self._flush()
        except Exception as e:
            logger.warning(f"PostgreSQL write error: {e}")

    def _flush(self):
        """Flush batch to database."""
        if not self._batch or not self._conn:
            return

        table = self._safe_table_name()
        try:
            with self._conn.cursor() as cur:
                # Use executemany for batch insert
                cur.executemany(
                    f"INSERT INTO {table} (ts, session_id, channel_values) VALUES (%s, %s, %s)",
                    self._batch
                )
            self._conn.commit()
            self._rows_written += len(self._batch)
            self._batch = []
        except Exception as e:
            logger.error(f"PostgreSQL flush error: {e}")
            try:
                self._conn.rollback()
            except Exception as e:
                logger.warning(f"PostgreSQL rollback failed: {e}")

    def close(self):
        """Flush remaining data and close connection."""
        if self._batch:
            self._flush()

        if self._conn:
            try:
                self._conn.close()
                logger.info(f"PostgreSQL closed ({self._rows_written} rows written)")
            except Exception as e:
                logger.warning(f"PostgreSQL close error: {e}")
            self._conn = None

    @property
    def rows_written(self) -> int:
        return self._rows_written

    @staticmethod
    def test_connection(host: str, port: int, dbname: str, user: str, password: str) -> tuple:
        """Test a PostgreSQL connection. Returns (success, message)."""
        try:
            import psycopg2
        except ImportError:
            return False, "psycopg2-binary not installed"

        try:
            conn = psycopg2.connect(
                host=host, port=port, dbname=dbname,
                user=user, password=password,
                connect_timeout=5,
            )
            # Check server version
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
            conn.close()
            return True, f"Connected: {version.split(',')[0]}"
        except Exception as e:
            return False, str(e)


@dataclass
class RecordingFile:
    """Information about a recorded file"""
    name: str
    path: str
    size: int  # bytes
    duration: float  # seconds
    created: str  # ISO format
    sample_count: int = 0
    channels: List[str] = field(default_factory=list)


class RecordingManager:
    """Manages data recording with advanced features"""

    def __init__(self, default_path: str = None):
        self.config = RecordingConfig()
        if default_path:
            self.config.base_path = default_path

        # Recording state
        self.recording = False
        self._resuming_file = False  # True when reopening a file in append mode
        self.recording_start_time: Optional[datetime] = None
        self.current_file: Optional[Path] = None
        self.current_file_handle = None
        self.csv_writer = None

        # Statistics
        self.bytes_written: int = 0
        self.samples_written: int = 0
        self.file_count: int = 0
        self.current_file_samples: int = 0  # Samples in current file (for sample-count rotation)

        # Decimation counter
        self.decimation_counter: int = 0

        # Time-based sample interval tracking
        self.last_sample_time: Optional[datetime] = None

        # Trigger state
        self.trigger_armed = False
        self.trigger_fired = False
        self.last_trigger_value: Optional[float] = None
        self.pre_trigger_buffer: List[Dict] = []
        self.post_trigger_count: int = 0

        # Script values storage (from frontend scripts)
        self.script_values: Dict[str, Any] = {}

        # Callback for status updates
        self.on_status_change: Optional[Callable] = None

        # Lock for thread safety
        self.lock = threading.Lock()

        # Column order for consistent CSV output
        self.column_order: List[str] = []

        # Write buffer for buffered mode
        self.write_buffer: List[List[Any]] = []
        self.last_flush_time: Optional[datetime] = None

        # Sequential file counter (for sequential naming)
        self.sequential_counter: int = 1

        # Circular file tracking
        self.circular_files: List[Path] = []

        # PostgreSQL writer (optional, alongside CSV)
        self.db_writer: Optional[PostgreSQLWriter] = None

    def configure(self, config_dict: dict):
        """Update recording configuration"""
        with self.lock:
            # If currently recording, don't allow config changes
            if self.recording:
                logger.warning("Cannot change config while recording")
                return False

            self.config = RecordingConfig.from_dict(config_dict)

            # Warn if pre_trigger_samples exceeds max limit
            if self.config.pre_trigger_samples > MAX_PRE_TRIGGER_SAMPLES:
                logger.warning(
                    f"pre_trigger_samples ({self.config.pre_trigger_samples}) exceeds maximum "
                    f"({MAX_PRE_TRIGGER_SAMPLES}). Will be capped to prevent memory exhaustion."
                )

            # Reset sequential counter if configured
            if self.config.naming_pattern == 'sequential':
                self.sequential_counter = self.config.sequential_start

            logger.info(f"Recording config updated: mode={self.config.mode}, "
                       f"interval={self.config.sample_interval}{self.config.sample_interval_unit}, "
                       f"rotation={self.config.rotation_mode}")
            return True

    def get_config(self) -> dict:
        """Get current configuration"""
        return self.config.to_dict()

    def start(self, filename: str = None) -> bool:
        """Start recording"""
        should_notify = False
        with self.lock:
            if self.recording:
                logger.warning("Recording already active")
                return False

            # Build output directory based on directory structure
            output_dir = self._get_output_directory()
            output_dir.mkdir(parents=True, exist_ok=True)

            # Check available disk space before opening file
            try:
                disk_usage = shutil.disk_usage(output_dir)
                if disk_usage.free < MIN_FREE_DISK_BYTES:
                    free_mb = disk_usage.free / (1024 * 1024)
                    logger.error(f"Insufficient disk space to start recording: {free_mb:.0f} MB free (need {MIN_FREE_DISK_BYTES // (1024*1024)} MB)")
                    return False
            except OSError as e:
                logger.warning(f"Could not check disk space: {e}")

            # Determine file: reuse previous or generate new
            reuse_existing = False
            if self.config.reuse_file and self.current_file and self.current_file.exists():
                # Reopen previous file in append mode
                reuse_existing = True
                logger.info(f"Reusing existing recording file: {self.current_file.name}")
            else:
                if not filename:
                    filename = self._generate_filename()
                self.current_file = output_dir / filename

            try:
                if reuse_existing:
                    self.current_file_handle = open(self.current_file, 'a', newline='')
                    _lock_file(self.current_file_handle)
                    # Write a resume marker so the file shows stop/start boundaries
                    self.current_file_handle.write(f"# Resumed: {datetime.now().isoformat()}\n")
                    # Keep existing column_order — skip header rewrite on next write_sample
                    self._resuming_file = True
                    self.csv_writer = None
                else:
                    self.current_file_handle = open(self.current_file, 'w', newline='')
                    _lock_file(self.current_file_handle)
                    self._resuming_file = False
                    self.csv_writer = None  # Will be initialized on first write
                    self.column_order = []

                self.recording = True
                self.recording_start_time = datetime.now()
                self.bytes_written = 0
                self.samples_written = 0
                self.current_file_samples = 0
                self.decimation_counter = 0
                self.last_sample_time = None  # Reset for time-based interval
                self.file_count = 1

                # Reset trigger state
                self.trigger_armed = (self.config.mode == 'triggered')
                self.trigger_fired = False
                self.pre_trigger_buffer = []
                self.post_trigger_count = 0

                # Reset buffer
                self.write_buffer = []
                self.last_flush_time = datetime.now()

                # Track for circular mode
                if self.config.on_limit_reached == 'circular':
                    self.circular_files = [self.current_file]

                # Start PostgreSQL writer if enabled
                if self.config.db_enabled:
                    self.db_writer = PostgreSQLWriter(self.config)
                    if self.db_writer.available:
                        session_id = self.recording_start_time.strftime('%Y%m%d_%H%M%S')
                        if not self.db_writer.connect(session_id):
                            logger.warning("PostgreSQL connection failed - continuing with file-only recording")
                            self.db_writer = None
                    else:
                        logger.warning("psycopg2 not installed - PostgreSQL storage unavailable")
                        self.db_writer = None

                logger.info(f"Recording started: {self.current_file}")
                should_notify = True

            except Exception as e:
                logger.error(f"Failed to start recording: {e}")
                return False

        # Call callback AFTER releasing lock to avoid deadlock
        if should_notify and self.on_status_change:
            self.on_status_change()

        return True

    def _get_output_directory(self) -> Path:
        """Get output directory based on directory structure configuration"""
        base = Path(self.config.base_path)
        now = datetime.now()

        if self.config.directory_structure == 'flat':
            return base
        elif self.config.directory_structure == 'daily':
            return base / now.strftime('%Y') / now.strftime('%m') / now.strftime('%d')
        elif self.config.directory_structure == 'monthly':
            return base / now.strftime('%Y') / now.strftime('%m')
        elif self.config.directory_structure == 'experiment':
            if self.config.experiment_name:
                return base / self.config.experiment_name
            return base
        else:
            return base

    def stop(self) -> bool:
        """Stop recording"""
        should_notify = False
        with self.lock:
            if not self.recording:
                logger.warning("Recording not active")
                return False

            # Flush any remaining buffered data
            if self.write_buffer:
                self._flush_buffer()

            self._close_current_file()

            # Close PostgreSQL writer
            if self.db_writer:
                self.db_writer.close()
                self.db_writer = None

            self.recording = False
            duration = (datetime.now() - self.recording_start_time).total_seconds() if self.recording_start_time else 0

            logger.info(f"Recording stopped: {self.samples_written} samples, {self.bytes_written} bytes, {duration:.1f}s")
            should_notify = True

        # Call callback AFTER releasing lock to avoid deadlock
        if should_notify and self.on_status_change:
            self.on_status_change()

        return True

    def write_sample(self, channel_values: Dict[str, Any], channel_configs: Dict[str, Any]):
        """Write a sample to the recording file"""
        if not self.recording:
            return

        should_notify = False
        with self.lock:
            # Apply decimation (sample count-based)
            self.decimation_counter += 1
            if self.decimation_counter < self.config.decimation:
                return
            self.decimation_counter = 0

            # Apply time-based sample interval
            now = datetime.now()
            if self.last_sample_time is not None:
                # Calculate sample interval in seconds
                interval_s = self.config.sample_interval
                if self.config.sample_interval_unit == "milliseconds":
                    interval_s = self.config.sample_interval / 1000.0

                # Check if enough time has passed since last sample
                elapsed = (now - self.last_sample_time).total_seconds()
                if elapsed < interval_s:
                    return  # Skip this sample, not enough time has passed

            # Update last sample time
            self.last_sample_time = now

            # Filter channels if selection is specified
            if self.config.selected_channels:
                filtered_values = {k: v for k, v in channel_values.items()
                                   if k in self.config.selected_channels}
            else:
                filtered_values = channel_values.copy()

            # Add script values if configured
            # Take a snapshot to avoid RuntimeError if dict changes during iteration
            if self.config.include_scripts and self.script_values:
                script_snapshot = dict(self.script_values)  # Atomic copy
                for name, value in script_snapshot.items():
                    # Validate value type - only accept numeric types
                    if isinstance(value, (int, float)) and not (isinstance(value, float) and (value != value or abs(value) == float('inf'))):
                        filtered_values[f"script:{name}"] = value
                    # Skip NaN, Inf, or non-numeric values silently

            # Handle triggered mode
            if self.config.mode == 'triggered':
                if not self._handle_trigger(filtered_values):
                    return

            # Write the sample
            self._write_row(filtered_values, channel_configs)

            # Check file limits (may signal need to notify)
            should_notify = self._check_file_limits()

        # Call callback AFTER releasing lock to avoid deadlock
        if should_notify and self.on_status_change:
            self.on_status_change()

    def update_script_values(self, values: Dict[str, Any]):
        """Update script-computed values (calculated params, transforms)"""
        if not isinstance(values, dict):
            logger.warning("update_script_values: received non-dict, ignoring")
            return

        # Limit the number of script values to prevent memory issues
        MAX_SCRIPT_VALUES = 500

        with self.lock:
            # Filter and validate incoming values
            for key, value in values.items():
                # Validate key is a string
                if not isinstance(key, str):
                    continue
                # Validate value is numeric
                if not isinstance(value, (int, float)):
                    continue
                # Skip NaN and Inf
                if isinstance(value, float) and (value != value or abs(value) == float('inf')):
                    continue
                # Check size limit
                if key not in self.script_values and len(self.script_values) >= MAX_SCRIPT_VALUES:
                    logger.warning(f"Script values limit reached ({MAX_SCRIPT_VALUES}), ignoring new key: {key}")
                    continue
                self.script_values[key] = value

    def _generate_filename(self) -> str:
        """Generate a filename based on configuration"""
        parts = [self.config.file_prefix]
        now = datetime.now()

        if self.config.naming_pattern == 'timestamp':
            if self.config.include_date:
                parts.append(now.strftime('%Y%m%d'))
            if self.config.include_time:
                parts.append(now.strftime('%H%M%S'))
        elif self.config.naming_pattern == 'sequential':
            seq_str = str(self.sequential_counter).zfill(self.config.sequential_padding)
            parts.append(seq_str)
            self.sequential_counter += 1
        # For 'custom', just use prefix and suffix

        # Add channel count if configured
        if self.config.include_channels_in_name:
            channel_count = len(self.config.selected_channels) if self.config.selected_channels else 'all'
            parts.append(f"{channel_count}ch")

        # Add custom suffix if specified
        if self.config.custom_suffix:
            parts.append(self.config.custom_suffix)

        extension = 'csv' if self.config.file_format == 'csv' else 'tdms'
        return f"{'_'.join(parts)}.{extension}"

    def _write_row(self, values: Dict[str, Any], channel_configs: Dict[str, Any]):
        """Write a row to the CSV file"""
        timestamp = datetime.now().isoformat()

        # Initialize CSV writer with headers on first write
        if self.csv_writer is None:
            self._init_csv_writer(values, channel_configs)

        # Build row in column order
        row = [timestamp]
        for col in self.column_order[1:]:  # Skip timestamp
            value = values.get(col, '')
            if isinstance(value, float):
                row.append(f"{value:.6f}")
            elif isinstance(value, bool):
                row.append('1' if value else '0')
            else:
                row.append(str(value))

        # Handle write mode (immediate vs buffered)
        try:
            if self.config.write_mode == 'immediate':
                self.csv_writer.writerow(row)
                self.current_file_handle.flush()
                try:
                    os.fsync(self.current_file_handle.fileno())
                except OSError:
                    pass  # Best-effort; buffered mode already has fsync error handling
            else:
                # Buffered mode
                self.write_buffer.append(row)

                # Check if we should flush
                should_flush = False
                if len(self.write_buffer) >= self.config.buffer_size:
                    should_flush = True
                elif self.last_flush_time:
                    time_since_flush = (datetime.now() - self.last_flush_time).total_seconds()
                    if time_since_flush >= self.config.flush_interval_s:
                        should_flush = True

                if should_flush:
                    self._flush_buffer()

            self.samples_written += 1
            self.current_file_samples += 1
            self.bytes_written = self.current_file.stat().st_size if self.current_file else 0

            # Write to PostgreSQL if enabled
            if self.db_writer:
                self.db_writer.write_row(values)
        except IOError as e:
            logger.error(f"File I/O error writing sample: {e}")
            # Try to recover by reopening file
            self._handle_write_error(e)
        except Exception as e:
            logger.error(f"Unexpected error writing sample: {e}")

    def _init_csv_writer(self, values: Dict[str, Any], channel_configs: Dict[str, Any]):
        """Initialize CSV writer with headers"""
        # Build column order: timestamp first, then channels sorted
        new_columns = ['timestamp'] + sorted(values.keys())

        # If resuming an existing file, reuse previous column order and skip headers
        if self._resuming_file and self.column_order:
            # Column order already set from previous session — just create writer
            self.csv_writer = csv.writer(self.current_file_handle)
            self._resuming_file = False
            return

        self.column_order = new_columns

        # Add units row as comment
        header_row = ['timestamp']
        units_row = ['ISO8601']

        for col in sorted(values.keys()):
            header_row.append(col)
            # Get units from config or use empty
            if col.startswith('script:'):
                units_row.append('')  # Script values don't have units yet
            elif col in channel_configs:
                units_row.append(channel_configs[col].get('units', ''))
            else:
                units_row.append('')

        # Write metadata header
        effective_rate = self.config.effective_sample_rate_hz
        self.current_file_handle.write(f"# NISystem Data Recording\n")
        self.current_file_handle.write(f"# Started: {self.recording_start_time.isoformat()}\n")
        self.current_file_handle.write(f"# Mode: {self.config.mode}\n")
        self.current_file_handle.write(f"# Interval: {self.config.sample_interval} {self.config.sample_interval_unit}\n")
        self.current_file_handle.write(f"# Effective Rate: {effective_rate:.3f} Hz (decimation: {self.config.decimation})\n")
        self.current_file_handle.write(f"# Rotation: {self.config.rotation_mode}\n")
        self.current_file_handle.write(f"# Write Mode: {self.config.write_mode}\n")
        self.current_file_handle.write(f"# Units: {','.join(units_row)}\n")
        self.current_file_handle.write(f"#\n")

        self.csv_writer = csv.writer(self.current_file_handle)
        self.csv_writer.writerow(header_row)
        self.current_file_handle.flush()

    def _flush_buffer(self):
        """Flush buffered rows to disk"""
        if not self.write_buffer or not self.csv_writer:
            return

        try:
            for row in self.write_buffer:
                self.csv_writer.writerow(row)

            self.current_file_handle.flush()
            try:
                os.fsync(self.current_file_handle.fileno())
            except OSError as e:
                logger.error(f"fsync failed during buffer flush: {e} — data may not be persisted to disk")
                # Treat fsync failure as a write error for proper recovery
                self._handle_write_error(e)
                return
            self.write_buffer = []
            self.last_flush_time = datetime.now()
        except IOError as e:
            logger.error(f"Error flushing buffer to disk: {e}")
            # Keep buffer intact for retry on next flush
            self._handle_write_error(e)
        except Exception as e:
            logger.error(f"Unexpected error flushing buffer: {e}")

    def _handle_write_error(self, error: Exception):
        """Handle write errors - attempt recovery or stop recording gracefully"""
        logger.warning(f"Attempting recovery from write error: {error}")
        try:
            # Check if file handle is still valid
            if self.current_file_handle and not self.current_file_handle.closed:
                self.current_file_handle.flush()
        except Exception:
            # File handle is broken, try to reopen
            try:
                if self.current_file and self.current_file.exists():
                    self.current_file_handle = open(self.current_file, 'a', newline='')
                    self.csv_writer = csv.writer(self.current_file_handle)
                    logger.info("Successfully reopened recording file")
            except Exception as reopen_error:
                logger.error(f"Failed to recover recording file: {reopen_error}")
                # Stop recording to prevent silent data loss — operator will see
                # the recording stop in the dashboard and can investigate
                logger.critical("Stopping recording due to unrecoverable write error")
                try:
                    self.stop()
                except Exception:
                    # Last resort: force recording state to False so status is accurate
                    self.recording = False

    def _handle_trigger(self, values: Dict[str, Any]) -> bool:
        """Handle triggered recording mode. Returns True if sample should be written."""
        trigger_channel = self.config.trigger_channel

        if not trigger_channel or trigger_channel not in values:
            # No trigger channel configured or not in values, record everything
            return True

        current_value = values[trigger_channel]

        # Handle pre-trigger buffering
        if self.trigger_armed and not self.trigger_fired:
            # Buffer sample for pre-trigger (enforce MAX limit to prevent memory exhaustion)
            effective_limit = min(self.config.pre_trigger_samples, MAX_PRE_TRIGGER_SAMPLES)
            if effective_limit > 0:
                self.pre_trigger_buffer.append(values.copy())
                if len(self.pre_trigger_buffer) > effective_limit:
                    self.pre_trigger_buffer.pop(0)

            # Check trigger condition
            triggered = False
            if self.config.trigger_condition == 'above':
                triggered = current_value > self.config.trigger_value
            elif self.config.trigger_condition == 'below':
                triggered = current_value < self.config.trigger_value
            elif self.config.trigger_condition == 'change':
                if self.last_trigger_value is not None:
                    triggered = abs(current_value - self.last_trigger_value) > self.config.trigger_value

            self.last_trigger_value = current_value

            if triggered:
                self.trigger_fired = True
                self.trigger_armed = False
                logger.info(f"Trigger fired: {trigger_channel}={current_value}")

                # Write pre-trigger buffer
                # Note: We'll write these without calling this function recursively
                return True

            return False  # Don't write yet

        # After trigger fired
        if self.trigger_fired:
            # Handle post-trigger samples
            if self.config.post_trigger_samples > 0:
                self.post_trigger_count += 1
                if self.post_trigger_count >= self.config.post_trigger_samples:
                    # Stop recording after post-trigger samples
                    self.recording = False
                    logger.info("Recording stopped: post-trigger samples complete")

            return True

        return True

    def _check_file_limits(self) -> bool:
        """Check if file limits are exceeded based on rotation mode.
        Returns True if status callback should be called (after lock release)."""
        # Single and session modes don't rotate
        if self.config.rotation_mode in ('single', 'session'):
            return False

        should_rotate = False
        reason = ""

        # Check based on rotation mode
        if self.config.rotation_mode == 'size':
            if self.config.max_file_size_mb > 0:
                current_size_mb = self.bytes_written / (1024 * 1024)
                if current_size_mb >= self.config.max_file_size_mb:
                    should_rotate = True
                    reason = f"size limit ({current_size_mb:.1f}MB)"

        elif self.config.rotation_mode == 'time':
            if self.config.max_file_duration_s > 0 and self.recording_start_time:
                duration = (datetime.now() - self.recording_start_time).total_seconds()
                if duration >= self.config.max_file_duration_s:
                    should_rotate = True
                    reason = f"time limit ({duration:.0f}s)"

        elif self.config.rotation_mode == 'samples':
            if self.config.max_file_samples > 0:
                if self.current_file_samples >= self.config.max_file_samples:
                    should_rotate = True
                    reason = f"sample limit ({self.current_file_samples} samples)"

        if should_rotate:
            return self._handle_rotation(reason)

        return False

    def _handle_rotation(self, reason: str) -> bool:
        """Handle file rotation based on on_limit_reached setting.
        Returns True if status callback should be called (after lock release)."""
        logger.info(f"File limit reached: {reason}")

        if self.config.on_limit_reached == 'stop':
            # Stop recording
            self.recording = False
            logger.info("Recording stopped due to limit reached")
            return True  # Signal to call status change callback

        elif self.config.on_limit_reached == 'circular':
            # Rotate and delete oldest if needed
            self._rotate_file()
            self._enforce_circular_limit()

        else:  # 'new_file'
            self._rotate_file()

        return False

    def _rotate_file(self):
        """Close current file and start a new one"""
        # Flush buffer before closing
        if self.write_buffer:
            self._flush_buffer()

        self._close_current_file()

        # Generate new filename
        self.file_count += 1
        filename = self._generate_filename()

        # Add part number for clarity
        base, ext = filename.rsplit('.', 1)
        filename = f"{base}_part{self.file_count:03d}.{ext}"

        output_dir = self._get_output_directory()
        output_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = output_dir / filename

        self.current_file_handle = open(self.current_file, 'w', newline='')
        self.csv_writer = None  # Will reinitialize with headers
        self.current_file_samples = 0
        self.write_buffer = []
        self.last_flush_time = datetime.now()

        # Track for circular mode
        if self.config.on_limit_reached == 'circular':
            self.circular_files.append(self.current_file)

        logger.info(f"Rotated to new file: {filename}")

    def _enforce_circular_limit(self):
        """Delete oldest files to maintain circular buffer limit"""
        while len(self.circular_files) > self.config.circular_max_files:
            oldest = self.circular_files[0]
            if oldest == self.current_file:
                # Never remove the current file from tracking — skip it
                break
            self.circular_files.pop(0)
            try:
                if oldest.exists():
                    oldest.unlink()
                    logger.info(f"Circular mode: deleted oldest file {oldest.name}")
            except Exception as e:
                logger.warning(f"Failed to delete circular file {oldest}: {e}")

    def _close_current_file(self):
        """Close the current file handle with optional integrity verification"""
        if self.current_file_handle:
            # Flush any remaining buffer
            if self.write_buffer:
                self._flush_buffer()

            # Write footer
            duration = (datetime.now() - self.recording_start_time).total_seconds() if self.recording_start_time else 0
            self.current_file_handle.write(f"\n# Stopped: {datetime.now().isoformat()}\n")
            self.current_file_handle.write(f"# Duration: {duration:.1f}s\n")
            self.current_file_handle.write(f"# Total Samples: {self.samples_written}\n")
            self.current_file_handle.write(f"# File Samples: {self.current_file_samples}\n")
            self.current_file_handle.write(f"# File Count: {self.file_count}\n")
            self.current_file_handle.flush()
            try:
                os.fsync(self.current_file_handle.fileno())
            except OSError as e:
                logger.warning(f"fsync failed during file close: {e}")
            _unlock_file(self.current_file_handle)
            self.current_file_handle.close()
            self.current_file_handle = None
            self.csv_writer = None

            # ALCOA+ Data Integrity: Compute and store checksum
            if self.config.verify_on_close and self.current_file:
                self._create_integrity_file(self.current_file)

            # ALCOA+ Data Integrity: Make file read-only if append_only is enabled
            # Skip if reuse_file is active — file needs to remain writable for next start
            if self.config.append_only and not self.config.reuse_file and self.current_file:
                self._make_file_readonly(self.current_file)

    def _create_integrity_file(self, data_file: Path):
        """Create a companion integrity file with SHA-256 checksum (ALCOA+ compliance)"""
        try:
            sha256 = hashlib.sha256()
            with open(data_file, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)

            file_hash = sha256.hexdigest()
            integrity_file = data_file.with_suffix(data_file.suffix + '.sha256')

            with open(integrity_file, 'w') as f:
                f.write(f"# NISystem Recording Integrity Verification\n")
                f.write(f"# ALCOA+ Compliance: Original, Accurate, Enduring\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write(f"file: {data_file.name}\n")
                f.write(f"sha256: {file_hash}\n")
                f.write(f"size_bytes: {data_file.stat().st_size}\n")
                f.write(f"samples: {self.current_file_samples}\n")

            logger.info(f"Created integrity file: {integrity_file}")

        except Exception as e:
            logger.error(f"Failed to create integrity file: {e}")

    def _make_file_readonly(self, file_path: Path):
        """Make file read-only to enforce append-only mode (ALCOA+ compliance)"""
        try:
            # Remove write permissions
            current_mode = file_path.stat().st_mode
            readonly_mode = current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
            file_path.chmod(readonly_mode)
            logger.info(f"File set to read-only (append-only mode): {file_path}")
        except Exception as e:
            logger.error(f"Failed to set file read-only: {e}")

    def verify_file_integrity(self, data_file: Path) -> tuple:
        """Verify a recording file against its integrity file

        Returns:
            (valid, message) tuple
        """
        integrity_file = data_file.with_suffix(data_file.suffix + '.sha256')

        if not integrity_file.exists():
            return False, "Integrity file not found"

        try:
            # Read expected hash
            expected_hash = None
            expected_size = None
            with open(integrity_file, 'r') as f:
                for line in f:
                    if line.startswith('sha256:'):
                        expected_hash = line.split(':')[1].strip()
                    elif line.startswith('size_bytes:'):
                        expected_size = int(line.split(':')[1].strip())

            if not expected_hash:
                return False, "Invalid integrity file format"

            # Compute actual hash
            sha256 = hashlib.sha256()
            with open(data_file, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)

            actual_hash = sha256.hexdigest()
            actual_size = data_file.stat().st_size

            if actual_hash != expected_hash:
                return False, f"Hash mismatch: expected {expected_hash[:16]}..., got {actual_hash[:16]}..."

            if expected_size and actual_size != expected_size:
                return False, f"Size mismatch: expected {expected_size}, got {actual_size}"

            return True, "Integrity verified"

        except Exception as e:
            return False, f"Verification error: {e}"

    def get_status(self) -> dict:
        """Get current recording status"""
        with self.lock:
            duration = 0.0
            if self.recording and self.recording_start_time:
                duration = (datetime.now() - self.recording_start_time).total_seconds()

            return {
                "recording": self.recording,
                "recording_filename": self.current_file.name if self.current_file else None,
                "recording_path": str(self.current_file) if self.current_file else None,
                "recording_start_time": self.recording_start_time.isoformat() if self.recording_start_time else None,
                "recording_duration": duration,
                "recording_bytes": self.bytes_written,
                "recording_samples": self.samples_written,
                "recording_file_samples": self.current_file_samples,
                "recording_file_count": self.file_count,
                "recording_mode": self.config.mode,
                "recording_rotation_mode": self.config.rotation_mode,
                "recording_write_mode": self.config.write_mode,
                "recording_buffer_pending": len(self.write_buffer),
                "trigger_armed": self.trigger_armed,
                "trigger_fired": self.trigger_fired,
                "db_enabled": self.config.db_enabled,
                "db_connected": self.db_writer is not None,
                "db_rows_written": self.db_writer.rows_written if self.db_writer else 0,
            }

    def list_files(self) -> List[dict]:
        """List recorded files from base path and subdirectories"""
        files = []
        data_dir = Path(self.config.base_path)

        if not data_dir.exists():
            return files

        # Snapshot file list under lock to avoid races with rotation/deletion
        with self.lock:
            try:
                csv_files = sorted(data_dir.glob("**/*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
            except OSError:
                return files

        for f in csv_files:
            try:
                stat = f.stat()

                # Try to extract duration from file footer
                duration = 0.0
                sample_count = 0
                channels = []

                try:
                    with open(f, 'r') as fp:
                        # Read first few lines for header info
                        lines = fp.readlines()
                        for line in lines:
                            if line.startswith('# Duration:'):
                                duration = float(line.split(':')[1].strip().rstrip('s'))
                            elif line.startswith('# Samples:'):
                                sample_count = int(line.split(':')[1].strip())
                            elif not line.startswith('#') and ',' in line:
                                # Header row
                                channels = [c.strip() for c in line.split(',')[1:]]  # Skip timestamp
                                break
                except (OSError, ValueError) as e:
                    logger.warning(f"Failed to read recording file header for {f.name}: {e}")

                files.append({
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "duration": duration,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "sample_count": sample_count,
                    "channels": channels[:10]  # Limit to first 10 channels for display
                })
            except Exception as e:
                logger.warning(f"Error reading file info for {f}: {e}")

        return files

    def delete_file(self, filename: str) -> bool:
        """Delete a recorded file (path-validated and lock-protected)"""
        try:
            # Reject traversal attempts
            if '..' in filename or os.path.isabs(filename):
                logger.warning(f"[SECURITY] Rejected delete with path traversal: {filename}")
                return False

            file_path = (Path(self.config.base_path) / filename).resolve()

            # Validate path stays within base directory
            if not self._is_path_within_base(file_path):
                logger.warning(f"[SECURITY] Path traversal blocked in delete: {filename}")
                return False

            with self.lock:
                if not file_path.exists() or not file_path.is_file():
                    logger.warning(f"File not found: {filename}")
                    return False

                # Don't delete current recording file (checked under lock)
                if self.recording and self.current_file and file_path == self.current_file.resolve():
                    logger.warning("Cannot delete file that is currently being recorded")
                    return False

                file_path.unlink()
                logger.info(f"Deleted recording file: {filename}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete file {filename}: {e}")
            return False

    def export_file(self, filename: str, format: str = 'csv') -> Optional[str]:
        """Export a file to different format (placeholder for future TDMS support)"""
        file_path = self._find_recording_file(filename)
        if file_path and file_path.exists():
            return str(file_path)
        return None

    def read_file(self, filename: str, start_time: str = None, end_time: str = None,
                  channels: List[str] = None, decimation: int = 1,
                  max_samples: int = 50000) -> Dict[str, Any]:
        """
        Read historical data from a recording file.

        Args:
            filename: Name of the recording file (relative to base_path)
            start_time: ISO format start time filter (optional)
            end_time: ISO format end time filter (optional)
            channels: List of channels to include (None = all)
            decimation: Return every Nth sample (1 = all samples)
            max_samples: Maximum samples to return (prevents memory issues)

        Returns:
            {
                success: bool,
                error: str or None,
                filename: str,
                channels: List[str],
                data: List[{timestamp: str, values: Dict[str, float]}],
                start_time: str (actual data start),
                end_time: str (actual data end),
                sample_count: int,
                total_samples: int (before decimation/filtering)
            }
        """
        result = {
            "success": False,
            "error": None,
            "filename": filename,
            "channels": [],
            "data": [],
            "start_time": None,
            "end_time": None,
            "sample_count": 0,
            "total_samples": 0
        }

        # Find the file (check base path and subdirectories)
        file_path = self._find_recording_file(filename)
        if not file_path:
            result["error"] = f"File not found: {filename}"
            return result

        try:
            # Parse time filters
            filter_start = None
            filter_end = None
            if start_time:
                try:
                    filter_start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                except ValueError:
                    result["error"] = f"Invalid start_time format: {start_time}"
                    return result
            if end_time:
                try:
                    filter_end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                except ValueError:
                    result["error"] = f"Invalid end_time format: {end_time}"
                    return result

            with open(file_path, 'r', newline='') as f:
                # Skip comment lines at the start
                header_line = None
                for line in f:
                    if not line.startswith('#'):
                        header_line = line.strip()
                        break

                if not header_line:
                    result["error"] = "No header found in file"
                    return result

                # Parse header
                all_columns = [col.strip() for col in header_line.split(',')]
                if 'timestamp' not in all_columns:
                    result["error"] = "Missing timestamp column"
                    return result

                timestamp_idx = all_columns.index('timestamp')
                data_columns = [c for c in all_columns if c != 'timestamp']

                # Filter channels if specified
                if channels:
                    selected_columns = [c for c in data_columns if c in channels]
                else:
                    selected_columns = data_columns

                result["channels"] = selected_columns

                # Build column index map
                col_indices = {col: all_columns.index(col) for col in selected_columns}

                # Read data rows
                reader = csv.reader(f)
                data = []
                total_samples = 0
                decimation_counter = 0
                actual_start = None
                actual_end = None

                for row in reader:
                    # Skip empty rows or comment rows
                    if not row or row[0].startswith('#'):
                        continue

                    total_samples += 1

                    # Parse timestamp
                    try:
                        ts_str = row[timestamp_idx]
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    except (ValueError, IndexError):
                        continue

                    # Apply time filter
                    if filter_start and ts < filter_start:
                        continue
                    if filter_end and ts > filter_end:
                        continue

                    # Apply decimation
                    decimation_counter += 1
                    if decimation_counter < decimation:
                        continue
                    decimation_counter = 0

                    # Track actual time range
                    if actual_start is None:
                        actual_start = ts_str
                    actual_end = ts_str

                    # Build row data
                    values = {}
                    for col, idx in col_indices.items():
                        try:
                            val = row[idx]
                            # Try to parse as number
                            if '.' in val:
                                values[col] = float(val)
                            else:
                                values[col] = int(val)
                        except (ValueError, IndexError):
                            values[col] = None

                    data.append({
                        "timestamp": ts_str,
                        "values": values
                    })

                    # Limit samples to prevent memory issues
                    if len(data) >= max_samples:
                        logger.warning(f"read_file: max_samples ({max_samples}) reached, truncating")
                        break

                result["data"] = data
                result["start_time"] = actual_start
                result["end_time"] = actual_end
                result["sample_count"] = len(data)
                result["total_samples"] = total_samples
                result["success"] = True

        except Exception as e:
            logger.error(f"Error reading recording file {filename}: {e}")
            result["error"] = str(e)

        return result

    def read_file_range(self, filename: str, start_sample: int = 0,
                        end_sample: int = None, channels: List[str] = None) -> Dict[str, Any]:
        """
        Read a range of samples from a recording file (lazy loading for large files).

        Args:
            filename: Name of the recording file
            start_sample: Starting sample index (0-based)
            end_sample: Ending sample index (exclusive, None = to end)
            channels: List of channels to include (None = all)

        Returns:
            {
                success: bool,
                error: str or None,
                channels: List[str],
                data: List[{timestamp: str, values: Dict[str, float]}],
                start_sample: int,
                end_sample: int,
                total_samples: int
            }
        """
        result = {
            "success": False,
            "error": None,
            "filename": filename,
            "channels": [],
            "data": [],
            "start_sample": start_sample,
            "end_sample": 0,
            "total_samples": 0
        }

        file_path = self._find_recording_file(filename)
        if not file_path:
            result["error"] = f"File not found: {filename}"
            return result

        try:
            with open(file_path, 'r', newline='') as f:
                # Skip comment lines
                header_line = None
                for line in f:
                    if not line.startswith('#'):
                        header_line = line.strip()
                        break

                if not header_line:
                    result["error"] = "No header found in file"
                    return result

                all_columns = [col.strip() for col in header_line.split(',')]
                timestamp_idx = all_columns.index('timestamp') if 'timestamp' in all_columns else 0
                data_columns = [c for c in all_columns if c != 'timestamp']

                if channels:
                    selected_columns = [c for c in data_columns if c in channels]
                else:
                    selected_columns = data_columns

                result["channels"] = selected_columns
                col_indices = {col: all_columns.index(col) for col in selected_columns}

                reader = csv.reader(f)
                data = []
                sample_idx = 0
                max_samples = 10000  # Limit per request

                for row in reader:
                    if not row or row[0].startswith('#'):
                        continue

                    # Skip until start_sample
                    if sample_idx < start_sample:
                        sample_idx += 1
                        continue

                    # Stop at end_sample
                    if end_sample is not None and sample_idx >= end_sample:
                        break

                    # Build row data
                    ts_str = row[timestamp_idx] if len(row) > timestamp_idx else ""
                    values = {}
                    for col, idx in col_indices.items():
                        try:
                            val = row[idx]
                            if '.' in val:
                                values[col] = float(val)
                            else:
                                values[col] = int(val)
                        except (ValueError, IndexError):
                            values[col] = None

                    data.append({
                        "timestamp": ts_str,
                        "values": values
                    })

                    sample_idx += 1

                    if len(data) >= max_samples:
                        break

                # Count total samples (continue reading without storing)
                total = sample_idx
                for row in reader:
                    if row and not row[0].startswith('#'):
                        total += 1

                result["data"] = data
                result["end_sample"] = start_sample + len(data)
                result["total_samples"] = total
                result["success"] = True

        except Exception as e:
            logger.error(f"Error reading file range {filename}: {e}")
            result["error"] = str(e)

        return result

    def get_file_info(self, filename: str) -> Dict[str, Any]:
        """
        Get metadata about a recording file without loading all data.

        Returns:
            {
                success: bool,
                error: str or None,
                filename: str,
                path: str,
                size_bytes: int,
                channels: List[str],
                sample_count: int,
                start_time: str,
                end_time: str,
                duration_seconds: float,
                sample_rate_hz: float (estimated)
            }
        """
        result = {
            "success": False,
            "error": None,
            "filename": filename,
            "path": None,
            "size_bytes": 0,
            "channels": [],
            "sample_count": 0,
            "start_time": None,
            "end_time": None,
            "duration_seconds": 0.0,
            "sample_rate_hz": 0.0
        }

        file_path = self._find_recording_file(filename)
        if not file_path:
            result["error"] = f"File not found: {filename}"
            return result

        try:
            result["path"] = str(file_path)
            result["size_bytes"] = file_path.stat().st_size

            with open(file_path, 'r', newline='') as f:
                # Parse header comments for metadata
                header_line = None
                first_data_ts = None
                last_data_ts = None

                for line in f:
                    if line.startswith('# Duration:'):
                        try:
                            result["duration_seconds"] = float(line.split(':')[1].strip().rstrip('s'))
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Could not parse duration from recording header: {e}")
                    elif line.startswith('# Total Samples:') or line.startswith('# Samples:'):
                        try:
                            result["sample_count"] = int(line.split(':')[1].strip())
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Could not parse sample count from recording header: {e}")
                    elif line.startswith('# Effective Rate:'):
                        try:
                            rate_str = line.split(':')[1].strip().split()[0]
                            result["sample_rate_hz"] = float(rate_str)
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Could not parse sample rate from recording header: {e}")
                    elif not line.startswith('#'):
                        header_line = line.strip()
                        break

                if header_line:
                    columns = [col.strip() for col in header_line.split(',')]
                    result["channels"] = [c for c in columns if c != 'timestamp']

                    # Read first data row for start_time
                    reader = csv.reader(f)
                    for row in reader:
                        if row and not row[0].startswith('#'):
                            first_data_ts = row[0]
                            break

                    # Read last few rows for end_time (seek to near end for efficiency)
                    # For large files, this is more efficient than reading all rows
                    f.seek(0, 2)  # Seek to end
                    file_size = f.tell()

                    if file_size > 10000:
                        f.seek(max(0, file_size - 10000))  # Back up 10KB
                        f.readline()  # Skip partial line

                    for line in f:
                        if line.strip() and not line.startswith('#'):
                            parts = line.strip().split(',')
                            if parts:
                                last_data_ts = parts[0]

                result["start_time"] = first_data_ts
                result["end_time"] = last_data_ts

                # Calculate duration if not in metadata
                if result["duration_seconds"] == 0.0 and first_data_ts and last_data_ts:
                    try:
                        start = datetime.fromisoformat(first_data_ts.replace('Z', '+00:00'))
                        end = datetime.fromisoformat(last_data_ts.replace('Z', '+00:00'))
                        result["duration_seconds"] = (end - start).total_seconds()
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not compute recording duration from timestamps: {e}")

                result["success"] = True

        except Exception as e:
            logger.error(f"Error getting file info {filename}: {e}")
            result["error"] = str(e)

        return result

    def _is_path_within_base(self, file_path: Path) -> bool:
        """Validate that a resolved path stays within the recording base directory.
        Prevents path traversal attacks (e.g., '../../etc/passwd').
        """
        try:
            base = Path(self.config.base_path).resolve()
            resolved = file_path.resolve()
            return str(resolved).startswith(str(base) + os.sep) or resolved == base
        except (OSError, ValueError):
            return False

    def _find_recording_file(self, filename: str) -> Optional[Path]:
        """Find a recording file by name, checking base path and subdirectories.
        All returned paths are validated to be within base_path (no traversal).
        """
        # Reject absolute paths and obvious traversal attempts
        if os.path.isabs(filename) or '..' in filename:
            logger.warning(f"[SECURITY] Rejected file path with traversal or absolute path: {filename}")
            return None

        # Check base path directly
        base = Path(self.config.base_path)
        direct_path = base / filename
        if direct_path.exists() and self._is_path_within_base(direct_path):
            return direct_path.resolve()

        # Search subdirectories (basename only to prevent traversal via glob)
        safe_name = Path(filename).name  # Strip any directory components
        for f in base.glob(f"**/{safe_name}"):
            if self._is_path_within_base(f):
                return f.resolve()

        return None
