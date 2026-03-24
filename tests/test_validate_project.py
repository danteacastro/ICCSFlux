"""
Tests for the Project Validator — static analysis of NISystem project JSON.

Tests all validation rules: channel types, duplicate IDs, port conflicts,
cross-reference checks (alarms, interlocks, recording, PID, scripts, simulation),
and the tag extraction AST parser.
"""

import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from validate_project import (
    extract_tag_references, extract_output_references,
    validate_project, validate_file, validate_directory,
    validate_channel_types, validate_duplicate_ids,
    validate_port_conflicts, validate_alarm_channel_refs,
    validate_interlock_channel_refs, validate_recording_channel_refs,
    validate_pid_channel_refs, validate_script_tag_refs,
    validate_simulation_config, validate_safety_action_refs,
    ValidationResult, Severity, VALID_CHANNEL_TYPES,
)

# ===== Tag Extraction Tests =====

class TestExtractTagReferences:
    def test_attribute_access(self):
        code = "x = tags.Temperature"
        refs = extract_tag_references(code)
        assert refs == {'Temperature'}

    def test_subscript_double_quotes(self):
        code = 'x = tags["Flow_Rate"]'
        refs = extract_tag_references(code)
        assert refs == {'Flow_Rate'}

    def test_subscript_single_quotes(self):
        code = "x = tags['Pressure']"
        refs = extract_tag_references(code)
        assert refs == {'Pressure'}

    def test_tags_get(self):
        code = 'x = tags.get("Level", 0.0)'
        refs = extract_tag_references(code)
        assert refs == {'Level'}

    def test_multiple_tags(self):
        code = """
temp = tags.TT_101
flow = tags["FT_201"]
level = tags.get("LT_301", 0)
"""
        refs = extract_tag_references(code)
        assert refs == {'TT_101', 'FT_201', 'LT_301'}

    def test_no_tags(self):
        code = "x = 42\ny = x + 1"
        refs = extract_tag_references(code)
        assert refs == set()

    def test_syntax_error(self):
        code = "def foo(:"
        refs = extract_tag_references(code)
        assert refs == set()

    def test_not_tags_object(self):
        code = "x = other.Temperature"
        refs = extract_tag_references(code)
        assert refs == set()

    def test_tags_in_loop(self):
        code = """
while True:
    t = tags.TC001
    if t > 100:
        v = tags["Valve_1"]
"""
        refs = extract_tag_references(code)
        assert refs == {'TC001', 'Valve_1'}

    def test_numeric_subscript_ignored(self):
        code = "x = tags[0]"
        refs = extract_tag_references(code)
        assert refs == set()

class TestExtractOutputReferences:
    def test_outputs_set(self):
        code = 'outputs.set("HeaterPower", 100)'
        refs = extract_output_references(code)
        assert refs == {'HeaterPower'}

    def test_no_outputs(self):
        code = "x = 42"
        refs = extract_output_references(code)
        assert refs == set()

    def test_not_outputs_object(self):
        code = 'other.set("Channel", 0)'
        refs = extract_output_references(code)
        assert refs == set()

# ===== Helper to build minimal projects =====

def _base_project(**overrides):
    project = {
        'name': 'TestProject',
        'channels': {
            'TT_101': {'name': 'TT_101', 'channel_type': 'thermocouple', 'physical_channel': 'Mod1/ai0'},
            'FT_201': {'name': 'FT_201', 'channel_type': 'voltage_input', 'physical_channel': 'Mod1/ai1'},
            'ValveOut': {'name': 'ValveOut', 'channel_type': 'voltage_output', 'physical_channel': 'Mod2/ao0'},
        },
        'scripts': {'calculatedParams': [], 'sequences': [], 'schedules': [], 'pythonScripts': []},
        'recording': {'config': {}, 'selectedChannels': []},
        'safety': {'alarmConfigs': {}, 'interlocks': []},
    }
    project.update(overrides)
    return project

# ===== Channel Type Validation =====

