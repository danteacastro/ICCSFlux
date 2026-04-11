#!/usr/bin/env python3
"""
User Session Management for NISystem

Provides user authentication and session management for:
- Critical action authorization (21 CFR Part 11 compliance)
- User attribution for audit trail
- Role-based access control
- Session timeout handling

Features:
- Simple password-based authentication (upgradeable to SSO/LDAP)
- Role-based permissions (operator, engineer, admin)
- Session timeout with configurable duration
- Electronic signature support for critical actions
"""

import json
import hashlib
import os
import secrets
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
import bcrypt

try:
    from .audit_trail import AuditEventType
except ImportError:
    try:
        from audit_trail import AuditEventType
    except ImportError:
        AuditEventType = None

logger = logging.getLogger('UserSession')


class SessionState(Enum):
    """Session state for inactivity lock (NIST 800-171 AC.L2-3.1.10).

    ACTIVE: Full access per role permissions.
    LOCKED: UI locked due to inactivity. Read-only data still flows.
            User must re-authenticate to unlock. No backend processes affected.
    """
    ACTIVE = "active"
    LOCKED = "locked"


class UserRole(Enum):
    """User roles with hierarchical permissions"""
    GUEST = "guest"             # Read-only access, monitoring only
    OPERATOR = "operator"       # Day-to-day operations, acknowledge alarms, control outputs
    SUPERVISOR = "supervisor"   # Configure channels, alarms, safety settings, projects
    ADMIN = "admin"             # Full access including user management


class Permission(Enum):
    """Granular permissions for access control"""
    # View permissions
    VIEW_DATA = "view.data"
    VIEW_ALARMS = "view.alarms"
    VIEW_CONFIG = "view.config"
    VIEW_AUDIT = "view.audit"

    # Operator permissions
    ACK_ALARMS = "alarm.acknowledge"
    RESET_ALARMS = "alarm.reset"
    SHELVE_ALARMS = "alarm.shelve"
    START_RECORDING = "recording.start"
    STOP_RECORDING = "recording.stop"
    START_ACQUISITION = "acquisition.start"
    STOP_ACQUISITION = "acquisition.stop"
    CONTROL_OUTPUTS = "output.control"

    # Engineer permissions
    MODIFY_CHANNELS = "config.channels.modify"
    MODIFY_ALARMS = "config.alarms.modify"
    MODIFY_SAFETY = "config.safety.modify"
    MODIFY_RECORDING = "config.recording.modify"
    LOAD_PROJECT = "project.load"
    SAVE_PROJECT = "project.save"

    # Admin permissions
    MANAGE_USERS = "users.manage"
    MODIFY_SYSTEM = "config.system.modify"
    EXPORT_AUDIT = "audit.export"
    BYPASS_SAFETY_LOCK = "safety.bypass"
    TRIGGER_SAFE_STATE = "system.safe_state"


# Permissions allowed even when session is LOCKED (read-only monitoring).
# Session lock must NEVER interrupt acquisition, recording, scripts, or safety.
LOCKED_SESSION_PERMISSIONS: Set[Permission] = {
    Permission.VIEW_DATA,
    Permission.VIEW_ALARMS,
    Permission.VIEW_CONFIG,
}

# Role to permissions mapping (hierarchical)
ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.GUEST: {
        Permission.VIEW_DATA,
        Permission.VIEW_ALARMS,
    },
    UserRole.OPERATOR: {
        Permission.VIEW_DATA,
        Permission.VIEW_ALARMS,
        Permission.VIEW_CONFIG,
        Permission.ACK_ALARMS,
        Permission.RESET_ALARMS,
        Permission.SHELVE_ALARMS,
        Permission.START_RECORDING,
        Permission.STOP_RECORDING,
        Permission.START_ACQUISITION,
        Permission.STOP_ACQUISITION,
        Permission.CONTROL_OUTPUTS,
        Permission.TRIGGER_SAFE_STATE,
    },
    UserRole.SUPERVISOR: {
        Permission.VIEW_DATA,
        Permission.VIEW_ALARMS,
        Permission.VIEW_CONFIG,
        Permission.VIEW_AUDIT,
        Permission.ACK_ALARMS,
        Permission.RESET_ALARMS,
        Permission.SHELVE_ALARMS,
        Permission.START_RECORDING,
        Permission.STOP_RECORDING,
        Permission.START_ACQUISITION,
        Permission.STOP_ACQUISITION,
        Permission.CONTROL_OUTPUTS,
        Permission.MODIFY_CHANNELS,
        Permission.MODIFY_ALARMS,
        Permission.MODIFY_SAFETY,
        Permission.MODIFY_RECORDING,
        Permission.LOAD_PROJECT,
        Permission.SAVE_PROJECT,
        Permission.EXPORT_AUDIT,
        Permission.TRIGGER_SAFE_STATE,
    },
    UserRole.ADMIN: set(Permission),  # All permissions
}


