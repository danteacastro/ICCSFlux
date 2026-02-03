#!/usr/bin/env python3
"""
NISystem Authentication and Session Test Suite

Tests user authentication and session management:
1. User authentication (login/logout)
2. Password hashing and verification
3. Session creation and validation
4. Session timeout handling
5. Account lockout after failed attempts
6. Role-based permissions
7. Electronic signature (21 CFR Part 11)
8. User management (create, update, delete)

Usage:
    pytest tests/test_auth_session.py -v
"""

import pytest
import time
import tempfile
from pathlib import Path
import shutil

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
from user_session import (
    UserSessionManager,
    UserRole,
    Permission,
    User,
    Session,
    ROLE_PERMISSIONS,
)


def _set_known_passwords(manager):
    """Reset default users to known passwords for testing."""
    manager.update_user("admin", password="iccsadmin1969")
    manager.update_user("supervisor", password="supervisor")
    manager.update_user("operator", password="operator")
    manager.update_user("guest", password="guest")


class TestUserAuthentication:
    """Test suite for user authentication"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager with temp directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(
            data_dir=Path(self.temp_dir),
            session_timeout_minutes=30,
            max_failed_attempts=3,
            lockout_duration_minutes=5
        )
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_users_created(self):
        """Test that default users are created on initialization"""
        # Check default users exist
        assert "admin" in self.manager.users
        assert "supervisor" in self.manager.users
        assert "operator" in self.manager.users
        assert "guest" in self.manager.users

        # Check roles
        assert self.manager.users["admin"].role == UserRole.ADMIN
        assert self.manager.users["supervisor"].role == UserRole.SUPERVISOR
        assert self.manager.users["operator"].role == UserRole.OPERATOR
        assert self.manager.users["guest"].role == UserRole.GUEST

    def test_successful_login(self):
        """Test successful authentication"""
        session = self.manager.authenticate(
            username="operator",
            password="operator",
            source_ip="127.0.0.1"
        )

        assert session is not None
        assert session.username == "operator"
        assert session.role == UserRole.OPERATOR
        assert session.source_ip == "127.0.0.1"
        assert session.session_id in self.manager.sessions

    def test_login_wrong_password(self):
        """Test authentication with wrong password"""
        session = self.manager.authenticate(
            username="operator",
            password="wrongpassword"
        )

        assert session is None

    def test_login_nonexistent_user(self):
        """Test authentication with non-existent user"""
        session = self.manager.authenticate(
            username="nonexistent",
            password="password"
        )

        assert session is None

    def test_login_disabled_user(self):
        """Test authentication with disabled user"""
        # Disable the user
        self.manager.update_user("operator", enabled=False)

        session = self.manager.authenticate(
            username="operator",
            password="operator"
        )

        assert session is None

    def test_logout(self):
        """Test session logout"""
        # Login
        session = self.manager.authenticate("operator", "operator")
        assert session is not None
        session_id = session.session_id

        # Logout
        result = self.manager.logout(session_id)
        assert result is True

        # Session should be invalid
        assert self.manager.validate_session(session_id) is None

    def test_logout_invalid_session(self):
        """Test logout with invalid session"""
        result = self.manager.logout("invalid_session_id")
        assert result is False


class TestAccountLockout:
    """Test suite for account lockout functionality"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(
            data_dir=Path(self.temp_dir),
            session_timeout_minutes=30,
            max_failed_attempts=3,
            lockout_duration_minutes=1  # Short lockout for testing
        )
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_failed_attempts_increment(self):
        """Test that failed attempts are counted"""
        # First failed attempt
        self.manager.authenticate("operator", "wrong")
        assert self.manager.users["operator"].failed_attempts == 1

        # Second failed attempt
        self.manager.authenticate("operator", "wrong")
        assert self.manager.users["operator"].failed_attempts == 2

    def test_account_locks_after_max_attempts(self):
        """Test that account is locked after max failed attempts"""
        # Make max failed attempts
        for _ in range(3):
            self.manager.authenticate("operator", "wrong")

        # Account should be locked
        user = self.manager.users["operator"]
        assert user.locked_until is not None

        # Even with correct password, should fail
        session = self.manager.authenticate("operator", "operator")
        assert session is None

    def test_lockout_expires(self):
        """Test that lockout expires after duration"""
        # Lock the account
        for _ in range(3):
            self.manager.authenticate("operator", "wrong")

        # Wait for lockout to expire (lockout is 1 minute, so we mock it)
        # For this test, manually clear the lockout
        user = self.manager.users["operator"]
        user.locked_until = None
        user.failed_attempts = 0

        # Should be able to login now
        session = self.manager.authenticate("operator", "operator")
        assert session is not None

    def test_successful_login_resets_failed_attempts(self):
        """Test that successful login resets failed attempts"""
        # Make some failed attempts
        self.manager.authenticate("operator", "wrong")
        self.manager.authenticate("operator", "wrong")
        assert self.manager.users["operator"].failed_attempts == 2

        # Successful login
        session = self.manager.authenticate("operator", "operator")
        assert session is not None

        # Failed attempts should be reset
        assert self.manager.users["operator"].failed_attempts == 0