class TestValidateChannelTypes:
    def test_valid_types_pass(self):
        project = _base_project()
        result = ValidationResult(file_path='test')
        validate_channel_types(project, result)
        assert result.error_count == 0

    def test_invalid_type_errors(self):
        project = _base_project()
        project['channels']['Bad'] = {'name': 'Bad', 'channel_type': 'virtual'}
        result = ValidationResult(file_path='test')
        validate_channel_types(project, result)
        assert result.error_count == 1
        assert 'virtual' in result.issues[0].message

    def test_all_valid_types_accepted(self):
        """Every type in VALID_CHANNEL_TYPES should pass."""
        for ct in VALID_CHANNEL_TYPES:
            project = {'channels': {'ch': {'channel_type': ct}}}
            result = ValidationResult(file_path='test')
            validate_channel_types(project, result)
            assert result.error_count == 0, f"Type {ct} incorrectly rejected"

# ===== Duplicate ID Validation =====

class TestValidateDuplicateIds:
    def test_no_duplicates(self):
        project = _base_project()
        result = ValidationResult(file_path='test')
        validate_duplicate_ids(project, result)
        assert result.error_count == 0

    def test_duplicate_script_ids(self):
        project = _base_project()
        project['scripts']['pythonScripts'] = [
            {'id': 'script-1', 'name': 'Script 1', 'code': ''},
            {'id': 'script-1', 'name': 'Script 2', 'code': ''},
        ]
        result = ValidationResult(file_path='test')
        validate_duplicate_ids(project, result)
        assert result.error_count == 1

    def test_same_id_across_sections(self):
        project = _base_project()
        project['scripts']['calculatedParams'] = [{'id': 'dup'}]
        project['scripts']['sequences'] = [{'id': 'dup'}]
        result = ValidationResult(file_path='test')
        validate_duplicate_ids(project, result)
        assert result.error_count == 1

# ===== Port Conflict Validation =====

class TestValidatePortConflicts:
    def test_no_conflicts(self):
        project = _base_project()
        result = ValidationResult(file_path='test')
        validate_port_conflicts(project, result)
        assert result.warning_count == 0

    def test_conflict_detected(self):
        project = _base_project()
        project['channels']['DuplicatePort'] = {
            'name': 'DuplicatePort',
            'channel_type': 'voltage_input',
            'physical_channel': 'Mod1/ai0',  # Same as TT_101
        }
        result = ValidationResult(file_path='test')
        validate_port_conflicts(project, result)
        assert result.warning_count == 1

# ===== Alarm Validation =====

class TestValidateAlarmChannelRefs:
    def test_valid_alarm_dict(self):
        project = _base_project()
        project['safety']['alarmConfigs'] = {'TT_101': {'enabled': True}}
        result = ValidationResult(file_path='test')
        validate_alarm_channel_refs(project, result)
        assert result.error_count == 0

    def test_broken_alarm_dict(self):
        project = _base_project()
        project['safety']['alarmConfigs'] = {'NonExistent': {'enabled': True}}
        result = ValidationResult(file_path='test')
        validate_alarm_channel_refs(project, result)
        assert result.error_count == 1

    def test_valid_alarm_list(self):
        project = _base_project()
        project['safety']['alarmConfigs'] = [{'channel': 'TT_101', 'id': 'alarm-1'}]
        result = ValidationResult(file_path='test')
        validate_alarm_channel_refs(project, result)
        assert result.error_count == 0

    def test_broken_alarm_list(self):
        project = _base_project()
        project['safety']['alarmConfigs'] = [{'channel': 'Ghost', 'id': 'alarm-1'}]
        result = ValidationResult(file_path='test')
        validate_alarm_channel_refs(project, result)
        assert result.error_count == 1

# ===== Interlock Validation =====

class TestValidateInterlockChannelRefs:
    def test_valid_interlock(self):
        project = _base_project()
        project['safety']['interlocks'] = [{
            'id': 'il-1', 'channelId': 'TT_101',
            'actions': [{'channelId': 'ValveOut'}],
        }]
        result = ValidationResult(file_path='test')
        validate_interlock_channel_refs(project, result)
        assert result.error_count == 0

    def test_broken_interlock_channel(self):
        project = _base_project()
        project['safety']['interlocks'] = [{
            'id': 'il-1', 'channelId': 'NonExistent', 'actions': [],
        }]
        result = ValidationResult(file_path='test')
        validate_interlock_channel_refs(project, result)
        assert result.error_count == 1

    def test_broken_interlock_action(self):
        project = _base_project()
        project['safety']['interlocks'] = [{
            'id': 'il-1', 'channelId': 'TT_101',
            'actions': [{'channelId': 'NonExistent'}],
        }]
        result = ValidationResult(file_path='test')
        validate_interlock_channel_refs(project, result)
        assert result.warning_count == 1