@dataclass
class User:
    """User account information"""
    username: str
    password_hash: str
    role: UserRole
    display_name: str = ""
    email: str = ""
    enabled: bool = True
    created_at: str = ""
    last_login: str = ""
    failed_attempts: int = 0
    locked_until: Optional[str] = None
    must_change_password: bool = False
    custom_permissions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['role'] = self.role.value
        return d

    @staticmethod
    def from_dict(d: dict) -> 'User':
        d = d.copy()
        role_str = d.get('role', 'operator')
        # Handle legacy role names
        role_map = {
            'viewer': 'guest',
            'engineer': 'supervisor',
        }
        role_str = role_map.get(role_str, role_str)
        try:
            d['role'] = UserRole(role_str)
        except ValueError:
            d['role'] = UserRole.OPERATOR  # Fallback
        return User(**d)


@dataclass
class Session:
    """Active user session"""
    session_id: str
    username: str
    role: UserRole
    created_at: datetime
    last_activity: datetime
    source_ip: str
    user_agent: str = ""
    state: SessionState = SessionState.ACTIVE

    def is_expired(self, timeout_minutes: int = 0) -> bool:
        """Check if session has expired. timeout_minutes=0 means never expires."""
        if timeout_minutes <= 0:
            return False
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)

    def should_lock(self, timeout_minutes: int = 0) -> bool:
        """Check if session should be locked due to inactivity."""
        if timeout_minutes <= 0:
            return False
        if self.state != SessionState.ACTIVE:
            return False
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)


@dataclass
class ElectronicSignature:
    """Electronic signature for critical actions (21 CFR Part 11)"""
    signature_id: str
    username: str
    timestamp: str
    action_type: str
    action_description: str
    reason: str
    password_verified: bool
    session_id: str
    source_ip: str

    def to_dict(self) -> dict:
        return asdict(self)


