"""
Tests for archive_manager.py
Covers long-term data archival, retention policies, and integrity verification.
Critical for FDA 21 CFR Part 11 / ALCOA+ compliance.
"""

import pytest
import tempfile
import gzip
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from archive_manager import (
    ArchiveManager, ArchiveConfig, ArchiveEntry,
    ArchiveFormat, RetentionPeriod
)


class TestArchiveFormat:
    """Tests for ArchiveFormat enum"""

    def test_format_values(self):
        """Test all format values exist"""
        assert ArchiveFormat.GZIP.value == "gzip"
        assert ArchiveFormat.ZIP.value == "zip"
        assert ArchiveFormat.TAR_GZ.value == "tar.gz"


class TestRetentionPeriod:
    """Tests for RetentionPeriod enum"""

    def test_retention_values(self):
        """Test retention period values"""
        assert RetentionPeriod.SHORT.value == 90
        assert RetentionPeriod.MEDIUM.value == 365
        assert RetentionPeriod.LONG.value == 1825
        assert RetentionPeriod.REGULATORY.value == 3650  # 10 years
        assert RetentionPeriod.PERMANENT.value == -1


class TestArchiveConfig:
    """Tests for ArchiveConfig dataclass"""

    def test_defaults(self):
        """Test default values"""
        config = ArchiveConfig()

        assert config.retention_days == 3650  # 10 years default
        assert config.archive_after_days == 30
        assert config.compression_level == 9
        assert config.auto_archive_enabled is True
        assert config.verify_on_archive is True

    def test_to_dict(self):
        """Test conversion to dictionary"""
        config = ArchiveConfig(retention_days=365)

        d = config.to_dict()

        assert d['retention_days'] == 365
        assert 'archive_dir' in d
        assert 'compression_level' in d

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'retention_days': 180,
            'compression_level': 6,
            'auto_archive_enabled': False
        }

        config = ArchiveConfig.from_dict(d)

        assert config.retention_days == 180
        assert config.compression_level == 6
        assert config.auto_archive_enabled is False


