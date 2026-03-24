"""
Tests for user_session.py
Covers user authentication, session management, permissions, and electronic signatures.
Critical for 21 CFR Part 11 compliance.
"""

import pytest
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from user_session import (
    UserSessionManager, User, Session, ElectronicSignature,
    UserRole, Permission, ROLE_PERMISSIONS
)

def _set_known_passwords(manager):
    """Reset default users to known passwords for testing."""
    manager.update_user("admin", password="iccsadmin1969")
    manager.update_user("supervisor", password="supervisor")
    manager.update_user("operator", password="operator")
    manager.update_user("guest", password="guest")

class TestUserRole:
    """Tests for UserRole enum"""

    def test_role_values(self):
        """Test all role values exist"""
        assert UserRole.GUEST.value == "guest"
        assert UserRole.OPERATOR.value == "operator"
        assert UserRole.SUPERVISOR.value == "supervisor"
        assert UserRole.ADMIN.value == "admin"

class TestPermission:
    """Tests for Permission enum"""

    def test_view_permissions(self):
        """Test view permissions exist"""
        assert Permission.VIEW_DATA.value == "view.data"
        assert Permission.VIEW_ALARMS.value == "view.alarms"
        assert Permission.VIEW_CONFIG.value == "view.config"
        assert Permission.VIEW_AUDIT.value == "view.audit"

    def test_operator_permissions(self):
        """Test operator permissions exist"""
        assert Permission.ACK_ALARMS.value == "alarm.acknowledge"
        assert Permission.START_RECORDING.value == "recording.start"
        assert Permission.CONTROL_OUTPUTS.value == "output.control"

    def test_admin_permissions(self):
        """Test admin permissions exist"""
        assert Permission.MANAGE_USERS.value == "users.manage"
        assert Permission.BYPASS_SAFETY_LOCK.value == "safety.bypass"

class TestRolePermissions:
    """Tests for role permission mapping"""

    def test_guest_limited_permissions(self):
        """Test guest has limited permissions"""
        guest_perms = ROLE_PERMISSIONS[UserRole.GUEST]

        assert Permission.VIEW_DATA in guest_perms
        assert Permission.VIEW_ALARMS in guest_perms
        assert Permission.CONTROL_OUTPUTS not in guest_perms
        assert Permission.MANAGE_USERS not in guest_perms

    def test_operator_has_operational_permissions(self):
        """Test operator has operational permissions"""
        operator_perms = ROLE_PERMISSIONS[UserRole.OPERATOR]

        assert Permission.VIEW_DATA in operator_perms
        assert Permission.ACK_ALARMS in operator_perms
        assert Permission.START_RECORDING in operator_perms
        assert Permission.CONTROL_OUTPUTS in operator_perms
        assert Permission.MANAGE_USERS not in operator_perms

    def test_supervisor_has_config_permissions(self):
        """Test supervisor has configuration permissions"""
        supervisor_perms = ROLE_PERMISSIONS[UserRole.SUPERVISOR]

        assert Permission.MODIFY_CHANNELS in supervisor_perms
        assert Permission.MODIFY_ALARMS in supervisor_perms
        assert Permission.MODIFY_SAFETY in supervisor_perms
        assert Permission.SAVE_PROJECT in supervisor_perms

    def test_admin_has_all_permissions(self):
        """Test admin has all permissions"""
        admin_perms = ROLE_PERMISSIONS[UserRole.ADMIN]

        # Admin should have every permission
        for perm in Permission:
            assert perm in admin_perms

