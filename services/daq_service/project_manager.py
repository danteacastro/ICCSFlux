#!/usr/bin/env python3
"""
Project Manager for NISystem

Provides project lifecycle management with:
- Auto-backup before save (IEC 61511 compliance)
- Schema validation on load
- Safety config locking during acquisition
- Audit trail integration
- Version control support

References:
- IEC 61511: Safety Instrumented Systems
- FDA 21 CFR Part 11: Electronic Records
- ALCOA+ Data Integrity Principles
"""

import json
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Support both package import and direct import
try:
    from .backup_logger import BackupLogger
    from .schema_migrations import migrate_project, SCHEMA_VERSIONS
except ImportError:
    from backup_logger import BackupLogger
    from schema_migrations import migrate_project, SCHEMA_VERSIONS

logger = logging.getLogger('ProjectManager')
class ProjectStatus(Enum):
    """Project load/save status"""
    SUCCESS = "success"
    ERROR = "error"
    VALIDATION_ERROR = "validation_error"
    LOCKED = "locked"
    BACKUP_FAILED = "backup_failed"
# Project schema definition for validation
PROJECT_SCHEMA = {
    "required_fields": ["type", "version"],
    "type_value": "nisystem-project",
    "valid_versions": ["1.0", "1.1", "2.0"],
    "optional_sections": [
        "channels", "system", "pages", "scripts", "alarms",
        "recording", "safety", "variables", "metadata"
    ],
    # Note: When channels is a dict, name comes from the key
    # When channels is a list, name is a required field in each object
    "channel_required_fields_list": ["name", "type"],  # For list format
    "channel_required_fields_dict": [],  # For dict format, name=key, type optional
    "channel_valid_types": [
        "analog_input", "analog_output", "digital_input", "digital_output",
        "thermocouple", "voltage", "current", "rtd", "counter", "virtual",
        "calculated", "modbus", "rest", "strain", "iepe", "resistance",
        "modbus_register", "modbus_coil"
    ]
}
@dataclass
class ValidationResult:
    """Result of schema validation"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)
@dataclass
class BackupInfo:
    """Information about a project backup"""
    backup_path: Path
    original_path: Path
    timestamp: datetime
    file_hash: str
    size_bytes: int
    reason: str  # "pre_save", "pre_load", "scheduled", "manual"

    def to_dict(self) -> dict:
        return {
            "backup_path": str(self.backup_path),
            "original_path": str(self.original_path),
            "timestamp": self.timestamp.isoformat(),
            "file_hash": self.file_hash,
            "size_bytes": self.size_bytes,
            "reason": self.reason
        }
class ProjectManager:
    """
    Manages project lifecycle with compliance features.

    Features:
    - Schema validation on load
    - Auto-backup before save
    - Safety config locking during acquisition
    - Audit trail integration
    - Backup retention policy
    """

    def __init__(self,
                 projects_dir: Path,
                 backup_dir: Optional[Path] = None,
                 max_backups: int = 10,
                 backup_on_save: bool = True,
                 validate_on_load: bool = True):
        """
        Initialize project manager.

        Args:
            projects_dir: Default directory for projects
            backup_dir: Directory for backups (default: projects_dir/backups)
            max_backups: Maximum number of backups to retain per project
            backup_on_save: Whether to auto-backup before save
            validate_on_load: Whether to validate schema on load
        """
        self.projects_dir = Path(projects_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else self.projects_dir / "backups"
        self.max_backups = max_backups
        self.backup_on_save = backup_on_save
        self.validate_on_load = validate_on_load

        # Safety lock state
        self._safety_locked = False
        self._lock_reason: Optional[str] = None

        # Audit trail reference (set externally)
        self.audit_trail = None

        # Current project state
        self.current_path: Optional[Path] = None
        self.current_data: Dict[str, Any] = {}
        self._original_hash: Optional[str] = None

        # Ensure directories exist
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Load backup manifest
        self.backup_manifest: List[BackupInfo] = []
        self._load_backup_manifest()

        # Initialize backup logger for human-readable changelog
        self.backup_logger = BackupLogger(self.backup_dir)

    def _load_backup_manifest(self):
        """Load backup manifest from disk"""
        manifest_path = self.backup_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r') as f:
                    data = json.load(f)
                    for entry in data.get("backups", []):
                        self.backup_manifest.append(BackupInfo(
                            backup_path=Path(entry["backup_path"]),
                            original_path=Path(entry["original_path"]),
                            timestamp=datetime.fromisoformat(entry["timestamp"]),
                            file_hash=entry["file_hash"],
                            size_bytes=entry["size_bytes"],
                            reason=entry["reason"]
                        ))
            except Exception as e:
                logger.warning(f"Failed to load backup manifest: {e}")

    def _save_backup_manifest(self):
        """Save backup manifest to disk"""
        manifest_path = self.backup_dir / "manifest.json"
        try:
            data = {
                "backups": [b.to_dict() for b in self.backup_manifest],
                "updated": datetime.now().isoformat()
            }
            with open(manifest_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save backup manifest: {e}")

    def _compute_file_hash(self, path: Path) -> str:
        """Compute SHA-256 hash of file"""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _compute_data_hash(self, data: Dict[str, Any]) -> str:
        """Compute hash of project data (for change detection)"""
        # Normalize by sorting keys and creating consistent JSON
        json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()

    # =========================================================================
    # SAFETY LOCKING
    # =========================================================================

    def lock_safety_config(self, reason: str = "Acquisition running"):
        """Lock safety configuration during acquisition (IEC 61511)"""
        self._safety_locked = True
        self._lock_reason = reason
        logger.info(f"Safety config locked: {reason}")

        if self.audit_trail:
            self.audit_trail.log_event(
                event_type="SAFETY_LOCKED",
                user="system",
                description=f"Safety configuration locked: {reason}",
                details={"reason": reason}
            )

    def unlock_safety_config(self):
        """Unlock safety configuration after acquisition stops"""
        if self._safety_locked:
            logger.info("Safety config unlocked")

            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type="SAFETY_UNLOCKED",
                    user="system",
                    description="Safety configuration unlocked"
                )

            self._safety_locked = False
            self._lock_reason = None

    def is_safety_locked(self) -> Tuple[bool, Optional[str]]:
        """Check if safety config is locked"""
        return self._safety_locked, self._lock_reason

    def check_safety_modification(self, field_name: str) -> Tuple[bool, str]:
        """
        Check if a safety-related field can be modified.

        Returns:
            (allowed, reason) tuple
        """
        safety_fields = {
            "safety_action", "safety_interlock", "safety_actions",
            "failsafe_value", "trip_setpoint", "reset_setpoint",
            "emergency_stop", "interlock_bypass"
        }

        if field_name in safety_fields and self._safety_locked:
            return False, f"Cannot modify {field_name}: {self._lock_reason}"

        return True, ""

    # =========================================================================
    # SCHEMA VALIDATION
    # =========================================================================

    def validate_project(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate project data against schema.

        Args:
            data: Project data to validate

        Returns:
            ValidationResult with any errors/warnings
        """
        result = ValidationResult(valid=True)

        # Check required fields
        for field in PROJECT_SCHEMA["required_fields"]:
            if field not in data:
                result.add_error(f"Missing required field: {field}")

        # Check project type
        if data.get("type") != PROJECT_SCHEMA["type_value"]:
            result.add_error(f"Invalid project type: {data.get('type')} (expected: {PROJECT_SCHEMA['type_value']})")

        # Check version
        version = data.get("version", "")
        if version not in PROJECT_SCHEMA["valid_versions"]:
            result.add_warning(f"Unknown project version: {version}")

        # Validate channels if present
        if "channels" in data:
            channels = data["channels"]
            if not isinstance(channels, (list, dict)):
                result.add_error("'channels' must be a list or dict")
            else:
                # Handle both list format (legacy) and dict format (current)
                is_dict_format = isinstance(channels, dict)

                if is_dict_format:
                    # Dict format: key is channel name, value is config
                    items = [(name, ch) for name, ch in channels.items()]
                else:
                    # List format: each item has 'name' and 'type' fields
                    items = [(i, ch) for i, ch in enumerate(channels)]

                for key, ch in items:
                    if not isinstance(ch, dict):
                        result.add_error(f"Channel {key}: must be a dict")
                        continue

                    # Check required channel fields based on format
                    if is_dict_format:
                        # Dict format: name comes from key, type field can be 'channel_type' or 'type'
                        required_fields = PROJECT_SCHEMA["channel_required_fields_dict"]
                    else:
                        # List format: requires 'name' and 'type' inside each object
                        required_fields = PROJECT_SCHEMA["channel_required_fields_list"]

                    for field in required_fields:
                        if field not in ch:
                            ch_name = key if is_dict_format else ch.get('name', key)
                            result.add_error(f"Channel {ch_name}: missing required field '{field}'")

                    # Check channel type - accept 'type' or 'channel_type'
                    ch_type = ch.get("type") or ch.get("channel_type", "")
                    if ch_type and ch_type not in PROJECT_SCHEMA["channel_valid_types"]:
                        ch_name = key if is_dict_format else ch.get('name', key)
                        result.add_warning(f"Channel {ch_name}: unknown type '{ch_type}'")

                    # Validate safety config consistency
                    if ch.get("safety_action"):
                        if not ch.get("high_alarm") and not ch.get("low_alarm") and not ch.get("hihi_limit") and not ch.get("hi_limit"):
                            ch_name = key if is_dict_format else ch.get('name', key)
                            result.add_warning(
                                f"Channel {ch_name}: has safety_action but no alarm limits configured"
                            )

        # Validate safety actions if present
        if "safety_actions" in data:
            actions = data["safety_actions"]
            if not isinstance(actions, dict):
                result.add_error("'safety_actions' must be a dict")
            else:
                for name, action in actions.items():
                    if not isinstance(action, dict):
                        result.add_error(f"Safety action '{name}': must be a dict")
                        continue

                    # Check for required action fields
                    if "outputs" not in action:
                        result.add_warning(f"Safety action '{name}': no outputs defined")

        # Validate pages (layout) if present
        if "pages" in data:
            pages = data["pages"]
            if not isinstance(pages, dict):
                result.add_error("'pages' must be a dict")

        return result

    # =========================================================================
    # BACKUP MANAGEMENT
    # =========================================================================

    def create_backup(self,
                     project_path: Path,
                     reason: str = "manual",
                     user: str = "system",
                     new_data: Optional[Dict[str, Any]] = None) -> Optional[BackupInfo]:
        """
        Create a backup of a project file with detailed changelog.

        Args:
            project_path: Path to project file
            reason: Reason for backup (pre_save, pre_load, scheduled, manual)
            user: User who triggered the backup
            new_data: New project data (for changelog diff, optional)

        Returns:
            BackupInfo if successful, None otherwise
        """
        if not project_path.exists():
            logger.warning(f"Cannot backup non-existent file: {project_path}")
            return None

        try:
            # Load current file data for diffing (this is what we're backing up)
            with open(project_path, 'r') as f:
                current_data = json.load(f)

            # Get previous data for diff (from cache or last backup)
            old_data = self.backup_logger.get_last_data(project_path)
            old_hash = ""

            if old_data is None and self.backup_manifest:
                # Try to load from most recent backup
                project_backups = [b for b in self.backup_manifest
                                  if b.original_path == project_path]
                if project_backups:
                    project_backups.sort(key=lambda b: b.timestamp, reverse=True)
                    last_backup = project_backups[0]
                    if last_backup.backup_path.exists():
                        try:
                            with open(last_backup.backup_path, 'r') as f:
                                old_data = json.load(f)
                            old_hash = last_backup.file_hash
                        except Exception as e:
                            logger.debug(f"Could not read previous backup for comparison: {e}")

            # Generate backup filename with timestamp
            timestamp = datetime.now()
            backup_name = f"{project_path.stem}_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = self.backup_dir / backup_name

            # Copy file
            shutil.copy2(project_path, backup_path)

            # Create backup info
            backup_info = BackupInfo(
                backup_path=backup_path,
                original_path=project_path,
                timestamp=timestamp,
                file_hash=self._compute_file_hash(backup_path),
                size_bytes=backup_path.stat().st_size,
                reason=reason
            )

            self.backup_manifest.append(backup_info)
            self._save_backup_manifest()

            # Count backups for this project
            project_backups = [b for b in self.backup_manifest
                              if b.original_path == project_path]
            backup_count = len(project_backups)

            # Write to human-readable changelog
            self.backup_logger.log_backup(
                project_name=project_path.stem,
                project_path=project_path,
                backup_path=backup_path,
                new_data=new_data or current_data,
                old_data=old_data,
                user=user,
                reason=reason,
                new_hash=backup_info.file_hash,
                old_hash=old_hash,
                backup_count=backup_count,
                max_backups=self.max_backups
            )

            # Enforce retention policy
            removed_count = self._cleanup_old_backups(project_path)

            logger.info(f"Created backup: {backup_path}")

            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type="PROJECT_BACKUP",
                    user=user,
                    description=f"Project backup created: {backup_name}",
                    details={
                        "original_path": str(project_path),
                        "backup_path": str(backup_path),
                        "reason": reason,
                        "file_hash": backup_info.file_hash
                    }
                )

            return backup_info

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            self.backup_logger.log_failure(
                project_name=project_path.stem,
                operation="BACKUP",
                user=user,
                error=str(e)
            )
            return None

    def _cleanup_old_backups(self, project_path: Path) -> int:
        """Remove old backups exceeding retention limit.

        Returns:
            Number of backups removed
        """
        # Find backups for this project
        project_backups = [
            b for b in self.backup_manifest
            if b.original_path == project_path
        ]

        # Sort by timestamp, oldest first
        project_backups.sort(key=lambda b: b.timestamp)

        # Remove excess backups
        removed_count = 0
        while len(project_backups) > self.max_backups:
            old_backup = project_backups.pop(0)
            try:
                if old_backup.backup_path.exists():
                    old_backup.backup_path.unlink()
                self.backup_manifest.remove(old_backup)
                removed_count += 1
                logger.info(f"Removed old backup: {old_backup.backup_path}")
            except Exception as e:
                logger.warning(f"Failed to remove old backup: {e}")

        self._save_backup_manifest()

        # Log cleanup if any backups were removed
        if removed_count > 0:
            remaining = len([b for b in self.backup_manifest if b.original_path == project_path])
            self.backup_logger.log_cleanup(
                project_name=project_path.stem,
                removed_count=removed_count,
                remaining_count=remaining,
                max_backups=self.max_backups
            )

        return removed_count

    def list_backups(self, project_path: Optional[Path] = None) -> List[BackupInfo]:
        """List available backups, optionally filtered by project"""
        if project_path:
            return [b for b in self.backup_manifest if b.original_path == project_path]
        return list(self.backup_manifest)

    def restore_backup(self, backup_path: Path,
                       user: str = "system",
                       reason: str = "") -> Tuple[bool, str]:
        """
        Restore a project from backup.

        Args:
            backup_path: Path to backup file
            user: User who triggered the restore
            reason: Reason for restore (optional)

        Returns:
            (success, message) tuple
        """
        # Find backup info
        backup_info = None
        for b in self.backup_manifest:
            if b.backup_path == backup_path:
                backup_info = b
                break

        if not backup_info:
            return False, f"Backup not found in manifest: {backup_path}"

        if not backup_path.exists():
            return False, f"Backup file not found: {backup_path}"

        try:
            # Verify backup integrity
            current_hash = self._compute_file_hash(backup_path)
            if current_hash != backup_info.file_hash:
                return False, "Backup file integrity check failed (hash mismatch)"

            # Create backup of current file before restore
            if backup_info.original_path.exists():
                self.create_backup(backup_info.original_path, reason="pre_restore", user=user)

            # Restore
            shutil.copy2(backup_path, backup_info.original_path)

            logger.info(f"Restored backup: {backup_path} -> {backup_info.original_path}")

            # Log to human-readable backup log
            self.backup_logger.log_restore(
                project_name=backup_info.original_path.stem,
                backup_timestamp=backup_info.timestamp,
                user=user,
                reason=reason
            )

            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type="PROJECT_RESTORE",
                    user=user,
                    description=f"Project restored from backup",
                    details={
                        "backup_path": str(backup_path),
                        "restored_to": str(backup_info.original_path),
                        "backup_timestamp": backup_info.timestamp.isoformat(),
                        "reason": reason
                    }
                )

            return True, f"Restored from backup: {backup_info.timestamp.isoformat()}"

        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            self.backup_logger.log_failure(
                project_name=backup_path.stem,
                operation="RESTORE",
                user=user,
                error=str(e)
            )
            return False, str(e)

    # =========================================================================
    # PROJECT LOAD/SAVE
    # =========================================================================

    def load_project(self,
                    project_path: Path,
                    user: str = "system") -> Tuple[ProjectStatus, Dict[str, Any], str]:
        """
        Load a project with validation.

        Args:
            project_path: Path to project file
            user: Username for audit

        Returns:
            (status, project_data, message) tuple
        """
        if not project_path.exists():
            return ProjectStatus.ERROR, {}, f"Project not found: {project_path}"

        try:
            with open(project_path, 'r') as f:
                data = json.load(f)

            # Auto-migrate older schema versions
            current_version = data.get("version", "1.0")
            latest_version = SCHEMA_VERSIONS[-1]
            if current_version != latest_version:
                data, migrations = migrate_project(data, latest_version)
                if migrations:
                    logger.info(f"Project schema migrated: {' -> '.join(migrations)}")

            # Validate if enabled
            if self.validate_on_load:
                validation = self.validate_project(data)
                if not validation.valid:
                    error_msg = "; ".join(validation.errors)
                    return ProjectStatus.VALIDATION_ERROR, {}, f"Validation failed: {error_msg}"

                if validation.warnings:
                    logger.warning(f"Project load warnings: {validation.warnings}")

            # Store state
            self.current_path = project_path
            self.current_data = data
            self._original_hash = self._compute_data_hash(data)

            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type="PROJECT_LOAD",
                    user=user,
                    description=f"Project loaded: {project_path.name}",
                    details={
                        "path": str(project_path),
                        "version": data.get("version"),
                        "channels": len(data.get("channels", []))
                    }
                )

            return ProjectStatus.SUCCESS, data, f"Loaded: {project_path.name}"

        except json.JSONDecodeError as e:
            return ProjectStatus.ERROR, {}, f"Invalid JSON: {e}"
        except Exception as e:
            return ProjectStatus.ERROR, {}, str(e)

    def save_project(self,
                    project_path: Path,
                    data: Dict[str, Any],
                    user: str = "system",
                    reason: str = "") -> Tuple[ProjectStatus, str]:
        """
        Save a project with auto-backup.

        Args:
            project_path: Path to save to
            data: Project data
            user: Username for audit
            reason: Reason for save (for audit trail)

        Returns:
            (status, message) tuple
        """
        # Validate before save
        validation = self.validate_project(data)
        if not validation.valid:
            error_msg = "; ".join(validation.errors)
            return ProjectStatus.VALIDATION_ERROR, f"Validation failed: {error_msg}"

        # Auto-backup if file exists
        if self.backup_on_save and project_path.exists():
            backup = self.create_backup(project_path, reason="pre_save", user=user, new_data=data)
            if not backup:
                logger.warning("Backup failed but proceeding with save")

        try:
            # Ensure parent directory exists
            project_path.parent.mkdir(parents=True, exist_ok=True)

            # Add metadata
            data["modified"] = datetime.now().isoformat()
            if not data.get("created"):
                data["created"] = datetime.now().isoformat()

            # Write file
            with open(project_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Update state
            self.current_path = project_path
            self.current_data = data
            self._original_hash = self._compute_data_hash(data)

            if self.audit_trail:
                self.audit_trail.log_event(
                    event_type="PROJECT_SAVE",
                    user=user,
                    description=f"Project saved: {project_path.name}",
                    details={
                        "path": str(project_path),
                        "reason": reason,
                        "channels": len(data.get("channels", []))
                    }
                )

            return ProjectStatus.SUCCESS, f"Saved: {project_path.name}"

        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            return ProjectStatus.ERROR, str(e)

    def has_unsaved_changes(self) -> bool:
        """Check if current project has unsaved changes"""
        if not self.current_data:
            return False

        current_hash = self._compute_data_hash(self.current_data)
        return current_hash != self._original_hash

    def close_project(self, user: str = "system"):
        """Close current project"""
        if self.current_path and self.audit_trail:
            self.audit_trail.log_event(
                event_type="PROJECT_CLOSE",
                user=user,
                description=f"Project closed: {self.current_path.name}",
                details={"path": str(self.current_path)}
            )

        self.current_path = None
        self.current_data = {}
        self._original_hash = None
