#!/usr/bin/env python3
"""
Unit tests for ArchiveManager

Tests:
- File archival with compression
- Integrity verification
- Archive retrieval
- Catalog management
- Search and query
- Retention and cleanup
"""

import pytest
import tempfile
import shutil
import json
import gzip
from pathlib import Path
from datetime import datetime, timedelta
import hashlib

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from archive_manager import ArchiveManager, ArchiveConfig, ArchiveEntry


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def archive_manager(temp_dir):
    """Create a fresh ArchiveManager for each test"""
    data_dir = temp_dir / "data"
    data_dir.mkdir()
    archive_dir = temp_dir / "archive"

    manager = ArchiveManager(
        data_dir=data_dir,
        archive_dir=archive_dir
    )
    return manager


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample file to archive"""
    file_path = temp_dir / "sample_recording.csv"
    content = "timestamp,value\n"
    for i in range(1000):
        content += f"2024-01-01T12:00:{i:02d},25.{i}\n"

    with open(file_path, 'w') as f:
        f.write(content)

    return file_path


class TestArchiveFile:
    """Tests for file archival"""

    def test_archive_file_success(self, archive_manager, sample_file):
        """Should successfully archive a file"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording",
            metadata={"session_id": "sess123", "channels": ["TC001", "TC002"]}
        )

        assert entry is not None
        assert entry.content_type == "recording"
        assert entry.original_path == str(sample_file)
        assert entry.archived_size < entry.original_size  # Compressed
        assert "sess123" in str(entry.metadata)

    def test_archive_creates_compressed_file(self, archive_manager, sample_file):
        """Archive should be gzip compressed"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        archive_path = Path(entry.archive_path)
        assert archive_path.exists()
        assert archive_path.suffix == ".gz"

        # Verify it's valid gzip
        with gzip.open(archive_path, 'rb') as f:
            content = f.read()
            assert b"timestamp,value" in content

    def test_archive_computes_hash(self, archive_manager, sample_file):
        """Archive should compute and store SHA-256 hash"""
        # Compute expected hash
        sha256 = hashlib.sha256()
        with open(sample_file, 'rb') as f:
            sha256.update(f.read())
        expected_hash = sha256.hexdigest()

        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        assert entry.file_hash == expected_hash

    def test_archive_nonexistent_file(self, archive_manager):
        """Archiving nonexistent file should return None"""
        entry = archive_manager.archive_file(
            source_path=Path("/nonexistent/file.csv"),
            content_type="recording"
        )

        assert entry is None

    def test_archive_removes_source(self, archive_manager, sample_file):
        """Source file should be removed after archival by default"""
        archive_manager.config.cleanup_source_after_archive = True
        assert sample_file.exists()

        archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        assert not sample_file.exists()

    def test_archive_preserves_source(self, archive_manager, sample_file):
        """Source file should be preserved if configured"""
        archive_manager.config.cleanup_source_after_archive = False

        archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        assert sample_file.exists()

    def test_archive_custom_retention(self, archive_manager, sample_file):
        """Should respect custom retention period"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording",
            retention_days=90
        )

        expires = datetime.fromisoformat(entry.expires_at)
        expected = datetime.now() + timedelta(days=90)

        # Should expire approximately 90 days from now
        assert abs((expires - expected).days) <= 1

    def test_archive_organizes_by_type_and_date(self, archive_manager, sample_file):
        """Archives should be organized in subdirectories"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        archive_path = Path(entry.archive_path)

        # Should be in recording/YYYY/MM/ subdirectory
        assert "recording" in str(archive_path)
        assert archive_path.parent.name.isdigit()  # Month directory


class TestIntegrityVerification:
    """Tests for archive integrity verification"""

    def test_verify_valid_archive(self, archive_manager, sample_file):
        """Valid archive should pass verification"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        is_valid, message = archive_manager.verify_archive(entry.archive_id)

        assert is_valid is True
        assert "verified" in message.lower()

    def test_verify_corrupted_archive(self, archive_manager, sample_file):
        """Corrupted archive should fail verification"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        # Corrupt the archive file
        archive_path = Path(entry.archive_path)
        with open(archive_path, 'ab') as f:
            f.write(b"CORRUPTED DATA")

        is_valid, message = archive_manager.verify_archive(entry.archive_id)

        assert is_valid is False

    def test_verify_missing_archive(self, archive_manager):
        """Missing archive should fail verification"""
        is_valid, message = archive_manager.verify_archive("nonexistent_id")

        assert is_valid is False
        assert "not found" in message.lower()

    def test_verify_deleted_file(self, archive_manager, sample_file):
        """Deleted archive file should fail verification"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        # Delete the archive file
        Path(entry.archive_path).unlink()

        is_valid, message = archive_manager.verify_archive(entry.archive_id)

        assert is_valid is False
        assert "missing" in message.lower()


