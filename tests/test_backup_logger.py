"""
Unit tests for Backup Logger

Tests the human-readable backup logging and changelog generation.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

import sys
services_dir = Path(__file__).parent.parent / "services" / "daq_service"
sys.path.insert(0, str(services_dir))

from backup_logger import BackupLogger, ProjectDiffer, ChangeEntry

class TestProjectDiffer:
    """Test the project diffing functionality"""

    def test_diff_empty_to_new(self):
        """Test diffing from empty to new project"""
        differ = ProjectDiffer()
        old_data = {}
        new_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2,
                     'props': {'title': 'Temperature'}}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        assert len(changes) >= 1

    def test_diff_added_widget(self):
        """Test detecting added widget"""
        differ = ProjectDiffer()
        old_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2}
                ]
            }
        }
        new_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2},
                    {'i': 'w2', 'type': 'GaugeWidget', 'x': 4, 'y': 0, 'w': 2, 'h': 2,
                     'props': {'channel': 'pressure'}}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        added = [c for c in changes if c.action == 'ADDED' and c.category == 'Widgets']
        assert len(added) == 1
        assert added[0].item_type == 'GaugeWidget'

    def test_diff_removed_widget(self):
        """Test detecting removed widget"""
        differ = ProjectDiffer()
        old_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2},
                    {'i': 'w2', 'type': 'GaugeWidget', 'x': 4, 'y': 0, 'w': 2, 'h': 2}
                ]
            }
        }
        new_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        removed = [c for c in changes if c.action == 'REMOVED' and c.category == 'Widgets']
        assert len(removed) == 1

    def test_diff_moved_widget(self):
        """Test detecting moved widget"""
        differ = ProjectDiffer()
        old_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2}
                ]
            }
        }
        new_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 4, 'y': 2, 'w': 4, 'h': 2}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        moved = [c for c in changes if c.action == 'MOVED']
        assert len(moved) == 1
        assert '0,0' in moved[0].details and '4,2' in moved[0].details

    def test_diff_added_channel(self):
        """Test detecting added channel"""
        differ = ProjectDiffer()
        old_data = {
            'channels': {
                'temp1': {'channel_type': 'thermocouple', 'units': 'C'}
            }
        }
        new_data = {
            'channels': {
                'temp1': {'channel_type': 'thermocouple', 'units': 'C'},
                'pressure': {'channel_type': 'analog_input', 'units': 'PSI'}
            }
        }

        changes = differ.diff(old_data, new_data)
        added = [c for c in changes if c.action == 'ADDED' and c.category == 'Channels']
        assert len(added) == 1
        assert added[0].item_name == 'pressure'

    def test_diff_modified_channel(self):
        """Test detecting modified channel"""
        differ = ProjectDiffer()
        old_data = {
            'channels': {
                'temp1': {'channel_type': 'thermocouple', 'units': 'C', 'scale': 1.0}
            }
        }
        new_data = {
            'channels': {
                'temp1': {'channel_type': 'thermocouple', 'units': 'F', 'scale': 1.8}
            }
        }

        changes = differ.diff(old_data, new_data)
        modified = [c for c in changes if c.action == 'MODIFIED' and c.category == 'Channels']
        assert len(modified) == 1
        assert 'units' in modified[0].details or 'scale' in modified[0].details

    def test_diff_added_script(self):
        """Test detecting added Python script"""
        differ = ProjectDiffer()
        old_data = {
            'scripts': {
                'pythonScripts': []
            }
        }
        new_data = {
            'scripts': {
                'pythonScripts': [
                    {'id': 'script1', 'name': 'My Script', 'code': 'print("hello")'}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        added = [c for c in changes if c.action == 'ADDED' and 'Script' in c.category]
        assert len(added) == 1
        assert added[0].item_name == 'My Script'

    def test_diff_added_interlock(self):
        """Test detecting added safety interlock"""
        differ = ProjectDiffer()
        old_data = {
            'safety': {'interlocks': []}
        }
        new_data = {
            'safety': {
                'interlocks': [
                    {'id': 'int1', 'name': 'High Pressure Trip',
                     'condition': 'pressure > 100', 'action': 'close_valve'}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        added = [c for c in changes if c.action == 'ADDED' and c.category == 'Safety']
        assert len(added) == 1
        assert 'High Pressure Trip' in added[0].item_name

    def test_diff_multipage_layout(self):
        """Test diffing multi-page layouts"""
        differ = ProjectDiffer()
        old_data = {
            'layout': {
                'pages': [
                    {'id': 'page1', 'name': 'Main', 'widgets': []}
                ]
            }
        }
        new_data = {
            'layout': {
                'pages': [
                    {'id': 'page1', 'name': 'Main', 'widgets': []},
                    {'id': 'page2', 'name': 'Alarms', 'widgets': [
                        {'i': 'w1', 'type': 'AlarmSummaryWidget', 'x': 0, 'y': 0, 'w': 6, 'h': 4}
                    ]}
                ]
            }
        }

        changes = differ.diff(old_data, new_data)
        added_pages = [c for c in changes if c.action == 'ADDED' and c.category == 'Pages']
        assert len(added_pages) == 1
        assert 'Alarms' in added_pages[0].item_name

class TestBackupLogger:
    """Test the backup logging functionality"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_creates_log_file(self, temp_dir):
        """Test that backup logger creates log file"""
        logger = BackupLogger(temp_dir)
        assert (temp_dir / "backup.log").parent.exists()

    def test_log_initial_backup(self, temp_dir):
        """Test logging an initial backup (no previous data)"""
        logger = BackupLogger(temp_dir)

        # Create a test project file
        project_path = temp_dir / "test_project.json"
        backup_path = temp_dir / "test_project_20260126_120000.json"

        project_data = {
            'type': 'nisystem-project',
            'version': '2.0',
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2}
                ]
            },
            'channels': {
                'temp1': {'channel_type': 'thermocouple'}
            }
        }

        # Write test files
        with open(project_path, 'w') as f:
            json.dump(project_data, f)
        with open(backup_path, 'w') as f:
            json.dump(project_data, f)

        changelog = logger.log_backup(
            project_name="Test Project",
            project_path=project_path,
            backup_path=backup_path,
            new_data=project_data,
            old_data=None,
            user="admin",
            reason="pre_save",
            new_hash="abc123",
            backup_count=1,
            max_backups=10
        )

        # Check log file was created
        log_file = temp_dir / "backup.log"
        assert log_file.exists()

        # Check log content
        content = log_file.read_text()
        assert "Test Project" in content
        assert "admin" in content
        assert "pre_save" in content

    def test_log_backup_with_changes(self, temp_dir):
        """Test logging a backup with detected changes"""
        logger = BackupLogger(temp_dir)

        project_path = temp_dir / "test_project.json"
        backup_path = temp_dir / "test_project_20260126_120000.json"

        old_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2}
                ]
            }
        }

        new_data = {
            'layout': {
                'widgets': [
                    {'i': 'w1', 'type': 'TrendChart', 'x': 0, 'y': 0, 'w': 4, 'h': 2},
                    {'i': 'w2', 'type': 'GaugeWidget', 'x': 4, 'y': 0, 'w': 2, 'h': 2,
                     'props': {'channel': 'pressure'}}
                ]
            }
        }

        with open(backup_path, 'w') as f:
            json.dump(new_data, f)

        changelog = logger.log_backup(
            project_name="Test Project",
            project_path=project_path,
            backup_path=backup_path,
            new_data=new_data,
            old_data=old_data,
            user="operator",
            reason="pre_save",
            new_hash="def456",
            old_hash="abc123",
            backup_count=2,
            max_backups=10
        )

        assert changelog.has_changes()

        # Check log file contains change details
        log_file = temp_dir / "backup.log"
        content = log_file.read_text()
        assert "ADDED" in content
        assert "GaugeWidget" in content

    def test_log_restore(self, temp_dir):
        """Test logging a restore operation"""
        logger = BackupLogger(temp_dir)

        logger.log_restore(
            project_name="Test Project",
            backup_timestamp=datetime(2026, 1, 8, 13, 38, 59),
            user="admin",
            reason="Rolling back config change"
        )

        log_file = temp_dir / "backup.log"
        content = log_file.read_text()
        assert "RESTORE" in content
        assert "admin" in content
        assert "Rolling back config change" in content

    def test_log_cleanup(self, temp_dir):
        """Test logging a cleanup operation"""
        logger = BackupLogger(temp_dir)

        logger.log_cleanup(
            project_name="Test Project",
            removed_count=2,
            remaining_count=8,
            max_backups=10
        )

        log_file = temp_dir / "backup.log"
        content = log_file.read_text()
        assert "CLEANUP" in content
        assert "2" in content  # removed count
        assert "8 of 10" in content

    def test_log_failure(self, temp_dir):
        """Test logging a failed operation"""
        logger = BackupLogger(temp_dir)

        logger.log_failure(
            project_name="Test Project",
            operation="BACKUP",
            user="operator",
            error="Disk full"
        )

        log_file = temp_dir / "backup.log"
        content = log_file.read_text()
        assert "FAILED" in content
        assert "Disk full" in content

