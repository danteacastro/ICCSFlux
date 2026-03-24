#!/usr/bin/env python3
"""
Archive Manager for NISystem

Provides long-term data archival and retention management:
- Automated archival of recordings based on age
- Archive format with integrity verification
- Retention policy enforcement
- Archive search and retrieval
- Compliance with DOE Order 414.1D / Security Compliance requirements

References:
- Security Compliance Section 3.3 (Audit and Accountability)
- DOE Order 414.1D (Quality Assurance)
- IEC 62443: Industrial Automation Security
"""

import json
import gzip
import shutil
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading

logger = logging.getLogger('ArchiveManager')

class ArchiveFormat(Enum):
    """Archive file format"""
    GZIP = "gzip"           # .gz compression
    ZIP = "zip"             # .zip with directory
    TAR_GZ = "tar.gz"       # .tar.gz archive

class RetentionPeriod(Enum):
    """Standard retention periods (DOE/DOD regulatory guidance)"""
    SHORT = 90              # 90 days - operational data
    MEDIUM = 365            # 1 year - standard records
    LONG = 1825             # 5 years - extended records
    REGULATORY = 3650       # 10 years - regulatory compliance
    PERMANENT = -1          # Never delete

@dataclass
class ArchiveConfig:
    """Archive system configuration"""
    # Archive location
    archive_dir: str = ""

    # Retention settings
    retention_days: int = 3650  # 10 years default (FDA compliance)
    archive_after_days: int = 30  # Move to archive after 30 days

    # Archive format
    format: str = "gzip"
    compression_level: int = 9  # 1-9, higher = smaller file

    # Auto-archival settings
    auto_archive_enabled: bool = True
    auto_archive_interval_hours: int = 24  # Check for archivable files daily

    # Integrity verification
    verify_on_archive: bool = True
    verify_on_retrieve: bool = True

    # Cleanup settings
    cleanup_source_after_archive: bool = True
    cleanup_expired_archives: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ArchiveConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

@dataclass
class ArchiveEntry:
    """Metadata for an archived item"""
    archive_id: str
    original_path: str
    archive_path: str
    archived_at: str
    expires_at: Optional[str]
    file_hash: str
    original_size: int
    archived_size: int
    content_type: str  # 'recording', 'audit', 'project', 'config'
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ArchiveEntry':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

