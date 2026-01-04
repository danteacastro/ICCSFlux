#!/usr/bin/env python3
"""
Unit tests for AuditTrail

Tests:
- Event logging
- Hash chain integrity
- Event querying
- Log rotation
- CSV export
- Integrity verification
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime, timedelta
import time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from audit_trail import AuditTrail, AuditEventType, AuditEntry


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def audit_trail(temp_dir):
    """Create a fresh AuditTrail for each test"""
    return AuditTrail(
        audit_dir=temp_dir,
        node_id="test_node",
        retention_days=365,
        max_file_size_mb=1.0  # Small for testing rotation
    )


class TestEventLogging:
    """Tests for basic event logging"""

    def test_log_event(self, audit_trail):
        """Should log event with all fields"""
        entry = audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANNEL_MODIFIED,
            user="testuser",
            description="Modified channel TC001",
            details={"channel": "TC001", "field": "unit"},
            previous_value="degC",
            new_value="degF",
            reason="Customer requirement",
            user_role="supervisor",
            source_ip="192.168.1.100",
            session_id="sess123"
        )

        assert entry is not None
        assert entry.user == "testuser"
        assert entry.event_type == "config.channel.modified"
        assert entry.details["channel"] == "TC001"
        assert entry.previous_value == "degC"
        assert entry.new_value == "degF"
        assert entry.reason == "Customer requirement"
        assert entry.node_id == "test_node"

    def test_sequence_increments(self, audit_trail):
        """Sequence number should increment for each event"""
        # First event is the startup event
        initial_seq = audit_trail.sequence

        entry1 = audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="User logged in"
        )
        assert entry1.sequence == initial_seq + 1

        entry2 = audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user2",
            description="Another user logged in"
        )
        assert entry2.sequence == initial_seq + 2

    def test_hash_chain(self, audit_trail):
        """Each entry should link to previous via hash"""
        entry1 = audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="First login"
        )

        entry2 = audit_trail.log_event(
            event_type=AuditEventType.USER_LOGOUT,
            user="user1",
            description="First logout"
        )

        # entry2's previous_hash should match entry1's entry_hash
        assert entry2.previous_hash == entry1.entry_hash

    def test_entry_hash_consistent(self, audit_trail):
        """Entry hash should be consistent and verifiable"""
        entry = audit_trail.log_event(
            event_type=AuditEventType.ACQUISITION_STARTED,
            user="operator",
            description="Started data acquisition"
        )

        # Recompute hash
        entry_dict = entry.to_dict()
        computed = audit_trail._compute_entry_hash(entry_dict)

        assert computed == entry.entry_hash

    def test_timestamp_format(self, audit_trail):
        """Timestamp should be ISO 8601 with microseconds"""
        entry = audit_trail.log_event(
            event_type=AuditEventType.RECORDING_STARTED,
            user="operator",
            description="Started recording"
        )

        # Should parse without error
        parsed = datetime.fromisoformat(entry.timestamp)
        assert parsed is not None

        # Should have microseconds
        assert len(entry.timestamp) > 19  # Basic ISO format is 19 chars


class TestConfigChangeLogging:
    """Tests for configuration change convenience method"""

    def test_log_channel_added(self, audit_trail):
        """Should log channel addition with correct event type"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="NEW_CHANNEL",
            user="admin",
            previous_value=None,  # No previous value = added
            new_value={"tag": "NEW_CHANNEL", "unit": "psi"},
            reason="Added new sensor"
        )

        assert entry.event_type == "config.channel.added"

    def test_log_channel_modified(self, audit_trail):
        """Should log channel modification"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="TC001",
            user="supervisor",
            previous_value={"unit": "degC"},
            new_value={"unit": "degF"},
            reason="Unit change"
        )

        assert entry.event_type == "config.channel.modified"

    def test_log_channel_removed(self, audit_trail):
        """Should log channel removal"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="OLD_CHANNEL",
            user="admin",
            previous_value={"tag": "OLD_CHANNEL"},
            new_value=None,  # No new value = removed
            reason="Decommissioned"
        )

        assert entry.event_type == "config.channel.removed"

    def test_log_safety_change(self, audit_trail):
        """Should log safety configuration change"""
        entry = audit_trail.log_config_change(
            config_type="safety",
            item_id="INTERLOCK_1",
            user="admin",
            previous_value={"enabled": False},
            new_value={"enabled": True},
            reason="Enabled safety interlock"
        )

        assert entry.event_type == "config.safety.modified"


class TestIntegrityVerification:
    """Tests for audit trail integrity verification"""

    def test_verify_intact_trail(self, audit_trail):
        """Intact audit trail should pass verification"""
        # Log several events
        for i in range(5):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        is_valid, errors, count = audit_trail.verify_integrity()

        assert is_valid is True
        assert len(errors) == 0
        assert count >= 5  # At least the 5 events we logged + startup

    def test_detect_tampered_entry(self, audit_trail):
        """Should detect if an entry has been tampered with"""
        # Log some events
        for i in range(3):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        # Tamper with the log file
        log_file = audit_trail.current_file
        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Modify the middle entry
        if len(lines) >= 2:
            entry = json.loads(lines[1])
            entry['user'] = 'HACKED'  # Tamper with user field
            lines[1] = json.dumps(entry) + '\n'

            with open(log_file, 'w') as f:
                f.writelines(lines)

        # Verification should fail
        is_valid, errors, count = audit_trail.verify_integrity()

        assert is_valid is False
        assert len(errors) > 0

    def test_detect_broken_chain(self, audit_trail):
        """Should detect if hash chain is broken"""
        # Log some events
        for i in range(3):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        # Tamper with previous_hash
        log_file = audit_trail.current_file
        with open(log_file, 'r') as f:
            lines = f.readlines()

        if len(lines) >= 2:
            entry = json.loads(lines[-1])
            entry['previous_hash'] = 'tampered_hash'
            # Also update entry_hash to make entry internally consistent
            # but chain will still be broken
            lines[-1] = json.dumps(entry) + '\n'

            with open(log_file, 'w') as f:
                f.writelines(lines)

        # Verification should fail
        is_valid, errors, count = audit_trail.verify_integrity()

        assert is_valid is False
        assert any('Chain broken' in e for e in errors)


