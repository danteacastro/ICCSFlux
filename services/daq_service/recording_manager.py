#!/usr/bin/env python3
"""
Recording Manager for NISystem
Handles data recording with configurable options, triggered recording, and script values
"""

import csv
import json
import os
import stat
import hashlib
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import logging

logger = logging.getLogger('RecordingManager')

# Maximum pre-trigger buffer size to prevent memory exhaustion
# Even if user requests more, we cap at this limit
MAX_PRE_TRIGGER_SAMPLES = 10000


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

            # Generate filename
            if not filename:
                filename = self._generate_filename()

            self.current_file = output_dir / filename

            try:
                self.current_file_handle = open(self.current_file, 'w', newline='')
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
        except IOError as e:
            logger.error(f"File I/O error writing sample: {e}")
            # Try to recover by reopening file
            self._handle_write_error(e)
        except Exception as e:
            logger.error(f"Unexpected error writing sample: {e}")

    def _init_csv_writer(self, values: Dict[str, Any], channel_configs: Dict[str, Any]):
        """Initialize CSV writer with headers"""
        # Build column order: timestamp first, then channels sorted
        self.column_order = ['timestamp'] + sorted(values.keys())

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
                # Mark recording as having errors but don't stop
                # The user should see this in the status

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
            oldest = self.circular_files.pop(0)
            try:
                if oldest.exists() and oldest != self.current_file:
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
            self.current_file_handle.close()
            self.current_file_handle = None
            self.csv_writer = None

            # ALCOA+ Data Integrity: Compute and store checksum
            if self.config.verify_on_close and self.current_file:
                self._create_integrity_file(self.current_file)

            # ALCOA+ Data Integrity: Make file read-only if append_only is enabled
            if self.config.append_only and self.current_file:
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
            }

    def list_files(self) -> List[dict]:
        """List recorded files from base path and subdirectories"""
        files = []
        data_dir = Path(self.config.base_path)

        if not data_dir.exists():
            return files

        # Search recursively to find files in date-based subdirectories
        for f in sorted(data_dir.glob("**/*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
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
                except:
                    pass

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
        """Delete a recorded file"""
        try:
            file_path = Path(self.config.base_path) / filename
            if file_path.exists() and file_path.is_file():
                # Don't delete current recording file
                if self.recording and self.current_file and file_path == self.current_file:
                    logger.warning("Cannot delete file that is currently being recorded")
                    return False

                file_path.unlink()
                logger.info(f"Deleted recording file: {filename}")
                return True
            else:
                logger.warning(f"File not found: {filename}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete file {filename}: {e}")
            return False

    def export_file(self, filename: str, format: str = 'csv') -> Optional[str]:
        """Export a file to different format (placeholder for future TDMS support)"""
        # For now, just return the path to the file
        file_path = Path(self.config.base_path) / filename
        if file_path.exists():
            return str(file_path)
        return None
