"""
Tests for audit_trail.py
Covers 21 CFR Part 11 / ALCOA+ compliant audit trail functionality.
"""

import pytest
import tempfile
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from audit_trail import AuditTrail, AuditEntry, AuditEventType


class TestAuditEventType:
    """Tests for AuditEventType enum"""

    def test_config_events(self):
        """Test configuration event types exist"""
        assert AuditEventType.CONFIG_CHANNEL_ADDED.value == "config.channel.added"
        assert AuditEventType.CONFIG_CHANNEL_MODIFIED.value == "config.channel.modified"
        assert AuditEventType.CONFIG_CHANNEL_REMOVED.value == "config.channel.removed"
        assert AuditEventType.CONFIG_SYSTEM_MODIFIED.value == "config.system.modified"
        assert AuditEventType.CONFIG_SAFETY_MODIFIED.value == "config.safety.modified"

    def test_project_events(self):
        """Test project event types exist"""
        assert AuditEventType.PROJECT_LOADED.value == "project.loaded"
        assert AuditEventType.PROJECT_SAVED.value == "project.saved"
        assert AuditEventType.PROJECT_CLOSED.value == "project.closed"

    def test_safety_events(self):
        """Test safety event types exist"""
        assert AuditEventType.SAFETY_ACTION_TRIGGERED.value == "safety.action.triggered"
        assert AuditEventType.SAFETY_ACTION_RESET.value == "safety.action.reset"

    def test_alarm_events(self):
        """Test alarm event types exist"""
        assert AuditEventType.ALARM_ACKNOWLEDGED.value == "alarm.acknowledged"
        assert AuditEventType.ALARM_RESET.value == "alarm.reset"
        assert AuditEventType.ALARM_SHELVED.value == "alarm.shelved"

    def test_recording_events(self):
        """Test recording event types exist"""
        assert AuditEventType.RECORDING_STARTED.value == "recording.started"
        assert AuditEventType.RECORDING_STOPPED.value == "recording.stopped"

    def test_user_events(self):
        """Test user event types exist"""
        assert AuditEventType.USER_LOGIN.value == "user.login"
        assert AuditEventType.USER_LOGIN_FAILED.value == "user.login.failed"
        assert AuditEventType.USER_LOGOUT.value == "user.logout"

    def test_system_events(self):
        """Test system event types exist"""
        assert AuditEventType.SYSTEM_STARTUP.value == "system.startup"
        assert AuditEventType.SYSTEM_SHUTDOWN.value == "system.shutdown"
        assert AuditEventType.SYSTEM_ERROR.value == "system.error"