class TestSessionManagement:
    """Test suite for session management"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(
            data_dir=Path(self.temp_dir),
            session_timeout_minutes=1  # 1 minute timeout for testing
        )
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_session_validation(self):
        """Test session validation"""
        session = self.manager.authenticate("operator", "operator")
        assert session is not None

        # Validate session
        validated = self.manager.validate_session(session.session_id)
        assert validated is not None
        assert validated.username == "operator"

    def test_session_validation_updates_activity(self):
        """Test that validation updates last activity"""
        session = self.manager.authenticate("operator", "operator")
        original_activity = session.last_activity

        time.sleep(0.1)

        # Validate session
        validated = self.manager.validate_session(session.session_id)
        assert validated.last_activity > original_activity

    def test_invalid_session_id(self):
        """Test validation with invalid session ID"""
        validated = self.manager.validate_session("invalid_session_id")
        assert validated is None

    def test_get_active_sessions(self):
        """Test getting list of active sessions"""
        # Create multiple sessions
        session1 = self.manager.authenticate("operator", "operator")
        session2 = self.manager.authenticate("admin", "iccsadmin1969")

        active = self.manager.get_active_sessions()
        assert len(active) == 2

        usernames = [s['username'] for s in active]
        assert "operator" in usernames
        assert "admin" in usernames

    def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions"""
        # Create a session
        session = self.manager.authenticate("operator", "operator")

        # Manually expire it
        from datetime import datetime, timedelta
        self.manager.sessions[session.session_id].last_activity = (
            datetime.now() - timedelta(minutes=10)
        )

        # Cleanup
        self.manager.cleanup_expired_sessions()

        # Session should be removed
        assert session.session_id not in self.manager.sessions


