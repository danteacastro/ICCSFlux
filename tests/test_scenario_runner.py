"""
Tests for the Scenario Test Runner.

Tests scenario parsing, step execution (with mocked MQTT), topic matching,
JUnit XML output, and result data structures.
"""

import json
import math
import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from run_scenario import (
    Scenario, ScenarioStep, ScenarioResult, StepResult,
    ScenarioMQTTClient, _execute_step, _topic_matches,
    COMPARE_OPS, results_to_junit_xml,
)


# ===== Scenario Data Model Tests =====

class TestScenarioStep:
    def test_from_dict(self):
        s = ScenarioStep.from_dict({'action': 'wait', 'seconds': 2})
        assert s.action == 'wait'
        assert s.params == {'seconds': 2}

    def test_from_dict_no_params(self):
        s = ScenarioStep.from_dict({'action': 'start_acquisition'})
        assert s.action == 'start_acquisition'
        assert s.params == {}


class TestScenario:
    def test_from_dict(self):
        d = {
            'name': 'Test',
            'description': 'A test',
            'steps': [
                {'action': 'wait', 'seconds': 1},
                {'action': 'start_acquisition'},
            ],
            'timeout': 15,
        }
        s = Scenario.from_dict(d)
        assert s.name == 'Test'
        assert len(s.steps) == 2
        assert s.timeout == 15

    def test_from_dict_defaults(self):
        s = Scenario.from_dict({})
        assert s.name == 'Unnamed'
        assert s.timeout == 30.0
        assert s.steps == []

    def test_from_file(self, tmp_path):
        d = {
            'name': 'FileTest',
            'steps': [{'action': 'wait', 'seconds': 0.1}],
        }
        f = tmp_path / 'test.json'
        f.write_text(json.dumps(d), encoding='utf-8')
        s = Scenario.from_file(str(f))
        assert s.name == 'FileTest'
        assert len(s.steps) == 1


class TestScenarioResult:
    def test_success(self):
        r = ScenarioResult(scenario_name='Test', success=True)
        assert r.success
        assert r.failed_steps == []

    def test_failed_steps(self):
        r = ScenarioResult(scenario_name='Test', success=False)
        r.step_results = [
            StepResult(0, 'wait', True),
            StepResult(1, 'assert_value', False, message='failed'),
        ]
        assert len(r.failed_steps) == 1


# ===== Compare Operators =====

class TestCompareOps:
    def test_greater_than(self):
        assert COMPARE_OPS['>'](10, 5)
        assert not COMPARE_OPS['>'](5, 10)

    def test_less_than(self):
        assert COMPARE_OPS['<'](5, 10)
        assert not COMPARE_OPS['<'](10, 5)

    def test_equal(self):
        assert COMPARE_OPS['=='](5, 5)
        assert not COMPARE_OPS['=='](5, 6)

    def test_not_equal(self):
        assert COMPARE_OPS['!='](5, 6)
        assert not COMPARE_OPS['!='](5, 5)

    def test_gte(self):
        assert COMPARE_OPS['>='](5, 5)
        assert COMPARE_OPS['>='](6, 5)

    def test_lte(self):
        assert COMPARE_OPS['<='](5, 5)
        assert COMPARE_OPS['<='](4, 5)

    def test_approx(self):
        assert COMPARE_OPS['~='](100, 100.1)
        assert not COMPARE_OPS['~='](100, 200)


# ===== Topic Matching =====

class TestTopicMatching:
    def test_exact(self):
        assert _topic_matches('a/b/c', 'a/b/c')

    def test_no_match(self):
        assert not _topic_matches('a/b/c', 'a/b/d')

    def test_wildcard_hash(self):
        assert _topic_matches('a/b/c', '#')

    def test_wildcard_hash_suffix(self):
        assert _topic_matches('a/b/c', 'a/#')

    def test_wildcard_plus(self):
        assert _topic_matches('a/b/c', 'a/+/c')

    def test_wildcard_plus_no_match(self):
        assert not _topic_matches('a/b/c', 'a/+/d')

    def test_different_lengths(self):
        assert not _topic_matches('a/b', 'a/b/c')
        assert not _topic_matches('a/b/c', 'a/b')

    def test_hash_at_mid(self):
        assert _topic_matches('a/b/c/d', 'a/b/#')


# ===== Mock MQTT Client for Step Execution =====