class TestArchiveEntry:
    """Tests for ArchiveEntry dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        entry = ArchiveEntry(
            archive_id="rec_20250115_abc123",
            original_path="/data/recording.csv",
            archive_path="/archive/recording.csv.gz",
            archived_at="2025-01-15T10:30:00",
            expires_at="2035-01-15T10:30:00",
            file_hash="abc123def456",
            original_size=1000000,
            archived_size=250000,
            content_type="recording"
        )

        d = entry.to_dict()

        assert d['archive_id'] == "rec_20250115_abc123"
        assert d['content_type'] == "recording"
        assert d['original_size'] == 1000000

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'archive_id': 'test_123',
            'original_path': '/data/test.csv',
            'archive_path': '/archive/test.csv.gz',
            'archived_at': '2025-01-15T10:00:00',
            'expires_at': None,
            'file_hash': 'hash123',
            'original_size': 5000,
            'archived_size': 1000,
            'content_type': 'recording'
        }

        entry = ArchiveEntry.from_dict(d)

        assert entry.archive_id == 'test_123'
        assert entry.expires_at is None


class TestArchiveManager:
    """Tests for ArchiveManager class"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for data and archive"""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            archive_dir = Path(tmpdir) / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()
            yield data_dir, archive_dir

    @pytest.fixture
    def manager(self, temp_dirs):
        """Create an ArchiveManager instance"""
        data_dir, archive_dir = temp_dirs
        return ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)

    @pytest.fixture
    def sample_file(self, temp_dirs):
        """Create a sample data file"""
        data_dir, _ = temp_dirs
        file_path = data_dir / "recording_20250115.csv"
        file_path.write_text("timestamp,value\n2025-01-15T10:00:00,25.5\n" * 1000)
        return file_path

    # =========================================================================
    # INITIALIZATION TESTS
    # =========================================================================

    def test_initialization(self, manager, temp_dirs):
        """Test manager initialization"""
        data_dir, archive_dir = temp_dirs

        assert manager.data_dir == data_dir
        assert manager.archive_dir == archive_dir
        assert manager.config.retention_days == 3650

    def test_directories_created(self, temp_dirs):
        """Test that archive directory is created if missing"""
        data_dir, _ = temp_dirs
        new_archive = data_dir / "new_archive"

        manager = ArchiveManager(data_dir=data_dir, archive_dir=new_archive)

        assert new_archive.exists()

    def test_catalog_loaded(self, temp_dirs):
        """Test that catalog is loaded on init"""
        data_dir, archive_dir = temp_dirs

        # Create a catalog file
        catalog = {
            "entries": {
                "test_123": {
                    "archive_id": "test_123",
                    "original_path": "/data/test.csv",
                    "archive_path": "/archive/test.csv.gz",
                    "archived_at": "2025-01-15T10:00:00",
                    "expires_at": None,
                    "file_hash": "hash123",
                    "original_size": 5000,
                    "archived_size": 1000,
                    "content_type": "recording",
                    "metadata": {}
                }
            }
        }
        catalog_path = archive_dir / "catalog.json"
        with open(catalog_path, 'w') as f:
            json.dump(catalog, f)

        manager = ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)

        assert "test_123" in manager.catalog

    # =========================================================================
    # ARCHIVE TESTS
    # =========================================================================

    def test_archive_file(self, manager, sample_file):
        """Test archiving a file"""
        entry = manager.archive_file(
            source_path=sample_file,
            content_type="recording",
            metadata={"experiment": "test1"}
        )

        assert entry is not None
        assert entry.content_type == "recording"
        assert entry.archive_id in manager.catalog
        assert Path(entry.archive_path).exists()
        assert entry.archived_size < entry.original_size  # Compressed

    def test_archive_file_nonexistent(self, manager, temp_dirs):
        """Test archiving nonexistent file returns None"""
        data_dir, _ = temp_dirs
        nonexistent = data_dir / "nonexistent.csv"

        entry = manager.archive_file(nonexistent, "recording")

        assert entry is None

    def test_archive_file_with_retention(self, manager, sample_file):
        """Test archiving with custom retention"""
        entry = manager.archive_file(
            source_path=sample_file,
            content_type="recording",
            retention_days=90
        )

        assert entry.expires_at is not None
        expires = datetime.fromisoformat(entry.expires_at)
        expected = datetime.now() + timedelta(days=90)
        assert abs((expires - expected).days) <= 1

    def test_archive_file_permanent_retention(self, manager, sample_file):
        """Test archiving with permanent retention"""
        manager.config.retention_days = -1

        entry = manager.archive_file(sample_file, "recording")

        assert entry.expires_at is None

    def test_archive_file_removes_source(self, manager, sample_file):
        """Test that archiving removes source by default"""
        manager.config.cleanup_source_after_archive = True

        manager.archive_file(sample_file, "recording")

        assert not sample_file.exists()

    def test_archive_file_keeps_source(self, manager, sample_file):
        """Test keeping source file after archive"""
        manager.config.cleanup_source_after_archive = False

        manager.archive_file(sample_file, "recording")

        assert sample_file.exists()

    def test_archive_creates_subdirectories(self, manager, sample_file):
        """Test that archive creates content-type/year/month subdirectories"""
        entry = manager.archive_file(sample_file, "recording")

        archive_path = Path(entry.archive_path)
        # Should be in archive_dir/recording/YYYY/MM/
        assert "recording" in str(archive_path)

    # =========================================================================
    # VERIFY TESTS
    # =========================================================================

    def test_verify_archive_valid(self, manager, sample_file):
        """Test verifying a valid archive"""
        entry = manager.archive_file(sample_file, "recording")

        valid, message = manager.verify_archive(entry.archive_id)

        assert valid is True
        assert "verified" in message.lower()

    def test_verify_archive_not_found(self, manager):
        """Test verifying nonexistent archive"""
        valid, message = manager.verify_archive("nonexistent_id")

        assert valid is False
        assert "not found" in message.lower()

    def test_verify_archive_corrupted(self, manager, sample_file):
        """Test verifying corrupted archive"""
        entry = manager.archive_file(sample_file, "recording")

        # Corrupt the archive
        archive_path = Path(entry.archive_path)
        archive_path.write_bytes(b"corrupted data")

        valid, message = manager.verify_archive(entry.archive_id)

        assert valid is False

    def test_verify_archive_missing_file(self, manager, sample_file):
        """Test verifying archive with missing file"""
        entry = manager.archive_file(sample_file, "recording")

        # Delete the archive file
        Path(entry.archive_path).unlink()

        valid, message = manager.verify_archive(entry.archive_id)

        assert valid is False
        assert "missing" in message.lower()

    # =========================================================================
    # RETRIEVE TESTS
    # =========================================================================

    def test_retrieve_archive(self, manager, sample_file, temp_dirs):
        """Test retrieving an archived file"""
        original_content = sample_file.read_text()
        entry = manager.archive_file(sample_file, "recording")

        data_dir, _ = temp_dirs
        dest = data_dir / "retrieved"

        retrieved_path = manager.retrieve_archive(entry.archive_id, dest)

        assert retrieved_path is not None
        assert retrieved_path.exists()
        assert retrieved_path.read_text() == original_content

    def test_retrieve_archive_not_found(self, manager, temp_dirs):
        """Test retrieving nonexistent archive"""
        data_dir, _ = temp_dirs

        path = manager.retrieve_archive("nonexistent", data_dir)

        assert path is None

    def test_retrieve_archive_to_temp(self, manager, sample_file):
        """Test retrieving to temp directory (no destination)"""
        entry = manager.archive_file(sample_file, "recording")

        retrieved_path = manager.retrieve_archive(entry.archive_id)

        assert retrieved_path is not None
        assert retrieved_path.exists()

    def test_retrieve_verifies_integrity(self, manager, sample_file):
        """Test that retrieve verifies integrity"""
        manager.config.verify_on_retrieve = True
        entry = manager.archive_file(sample_file, "recording")

        # Corrupt the archive
        Path(entry.archive_path).write_bytes(b"corrupted")

        path = manager.retrieve_archive(entry.archive_id)

        assert path is None  # Should fail integrity check

    # =========================================================================
    # SEARCH TESTS
    # =========================================================================

    def test_search_by_content_type(self, manager, temp_dirs):
        """Test searching by content type"""
        data_dir, _ = temp_dirs

        # Create files of different types
        rec_file = data_dir / "recording.csv"
        rec_file.write_text("data")
        manager.archive_file(rec_file, "recording")

        audit_file = data_dir / "audit.jsonl"
        audit_file.write_text("data")
        manager.archive_file(audit_file, "audit")

        results = manager.search_archives(content_type="recording")

        assert len(results) == 1
        assert results[0].content_type == "recording"

    def test_search_by_date_range(self, manager, sample_file):
        """Test searching by date range"""
        manager.archive_file(sample_file, "recording")

        # Search for archives from today
        start = datetime.now() - timedelta(hours=1)
        end = datetime.now() + timedelta(hours=1)

        results = manager.search_archives(start_date=start, end_date=end)

        assert len(results) >= 1

    def test_search_by_keyword(self, manager, temp_dirs):
        """Test searching by keyword in path"""
        data_dir, _ = temp_dirs

        file1 = data_dir / "experiment_001.csv"
        file1.write_text("data")
        manager.archive_file(file1, "recording")

        file2 = data_dir / "calibration_001.csv"
        file2.write_text("data")
        manager.archive_file(file2, "recording")

        results = manager.search_archives(keyword="experiment")

        assert len(results) == 1
        assert "experiment" in results[0].original_path

    def test_search_results_sorted(self, manager, temp_dirs):
        """Test that search results are sorted by date (newest first)"""
        data_dir, _ = temp_dirs

        for i in range(3):
            file = data_dir / f"file_{i}.csv"
            file.write_text("data")
            manager.archive_file(file, "recording")
            time.sleep(0.01)

        results = manager.search_archives()

        # Should be sorted newest first
        assert len(results) == 3
        for i in range(len(results) - 1):
            assert results[i].archived_at >= results[i + 1].archived_at

    # =========================================================================
    # CLEANUP TESTS
    # =========================================================================

    def test_cleanup_expired_archives(self, manager, temp_dirs):
        """Test cleaning up expired archives"""
        data_dir, _ = temp_dirs

        file = data_dir / "old_file.csv"
        file.write_text("data")
        entry = manager.archive_file(file, "recording", retention_days=0)

        # Manually set expiration to past
        manager.catalog[entry.archive_id].expires_at = (
            datetime.now() - timedelta(days=1)
        ).isoformat()

        removed = manager.cleanup_expired_archives()

        assert removed >= 1
        assert entry.archive_id not in manager.catalog

    def test_cleanup_removes_files(self, manager, temp_dirs):
        """Test that cleanup removes archive files"""
        data_dir, _ = temp_dirs

        file = data_dir / "old_file.csv"
        file.write_text("data")
        entry = manager.archive_file(file, "recording", retention_days=0)
        archive_path = Path(entry.archive_path)

        # Expire it
        manager.catalog[entry.archive_id].expires_at = (
            datetime.now() - timedelta(days=1)
        ).isoformat()

        manager.cleanup_expired_archives()

        assert not archive_path.exists()

    def test_cleanup_disabled(self, manager, temp_dirs):
        """Test that cleanup can be disabled"""
        manager.config.cleanup_expired_archives = False

        data_dir, _ = temp_dirs
        file = data_dir / "file.csv"
        file.write_text("data")
        entry = manager.archive_file(file, "recording")

        # Expire it
        manager.catalog[entry.archive_id].expires_at = (
            datetime.now() - timedelta(days=1)
        ).isoformat()

        removed = manager.cleanup_expired_archives()

        assert removed == 0
        assert entry.archive_id in manager.catalog

    # =========================================================================
    # STATISTICS TESTS
    # =========================================================================

    def test_get_archive_stats(self, manager, temp_dirs):
        """Test getting archive statistics"""
        data_dir, _ = temp_dirs

        # Create some archives
        for i in range(3):
            file = data_dir / f"file_{i}.csv"
            file.write_text("data" * 100)
            manager.archive_file(file, "recording")

        stats = manager.get_archive_stats()

        assert stats['total_entries'] == 3
        assert stats['total_archived_size'] > 0
        assert stats['total_original_size'] > 0
        assert 'compression_ratio' in stats
        assert 'by_content_type' in stats
        assert 'recording' in stats['by_content_type']

    def test_get_archive_stats_empty(self, manager):
        """Test stats with empty archive"""
        stats = manager.get_archive_stats()

        assert stats['total_entries'] == 0
        assert stats['compression_ratio'] == 1.0

    # =========================================================================
    # AUTO-ARCHIVE TESTS
    # =========================================================================

    def test_start_auto_archive(self, manager):
        """Test starting auto-archive"""
        manager.start_auto_archive()

        assert manager._running is True

        manager.stop_auto_archive()

    def test_stop_auto_archive(self, manager):
        """Test stopping auto-archive"""
        manager.start_auto_archive()
        manager.stop_auto_archive()

        assert manager._running is False
        assert manager._auto_archive_timer is None

    def test_archive_old_files_disabled(self, manager):
        """Test that archive_old_files respects enabled setting"""
        manager.config.auto_archive_enabled = False

        count = manager.archive_old_files()

        assert count == 0

    # =========================================================================
    # CATALOG PERSISTENCE TESTS
    # =========================================================================

    def test_catalog_saved(self, manager, sample_file, temp_dirs):
        """Test that catalog is saved after archiving"""
        manager.archive_file(sample_file, "recording")

        # Check catalog file exists
        catalog_path = manager.archive_dir / "catalog.json"
        assert catalog_path.exists()

        with open(catalog_path) as f:
            data = json.load(f)
        assert len(data['entries']) == 1

    def test_catalog_persists(self, temp_dirs, sample_file):
        """Test catalog persists across manager instances"""
        data_dir, archive_dir = temp_dirs

        # First manager archives a file
        manager1 = ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)
        entry = manager1.archive_file(sample_file, "recording")

        # Second manager should see the entry
        manager2 = ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)
        assert entry.archive_id in manager2.catalog


