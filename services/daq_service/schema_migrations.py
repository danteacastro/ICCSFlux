"""Project schema migration functions.

Each migration function transforms project data from one version to the next.
Migrations are applied in sequence: 1.0 -> 1.1 -> 2.0

Migration functions MUST be idempotent (safe to run multiple times).
"""

import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger('ProjectManager')

# Ordered list of supported schema versions
SCHEMA_VERSIONS = ["1.0", "1.1", "2.0"]

def get_migration_path(from_version: str, to_version: str) -> List[str]:
    """Get ordered list of versions to migrate through.

    Returns empty list if no migration needed or versions invalid.
    """
    if from_version not in SCHEMA_VERSIONS or to_version not in SCHEMA_VERSIONS:
        return []
    from_idx = SCHEMA_VERSIONS.index(from_version)
    to_idx = SCHEMA_VERSIONS.index(to_version)
    if from_idx >= to_idx:
        return []
    return SCHEMA_VERSIONS[from_idx + 1:to_idx + 1]

def migrate_project(data: Dict[str, Any],
                    target_version: str = None) -> Tuple[Dict[str, Any], List[str]]:
    """Migrate project data to target version (default: latest).

    Returns (migrated_data, list_of_applied_migrations).
    Does NOT modify the input dict.
    """
    target_version = target_version or SCHEMA_VERSIONS[-1]
    current_version = data.get("version", "1.0")

    path = get_migration_path(current_version, target_version)
    if not path:
        return data, []

    result = dict(data)  # Shallow copy
    applied = []

    for version in path:
        func_name = f"_migrate_to_{version.replace('.', '_')}"
        migrate_func = globals().get(func_name)
        if migrate_func:
            prev_version = result.get('version', '?')
            logger.info(f"Applying schema migration: {prev_version} -> {version}")
            result = migrate_func(result)
            result["version"] = version
            applied.append(f"{prev_version}->{version}")
        else:
            logger.warning(f"No migration function for version {version}")

    return result, applied

def _migrate_to_1_1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.0 to 1.1.

    Changes:
    - Normalize 'type' field to 'channel_type' in channels
    - Add default alarm_deadband and alarm_delay_sec if missing
    """
    channels = data.get("channels", {})
    if isinstance(channels, dict):
        for name, ch in channels.items():
            if 'type' in ch and 'channel_type' not in ch:
                ch['channel_type'] = ch['type']
            if 'alarm_deadband' not in ch:
                ch['alarm_deadband'] = 0.0
            if 'alarm_delay_sec' not in ch:
                ch['alarm_delay_sec'] = 0.0
    return data

def _migrate_to_2_0(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate from 1.1 to 2.0.

    Changes:
    - Convert channels from list format to dict format (if list)
    - Add 'metadata' section if missing
    """
    channels = data.get("channels", {})
    if isinstance(channels, list):
        channels_dict = {}
        for ch in channels:
            name = ch.get("name", f"channel_{len(channels_dict)}")
            channels_dict[name] = ch
        data["channels"] = channels_dict

    if "metadata" not in data:
        data["metadata"] = {
            "migrated_from": "1.1",
            "migration_note": "Auto-migrated to 2.0 schema"
        }

    return data