class ArchiveManager:
    """
    Manages long-term data archival and retention.

    Features:
    - Automated archival based on file age
    - Compressed archive storage with integrity verification
    - Retention policy enforcement
    - Archive catalog with search capability
    - Secure retrieval with integrity checking
    """

    def __init__(self,
                 data_dir: Path,
                 archive_dir: Optional[Path] = None):
        """
        Initialize archive manager.

        Args:
            data_dir: Base data directory
            archive_dir: Archive storage location (default: data_dir/archive)
        """
        self.data_dir = Path(data_dir)
        self.archive_dir = Path(archive_dir) if archive_dir else self.data_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        self.config = ArchiveConfig(archive_dir=str(self.archive_dir))
        self.lock = threading.RLock()

        # Archive catalog
        self.catalog: Dict[str, ArchiveEntry] = {}
        self._load_catalog()

        # Auto-archive timer
        self._auto_archive_timer: Optional[threading.Timer] = None
        self._running = False

    def _load_catalog(self):
        """Load archive catalog from disk"""
        catalog_path = self.archive_dir / "catalog.json"
        if catalog_path.exists():
            try:
                with open(catalog_path, 'r') as f:
                    data = json.load(f)
                    for entry_id, entry_data in data.get("entries", {}).items():
                        self.catalog[entry_id] = ArchiveEntry.from_dict(entry_data)
                logger.info(f"Loaded archive catalog: {len(self.catalog)} entries")
            except Exception as e:
                logger.error(f"Failed to load archive catalog: {e}")

    def _save_catalog(self):
        """Save archive catalog to disk"""
        catalog_path = self.archive_dir / "catalog.json"
        try:
            data = {
                "entries": {k: v.to_dict() for k, v in self.catalog.items()},
                "updated": datetime.now().isoformat(),
                "total_entries": len(self.catalog)
            }
            with open(catalog_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save archive catalog: {e}")

    def _compute_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _generate_archive_id(self, content_type: str) -> str:
        """Generate unique archive ID"""
        import secrets
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        random_suffix = secrets.token_hex(4)
        return f"{content_type}_{timestamp}_{random_suffix}"

    # =========================================================================
    # ARCHIVAL OPERATIONS
    # =========================================================================

    def archive_file(self,
                    source_path: Path,
                    content_type: str,
                    metadata: Optional[Dict[str, Any]] = None,
                    retention_days: Optional[int] = None) -> Optional[ArchiveEntry]:
        """
        Archive a file with compression and integrity verification.

        Args:
            source_path: Path to file to archive
            content_type: Type of content ('recording', 'audit', 'project', 'config')
            metadata: Additional metadata to store
            retention_days: Custom retention period (uses config default if None)

        Returns:
            ArchiveEntry if successful, None otherwise
        """
        if not source_path.exists():
            logger.warning(f"Cannot archive non-existent file: {source_path}")
            return None

        with self.lock:
            try:
                archive_id = self._generate_archive_id(content_type)

                # Compute hash before compression
                original_hash = self._compute_hash(source_path)
                original_size = source_path.stat().st_size

                # Determine archive subdirectory based on content type and date
                archive_date = datetime.now()
                archive_subdir = self.archive_dir / content_type / archive_date.strftime('%Y/%m')
                archive_subdir.mkdir(parents=True, exist_ok=True)

                # Create compressed archive
                archive_filename = f"{archive_id}_{source_path.name}.gz"
                archive_path = archive_subdir / archive_filename

                with open(source_path, 'rb') as f_in:
                    with gzip.open(archive_path, 'wb', compresslevel=self.config.compression_level) as f_out:
                        shutil.copyfileobj(f_in, f_out)

                archived_size = archive_path.stat().st_size

                # Calculate expiration
                retention = retention_days or self.config.retention_days
                expires_at = None
                if retention > 0:
                    expires_at = (datetime.now() + timedelta(days=retention)).isoformat()

                # Create catalog entry
                entry = ArchiveEntry(
                    archive_id=archive_id,
                    original_path=str(source_path),
                    archive_path=str(archive_path),
                    archived_at=datetime.now().isoformat(),
                    expires_at=expires_at,
                    file_hash=original_hash,
                    original_size=original_size,
                    archived_size=archived_size,
                    content_type=content_type,
                    metadata=metadata or {}
                )

                self.catalog[archive_id] = entry
                self._save_catalog()

                # Verify archive if configured
                if self.config.verify_on_archive:
                    valid, msg = self.verify_archive(archive_id)
                    if not valid:
                        logger.error(f"Archive verification failed: {msg}")
                        # Delete invalid archive
                        archive_path.unlink()
                        del self.catalog[archive_id]
                        self._save_catalog()
                        return None

                logger.info(f"Archived: {source_path.name} -> {archive_id} "
                           f"(compressed {original_size} -> {archived_size} bytes, "
                           f"{100 * archived_size / original_size:.1f}%)")

                # Clean up source if configured
                if self.config.cleanup_source_after_archive:
                    source_path.unlink()
                    logger.debug(f"Removed source file after archive: {source_path}")

                return entry

            except Exception as e:
                logger.error(f"Failed to archive {source_path}: {e}")
                return None

    def verify_archive(self, archive_id: str) -> Tuple[bool, str]:
        """
        Verify integrity of an archived file.

        Args:
            archive_id: Archive entry ID

        Returns:
            (valid, message) tuple
        """
        entry = self.catalog.get(archive_id)
        if not entry:
            return False, f"Archive not found: {archive_id}"

        archive_path = Path(entry.archive_path)
        if not archive_path.exists():
            return False, f"Archive file missing: {archive_path}"

        try:
            # Decompress and verify hash
            sha256 = hashlib.sha256()
            with gzip.open(archive_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)

            actual_hash = sha256.hexdigest()
            if actual_hash != entry.file_hash:
                return False, f"Hash mismatch: expected {entry.file_hash[:16]}..., got {actual_hash[:16]}..."

            return True, "Integrity verified"

        except Exception as e:
            return False, f"Verification error: {e}"

    def retrieve_archive(self,
                        archive_id: str,
                        destination: Optional[Path] = None) -> Optional[Path]:
        """
        Retrieve and decompress an archived file.

        Args:
            archive_id: Archive entry ID
            destination: Where to extract (default: temp directory)

        Returns:
            Path to extracted file, or None on failure
        """
        entry = self.catalog.get(archive_id)
        if not entry:
            logger.warning(f"Archive not found: {archive_id}")
            return None

        # Verify before retrieval if configured
        if self.config.verify_on_retrieve:
            valid, msg = self.verify_archive(archive_id)
            if not valid:
                logger.error(f"Archive verification failed before retrieval: {msg}")
                return None

        try:
            archive_path = Path(entry.archive_path)
            original_name = Path(entry.original_path).name

            if destination:
                destination.mkdir(parents=True, exist_ok=True)
                output_path = destination / original_name
            else:
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / "nisystem_archive"
                temp_dir.mkdir(parents=True, exist_ok=True)
                output_path = temp_dir / original_name

            with gzip.open(archive_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            logger.info(f"Retrieved archive: {archive_id} -> {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to retrieve archive {archive_id}: {e}")
            return None

    # =========================================================================
    # AUTO-ARCHIVAL
    # =========================================================================

    def start_auto_archive(self):
        """Start automatic archival background process"""
        self._running = True
        self._schedule_auto_archive()
        logger.info("Auto-archive started")

    def stop_auto_archive(self):
        """Stop automatic archival"""
        self._running = False
        if self._auto_archive_timer:
            self._auto_archive_timer.cancel()
            self._auto_archive_timer = None
        logger.info("Auto-archive stopped")

    def _schedule_auto_archive(self):
        """Schedule next auto-archive run"""
        if not self._running:
            return

        interval_seconds = self.config.auto_archive_interval_hours * 3600
        self._auto_archive_timer = threading.Timer(interval_seconds, self._run_auto_archive)
        self._auto_archive_timer.daemon = True
        self._auto_archive_timer.start()

    def _run_auto_archive(self):
        """Run automatic archival process"""
        try:
            archived_count = self.archive_old_files()
            expired_count = self.cleanup_expired_archives()
            logger.info(f"Auto-archive complete: {archived_count} archived, {expired_count} expired removed")
        except Exception as e:
            logger.error(f"Auto-archive error: {e}")
        finally:
            self._schedule_auto_archive()

    def archive_old_files(self) -> int:
        """
        Archive files older than archive_after_days.

        Returns:
            Number of files archived
        """
        if not self.config.auto_archive_enabled:
            return 0

        archived_count = 0
        cutoff_date = datetime.now() - timedelta(days=self.config.archive_after_days)

        # Scan for old recordings
        recordings_dir = self.data_dir
        if recordings_dir.exists():
            for file_path in recordings_dir.glob("**/*.csv"):
                if file_path.stat().st_mtime < cutoff_date.timestamp():
                    entry = self.archive_file(file_path, "recording")
                    if entry:
                        archived_count += 1

        # Scan for old audit logs
        audit_dir = self.data_dir / "audit"
        if audit_dir.exists():
            for file_path in audit_dir.glob("*.jsonl"):
                if file_path.stat().st_mtime < cutoff_date.timestamp():
                    entry = self.archive_file(file_path, "audit")
                    if entry:
                        archived_count += 1

        return archived_count

    def cleanup_expired_archives(self) -> int:
        """
        Remove archives that have exceeded their retention period.

        Returns:
            Number of archives removed
        """
        if not self.config.cleanup_expired_archives:
            return 0

        removed_count = 0
        now = datetime.now()

        with self.lock:
            expired_ids = []
            for archive_id, entry in self.catalog.items():
                if entry.expires_at:
                    expires = datetime.fromisoformat(entry.expires_at)
                    if now > expires:
                        expired_ids.append(archive_id)

            for archive_id in expired_ids:
                entry = self.catalog[archive_id]
                try:
                    archive_path = Path(entry.archive_path)
                    if archive_path.exists():
                        archive_path.unlink()
                    del self.catalog[archive_id]
                    removed_count += 1
                    logger.info(f"Removed expired archive: {archive_id}")
                except Exception as e:
                    logger.error(f"Failed to remove expired archive {archive_id}: {e}")

            if removed_count > 0:
                self._save_catalog()

        return removed_count

    # =========================================================================
    # SEARCH AND QUERY
    # =========================================================================

    def search_archives(self,
                       content_type: Optional[str] = None,
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None,
                       keyword: Optional[str] = None) -> List[ArchiveEntry]:
        """
        Search archive catalog.

        Args:
            content_type: Filter by content type
            start_date: Filter by archive date (from)
            end_date: Filter by archive date (to)
            keyword: Search in original path and metadata

        Returns:
            List of matching ArchiveEntry objects
        """
        results = []

        for entry in self.catalog.values():
            # Filter by content type
            if content_type and entry.content_type != content_type:
                continue

            # Filter by date range
            archived_date = datetime.fromisoformat(entry.archived_at)
            if start_date and archived_date < start_date:
                continue
            if end_date and archived_date > end_date:
                continue

            # Filter by keyword
            if keyword:
                keyword_lower = keyword.lower()
                if keyword_lower not in entry.original_path.lower():
                    # Check metadata
                    metadata_str = json.dumps(entry.metadata).lower()
                    if keyword_lower not in metadata_str:
                        continue

            results.append(entry)

        return sorted(results, key=lambda e: e.archived_at, reverse=True)

    def get_archive_stats(self) -> Dict[str, Any]:
        """Get archive statistics"""
        stats = {
            "total_entries": len(self.catalog),
            "total_archived_size": 0,
            "total_original_size": 0,
            "by_content_type": {},
            "oldest_archive": None,
            "newest_archive": None,
            "expiring_soon": 0  # Within 30 days
        }

        thirty_days = datetime.now() + timedelta(days=30)

        for entry in self.catalog.values():
            stats["total_archived_size"] += entry.archived_size
            stats["total_original_size"] += entry.original_size

            ct = entry.content_type
            if ct not in stats["by_content_type"]:
                stats["by_content_type"][ct] = {"count": 0, "size": 0}
            stats["by_content_type"][ct]["count"] += 1
            stats["by_content_type"][ct]["size"] += entry.archived_size

            archived_date = datetime.fromisoformat(entry.archived_at)
            if not stats["oldest_archive"] or archived_date < datetime.fromisoformat(stats["oldest_archive"]):
                stats["oldest_archive"] = entry.archived_at
            if not stats["newest_archive"] or archived_date > datetime.fromisoformat(stats["newest_archive"]):
                stats["newest_archive"] = entry.archived_at

            if entry.expires_at:
                expires = datetime.fromisoformat(entry.expires_at)
                if expires < thirty_days:
                    stats["expiring_soon"] += 1

        if stats["total_original_size"] > 0:
            stats["compression_ratio"] = stats["total_archived_size"] / stats["total_original_size"]
        else:
            stats["compression_ratio"] = 1.0

        return stats
