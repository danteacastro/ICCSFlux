"""
Project Validator — Static analysis of NISystem project JSON files.

Checks for:
- Broken cross-references (scripts→channels, alarms→channels, etc.)
- Duplicate IDs
- Invalid channel types
- Orphan references
- Port conflicts
- Simulation config validity

Usage:
    python tools/validate_project.py config/projects/MyProject.json
    python tools/validate_project.py config/projects/          # all files in directory
    python tools/validate_project.py --format json config/projects/MyProject.json
"""

import ast
import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

# Valid channel types (from config_parser.py ChannelType enum)
VALID_CHANNEL_TYPES = {
    'thermocouple', 'voltage_input', 'current_input', 'rtd',
    'strain', 'strain_input', 'bridge_input',
    'iepe', 'iepe_input',
    'resistance', 'resistance_input',
    'voltage_output', 'current_output',
    'digital_input', 'digital_output',
    'counter',
}

# Valid process model types (from process_simulator.py)
VALID_MODEL_TYPES = {
    'thermalMass', 'flowLoop', 'pressureVessel',
    'levelTank', 'genericFirstOrder', 'heatExchanger',
}

class Severity(Enum):
    ERROR = 'ERROR'
    WARNING = 'WARNING'
    INFO = 'INFO'

@dataclass
class ValidationIssue:
    severity: Severity
    path: str  # JSON path, e.g. "channels.TT_101"
    message: str
    rule: str  # Rule ID for grouping

    def __str__(self):
        return f"[{self.severity.value}] {self.path}: {self.message}"

@dataclass
class ValidationResult:
    file_path: str
    project_name: str = ''
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.INFO)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def add(self, severity: Severity, path: str, message: str, rule: str):
        self.issues.append(ValidationIssue(severity, path, message, rule))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'file': self.file_path,
            'project': self.project_name,
            'errors': self.error_count,
            'warnings': self.warning_count,
            'info': self.info_count,
            'issues': [
                {
                    'severity': i.severity.value,
                    'path': i.path,
                    'message': i.message,
                    'rule': i.rule,
                }
                for i in self.issues
            ],
        }

# ---------------------------------------------------------------------------
# Tag Reference Extraction (AST-based)
# ---------------------------------------------------------------------------

def extract_tag_references(code: str) -> Set[str]:
    """
    Parse Python code and extract channel references via tags.XXX and tags["XXX"].

    Matches patterns:
        tags.ChannelName       -> "ChannelName"
        tags["ChannelName"]    -> "ChannelName"
        tags['ChannelName']    -> "ChannelName"
        tags.get("Name", 0)   -> "Name"
    """
    refs: Set[str] = set()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return refs

    # TagsAPI method names that are not channel references
    _TAGS_METHODS = {'get', 'keys', 'age', 'items', 'values'}

    for node in ast.walk(tree):
        # tags.XXX (but not tags.get, tags.keys, etc.)
        if isinstance(node, ast.Attribute):
            if (isinstance(node.value, ast.Name)
                    and node.value.id == 'tags'
                    and node.attr not in _TAGS_METHODS):
                refs.add(node.attr)

        # tags["XXX"] or tags['XXX']
        elif isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == 'tags':
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    refs.add(node.slice.value)

        # tags.get("XXX", default)
        elif isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get'
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'tags'
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                refs.add(node.args[0].value)

    return refs

def extract_output_references(code: str) -> Set[str]:
    """
    Extract outputs.set("ChannelName", value) references from script code.
    """
    refs: Set[str] = set()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return refs

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'set'
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'outputs'
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                refs.add(node.args[0].value)

    return refs

# ---------------------------------------------------------------------------
# Validation Rules
# ---------------------------------------------------------------------------

def _get_channel_names(project: Dict) -> Set[str]:
    """Get all channel names from the project."""
    channels = project.get('channels', {})
    return set(channels.keys())

def _get_channel_ports(project: Dict) -> Dict[str, str]:
    """Get channel_name -> physical_channel mapping."""
    result = {}
    for name, ch in project.get('channels', {}).items():
        port = ch.get('physical_channel', '')
        if port:
            result[name] = port
    return result

def validate_channel_types(project: Dict, result: ValidationResult):
    """Rule: All channel types must be valid ChannelType values."""
    for name, ch in project.get('channels', {}).items():
        ch_type = ch.get('channel_type', '')
        if ch_type not in VALID_CHANNEL_TYPES:
            result.add(Severity.ERROR, f'channels.{name}.channel_type',
                       f'Invalid channel type: {ch_type!r}', 'channel_type')