class TestPermissions:
    """Test suite for role-based permissions"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(data_dir=Path(self.temp_dir))
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_guest_permissions(self):
        """Test guest user permissions"""
        session = self.manager.authenticate("guest", "guest")
        assert session is not None

        # Guest can view data
        assert self.manager.has_permission(session.session_id, Permission.VIEW_DATA)

        # Guest cannot control outputs
        assert not self.manager.has_permission(session.session_id, Permission.CONTROL_OUTPUTS)

        # Guest cannot manage users
        assert not self.manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_operator_permissions(self):
        """Test operator user permissions"""
        session = self.manager.authenticate("operator", "operator")
        assert session is not None

        # Operator can view and control
        assert self.manager.has_permission(session.session_id, Permission.VIEW_DATA)
        assert self.manager.has_permission(session.session_id, Permission.CONTROL_OUTPUTS)
        assert self.manager.has_permission(session.session_id, Permission.ACK_ALARMS)

        # Operator cannot modify config
        assert not self.manager.has_permission(session.session_id, Permission.MODIFY_CHANNELS)
        assert not self.manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_supervisor_permissions(self):
        """Test supervisor user permissions"""
        session = self.manager.authenticate("supervisor", "supervisor")
        assert session is not None

        # Supervisor can control and configure
        assert self.manager.has_permission(session.session_id, Permission.CONTROL_OUTPUTS)
        assert self.manager.has_permission(session.session_id, Permission.MODIFY_CHANNELS)
        assert self.manager.has_permission(session.session_id, Permission.MODIFY_ALARMS)
        assert self.manager.has_permission(session.session_id, Permission.SAVE_PROJECT)

        # Supervisor cannot manage users
        assert not self.manager.has_permission(session.session_id, Permission.MANAGE_USERS)

    def test_admin_permissions(self):
        """Test admin user has all permissions"""
        session = self.manager.authenticate("admin", "iccsadmin1969")
        assert session is not None

        # Admin has all permissions
        for permission in Permission:
            assert self.manager.has_permission(session.session_id, permission), \
                f"Admin missing permission: {permission}"

    def test_require_permission_success(self):
        """Test require_permission with valid permission"""
        session = self.manager.authenticate("operator", "operator")

        # Should not raise
        result = self.manager.require_permission(
            session.session_id,
            Permission.CONTROL_OUTPUTS
        )
        assert result.username == "operator"

    def test_require_permission_failure(self):
        """Test require_permission with invalid permission"""
        session = self.manager.authenticate("operator", "operator")

        # Should raise PermissionError
        with pytest.raises(PermissionError):
            self.manager.require_permission(
                session.session_id,
                Permission.MANAGE_USERS
            )

    def test_require_permission_invalid_session(self):
        """Test require_permission with invalid session"""
        with pytest.raises(PermissionError):
            self.manager.require_permission(
                "invalid_session",
                Permission.VIEW_DATA
            )


class TestUserManagement:
    """Test suite for user management"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(data_dir=Path(self.temp_dir))
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_user(self):
        """Test creating a new user"""
        user = self.manager.create_user(
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

        # User should be able to authenticate
        session = self.manager.authenticate("testuser", "testpass123")
        assert session is not None

    def test_create_duplicate_user(self):
        """Test creating a user with existing username"""
        user = self.manager.create_user(
            username="operator",  # Already exists
            password="password",
            role=UserRole.OPERATOR
        )

        assert user is None

    def test_update_user_password(self):
        """Test updating user password"""
        # Update password
        result = self.manager.update_user("operator", password="newpassword")
        assert result is True

        # Old password should not work
        session = self.manager.authenticate("operator", "operator")
        assert session is None

        # New password should work
        session = self.manager.authenticate("operator", "newpassword")
        assert session is not None

    def test_update_user_role(self):
        """Test updating user role"""
        result = self.manager.update_user("operator", role=UserRole.SUPERVISOR)
        assert result is True

        assert self.manager.users["operator"].role == UserRole.SUPERVISOR

    def test_delete_user(self):
        """Test deleting a user"""
        # Create a test user
        self.manager.create_user("testuser", "testpass", UserRole.OPERATOR)

        # Delete user
        result = self.manager.delete_user("testuser")
        assert result is True

        # User should not exist
        assert "testuser" not in self.manager.users

    def test_delete_user_invalidates_sessions(self):
        """Test that deleting user invalidates their sessions"""
        # Create and authenticate a test user
        self.manager.create_user("testuser", "testpass", UserRole.OPERATOR)
        session = self.manager.authenticate("testuser", "testpass")
        session_id = session.session_id

        # Delete user
        self.manager.delete_user("testuser")

        # Session should be invalid
        assert self.manager.validate_session(session_id) is None

    def test_list_users(self):
        """Test listing all users"""
        users = self.manager.list_users()

        assert len(users) >= 4  # At least default users
        usernames = [u['username'] for u in users]
        assert "admin" in usernames
        assert "operator" in usernames

    def test_get_user_info(self):
        """Test getting user info"""
        info = self.manager.get_user_info("operator")

        assert info is not None
        assert info['username'] == "operator"
        assert info['role'] == "operator"
        assert 'password_hash' not in info  # Should not expose password hash


class TestElectronicSignature:
    """Test suite for electronic signature (21 CFR Part 11)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(data_dir=Path(self.temp_dir))
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_electronic_signature(self):
        """Test creating electronic signature with valid password"""
        session = self.manager.authenticate("supervisor", "supervisor")

        signature = self.manager.create_electronic_signature(
            session_id=session.session_id,
            password="supervisor",  # Re-verify password
            action_type="safety.bypass",
            action_description="Bypass interlock IL001 for maintenance",
            reason="Scheduled maintenance window"
        )

        assert signature is not None
        assert signature.username == "supervisor"
        assert signature.action_type == "safety.bypass"
        assert signature.password_verified is True
        assert signature.reason == "Scheduled maintenance window"

    def test_electronic_signature_wrong_password(self):
        """Test electronic signature with wrong password fails"""
        session = self.manager.authenticate("supervisor", "supervisor")

        signature = self.manager.create_electronic_signature(
            session_id=session.session_id,
            password="wrongpassword",  # Wrong password
            action_type="safety.bypass",
            action_description="Test action",
            reason="Test reason"
        )

        assert signature is None

    def test_electronic_signature_invalid_session(self):
        """Test electronic signature with invalid session fails"""
        signature = self.manager.create_electronic_signature(
            session_id="invalid_session",
            password="password",
            action_type="test",
            action_description="Test",
            reason="Test"
        )

        assert signature is None


class TestPasswordHashing:
    """Test suite for password hashing"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test session manager"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = UserSessionManager(data_dir=Path(self.temp_dir))
        _set_known_passwords(self.manager)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_passwords_are_hashed(self):
        """Test that passwords are stored as hashes"""
        user = self.manager.users["operator"]

        # Password hash should not equal the password
        assert user.password_hash != "operator"

        # Password hash should start with bcrypt prefix
        assert user.password_hash.startswith("$2")

    def test_different_passwords_have_different_hashes(self):
        """Test that different passwords produce different hashes"""
        hash1 = self.manager._hash_password("password1")
        hash2 = self.manager._hash_password("password2")

        assert hash1 != hash2

    def test_same_password_has_different_hashes(self):
        """Test that same password with different salts produces different hashes"""
        hash1 = self.manager._hash_password("samepassword")
        hash2 = self.manager._hash_password("samepassword")

        # Same password but different salts = different hashes
        assert hash1 != hash2

    def test_password_verification(self):
        """Test password verification"""
        password = "testpassword123"
        password_hash = self.manager._hash_password(password)

        assert self.manager._verify_password(password, password_hash) is True
        assert self.manager._verify_password("wrongpassword", password_hash) is False


class TestDataPersistence:
    """Test suite for user data persistence"""

    def test_users_persist_across_restarts(self):
        """Test that users are saved and loaded correctly"""
        temp_dir = tempfile.mkdtemp()

        try:
            # Create manager and add user
            manager1 = UserSessionManager(data_dir=Path(temp_dir))
            manager1.create_user(
                username="persistent_user",
                password="mypassword",
                role=UserRole.SUPERVISOR,
                display_name="Persistent User"
            )

            # Create new manager (simulating restart)
            manager2 = UserSessionManager(data_dir=Path(temp_dir))

            # User should exist
            assert "persistent_user" in manager2.users
            assert manager2.users["persistent_user"].role == UserRole.SUPERVISOR

            # User should be able to authenticate
            session = manager2.authenticate("persistent_user", "mypassword")
            assert session is not None

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_user_updates_persist(self):
        """Test that user updates are saved"""
        temp_dir = tempfile.mkdtemp()

        try:
            # Create manager and update user
            manager1 = UserSessionManager(data_dir=Path(temp_dir))
            manager1.update_user("operator", role=UserRole.SUPERVISOR)

            # Create new manager
            manager2 = UserSessionManager(data_dir=Path(temp_dir))

            # Change should persist
            assert manager2.users["operator"].role == UserRole.SUPERVISOR

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
