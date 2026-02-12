#!/usr/bin/env python3
"""
Backup Logger for NISystem

Provides human-readable backup logging with detailed changelogs showing
exactly what was added, removed, or modified between project versions.

Features:
- Human-readable backup.log file
- Detailed diff between project versions
- Tracks changes to pages, widgets, scripts, channels, safety settings
- Works in both dev and portable environments

References:
- IEC 61511: Safety Instrumented Systems (change tracking)
- FDA 21 CFR Part 11: Electronic Records (audit trail)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger('BackupLogger')


@dataclass
class ChangeEntry:
    """A single change in the changelog"""
    action: str  # ADDED, REMOVED, MODIFIED, MOVED, RENAMED
    category: str  # Pages, Widgets, Scripts, Channels, Safety, Recording
    item_type: str  # Page, TrendChart, PythonScript, Channel, etc.
    item_name: str
    details: str = ""
    page_context: str = ""  # Which page the change is on (for widgets)


@dataclass
class ChangeLog:
    """Collection of changes between two project versions"""
    timestamp: datetime
    project_name: str
    user: str
    reason: str
    old_size: int
    new_size: int
    old_hash: str
    new_hash: str
    changes: List[ChangeEntry] = field(default_factory=list)

    @property
    def size_delta(self) -> int:
        return self.new_size - self.old_size

    @property
    def size_delta_str(self) -> str:
        delta = self.size_delta
        if delta > 0:
            return f"+{self._format_size(delta)}"
        elif delta < 0:
            return f"-{self._format_size(abs(delta))}"
        return "0 bytes"

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / (1024*1024):.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} bytes"

    def has_changes(self) -> bool:
        return len(self.changes) > 0


class ProjectDiffer:
    """Compares two project versions and generates a detailed changelog"""

    def __init__(self):
        self.changes: List[ChangeEntry] = []

    def diff(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> List[ChangeEntry]:
        """
        Generate a list of changes between two project versions.

        Args:
            old_data: Previous project data (or empty dict for initial)
            new_data: New project data

        Returns:
            List of ChangeEntry objects describing all changes
        """
        self.changes = []

        # Compare each major section
        self._diff_pages(old_data, new_data)
        self._diff_scripts(old_data, new_data)
        self._diff_channels(old_data, new_data)
        self._diff_safety(old_data, new_data)
        self._diff_recording(old_data, new_data)
        self._diff_variables(old_data, new_data)

        return self.changes

    def _add_change(self, action: str, category: str, item_type: str,
                    item_name: str, details: str = "", page_context: str = ""):
        self.changes.append(ChangeEntry(
            action=action,
            category=category,
            item_type=item_type,
            item_name=item_name,
            details=details,
            page_context=page_context
        ))

    def _diff_pages(self, old_data: Dict, new_data: Dict):
        """Compare pages and widgets"""
        old_layout = old_data.get('layout', {})
        new_layout = new_data.get('layout', {})

        # Handle both single-page (widgets) and multi-page (pages) formats
        old_pages = self._normalize_pages(old_layout)
        new_pages = self._normalize_pages(new_layout)

        old_page_ids = set(old_pages.keys())
        new_page_ids = set(new_pages.keys())

        # Added pages
        for page_id in new_page_ids - old_page_ids:
            page = new_pages[page_id]
            widget_count = len(page.get('widgets', []))
            self._add_change('ADDED', 'Pages', 'Page',
                           page.get('name', page_id),
                           f"new page with {widget_count} widgets")

        # Removed pages
        for page_id in old_page_ids - new_page_ids:
            page = old_pages[page_id]
            self._add_change('REMOVED', 'Pages', 'Page',
                           page.get('name', page_id))

        # Modified pages - compare widgets
        for page_id in old_page_ids & new_page_ids:
            old_page = old_pages[page_id]
            new_page = new_pages[page_id]

            # Check for page rename
            old_name = old_page.get('name', page_id)
            new_name = new_page.get('name', page_id)
            if old_name != new_name:
                self._add_change('RENAMED', 'Pages', 'Page',
                               new_name, f'"{old_name}" → "{new_name}"')

            # Compare widgets on this page
            self._diff_widgets(old_page, new_page, new_name)

    def _normalize_pages(self, layout: Dict) -> Dict[str, Dict]:
        """Convert layout to normalized pages dict"""
        if 'pages' in layout and layout['pages']:
            # Multi-page format
            return {p.get('id', str(i)): p for i, p in enumerate(layout['pages'])}
        elif 'widgets' in layout:
            # Single-page format - create a synthetic "Main" page
            return {'main': {'id': 'main', 'name': 'Main', 'widgets': layout['widgets']}}
        return {}

    def _diff_widgets(self, old_page: Dict, new_page: Dict, page_name: str):
        """Compare widgets on a page"""
        old_widgets = {w.get('i', str(i)): w for i, w in enumerate(old_page.get('widgets', []))}
        new_widgets = {w.get('i', str(i)): w for i, w in enumerate(new_page.get('widgets', []))}

        old_ids = set(old_widgets.keys())
        new_ids = set(new_widgets.keys())

        # Added widgets
        for wid in new_ids - old_ids:
            w = new_widgets[wid]
            widget_type = w.get('type', 'Widget')
            widget_name = w.get('props', {}).get('title') or w.get('props', {}).get('label') or w.get('props', {}).get('channel') or wid
            pos = f"position: {w.get('x', 0)},{w.get('y', 0)}"
            self._add_change('ADDED', 'Widgets', widget_type, widget_name, pos, page_name)

        # Removed widgets
        for wid in old_ids - new_ids:
            w = old_widgets[wid]
            widget_type = w.get('type', 'Widget')
            widget_name = w.get('props', {}).get('title') or w.get('props', {}).get('label') or w.get('props', {}).get('channel') or wid
            self._add_change('REMOVED', 'Widgets', widget_type, widget_name, "", page_name)

        # Modified widgets
        for wid in old_ids & new_ids:
            old_w = old_widgets[wid]
            new_w = new_widgets[wid]

            widget_type = new_w.get('type', 'Widget')
            widget_name = new_w.get('props', {}).get('title') or new_w.get('props', {}).get('label') or new_w.get('props', {}).get('channel') or wid

            # Check position change
            old_pos = (old_w.get('x', 0), old_w.get('y', 0))
            new_pos = (new_w.get('x', 0), new_w.get('y', 0))
            if old_pos != new_pos:
                self._add_change('MOVED', 'Widgets', widget_type, widget_name,
                               f"{old_pos[0]},{old_pos[1]} → {new_pos[0]},{new_pos[1]}", page_name)

            # Check size change
            old_size = (old_w.get('w', 1), old_w.get('h', 1))
            new_size = (new_w.get('w', 1), new_w.get('h', 1))
            if old_size != new_size:
                self._add_change('MODIFIED', 'Widgets', widget_type, widget_name,
                               f"size: {old_size[0]}x{old_size[1]} → {new_size[0]}x{new_size[1]}", page_name)

            # Check props change
            old_props = old_w.get('props', {})
            new_props = new_w.get('props', {})
            prop_changes = self._diff_dict(old_props, new_props)
            if prop_changes:
                self._add_change('MODIFIED', 'Widgets', widget_type, widget_name,
                               prop_changes, page_name)

    def _diff_scripts(self, old_data: Dict, new_data: Dict):
        """Compare all script types"""
        old_scripts = old_data.get('scripts', {})
        new_scripts = new_data.get('scripts', {})

        script_types = [
            ('pythonScripts', 'Python Script', 'name'),
            ('sequences', 'Sequence', 'name'),
            ('schedules', 'Schedule', 'name'),
            ('calculatedParams', 'Calculated Param', 'name'),
            ('alarms', 'Alarm Script', 'name'),
            ('triggers', 'Trigger', 'name'),
            ('transformations', 'Transformation', 'name'),
            ('watchdogs', 'Watchdog', 'name'),
            ('stateMachines', 'State Machine', 'name'),
        ]

        for script_key, script_type, name_field in script_types:
            old_list = old_scripts.get(script_key, [])
            new_list = new_scripts.get(script_key, [])

            # Convert to dict by ID or name
            old_dict = {s.get('id') or s.get(name_field, str(i)): s for i, s in enumerate(old_list)}
            new_dict = {s.get('id') or s.get(name_field, str(i)): s for i, s in enumerate(new_list)}

            old_ids = set(old_dict.keys())
            new_ids = set(new_dict.keys())

            # Added
            for sid in new_ids - old_ids:
                s = new_dict[sid]
                self._add_change('ADDED', 'Scripts', script_type, s.get(name_field, sid))

            # Removed
            for sid in old_ids - new_ids:
                s = old_dict[sid]
                self._add_change('REMOVED', 'Scripts', script_type, s.get(name_field, sid))

            # Modified
            for sid in old_ids & new_ids:
                old_s = old_dict[sid]
                new_s = new_dict[sid]
                changes = self._diff_dict(old_s, new_s, exclude=['id', 'modified', 'created'])
                if changes:
                    self._add_change('MODIFIED', 'Scripts', script_type,
                                   new_s.get(name_field, sid), changes)

    def _diff_channels(self, old_data: Dict, new_data: Dict):
        """Compare channels"""
        old_channels = old_data.get('channels', {})
        new_channels = new_data.get('channels', {})

        # Handle both dict and list formats
        if isinstance(old_channels, list):
            old_channels = {ch.get('name', str(i)): ch for i, ch in enumerate(old_channels)}
        if isinstance(new_channels, list):
            new_channels = {ch.get('name', str(i)): ch for i, ch in enumerate(new_channels)}

        old_names = set(old_channels.keys())
        new_names = set(new_channels.keys())

        # Added
        for name in new_names - old_names:
            ch = new_channels[name]
            ch_type = ch.get('channel_type') or ch.get('type', 'unknown')
            details = f"({ch_type})"
            if 'units' in ch:
                details += f", units: {ch['units']}"
            self._add_change('ADDED', 'Channels', 'Channel', name, details)

        # Removed
        for name in old_names - new_names:
            self._add_change('REMOVED', 'Channels', 'Channel', name)

        # Modified
        for name in old_names & new_names:
            old_ch = old_channels[name]
            new_ch = new_channels[name]
            changes = self._diff_dict(old_ch, new_ch, exclude=['name'])
            if changes:
                self._add_change('MODIFIED', 'Channels', 'Channel', name, changes)

    def _diff_safety(self, old_data: Dict, new_data: Dict):
        """Compare safety settings"""
        old_safety = old_data.get('safety', {})
        new_safety = new_data.get('safety', {})

        # Interlocks
        old_interlocks = {i.get('id') or i.get('name', str(idx)): i
                         for idx, i in enumerate(old_safety.get('interlocks', []))}
        new_interlocks = {i.get('id') or i.get('name', str(idx)): i
                         for idx, i in enumerate(new_safety.get('interlocks', []))}

        old_ids = set(old_interlocks.keys())
        new_ids = set(new_interlocks.keys())

        for iid in new_ids - old_ids:
            interlock = new_interlocks[iid]
            condition = interlock.get('condition', '')
            action = interlock.get('action', '')
            self._add_change('ADDED', 'Safety', 'Interlock',
                           interlock.get('name', iid),
                           f"condition: {condition}, action: {action}")

        for iid in old_ids - new_ids:
            self._add_change('REMOVED', 'Safety', 'Interlock',
                           old_interlocks[iid].get('name', iid))

        for iid in old_ids & new_ids:
            changes = self._diff_dict(old_interlocks[iid], new_interlocks[iid], exclude=['id'])
            if changes:
                self._add_change('MODIFIED', 'Safety', 'Interlock',
                               new_interlocks[iid].get('name', iid), changes)

        # Alarm configs
        old_alarms = old_safety.get('alarmConfigs', {})
        new_alarms = new_safety.get('alarmConfigs', {})

        # Handle list format
        if isinstance(old_alarms, list):
            old_alarms = {a.get('id', str(i)): a for i, a in enumerate(old_alarms)} if old_alarms else {}
        if isinstance(new_alarms, list):
            new_alarms = {a.get('id', str(i)): a for i, a in enumerate(new_alarms)} if new_alarms else {}

        for name in set(new_alarms.keys()) - set(old_alarms.keys()):
            self._add_change('ADDED', 'Safety', 'Alarm Config', name)

        for name in set(old_alarms.keys()) - set(new_alarms.keys()):
            self._add_change('REMOVED', 'Safety', 'Alarm Config', name)

        for name in set(old_alarms.keys()) & set(new_alarms.keys()):
            changes = self._diff_dict(old_alarms[name], new_alarms[name])
            if changes:
                self._add_change('MODIFIED', 'Safety', 'Alarm Config', name, changes)

    def _diff_recording(self, old_data: Dict, new_data: Dict):
        """Compare recording settings"""
        old_rec = old_data.get('recording', {})
        new_rec = new_data.get('recording', {})

        # Selected channels
        old_channels = set(old_rec.get('selectedChannels', []))
        new_channels = set(new_rec.get('selectedChannels', []))

        for ch in new_channels - old_channels:
            self._add_change('ADDED', 'Recording', 'Channel', ch, "added to recording list")

        for ch in old_channels - new_channels:
            self._add_change('REMOVED', 'Recording', 'Channel', ch, "removed from recording list")

        # Config changes
        old_config = old_rec.get('config', {})
        new_config = new_rec.get('config', {})
        changes = self._diff_dict(old_config, new_config)
        if changes:
            self._add_change('MODIFIED', 'Recording', 'Config', 'Recording Settings', changes)

    def _diff_variables(self, old_data: Dict, new_data: Dict):
        """Compare user variables"""
        old_vars = old_data.get('variables', {})
        new_vars = new_data.get('variables', {})

        # Handle list format (some projects store variables as [])
        if isinstance(old_vars, list):
            old_vars = {v.get('name', str(i)): v for i, v in enumerate(old_vars)} if old_vars else {}
        if isinstance(new_vars, list):
            new_vars = {v.get('name', str(i)): v for i, v in enumerate(new_vars)} if new_vars else {}

        for name in set(new_vars.keys()) - set(old_vars.keys()):
            self._add_change('ADDED', 'Variables', 'Variable', name, f"= {new_vars[name]}")

        for name in set(old_vars.keys()) - set(new_vars.keys()):
            self._add_change('REMOVED', 'Variables', 'Variable', name)

        for name in set(old_vars.keys()) & set(new_vars.keys()):
            if old_vars[name] != new_vars[name]:
                self._add_change('MODIFIED', 'Variables', 'Variable', name,
                               f"{old_vars[name]} → {new_vars[name]}")

    def _diff_dict(self, old: Dict, new: Dict, exclude: List[str] = None) -> str:
        """Generate a summary of dictionary changes"""
        exclude = exclude or []
        changes = []

        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            if key in exclude:
                continue

            old_val = old.get(key)
            new_val = new.get(key)

            if old_val != new_val:
                if old_val is None:
                    changes.append(f"{key}: (new) {self._format_value(new_val)}")
                elif new_val is None:
                    changes.append(f"{key}: (removed)")
                else:
                    changes.append(f"{key}: {self._format_value(old_val)} → {self._format_value(new_val)}")

        return "; ".join(changes[:5])  # Limit to 5 changes to keep it readable

    def _format_value(self, val: Any) -> str:
        """Format a value for display"""
        if isinstance(val, str):
            if len(val) > 30:
                return f'"{val[:27]}..."'
            return f'"{val}"'
        if isinstance(val, bool):
            return str(val).lower()
        if isinstance(val, (list, dict)):
            return f"[{len(val)} items]"
        return str(val)


class BackupLogger:
    """
    Manages human-readable backup logging with detailed changelogs.

    Creates a backup.log file that tracks all backup operations with
    detailed diffs showing exactly what changed.
    """

    def __init__(self, log_dir: Path):
        """
        Initialize backup logger.

        Args:
            log_dir: Directory for backup.log file
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "backup.log"
        self.differ = ProjectDiffer()

        # Cache of last known project data for diffing
        self._last_data_cache: Dict[str, Dict] = {}

    def log_backup(self,
                   project_name: str,
                   project_path: Path,
                   backup_path: Path,
                   new_data: Dict[str, Any],
                   old_data: Optional[Dict[str, Any]],
                   user: str,
                   reason: str,
                   new_hash: str,
                   old_hash: str = "",
                   backup_count: int = 0,
                   max_backups: int = 10) -> ChangeLog:
        """
        Log a backup operation with detailed changelog.

        Args:
            project_name: Name of the project
            project_path: Path to original project file
            backup_path: Path to backup file
            new_data: New project data
            old_data: Previous project data (for diff)
            user: User who triggered backup
            reason: Reason for backup
            new_hash: Hash of new file
            old_hash: Hash of old file
            backup_count: Current number of backups for this project
            max_backups: Maximum backups allowed

        Returns:
            ChangeLog object with all detected changes
        """
        timestamp = datetime.now()

        # Calculate sizes
        new_size = backup_path.stat().st_size if backup_path.exists() else 0
        old_size = 0
        if old_data:
            # Estimate old size from JSON
            old_size = len(json.dumps(old_data))

        # Generate diff
        changes = []
        if old_data:
            changes = self.differ.diff(old_data, new_data)
        else:
            # Initial backup - list what's being saved
            changes = self._describe_initial(new_data)

        # Create changelog
        changelog = ChangeLog(
            timestamp=timestamp,
            project_name=project_name,
            user=user,
            reason=reason,
            old_size=old_size,
            new_size=new_size,
            old_hash=old_hash,
            new_hash=new_hash,
            changes=changes
        )

        # Write to log file
        self._write_log_entry(changelog, backup_count, max_backups, backup_path)

        # Cache for next diff
        self._last_data_cache[str(project_path)] = new_data

        return changelog

    def log_restore(self,
                    project_name: str,
                    backup_timestamp: datetime,
                    user: str,
                    reason: str = ""):
        """Log a restore operation"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
            f.write("=" * 80 + "\n")
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | RESTORE | SUCCESS | manual\n")
            f.write("=" * 80 + "\n")
            f.write(f"Project: {project_name}\n")
            f.write(f"User: {user}\n")
            f.write(f"Restored from: {backup_timestamp.strftime('%Y-%m-%d %H:%M:%S')} backup\n")
            if reason:
                f.write(f"Reason: \"{reason}\"\n")
            f.write("-" * 80 + "\n")

    def log_cleanup(self,
                    project_name: str,
                    removed_count: int,
                    remaining_count: int,
                    max_backups: int):
        """Log a cleanup/retention operation"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | CLEANUP | SUCCESS | retention\n")
            f.write(f"  Project: {project_name}\n")
            f.write(f"  Removed: {removed_count} backup(s) exceeding retention limit\n")
            f.write(f"  Remaining: {remaining_count} of {max_backups}\n")

    def log_failure(self,
                    project_name: str,
                    operation: str,
                    user: str,
                    error: str):
        """Log a failed backup operation"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
            f.write("=" * 80 + "\n")
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {operation.upper()} | FAILED\n")
            f.write("=" * 80 + "\n")
            f.write(f"Project: {project_name}\n")
            f.write(f"User: {user}\n")
            f.write(f"Error: {error}\n")
            f.write("-" * 80 + "\n")

    def _describe_initial(self, data: Dict[str, Any]) -> List[ChangeEntry]:
        """Describe contents of initial backup"""
        changes = []

        # Count pages
        layout = data.get('layout', {})
        if 'pages' in layout:
            for page in layout['pages']:
                widget_count = len(page.get('widgets', []))
                changes.append(ChangeEntry(
                    'ADDED', 'Pages', 'Page',
                    page.get('name', 'Unnamed'),
                    f"with {widget_count} widgets"
                ))
        elif 'widgets' in layout:
            widget_count = len(layout['widgets'])
            changes.append(ChangeEntry(
                'ADDED', 'Pages', 'Page', 'Main', f"with {widget_count} widgets"
            ))

        # Count scripts
        scripts = data.get('scripts', {})
        for script_type, display_name in [
            ('pythonScripts', 'Python Scripts'),
            ('sequences', 'Sequences'),
            ('schedules', 'Schedules'),
            ('alarms', 'Alarm Scripts'),
        ]:
            count = len(scripts.get(script_type, []))
            if count > 0:
                changes.append(ChangeEntry(
                    'ADDED', 'Scripts', display_name, f"{count} items", ""
                ))

        # Count channels
        channels = data.get('channels', {})
        if isinstance(channels, dict):
            count = len(channels)
        else:
            count = len(channels) if channels else 0
        if count > 0:
            changes.append(ChangeEntry(
                'ADDED', 'Channels', 'Channels', f"{count} channels", ""
            ))

        return changes

    def _write_log_entry(self, changelog: ChangeLog, backup_count: int,
                         max_backups: int, backup_path: Path):
        """Write a changelog entry to the log file"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
            f.write("=" * 80 + "\n")
            f.write(f"{changelog.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | BACKUP | SUCCESS | {changelog.reason}\n")
            f.write("=" * 80 + "\n")
            f.write(f"Project: {changelog.project_name}\n")
            f.write(f"User: {changelog.user}\n")
            f.write(f"Size: {self._format_size(changelog.new_size)} ({changelog.size_delta_str})\n")
            f.write(f"Hash: {changelog.new_hash[:8]}\n")
            f.write(f"Backups: {backup_count} of {max_backups}\n")
            f.write(f"File: {backup_path.name}\n")

            if changelog.has_changes():
                f.write("\nCHANGES FROM PREVIOUS:\n")

                # Group changes by category
                by_category: Dict[str, List[ChangeEntry]] = {}
                for change in changelog.changes:
                    key = change.page_context if change.category == 'Widgets' else change.category
                    if key not in by_category:
                        by_category[key] = []
                    by_category[key].append(change)

                # Write grouped changes
                for category, changes in by_category.items():
                    if category and changes[0].category == 'Widgets':
                        f.write(f"\n[Page: {category}]\n")
                    else:
                        f.write(f"\n[{category}]\n")

                    for change in changes:
                        symbol = {
                            'ADDED': '+',
                            'REMOVED': '-',
                            'MODIFIED': '~',
                            'MOVED': '→',
                            'RENAMED': '↔'
                        }.get(change.action, '*')

                        line = f"  {symbol} {change.action}: {change.item_type} \"{change.item_name}\""
                        if change.details:
                            line += f" ({change.details})"
                        f.write(line + "\n")
            else:
                f.write("\nNo changes detected (identical to previous backup)\n")

            f.write("-" * 80 + "\n")

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / (1024*1024):.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} bytes"

    def get_last_data(self, project_path: Path) -> Optional[Dict[str, Any]]:
        """Get cached project data for diffing"""
        return self._last_data_cache.get(str(project_path))

    def set_last_data(self, project_path: Path, data: Dict[str, Any]):
        """Cache project data for next diff"""
        self._last_data_cache[str(project_path)] = data