def validate_duplicate_ids(project: Dict, result: ValidationResult):
    """Rule: No duplicate channel, script, alarm, or interlock IDs."""
    # Channel names (keys are unique by nature of JSON objects, but check for
    # duplicate physical_channel values)
    channel_names = list(project.get('channels', {}).keys())
    seen_names: Set[str] = set()
    for name in channel_names:
        if name in seen_names:
            result.add(Severity.ERROR, f'channels.{name}',
                       'Duplicate channel name', 'duplicate_id')
        seen_names.add(name)

    # Script IDs
    scripts = project.get('scripts', {})
    seen_script_ids: Set[str] = set()
    for section_key in ('calculatedParams', 'sequences', 'schedules', 'pythonScripts'):
        for script in scripts.get(section_key, []):
            sid = script.get('id', '')
            if sid:
                if sid in seen_script_ids:
                    result.add(Severity.ERROR, f'scripts.{section_key}.{sid}',
                               f'Duplicate script ID: {sid!r}', 'duplicate_id')
                seen_script_ids.add(sid)

    # Alarm IDs
    safety = project.get('safety', {})
    alarm_configs = safety.get('alarmConfigs', {})
    if isinstance(alarm_configs, dict):
        # Already keyed by channel name — inherently unique
        pass
    elif isinstance(alarm_configs, list):
        seen_alarm_ids: Set[str] = set()
        for alarm in alarm_configs:
            aid = alarm.get('id', alarm.get('channel', ''))
            if aid and aid in seen_alarm_ids:
                result.add(Severity.ERROR, f'safety.alarmConfigs.{aid}',
                           f'Duplicate alarm ID: {aid!r}', 'duplicate_id')
            seen_alarm_ids.add(aid)

def validate_port_conflicts(project: Dict, result: ValidationResult):
    """Rule: No two channels should share the same physical port."""
    port_to_channels: Dict[str, List[str]] = {}
    for name, ch in project.get('channels', {}).items():
        port = ch.get('physical_channel', '')
        if port:
            port_to_channels.setdefault(port, []).append(name)

    for port, channels in port_to_channels.items():
        if len(channels) > 1:
            result.add(Severity.WARNING, f'channels',
                       f'Port conflict: {port!r} used by {channels}',
                       'port_conflict')

def validate_alarm_channel_refs(project: Dict, result: ValidationResult):
    """Rule: Alarm channelId references must exist."""
    channel_names = _get_channel_names(project)
    safety = project.get('safety', {})
    alarm_configs = safety.get('alarmConfigs', {})

    if isinstance(alarm_configs, dict):
        for channel_name, alarm in alarm_configs.items():
            if channel_name not in channel_names:
                result.add(Severity.ERROR, f'safety.alarmConfigs.{channel_name}',
                           f'Alarm references non-existent channel: {channel_name!r}',
                           'alarm_channel_ref')
    elif isinstance(alarm_configs, list):
        for alarm in alarm_configs:
            channel_name = alarm.get('channel', alarm.get('channelId', ''))
            if channel_name and channel_name not in channel_names:
                result.add(Severity.ERROR, f'safety.alarmConfigs.{channel_name}',
                           f'Alarm references non-existent channel: {channel_name!r}',
                           'alarm_channel_ref')

def validate_interlock_channel_refs(project: Dict, result: ValidationResult):
    """Rule: Interlock channel references and action targets must exist."""
    channel_names = _get_channel_names(project)
    safety = project.get('safety', {})

    for interlock in safety.get('interlocks', []):
        iid = interlock.get('id', 'unknown')
        ch = interlock.get('channelId', interlock.get('channel', ''))
        if ch and ch not in channel_names:
            result.add(Severity.ERROR, f'safety.interlocks.{iid}',
                       f'Interlock references non-existent channel: {ch!r}',
                       'interlock_channel_ref')

        # Check action target channels
        for action in interlock.get('actions', []):
            target = action.get('channelId', action.get('channel', ''))
            if target and target not in channel_names:
                result.add(Severity.WARNING, f'safety.interlocks.{iid}.actions',
                           f'Interlock action targets non-existent channel: {target!r}',
                           'interlock_action_ref')

def validate_recording_channel_refs(project: Dict, result: ValidationResult):
    """Rule: Recording selected channels must exist."""
    channel_names = _get_channel_names(project)
    recording = project.get('recording', {})

    for ch_name in recording.get('selectedChannels', []):
        if ch_name not in channel_names:
            result.add(Severity.WARNING, f'recording.selectedChannels',
                       f'Recording references non-existent channel: {ch_name!r}',
                       'recording_channel_ref')

def validate_pid_channel_refs(project: Dict, result: ValidationResult):
    """Rule: PID controller channel references must exist."""
    channel_names = _get_channel_names(project)

    for pid_name, pid in project.get('pidControllers', {}).items():
        for key in ('inputChannel', 'outputChannel', 'feedbackChannel'):
            ch = pid.get(key, '')
            if ch and ch not in channel_names:
                result.add(Severity.ERROR, f'pidControllers.{pid_name}.{key}',
                           f'PID references non-existent channel: {ch!r}',
                           'pid_channel_ref')