# ===== Recording Validation =====

class TestValidateRecordingChannelRefs:
    def test_valid_channels(self):
        project = _base_project()
        project['recording']['selectedChannels'] = ['TT_101', 'FT_201']
        result = ValidationResult(file_path='test')
        validate_recording_channel_refs(project, result)
        assert result.warning_count == 0

    def test_broken_channel(self):
        project = _base_project()
        project['recording']['selectedChannels'] = ['TT_101', 'Deleted_Channel']
        result = ValidationResult(file_path='test')
        validate_recording_channel_refs(project, result)
        assert result.warning_count == 1

# ===== PID Validation =====

class TestValidatePidChannelRefs:
    def test_valid_pid(self):
        project = _base_project()
        project['pidControllers'] = {
            'pid-1': {
                'inputChannel': 'TT_101',
                'outputChannel': 'ValveOut',
            }
        }
        result = ValidationResult(file_path='test')
        validate_pid_channel_refs(project, result)
        assert result.error_count == 0

    def test_broken_pid_input(self):
        project = _base_project()
        project['pidControllers'] = {
            'pid-1': {
                'inputChannel': 'Ghost',
                'outputChannel': 'ValveOut',
            }
        }
        result = ValidationResult(file_path='test')
        validate_pid_channel_refs(project, result)
        assert result.error_count == 1

    def test_no_pid_section(self):
        project = _base_project()
        result = ValidationResult(file_path='test')
        validate_pid_channel_refs(project, result)
        assert result.error_count == 0

# ===== Script Tag Ref Validation =====

class TestValidateScriptTagRefs:
    def test_valid_script_refs(self):
        project = _base_project()
        project['scripts']['pythonScripts'] = [{
            'id': 's1', 'code': 'x = tags.TT_101\ny = tags["FT_201"]',
        }]
        result = ValidationResult(file_path='test')
        validate_script_tag_refs(project, result)
        assert result.warning_count == 0

    def test_broken_script_ref(self):
        project = _base_project()
        project['scripts']['pythonScripts'] = [{
            'id': 's1', 'code': 'x = tags.NonExistent',
        }]
        result = ValidationResult(file_path='test')
        validate_script_tag_refs(project, result)
        assert result.warning_count == 1

    def test_empty_code_ok(self):
        project = _base_project()
        project['scripts']['pythonScripts'] = [{'id': 's1', 'code': ''}]
        result = ValidationResult(file_path='test')
        validate_script_tag_refs(project, result)
        assert result.warning_count == 0

    def test_output_ref_to_unknown_channel(self):
        project = _base_project()
        project['scripts']['pythonScripts'] = [{
            'id': 's1', 'code': 'outputs.set("UnknownOut", 42)',
        }]
        result = ValidationResult(file_path='test')
        validate_script_tag_refs(project, result)
        assert result.info_count == 1

# ===== Simulation Config Validation =====

class TestValidateSimulationConfig:
    def test_valid_config(self):
        project = _base_project()
        project['simulation'] = {
            'processModels': [{
                'type': 'thermalMass',
                'name': 'Furnace',
                'inputChannels': {'heater_power': 'ValveOut'},
                'outputChannels': {'temperature': 'TT_101'},
                'params': {},
            }]
        }
        result = ValidationResult(file_path='test')
        validate_simulation_config(project, result)
        assert result.error_count == 0

    def test_unknown_model_type(self):
        project = _base_project()
        project['simulation'] = {
            'processModels': [{'type': 'fakeModel', 'name': 'Bad'}]
        }
        result = ValidationResult(file_path='test')
        validate_simulation_config(project, result)
        assert result.error_count == 1

    def test_broken_channel_ref(self):
        project = _base_project()
        project['simulation'] = {
            'processModels': [{
                'type': 'thermalMass',
                'name': 'Furnace',
                'inputChannels': {'heater_power': 'NonExistent'},
                'outputChannels': {'temperature': 'TT_101'},
            }]
        }
        result = ValidationResult(file_path='test')
        validate_simulation_config(project, result)
        assert result.error_count == 1

    def test_no_simulation_section(self):
        project = _base_project()
        result = ValidationResult(file_path='test')
        validate_simulation_config(project, result)
        assert result.error_count == 0