class TestChangeLogFormatting:
    """Test changelog output formatting"""

    def test_size_delta_positive(self):
        """Test positive size delta formatting"""
        from backup_logger import ChangeLog

        changelog = ChangeLog(
            timestamp=datetime.now(),
            project_name="Test",
            user="admin",
            reason="pre_save",
            old_size=1024,
            new_size=2048,
            old_hash="abc",
            new_hash="def"
        )

        assert "+1.0 KB" in changelog.size_delta_str

    def test_size_delta_negative(self):
        """Test negative size delta formatting"""
        from backup_logger import ChangeLog

        changelog = ChangeLog(
            timestamp=datetime.now(),
            project_name="Test",
            user="admin",
            reason="pre_save",
            old_size=2048,
            new_size=1024,
            old_hash="abc",
            new_hash="def"
        )

        assert "-1.0 KB" in changelog.size_delta_str

    def test_size_delta_zero(self):
        """Test zero size delta formatting"""
        from backup_logger import ChangeLog

        changelog = ChangeLog(
            timestamp=datetime.now(),
            project_name="Test",
            user="admin",
            reason="pre_save",
            old_size=1024,
            new_size=1024,
            old_hash="abc",
            new_hash="def"
        )

        assert "0 bytes" in changelog.size_delta_str

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