def validate_script_tag_refs(project: Dict, result: ValidationResult):
    """Rule: Script tag references (tags.XXX) should match existing channels."""
    channel_names = _get_channel_names(project)
    scripts = project.get('scripts', {})

    for section_key in ('calculatedParams', 'sequences', 'schedules', 'pythonScripts'):
        for script in scripts.get(section_key, []):
            sid = script.get('id', script.get('name', 'unknown'))
            code = script.get('code', '')
            if not code:
                continue

            tag_refs = extract_tag_references(code)
            for ref in tag_refs:
                if ref not in channel_names:
                    result.add(Severity.WARNING, f'scripts.{section_key}.{sid}',
                               f'Script references unknown tag: {ref!r}',
                               'script_tag_ref')

            output_refs = extract_output_references(code)
            for ref in output_refs:
                if ref not in channel_names:
                    result.add(Severity.INFO, f'scripts.{section_key}.{sid}',
                               f'Script sets output on unknown channel: {ref!r}',
                               'script_output_ref')

def validate_simulation_config(project: Dict, result: ValidationResult):
    """Rule: Process model channel references must exist."""
    channel_names = _get_channel_names(project)
    simulation = project.get('simulation', {})

    for i, model in enumerate(simulation.get('processModels', [])):
        model_type = model.get('type', '')
        model_name = model.get('name', f'model_{i}')

        if model_type not in VALID_MODEL_TYPES:
            result.add(Severity.ERROR, f'simulation.processModels.{model_name}',
                       f'Unknown process model type: {model_type!r}',
                       'sim_model_type')

        for role, mapping in [('inputChannels', model.get('inputChannels', {})),
                              ('outputChannels', model.get('outputChannels', {}))]:
            for model_port, daq_channel in mapping.items():
                if daq_channel not in channel_names:
                    result.add(Severity.ERROR,
                               f'simulation.processModels.{model_name}.{role}.{model_port}',
                               f'Process model references non-existent channel: {daq_channel!r}',
                               'sim_channel_ref')

def validate_safety_action_refs(project: Dict, result: ValidationResult):
    """Rule: Safety action channel references must exist."""
    channel_names = _get_channel_names(project)
    safety = project.get('safety', {})

    for name, action in safety.get('safetyActions', {}).items():
        ch = action.get('channelId', action.get('channel', ''))
        if ch and ch not in channel_names:
            result.add(Severity.ERROR, f'safety.safetyActions.{name}',
                       f'Safety action references non-existent channel: {ch!r}',
                       'safety_action_ref')

# ---------------------------------------------------------------------------
# Main Validator
# ---------------------------------------------------------------------------

ALL_VALIDATORS = [
    validate_channel_types,
    validate_duplicate_ids,
    validate_port_conflicts,
    validate_alarm_channel_refs,
    validate_interlock_channel_refs,
    validate_recording_channel_refs,
    validate_pid_channel_refs,
    validate_script_tag_refs,
    validate_simulation_config,
    validate_safety_action_refs,
]

def validate_project(project: Dict, file_path: str = '<unknown>') -> ValidationResult:
    """Run all validation rules on a project dict."""
    result = ValidationResult(file_path=file_path)
    result.project_name = project.get('name', '')

    for validator in ALL_VALIDATORS:
        validator(project, result)

    # Sort issues by severity (ERROR first)
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    result.issues.sort(key=lambda i: severity_order[i.severity])

    return result

def validate_file(file_path: str) -> ValidationResult:
    """Load and validate a single project JSON file."""
    result = ValidationResult(file_path=file_path)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            project = json.load(f)
    except json.JSONDecodeError as e:
        result.add(Severity.ERROR, '', f'Invalid JSON: {e}', 'json_parse')
        return result
    except OSError as e:
        result.add(Severity.ERROR, '', f'Cannot read file: {e}', 'file_read')
        return result

    return validate_project(project, file_path)

def validate_directory(dir_path: str) -> List[ValidationResult]:
    """Validate all .json files in a directory."""
    results = []
    for entry in sorted(Path(dir_path).iterdir()):
        if entry.suffix == '.json' and entry.is_file():
            results.append(validate_file(str(entry)))
    return results

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Validate NISystem project JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/validate_project.py config/projects/MyProject.json
  python tools/validate_project.py config/projects/
  python tools/validate_project.py --format json config/projects/MyProject.json
        """,
    )
    parser.add_argument('path', help='Project JSON file or directory')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        help='Output format (default: text)')
    args = parser.parse_args()

    target = Path(args.path)
    if target.is_dir():
        results = validate_directory(str(target))
    elif target.is_file():
        results = [validate_file(str(target))]
    else:
        print(f"Error: {args.path} not found", file=sys.stderr)
        sys.exit(2)

    if args.format == 'json':
        output = [r.to_dict() for r in results]
        print(json.dumps(output, indent=2))
    else:
        any_errors = False
        for result in results:
            name = result.project_name or os.path.basename(result.file_path)
            header = f"=== {name} ==="
            print(header)

            if not result.issues:
                print("  No issues found.")
            else:
                for issue in result.issues:
                    print(f"  {issue}")

            counts = f"  ({result.error_count} errors, {result.warning_count} warnings, {result.info_count} info)"
            print(counts)
            print()

            if result.has_errors:
                any_errors = True

        total_errors = sum(r.error_count for r in results)
        total_warnings = sum(r.warning_count for r in results)
        print(f"Total: {total_errors} errors, {total_warnings} warnings across {len(results)} file(s)")

        sys.exit(1 if any_errors else 0)

if __name__ == '__main__':
    main()
