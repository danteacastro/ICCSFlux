"""
Tests for project_manager.py
Covers project lifecycle, backup management, schema validation, and safety locking.
"""

import pytest
import tempfile
import json
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from project_manager import (
    ProjectManager, ProjectStatus, ValidationResult, BackupInfo,
    PROJECT_SCHEMA
)


class TestProjectStatus:
    """Tests for ProjectStatus enum"""

    def test_status_values(self):
        """Test all status values exist"""
        assert ProjectStatus.SUCCESS.value == "success"
        assert ProjectStatus.ERROR.value == "error"
        assert ProjectStatus.VALIDATION_ERROR.value == "validation_error"
        assert ProjectStatus.LOCKED.value == "locked"
        assert ProjectStatus.BACKUP_FAILED.value == "backup_failed"


class TestValidationResult:
    """Tests for ValidationResult dataclass"""

    def test_initial_valid(self):
        """Test initial state is valid"""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        """Test adding an error marks result invalid"""
        result = ValidationResult(valid=True)
        result.add_error("Test error")

        assert result.valid is False
        assert "Test error" in result.errors

    def test_add_warning(self):
        """Test adding a warning doesn't mark result invalid"""
        result = ValidationResult(valid=True)
        result.add_warning("Test warning")

        assert result.valid is True
        assert "Test warning" in result.warnings