class TestArchiveIntegrity:
    """Tests for archive integrity features"""

    @pytest.fixture
    def temp_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            archive_dir = Path(tmpdir) / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()
            yield data_dir, archive_dir

    @pytest.fixture
    def manager(self, temp_dirs):
        data_dir, archive_dir = temp_dirs
        return ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)

    def test_hash_computed_before_compression(self, manager, temp_dirs):
        """Test that hash is computed on original file"""
        data_dir, _ = temp_dirs
        file = data_dir / "test.csv"
        content = b"timestamp,value\n2025-01-15,100\n"
        file.write_bytes(content)  # Binary mode for consistent hash

        entry = manager.archive_file(file, "recording")

        # Hash should be of original content
        import hashlib
        expected_hash = hashlib.sha256(content).hexdigest()
        assert entry.file_hash == expected_hash

    def test_verify_on_archive_enabled(self, manager, temp_dirs):
        """Test verification during archive when enabled"""
        manager.config.verify_on_archive = True

        data_dir, _ = temp_dirs
        file = data_dir / "test.csv"
        file.write_text("data")

        entry = manager.archive_file(file, "recording")

        # Should succeed since archive is valid
        assert entry is not None

    def test_archive_generates_unique_ids(self, manager, temp_dirs):
        """Test that archive IDs are unique"""
        data_dir, _ = temp_dirs
        ids = set()

        for i in range(10):
            file = data_dir / f"test_{i}.csv"
            file.write_text(f"data_{i}")
            entry = manager.archive_file(file, "recording")
            ids.add(entry.archive_id)

        assert len(ids) == 10  # All unique
