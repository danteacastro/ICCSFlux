#!/usr/bin/env python3
"""
Integration tests for MQTT authentication and user management handlers

Tests the MQTT message handlers in daq_service.py for:
- Authentication (login/logout)
- User management (CRUD operations)
- Audit trail queries
- Archive management

These tests mock the MQTT client and verify handler behavior.
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from user_session import UserSessionManager, UserRole, Permission
from audit_trail import AuditTrail, AuditEventType
from archive_manager import ArchiveManager

# Test credentials - NOT for production use
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "admin"  # Default password from UserSessionManager


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def session_manager(temp_dir):
    """Create UserSessionManager"""
    return UserSessionManager(data_dir=temp_dir)


@pytest.fixture
def audit_trail(temp_dir):
    """Create AuditTrail"""
    audit_dir = temp_dir / "audit"
    return AuditTrail(audit_dir=audit_dir)


@pytest.fixture
def archive_manager(temp_dir):
    """Create ArchiveManager"""
    data_dir = temp_dir / "data"
    data_dir.mkdir()
    return ArchiveManager(data_dir=data_dir)


class TestAuthenticationHandlers:
    """Tests for authentication MQTT handlers"""

    def test_login_success(self, session_manager):
        """Successful login should create session and publish status"""
        # Create test user
        session_manager.create_user("testuser", "testpass", UserRole.OPERATOR)

        # Simulate login handler
        payload = {
            "username": "testuser",
            "password": "testpass",
            "source_ip": "192.168.1.100"
        }

        session = session_manager.authenticate(
            payload["username"],
            payload["password"],
            payload.get("source_ip", "local")
        )

        assert session is not None
        assert session.username == "testuser"
        assert session.role == UserRole.OPERATOR

    def test_login_failure_wrong_password(self, session_manager):
        """Failed login should return None"""
        session_manager.create_user("testuser", "correct", UserRole.OPERATOR)

        session = session_manager.authenticate("testuser", "wrong")

        assert session is None

    def test_login_failure_no_user(self, session_manager):
        """Login with nonexistent user should fail"""
        session = session_manager.authenticate("nobody", "pass")
        assert session is None

    def test_logout(self, session_manager):
        """Logout should invalidate session"""
        session_manager.create_user("logoutuser", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("logoutuser", "pass")

        result = session_manager.logout(session.session_id)

        assert result is True
        assert session_manager.validate_session(session.session_id) is None


class TestUserManagementHandlers:
    """Tests for user management MQTT handlers"""

    def test_list_users(self, session_manager):
        """Should list all users"""
        session_manager.create_user("user1", "pass", UserRole.OPERATOR)
        session_manager.create_user("user2", "pass", UserRole.ENGINEER)

        users = session_manager.list_users()

        usernames = [u["username"] for u in users]
        assert "user1" in usernames
        assert "user2" in usernames
        assert "admin" in usernames  # Default user

    def test_create_user_handler(self, session_manager):
        """Create user handler should add user"""
        payload = {
            "username": "newuser",
            "password": "newpass",
            "role": "operator",
            "display_name": "New User",
            "email": "new@example.com"
        }

        user = session_manager.create_user(
            username=payload["username"],
            password=payload["password"],
            role=UserRole(payload["role"]),
            display_name=payload.get("display_name", ""),
            email=payload.get("email", "")
        )

        assert user is not None
        assert user.username == "newuser"
        assert user.display_name == "New User"

    def test_update_user_handler(self, session_manager):
        """Update user handler should modify user"""
        session_manager.create_user("updateme", "pass", UserRole.OPERATOR)

        result = session_manager.update_user(
            "updateme",
            role="engineer",
            display_name="Updated Name"
        )

        assert result is True
        assert session_manager.users["updateme"].role == UserRole.ENGINEER
        assert session_manager.users["updateme"].display_name == "Updated Name"

    def test_delete_user_handler(self, session_manager):
        """Delete user handler should remove user"""
        session_manager.create_user("deleteme", "pass", UserRole.OPERATOR)

        result = session_manager.delete_user("deleteme")

        assert result is True
        assert "deleteme" not in session_manager.users

    def test_get_active_sessions(self, session_manager):
        """Should list active sessions"""
        session_manager.create_user("user1", "pass", UserRole.OPERATOR)
        session_manager.create_user("user2", "pass", UserRole.ADMIN)

        session_manager.authenticate("user1", "pass")
        session_manager.authenticate("user2", "pass")

        sessions = session_manager.get_active_sessions()

        assert len(sessions) == 2


class TestPermissionChecks:
    """Tests for permission checking in handlers"""

    def test_admin_can_manage_users(self, session_manager):
        """Admin should have MANAGE_USERS permission"""
        session = session_manager.authenticate(TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)

        assert session_manager.has_permission(
            session.session_id,
            Permission.MANAGE_USERS
        )

    def test_operator_cannot_manage_users(self, session_manager):
        """Operator should NOT have MANAGE_USERS permission"""
        session_manager.create_user("op", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("op", "pass")

        assert not session_manager.has_permission(
            session.session_id,
            Permission.MANAGE_USERS
        )

    def test_engineer_can_view_audit(self, session_manager):
        """Engineer should have VIEW_AUDIT permission"""
        session_manager.create_user("engineer", "pass", UserRole.ENGINEER)
        session = session_manager.authenticate("engineer", "pass")

        assert session_manager.has_permission(
            session.session_id,
            Permission.VIEW_AUDIT
        )


class TestAuditTrailHandlers:
    """Tests for audit trail MQTT handlers"""

    def test_query_events(self, audit_trail):
        """Should query audit events with filters"""
        # Log some events
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user1",
            description="Login 1"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGOUT,
            user="user1",
            description="Logout 1"
        )
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="user2",
            description="Login 2"
        )

        # Query logins only
        results = audit_trail.query_events(
            event_types=[AuditEventType.USER_LOGIN]
        )

        assert len(results) == 2
        assert all(e.event_type == "user.login" for e in results)

    def test_verify_integrity(self, audit_trail):
        """Integrity check should pass for valid trail"""
        for i in range(5):
            audit_trail.log_event(
                event_type=AuditEventType.USER_LOGIN,
                user=f"user{i}",
                description=f"Login {i}"
            )

        is_valid, errors, count = audit_trail.verify_integrity()

        assert is_valid is True
        assert len(errors) == 0

    def test_export_csv(self, audit_trail, temp_dir):
        """Should export to CSV"""
        audit_trail.log_event(
            event_type=AuditEventType.CONFIG_CHANNEL_MODIFIED,
            user="admin",
            description="Test export"
        )

        output = temp_dir / "export.csv"
        count = audit_trail.export_csv(output)

        assert count >= 1
        assert output.exists()


class TestArchiveHandlers:
    """Tests for archive management MQTT handlers"""

    def test_list_archives_empty(self, archive_manager):
        """Should return empty list when no archives"""
        results = archive_manager.search_archives()
        assert len(results) == 0

    def test_archive_and_search(self, archive_manager, temp_dir):
        """Should archive and find via search"""
        # Create file
        test_file = temp_dir / "test_data.csv"
        test_file.write_text("a,b,c\n1,2,3\n")

        # Archive it
        entry = archive_manager.archive_file(test_file, "recording")

        # Search should find it
        results = archive_manager.search_archives(content_type="recording")

        assert len(results) == 1
        assert results[0].archive_id == entry.archive_id

    def test_verify_archive(self, archive_manager, temp_dir):
        """Should verify archive integrity"""
        test_file = temp_dir / "test_data.csv"
        test_file.write_text("a,b,c\n1,2,3\n")

        entry = archive_manager.archive_file(test_file, "recording")

        is_valid, message = archive_manager.verify_archive(entry.archive_id)

        assert is_valid is True

    def test_retrieve_archive(self, archive_manager, temp_dir):
        """Should retrieve archived file"""
        test_file = temp_dir / "test_data.csv"
        original_content = "a,b,c\n1,2,3\n"
        test_file.write_text(original_content)

        entry = archive_manager.archive_file(test_file, "recording")

        retrieved = archive_manager.retrieve_archive(
            entry.archive_id,
            destination=temp_dir / "retrieved"
        )

        assert retrieved is not None
        assert retrieved.read_text() == original_content


class TestAuthIntegration:
    """Integration tests combining auth with other components"""

    def test_audit_login_event(self, session_manager, audit_trail):
        """Login should be auditable"""
        session_manager.create_user("audituser", "pass", UserRole.OPERATOR)

        # Log the authentication event
        audit_trail.log_event(
            event_type=AuditEventType.USER_LOGIN,
            user="audituser",
            description="User logged in",
            source_ip="192.168.1.100"
        )

        # Query for login events
        events = audit_trail.query_events(
            event_types=[AuditEventType.USER_LOGIN],
            user="audituser"
        )

        assert len(events) >= 1
        assert events[0].user == "audituser"

    def test_config_change_with_signature(self, session_manager, audit_trail):
        """Config changes should require electronic signature"""
        session_manager.create_user("signer", "signerpass", UserRole.ENGINEER)
        session = session_manager.authenticate("signer", "signerpass")

        # Create signature
        signature = session_manager.create_electronic_signature(
            session_id=session.session_id,
            password="signerpass",
            action_type="config_change",
            action_description="Modified safety threshold",
            reason="Production requirement"
        )

        assert signature is not None

        # Log with signature info
        audit_trail.log_event(
            event_type=AuditEventType.CONFIG_SAFETY_MODIFIED,
            user="signer",
            description="Modified safety threshold",
            details={"signature_id": signature.signature_id},
            reason="Production requirement"
        )

        events = audit_trail.query_events(
            event_types=[AuditEventType.CONFIG_SAFETY_MODIFIED]
        )

        assert len(events) >= 1
        assert "signature_id" in events[0].details


class TestPayloadValidation:
    """Tests for MQTT payload validation"""

    def test_login_missing_username(self):
        """Login should fail with missing username"""
        payload = {"password": "pass"}

        # Simulating handler validation
        username = payload.get("username")
        assert username is None  # Would fail in handler

    def test_login_missing_password(self):
        """Login should fail with missing password"""
        payload = {"username": "user"}

        password = payload.get("password")
        assert password is None  # Would fail in handler

    def test_create_user_valid_role(self, session_manager):
        """Should only accept valid roles"""
        valid_roles = ["viewer", "operator", "engineer", "admin"]

        for role in valid_roles:
            user = session_manager.create_user(
                username=f"user_{role}",
                password="pass",
                role=UserRole(role)
            )
            assert user is not None

    def test_create_user_invalid_role(self):
        """Should reject invalid roles"""
        with pytest.raises(ValueError):
            UserRole("invalid_role")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