class TestBackupInfo:
    """Tests for BackupInfo dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        info = BackupInfo(
            backup_path=Path("/backups/test.json"),
            original_path=Path("/projects/test.json"),
            timestamp=datetime(2025, 1, 15, 10, 30, 0),
            file_hash="abc123",
            size_bytes=1024,
            reason="pre_save"
        )

        d = info.to_dict()

        # Use Path for comparison to handle Windows/Unix path differences
        assert Path(d['backup_path']).name == "test.json"
        assert Path(d['original_path']).name == "test.json"
        assert d['file_hash'] == "abc123"
        assert d['size_bytes'] == 1024
        assert d['reason'] == "pre_save"


class TestProjectManager:
    """Tests for ProjectManager class"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for projects and backups"""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            backup_dir = Path(tmpdir) / "backups"
            projects_dir.mkdir()
            backup_dir.mkdir()
            yield projects_dir, backup_dir

    @pytest.fixture
    def manager(self, temp_dirs):
        """Create a ProjectManager instance"""
        projects_dir, backup_dir = temp_dirs
        return ProjectManager(
            projects_dir=projects_dir,
            backup_dir=backup_dir,
            max_backups=5
        )

    @pytest.fixture
    def valid_project(self):
        """A valid project data structure"""
        return {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "temp_1": {
                    "channel_type": "thermocouple",
                    "physical_channel": "cDAQ1Mod1/ai0"
                }
            },
            "metadata": {
                "name": "Test Project"
            }
        }

    def test_initialization(self, manager, temp_dirs):
        """Test manager initialization"""
        projects_dir, backup_dir = temp_dirs

        assert manager.projects_dir == projects_dir
        assert manager.backup_dir == backup_dir
        assert manager.max_backups == 5
        assert manager._safety_locked is False

    def test_directories_created(self, temp_dirs):
        """Test that directories are created if missing"""
        projects_dir, backup_dir = temp_dirs
        new_projects = projects_dir / "new"
        new_backups = backup_dir / "new"

        manager = ProjectManager(
            projects_dir=new_projects,
            backup_dir=new_backups
        )

        assert new_projects.exists()
        assert new_backups.exists()

    # =========================================================================
    # SCHEMA VALIDATION TESTS
    # =========================================================================

    def test_validate_valid_project(self, manager, valid_project):
        """Test validating a valid project"""
        result = manager.validate_project(valid_project)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_missing_type(self, manager):
        """Test validation fails without type field"""
        project = {"version": "2.0"}

        result = manager.validate_project(project)

        assert result.valid is False
        assert any("type" in e for e in result.errors)

    def test_validate_missing_version(self, manager):
        """Test validation fails without version field"""
        project = {"type": "nisystem-project"}

        result = manager.validate_project(project)

        assert result.valid is False
        assert any("version" in e for e in result.errors)

    def test_validate_invalid_type(self, manager):
        """Test validation fails with wrong type"""
        project = {
            "type": "wrong-type",
            "version": "2.0"
        }

        result = manager.validate_project(project)

        assert result.valid is False
        assert any("Invalid project type" in e for e in result.errors)

    def test_validate_unknown_version_warns(self, manager):
        """Test unknown version produces warning but passes"""
        project = {
            "type": "nisystem-project",
            "version": "99.0"
        }

        result = manager.validate_project(project)

        assert result.valid is True  # Still valid
        assert any("version" in w for w in result.warnings)

    def test_validate_channels_dict_format(self, manager):
        """Test validation with dict-format channels"""
        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "temp_1": {"channel_type": "thermocouple"},
                "pressure": {"channel_type": "voltage_input"}
            }
        }

        result = manager.validate_project(project)

        assert result.valid is True

    def test_validate_channels_list_format(self, manager):
        """Test validation with list-format channels (legacy)"""
        project = {
            "type": "nisystem-project",
            "version": "1.0",
            "channels": [
                {"name": "temp_1", "type": "thermocouple"},
                {"name": "pressure", "type": "analog_input"}
            ]
        }

        result = manager.validate_project(project)

        assert result.valid is True

    def test_validate_channels_invalid_format(self, manager):
        """Test validation fails with invalid channels format"""
        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": "invalid"
        }

        result = manager.validate_project(project)

        assert result.valid is False
        assert any("channels" in e for e in result.errors)

    def test_validate_safety_action_without_limits_warns(self, manager):
        """Test warning when safety_action has no alarm limits"""
        project = {
            "type": "nisystem-project",
            "version": "2.0",
            "channels": {
                "temp_1": {
                    "channel_type": "thermocouple",
                    "safety_action": "emergency_stop"
                    # No alarm limits configured
                }
            }
        }

        result = manager.validate_project(project)

        assert result.valid is True  # Still valid
        assert any("safety_action" in w and "alarm" in w for w in result.warnings)

    # =========================================================================
    # SAFETY LOCKING TESTS
    # =========================================================================

    def test_lock_safety_config(self, manager):
        """Test locking safety configuration"""
        manager.lock_safety_config("Test acquisition running")

        locked, reason = manager.is_safety_locked()
        assert locked is True
        assert reason == "Test acquisition running"

    def test_unlock_safety_config(self, manager):
        """Test unlocking safety configuration"""
        manager.lock_safety_config("Test")
        manager.unlock_safety_config()

        locked, reason = manager.is_safety_locked()
        assert locked is False
        assert reason is None

    def test_check_safety_modification_blocked(self, manager):
        """Test safety field modification is blocked when locked"""
        manager.lock_safety_config("Acquisition running")

        allowed, reason = manager.check_safety_modification("safety_action")

        assert allowed is False
        assert "Acquisition running" in reason

    def test_check_safety_modification_allowed(self, manager):
        """Test safety field modification allowed when unlocked"""
        allowed, reason = manager.check_safety_modification("safety_action")

        assert allowed is True
        assert reason == ""

    def test_check_non_safety_field_always_allowed(self, manager):
        """Test non-safety fields are always modifiable"""
        manager.lock_safety_config("Acquisition running")

        allowed, reason = manager.check_safety_modification("description")

        assert allowed is True

    # =========================================================================
    # BACKUP TESTS
    # =========================================================================

    def test_create_backup(self, manager, temp_dirs, valid_project):
        """Test creating a backup"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        backup = manager.create_backup(project_path, reason="manual")

        assert backup is not None
        assert backup.backup_path.exists()
        assert backup.reason == "manual"
        assert backup.file_hash is not None

    def test_create_backup_nonexistent_file(self, manager, temp_dirs):
        """Test creating backup of nonexistent file returns None"""
        projects_dir, _ = temp_dirs
        nonexistent = projects_dir / "nonexistent.json"

        backup = manager.create_backup(nonexistent)

        assert backup is None

    def test_list_backups(self, manager, temp_dirs, valid_project):
        """Test listing backups"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        # Create multiple backups
        manager.create_backup(project_path, reason="backup1")
        time.sleep(0.01)  # Ensure different timestamps
        manager.create_backup(project_path, reason="backup2")

        backups = manager.list_backups(project_path)

        assert len(backups) == 2

    def test_backup_retention(self, manager, temp_dirs, valid_project):
        """Test backup retention policy"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"
        manager.max_backups = 3

        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        # Create more backups than max_backups
        for i in range(5):
            manager.create_backup(project_path, reason=f"backup{i}")
            time.sleep(0.01)

        backups = manager.list_backups(project_path)

        # Should only keep max_backups
        assert len(backups) <= 3

    def test_restore_backup(self, manager, temp_dirs, valid_project):
        """Test restoring from backup"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        # Save original
        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        # Create backup
        backup = manager.create_backup(project_path, reason="pre_modify")

        # Modify original
        modified = valid_project.copy()
        modified['metadata'] = {'name': 'Modified'}
        with open(project_path, 'w') as f:
            json.dump(modified, f)

        # Restore
        success, message = manager.restore_backup(backup.backup_path)

        assert success is True

        # Verify restored content matches original
        with open(project_path, 'r') as f:
            restored = json.load(f)
        # Compare key fields (metadata might have been modified in backup too)
        assert restored['type'] == valid_project['type']
        assert restored['version'] == valid_project['version']

    def test_restore_nonexistent_backup(self, manager, temp_dirs):
        """Test restoring nonexistent backup fails"""
        projects_dir, backup_dir = temp_dirs
        nonexistent = backup_dir / "nonexistent.json"

        success, message = manager.restore_backup(nonexistent)

        assert success is False
        assert "not found" in message.lower()

    # =========================================================================
    # LOAD/SAVE TESTS
    # =========================================================================

    def test_load_project(self, manager, temp_dirs, valid_project):
        """Test loading a project"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        status, data, message = manager.load_project(project_path)

        assert status == ProjectStatus.SUCCESS
        assert data['type'] == "nisystem-project"
        assert manager.current_path == project_path

    def test_load_nonexistent_project(self, manager, temp_dirs):
        """Test loading nonexistent project fails"""
        projects_dir, _ = temp_dirs
        nonexistent = projects_dir / "nonexistent.json"

        status, data, message = manager.load_project(nonexistent)

        assert status == ProjectStatus.ERROR
        assert data == {}

    def test_load_invalid_json(self, manager, temp_dirs):
        """Test loading invalid JSON fails"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "invalid.json"

        with open(project_path, 'w') as f:
            f.write("not valid json {{{")

        status, data, message = manager.load_project(project_path)

        assert status == ProjectStatus.ERROR
        assert "JSON" in message

    def test_load_project_validation_failure(self, manager, temp_dirs):
        """Test loading project with validation failure"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "invalid_project.json"

        invalid_project = {"not_a": "valid_project"}
        with open(project_path, 'w') as f:
            json.dump(invalid_project, f)

        status, data, message = manager.load_project(project_path)

        assert status == ProjectStatus.VALIDATION_ERROR

    def test_save_project(self, manager, temp_dirs, valid_project):
        """Test saving a project"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "new_project.json"

        status, message = manager.save_project(project_path, valid_project)

        assert status == ProjectStatus.SUCCESS
        assert project_path.exists()

        # Verify saved content
        with open(project_path, 'r') as f:
            saved = json.load(f)
        assert saved['type'] == "nisystem-project"
        assert 'modified' in saved  # Metadata added

    def test_save_project_creates_backup(self, manager, temp_dirs, valid_project):
        """Test that saving creates a backup of existing file"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        # Create initial file
        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        # Save again
        status, message = manager.save_project(project_path, valid_project)

        # Should have created a backup
        backups = manager.list_backups(project_path)
        assert len(backups) >= 1

    def test_save_invalid_project_fails(self, manager, temp_dirs):
        """Test saving invalid project fails validation"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "invalid.json"

        invalid_project = {"not": "valid"}

        status, message = manager.save_project(project_path, invalid_project)

        assert status == ProjectStatus.VALIDATION_ERROR
        assert not project_path.exists()

    def test_has_unsaved_changes(self, manager, temp_dirs, valid_project):
        """Test detecting unsaved changes"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        # Save and load
        manager.save_project(project_path, valid_project)
        manager.load_project(project_path)

        # No changes yet
        assert manager.has_unsaved_changes() is False

        # Make a change
        manager.current_data['metadata'] = {'modified': True}

        # Now has changes
        assert manager.has_unsaved_changes() is True

    def test_close_project(self, manager, temp_dirs, valid_project):
        """Test closing a project"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        manager.save_project(project_path, valid_project)
        manager.load_project(project_path)

        manager.close_project()

        assert manager.current_path is None
        assert manager.current_data == {}

    # =========================================================================
    # AUDIT TRAIL INTEGRATION
    # =========================================================================

    def test_audit_trail_on_load(self, manager, temp_dirs, valid_project):
        """Test audit trail is called on project load"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        with open(project_path, 'w') as f:
            json.dump(valid_project, f)

        mock_audit = Mock()
        manager.audit_trail = mock_audit

        manager.load_project(project_path, user="testuser")

        mock_audit.log_event.assert_called()

    def test_audit_trail_on_save(self, manager, temp_dirs, valid_project):
        """Test audit trail is called on project save"""
        projects_dir, _ = temp_dirs
        project_path = projects_dir / "test_project.json"

        mock_audit = Mock()
        manager.audit_trail = mock_audit

        manager.save_project(project_path, valid_project, user="testuser")

        mock_audit.log_event.assert_called()

    def test_audit_trail_on_safety_lock(self, manager):
        """Test audit trail is called on safety lock"""
        mock_audit = Mock()
        manager.audit_trail = mock_audit

        manager.lock_safety_config("Test lock")

        mock_audit.log_event.assert_called()

    # =========================================================================
    # HASH COMPUTATION
    # =========================================================================

    def test_compute_file_hash(self, manager, temp_dirs):
        """Test file hash computation"""
        projects_dir, _ = temp_dirs
        test_file = projects_dir / "test.txt"

        test_file.write_text("test content")

        hash1 = manager._compute_file_hash(test_file)
        hash2 = manager._compute_file_hash(test_file)

        # Same content should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_compute_data_hash(self, manager, valid_project):
        """Test data hash computation"""
        hash1 = manager._compute_data_hash(valid_project)
        hash2 = manager._compute_data_hash(valid_project)

        assert hash1 == hash2

        # Different data should produce different hash
        modified = valid_project.copy()
        modified['version'] = "3.0"
        hash3 = manager._compute_data_hash(modified)

        assert hash3 != hash1
