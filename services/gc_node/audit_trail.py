"""
Lightweight Audit Trail for GC Node

Provides append-only, tamper-evident logging for GC analysis events:
- Analysis run start/completion
- Result publication
- Configuration changes
- Calibration events
- Error conditions

Features:
- SHA-256 hash chain (each entry chains to the previous)
- Append-only JSONL format
- Auto-rotation at configurable size limit
- Gzip compression of rotated files

Adapted from the cRIO node audit trail. Uses Windows-friendly
default paths since GC nodes run on Windows VMs.
"""

import gzip
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger('GCNode.Audit')

# Default rotation threshold (10 MB)
DEFAULT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


class AuditTrail:
    """
    Lightweight append-only audit trail with SHA-256 hash chain.

    Each entry is JSON with a hash linking to the previous entry,
    making any tampering detectable.
    """

    def __init__(self,
                 audit_dir: str = './audit',
                 node_id: str = 'gc',
                 max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES):
        self._audit_dir = Path(audit_dir)
        self._node_id = node_id
        self._max_file_size_bytes = max_file_size_bytes
        self._lock = threading.Lock()
        self._sequence = 0
        self._prev_hash = 'genesis'
        self._current_file: Optional[Path] = None

        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"Cannot create audit dir {audit_dir}: {e}")

        self._initialize_from_existing()

    def _initialize_from_existing(self):
        """Resume hash chain from the latest existing log entry."""
        log_files = sorted(self._audit_dir.glob('audit_*.jsonl'), reverse=True)

        for log_file in log_files:
            try:
                with open(log_file, 'rb') as f:
                    f.seek(0, 2)
                    file_size = f.tell()
                    if file_size == 0:
                        continue
                    read_size = min(file_size, 4096)
                    f.seek(file_size - read_size)
                    data = f.read().decode('utf-8', errors='replace').strip()

                lines = data.split('\n')
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    self._sequence = entry.get('seq', 0)
                    self._prev_hash = entry.get('hash', 'genesis')
                    self._current_file = log_file
                    logger.info(f"Resumed audit trail at seq {self._sequence} from {log_file.name}")
                    return
            except Exception as e:
                logger.warning(f"Could not read audit file {log_file}: {e}")

        # No existing logs — start fresh
        self._create_new_log_file()

    def _create_new_log_file(self):
        """Create a new timestamped log file."""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._current_file = self._audit_dir / f'audit_{ts}.jsonl'

    def _rotate_if_needed(self):
        """Rotate log file if it exceeds size limit."""
        if self._current_file is None or not self._current_file.exists():
            self._create_new_log_file()
            return

        try:
            size = self._current_file.stat().st_size
        except OSError:
            return

        if size >= self._max_file_size_bytes:
            # Gzip the old file
            gz_path = self._current_file.with_suffix('.jsonl.gz')
            try:
                with open(self._current_file, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        f_out.write(f_in.read())
                self._current_file.unlink()
                logger.info(f"Audit log rotated: {self._current_file.name} -> {gz_path.name}")
            except Exception as e:
                logger.warning(f"Audit rotation failed: {e}")

            self._create_new_log_file()

    def log_event(self, event_type: str, channel: str = '', details: Optional[Dict[str, Any]] = None,
                  operator: str = 'SYSTEM'):
        """
        Write a single audit event.

        Args:
            event_type: Event category (analysis_start, analysis_complete,
                        result_published, config_change, calibration, error, etc.)
            channel: Related channel name (empty for system events)
            details: Additional structured data
            operator: Who initiated the action
        """
        with self._lock:
            self._rotate_if_needed()

            self._sequence += 1
            now = datetime.now(timezone.utc)

            entry = {
                'seq': self._sequence,
                'ts': now.isoformat(),
                'node': self._node_id,
                'type': event_type,
                'channel': channel,
                'operator': operator,
                'details': details or {},
                'prev_hash': self._prev_hash,
            }

            # Compute hash of the entry (without the hash field itself)
            payload = json.dumps(entry, sort_keys=True, separators=(',', ':'))
            entry_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            entry['hash'] = entry_hash
            self._prev_hash = entry_hash

            # Write to file
            if self._current_file is None:
                self._create_new_log_file()
            try:
                with open(self._current_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, separators=(',', ':')) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                logger.error(f"Audit write failed: {e}")

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verify the hash chain integrity of the current log file.

        Returns:
            Dict with 'valid' (bool), 'entries_checked' (int), 'errors' (list)
        """
        result = {'valid': True, 'entries_checked': 0, 'errors': []}

        if not self._current_file or not self._current_file.exists():
            return result

        prev_hash = 'genesis'
        try:
            with open(self._current_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as e:
                        result['valid'] = False
                        result['errors'].append(f"Line {line_num}: invalid JSON: {e}")
                        continue

                    result['entries_checked'] += 1

                    # Verify prev_hash chain
                    if entry.get('prev_hash') != prev_hash:
                        result['valid'] = False
                        result['errors'].append(
                            f"Line {line_num}: prev_hash mismatch (expected {prev_hash[:16]}...)")

                    # Verify entry hash
                    stored_hash = entry.pop('hash', '')
                    payload = json.dumps(entry, sort_keys=True, separators=(',', ':'))
                    computed_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
                    entry['hash'] = stored_hash  # restore

                    if computed_hash != stored_hash:
                        result['valid'] = False
                        result['errors'].append(
                            f"Line {line_num}: hash mismatch (tampering detected)")

                    prev_hash = stored_hash

        except Exception as e:
            result['valid'] = False
            result['errors'].append(f"Read error: {e}")

        return result