class TestUser:
    """Tests for User dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        user = User(
            username="testuser",
            password_hash="hash123",
            role=UserRole.OPERATOR,
            display_name="Test User",
            email="test@example.com"
        )

        d = user.to_dict()

        assert d['username'] == "testuser"
        assert d['role'] == "operator"  # Enum value
        assert d['display_name'] == "Test User"

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'username': 'testuser',
            'password_hash': 'hash123',
            'role': 'supervisor',
            'display_name': 'Test User'
        }

        user = User.from_dict(d)

        assert user.username == "testuser"
        assert user.role == UserRole.SUPERVISOR

    def test_from_dict_legacy_role(self):
        """Test legacy role name mapping"""
        d = {
            'username': 'testuser',
            'password_hash': 'hash123',
            'role': 'engineer',  # Legacy name
            'display_name': 'Test User'
        }

        user = User.from_dict(d)

        assert user.role == UserRole.SUPERVISOR  # Mapped

class TestSession:
    """Tests for Session dataclass"""

    def test_is_expired_not_expired(self):
        """Test session not expired"""
        session = Session(
            session_id="test123",
            username="user",
            role=UserRole.OPERATOR,
            created_at=datetime.now(),
            last_activity=datetime.now(),
            source_ip="127.0.0.1"
        )

        assert session.is_expired(timeout_minutes=30) is False

    def test_is_expired_expired(self):
        """Test session expired"""
        old_time = datetime.now() - timedelta(minutes=60)
        session = Session(
            session_id="test123",
            username="user",
            role=UserRole.OPERATOR,
            created_at=old_time,
            last_activity=old_time,
            source_ip="127.0.0.1"
        )

        assert session.is_expired(timeout_minutes=30) is True

class TestUserSessionManager:
    """Tests for UserSessionManager class"""

    @pytest.fixture
    def data_dir(self):
        """Create a temporary directory for user data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, data_dir):
        """Create a UserSessionManager instance"""
        mgr = UserSessionManager(
            data_dir=data_dir,
            session_timeout_minutes=30,
            max_failed_attempts=3,
            lockout_duration_minutes=5
        )
        _set_known_passwords(mgr)
        return mgr

    # =========================================================================
    # USER MANAGEMENT TESTS
    # =========================================================================

    def test_default_users_created(self, manager):
        """Test default users are created"""
        assert 'admin' in manager.users
        assert 'operator' in manager.users
        assert 'supervisor' in manager.users
        assert 'guest' in manager.users

    def test_create_user(self, manager):
        """Test creating a new user"""
        user = manager.create_user(
            username="newuser",
            password="password123",
            role=UserRole.OPERATOR,
            display_name="New User"
        )

        assert user is not None
        assert user.username == "newuser"
        assert user.role == UserRole.OPERATOR
        assert 'newuser' in manager.users

    def test_create_duplicate_user_fails(self, manager):
        """Test creating duplicate user fails"""
        manager.create_user("testuser", "pass", UserRole.OPERATOR)

        result = manager.create_user("testuser", "pass2", UserRole.ADMIN)

        assert result is None

    def test_update_user(self, manager):
        """Test updating user properties"""
        manager.create_user("testuser", "pass", UserRole.OPERATOR)

        success = manager.update_user("testuser", display_name="Updated Name")

        assert success is True
        assert manager.users["testuser"].display_name == "Updated Name"

    def test_update_user_password(self, manager):
        """Test updating user password"""
        manager.create_user("testuser", "oldpass", UserRole.OPERATOR)
        old_hash = manager.users["testuser"].password_hash

        manager.update_user("testuser", password="newpass")

        assert manager.users["testuser"].password_hash != old_hash

    def test_update_user_role(self, manager):
        """Test updating user role"""
        manager.create_user("testuser", "pass", UserRole.OPERATOR)

        manager.update_user("testuser", role=UserRole.SUPERVISOR)

        assert manager.users["testuser"].role == UserRole.SUPERVISOR

    def test_delete_user(self, manager):
        """Test deleting a user"""
        manager.create_user("testuser", "pass", UserRole.OPERATOR)

        success = manager.delete_user("testuser")

        assert success is True
        assert "testuser" not in manager.users

    def test_delete_nonexistent_user(self, manager):
        """Test deleting nonexistent user fails"""
        success = manager.delete_user("nonexistent")

        assert success is False

    def test_list_users(self, manager):
        """Test listing all users"""
        users = manager.list_users()

        assert len(users) >= 4  # Default users
        assert any(u['username'] == 'admin' for u in users)

    def test_get_user_info(self, manager):
        """Test getting user info"""
        info = manager.get_user_info("admin")

        assert info is not None
        assert info['username'] == "admin"
        assert info['role'] == "admin"
        assert 'password_hash' not in info  # Should be excluded

    # =========================================================================
    # AUTHENTICATION TESTS
    # =========================================================================

    def test_authenticate_success(self, manager):
        """Test successful authentication"""
        # Default admin password is "iccsadmin1969"
        session = manager.authenticate("admin", "iccsadmin1969")

        assert session is not None
        assert session.username == "admin"
        assert session.role == UserRole.ADMIN

    def test_authenticate_wrong_password(self, manager):
        """Test authentication with wrong password"""
        session = manager.authenticate("admin", "wrongpassword")

        assert session is None

    def test_authenticate_nonexistent_user(self, manager):
        """Test authentication with nonexistent user"""
        session = manager.authenticate("nonexistent", "password")

        assert session is None

    def test_authenticate_disabled_user(self, manager):
        """Test authentication of disabled user"""
        manager.create_user("disabled", "pass", UserRole.OPERATOR)
        manager.users["disabled"].enabled = False

        session = manager.authenticate("disabled", "pass")

        assert session is None

    def test_account_lockout_after_failed_attempts(self, manager):
        """Test account lockout after max failed attempts"""
        manager.create_user("testuser", "correctpass", UserRole.OPERATOR)

        # Make max_failed_attempts wrong attempts
        for _ in range(3):
            manager.authenticate("testuser", "wrongpass")

        # Account should be locked
        session = manager.authenticate("testuser", "correctpass")

        assert session is None
        assert manager.users["testuser"].locked_until is not None

    def test_lockout_expires(self, manager):
        """Test account lockout expires"""
        manager.lockout_duration = 0  # Immediate expiry for testing
        manager.create_user("testuser", "correctpass", UserRole.OPERATOR)

        # Lock the account
        for _ in range(3):
            manager.authenticate("testuser", "wrongpass")

        # Wait a moment for lockout to expire
        time.sleep(0.1)

        # Should be able to login now
        session = manager.authenticate("testuser", "correctpass")

        assert session is not None

    # =========================================================================
    # SESSION MANAGEMENT TESTS
    # =========================================================================

    def test_validate_session_valid(self, manager):
        """Test validating a valid session"""
        session = manager.authenticate("admin", "iccsadmin1969")

        validated = manager.validate_session(session.session_id)

        assert validated is not None
        assert validated.username == "admin"

    def test_validate_session_invalid(self, manager):
        """Test validating an invalid session"""
        validated = manager.validate_session("invalid_session_id")

        assert validated is None

    def test_validate_session_expired(self, manager):
        """Test validating an expired session"""
        session = manager.authenticate("admin", "iccsadmin1969")

        # Manually expire the session
        manager.sessions[session.session_id].last_activity = (
            datetime.now() - timedelta(hours=2)
        )

        validated = manager.validate_session(session.session_id)

        assert validated is None

    def test_validate_session_updates_activity(self, manager):
        """Test that validating session updates last_activity"""
        session = manager.authenticate("admin", "iccsadmin1969")
        old_activity = manager.sessions[session.session_id].last_activity

        time.sleep(0.01)
        manager.validate_session(session.session_id)

        new_activity = manager.sessions[session.session_id].last_activity
        assert new_activity > old_activity

    def test_logout(self, manager):
        """Test logging out"""
        session = manager.authenticate("admin", "iccsadmin1969")

        success = manager.logout(session.session_id)

        assert success is True
        assert session.session_id not in manager.sessions

    def test_logout_invalid_session(self, manager):
        """Test logging out invalid session"""
        success = manager.logout("invalid_session_id")

        assert success is False

    def test_get_active_sessions(self, manager):
        """Test getting active sessions"""
        manager.authenticate("admin", "iccsadmin1969")
        manager.authenticate("operator", "operator")

        active = manager.get_active_sessions()

        assert len(active) >= 2

    def test_cleanup_expired_sessions(self, manager):
        """Test cleaning up expired sessions"""
        session = manager.authenticate("admin", "iccsadmin1969")

        # Manually expire the session
        manager.sessions[session.session_id].last_activity = (
            datetime.now() - timedelta(hours=2)
        )

        manager.cleanup_expired_sessions()

        assert session.session_id not in manager.sessions

    # =========================================================================
    # PERMISSION TESTS
    # =========================================================================

    def test_has_permission_true(self, manager):
        """Test has_permission returns True for valid permission"""
        session = manager.authenticate("admin", "iccsadmin1969")

        result = manager.has_permission(session.session_id, Permission.MANAGE_USERS)

        assert result is True

    def test_has_permission_false(self, manager):
        """Test has_permission returns False for invalid permission"""
        session = manager.authenticate("guest", "guest")

        result = manager.has_permission(session.session_id, Permission.MANAGE_USERS)

        assert result is False

    def test_has_permission_invalid_session(self, manager):
        """Test has_permission returns False for invalid session"""
        result = manager.has_permission("invalid", Permission.VIEW_DATA)

        assert result is False

    def test_require_permission_success(self, manager):
        """Test require_permission passes for valid permission"""
        session = manager.authenticate("admin", "iccsadmin1969")

        result = manager.require_permission(session.session_id, Permission.MANAGE_USERS)

        assert result.username == "admin"

    def test_require_permission_failure(self, manager):
        """Test require_permission raises for invalid permission"""
        session = manager.authenticate("guest", "guest")

        with pytest.raises(PermissionError):
            manager.require_permission(session.session_id, Permission.MANAGE_USERS)

    def test_require_permission_invalid_session(self, manager):
        """Test require_permission raises for invalid session"""
        with pytest.raises(PermissionError):
            manager.require_permission("invalid", Permission.VIEW_DATA)

    # =========================================================================
    # ELECTRONIC SIGNATURE TESTS (21 CFR Part 11)
    # =========================================================================

    def test_create_electronic_signature(self, manager):
        """Test creating an electronic signature"""
        session = manager.authenticate("admin", "iccsadmin1969")

        signature = manager.create_electronic_signature(
            session_id=session.session_id,
            password="iccsadmin1969",
            action_type="config_change",
            action_description="Modified safety settings",
            reason="Required for new process"
        )

        assert signature is not None
        assert signature.username == "admin"
        assert signature.action_type == "config_change"
        assert signature.password_verified is True
        assert signature.reason == "Required for new process"

    def test_electronic_signature_wrong_password(self, manager):
        """Test electronic signature with wrong password"""
        session = manager.authenticate("admin", "iccsadmin1969")

        signature = manager.create_electronic_signature(
            session_id=session.session_id,
            password="wrongpassword",
            action_type="config_change",
            action_description="Test",
            reason="Test"
        )

        assert signature is None

    def test_electronic_signature_invalid_session(self, manager):
        """Test electronic signature with invalid session"""
        signature = manager.create_electronic_signature(
            session_id="invalid",
            password="password",
            action_type="config_change",
            action_description="Test",
            reason="Test"
        )

        assert signature is None

    def test_electronic_signature_to_dict(self):
        """Test electronic signature serialization"""
        signature = ElectronicSignature(
            signature_id="sig123",
            username="admin",
            timestamp="2025-01-15T10:30:00",
            action_type="config_change",
            action_description="Test change",
            reason="Testing",
            password_verified=True,
            session_id="session123",
            source_ip="127.0.0.1"
        )

        d = signature.to_dict()

        assert d['signature_id'] == "sig123"
        assert d['password_verified'] is True

    # =========================================================================
    # PERSISTENCE TESTS
    # =========================================================================

    def test_users_persist(self, data_dir):
        """Test that users persist across restarts"""
        # Create first manager and add user
        manager1 = UserSessionManager(data_dir)
        manager1.create_user("persisttest", "pass", UserRole.OPERATOR)

        # Create second manager (simulating restart)
        manager2 = UserSessionManager(data_dir)

        assert "persisttest" in manager2.users

    def test_delete_user_invalidates_sessions(self, manager):
        """Test deleting user invalidates their sessions"""
        manager.create_user("testuser", "pass", UserRole.OPERATOR)
        session = manager.authenticate("testuser", "pass")

        manager.delete_user("testuser")

        assert session.session_id not in manager.sessions