class TestArchiveRetrieval:
    """Tests for archive retrieval"""

    def test_retrieve_archive(self, archive_manager, sample_file, temp_dir):
        """Should retrieve and decompress archive"""
        # Read original content
        with open(sample_file, 'rb') as f:
            original_content = f.read()

        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        # Retrieve to destination
        dest_dir = temp_dir / "retrieved"
        retrieved_path = archive_manager.retrieve_archive(
            archive_id=entry.archive_id,
            destination=dest_dir
        )

        assert retrieved_path is not None
        assert retrieved_path.exists()

        # Content should match original
        with open(retrieved_path, 'rb') as f:
            retrieved_content = f.read()

        assert retrieved_content == original_content

    def test_retrieve_to_temp(self, archive_manager, sample_file):
        """Should retrieve to temp directory if no destination specified"""
        entry = archive_manager.archive_file(
            source_path=sample_file,
            content_type="recording"
        )

        retrieved_path = archive_manager.retrieve_archive(
            archive_id=entry.archive_id
        )

        assert retrieved_path is not None
        assert retrieved_path.exists()
        assert "temp" in str(retrieved_path).lower() or "tmp" in str(retrieved_path).lower()

    def test_retrieve_nonexistent(self, archive_manager):
        """Retrieving nonexistent archive should return None"""
        result = archive_manager.retrieve_archive("nonexistent_id")
        assert result is None


class TestCatalog:
    """Tests for archive catalog management"""

    def test_catalog_persistence(self, temp_dir):
        """Catalog should persist across restarts"""
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        archive_dir = temp_dir / "archive"

        # Create sample file
        sample = data_dir / "test.csv"
        sample.write_text("a,b,c\n1,2,3\n")

        # Create manager and archive
        manager1 = ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)
        entry = manager1.archive_file(sample, "recording")
        archive_id = entry.archive_id

        # Create new manager instance
        manager2 = ArchiveManager(data_dir=data_dir, archive_dir=archive_dir)

        assert archive_id in manager2.catalog
        assert manager2.catalog[archive_id].content_type == "recording"

    def test_catalog_updates_on_archive(self, archive_manager, sample_file):
        """Catalog should update when file is archived"""
        initial_count = len(archive_manager.catalog)

        archive_manager.archive_file(sample_file, "recording")

        assert len(archive_manager.catalog) == initial_count + 1

    def test_unique_archive_ids(self, archive_manager, temp_dir):
        """Each archive should have unique ID"""
        ids = set()

        for i in range(10):
            sample = temp_dir / f"file_{i}.csv"
            sample.write_text(f"data,{i}\n")

            entry = archive_manager.archive_file(sample, "recording")
            assert entry.archive_id not in ids
            ids.add(entry.archive_id)


class TestSearch:
    """Tests for archive search functionality"""

    def test_search_by_content_type(self, archive_manager, temp_dir):
        """Should filter by content type"""
        # Create different types
        for i, content_type in enumerate(["recording", "audit", "recording", "config"]):
            sample = temp_dir / f"file_{i}.csv"
            sample.write_text(f"data,{i}\n")
            archive_manager.archive_file(sample, content_type)

        results = archive_manager.search_archives(content_type="recording")

        assert len(results) == 2
        assert all(e.content_type == "recording" for e in results)

    def test_search_by_keyword(self, archive_manager, temp_dir):
        """Should search by keyword in path"""
        for name in ["sensor_data.csv", "alarm_log.csv", "sensor_backup.csv"]:
            sample = temp_dir / name
            sample.write_text("data\n")
            archive_manager.archive_file(sample, "recording")

        results = archive_manager.search_archives(keyword="sensor")

        assert len(results) == 2

    def test_search_empty_results(self, archive_manager, sample_file):
        """Should return empty list for no matches"""
        archive_manager.archive_file(sample_file, "recording")

        results = archive_manager.search_archives(content_type="nonexistent")

        assert len(results) == 0