# ===== Safety Action Validation =====

class TestValidateSafetyActionRefs:
    def test_valid_action(self):
        project = _base_project()
        project['safety']['safetyActions'] = {
            'close-valve': {'channelId': 'ValveOut'}
        }
        result = ValidationResult(file_path='test')
        validate_safety_action_refs(project, result)
        assert result.error_count == 0

    def test_broken_action_ref(self):
        project = _base_project()
        project['safety']['safetyActions'] = {
            'close-valve': {'channelId': 'NoSuchChannel'}
        }
        result = ValidationResult(file_path='test')
        validate_safety_action_refs(project, result)
        assert result.error_count == 1

# ===== Full Validator Tests =====

class TestValidateProject:
    def test_clean_project(self):
        project = _base_project()
        result = validate_project(project, 'test.json')
        assert not result.has_errors

    def test_multiple_issues(self):
        project = _base_project()
        project['channels']['Bad'] = {'channel_type': 'virtual'}
        project['safety']['alarmConfigs'] = {'Ghost': {}}
        result = validate_project(project, 'test.json')
        assert result.error_count >= 2

    def test_sorted_by_severity(self):
        project = _base_project()
        project['channels']['Bad'] = {'channel_type': 'virtual'}
        project['recording']['selectedChannels'] = ['Gone']
        result = validate_project(project, 'test.json')
        # Errors should come before warnings
        found_warning = False
        for issue in result.issues:
            if issue.severity == Severity.WARNING:
                found_warning = True
            if found_warning and issue.severity == Severity.ERROR:
                pytest.fail("ERROR after WARNING — not sorted")

    def test_to_dict(self):
        project = _base_project()
        result = validate_project(project, 'test.json')
        d = result.to_dict()
        assert d['file'] == 'test.json'
        assert d['errors'] == 0
        assert isinstance(d['issues'], list)

# ===== File/Directory Validation =====

class TestValidateFile:
    def test_valid_json_file(self, tmp_path):
        project = _base_project()
        f = tmp_path / 'test.json'
        f.write_text(json.dumps(project), encoding='utf-8')
        result = validate_file(str(f))
        assert not result.has_errors

    def test_invalid_json(self, tmp_path):
        f = tmp_path / 'bad.json'
        f.write_text('not json{{{', encoding='utf-8')
        result = validate_file(str(f))
        assert result.has_errors
        assert any('Invalid JSON' in i.message for i in result.issues)

    def test_missing_file(self):
        result = validate_file('/nonexistent/path.json')
        assert result.has_errors

    def test_directory_validation(self, tmp_path):
        # Create 2 project files
        for i in range(2):
            project = _base_project()
            project['name'] = f'Project {i}'
            f = tmp_path / f'project_{i}.json'
            f.write_text(json.dumps(project), encoding='utf-8')

        results = validate_directory(str(tmp_path))
        assert len(results) == 2
        for r in results:
            assert not r.has_errors

# ===== Real Project File Validation =====

class TestRealProjects:
    """Run the validator against actual project files in the repo."""

    @pytest.fixture
    def projects_dir(self):
        d = os.path.join(os.path.dirname(__file__), '..', 'config', 'projects')
        if os.path.isdir(d):
            return d
        pytest.skip("config/projects directory not found")

    def test_real_projects_parse(self, projects_dir):
        """All real project files should be valid JSON."""
        results = validate_directory(projects_dir)
        assert len(results) > 0
        for r in results:
            json_errors = [i for i in r.issues if i.rule == 'json_parse']
            assert len(json_errors) == 0, f"JSON parse error in {r.file_path}"

    def test_real_projects_valid_channel_types(self, projects_dir):
        """All channels in real projects should have valid types (except test files)."""
        results = validate_directory(projects_dir)
        for r in results:
            # Skip intentional validation test files
            if 'Validation_Error' in os.path.basename(r.file_path):
                continue
            type_errors = [i for i in r.issues if i.rule == 'channel_type']
            assert len(type_errors) == 0, f"Invalid channel type in {r.file_path}: {type_errors}"