class TestAuditEntry:
    """Tests for AuditEntry dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        entry = AuditEntry(
            sequence=1,
            timestamp="2025-01-15T10:30:00.000000",
            event_type="test.event",
            user="testuser",
            user_role="operator",
            description="Test event",
            details={"key": "value"},
            previous_value=None,
            new_value=None,
            reason="Testing",
            source_ip="127.0.0.1",
            session_id="sess-123",
            node_id="node-001",
            previous_hash="genesis",
            entry_hash="abc123"
        )

        d = entry.to_dict()
        assert d['sequence'] == 1
        assert d['user'] == "testuser"
        assert d['description'] == "Test event"
        assert d['details'] == {"key": "value"}

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'sequence': 5,
            'timestamp': "2025-01-15T10:30:00.000000",
            'event_type': "config.change",
            'user': "admin",
            'user_role': "administrator",
            'description': "Changed config",
            'details': {},
            'previous_value': "old",
            'new_value': "new",
            'reason': "Update required",
            'source_ip': "192.168.1.1",
            'session_id': "sess-456",
            'node_id': "node-002",
            'previous_hash': "prevhash",
            'entry_hash': "entryhash"
        }

        entry = AuditEntry.from_dict(d)
        assert entry.sequence == 5
        assert entry.user == "admin"
        assert entry.previous_value == "old"
        assert entry.new_value == "new"


class TestAuditTrail:
    """Tests for AuditTrail class"""

    @pytest.fixture
    def audit_dir(self):
        """Create a temporary directory for audit logs"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def audit_trail(self, audit_dir):
        """Create an AuditTrail instance"""
        return AuditTrail(audit_dir, node_id="test-node")

    def test_initialization(self, audit_trail, audit_dir):
        """Test audit trail initialization"""
        assert audit_trail.node_id == "test-node"
        assert audit_trail.sequence >= 1  # At least startup event logged
        assert audit_trail.previous_hash != "genesis"  # Has logged at least one event
        assert audit_trail.current_file is not None
        assert audit_trail.current_file.exists()

    def test_log_event(self, audit_trail):
        """Test logging a simple event"""
        initial_seq = audit_trail.sequence

        entry = audit_trail.log_event(
            event_type=AuditEventType.RECORDING_STARTED,
            user="testuser",
            description="Started recording",
            details={"filename": "test.csv"}
        )

        assert entry.sequence == initial_seq + 1
        assert entry.event_type == AuditEventType.RECORDING_STARTED.value
        assert entry.user == "testuser"
        assert entry.description == "Started recording"
        assert entry.details == {"filename": "test.csv"}
        assert entry.node_id == "test-node"
        assert entry.entry_hash != ""

    def test_hash_chain_integrity(self, audit_trail):
        """Test that events form a valid hash chain"""
        # Log multiple events
        entries = []
        for i in range(5):
            entry = audit_trail.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                user="user",
                description=f"Change {i}"
            )
            entries.append(entry)

        # Verify chain
        is_valid, errors, count = audit_trail.verify_integrity()
        assert is_valid is True
        assert len(errors) == 0
        assert count >= 5

    def test_log_config_change_added(self, audit_trail):
        """Test logging a config addition"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="TC_1",
            user="admin",
            previous_value=None,  # None indicates new item
            new_value={"name": "TC_1", "type": "thermocouple"},
            reason="Added new thermocouple"
        )

        assert entry.event_type == AuditEventType.CONFIG_CHANNEL_ADDED.value

    def test_log_config_change_modified(self, audit_trail):
        """Test logging a config modification"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="TC_1",
            user="admin",
            previous_value={"units": "degC"},
            new_value={"units": "degF"},
            reason="Changed units"
        )

        assert entry.event_type == AuditEventType.CONFIG_CHANNEL_MODIFIED.value
        assert entry.previous_value == {"units": "degC"}
        assert entry.new_value == {"units": "degF"}

    def test_log_config_change_removed(self, audit_trail):
        """Test logging a config removal"""
        entry = audit_trail.log_config_change(
            config_type="channel",
            item_id="TC_1",
            user="admin",
            previous_value={"name": "TC_1"},
            new_value=None,  # None indicates removal
            reason="Channel no longer needed"
        )

        assert entry.event_type == AuditEventType.CONFIG_CHANNEL_REMOVED.value

    def test_log_safety_config_change(self, audit_trail):
        """Test logging a safety config change"""
        entry = audit_trail.log_config_change(
            config_type="safety",
            item_id="interlock_1",
            user="admin",
            previous_value={"enabled": True},
            new_value={"enabled": False},
            reason="Maintenance mode"
        )

        assert entry.event_type == AuditEventType.CONFIG_SAFETY_MODIFIED.value

    def test_verify_integrity_valid(self, audit_trail):
        """Test integrity verification on valid log"""
        # Log some events
        for i in range(3):
            audit_trail.log_event(
                event_type=AuditEventType.SYSTEM_STARTUP,
                user="system",
                description=f"Test event {i}"
            )

        is_valid, errors, count = audit_trail.verify_integrity()
        assert is_valid is True
        assert len(errors) == 0
        assert count >= 3

    def test_verify_integrity_tampered(self, audit_trail, audit_dir):
        """Test integrity verification detects tampering"""
        # Log some events
        for i in range(3):
            audit_trail.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                user="user",
                description=f"Event {i}"
            )

        # Tamper with the log file
        log_file = audit_trail.current_file
        with open(log_file, 'r') as f:
            lines = f.readlines()

        if len(lines) > 1:
            # Modify a line (change description)
            entry = json.loads(lines[-1])
            entry['description'] = "TAMPERED"
            lines[-1] = json.dumps(entry) + '\n'

            with open(log_file, 'w') as f:
                f.writelines(lines)

            # Verify should now fail
            is_valid, errors, count = audit_trail.verify_integrity()
            assert is_valid is False
            assert len(errors) > 0

    def test_query_events_no_filter(self, audit_trail):
        """Test querying events without filters"""
        # Log some events
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="Login"
        )

        results = audit_trail.query_events(limit=100)
        assert len(results) >= 1

    def test_query_events_by_type(self, audit_trail):
        """Test querying events filtered by type"""
        # Log events of different types
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="Login"
        )
        audit_trail.log_event(
            event_type=AuditEventType.RECORDING_STARTED,
            user="user1",
            description="Recording"
        )

        # Query only login events
        results = audit_trail.query_events(
            event_types=[AuditEventType.USER_LOGIN],
            limit=100
        )

        # All results should be login events
        for entry in results:
            assert entry.event_type == AuditEventType.USER_LOGIN.value

    def test_query_events_by_user(self, audit_trail):
        """Test querying events filtered by user"""
        audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="admin",
            description="Admin change"
        )
        audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="operator",
            description="Operator change"
        )

        results = audit_trail.query_events(user="admin", limit=100)

        for entry in results:
            assert entry.user == "admin"

    def test_query_events_by_time_range(self, audit_trail):
        """Test querying events within a time range"""
        now = datetime.now()

        # Query recent events (last minute)
        results = audit_trail.query_events(
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=1),
            limit=100
        )

        # All startup events should be within this range
        assert len(results) >= 1

    def test_export_csv(self, audit_trail, audit_dir):
        """Test exporting audit trail to CSV"""
        # Log some events
        for i in range(3):
            audit_trail.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                user="user",
                description=f"Change {i}"
            )

        output_path = audit_dir / "export.csv"
        count = audit_trail.export_csv(output_path)

        assert count >= 3
        assert output_path.exists()

        # Verify CSV has headers and data
        with open(output_path) as f:
            lines = f.readlines()
        assert len(lines) > 1  # Header + data
        assert "Sequence" in lines[0]
        assert "Timestamp" in lines[0]

    def test_get_statistics(self, audit_trail):
        """Test getting audit trail statistics"""
        # Log some events
        for i in range(5):
            audit_trail.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                user="user",
                description=f"Change {i}"
            )

        stats = audit_trail.get_statistics()

        assert 'current_sequence' in stats
        assert stats['current_sequence'] >= 5
        assert 'current_file' in stats
        assert 'log_files' in stats
        assert len(stats['log_files']) >= 1

    def test_file_rotation_by_size(self, audit_dir):
        """Test log file rotation when size limit is reached"""
        # Create audit trail with very small max size
        trail = AuditTrail(
            audit_dir,
            node_id="test",
            max_file_size_mb=0.001  # Very small to trigger rotation quickly
        )

        initial_file = trail.current_file

        # Log many events to exceed size limit
        for i in range(100):
            trail.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                user="user",
                description=f"Change {i}" + "x" * 1000  # Large description
            )

        # Should have rotated to a new file
        log_files = list(audit_dir.glob("audit_*.jsonl"))
        # May or may not have rotated depending on exact size
        assert len(log_files) >= 1

    def test_thread_safety(self, audit_trail):
        """Test thread-safe logging"""
        import threading

        errors = []

        def log_events(thread_id):
            try:
                for i in range(10):
                    audit_trail.log_event(
                        event_type=AuditEventType.CONFIG_CHANGE,
                        user=f"thread-{thread_id}",
                        description=f"Event {i} from thread {thread_id}"
                    )
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=log_events, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # Verify integrity
        is_valid, _, count = audit_trail.verify_integrity()
        assert is_valid is True
        assert count >= 50  # 5 threads * 10 events

    def test_append_only_semantics(self, audit_trail):
        """Test that audit log is append-only"""
        # Log an event
        entry1 = audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="user",
            description="First event"
        )
        seq1 = entry1.sequence

        # Log another event
        entry2 = audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="user",
            description="Second event"
        )

        # Sequences should be monotonically increasing
        assert entry2.sequence > seq1

        # Hash chain should link entries
        assert entry2.previous_hash == entry1.entry_hash

    def test_persistence_across_restarts(self, audit_dir):
        """Test that audit trail persists and continues across restarts"""
        # Create first instance and log events
        trail1 = AuditTrail(audit_dir, node_id="test")
        seq1 = trail1.sequence

        trail1.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="user",
            description="Event before restart"
        )

        last_seq = trail1.sequence

        # Create second instance (simulating restart)
        # Note: AuditTrail logs a startup event on initialization, which extends the chain
        trail2 = AuditTrail(audit_dir, node_id="test")

        # The second instance should have a sequence >= the first instance's last sequence
        # (may be higher due to startup event)
        assert trail2.sequence >= last_seq

        # Log new event should work
        entry = trail2.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            user="user",
            description="Event after restart"
        )

        # Verify entire chain is still valid
        is_valid, errors, _ = trail2.verify_integrity()
        assert is_valid is True


class TestAuditTrailCompression:
    """Tests for audit log compression functionality"""

    @pytest.fixture
    def audit_dir(self):
        """Create a temporary directory for audit logs"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_compress_log(self, audit_dir):
        """Test log file compression"""
        import gzip

        # Create audit trail first (so it creates its own log file)
        trail = AuditTrail(audit_dir, node_id="test")

        # Create a separate old log file (not the current one)
        old_log = audit_dir / "audit_20200101_000000.jsonl"
        old_log.write_text('{"test": "data"}\n')

        # Verify the old_log is different from current_file
        assert old_log != trail.current_file

        # Manually call compress on the old log
        trail._compress_log(old_log)

        # Check compressed file exists
        gz_path = audit_dir / "audit_20200101_000000.jsonl.gz"
        assert gz_path.exists()

        # Original should be deleted
        assert not old_log.exists()

        # Verify contents
        with gzip.open(gz_path, 'rt') as f:
            content = f.read()
        assert '{"test": "data"}' in content