class TestRetentionCleanup:
    """Tests for retention and cleanup"""

    def test_cleanup_expired_archives(self, archive_manager, temp_dir):
        """Should remove expired archives"""
        # Create archive with very short retention
        sample = temp_dir / "expired.csv"
        sample.write_text("old data\n")

        entry = archive_manager.archive_file(
            sample, "recording", retention_days=0
        )

        # Manually set expiration to past
        entry.expires_at = (datetime.now() - timedelta(days=1)).isoformat()
        archive_manager.catalog[entry.archive_id] = entry
        archive_manager._save_catalog()

        # Run cleanup
        removed = archive_manager.cleanup_expired_archives()

        assert removed == 1
        assert entry.archive_id not in archive_manager.catalog

    def test_preserve_non_expired(self, archive_manager, temp_dir):
        """Should preserve non-expired archives"""
        sample = temp_dir / "current.csv"
        sample.write_text("current data\n")

        entry = archive_manager.archive_file(
            sample, "recording", retention_days=365
        )

        removed = archive_manager.cleanup_expired_archives()

        assert removed == 0
        assert entry.archive_id in archive_manager.catalog


class TestStatistics:
    """Tests for archive statistics"""

    def test_get_stats_empty(self, archive_manager):
        """Should return stats for empty archive"""
        stats = archive_manager.get_archive_stats()

        assert stats["total_entries"] == 0
        assert stats["total_archived_size"] == 0

    def test_get_stats_with_entries(self, archive_manager, temp_dir):
        """Should return correct stats"""
        for i in range(5):
            sample = temp_dir / f"file_{i}.csv"
            content = "a,b,c\n" + "1,2,3\n" * (100 * (i + 1))
            sample.write_text(content)
            archive_manager.archive_file(sample, "recording")

        stats = archive_manager.get_archive_stats()

        assert stats["total_entries"] == 5
        assert stats["total_archived_size"] > 0
        assert stats["total_original_size"] > stats["total_archived_size"]
        assert stats["compression_ratio"] < 1.0
        assert stats["oldest_archive"] is not None
        assert stats["newest_archive"] is not None

    def test_stats_by_content_type(self, archive_manager, temp_dir):
        """Should track stats by content type"""
        for content_type in ["recording", "recording", "audit", "config"]:
            sample = temp_dir / f"{content_type}_{id(content_type)}.csv"
            sample.write_text("data\n")
            archive_manager.archive_file(sample, content_type)

        stats = archive_manager.get_archive_stats()

        assert "by_content_type" in stats
        assert stats["by_content_type"]["recording"]["count"] == 2
        assert stats["by_content_type"]["audit"]["count"] == 1
        assert stats["by_content_type"]["config"]["count"] == 1


class TestAutoArchive:
    """Tests for automatic archival"""

    def test_start_stop_auto_archive(self, archive_manager):
        """Should start and stop auto-archive without error"""
        archive_manager.start_auto_archive()
        assert archive_manager._running is True

        archive_manager.stop_auto_archive()
        assert archive_manager._running is False

    def test_archive_old_files(self, archive_manager, temp_dir):
        """Should archive files older than threshold"""
        # Create old file
        old_file = archive_manager.data_dir / "old_recording.csv"
        old_file.write_text("old data\n")

        # Set modification time to past
        import os
        old_time = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_file, (old_time, old_time))

        archive_manager.config.archive_after_days = 30
        archive_manager.config.auto_archive_enabled = True

        archived_count = archive_manager.archive_old_files()

        assert archived_count >= 1


class TestConfig:
    """Tests for archive configuration"""

    def test_default_config(self, archive_manager):
        """Should have sensible defaults"""
        assert archive_manager.config.retention_days == 3650  # 10 years
        assert archive_manager.config.compression_level == 9
        assert archive_manager.config.verify_on_archive is True
        assert archive_manager.config.verify_on_retrieve is True

    def test_config_serialization(self):
        """Config should serialize and deserialize"""
        config = ArchiveConfig(
            retention_days=365,
            compression_level=5,
            verify_on_archive=False
        )

        data = config.to_dict()
        restored = ArchiveConfig.from_dict(data)

        assert restored.retention_days == 365
        assert restored.compression_level == 5
        assert restored.verify_on_archive is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