class MockScenarioClient:
    """Mock client that doesn't need a real MQTT broker."""

    def __init__(self):
        self._channel_values = {}
        self._alarm_states = {}
        self._system_state = 'STOPPED'
        self._recording_state = 'stopped'
        self._received_messages = []
        self._published = []

    def publish(self, topic, payload, qos=1):
        self._published.append({'topic': topic, 'payload': payload})

    def get_channel_value(self, channel):
        return self._channel_values.get(channel)

    def get_alarm_state(self, alarm):
        return self._alarm_states.get(alarm)

    def get_system_state(self):
        return self._system_state

    def get_recording_state(self):
        return self._recording_state

    def wait_for_condition(self, condition, timeout=10.0, poll_interval=0.01):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(poll_interval)
        return False


# ===== Step Execution Tests =====

class TestExecuteStep:
    def test_wait(self):
        client = MockScenarioClient()
        step = ScenarioStep('wait', {'seconds': 0.05})
        result = _execute_step(client, step)
        assert result.success
        assert result.duration >= 0.04

    def test_inject_value(self):
        client = MockScenarioClient()
        step = ScenarioStep('inject_value', {'channel': 'TT_101', 'value': 500})
        result = _execute_step(client, step)
        assert result.success
        assert client._channel_values['TT_101'] == 500.0

    def test_assert_value_pass(self):
        client = MockScenarioClient()
        client._channel_values['TT_101'] = 100.0
        step = ScenarioStep('assert_value', {
            'channel': 'TT_101', 'operator': '>', 'value': 50, 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert result.success

    def test_assert_value_fail(self):
        client = MockScenarioClient()
        client._channel_values['TT_101'] = 30.0
        step = ScenarioStep('assert_value', {
            'channel': 'TT_101', 'operator': '>', 'value': 50, 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert not result.success

    def test_assert_value_missing_channel(self):
        client = MockScenarioClient()
        step = ScenarioStep('assert_value', {
            'channel': 'NonExistent', 'operator': '==', 'value': 0, 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert not result.success
        assert 'not found' in result.message

    def test_assert_value_unknown_operator(self):
        client = MockScenarioClient()
        step = ScenarioStep('assert_value', {
            'channel': 'TT_101', 'operator': '??', 'value': 0, 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert not result.success

    def test_assert_alarm_pass(self):
        client = MockScenarioClient()
        client._alarm_states['HighTemp'] = 'active'
        step = ScenarioStep('assert_alarm', {
            'alarm': 'HighTemp', 'state': 'active', 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert result.success

    def test_assert_alarm_fail(self):
        client = MockScenarioClient()
        client._alarm_states['HighTemp'] = 'cleared'
        step = ScenarioStep('assert_alarm', {
            'alarm': 'HighTemp', 'state': 'active', 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert not result.success

    def test_start_acquisition_pass(self):
        client = MockScenarioClient()
        client._system_state = 'RUNNING'
        step = ScenarioStep('start_acquisition', {'timeout': 0.1})
        result = _execute_step(client, step)
        assert result.success

    def test_start_acquisition_fail(self):
        client = MockScenarioClient()
        client._system_state = 'STOPPED'
        step = ScenarioStep('start_acquisition', {'timeout': 0.1})
        result = _execute_step(client, step)
        assert not result.success

    def test_stop_acquisition_pass(self):
        client = MockScenarioClient()
        client._system_state = 'STOPPED'
        step = ScenarioStep('stop_acquisition', {'timeout': 0.1})
        result = _execute_step(client, step)
        assert result.success

    def test_assert_recording_pass(self):
        client = MockScenarioClient()
        client._recording_state = 'running'
        step = ScenarioStep('assert_recording', {
            'state': 'running', 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert result.success

    def test_set_output(self):
        client = MockScenarioClient()
        step = ScenarioStep('set_output', {'channel': 'Valve', 'value': 50})
        result = _execute_step(client, step)
        assert result.success
        assert len(client._published) == 1

    def test_run_script(self):
        client = MockScenarioClient()
        step = ScenarioStep('run_script', {'script': 'my-script'})
        result = _execute_step(client, step)
        assert result.success

    def test_start_recording(self):
        client = MockScenarioClient()
        step = ScenarioStep('start_recording', {})
        result = _execute_step(client, step)
        assert result.success

    def test_stop_recording(self):
        client = MockScenarioClient()
        step = ScenarioStep('stop_recording', {})
        result = _execute_step(client, step)
        assert result.success

    def test_publish(self):
        client = MockScenarioClient()
        step = ScenarioStep('publish', {'topic': 'test/data', 'payload': 'hello'})
        result = _execute_step(client, step)
        assert result.success

    def test_unknown_action(self):
        client = MockScenarioClient()
        step = ScenarioStep('unknown_action', {})
        result = _execute_step(client, step)
        assert not result.success

    def test_assert_mqtt_pass(self):
        client = MockScenarioClient()
        # Pre-populate a message
        client._received_messages = [
            {'topic': 'test/data', 'payload': {'value': 42}, 'ts': time.time() + 0.01}
        ]
        step = ScenarioStep('assert_mqtt', {
            'topic': 'test/data', 'timeout': 0.5,
        })
        result = _execute_step(client, step)
        assert result.success

    def test_assert_mqtt_with_contains(self):
        client = MockScenarioClient()
        client._received_messages = [
            {'topic': 'test/data', 'payload': {'status': 'ok'}, 'ts': time.time() + 0.01}
        ]
        step = ScenarioStep('assert_mqtt', {
            'topic': 'test/data', 'contains': 'ok', 'timeout': 0.5,
        })
        result = _execute_step(client, step)
        assert result.success

    def test_assert_mqtt_timeout(self):
        client = MockScenarioClient()
        step = ScenarioStep('assert_mqtt', {
            'topic': 'test/data', 'timeout': 0.1,
        })
        result = _execute_step(client, step)
        assert not result.success


# ===== JUnit XML Tests =====

class TestJunitXml:
    def test_empty_results(self):
        xml = results_to_junit_xml([])
        assert '<?xml' in xml
        assert 'testsuites' in xml

    def test_passing_result(self):
        r = ScenarioResult('PassTest', success=True, duration=1.0)
        xml = results_to_junit_xml([r])
        assert 'PassTest' in xml
        # Should not have a <failure> element (but failures="0" attribute is fine)
        assert '<failure' not in xml

    def test_failing_result(self):
        r = ScenarioResult('FailTest', success=False, error='Something broke', duration=2.0)
        r.step_results = [
            StepResult(0, 'wait', True, 'ok', 0.1),
            StepResult(1, 'assert_value', False, 'value too low', 0.5),
        ]
        xml = results_to_junit_xml([r])
        assert 'FailTest' in xml
        assert 'failure' in xml
        assert 'Something broke' in xml

    def test_multiple_results(self):
        results = [
            ScenarioResult('Test1', success=True, duration=1.0),
            ScenarioResult('Test2', success=False, error='fail', duration=2.0),
        ]
        xml = results_to_junit_xml(results)
        assert 'tests="2"' in xml
        assert 'failures="1"' in xml


# ===== ScenarioMQTTClient Unit Tests =====

class TestScenarioMQTTClientUnit:
    def test_initial_state(self):
        c = ScenarioMQTTClient('localhost', 1883)
        assert c.get_system_state() == 'unknown'
        assert c.get_recording_state() == 'stopped'
        assert c.get_channel_value('anything') is None
        assert c.get_alarm_state('any') is None

    def test_channel_value_cache(self):
        c = ScenarioMQTTClient('localhost', 1883)
        c._channel_values['TT_101'] = 42.5
        assert c.get_channel_value('TT_101') == 42.5

    def test_alarm_state_cache(self):
        c = ScenarioMQTTClient('localhost', 1883)
        c._alarm_states['HighTemp'] = 'active'
        assert c.get_alarm_state('HighTemp') == 'active'


# ===== Scenario File Loading from Real Files =====

class TestRealScenarioFiles:
    @pytest.fixture
    def scenarios_dir(self):
        d = os.path.join(os.path.dirname(__file__), '..', 'scenarios')
        if os.path.isdir(d):
            return d
        pytest.skip("scenarios directory not found")

    def test_example_scenario_parses(self, scenarios_dir):
        """All .json files in scenarios/ should parse as valid scenarios."""
        import glob
        files = glob.glob(os.path.join(scenarios_dir, '*.json'))
        assert len(files) > 0
        for f in files:
            s = Scenario.from_file(f)
            assert s.name
            assert len(s.steps) > 0
