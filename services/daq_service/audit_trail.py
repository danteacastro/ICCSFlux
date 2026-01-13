#!/usr/bin/env python3
"""
Configuration Audit Trail for NISystem

Provides 21 CFR Part 11 / ALCOA+ compliant audit trail for:
- Configuration changes (channels, safety, system settings)
- Project load/save operations
- Critical operator actions (alarm ack, safety changes, recording)

Features:
- Append-only log (records cannot be deleted or modified)
- Cryptographic integrity verification (SHA-256 chain)
- Timestamped entries with user attribution
- JSON Lines format for easy parsing and archival
- Automatic log rotation with retention

References:
- FDA 21 CFR Part 11 (Electronic Records)
- ALCOA+ Data Integrity Principles
- ISA-18.2 Alarm Management (audit requirements)
"""

import json
import hashlib
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import shutil
import gzip

logger = logging.getLogger('AuditTrail')


class AuditEventType(Enum):
    """Types of auditable events"""
    # Configuration changes
    CONFIG_CHANNEL_ADDED = "config.channel.added"
    CONFIG_CHANNEL_MODIFIED = "config.channel.modified"
    CONFIG_CHANNEL_REMOVED = "config.channel.removed"
    CONFIG_SYSTEM_MODIFIED = "config.system.modified"
    CONFIG_SAFETY_MODIFIED = "config.safety.modified"
    CONFIG_ALARM_MODIFIED = "config.alarm.modified"
    CONFIG_CHANGE = "config.change"

    # Project operations
    PROJECT_LOADED = "project.loaded"
    PROJECT_SAVED = "project.saved"
    PROJECT_CLOSED = "project.closed"
    PROJECT_CREATED = "project.created"
    PROJECT_IMPORTED = "project.imported"

    # Safety actions
    SAFETY_ACTION_TRIGGERED = "safety.action.triggered"
    SAFETY_ACTION_RESET = "safety.action.reset"
    SAFETY_INTERLOCK_MODIFIED = "safety.interlock.modified"
    SAFETY_CONFIG_LOCKED = "safety.config.locked"
    SAFETY_CONFIG_UNLOCKED = "safety.config.unlocked"

    # Alarm actions
    ALARM_ACKNOWLEDGED = "alarm.acknowledged"
    ALARM_RESET = "alarm.reset"
    ALARM_SHELVED = "alarm.shelved"
    ALARM_UNSHELVED = "alarm.unshelved"
    ALARM_DISABLED = "alarm.disabled"
    ALARM_ENABLED = "alarm.enabled"

    # Recording operations
    RECORDING_STARTED = "recording.started"
    RECORDING_STOPPED = "recording.stopped"
    RECORDING_CONFIG_MODIFIED = "recording.config.modified"

    # Acquisition control
    ACQUISITION_STARTED = "acquisition.started"
    ACQUISITION_STOPPED = "acquisition.stopped"

    # User management
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login.failed"
    USER_LOGOUT = "user.logout"
    USER_SESSION_TIMEOUT = "user.session.timeout"

    # System events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"


@dataclass
class AuditEntry:
    """Single audit log entry with integrity chain"""
    sequence: int               # Monotonic sequence number
    timestamp: str              # ISO 8601 timestamp with microseconds
    event_type: str             # AuditEventType value
    user: str                   # Who performed the action
    user_role: str              # User's role at time of action
    description: str            # Human-readable description
    details: Dict[str, Any]     # Structured event details
    previous_value: Optional[Any]  # Value before change (for modifications)
    new_value: Optional[Any]    # Value after change (for modifications)
    reason: str                 # Why the change was made (required for some actions)
    source_ip: str              # Client IP address
    session_id: str             # Session identifier
    node_id: str                # DAQ node identifier
    previous_hash: str          # SHA-256 of previous entry (chain)
    entry_hash: str             # SHA-256 of this entry (without entry_hash field)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'AuditEntry':
        return AuditEntry(**d)