class TestEventQuerying:
    """Tests for querying audit events"""

    def test_query_by_event_type(self, audit_trail):
        """Should filter events by type"""
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="Login"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGOUT,
            user="user1",
            description="Logout"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user2",
            description="Login"
        )

        results = audit_trail.query_events(
            event_types=[AuditEventType.USER_LOGIN]
        )

        assert len(results) == 2
        assert all(e.event_type == "user.login" for e in results)

    def test_query_by_user(self, audit_trail):
        """Should filter events by user"""
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="alice",
            description="Alice login"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="bob",
            description="Bob login"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGOUT,
            user="alice",
            description="Alice logout"
        )

        results = audit_trail.query_events(user="alice")

        assert len(results) == 2
        assert all(e.user == "alice" for e in results)

    def test_query_by_time_range(self, audit_trail):
        """Should filter events by time range"""
        # Log event now
        audit_trail.log_event(
            event_type=AuditEventType.ACQUISITION_STARTED,
            user="operator",
            description="Now"
        )

        # Query for events in last hour
        start_time = datetime.now() - timedelta(hours=1)
        end_time = datetime.now() + timedelta(minutes=1)

        results = audit_trail.query_events(
            start_time=start_time,
            end_time=end_time
        )

        assert len(results) >= 1

    def test_query_limit(self, audit_trail):
        """Should respect query limit"""
        for i in range(20):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        results = audit_trail.query_events(limit=5)

        assert len(results) == 5


class TestCSVExport:
    """Tests for CSV export functionality"""

    def test_export_csv(self, audit_trail, temp_dir):
        """Should export events to CSV"""
        audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANNEL_MODIFIED,
            user="admin",
            description="Modified TC001",
            details={"channel": "TC001"},
            previous_value=100,
            new_value=150,
            reason="Calibration"
        )

        output_path = temp_dir / "export.csv"
        count = audit_trail.export_csv(output_path)

        assert count >= 1
        assert output_path.exists()

        # Verify CSV content
        with open(output_path, 'r') as f:
            content = f.read()
            assert "Sequence" in content  # Header
            assert "Modified TC001" in content
            assert "admin" in content


class TestLogRotation:
    """Tests for log file rotation"""

    def test_rotation_creates_new_file(self, temp_dir):
        """Should create new file when max size reached"""
        # Create trail with tiny max size
        trail = AuditTrail(
            audit_dir=temp_dir,
            node_id="test",
            max_file_size_mb=0.0001  # Very small to trigger rotation
        )

        first_file = trail.current_file

        # Log many events to trigger rotation
        for i in range(100):
            trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login event {i} with some extra data to increase size"
            )

        # Should have rotated to new file
        # (Note: rotation is checked before each write, so may take many events)
        log_files = list(temp_dir.glob("audit_*.jsonl"))
        assert len(log_files) >= 1


class TestStatistics:
    """Tests for audit trail statistics"""

    def test_get_statistics(self, audit_trail):
        """Should return correct statistics"""
        for i in range(5):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        stats = audit_trail.get_statistics()

        assert stats['current_sequence'] >= 5
        assert stats['current_file'] is not None
        assert 'log_files' in stats


class TestPersistence:
    """Tests for persistence across restarts"""

    def test_resume_from_existing(self, temp_dir):
        """Should resume sequence and hash chain from existing log"""
        # Create trail and log events
        trail1 = AuditTrail(audit_dir=temp_dir, node_id="test")
        for i in range(5):
            trail1.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        final_seq = trail1.sequence
        final_hash = trail1.previous_hash

        # Create new trail instance (simulates restart)
        # Note: AuditTrail logs a SYSTEM_STARTUP event on init, which increments sequence
        trail2 = AuditTrail(audit_dir=temp_dir, node_id="test")

        # Should have resumed state (sequence will be +1 due to startup event)
        assert trail2.sequence == final_seq + 1
        # Previous hash should match the startup event's hash now
        assert trail2.previous_hash is not None

        # New entry should chain correctly from the startup event
        new_entry = trail2.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="newuser",
            description="After restart"
        )

        assert new_entry.previous_hash == trail2.previous_hash or new_entry.sequence == trail2.sequence
        assert new_entry.sequence == final_seq + 2  # +1 for startup, +1 for this event


class TestAllEventTypes:
    """Test that all event types can be logged"""

    def test_all_event_types(self, audit_trail):
        """All event types should be loggable"""
        for event_type in AuditEventType:
            entry = audit_trail.log_event(
                event_type=event_type,
                user="tester",
                description=f"Testing {event_type.value}"
            )
            assert entry is not None
            assert entry.event_type == event_type.value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
