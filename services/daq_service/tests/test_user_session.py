#!/usr/bin/env python3
"""
Unit tests for UserSessionManager

Tests:
- User creation, update, deletion
- Authentication and session management
- Password hashing and verification
- Account lockout after failed attempts
- Permission checking
- Electronic signatures
- Session timeout and cleanup
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from user_session import (
    UserSessionManager, User, Session, ElectronicSignature,
    UserRole, Permission, ROLE_PERMISSIONS
)

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
    """Create a fresh UserSessionManager for each test"""
    return UserSessionManager(
        data_dir=temp_dir,
        session_timeout_minutes=30,
        max_failed_attempts=3,
        lockout_duration_minutes=5
    )

class TestUserCreation:
    """Tests for user creation and management"""

    def test_default_users_created(self, session_manager):
        """Default admin and operator users should be created"""
        assert "admin" in session_manager.users
        assert "operator" in session_manager.users

    def test_create_user(self, session_manager):
        """Should create new user with hashed password"""
        user = session_manager.create_user(
            username="testuser",
            password="testpass123",
            role=UserRole.OPERATOR,
            display_name="Test User",
            email="test@example.com"
        )

        assert user is not None
        assert user.username == "testuser"
        assert user.role == UserRole.OPERATOR
        assert user.display_name == "Test User"
        assert user.email == "test@example.com"
        assert user.enabled is True
        assert user.password_hash != "testpass123"  # Should be hashed

    def test_create_duplicate_user_fails(self, session_manager):
        """Creating a user with existing username should fail"""
        session_manager.create_user(
            username="duplicate",
            password="pass1",
            role=UserRole.OPERATOR
        )

        result = session_manager.create_user(
            username="duplicate",
            password="pass2",
            role=UserRole.ADMIN
        )

        assert result is None

    def test_update_user(self, session_manager):
        """Should update user properties"""
        session_manager.create_user(
            username="updatetest",
            password="oldpass",
            role=UserRole.OPERATOR
        )

        result = session_manager.update_user(
            username="updatetest",
            role="engineer",
            display_name="Updated Name"
        )

        assert result is True
        user = session_manager.users["updatetest"]
        assert user.role == UserRole.ENGINEER
        assert user.display_name == "Updated Name"

    def test_update_password(self, session_manager):
        """Should update user password"""
        session_manager.create_user(
            username="passtest",
            password="oldpass",
            role=UserRole.OPERATOR
        )

        old_hash = session_manager.users["passtest"].password_hash
        session_manager.update_user(username="passtest", password="newpass")
        new_hash = session_manager.users["passtest"].password_hash

        assert old_hash != new_hash

        # Verify new password works
        session = session_manager.authenticate("passtest", "newpass")
        assert session is not None

    def test_delete_user(self, session_manager):
        """Should delete user and invalidate sessions"""
        session_manager.create_user(
            username="deletetest",
            password="pass",
            role=UserRole.OPERATOR
        )

        # Create a session
        session = session_manager.authenticate("deletetest", "pass")
        session_id = session.session_id

        # Delete user
        result = session_manager.delete_user("deletetest")

        assert result is True
        assert "deletetest" not in session_manager.users
        assert session_id not in session_manager.sessions

    def test_delete_nonexistent_user(self, session_manager):
        """Deleting nonexistent user should return False"""
        result = session_manager.delete_user("nonexistent")
        assert result is False

class TestAuthentication:
    """Tests for authentication functionality"""

    def test_successful_authentication(self, session_manager):
        """Valid credentials should create session"""
        session_manager.create_user(
            username="authtest",
            password="correctpass",
            role=UserRole.OPERATOR
        )

        session = session_manager.authenticate(
            username="authtest",
            password="correctpass",
            source_ip="192.168.1.100"
        )

        assert session is not None
        assert session.username == "authtest"
        assert session.role == UserRole.OPERATOR
        assert session.source_ip == "192.168.1.100"

    def test_wrong_password(self, session_manager):
        """Wrong password should fail authentication"""
        session_manager.create_user(
            username="wrongpass",
            password="correct",
            role=UserRole.OPERATOR
        )

        session = session_manager.authenticate("wrongpass", "incorrect")
        assert session is None

    def test_nonexistent_user(self, session_manager):
        """Authentication with nonexistent user should fail"""
        session = session_manager.authenticate("nobody", "pass")
        assert session is None

    def test_disabled_user(self, session_manager):
        """Disabled user should not authenticate"""
        session_manager.create_user(
            username="disabled",
            password="pass",
            role=UserRole.OPERATOR
        )
        session_manager.update_user("disabled", enabled=False)

        session = session_manager.authenticate("disabled", "pass")
        assert session is None

    def test_last_login_updated(self, session_manager):
        """Successful login should update last_login timestamp"""
        session_manager.create_user(
            username="logintime",
            password="pass",
            role=UserRole.OPERATOR
        )

        before = session_manager.users["logintime"].last_login
        session_manager.authenticate("logintime", "pass")
        after = session_manager.users["logintime"].last_login

        assert after != before
        assert after != ""

class TestAccountLockout:
    """Tests for account lockout after failed attempts"""

    def test_failed_attempts_tracked(self, session_manager):
        """Failed attempts should be counted"""
        session_manager.create_user(
            username="locktest",
            password="correct",
            role=UserRole.OPERATOR
        )

        session_manager.authenticate("locktest", "wrong1")
        assert session_manager.users["locktest"].failed_attempts == 1

        session_manager.authenticate("locktest", "wrong2")
        assert session_manager.users["locktest"].failed_attempts == 2

    def test_lockout_after_max_attempts(self, session_manager):
        """Account should lock after max failed attempts"""
        session_manager.create_user(
            username="lockme",
            password="correct",
            role=UserRole.OPERATOR
        )

        # Fail 3 times (max_failed_attempts=3)
        for i in range(3):
            session_manager.authenticate("lockme", f"wrong{i}")

        # Account should be locked
        assert session_manager.users["lockme"].locked_until is not None

        # Even correct password should fail during lockout
        session = session_manager.authenticate("lockme", "correct")
        assert session is None

    def test_successful_login_resets_attempts(self, session_manager):
        """Successful login should reset failed attempts"""
        session_manager.create_user(
            username="resetattempts",
            password="correct",
            role=UserRole.OPERATOR
        )

        # Fail twice
        session_manager.authenticate("resetattempts", "wrong1")
        session_manager.authenticate("resetattempts", "wrong2")
        assert session_manager.users["resetattempts"].failed_attempts == 2

        # Succeed
        session_manager.authenticate("resetattempts", "correct")
        assert session_manager.users["resetattempts"].failed_attempts == 0

class TestSessionManagement:
    """Tests for session validation and management"""

    def test_validate_session(self, session_manager):
        """Valid session should be validated"""
        session_manager.create_user("sessionuser", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("sessionuser", "pass")

        validated = session_manager.validate_session(session.session_id)

        assert validated is not None
        assert validated.username == "sessionuser"

    def test_validate_invalid_session(self, session_manager):
        """Invalid session ID should return None"""
        result = session_manager.validate_session("invalid_session_id")
        assert result is None

    def test_logout(self, session_manager):
        """Logout should invalidate session"""
        session_manager.create_user("logoutuser", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("logoutuser", "pass")
        session_id = session.session_id

        result = session_manager.logout(session_id)

        assert result is True
        assert session_manager.validate_session(session_id) is None

    def test_logout_invalid_session(self, session_manager):
        """Logout with invalid session should return False"""
        result = session_manager.logout("invalid_session_id")
        assert result is False

    def test_session_activity_updated(self, session_manager):
        """Validating session should update last_activity"""
        session_manager.create_user("activityuser", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("activityuser", "pass")

        initial_activity = session.last_activity
        time.sleep(0.1)

        session_manager.validate_session(session.session_id)
        updated_session = session_manager.sessions[session.session_id]

        assert updated_session.last_activity > initial_activity

    def test_get_active_sessions(self, session_manager):
        """Should list active sessions"""
        session_manager.create_user("user1", "pass", UserRole.OPERATOR)
        session_manager.create_user("user2", "pass", UserRole.ADMIN)

        session_manager.authenticate("user1", "pass")
        session_manager.authenticate("user2", "pass")

        active = session_manager.get_active_sessions()

        assert len(active) == 2
        usernames = [s['username'] for s in active]
        assert "user1" in usernames
        assert "user2" in usernames

class TestPermissions:
    """Tests for permission checking"""

    def test_viewer_permissions(self, session_manager):
        """Viewer should only have view permissions"""
        session_manager.create_user("viewer", "pass", UserRole.VIEWER)
        session = session_manager.authenticate("viewer", "pass")

        # Should have
        assert session_manager.has_permission(session.session_id, Permission.VIEW_DATA)
        assert session_manager.has_permission(session.session_id, Permission.VIEW_ALARMS)

        # Should NOT have
        assert not session_manager.has_permission(session.session_id, Permission.ACK_ALARMS)
        assert not session_manager.has_permission(session.session_id, Permission.MODIFY_CHANNELS)
        assert not session_manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_operator_permissions(self, session_manager):
        """Operator should have operational permissions"""
        session_manager.create_user("op", "pass", UserRole.OPERATOR)
        session = session_manager.authenticate("op", "pass")

        # Should have
        assert session_manager.has_permission(session.session_id, Permission.VIEW_DATA)
        assert session_manager.has_permission(session.session_id, Permission.ACK_ALARMS)
        assert session_manager.has_permission(session.session_id, Permission.START_RECORDING)
        assert session_manager.has_permission(session.session_id, Permission.CONTROL_OUTPUTS)

        # Should NOT have
        assert not session_manager.has_permission(session.session_id, Permission.MODIFY_CHANNELS)
        assert not session_manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_engineer_permissions(self, session_manager):
        """Engineer should have config permissions"""
        session_manager.create_user("engineer", "pass", UserRole.ENGINEER)
        session = session_manager.authenticate("engineer", "pass")

        # Should have
        assert session_manager.has_permission(session.session_id, Permission.VIEW_DATA)
        assert session_manager.has_permission(session.session_id, Permission.ACK_ALARMS)
        assert session_manager.has_permission(session.session_id, Permission.MODIFY_CHANNELS)
        assert session_manager.has_permission(session.session_id, Permission.LOAD_PROJECT)

        # Should NOT have
        assert not session_manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_admin_permissions(self, session_manager):
        """Admin should have all permissions"""
        session = session_manager.authenticate(TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)

        # Should have ALL permissions
        for permission in Permission:
            assert session_manager.has_permission(session.session_id, permission), \
                f"Admin should have {permission.value}"

    def test_require_permission_raises(self, session_manager):
        """require_permission should raise on missing permission"""
        session_manager.create_user("restricted", "pass", UserRole.VIEWER)
        session = session_manager.authenticate("restricted", "pass")

        with pytest.raises(PermissionError):
            session_manager.require_permission(session.session_id, Permission.MANAGE_USERS)

    def test_require_permission_invalid_session(self, session_manager):
        """require_permission should raise for invalid session"""
        with pytest.raises(PermissionError):
            session_manager.require_permission("invalid", Permission.VIEW_DATA)

class TestElectronicSignature:
    """Tests for electronic signatures (21 CFR Part 11)"""

    def test_create_signature(self, session_manager):
        """Should create electronic signature with valid credentials"""
        session_manager.create_user("signer", "signerpass", UserRole.ENGINEER)
        session = session_manager.authenticate("signer", "signerpass")

        signature = session_manager.create_electronic_signature(
            session_id=session.session_id,
            password="signerpass",
            action_type="config_change",
            action_description="Modified safety threshold",
            reason="Production requirement change"
        )

        assert signature is not None
        assert signature.username == "signer"
        assert signature.action_type == "config_change"
        assert signature.password_verified is True
        assert signature.reason == "Production requirement change"

    def test_signature_wrong_password(self, session_manager):
        """Electronic signature should fail with wrong password"""
        session_manager.create_user("badsigner", "correct", UserRole.ENGINEER)
        session = session_manager.authenticate("badsigner", "correct")

        signature = session_manager.create_electronic_signature(
            session_id=session.session_id,
            password="wrong",  # Wrong password
            action_type="test",
            action_description="Test action",
            reason="Test"
        )

        assert signature is None

    def test_signature_invalid_session(self, session_manager):
        """Electronic signature should fail with invalid session"""
        signature = session_manager.create_electronic_signature(
            session_id="invalid",
            password="pass",
            action_type="test",
            action_description="Test",
            reason="Test"
        )

        assert signature is None

class TestPersistence:
    """Tests for data persistence"""

    def test_users_persisted(self, temp_dir):
        """Users should be saved to disk and reloaded"""
        # Create manager and add user
        manager1 = UserSessionManager(data_dir=temp_dir)
        manager1.create_user("persistent", "pass", UserRole.ENGINEER)

        # Create new manager instance (should load from disk)
        manager2 = UserSessionManager(data_dir=temp_dir)

        assert "persistent" in manager2.users
        assert manager2.users["persistent"].role == UserRole.ENGINEER

    def test_password_survives_reload(self, temp_dir):
        """Password hash should survive reload"""
        manager1 = UserSessionManager(data_dir=temp_dir)
        manager1.create_user("passreload", "mypassword", UserRole.OPERATOR)

        manager2 = UserSessionManager(data_dir=temp_dir)
        session = manager2.authenticate("passreload", "mypassword")

        assert session is not None

class TestUserInfo:
    """Tests for user info retrieval"""

    def test_get_user_info(self, session_manager):
        """Should return user info without password hash"""
        session_manager.create_user(
            username="infotest",
            password="secret",
            role=UserRole.ENGINEER,
            display_name="Info Test",
            email="info@test.com"
        )

        info = session_manager.get_user_info("infotest")

        assert info is not None
        assert info["username"] == "infotest"
        assert info["display_name"] == "Info Test"
        assert info["role"] == "engineer"
        assert "password" not in info
        assert "password_hash" not in info

    def test_list_users(self, session_manager):
        """Should list all users"""
        session_manager.create_user("list1", "pass", UserRole.OPERATOR)
        session_manager.create_user("list2", "pass", UserRole.ENGINEER)

        users = session_manager.list_users()

        usernames = [u["username"] for u in users]
        assert "admin" in usernames
        assert "operator" in usernames
        assert "list1" in usernames
        assert "list2" in usernames

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