class UserSessionManager:
    """
    Manages user authentication, sessions, and permissions.

    Provides:
    - User account management
    - Session creation and validation
    - Permission checking
    - Electronic signature verification
    """

    def __init__(self,
                 data_dir: Path,
                 session_timeout_minutes: int = 0,
                 max_failed_attempts: int = 5,
                 lockout_duration_minutes: int = 15,
                 max_concurrent_sessions: int = 10,
                 audit_trail=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.session_timeout = session_timeout_minutes
        self.max_failed_attempts = max_failed_attempts
        self.lockout_duration = lockout_duration_minutes
        self.max_concurrent_sessions = max_concurrent_sessions
        self._audit_trail = audit_trail

        self.lock = threading.RLock()
        self.users: Dict[str, User] = {}
        self.sessions: Dict[str, Session] = {}

        self._load_users()
        self._ensure_default_users()

    def _load_users(self):
        """Load users from disk"""
        users_file = self.data_dir / 'users.json'
        if users_file.exists():
            try:
                with open(users_file, 'r') as f:
                    data = json.load(f)
                    for username, user_data in data.items():
                        self.users[username] = User.from_dict(user_data)
                logger.info(f"Loaded {len(self.users)} users")
            except Exception as e:
                logger.error(f"Error loading users: {e}")

    def _save_users(self):
        """Save users to disk"""
        users_file = self.data_dir / 'users.json'
        try:
            data = {u: user.to_dict() for u, user in self.users.items()}
            with open(users_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving users: {e}")

    def _ensure_default_users(self):
        """Create default users if none exist.

        Default accounts are created with random passwords. The initial
        admin password is written to data/initial_admin_password.txt
        (chmod 600) for first-time setup. All other accounts get random
        passwords that must be reset by an admin.
        """
        if not self.users:
            # Generate random passwords for all default accounts
            admin_pw = secrets.token_urlsafe(16)
            default_accounts = [
                ("admin", admin_pw, UserRole.ADMIN, "Administrator"),
                ("supervisor", secrets.token_urlsafe(16), UserRole.SUPERVISOR, "Supervisor"),
                ("operator", secrets.token_urlsafe(16), UserRole.OPERATOR, "Operator"),
                ("guest", secrets.token_urlsafe(12), UserRole.GUEST, "Guest"),
            ]
            for username, password, role, display_name in default_accounts:
                self.create_user(
                    username=username,
                    password=password,
                    role=role,
                    display_name=display_name
                )

            # Write admin password to file for first-time setup
            pw_file = Path('data') / 'initial_admin_password.txt'
            try:
                pw_file.parent.mkdir(parents=True, exist_ok=True)
                pw_file.write_text(
                    f"Initial admin credentials (change after first login):\n"
                    f"  Username: admin\n"
                    f"  Password: {admin_pw}\n",
                    encoding='utf-8'
                )
                # Restrict file permissions (owner read/write only)
                try:
                    pw_file.chmod(0o600)
                except OSError:
                    pass  # Windows may not support chmod; NTFS ACLs apply
                logger.info(f"Initial admin password written to {pw_file}")
            except Exception as e:
                # Fall back to logging if file write fails
                logger.warning(f"Could not write password file: {e}")
                logger.info(f"Initial admin password: {admin_pw}")

            logger.info("Created default users with random passwords")

    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False

    def create_user(self,
                    username: str,
                    password: str,
                    role: UserRole,
                    display_name: str = "",
                    email: str = "") -> Optional[User]:
        """Create a new user account"""
        with self.lock:
            if username in self.users:
                logger.warning(f"User {username} already exists")
                return None

            user = User(
                username=username,
                password_hash=self._hash_password(password),
                role=role,
                display_name=display_name or username,
                email=email,
                created_at=datetime.now().isoformat()
            )

            self.users[username] = user
            self._save_users()
            logger.info(f"Created user: {username} (role: {role.value})")
            return user

    def update_user(self, username: str, **kwargs) -> bool:
        """Update user properties"""
        with self.lock:
            user = self.users.get(username)
            if not user:
                return False

            for key, value in kwargs.items():
                if key == 'password':
                    user.password_hash = self._hash_password(value)
                elif key == 'role':
                    user.role = UserRole(value) if isinstance(value, str) else value
                elif hasattr(user, key):
                    setattr(user, key, value)

            self._save_users()
            return True

    def delete_user(self, username: str) -> bool:
        """Delete a user account"""
        with self.lock:
            if username not in self.users:
                return False

            del self.users[username]

            # Invalidate any active sessions
            for session_id in list(self.sessions.keys()):
                if self.sessions[session_id].username == username:
                    del self.sessions[session_id]

            self._save_users()
            logger.info(f"Deleted user: {username}")
            return True

    def authenticate(self,
                     username: str,
                     password: str,
                     source_ip: str = "local",
                     user_agent: str = "") -> Optional[Session]:
        """
        Authenticate user and create session.

        Returns Session if successful, None if authentication fails.
        """
        with self.lock:
            user = self.users.get(username)

            if not user:
                logger.warning(f"Authentication failed: user {username} not found")
                return None

            if not user.enabled:
                logger.warning(f"Authentication failed: user {username} is disabled")
                return None

            # Check account lockout
            if user.locked_until:
                lockout_time = datetime.fromisoformat(user.locked_until)
                if datetime.now() < lockout_time:
                    logger.warning(f"Authentication failed: user {username} is locked")
                    return None
                else:
                    # Lockout expired
                    user.locked_until = None
                    user.failed_attempts = 0

            # Verify password
            if not self._verify_password(password, user.password_hash):
                user.failed_attempts += 1
                if user.failed_attempts >= self.max_failed_attempts:
                    user.locked_until = (
                        datetime.now() + timedelta(minutes=self.lockout_duration)
                    ).isoformat()
                    logger.warning(f"User {username} locked due to failed attempts")
                self._save_users()
                logger.warning(f"Authentication failed: incorrect password for {username}")
                if self._audit_trail:
                    self._audit_trail.log_event(
                        event_type=AuditEventType.USER_LOGIN_FAILED,
                        user=username,
                        description=f"Login failed for {username}: incorrect password",
                        source_ip=source_ip,
                    )
                return None

            # Successful authentication
            user.failed_attempts = 0
            user.last_login = datetime.now().isoformat()
            self._save_users()

            # Enforce concurrent session limit (NIST 800-171 resource limit)
            if len(self.sessions) >= self.max_concurrent_sessions:
                logger.warning(f"Concurrent session limit reached ({self.max_concurrent_sessions}), "
                               f"rejecting login for {username}")
                return None

            # Create session
            session = Session(
                session_id=secrets.token_urlsafe(32),
                username=username,
                role=user.role,
                created_at=datetime.now(),
                last_activity=datetime.now(),
                source_ip=source_ip,
                user_agent=user_agent
            )

            self.sessions[session.session_id] = session
            logger.info(f"User {username} authenticated from {source_ip}")

            if self._audit_trail:
                self._audit_trail.log_event(
                    event_type=AuditEventType.USER_LOGIN,
                    user=username,
                    description=f"User {username} logged in",
                    details={'role': user.role.value},
                    user_role=user.role.value,
                    source_ip=source_ip,
                )

            return session

    def validate_session(self, session_id: str) -> Optional[Session]:
        """Validate session and update activity timestamp.

        Locked sessions are still valid (for read-only access) but
        do not update last_activity. This preserves the session for
        re-authentication without affecting backend processes.
        """
        with self.lock:
            session = self.sessions.get(session_id)

            if not session:
                return None

            # Locked sessions remain valid but don't update activity
            if session.state == SessionState.LOCKED:
                return session

            if session.is_expired(self.session_timeout):
                # Lock instead of delete — backend processes continue
                session.state = SessionState.LOCKED
                logger.info(f"Session locked for user {session.username} (inactivity timeout)")
                return session

            # Update activity (only for ACTIVE sessions)
            session.last_activity = datetime.now()
            return session

    def logout(self, session_id: str) -> bool:
        """Invalidate a session"""
        with self.lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                del self.sessions[session_id]
                logger.info(f"User {session.username} logged out")
                if self._audit_trail:
                    self._audit_trail.log_event(
                        event_type=AuditEventType.USER_LOGOUT,
                        user=session.username,
                        description=f"User {session.username} logged out",
                        user_role=session.role.value,
                        source_ip=session.source_ip,
                        session_id=session_id,
                    )
                return True
            return False

    def has_permission(self, session_id: str, permission: Permission) -> bool:
        """Check if session has a specific permission.

        Locked sessions only allow LOCKED_SESSION_PERMISSIONS (view-only).
        This ensures session lock never interrupts backend processes.
        """
        session = self.validate_session(session_id)
        if not session:
            return False

        # Locked sessions: only read-only permissions allowed
        if session.state == SessionState.LOCKED:
            return permission in LOCKED_SESSION_PERMISSIONS

        role_permissions = ROLE_PERMISSIONS.get(session.role, set())
        return permission in role_permissions

    def require_permission(self, session_id: str, permission: Permission) -> Session:
        """
        Check permission and return session, or raise exception.

        Use this for permission checking with clear error messages.
        """
        session = self.validate_session(session_id)
        if not session:
            raise PermissionError("Invalid or expired session")

        if not self.has_permission(session_id, permission):
            raise PermissionError(
                f"User {session.username} does not have permission: {permission.value}"
            )

        return session

    def create_electronic_signature(self,
                                    session_id: str,
                                    password: str,
                                    action_type: str,
                                    action_description: str,
                                    reason: str) -> Optional[ElectronicSignature]:
        """
        Create an electronic signature for a critical action.

        This re-verifies the user's password to ensure they are
        present and authorizing the action (21 CFR Part 11 requirement).
        """
        session = self.validate_session(session_id)
        if not session:
            return None

        user = self.users.get(session.username)
        if not user:
            return None

        # Re-verify password for signature
        if not self._verify_password(password, user.password_hash):
            logger.warning(f"Electronic signature failed: password verification failed for {session.username}")
            if self._audit_trail:
                self._audit_trail.log_event(
                    event_type=AuditEventType.ELECTRONIC_SIGNATURE_FAILED,
                    user=session.username,
                    description=f"Electronic signature FAILED: {action_type} - password verification failed",
                    details={'action_type': action_type, 'action_description': action_description},
                    user_role=session.role.value,
                    source_ip=session.source_ip,
                    session_id=session_id,
                )
            return None

        signature = ElectronicSignature(
            signature_id=secrets.token_urlsafe(16),
            username=session.username,
            timestamp=datetime.now().isoformat(),
            action_type=action_type,
            action_description=action_description,
            reason=reason,
            password_verified=True,
            session_id=session_id,
            source_ip=session.source_ip
        )

        logger.info(f"Electronic signature created by {session.username} for: {action_type}")

        if self._audit_trail:
            self._audit_trail.log_event(
                event_type=AuditEventType.ELECTRONIC_SIGNATURE,
                user=session.username,
                description=f"Electronic signature: {action_type} - {action_description}",
                details={
                    'signature_id': signature.signature_id,
                    'action_type': action_type,
                    'action_description': action_description,
                    'reason': reason,
                },
                reason=reason,
                user_role=session.role.value,
                source_ip=session.source_ip,
                session_id=session_id,
            )

        return signature

    def get_active_sessions(self) -> List[dict]:
        """Get list of all sessions (active and locked) for admin"""
        with self.lock:
            result = []
            for session in self.sessions.values():
                result.append({
                    'session_id': session.session_id[:8] + '...',  # Partial ID for security
                    'username': session.username,
                    'role': session.role.value,
                    'state': session.state.value,
                    'created_at': session.created_at.isoformat(),
                    'last_activity': session.last_activity.isoformat(),
                    'source_ip': session.source_ip
                })
            return result

    def lock_expired_sessions(self) -> List[str]:
        """Lock sessions that have exceeded the inactivity timeout.

        Returns list of session_ids that were locked (for MQTT notification).
        Does NOT delete sessions or affect any backend processes.
        """
        locked_ids = []
        with self.lock:
            for sid, session in self.sessions.items():
                if session.should_lock(self.session_timeout):
                    session.state = SessionState.LOCKED
                    locked_ids.append(sid)
                    logger.info(f"Session locked for user {session.username} (inactivity)")
                    if self._audit_trail:
                        self._audit_trail.log_event(
                            event_type=AuditEventType.USER_LOGOUT,
                            user=session.username,
                            description=f"Session locked for {session.username} (inactivity timeout)",
                            details={'reason': 'inactivity_timeout', 'session_state': 'locked'},
                            user_role=session.role.value,
                            source_ip=session.source_ip,
                            session_id=sid,
                        )
        return locked_ids

    def unlock_session(self, session_id: str, password: str) -> Optional[Session]:
        """Re-authenticate a locked session without creating a new one.

        Same session_id preserved — audit trail continuity maintained.
        Returns the unlocked session, or None if auth fails.
        """
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            if session.state != SessionState.LOCKED:
                # Already active, just return it
                session.last_activity = datetime.now()
                return session

            user = self.users.get(session.username)
            if not user:
                return None

            if not self._verify_password(password, user.password_hash):
                logger.warning(f"Unlock failed: incorrect password for {session.username}")
                if self._audit_trail:
                    self._audit_trail.log_event(
                        event_type=AuditEventType.USER_LOGIN_FAILED,
                        user=session.username,
                        description=f"Session unlock failed for {session.username}: incorrect password",
                        details={'reason': 'unlock_failed'},
                        source_ip=session.source_ip,
                        session_id=session_id,
                    )
                return None

            # Unlock: restore to ACTIVE, reset activity timer
            session.state = SessionState.ACTIVE
            session.last_activity = datetime.now()
            logger.info(f"Session unlocked for user {session.username}")

            if self._audit_trail:
                self._audit_trail.log_event(
                    event_type=AuditEventType.USER_LOGIN,
                    user=session.username,
                    description=f"Session unlocked for {session.username}",
                    details={'reason': 'session_unlock', 'session_state': 'active'},
                    user_role=session.role.value,
                    source_ip=session.source_ip,
                    session_id=session_id,
                )

            return session

    def cleanup_expired_sessions(self):
        """Remove long-expired sessions (locked for >24h).

        Normal inactivity uses lock_expired_sessions() instead.
        This only removes sessions abandoned for a full day.
        """
        with self.lock:
            stale = [
                sid for sid, session in self.sessions.items()
                if session.state == SessionState.LOCKED and
                datetime.now() - session.last_activity > timedelta(hours=24)
            ]
            for sid in stale:
                del self.sessions[sid]

            if stale:
                logger.info(f"Cleaned up {len(stale)} abandoned sessions")

    def get_user_info(self, username: str) -> Optional[dict]:
        """Get user info (without password hash)"""
        user = self.users.get(username)
        if not user:
            return None

        return {
            'username': user.username,
            'display_name': user.display_name,
            'email': user.email,
            'role': user.role.value,
            'enabled': user.enabled,
            'created_at': user.created_at,
            'last_login': user.last_login
        }

    def list_users(self) -> List[dict]:
        """List all users (for admin)"""
        return [self.get_user_info(u) for u in self.users.keys()]