class AuditTrail:
    """
    Append-only audit trail with cryptographic integrity verification.

    Each entry is chained to the previous via SHA-256 hash, making
    any tampering detectable. Entries are written immediately to disk
    in JSON Lines format.
    """

    def __init__(self,
                 audit_dir: Path,
                 node_id: str = "default",
                 retention_days: int = 365,
                 max_file_size_mb: float = 50.0):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        self.node_id = node_id
        self.retention_days = retention_days
        self.max_file_size_mb = max_file_size_mb

        self.lock = threading.RLock()
        self.sequence = 0
        self.previous_hash = "genesis"
        self.current_file: Optional[Path] = None

        # Load state from existing log
        self._initialize_from_existing()

        # Log startup
        self.log_event(
            event_type=AuditEventType.SYSTEM_STARTUP,
            user="SYSTEM",
            description="Audit trail initialized",
            details={"node_id": node_id, "retention_days": retention_days}
        )

    def _initialize_from_existing(self):
        """Load sequence and hash chain from existing log file"""
        log_files = sorted(self.audit_dir.glob("audit_*.jsonl"), reverse=True)

        if not log_files:
            # No existing logs - start fresh
            self._create_new_log_file()
            return

        # Find latest entry to continue chain
        for log_file in log_files:
            try:
                # Read last line of file
                with open(log_file, 'rb') as f:
                    # Seek to end and work backwards to find last line
                    f.seek(0, 2)  # End of file
                    file_size = f.tell()
                    if file_size == 0:
                        continue

                    # Read last few KB to find last complete line
                    read_size = min(file_size, 4096)
                    f.seek(file_size - read_size)
                    data = f.read()

                    lines = data.decode('utf-8', errors='replace').strip().split('\n')
                    for line in reversed(lines):
                        if line.strip():
                            entry = json.loads(line)
                            self.sequence = entry.get('sequence', 0)
                            self.previous_hash = entry.get('entry_hash', 'genesis')
                            self.current_file = log_file
                            logger.info(f"Resumed audit trail at sequence {self.sequence}")
                            return
            except Exception as e:
                logger.warning(f"Could not read audit file {log_file}: {e}")
                continue

        # Could not restore - start fresh
        self._create_new_log_file()

    def _create_new_log_file(self):
        """Create a new audit log file with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_file = self.audit_dir / f"audit_{timestamp}.jsonl"
        logger.info(f"Created new audit log: {self.current_file}")

    def _check_rotation(self):
        """Check if log file needs rotation based on size"""
        if self.current_file and self.current_file.exists():
            size_mb = self.current_file.stat().st_size / (1024 * 1024)
            if size_mb >= self.max_file_size_mb:
                logger.info(f"Rotating audit log (size: {size_mb:.1f} MB)")
                self._create_new_log_file()

    def _compute_entry_hash(self, entry_dict: dict) -> str:
        """Compute SHA-256 hash of entry (excluding entry_hash field)"""
        # Create copy without entry_hash
        hashable = {k: v for k, v in entry_dict.items() if k != 'entry_hash'}
        # Canonical JSON encoding for consistent hashing
        canonical = json.dumps(hashable, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def log_event(self,
                  event_type: AuditEventType,
                  user: str,
                  description: str,
                  details: Optional[Dict[str, Any]] = None,
                  previous_value: Optional[Any] = None,
                  new_value: Optional[Any] = None,
                  reason: str = "",
                  user_role: str = "operator",
                  source_ip: str = "local",
                  session_id: str = "") -> AuditEntry:
        """
        Log an auditable event to the trail.

        This is the main method for recording audit events. It creates
        a cryptographically chained entry and writes it immediately to disk.
        """
        with self.lock:
            self._check_rotation()

            self.sequence += 1
            timestamp = datetime.now().isoformat(timespec='microseconds')

            # Build entry without hash first
            entry_dict = {
                'sequence': self.sequence,
                'timestamp': timestamp,
                'event_type': event_type.value if isinstance(event_type, AuditEventType) else str(event_type),
                'user': user,
                'user_role': user_role,
                'description': description,
                'details': details or {},
                'previous_value': previous_value,
                'new_value': new_value,
                'reason': reason,
                'source_ip': source_ip,
                'session_id': session_id,
                'node_id': self.node_id,
                'previous_hash': self.previous_hash,
                'entry_hash': ''  # Placeholder
            }

            # Compute and add hash
            entry_hash = self._compute_entry_hash(entry_dict)
            entry_dict['entry_hash'] = entry_hash

            # Write to file immediately (append)
            try:
                with open(self.current_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry_dict, default=str) + '\n')
                    f.flush()
            except Exception as e:
                logger.error(f"Failed to write audit entry: {e}")
                raise

            # Update chain
            self.previous_hash = entry_hash

            entry = AuditEntry.from_dict(entry_dict)

            logger.debug(f"Audit [{self.sequence}] {event_type.value if isinstance(event_type, AuditEventType) else event_type}: {description}")

            return entry

    def log_config_change(self,
                          config_type: str,
                          item_id: str,
                          user: str,
                          previous_value: Any,
                          new_value: Any,
                          reason: str = "",
                          **kwargs) -> AuditEntry:
        """Convenience method for logging configuration changes"""
        event_type = AuditEventType.CONFIG_CHANNEL_MODIFIED
        if config_type == "channel":
            if previous_value is None:
                event_type = AuditEventType.CONFIG_CHANNEL_ADDED
            elif new_value is None:
                event_type = AuditEventType.CONFIG_CHANNEL_REMOVED
            else:
                event_type = AuditEventType.CONFIG_CHANNEL_MODIFIED
        elif config_type == "safety":
            event_type = AuditEventType.CONFIG_SAFETY_MODIFIED
        elif config_type == "alarm":
            event_type = AuditEventType.CONFIG_ALARM_MODIFIED
        elif config_type == "system":
            event_type = AuditEventType.CONFIG_SYSTEM_MODIFIED

        return self.log_event(
            event_type=event_type,
            user=user,
            description=f"Modified {config_type} config: {item_id}",
            details={"config_type": config_type, "item_id": item_id},
            previous_value=previous_value,
            new_value=new_value,
            reason=reason,
            **kwargs
        )

    def verify_integrity(self, start_sequence: int = 1, end_sequence: Optional[int] = None) -> tuple:
        """
        Verify the integrity of the audit trail by checking hash chain.

        Returns:
            (is_valid: bool, errors: List[str], entries_checked: int)
        """
        errors = []
        entries_checked = 0
        expected_hash = "genesis"

        log_files = sorted(self.audit_dir.glob("audit_*.jsonl"))

        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if not line.strip():
                            continue

                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError as e:
                            errors.append(f"{log_file.name}:{line_num}: Invalid JSON: {e}")
                            continue

                        seq = entry.get('sequence', 0)

                        if end_sequence and seq > end_sequence:
                            break

                        if seq < start_sequence:
                            expected_hash = entry.get('entry_hash', 'genesis')
                            continue

                        entries_checked += 1

                        # Verify previous hash chain
                        if entry.get('previous_hash') != expected_hash:
                            errors.append(
                                f"Sequence {seq}: Chain broken - expected previous_hash "
                                f"{expected_hash[:16]}..., got {entry.get('previous_hash', 'missing')[:16]}..."
                            )

                        # Verify entry hash
                        computed_hash = self._compute_entry_hash(entry)
                        if entry.get('entry_hash') != computed_hash:
                            errors.append(
                                f"Sequence {seq}: Entry hash mismatch - computed "
                                f"{computed_hash[:16]}..., stored {entry.get('entry_hash', 'missing')[:16]}..."
                            )

                        expected_hash = entry.get('entry_hash', 'genesis')

            except Exception as e:
                errors.append(f"{log_file.name}: Read error: {e}")

        is_valid = len(errors) == 0

        if is_valid:
            logger.info(f"Audit trail integrity verified: {entries_checked} entries checked")
        else:
            logger.error(f"Audit trail integrity check FAILED: {len(errors)} errors")
            for error in errors[:10]:  # Log first 10 errors
                logger.error(f"  - {error}")

        return is_valid, errors, entries_checked

    def query_events(self,
                     event_types: Optional[List[AuditEventType]] = None,
                     user: Optional[str] = None,
                     start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None,
                     limit: int = 1000) -> List[AuditEntry]:
        """Query audit trail with filters"""
        results = []
        event_type_values = [e.value for e in event_types] if event_types else None

        log_files = sorted(self.audit_dir.glob("audit_*.jsonl"), reverse=True)

        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue

                        entry_dict = json.loads(line)

                        # Apply filters
                        if event_type_values and entry_dict.get('event_type') not in event_type_values:
                            continue

                        if user and entry_dict.get('user') != user:
                            continue

                        entry_time = datetime.fromisoformat(entry_dict.get('timestamp', ''))
                        if start_time and entry_time < start_time:
                            continue
                        if end_time and entry_time > end_time:
                            continue

                        results.append(AuditEntry.from_dict(entry_dict))

                        if len(results) >= limit:
                            return results

            except Exception as e:
                logger.warning(f"Error reading {log_file}: {e}")

        return results

    def cleanup_old_logs(self):
        """Remove audit logs older than retention period and compress old logs"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)

        for log_file in self.audit_dir.glob("audit_*.jsonl"):
            try:
                # Parse date from filename
                name = log_file.stem  # audit_YYYYMMDD_HHMMSS
                date_str = name.split('_')[1]
                file_date = datetime.strptime(date_str, "%Y%m%d")

                if file_date < cutoff:
                    logger.info(f"Removing old audit log: {log_file.name}")
                    log_file.unlink()
                elif file_date < datetime.now() - timedelta(days=7):
                    # Compress logs older than 7 days
                    if not (self.audit_dir / f"{log_file.name}.gz").exists():
                        self._compress_log(log_file)

            except Exception as e:
                logger.warning(f"Error processing {log_file}: {e}")

    def _compress_log(self, log_file: Path):
        """Compress a log file to save space"""
        if log_file == self.current_file:
            return  # Don't compress active file

        try:
            gz_path = self.audit_dir / f"{log_file.name}.gz"
            with open(log_file, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Verify compressed file before deleting original
            with gzip.open(gz_path, 'rb') as f:
                f.read(1)  # Test read

            log_file.unlink()
            logger.info(f"Compressed {log_file.name}")

        except Exception as e:
            logger.error(f"Failed to compress {log_file}: {e}")

    def export_csv(self, output_path: Path, **filters) -> int:
        """Export audit trail to CSV format for external analysis"""
        import csv

        entries = self.query_events(**filters)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Sequence', 'Timestamp', 'Event Type', 'User', 'Role',
                'Description', 'Reason', 'Details', 'Previous Value',
                'New Value', 'Source IP', 'Session ID', 'Node ID'
            ])

            for entry in entries:
                writer.writerow([
                    entry.sequence,
                    entry.timestamp,
                    entry.event_type,
                    entry.user,
                    entry.user_role,
                    entry.description,
                    entry.reason,
                    json.dumps(entry.details) if entry.details else '',
                    json.dumps(entry.previous_value) if entry.previous_value else '',
                    json.dumps(entry.new_value) if entry.new_value else '',
                    entry.source_ip,
                    entry.session_id,
                    entry.node_id
                ])

        return len(entries)

    def get_statistics(self) -> Dict[str, Any]:
        """Get audit trail statistics"""
        stats = {
            'current_sequence': self.sequence,
            'current_file': str(self.current_file) if self.current_file else None,
            'log_files': [],
            'total_size_mb': 0,
            'events_by_type': {},
            'events_by_user': {}
        }

        for log_file in self.audit_dir.glob("audit_*.jsonl*"):
            size_mb = log_file.stat().st_size / (1024 * 1024)
            stats['log_files'].append({
                'name': log_file.name,
                'size_mb': round(size_mb, 2),
                'compressed': log_file.suffix == '.gz'
            })
            stats['total_size_mb'] += size_mb

        stats['total_size_mb'] = round(stats['total_size_mb'], 2)

        return stats
